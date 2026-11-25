"""In-app notifications of the current user."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import ColumnElement, func, select, update

from app.api import planning_schemas as schemas
from app.deps import CurrentMember, DbDep, MemberContext
from app.models import Notification
from app.models.base import utcnow

router = APIRouter(prefix="/notifications", tags=["notifications"])

MAX_LIMIT = 50


def _mine(member: MemberContext) -> list[ColumnElement[bool]]:
    return [Notification.user_id == member.user.id, Notification.household_id == member.household.id]


@router.get("")
def list_notifications(
    member: CurrentMember,
    db: DbDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = MAX_LIMIT,
) -> list[schemas.NotificationOut]:
    query = select(Notification).where(*_mine(member))
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = db.scalars(query.order_by(Notification.created_at.desc(), Notification.id).limit(limit))
    return [schemas.NotificationOut.model_validate(n, from_attributes=True) for n in rows]


@router.get("/unread-count")
def unread_count(member: CurrentMember, db: DbDep) -> schemas.UnreadCount:
    count = db.scalar(
        select(func.count()).select_from(Notification).where(*_mine(member), Notification.read_at.is_(None))
    )
    return schemas.UnreadCount(count=int(count or 0))


@router.post("/read-all")
def read_all(member: CurrentMember, db: DbDep) -> schemas.ReadAllResult:
    result = db.execute(
        update(Notification)
        .where(*_mine(member), Notification.read_at.is_(None))
        .values(read_at=utcnow())
        .returning(Notification.id)
    )
    return schemas.ReadAllResult(updated=len(result.all()))


@router.post("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, member: CurrentMember, db: DbDep) -> schemas.NotificationOut:
    notification = db.scalar(select(Notification).where(Notification.id == notification_id, *_mine(member)))
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if notification.read_at is None:
        notification.read_at = utcnow()
        db.flush()
    return schemas.NotificationOut.model_validate(notification, from_attributes=True)
