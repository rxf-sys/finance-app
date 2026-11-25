"""Recurring payments: detection, matching of new payments, price changes and cancellation deadlines.

Detection works per (account, counterparty key), so a contract found on a private account keeps that
`account_id` and stays invisible to other members (see `app.finance.access.visible_contract_clause`).
"""

import calendar
import itertools
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance.access import account_audience
from app.finance.normalize import normalize_text
from app.finance.notify import deliver, format_eur
from app.models import (
    Category,
    CategoryKind,
    Contract,
    ContractInterval,
    ContractKind,
    ContractPriceChange,
    ContractStatus,
    NotificationKind,
    Transaction,
)

BERLIN = ZoneInfo("Europe/Berlin")
MANUAL_PREFIX = "manual:"

# Nominal length in days and accepted median spacing (nominal +- tolerance) per interval.
NOMINAL_DAYS = {
    ContractInterval.WEEKLY: 7,
    ContractInterval.MONTHLY: 30,
    ContractInterval.QUARTERLY: 91,
    ContractInterval.HALF_YEARLY: 182,
    ContractInterval.YEARLY: 365,
}
_TOLERANCE_DAYS = {
    ContractInterval.WEEKLY: 2,
    ContractInterval.MONTHLY: 4,
    ContractInterval.QUARTERLY: 7,
    ContractInterval.HALF_YEARLY: 10,
    ContractInterval.YEARLY: 15,
}
_MONTHS = {
    ContractInterval.MONTHLY: 1,
    ContractInterval.QUARTERLY: 3,
    ContractInterval.HALF_YEARLY: 6,
    ContractInterval.YEARLY: 12,
}
AMOUNT_BAND_PCT = 10
MIN_OCCURRENCES = 3
MIN_OCCURRENCES_YEARLY = 2


def today_berlin() -> date:
    return datetime.now(BERLIN).date()


# ---------------------------------------------------------------- dates


def add_months_clamped(day: date, months: int) -> date:
    """Same day of month `months` later, clamped to the month's length (31 Jan + 1 -> 28/29 Feb)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def add_interval(day: date, interval: ContractInterval) -> date:
    if interval is ContractInterval.WEEKLY:
        return day + timedelta(days=7)
    return add_months_clamped(day, _MONTHS[interval])


def interval_matches(days: float, interval: ContractInterval) -> bool:
    return abs(days - NOMINAL_DAYS[interval]) <= _TOLERANCE_DAYS[interval]


def cancellation_deadline(contract: Contract, today: date | None = None) -> date | None:
    """Last day to give notice: the end of the minimum term minus the notice period.

    Assumption: once `min_term_end` has passed, the contract renews month by month (the German
    default after the minimum term, section 309 no. 9 BGB), so the next term end is the first date
    after `today` reached by stepping from `min_term_end` in whole months (day of month preserved,
    clamped). The deadline may then already lie in the past if the notice period is longer than the
    time left in that month.
    """
    if contract.min_term_end is None or contract.notice_period_days is None:
        return None
    today = today or today_berlin()
    term_end = contract.min_term_end
    steps = 0
    while term_end < today:
        steps += 1
        term_end = add_months_clamped(contract.min_term_end, steps)
    return term_end - timedelta(days=contract.notice_period_days)


# ---------------------------------------------------------------- keys


def transaction_key(tx: Transaction) -> str:
    if tx.counterparty_iban:
        return tx.counterparty_iban
    return normalize_text(tx.counterparty_name) if tx.counterparty_name else ""


def contract_match_key(contract: Contract) -> str:
    """The key payments are compared with; manual contracts carry a marker prefix."""
    return contract.counterparty_key.removeprefix(MANUAL_PREFIX)


def is_manual(contract: Contract) -> bool:
    return contract.counterparty_key.startswith(MANUAL_PREFIX)


# ---------------------------------------------------------------- detection


def _median_int(values: Sequence[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _guess_interval(dates: Sequence[date]) -> ContractInterval | None:
    gaps = [(b - a).days for a, b in itertools.pairwise(dates)]
    if not gaps:
        return None
    middle = median(gaps)
    for interval in ContractInterval:
        if interval_matches(middle, interval):
            return interval
    return None


def _guess_kind(category: Category | None, categories: dict[uuid.UUID, Category]) -> ContractKind:
    if category is None:
        return ContractKind.OTHER
    parent = categories.get(category.parent_id) if category.parent_id else None
    top = (parent or category).name
    child = category.name if parent else ""
    if top == "Versicherungen":
        return ContractKind.INSURANCE
    if top == "Abos & Medien":
        return ContractKind.SUBSCRIPTION
    if top == "Wohnen":
        if child == "Miete":
            return ContractKind.RENT
        if "Strom" in child or "Nebenkosten" in child:
            return ContractKind.UTILITIES
        if "Internet" in child:
            return ContractKind.TELECOM
    return ContractKind.OTHER


def detect_contracts(
    db: Session,
    household_id: uuid.UUID,
    *,
    account_ids: Iterable[uuid.UUID] | None = None,
    today: date | None = None,
) -> list[Contract]:
    """Propose `detected` contracts from recurring outgoing payments; return the new ones.

    `account_ids` limits the transactions looked at (None: the whole household). Keys that already
    have a contract in the same account, with any status, are never proposed again.
    """
    today = today or today_berlin()
    query = (
        select(Transaction)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.household_id == household_id,
            Transaction.amount_cents < 0,
            Transaction.transfer_peer_id.is_(None),
            (Category.kind.is_(None)) | (Category.kind != CategoryKind.TRANSFER),
        )
        .order_by(Transaction.booking_date, Transaction.created_at, Transaction.id)
    )
    if account_ids is not None:
        ids = list(account_ids)
        if not ids:
            return []
        query = query.where(Transaction.account_id.in_(ids))

    groups: dict[tuple[uuid.UUID, str], list[Transaction]] = defaultdict(list)
    for tx in db.scalars(query):
        key = transaction_key(tx)
        if key:
            groups[tx.account_id, key].append(tx)
    if not groups:
        return []

    existing = {
        (c.account_id, contract_match_key(c))
        for c in db.scalars(select(Contract).where(Contract.household_id == household_id))
    }
    categories = {c.id: c for c in db.scalars(select(Category).where(Category.household_id == household_id))}

    created: list[Contract] = []
    for (account_id, key), txs in groups.items():
        if (account_id, key) in existing or (None, key) in existing:
            continue
        contract = _contract_from_group(household_id, account_id, key, txs, categories, today)
        if contract is None:
            continue
        db.add(contract)
        db.flush()
        cluster = [tx for tx in txs if _in_band(tx.amount_cents, contract.expected_amount_cents)]
        for tx in cluster:
            if tx.contract_id is None:
                tx.contract_id = contract.id
        created.append(contract)
    db.flush()
    return created


def _in_band(amount: int, centre: int) -> bool:
    return abs(amount - centre) * 100 <= abs(centre) * AMOUNT_BAND_PCT


def _contract_from_group(
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    key: str,
    txs: list[Transaction],
    categories: dict[uuid.UUID, Category],
    today: date,
) -> Contract | None:
    centre = _median_int([tx.amount_cents for tx in txs])
    cluster = [tx for tx in txs if _in_band(tx.amount_cents, centre)]
    if len(cluster) < MIN_OCCURRENCES_YEARLY:
        return None
    dates = [tx.booking_date for tx in cluster]
    interval = _guess_interval(dates)
    if interval is None:
        return None
    minimum = MIN_OCCURRENCES_YEARLY if interval is ContractInterval.YEARLY else MIN_OCCURRENCES
    if len(cluster) < minimum:
        return None
    last = cluster[-1]
    if (today - last.booking_date).days > 1.5 * NOMINAL_DAYS[interval]:
        return None
    expected = _median_int([tx.amount_cents for tx in cluster])
    category = categories.get(last.category_id) if last.category_id else None
    name = (last.counterparty_name or key).strip()[:100] or key[:100]
    return Contract(
        id=uuid.uuid4(),
        household_id=household_id,
        account_id=account_id,
        category_id=category.id if category else None,
        name=name,
        kind=_guess_kind(category, categories),
        status=ContractStatus.DETECTED,
        counterparty_key=key[:200],
        counterparty_iban=last.counterparty_iban,
        interval=interval,
        expected_amount_cents=expected,
        amount_tolerance_pct=AMOUNT_BAND_PCT,
        last_payment_date=last.booking_date,
        next_due_date=add_interval(last.booking_date, interval),
    )


# ---------------------------------------------------------------- matching


def match_payments(db: Session, household_id: uuid.UUID, transactions: Iterable[Transaction]) -> int:
    """Link new transactions to confirmed or detected contracts; return the number linked.

    A payment must share the key and the account. An amount outside the contract's tolerance is
    accepted as a price change when it arrives one interval after the last payment.
    """
    candidates = sorted(
        (
            tx
            for tx in transactions
            if tx.household_id == household_id
            and tx.contract_id is None
            and tx.transfer_peer_id is None
            and transaction_key(tx)
        ),
        key=lambda tx: (tx.booking_date, tx.id),
    )
    if not candidates:
        return 0
    contracts: dict[tuple[uuid.UUID | None, str], Contract] = {}
    for contract in db.scalars(
        select(Contract)
        .where(
            Contract.household_id == household_id,
            Contract.status.in_([ContractStatus.CONFIRMED, ContractStatus.DETECTED]),
            Contract.account_id.in_({tx.account_id for tx in candidates}),
        )
        .order_by(Contract.created_at, Contract.id)
    ):
        contracts.setdefault((contract.account_id, contract_match_key(contract)), contract)

    linked = 0
    for tx in candidates:
        found = contracts.get((tx.account_id, transaction_key(tx)))
        if found is None or (tx.amount_cents > 0) != (found.expected_amount_cents > 0):
            continue
        contract = found
        expected = contract.expected_amount_cents
        within = abs(tx.amount_cents - expected) * 100 <= abs(expected) * contract.amount_tolerance_pct
        if not within:
            last = contract.last_payment_date
            if last is None or tx.booking_date <= last:
                continue
            if not interval_matches((tx.booking_date - last).days, contract.interval):
                continue
            _record_price_change(db, contract, tx)
        tx.contract_id = contract.id
        if contract.last_payment_date is None or tx.booking_date >= contract.last_payment_date:
            contract.last_payment_date = tx.booking_date
            contract.next_due_date = add_interval(tx.booking_date, contract.interval)
        linked += 1
    db.flush()
    return linked


def _record_price_change(db: Session, contract: Contract, tx: Transaction) -> None:
    change = ContractPriceChange(
        id=uuid.uuid4(),
        contract_id=contract.id,
        old_amount_cents=contract.expected_amount_cents,
        new_amount_cents=tx.amount_cents,
        effective_date=tx.booking_date,
        transaction_id=tx.id,
    )
    db.add(change)
    old, new = contract.expected_amount_cents, tx.amount_cents
    contract.expected_amount_cents = tx.amount_cents
    db.flush()
    deliver(
        db,
        contract.household_id,
        account_audience(db, contract.household_id, contract.account_id),
        kind=NotificationKind.PRICE_CHANGE,
        title=f"Preisänderung: {contract.name}",
        body=f"Der Betrag hat sich von {format_eur(abs(old))} auf {format_eur(abs(new))} geändert.",
        link=f"/contracts/{contract.id}",
        dedupe_key=f"price_change:{change.id}",
    )
