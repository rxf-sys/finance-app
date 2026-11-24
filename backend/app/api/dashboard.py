"""Dashboard numbers for one month, limited to what the caller may see."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api import finance_schemas as schemas
from app.deps import CurrentMember, DbDep
from app.finance import reporting

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TREND_MONTHS = 12


@router.get("")
def get_dashboard(
    member: CurrentMember,
    db: DbDep,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> schemas.DashboardOut:
    selected = reporting.parse_month(month) if month else reporting.current_month()
    accounts = reporting.account_stats(db, member, include_archived=False)
    flows = reporting.monthly_flows(db, member, reporting.add_months(selected, -(TREND_MONTHS - 1)), selected)
    _, income, expense = flows[-1]
    return schemas.DashboardOut(
        month=reporting.month_key(selected),
        accounts=[
            schemas.DashboardAccount(
                id=stats.account.id,
                name=stats.account.name,
                kind=stats.account.kind,
                visibility=stats.account.visibility,
                balance_cents=stats.balance_cents,
                is_mine=stats.account.owner_user_id == member.user.id,
            )
            for stats in accounts
        ],
        net_worth_cents=sum(stats.balance_cents for stats in accounts),
        income_cents=income,
        expense_cents=expense,
        net_cents=income - expense,
        top_categories=[
            schemas.TopCategory(
                category_id=total.category_id,
                name=total.name,
                icon=total.icon,
                color=total.color,
                amount_cents=total.amount_cents,
            )
            for total in reporting.top_expense_categories(db, member, selected)
        ],
        trend=[schemas.TrendPoint(month=key, income_cents=inc, expense_cents=exp) for key, inc, exp in flows],
        uncategorized_count=reporting.uncategorized_count(db, member),
    )
