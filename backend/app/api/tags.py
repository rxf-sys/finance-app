"""Household tags."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import finance_schemas as schemas
from app.api.common import conflict_on_duplicate, ensure_name_free
from app.deps import CurrentMember, DbDep, MemberContext
from app.models import Tag

router = APIRouter(prefix="/tags", tags=["tags"])

DUPLICATE_NAME = "A tag with this name already exists"


def _ensure_name_free(db: Session, member: MemberContext, name: str, exclude_id: uuid.UUID | None) -> None:
    query = select(Tag.name).where(Tag.household_id == member.household.id)
    if exclude_id is not None:
        query = query.where(Tag.id != exclude_id)
    ensure_name_free(db.scalars(query), name, DUPLICATE_NAME)


def _get_tag(db: Session, member: MemberContext, tag_id: uuid.UUID) -> Tag:
    tag = db.scalar(select(Tag).where(Tag.id == tag_id, Tag.household_id == member.household.id))
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    return tag


@router.get("")
def list_tags(member: CurrentMember, db: DbDep) -> list[schemas.TagOut]:
    tags = db.scalars(select(Tag).where(Tag.household_id == member.household.id).order_by(Tag.name, Tag.id))
    return [schemas.TagOut.model_validate(tag) for tag in tags]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tag(body: schemas.TagWrite, member: CurrentMember, db: DbDep) -> schemas.TagOut:
    _ensure_name_free(db, member, body.name, None)
    tag = Tag(id=uuid.uuid4(), household_id=member.household.id, name=body.name)
    with conflict_on_duplicate(db, DUPLICATE_NAME):
        db.add(tag)
    return schemas.TagOut.model_validate(tag)


@router.patch("/{tag_id}")
def rename_tag(tag_id: uuid.UUID, body: schemas.TagWrite, member: CurrentMember, db: DbDep) -> schemas.TagOut:
    tag = _get_tag(db, member, tag_id)
    _ensure_name_free(db, member, body.name, tag.id)
    with conflict_on_duplicate(db, DUPLICATE_NAME):
        tag.name = body.name
    return schemas.TagOut.model_validate(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    db.delete(_get_tag(db, member, tag_id))
