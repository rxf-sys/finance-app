"""Two-level category tree, scoped to the caller's household."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.api import finance_schemas as schemas
from app.api.common import conflict_on_duplicate
from app.deps import CurrentMember, DbDep, MemberContext
from app.finance import reporting
from app.finance.default_categories import seed_default_categories
from app.models import Category, Transaction

router = APIRouter(prefix="/categories", tags=["categories"])

DUPLICATE_NAME = "A category with this name already exists here"


def get_category(db: Session, member: MemberContext, category_id: uuid.UUID) -> Category:
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.household_id == member.household.id)
    )
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category


def _list(db: Session, member: MemberContext) -> list[schemas.CategoryOut]:
    counts = reporting.category_line_counts(db, member)
    categories = db.scalars(
        select(Category)
        .where(Category.household_id == member.household.id)
        .order_by(Category.parent_id.is_not(None), Category.name, Category.id)
    )
    return [
        schemas.CategoryOut(
            id=c.id,
            parent_id=c.parent_id,
            name=c.name,
            kind=c.kind,
            icon=c.icon,
            color=c.color,
            transaction_count=counts.get(c.id, 0),
        )
        for c in categories
    ]


def _out(db: Session, member: MemberContext, category: Category) -> schemas.CategoryOut:
    counts = reporting.category_line_counts(db, member)
    return schemas.CategoryOut(
        id=category.id,
        parent_id=category.parent_id,
        name=category.name,
        kind=category.kind,
        icon=category.icon,
        color=category.color,
        transaction_count=counts.get(category.id, 0),
    )


@router.get("")
def list_categories(member: CurrentMember, db: DbDep) -> list[schemas.CategoryOut]:
    return _list(db, member)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(body: schemas.CategoryCreate, member: CurrentMember, db: DbDep) -> schemas.CategoryOut:
    if body.parent_id is not None:
        parent = get_category(db, member, body.parent_id)
        if parent.parent_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "The parent must be a top-level category"
            )
        kind = parent.kind
        color = body.color if body.color is not None else parent.color
    else:
        if body.kind is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A top-level category needs a kind")
        kind = body.kind
        color = body.color
    category = Category(
        id=uuid.uuid4(),
        household_id=member.household.id,
        parent_id=body.parent_id,
        name=body.name,
        kind=kind,
        icon=body.icon,
        color=color,
    )
    with conflict_on_duplicate(db, DUPLICATE_NAME):
        db.add(category)
    return _out(db, member, category)


@router.post("/defaults", status_code=status.HTTP_201_CREATED)
def seed_defaults(member: CurrentMember, db: DbDep) -> list[schemas.CategoryOut]:
    exists = db.scalar(select(Category.id).where(Category.household_id == member.household.id).limit(1))
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The household already has categories")
    seed_default_categories(db, member.household.id)
    return _list(db, member)


@router.patch("/{category_id}")
def update_category(
    category_id: uuid.UUID, body: schemas.CategoryUpdate, member: CurrentMember, db: DbDep
) -> schemas.CategoryOut:
    category = get_category(db, member, category_id)
    fields = body.model_fields_set
    if body.kind is not None and category.parent_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The kind can only be changed on a top-level category"
        )
    with conflict_on_duplicate(db, DUPLICATE_NAME):
        if body.name is not None:
            category.name = body.name
        if "icon" in fields:
            category.icon = body.icon
        if "color" in fields:
            category.color = body.color
        if body.kind is not None and body.kind != category.kind:
            category.kind = body.kind
            db.execute(update(Category).where(Category.parent_id == category.id).values(kind=body.kind))
    return _out(db, member, category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    category = get_category(db, member, category_id)
    ids = [category.id, *db.scalars(select(Category.id).where(Category.parent_id == category.id))]
    # Foreign keys null the category on transactions and splits and drop the rules that used it.
    # The category source is cleared here so rules may categorize those transactions again.
    db.execute(
        update(Transaction)
        .where(Transaction.household_id == member.household.id, Transaction.category_id.in_(ids))
        .values(category_source=None, rule_id=None)
    )
    # A Core delete lets the database cascade to children; the ORM would orphan them instead.
    db.execute(delete(Category).where(Category.id == category.id))
