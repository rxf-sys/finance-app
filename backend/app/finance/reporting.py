"""SQL aggregations for balances, dashboards and category counts.

Everything here aggregates in Postgres. The basis is `effective_lines`: one row per unsplit
transaction or per split, restricted to accounts the member can see. A line is a transfer, and
excluded from income and expense, when its transaction is paired or its category has kind transfer.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Subquery,
    and_,
    case,
    exists,
    func,
    select,
    union_all,
)
from sqlalchemy.orm import Session, aliased

from app.deps import MemberContext
from app.finance.access import visible_account_clause, visible_transaction_clause
from app.models import Account, Category, CategoryKind, Transaction, TransactionSplit

BERLIN = ZoneInfo("Europe/Berlin")


# ---------------------------------------------------------------- months


def current_month() -> date:
    today = datetime.now(BERLIN).date()
    return today.replace(day=1)


def add_months(month: date, delta: int) -> date:
    index = month.year * 12 + (month.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def month_key(month: date) -> str:
    return f"{month.year:04d}-{month.month:02d}"


def parse_month(value: str) -> date:
    year, mon = value.split("-")
    return date(int(year), int(mon), 1)


# ---------------------------------------------------------------- effective lines


def effective_lines(
    member: MemberContext, date_from: date | None = None, date_to: date | None = None
) -> Subquery:
    """Columns: transaction_id, account_id, booking_date, amount_cents, category_id, is_paired, contract_id.

    `date_to` is exclusive. Splits replace their parent transaction.
    """

    def bounds() -> list[ColumnElement[bool]]:
        clauses: list[ColumnElement[bool]] = []
        if date_from is not None:
            clauses.append(Transaction.booking_date >= date_from)
        if date_to is not None:
            clauses.append(Transaction.booking_date < date_to)
        return clauses

    visible = visible_transaction_clause(member)
    unsplit = select(
        Transaction.id.label("transaction_id"),
        Transaction.account_id.label("account_id"),
        Transaction.booking_date.label("booking_date"),
        Transaction.amount_cents.label("amount_cents"),
        Transaction.category_id.label("category_id"),
        Transaction.transfer_peer_id.is_not(None).label("is_paired"),
        Transaction.contract_id.label("contract_id"),
    ).where(
        visible,
        ~exists().where(TransactionSplit.transaction_id == Transaction.id),
        *bounds(),
    )
    split = (
        select(
            Transaction.id.label("transaction_id"),
            Transaction.account_id.label("account_id"),
            Transaction.booking_date.label("booking_date"),
            TransactionSplit.amount_cents.label("amount_cents"),
            TransactionSplit.category_id.label("category_id"),
            Transaction.transfer_peer_id.is_not(None).label("is_paired"),
            Transaction.contract_id.label("contract_id"),
        )
        .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
        .where(visible, *bounds())
    )
    return union_all(unsplit, split).subquery("lines")


def is_transfer(lines: Subquery, category: type[Category]) -> ColumnElement[bool]:
    in_transfer_category = case((category.kind == CategoryKind.TRANSFER, True), else_=False)
    return lines.c.is_paired | in_transfer_category


# ---------------------------------------------------------------- accounts


@dataclass(frozen=True)
class AccountStats:
    account: Account
    balance_cents: int
    transaction_count: int
    last_booking_date: date | None


def account_stats(
    db: Session, member: MemberContext, *, account_id: uuid.UUID | None = None, include_archived: bool = True
) -> list[AccountStats]:
    query = (
        select(
            Account,
            func.coalesce(func.sum(Transaction.amount_cents), 0),
            func.count(Transaction.id),
            func.max(Transaction.booking_date),
        )
        .outerjoin(Transaction, Transaction.account_id == Account.id)
        .where(visible_account_clause(member))
        .group_by(Account.id)
        .order_by(Account.is_archived, Account.name, Account.id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)
    if not include_archived:
        query = query.where(Account.is_archived.is_(False))
    return [
        AccountStats(account, account.opening_balance_cents + int(total), int(count), last)
        for account, total, count, last in db.execute(query)
    ]


def balance_history(db: Session, account: Account, months: int) -> list[tuple[str, int]]:
    """Month-end balances, oldest first, ending with the current month; empty months are included."""
    first = add_months(current_month(), -(months - 1))
    end = add_months(current_month(), 1)
    before = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.account_id == account.id, Transaction.booking_date < first
        )
    )
    month_expr = func.to_char(Transaction.booking_date, "YYYY-MM")
    sums = {
        key: int(total)
        for key, total in db.execute(
            select(month_expr, func.sum(Transaction.amount_cents))
            .where(
                Transaction.account_id == account.id,
                Transaction.booking_date >= first,
                Transaction.booking_date < end,
            )
            .group_by(month_expr)
        )
    }
    balance = account.opening_balance_cents + int(before or 0)
    history: list[tuple[str, int]] = []
    for offset in range(months):
        key = month_key(add_months(first, offset))
        balance += sums.get(key, 0)
        history.append((key, balance))
    return history


# ---------------------------------------------------------------- flows


def monthly_flows(db: Session, member: MemberContext, first: date, last: date) -> list[tuple[str, int, int]]:
    """(month, income_cents, expense_cents) for every month from `first` to `last` inclusive."""
    lines = effective_lines(member, first, add_months(last, 1))
    category = aliased(Category)
    counted = ~is_transfer(lines, category)
    month_expr = func.to_char(lines.c.booking_date, "YYYY-MM")
    income = func.coalesce(
        func.sum(case((and_(counted, lines.c.amount_cents > 0), lines.c.amount_cents), else_=0)), 0
    )
    expense = func.coalesce(
        func.sum(case((and_(counted, lines.c.amount_cents < 0), -lines.c.amount_cents), else_=0)), 0
    )
    rows = db.execute(
        select(month_expr, income, expense)
        .select_from(lines.outerjoin(category, category.id == lines.c.category_id))
        .group_by(month_expr)
    )
    found = {key: (int(inc), int(exp)) for key, inc, exp in rows}
    result: list[tuple[str, int, int]] = []
    month = first
    while month <= last:
        key = month_key(month)
        inc, exp = found.get(key, (0, 0))
        result.append((key, inc, exp))
        month = add_months(month, 1)
    return result


@dataclass(frozen=True)
class CategoryTotal:
    category_id: uuid.UUID | None
    name: str | None
    icon: str | None
    color: str | None
    amount_cents: int


def top_expense_categories(
    db: Session, member: MemberContext, month: date, limit: int = 6
) -> list[CategoryTotal]:
    """Expense per top-level category for one month; uncategorized money forms a null bucket."""
    lines = effective_lines(member, month, add_months(month, 1))
    category = aliased(Category)
    top = aliased(Category)
    amount = func.sum(-lines.c.amount_cents)
    rows = db.execute(
        select(top.id, top.name, top.icon, top.color, amount)
        .select_from(
            lines.outerjoin(category, category.id == lines.c.category_id).outerjoin(
                top, top.id == func.coalesce(category.parent_id, category.id)
            )
        )
        .where(lines.c.amount_cents < 0, ~is_transfer(lines, category))
        .group_by(top.id, top.name, top.icon, top.color)
        .order_by(amount.desc(), top.name)
        .limit(limit)
    )
    return [CategoryTotal(cid, name, icon, color, int(total)) for cid, name, icon, color, total in rows]


def category_line_counts(db: Session, member: MemberContext) -> dict[uuid.UUID, int]:
    """Number of visible transactions (or splits) per effective category."""
    lines = effective_lines(member)
    rows = db.execute(
        select(lines.c.category_id, func.count())
        .where(lines.c.category_id.is_not(None))
        .group_by(lines.c.category_id)
    )
    return {category_id: int(count) for category_id, count in rows}


def uncategorized_count(db: Session, member: MemberContext) -> int:
    """Visible, unpaired, unsplit transactions without a category."""
    return int(
        db.scalar(
            select(func.count()).where(
                visible_transaction_clause(member),
                Transaction.category_id.is_(None),
                Transaction.transfer_peer_id.is_(None),
                ~exists().where(TransactionSplit.transaction_id == Transaction.id),
            )
        )
        or 0
    )
