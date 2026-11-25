"""Savings goals with manual contributions or account-based progress."""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api import planning_schemas as schemas
from app.deps import CurrentMember, DbDep, MemberContext
from app.finance.access import get_visible_account, get_visible_goal, visible_goal_clause
from app.finance.contracts import today_berlin
from app.finance.goals import compute_progress, progress_for_goals
from app.models import Account, AccountVisibility, SavingsContribution, SavingsGoal
from app.models.base import utcnow

router = APIRouter(prefix="/savings-goals", tags=["savings goals"])

_NOT_NULL = ("name", "target_cents", "visibility")


def _out(
    db: Session, member: MemberContext, goals: Sequence[SavingsGoal], *, detail: bool
) -> list[schemas.GoalOut]:
    progress = progress_for_goals(db, member, goals)
    today = today_berlin()
    result: list[schemas.GoalOut] = []
    for goal in goals:
        computed = compute_progress(progress[goal.id], goal.target_cents, goal.target_date, today)
        result.append(
            schemas.GoalOut(
                id=goal.id,
                name=goal.name,
                target_cents=goal.target_cents,
                target_date=goal.target_date,
                account_id=goal.account_id,
                account_name=goal.account.name if goal.account else None,
                visibility=goal.visibility,
                owner_user_id=goal.owner_user_id,
                icon=goal.icon,
                color=goal.color,
                note=goal.note,
                archived=goal.archived_at is not None,
                archived_at=goal.archived_at,
                created_at=goal.created_at,
                progress_cents=computed.progress_cents,
                percent=computed.percent,
                remaining_cents=computed.remaining_cents,
                monthly_needed_cents=computed.monthly_needed_cents,
                achieved=computed.achieved,
                contributions=(
                    [
                        schemas.ContributionOut.model_validate(c, from_attributes=True)
                        for c in goal.contributions
                    ]
                    if detail and goal.account_id is None
                    else []
                ),
            )
        )
    return result


def _one(db: Session, member: MemberContext, goal: SavingsGoal) -> schemas.GoalOut:
    db.flush()
    db.refresh(goal, ["account", "contributions"])
    return _out(db, member, [goal], detail=True)[0]


def _check_account_rule(goal: SavingsGoal, account: Account | None) -> None:
    """A goal on a private account is private and belongs to that account's owner."""
    if (
        account is not None
        and account.visibility is AccountVisibility.PRIVATE
        and (goal.visibility is not AccountVisibility.PRIVATE or goal.owner_user_id != account.owner_user_id)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A goal linked to a private account must be private and owned by the account owner",
        )


@router.get("")
def list_goals(
    member: CurrentMember, db: DbDep, include_archived: Annotated[bool, Query()] = False
) -> list[schemas.GoalOut]:
    query = (
        select(SavingsGoal)
        .where(visible_goal_clause(member))
        .options(selectinload(SavingsGoal.account))
        .order_by(SavingsGoal.created_at, SavingsGoal.id)
    )
    if not include_archived:
        query = query.where(SavingsGoal.archived_at.is_(None))
    return _out(db, member, list(db.scalars(query)), detail=False)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_goal(body: schemas.GoalCreate, member: CurrentMember, db: DbDep) -> schemas.GoalOut:
    if body.target_date is not None and body.target_date <= today_berlin():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "target_date must be in the future")
    account = get_visible_account(db, member, body.account_id) if body.account_id else None
    goal = SavingsGoal(
        id=uuid.uuid4(),
        household_id=member.household.id,
        owner_user_id=member.user.id,
        visibility=body.visibility,
        name=body.name,
        target_cents=body.target_cents,
        target_date=body.target_date,
        account_id=account.id if account else None,
        icon=body.icon,
        color=body.color,
        note=body.note,
    )
    _check_account_rule(goal, account)
    db.add(goal)
    return _one(db, member, goal)


@router.get("/{goal_id}")
def get_goal(goal_id: uuid.UUID, member: CurrentMember, db: DbDep) -> schemas.GoalOut:
    return _one(db, member, get_visible_goal(db, member, goal_id))


@router.patch("/{goal_id}")
def update_goal(
    goal_id: uuid.UUID, body: schemas.GoalUpdate, member: CurrentMember, db: DbDep
) -> schemas.GoalOut:
    goal = get_visible_goal(db, member, goal_id)
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    if any(name in changes and changes[name] is None for name in _NOT_NULL):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "name, target_cents and visibility cannot be null"
        )
    if "account_id" in changes:
        account_id = changes.pop("account_id")
        account = get_visible_account(db, member, account_id) if account_id else None
        goal.account_id = account.id if account else None
    archived = changes.pop("archived", None)
    for name, value in changes.items():
        setattr(goal, name, value)
    if archived is not None:
        goal.archived_at = (goal.archived_at or utcnow()) if archived else None
    db.flush()
    db.refresh(goal, ["account"])
    _check_account_rule(goal, goal.account)
    return _one(db, member, goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    db.delete(get_visible_goal(db, member, goal_id))


@router.post("/{goal_id}/contributions", status_code=status.HTTP_201_CREATED)
def add_contribution(
    goal_id: uuid.UUID, body: schemas.ContributionCreate, member: CurrentMember, db: DbDep
) -> schemas.GoalOut:
    goal = get_visible_goal(db, member, goal_id)
    if goal.account_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Goals linked to an account take their progress from its balance"
        )
    if goal.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Goal is archived")
    if body.booked_on > today_berlin():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "booked_on must not be in the future")
    goal.contributions.append(
        SavingsContribution(
            id=uuid.uuid4(),
            amount_cents=body.amount_cents,
            booked_on=body.booked_on,
            note=body.note or None,
            created_by_id=member.user.id,
        )
    )
    return _one(db, member, goal)


@router.delete("/{goal_id}/contributions/{contribution_id}")
def delete_contribution(
    goal_id: uuid.UUID, contribution_id: uuid.UUID, member: CurrentMember, db: DbDep
) -> schemas.GoalOut:
    goal = get_visible_goal(db, member, goal_id)
    contribution = db.scalar(
        select(SavingsContribution).where(
            SavingsContribution.id == contribution_id, SavingsContribution.goal_id == goal.id
        )
    )
    if contribution is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    goal.contributions.remove(contribution)
    return _one(db, member, goal)
