"""Budget status: spending per budget and month, with optional one-month rollover."""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.deps import MemberContext
from app.finance.reporting import add_months, effective_lines, is_transfer
from app.models import Budget, Category

WARNING_PCT = 80
EXCEEDED_PCT = 100

BudgetState = Literal["ok", "warning", "exceeded"]


@dataclass(frozen=True)
class BudgetStatus:
    budget: Budget
    category_name: str
    month: date
    spent_cents: int
    limit_cents: int
    remaining_cents: int
    pct: int
    state: BudgetState


def _spent_by_budget(db: Session, member: MemberContext, month: date) -> dict[uuid.UUID, int]:
    """Expense per budget id in one month. A budget on a top-level category includes its children."""
    lines = effective_lines(member, month, add_months(month, 1))
    category = aliased(Category)
    amount = func.coalesce(func.sum(-lines.c.amount_cents), 0)
    rows = db.execute(
        select(Budget.id, amount)
        .select_from(lines)
        .join(category, category.id == lines.c.category_id)
        .join(
            Budget,
            (Budget.household_id == member.household.id)
            & or_(Budget.category_id == category.id, Budget.category_id == category.parent_id),
        )
        .where(lines.c.amount_cents < 0, ~is_transfer(lines, category))
        .group_by(Budget.id)
    )
    return {budget_id: int(total) for budget_id, total in rows}


def classify(spent_cents: int, limit_cents: int) -> tuple[int, BudgetState]:
    if limit_cents <= 0:
        return (EXCEEDED_PCT, "exceeded") if spent_cents > 0 else (0, "ok")
    pct = spent_cents * 100 // limit_cents
    if pct >= EXCEEDED_PCT:
        return pct, "exceeded"
    if pct >= WARNING_PCT:
        return pct, "warning"
    return pct, "ok"


def budget_status(db: Session, member: MemberContext, month: date) -> list[BudgetStatus]:
    month = month.replace(day=1)
    budgets = list(
        db.execute(
            select(Budget, Category.name)
            .join(Category, Category.id == Budget.category_id)
            .where(Budget.household_id == member.household.id)
            .order_by(Category.name, Budget.id)
        )
    )
    if not budgets:
        return []
    spent = _spent_by_budget(db, member, month)
    previous = (
        _spent_by_budget(db, member, add_months(month, -1)) if any(b.rollover for b, _ in budgets) else {}
    )
    result: list[BudgetStatus] = []
    for budget, name in budgets:
        limit = budget.amount_cents
        if budget.rollover:
            # Only last month's own remainder counts (against its base amount), so it never chains.
            limit += max(0, budget.amount_cents - previous.get(budget.id, 0))
        used = spent.get(budget.id, 0)
        pct, state = classify(used, limit)
        result.append(BudgetStatus(budget, name, month, used, limit, limit - used, pct, state))
    return result
