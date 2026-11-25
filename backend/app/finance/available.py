"""'Frei verfügbar': current balance minus fixed costs still due this month."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import MemberContext
from app.finance import reporting
from app.finance.access import visible_contract_clause
from app.finance.contracts import add_interval
from app.models import Account, AccountKind, Contract, ContractInterval, ContractStatus

SPENDABLE_KINDS = {AccountKind.GIRO, AccountKind.CASH}


@dataclass(frozen=True)
class UpcomingItem:
    contract_id: uuid.UUID
    name: str
    due_date: date
    amount_cents: int  # signed: negative is a payment


@dataclass(frozen=True)
class Available:
    balance_cents: int
    upcoming_out_cents: int
    upcoming_in_cents: int
    available_cents: int
    items: list[UpcomingItem]


def end_of_month(day: date) -> date:
    return reporting.add_months(day.replace(day=1), 1) - timedelta(days=1)


def available_to_spend(db: Session, member: MemberContext, today: date) -> Available:
    balance = sum(
        stats.balance_cents
        for stats in reporting.account_stats(db, member, include_archived=False)
        if stats.account.kind in SPENDABLE_KINDS
    )
    last_day = end_of_month(today)
    contracts = db.scalars(
        select(Contract)
        .outerjoin(Account, Account.id == Contract.account_id)
        .where(
            # Only what is paid from the accounts counted in the balance, or from no known account.
            Account.id.is_(None) | Account.kind.in_(SPENDABLE_KINDS),
            visible_contract_clause(member),
            Contract.status == ContractStatus.CONFIRMED,
            Contract.next_due_date > today,
            Contract.next_due_date <= last_day,
        )
        .order_by(Contract.next_due_date, Contract.name, Contract.id)
    )
    items: list[UpcomingItem] = []
    for contract in contracts:
        due = contract.next_due_date
        while due is not None and due <= last_day:
            items.append(UpcomingItem(contract.id, contract.name, due, contract.expected_amount_cents))
            if contract.interval is not ContractInterval.WEEKLY:
                break
            due = add_interval(due, contract.interval)
    items.sort(key=lambda i: (i.due_date, i.name, i.contract_id))
    out = -sum(i.amount_cents for i in items if i.amount_cents < 0)
    incoming = sum(i.amount_cents for i in items if i.amount_cents > 0)
    return Available(balance, out, incoming, balance - out + incoming, items)
