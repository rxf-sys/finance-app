"""Monthly category budgets and their status."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import planning_schemas as schemas
from app.api.categories import get_category
from app.api.common import conflict_on_duplicate
from app.deps import CurrentMember, DbDep, MemberContext
from app.finance.budgets import budget_status
from app.finance.reporting import current_month, month_key, parse_month
from app.models import Budget, CategoryKind

router = APIRouter(prefix="/budgets", tags=["budgets"])

DUPLICATE = "A budget for this category already exists"


def _get_budget(db: Session, member: MemberContext, budget_id: uuid.UUID) -> Budget:
    budget = db.scalar(
        select(Budget).where(Budget.id == budget_id, Budget.household_id == member.household.id)
    )
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    return budget


def _out(budget: Budget) -> schemas.BudgetOut:
    return schemas.BudgetOut(
        id=budget.id,
        category_id=budget.category_id,
        category_name=budget.category.name,
        amount_cents=budget.amount_cents,
        rollover=budget.rollover,
    )


@router.get("")
def list_budgets(member: CurrentMember, db: DbDep) -> list[schemas.BudgetOut]:
    budgets = db.scalars(select(Budget).where(Budget.household_id == member.household.id)).all()
    return sorted((_out(b) for b in budgets), key=lambda b: (b.category_name, b.id))


@router.get("/status")
def get_status(
    member: CurrentMember,
    db: DbDep,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> list[schemas.BudgetStatusOut]:
    first = parse_month(month) if month else current_month()
    return [
        schemas.BudgetStatusOut(
            **_out(s.budget).model_dump(),
            month=month_key(first),
            spent_cents=s.spent_cents,
            limit_cents=s.limit_cents,
            remaining_cents=s.remaining_cents,
            pct=s.pct,
            state=s.state,
        )
        for s in budget_status(db, member, first)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_budget(body: schemas.BudgetCreate, member: CurrentMember, db: DbDep) -> schemas.BudgetOut:
    category = get_category(db, member, body.category_id)
    if category.kind is not CategoryKind.EXPENSE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Budgets need an expense category")
    budget = Budget(
        id=uuid.uuid4(),
        household_id=member.household.id,
        category_id=category.id,
        amount_cents=body.amount_cents,
        rollover=body.rollover,
    )
    with conflict_on_duplicate(db, DUPLICATE):
        db.add(budget)
    db.refresh(budget, ["category"])
    return _out(budget)


@router.patch("/{budget_id}")
def update_budget(
    budget_id: uuid.UUID, body: schemas.BudgetUpdate, member: CurrentMember, db: DbDep
) -> schemas.BudgetOut:
    budget = _get_budget(db, member, budget_id)
    if body.amount_cents is not None:
        budget.amount_cents = body.amount_cents
    if body.rollover is not None:
        budget.rollover = body.rollover
    db.flush()
    return _out(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    db.delete(_get_budget(db, member, budget_id))
