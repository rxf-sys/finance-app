"""Detecting and managing transfers between a household's own accounts."""

import uuid
from collections.abc import Iterable
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session, selectinload

from app.deps import MemberContext
from app.finance.access import get_visible_transaction, visible_transaction_clause
from app.models import Account, Transaction

AUTO_WINDOW_DAYS = 3


def _candidate_query(
    tx: Transaction, window_days: int, visible: ColumnElement[bool] | None
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [
        Transaction.household_id == tx.household_id,
        Transaction.account_id != tx.account_id,
        Transaction.transfer_peer_id.is_(None),
        Transaction.id != tx.id,
        Transaction.amount_cents == -tx.amount_cents,
        Transaction.booking_date >= tx.booking_date - timedelta(days=window_days),
        Transaction.booking_date <= tx.booking_date + timedelta(days=window_days),
    ]
    if visible is not None:
        clauses.append(visible)
    return clauses


def detect_transfers(
    db: Session,
    household_id: uuid.UUID,
    transactions: Iterable[Transaction],
    *,
    member: MemberContext | None = None,
) -> int:
    """Pair each unpaired transaction with its unique counterpart; return the number of pairs made.

    Without `member` the whole household is searched (background jobs). With a member, both sides
    must sit on accounts that member can see, so a private account is never paired on their behalf.
    """
    visible = visible_transaction_clause(member) if member is not None else None
    pairs = 0
    for tx in transactions:
        if tx.transfer_peer_id is not None or tx.household_id != household_id:
            continue
        if (
            visible is not None
            and db.scalar(select(Transaction.id).where(Transaction.id == tx.id, visible)) is None
        ):
            continue
        own_account = db.get(Account, tx.account_id)
        if own_account is None:
            continue
        iban_match: list[ColumnElement[bool]] = []
        if tx.counterparty_iban:
            iban_match.append(Account.iban == tx.counterparty_iban)
        if own_account.iban:
            iban_match.append(Transaction.counterparty_iban == own_account.iban)
        if not iban_match:
            continue
        candidates = db.scalars(
            select(Transaction)
            .join(Account, Account.id == Transaction.account_id)
            .where(*_candidate_query(tx, AUTO_WINDOW_DAYS, visible), or_(*iban_match))
            .limit(2)
        ).all()
        if len(candidates) == 1:
            _link(candidates[0], tx)
            db.flush()
            pairs += 1
    return pairs


def _link(a: Transaction, b: Transaction) -> None:
    a.transfer_peer_id = b.id
    b.transfer_peer_id = a.id


def pair(db: Session, member: MemberContext, a: Transaction, b: Transaction) -> None:
    """Manually pair two transactions after checking visibility and consistency."""
    a = get_visible_transaction(db, member, a.id)
    b = get_visible_transaction(db, member, b.id)
    if a.id == b.id or a.account_id == b.account_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A transfer needs two different accounts")
    if a.amount_cents != -b.amount_cents:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Transfer amounts must be opposite")
    if a.transfer_peer_id is not None or b.transfer_peer_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transaction is already part of a transfer")
    _link(a, b)
    db.flush()


def unpair(db: Session, member: MemberContext, tx: Transaction) -> None:
    """Remove the pairing; both sides must be visible, otherwise the pair is invisible to the caller."""
    tx = get_visible_transaction(db, member, tx.id)
    peer = None
    if tx.transfer_peer_id is not None:
        peer = db.scalar(
            select(Transaction).where(
                Transaction.id == tx.transfer_peer_id, visible_transaction_clause(member)
            )
        )
    if peer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction is not part of a transfer")
    tx.transfer_peer_id = None
    peer.transfer_peer_id = None
    db.flush()


def find_candidates(
    db: Session, member: MemberContext, tx: Transaction, window_days: int = 5
) -> list[Transaction]:
    """Unpaired opposite-amount transactions on other visible accounts near the booking date."""
    if tx.transfer_peer_id is not None:
        return []
    rows = db.scalars(
        select(Transaction)
        .where(*_candidate_query(tx, window_days, visible_transaction_clause(member)))
        .order_by(Transaction.booking_date.desc(), Transaction.id)
        .limit(50)
        .options(
            selectinload(Transaction.splits),
            selectinload(Transaction.tags),
            selectinload(Transaction.category),
        )
    ).all()
    return sorted(rows, key=lambda row: abs((row.booking_date - tx.booking_date).days))
