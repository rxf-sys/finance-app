"""Daily generation of in-app notifications.

Every notice has a `dedupe_key`, so running the job again (or twice a day) never duplicates one.
A threshold fires on the first run at or below it, so a missed day does not lose a notice; when
two thresholds are crossed at once only the tighter one is sent.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.deps import MemberContext
from app.finance.access import account_audience
from app.finance.budgets import EXCEEDED_PCT, WARNING_PCT, budget_status
from app.finance.contracts import BERLIN, cancellation_deadline
from app.finance.notify import deliver, format_eur
from app.finance.reporting import month_key
from app.models import (
    BankConnection,
    BankConnectionStatus,
    Contract,
    ContractStatus,
    HouseholdMember,
    NotificationKind,
)

CONTRACT_THRESHOLDS = (7, 30)
CONSENT_THRESHOLDS = (3, 14)


def _threshold(days_left: int, thresholds: tuple[int, ...]) -> int | None:
    """The tightest threshold that `days_left` has reached, or None (also when already past)."""
    if days_left < 0:
        return None
    return next((t for t in thresholds if days_left <= t), None)


def generate_notifications(db: Session, today: date) -> int:
    """Create all due notifications for every household; return how many rows were created."""
    return _contract_notices(db, today) + _budget_warnings(db, today) + _consent_expiry(db, today)


def _contract_notices(db: Session, today: date) -> int:
    created = 0
    contracts = db.scalars(
        select(Contract)
        .where(Contract.status == ContractStatus.CONFIRMED, Contract.min_term_end.is_not(None))
        .order_by(Contract.id)
    )
    for contract in contracts:
        deadline = cancellation_deadline(contract, today)
        if deadline is None:
            continue
        days_left = (deadline - today).days
        threshold = _threshold(days_left, CONTRACT_THRESHOLDS)
        if threshold is None:
            continue
        created += deliver(
            db,
            contract.household_id,
            account_audience(db, contract.household_id, contract.account_id),
            kind=NotificationKind.CONTRACT_NOTICE,
            title=f"Kündigungsfrist: {contract.name}",
            body=f"Die Kündigungsfrist endet am {deadline:%d.%m.%Y} (in {days_left} Tagen).",
            link=f"/contracts/{contract.id}",
            dedupe_key=f"contract:{contract.id}:deadline:{deadline.isoformat()}:{threshold}",
        )
    return created


def _members(db: Session) -> list[MemberContext]:
    rows = db.scalars(
        select(HouseholdMember)
        .options(joinedload(HouseholdMember.user), joinedload(HouseholdMember.household))
        .order_by(HouseholdMember.household_id, HouseholdMember.user_id)
    )
    return [MemberContext(row.user, row.household, row.role) for row in rows if row.user.is_active]


def _budget_warnings(db: Session, today: date) -> int:
    created = 0
    month = today.replace(day=1)
    for member in _members(db):
        for status in budget_status(db, member, month):
            if status.pct >= EXCEEDED_PCT:
                level = EXCEEDED_PCT
            elif status.pct >= WARNING_PCT:
                level = WARNING_PCT
            else:
                continue
            what = "überschritten" if level == EXCEEDED_PCT else f"zu {level} Prozent ausgeschöpft"
            created += deliver(
                db,
                member.household.id,
                [member.user.id],
                kind=NotificationKind.BUDGET_WARNING,
                title=f"Budget {status.category_name}",
                body=(
                    f"Das Budget ist {what}: {format_eur(status.spent_cents)} "
                    f"von {format_eur(status.limit_cents)}."
                ),
                link="/budgets",
                dedupe_key=f"budget:{status.budget.id}:{month_key(month)}:{level}",
            )
    return created


def _consent_expiry(db: Session, today: date) -> int:
    created = 0
    connections = db.scalars(
        select(BankConnection)
        .where(
            BankConnection.status == BankConnectionStatus.ACTIVE,
            BankConnection.consent_valid_until.is_not(None),
            BankConnection.owner_user_id.is_not(None),
        )
        .order_by(BankConnection.id)
    )
    for connection in connections:
        if connection.consent_valid_until is None or connection.owner_user_id is None:
            continue
        valid_until = connection.consent_valid_until.astimezone(BERLIN).date()
        days_left = (valid_until - today).days
        threshold = _threshold(days_left, CONSENT_THRESHOLDS)
        if threshold is None:
            continue
        created += deliver(
            db,
            connection.household_id,
            [connection.owner_user_id],
            kind=NotificationKind.CONSENT_EXPIRY,
            title=f"Bankzugang läuft ab: {connection.aspsp_name}",
            body=f"Die Zustimmung zum Bankzugang endet am {valid_until:%d.%m.%Y}. Bitte erneuern.",
            link="/accounts",
            dedupe_key=f"consent:{connection.id}:{valid_until.isoformat()}:{threshold}",
        )
    return created
