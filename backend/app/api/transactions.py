"""Transactions: listing with filters, manual entry, categorization, splits and transfers."""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api import finance_schemas as schemas
from app.api.categories import get_category
from app.deps import CurrentMember, DbDep, MemberContext
from app.finance import transfers as transfer_logic
from app.finance.access import get_visible_account, get_visible_transaction, visible_transaction_clause
from app.finance.dedupe import random_dedupe_hash
from app.finance.rules import apply_rule_to_similar, apply_rules, assign_category, learn_from_correction
from app.models import (
    Category,
    CategoryKind,
    CategorySource,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionTag,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])

MAX_SPLITS = 50


# ---------------------------------------------------------------- serialization


def _build[T: schemas.TransactionOut](
    cls: type[T], tx: Transaction, visible_peers: set[uuid.UUID], **extra: Any
) -> T:
    peer_id = tx.transfer_peer_id if tx.transfer_peer_id in visible_peers else None
    in_transfer_category = tx.category is not None and tx.category.kind is CategoryKind.TRANSFER
    return cls(
        id=tx.id,
        account_id=tx.account_id,
        booking_date=tx.booking_date,
        value_date=tx.value_date,
        amount_cents=tx.amount_cents,
        currency=tx.currency,
        counterparty_name=tx.counterparty_name,
        counterparty_iban=tx.counterparty_iban,
        purpose=tx.purpose,
        booking_text=tx.booking_text,
        category_id=tx.category_id,
        category_source=tx.category_source,
        rule_id=tx.rule_id,
        transfer_peer_id=peer_id,
        is_transfer=tx.transfer_peer_id is not None or in_transfer_category,
        note=tx.note,
        import_run_id=tx.import_run_id,
        created_at=tx.created_at,
        splits=[schemas.SplitOut.model_validate(split) for split in tx.splits],
        tags=[schemas.TagOut.model_validate(tag) for tag in tx.tags],
        **extra,
    )


def _visible_peers(db: Session, member: MemberContext, txs: Sequence[Transaction]) -> set[uuid.UUID]:
    """Peer ids the caller may see; a transfer to a hidden account is reported as a bare flag."""
    peer_ids = {tx.transfer_peer_id for tx in txs if tx.transfer_peer_id is not None}
    if not peer_ids:
        return set()
    return set(
        db.scalars(
            select(Transaction.id).where(Transaction.id.in_(peer_ids), visible_transaction_clause(member))
        )
    )


def _out(db: Session, member: MemberContext, txs: Sequence[Transaction]) -> list[schemas.TransactionOut]:
    peers = _visible_peers(db, member, txs)
    return [_build(schemas.TransactionOut, tx, peers) for tx in txs]


def _detail(db: Session, member: MemberContext, tx: Transaction) -> schemas.TransactionDetail:
    return _build(schemas.TransactionDetail, tx, _visible_peers(db, member, [tx]), raw=tx.raw)


def _resolve_tags(db: Session, member: MemberContext, tag_ids: list[uuid.UUID]) -> list[Tag]:
    wanted = set(tag_ids)
    if not wanted:
        return []
    tags = list(db.scalars(select(Tag).where(Tag.id.in_(wanted), Tag.household_id == member.household.id)))
    if len(tags) != len(wanted):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    return sorted(tags, key=lambda tag: tag.name)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _has_splits() -> ColumnElement[bool]:
    return exists().where(TransactionSplit.transaction_id == Transaction.id)


# ---------------------------------------------------------------- list and detail


@router.get("")
def list_transactions(
    member: CurrentMember,
    db: DbDep,
    account_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    category_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    uncategorized: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    amount_min: int | None = None,
    amount_max: int | None = None,
    direction: Literal["in", "out"] | None = None,
    tag_id: uuid.UUID | None = None,
    transfers: Literal["include", "exclude", "only"] = "include",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.TransactionList:
    where: list[ColumnElement[bool]] = [visible_transaction_clause(member)]
    if account_id:
        where.append(Transaction.account_id.in_(account_id))
    if category_id:
        # A top-level category also matches its children.
        matching = select(Category.id).where(
            Category.household_id == member.household.id,
            or_(Category.id.in_(category_id), Category.parent_id.in_(category_id)),
        )
        in_split = exists().where(
            TransactionSplit.transaction_id == Transaction.id, TransactionSplit.category_id.in_(matching)
        )
        where.append(or_(and_(~_has_splits(), Transaction.category_id.in_(matching)), in_split))
    if uncategorized:
        where.append(and_(Transaction.category_id.is_(None), ~_has_splits()))
    if date_from is not None:
        where.append(Transaction.booking_date >= date_from)
    if date_to is not None:
        where.append(Transaction.booking_date <= date_to)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        where.append(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (
                        Transaction.counterparty_name,
                        Transaction.purpose,
                        Transaction.booking_text,
                        Transaction.note,
                    )
                )
            )
        )
    if amount_min is not None:
        where.append(Transaction.amount_cents >= amount_min)
    if amount_max is not None:
        where.append(Transaction.amount_cents <= amount_max)
    if direction == "in":
        where.append(Transaction.amount_cents > 0)
    elif direction == "out":
        where.append(Transaction.amount_cents < 0)
    if tag_id is not None:
        where.append(
            exists().where(TransactionTag.transaction_id == Transaction.id, TransactionTag.tag_id == tag_id)
        )
    if transfers != "include":
        # EXISTS keeps the predicate two-valued, so NOT works for uncategorized rows too.
        in_transfer_category = exists().where(
            Category.id == Transaction.category_id, Category.kind == CategoryKind.TRANSFER
        )
        is_transfer = or_(Transaction.transfer_peer_id.is_not(None), in_transfer_category)
        where.append(is_transfer if transfers == "only" else ~is_transfer)

    total = db.scalar(select(func.count()).select_from(Transaction).where(*where)) or 0
    rows = db.scalars(
        select(Transaction)
        .where(*where)
        .order_by(Transaction.booking_date.desc(), Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
        .options(
            selectinload(Transaction.splits),
            selectinload(Transaction.tags),
            selectinload(Transaction.category),
        )
    ).all()
    return schemas.TransactionList(items=_out(db, member, rows), total=int(total))


@router.get("/{transaction_id}")
def get_transaction(transaction_id: uuid.UUID, member: CurrentMember, db: DbDep) -> schemas.TransactionDetail:
    return _detail(db, member, get_visible_transaction(db, member, transaction_id))


# ---------------------------------------------------------------- create, update, delete


@router.post("", status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: schemas.TransactionCreate, member: CurrentMember, db: DbDep
) -> schemas.TransactionDetail:
    account = get_visible_account(db, member, body.account_id)
    category = get_category(db, member, body.category_id) if body.category_id else None
    tags = _resolve_tags(db, member, body.tag_ids)
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=member.household.id,
        account_id=account.id,
        booking_date=body.booking_date,
        value_date=body.value_date,
        amount_cents=body.amount_cents,
        currency=account.currency,
        counterparty_name=body.counterparty_name or None,
        counterparty_iban=body.counterparty_iban,
        purpose=body.purpose,
        booking_text=body.booking_text or None,
        note=body.note,
        dedupe_hash=random_dedupe_hash(),
    )
    tx.tags = tags
    db.add(tx)
    db.flush()
    if category is not None:
        assign_category(db, tx, category.id, CategorySource.MANUAL, None)
    else:
        apply_rules(db, member.household.id, [tx])
    transfer_logic.detect_transfers(db, member.household.id, [tx], member=member)
    db.flush()
    db.refresh(tx)  # server defaults such as created_at
    return _detail(db, member, tx)


@router.patch("/{transaction_id}")
def update_transaction(
    transaction_id: uuid.UUID, body: schemas.TransactionUpdate, member: CurrentMember, db: DbDep
) -> schemas.TransactionUpdated:
    tx = get_visible_transaction(db, member, transaction_id)
    fields = body.model_fields_set
    similar_updated = 0
    if "note" in fields:
        tx.note = body.note or None
    if body.tag_ids is not None:
        tx.tags = _resolve_tags(db, member, body.tag_ids)
    if "category_id" in fields:
        if body.category_id is None:
            assign_category(db, tx, None, None, None)
        else:
            category = get_category(db, member, body.category_id)
            assign_category(db, tx, category.id, CategorySource.MANUAL, None)
            if body.learn:
                rule = learn_from_correction(db, member, tx, category.id)
                if rule is not None and body.apply_to_similar:
                    similar_updated = apply_rule_to_similar(db, member, rule, tx.id)
    db.flush()
    detail = _detail(db, member, tx)
    return schemas.TransactionUpdated(**detail.model_dump(), similar_updated=similar_updated)


@router.put("/{transaction_id}/splits")
def replace_splits(
    transaction_id: uuid.UUID, body: list[schemas.SplitIn], member: CurrentMember, db: DbDep
) -> schemas.TransactionDetail:
    tx = get_visible_transaction(db, member, transaction_id)
    if len(body) == 1 or len(body) > MAX_SPLITS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Provide 2 to {MAX_SPLITS} parts, or none to clear"
        )
    if body and sum(part.amount_cents for part in body) != tx.amount_cents:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The parts must add up to the transaction amount"
        )
    for category_id in {part.category_id for part in body if part.category_id is not None}:
        get_category(db, member, category_id)
    tx.splits = [
        TransactionSplit(
            id=uuid.uuid4(),
            position=index,
            amount_cents=part.amount_cents,
            category_id=part.category_id,
            note=part.note or None,
        )
        for index, part in enumerate(body)
    ]
    db.flush()
    return _detail(db, member, tx)


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(transaction_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    db.delete(get_visible_transaction(db, member, transaction_id))


# ---------------------------------------------------------------- transfers


@router.post("/{transaction_id}/transfer")
def pair_transfer(
    transaction_id: uuid.UUID, body: schemas.TransferRequest, member: CurrentMember, db: DbDep
) -> schemas.TransactionDetail:
    tx = get_visible_transaction(db, member, transaction_id)
    peer = get_visible_transaction(db, member, body.peer_id)
    transfer_logic.pair(db, member, tx, peer)
    return _detail(db, member, tx)


@router.delete("/{transaction_id}/transfer", status_code=status.HTTP_204_NO_CONTENT)
def unpair_transfer(transaction_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    transfer_logic.unpair(db, member, get_visible_transaction(db, member, transaction_id))


@router.get("/{transaction_id}/transfer-candidates")
def transfer_candidates(
    transaction_id: uuid.UUID, member: CurrentMember, db: DbDep
) -> list[schemas.TransactionOut]:
    tx = get_visible_transaction(db, member, transaction_id)
    candidates = transfer_logic.find_candidates(db, member, tx)
    return _out(db, member, candidates)
