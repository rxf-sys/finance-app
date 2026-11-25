"""Contracts: recurring payments, detection suggestions, price changes and cancellation letters."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api import planning_schemas as schemas
from app.api.categories import get_category
from app.deps import CurrentMember, DbDep, MemberContext, SettingsDep
from app.finance.access import (
    get_visible_account,
    get_visible_contract,
    visible_account_clause,
    visible_contract_clause,
    visible_transaction_clause,
)
from app.finance.contracts import (
    MANUAL_PREFIX,
    add_interval,
    cancellation_deadline,
    detect_contracts,
    is_manual,
)
from app.finance.normalize import normalize_iban, normalize_text
from app.models import (
    Account,
    Contract,
    ContractInterval,
    ContractKind,
    ContractPriceChange,
    ContractStatus,
    Transaction,
)
from app.models.base import utcnow
from app.sessions import audit

router = APIRouter(prefix="/contracts", tags=["contracts"])

# Monthly equivalent as a fraction: a week is 52/12 months.
_MONTHLY_FACTOR = {
    ContractInterval.WEEKLY: (13, 3),
    ContractInterval.MONTHLY: (1, 1),
    ContractInterval.QUARTERLY: (1, 3),
    ContractInterval.HALF_YEARLY: (1, 6),
    ContractInterval.YEARLY: (1, 12),
}
DETAIL_TRANSACTIONS = 24


def monthly_amount(amount_cents: int, interval: ContractInterval) -> int:
    """Amount per month in cents, rounded half away from zero."""
    num, den = _MONTHLY_FACTOR[interval]
    scaled = abs(amount_cents) * num
    rounded = (scaled * 2 + den) // (den * 2)
    return rounded if amount_cents >= 0 else -rounded


# ---------------------------------------------------------------- serialization


def _price_change_out(change: ContractPriceChange) -> schemas.PriceChangeOut:
    return schemas.PriceChangeOut.model_validate(change, from_attributes=True)


def _payment_counts(db: Session, member: MemberContext, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Transaction.contract_id, func.count())
        .where(Transaction.contract_id.in_(ids), visible_transaction_clause(member))
        .group_by(Transaction.contract_id)
    )
    return {cid: int(n) for cid, n in rows if cid is not None}


def _out_one(contract: Contract, count: int) -> schemas.ContractOut:
    pending = [pc for pc in contract.price_changes if pc.acknowledged_at is None]
    return schemas.ContractOut(
        id=contract.id,
        name=contract.name,
        kind=contract.kind,
        status=contract.status,
        interval=contract.interval,
        account_id=contract.account_id,
        category_id=contract.category_id,
        expected_amount_cents=contract.expected_amount_cents,
        amount_tolerance_pct=contract.amount_tolerance_pct,
        monthly_amount_cents=monthly_amount(contract.expected_amount_cents, contract.interval),
        last_payment_date=contract.last_payment_date,
        next_due_date=contract.next_due_date,
        start_date=contract.start_date,
        min_term_end=contract.min_term_end,
        notice_period_days=contract.notice_period_days,
        cancellation_deadline=cancellation_deadline(contract),
        customer_number=contract.customer_number,
        note=contract.note,
        is_manual=is_manual(contract),
        confirmed_at=contract.confirmed_at,
        cancelled_at=contract.cancelled_at,
        created_at=contract.created_at,
        payments_count=count,
        unacknowledged_price_change=_price_change_out(pending[-1]) if pending else None,
    )


def _out(db: Session, member: MemberContext, contracts: Sequence[Contract]) -> list[schemas.ContractOut]:
    counts = _payment_counts(db, member, [c.id for c in contracts])
    return [_out_one(c, counts.get(c.id, 0)) for c in contracts]


def _single(db: Session, member: MemberContext, contract: Contract) -> schemas.ContractOut:
    db.refresh(contract, ["price_changes"])
    return _out(db, member, [contract])[0]


def _load(db: Session, member: MemberContext, contract_id: uuid.UUID) -> Contract:
    contract = get_visible_contract(db, member, contract_id)
    db.refresh(contract, ["price_changes"])
    return contract


# ---------------------------------------------------------------- list, summary, detect


@router.get("")
def list_contracts(
    member: CurrentMember,
    db: DbDep,
    status_filter: Annotated[ContractStatus | None, Query(alias="status")] = None,
    kind: ContractKind | None = None,
    account_id: uuid.UUID | None = None,
) -> list[schemas.ContractOut]:
    query = (
        select(Contract)
        .where(visible_contract_clause(member))
        .options(selectinload(Contract.price_changes))
        .order_by(Contract.name, Contract.id)
    )
    if status_filter is not None:
        query = query.where(Contract.status == status_filter)
    if kind is not None:
        query = query.where(Contract.kind == kind)
    if account_id is not None:
        query = query.where(Contract.account_id == account_id)
    return _out(db, member, db.scalars(query).all())


@router.get("/summary")
def contracts_summary(member: CurrentMember, db: DbDep) -> schemas.ContractSummary:
    contracts = db.scalars(select(Contract).where(visible_contract_clause(member))).all()
    cost: dict[ContractKind, int] = defaultdict(int)
    counts: dict[ContractKind, int] = defaultdict(int)
    income = 0
    detected = 0
    for contract in contracts:
        if contract.status is ContractStatus.DETECTED:
            detected += 1
        if contract.status is not ContractStatus.CONFIRMED:
            continue
        monthly = monthly_amount(contract.expected_amount_cents, contract.interval)
        if monthly < 0:
            cost[contract.kind] += -monthly
        else:
            income += monthly
        counts[contract.kind] += 1
    by_kind = [
        schemas.KindSummary(kind=kind, count=counts[kind], monthly_cost_cents=cost[kind])
        for kind in sorted(counts, key=lambda k: (-cost[k], k.value))
    ]
    return schemas.ContractSummary(
        monthly_cost_cents=sum(cost.values()),
        monthly_income_cents=income,
        by_kind=by_kind,
        detected_count=detected,
    )


@router.post("/detect")
def detect(member: CurrentMember, db: DbDep) -> list[schemas.ContractOut]:
    visible_ids = list(db.scalars(select(Account.id).where(visible_account_clause(member))))
    created = detect_contracts(db, member.household.id, account_ids=visible_ids)
    return _out(db, member, created)


# ---------------------------------------------------------------- create, read, update, delete


def _check_links(
    db: Session, member: MemberContext, account_id: uuid.UUID | None, category_id: uuid.UUID | None
) -> None:
    if account_id is not None:
        get_visible_account(db, member, account_id)
    if category_id is not None:
        get_category(db, member, category_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_contract(
    body: schemas.ContractCreate, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> schemas.ContractOut:
    _check_links(db, member, body.account_id, body.category_id)
    if body.expected_amount_cents == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Amount must not be zero")
    iban: str | None = None
    if body.counterparty_iban and body.counterparty_iban.strip():
        try:
            iban = normalize_iban(body.counterparty_iban)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    contract_id = uuid.uuid4()
    key = (
        iban or (normalize_text(body.counterparty_name) if body.counterparty_name else "") or contract_id.hex
    )
    contract = Contract(
        id=contract_id,
        household_id=member.household.id,
        account_id=body.account_id,
        category_id=body.category_id,
        name=body.name,
        kind=body.kind,
        status=ContractStatus.CONFIRMED,
        counterparty_key=(MANUAL_PREFIX + key)[:200],
        counterparty_iban=iban,
        interval=body.interval,
        expected_amount_cents=body.expected_amount_cents,
        amount_tolerance_pct=body.amount_tolerance_pct,
        next_due_date=body.next_due_date,
        start_date=body.start_date,
        min_term_end=body.min_term_end,
        notice_period_days=body.notice_period_days,
        customer_number=body.customer_number or None,
        note=body.note or None,
        confirmed_at=utcnow(),
    )
    db.add(contract)
    db.flush()
    audit(db, request, settings, "contract_created", member.user, contract_id=str(contract.id))
    return _single(db, member, contract)


@router.get("/{contract_id}")
def get_contract(contract_id: uuid.UUID, member: CurrentMember, db: DbDep) -> schemas.ContractDetail:
    contract = _load(db, member, contract_id)
    transactions = db.scalars(
        select(Transaction)
        .where(Transaction.contract_id == contract.id, visible_transaction_clause(member))
        .order_by(Transaction.booking_date.desc(), Transaction.id)
        .limit(DETAIL_TRANSACTIONS)
    ).all()
    base = _out(db, member, [contract])[0]
    return schemas.ContractDetail(
        **base.model_dump(),
        price_changes=[_price_change_out(pc) for pc in reversed(contract.price_changes)],
        transactions=[
            schemas.ContractTransactionOut.model_validate(tx, from_attributes=True) for tx in transactions
        ],
    )


@router.patch("/{contract_id}")
def update_contract(
    contract_id: uuid.UUID, body: schemas.ContractUpdate, member: CurrentMember, db: DbDep
) -> schemas.ContractOut:
    contract = _load(db, member, contract_id)
    fields = body.model_fields_set
    _check_links(db, member, body.account_id, body.category_id)
    for name in ("name", "kind", "interval", "expected_amount_cents", "amount_tolerance_pct"):
        if name in fields and getattr(body, name) is not None:
            setattr(contract, name, getattr(body, name))
    for name in (
        "start_date",
        "min_term_end",
        "notice_period_days",
        "customer_number",
        "note",
        "category_id",
        "account_id",
    ):
        if name in fields:
            setattr(contract, name, getattr(body, name) or None)
    if contract.expected_amount_cents == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Amount must not be zero")
    if "interval" in fields and contract.last_payment_date is not None:
        contract.next_due_date = add_interval(contract.last_payment_date, contract.interval)
    db.flush()
    return _single(db, member, contract)


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: uuid.UUID, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> None:
    contract = get_visible_contract(db, member, contract_id)
    if not (is_manual(contract) or contract.status is ContractStatus.IGNORED):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only manual or ignored contracts can be deleted; cancel or ignore it"
        )
    db.delete(contract)
    audit(db, request, settings, "contract_deleted", member.user, contract_id=str(contract_id))


# ---------------------------------------------------------------- status actions


def _transition(
    db: Session,
    member: MemberContext,
    request: Request,
    settings: SettingsDep,
    contract_id: uuid.UUID,
    action: str,
    allowed: dict[ContractStatus, ContractStatus],
) -> schemas.ContractOut:
    contract = _load(db, member, contract_id)
    target = allowed.get(contract.status)
    if target is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot {action} a {contract.status.value} contract")
    now: datetime = utcnow()
    contract.status = target
    if target is ContractStatus.CONFIRMED:
        contract.confirmed_at = contract.confirmed_at or now
        contract.cancelled_at = None
    elif target is ContractStatus.CANCELLED:
        contract.cancelled_at = now
    elif target is ContractStatus.DETECTED:
        contract.confirmed_at = None
        contract.cancelled_at = None
    db.flush()
    audit(db, request, settings, f"contract_{action}", member.user, contract_id=str(contract.id))
    return _single(db, member, contract)


@router.post("/{contract_id}/confirm")
def confirm_contract(
    contract_id: uuid.UUID, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> schemas.ContractOut:
    allowed = {ContractStatus.DETECTED: ContractStatus.CONFIRMED}
    return _transition(db, member, request, settings, contract_id, "confirm", allowed)


@router.post("/{contract_id}/cancel")
def cancel_contract(
    contract_id: uuid.UUID, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> schemas.ContractOut:
    allowed = {ContractStatus.CONFIRMED: ContractStatus.CANCELLED}
    return _transition(db, member, request, settings, contract_id, "cancel", allowed)


@router.post("/{contract_id}/ignore")
def ignore_contract(
    contract_id: uuid.UUID, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> schemas.ContractOut:
    allowed = {
        ContractStatus.DETECTED: ContractStatus.IGNORED,
        ContractStatus.CONFIRMED: ContractStatus.IGNORED,
    }
    return _transition(db, member, request, settings, contract_id, "ignore", allowed)


@router.post("/{contract_id}/reactivate")
def reactivate_contract(
    contract_id: uuid.UUID, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> schemas.ContractOut:
    """A cancelled contract runs again; an ignored suggestion becomes a suggestion again."""
    allowed = {
        ContractStatus.CANCELLED: ContractStatus.CONFIRMED,
        ContractStatus.IGNORED: ContractStatus.DETECTED,
    }
    return _transition(db, member, request, settings, contract_id, "reactivate", allowed)


# ---------------------------------------------------------------- price changes, letter


@router.post("/{contract_id}/price-changes/{price_change_id}/acknowledge")
def acknowledge_price_change(
    contract_id: uuid.UUID, price_change_id: uuid.UUID, member: CurrentMember, db: DbDep
) -> schemas.PriceChangeOut:
    contract = get_visible_contract(db, member, contract_id)
    change = db.scalar(
        select(ContractPriceChange).where(
            ContractPriceChange.id == price_change_id, ContractPriceChange.contract_id == contract.id
        )
    )
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price change not found")
    if change.acknowledged_at is None:
        change.acknowledged_at = utcnow()
        db.flush()
    return _price_change_out(change)


@router.get("/{contract_id}/cancellation-letter")
def cancellation_letter(
    contract_id: uuid.UUID, member: CurrentMember, db: DbDep
) -> schemas.CancellationLetter:
    contract = get_visible_contract(db, member, contract_id)
    reference = f"Kundennummer: {contract.customer_number}\n\n" if contract.customer_number else ""
    subject = "Kündigung meines Vertrags"
    if contract.customer_number:
        subject += f" (Kundennummer {contract.customer_number})"
    body = (
        "Sehr geehrte Damen und Herren,\n\n"
        f"{reference}"
        f'hiermit kündige ich meinen Vertrag mit der Bezeichnung "{contract.name}" '
        "ordentlich und fristgerecht zum nächstmöglichen Zeitpunkt.\n\n"
        "Bitte bestätigen Sie mir die Kündigung sowie das Datum der Vertragsbeendigung schriftlich.\n\n"
        "Mit freundlichen Grüßen\n"
        f"{member.user.display_name}"
    )
    return schemas.CancellationLetter(subject=subject, body=body, recipient_name=contract.name)
