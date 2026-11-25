"""Household overview, member management and invites (owner only for changes)."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api import schemas
from app.deps import CurrentMember, CurrentOwner, DbDep, SettingsDep
from app.models import HouseholdMember, Invite, User
from app.models.base import utcnow
from app.security.tokens import generate_token, hash_token
from app.sessions import audit, end_all_sessions

router = APIRouter(prefix="/household", tags=["household"])


@router.get("")
def get_household(member: CurrentMember, db: DbDep) -> schemas.HouseholdOut:
    rows = db.execute(
        select(HouseholdMember, User)
        .join(User, User.id == HouseholdMember.user_id)
        .where(HouseholdMember.household_id == member.household.id, User.is_active.is_(True))
        .order_by(HouseholdMember.joined_at)
    )
    return schemas.HouseholdOut(
        id=member.household.id,
        name=member.household.name,
        members=[
            schemas.Member(
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                role=membership.role,
                joined_at=membership.joined_at,
            )
            for membership, user in rows
        ],
    )


@router.get("/invites")
def list_invites(owner: CurrentOwner, db: DbDep) -> list[schemas.InviteOut]:
    rows = db.scalars(
        select(Invite)
        .where(
            Invite.household_id == owner.household.id,
            Invite.accepted_at.is_(None),
            Invite.expires_at > utcnow(),
        )
        .order_by(Invite.created_at)
    )
    return [schemas.InviteOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def create_invite(
    body: schemas.InviteCreateRequest,
    request: Request,
    owner: CurrentOwner,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.InviteCreated:
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    token = generate_token()
    invite = Invite(
        id=uuid.uuid4(),
        household_id=owner.household.id,
        email=body.email,
        role=body.role,
        token_hash=hash_token(token),
        created_by_id=owner.user.id,
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=settings.invite_ttl_hours),
    )
    db.add(invite)
    audit(db, request, settings, "invite_created", owner.user, email=body.email)
    return schemas.InviteCreated(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        invite_url=f"{settings.public_origin.rstrip('/')}/invite/{token}",
    )


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: uuid.UUID, owner: CurrentOwner, db: DbDep) -> None:
    invite = db.get(Invite, invite_id)
    if invite is None or invite.household_id != owner.household.id or invite.accepted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    db.delete(invite)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID, request: Request, owner: CurrentOwner, db: DbDep, settings: SettingsDep
) -> None:
    if user_id == owner.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The owner cannot remove themselves")
    membership = db.get(HouseholdMember, (owner.household.id, user_id))
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    user = membership.user
    # Deactivate instead of delete, so the audit trail keeps its references.
    user.is_active = False
    end_all_sessions(db, user)
    db.delete(membership)
    audit(db, request, settings, "member_removed", owner.user, member_email=user.email)
