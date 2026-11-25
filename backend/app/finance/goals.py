"""Savings goal arithmetic. Progress comes from the linked account's balance or manual contributions."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import MemberContext
from app.finance import reporting
from app.models import SavingsContribution, SavingsGoal


@dataclass(frozen=True)
class GoalProgress:
    progress_cents: int
    percent: int
    remaining_cents: int
    monthly_needed_cents: int | None
    achieved: bool


def months_left(today: date, target_date: date) -> int:
    """Calendar months from the current month to the target month, at least 1."""
    return max(1, (target_date.year * 12 + target_date.month) - (today.year * 12 + today.month))


def compute_progress(
    progress_cents: int, target_cents: int, target_date: date | None, today: date
) -> GoalProgress:
    remaining = max(0, target_cents - progress_cents)
    monthly = None
    if target_date is not None and remaining > 0:
        months = months_left(today, target_date)
        monthly = -(-remaining // months)  # ceiling division
    return GoalProgress(
        progress_cents=progress_cents,
        percent=max(0, progress_cents * 100 // target_cents),
        remaining_cents=remaining,
        monthly_needed_cents=monthly,
        achieved=progress_cents >= target_cents,
    )


def progress_for_goals(
    db: Session, member: MemberContext, goals: Iterable[SavingsGoal]
) -> dict[uuid.UUID, int]:
    """Progress in cents per goal id: account balance when linked, else the sum of contributions."""
    goals = list(goals)
    result: dict[uuid.UUID, int] = {}
    if any(g.account_id is not None for g in goals):
        balances = {s.account.id: s.balance_cents for s in reporting.account_stats(db, member)}
        for goal in goals:
            if goal.account_id is not None:
                result[goal.id] = balances.get(goal.account_id, 0)
    manual = [g.id for g in goals if g.account_id is None]
    if manual:
        rows = db.execute(
            select(SavingsContribution.goal_id, func.sum(SavingsContribution.amount_cents))
            .where(SavingsContribution.goal_id.in_(manual))
            .group_by(SavingsContribution.goal_id)
        )
        sums = {goal_id: int(total) for goal_id, total in rows}
        for goal_id in manual:
            result[goal_id] = int(sums.get(goal_id, 0))
    return result
