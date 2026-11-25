"""Year reports: income and expense per month, and category matrices per month.

Built on `reporting.effective_lines`: splits count by their own category, transfers never count.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session, aliased

from app.deps import MemberContext
from app.finance import reporting
from app.models import Category

ReportKind = Literal["expense", "income"]


def savings_rate_bp(income_cents: int, saldo_cents: int) -> int | None:
    """Saldo as a share of income in basis points (1234 = 12.34 %), rounded; None without income."""
    if income_cents <= 0:
        return None
    return (saldo_cents * 20_000 + income_cents) // (2 * income_cents)


@dataclass(frozen=True)
class MonthFlow:
    month: str
    income_cents: int
    expense_cents: int  # negative
    saldo_cents: int
    savings_rate_bp: int | None


def year_flows(db: Session, member: MemberContext, year: int) -> list[MonthFlow]:
    flows = reporting.monthly_flows(db, member, date(year, 1, 1), date(year, 12, 1))
    return [
        MonthFlow(month, income, -expense, income - expense, savings_rate_bp(income, income - expense))
        for month, income, expense in flows
    ]


@dataclass
class CategoryLine:
    category_id: uuid.UUID | None
    name: str | None
    icon: str | None
    color: str | None
    months: list[int] = field(default_factory=lambda: [0] * 12)
    children: list["CategoryLine"] = field(default_factory=list)

    @property
    def total_cents(self) -> int:
        return sum(self.months)

    def add(self, month: int, cents: int) -> None:
        self.months[month - 1] += cents


@dataclass
class CategoryReport:
    rows: list[CategoryLine]
    uncategorized: CategoryLine
    totals: list[int]


def category_report(db: Session, member: MemberContext, year: int, kind: ReportKind) -> CategoryReport:
    """Signed cents per top-level category (with children) and month for one year.

    Expense reports count debit lines, income reports credit lines; refunds are not netted.
    """
    lines = reporting.effective_lines(member, date(year, 1, 1), date(year + 1, 1, 1))
    category = aliased(Category)
    top = aliased(Category)
    month = extract("month", lines.c.booking_date)
    sign = lines.c.amount_cents < 0 if kind == "expense" else lines.c.amount_cents > 0
    query = (
        select(
            top.id,
            top.name,
            top.icon,
            top.color,
            category.id,
            category.name,
            category.icon,
            category.color,
            month,
            func.sum(lines.c.amount_cents),
        )
        .select_from(
            lines.outerjoin(category, category.id == lines.c.category_id).outerjoin(
                top, top.id == func.coalesce(category.parent_id, category.id)
            )
        )
        .where(sign, ~reporting.is_transfer(lines, category))
        .group_by(
            top.id,
            top.name,
            top.icon,
            top.color,
            category.id,
            category.name,
            category.icon,
            category.color,
            month,
        )
    )
    uncategorized = CategoryLine(None, None, None, None)
    tops: dict[uuid.UUID, CategoryLine] = {}
    children: dict[tuple[uuid.UUID, uuid.UUID], CategoryLine] = {}
    for (
        top_id,
        top_name,
        top_icon,
        top_color,
        cat_id,
        cat_name,
        cat_icon,
        cat_color,
        month_no,
        total,
    ) in db.execute(query):
        cents, mon = int(total), int(month_no)
        if top_id is None:
            uncategorized.add(mon, cents)
            continue
        parent = tops.setdefault(top_id, CategoryLine(top_id, top_name, top_icon, top_color))
        parent.add(mon, cents)
        if cat_id != top_id:
            child = children.get((top_id, cat_id))
            if child is None:
                child = children[(top_id, cat_id)] = CategoryLine(cat_id, cat_name, cat_icon, cat_color)
                parent.children.append(child)
            child.add(mon, cents)

    def order(line: CategoryLine) -> tuple[int, str]:
        # Largest absolute amount first, then by name.
        return -abs(line.total_cents), line.name or ""

    rows = sorted(tops.values(), key=order)
    for row in rows:
        row.children.sort(key=order)
    totals = [sum(r.months[i] for r in rows) + uncategorized.months[i] for i in range(12)]
    return CategoryReport(rows, uncategorized, totals)
