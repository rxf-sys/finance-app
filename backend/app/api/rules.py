"""Categorization rules: CRUD plus a bulk "apply" over everything the caller can see."""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.api import finance_schemas as schemas
from app.api.categories import get_category
from app.deps import CurrentMember, DbDep, MemberContext
from app.finance.access import get_visible_account, get_visible_rule, visible_rule_clause
from app.finance.rules import RuleConditions, apply_rules_for_member
from app.models import CategoryRule, RuleSource

router = APIRouter(prefix="/rules", tags=["rules"])


def _out(rule: CategoryRule) -> schemas.RuleOut:
    return schemas.RuleOut.model_validate(rule, from_attributes=True)


def _check_conditions(db: Session, member: MemberContext, conditions: RuleConditions) -> None:
    if conditions.account_id is not None:
        get_visible_account(db, member, conditions.account_id)


@router.get("")
def list_rules(member: CurrentMember, db: DbDep) -> list[schemas.RuleOut]:
    rules = db.scalars(
        select(CategoryRule)
        .where(visible_rule_clause(member))
        .order_by(
            case((CategoryRule.source == RuleSource.MANUAL, 0), else_=1),
            CategoryRule.priority,
            CategoryRule.created_at,
            CategoryRule.id,
        )
    )
    return [_out(rule) for rule in rules]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_rule(body: schemas.RuleCreate, member: CurrentMember, db: DbDep) -> schemas.RuleOut:
    get_category(db, member, body.category_id)
    _check_conditions(db, member, body.conditions)
    rule = CategoryRule(
        id=uuid.uuid4(),
        household_id=member.household.id,
        category_id=body.category_id,
        priority=body.priority,
        conditions=body.conditions.to_json(),
        source=RuleSource.MANUAL,
        is_active=body.is_active,
        created_by_id=member.user.id,
    )
    db.add(rule)
    db.flush()
    db.refresh(rule)  # load the server-side created_at
    return _out(rule)


@router.post("/apply")
def apply_all_rules(member: CurrentMember, db: DbDep) -> schemas.RulesApplied:
    return schemas.RulesApplied(updated=apply_rules_for_member(db, member))


@router.patch("/{rule_id}")
def update_rule(
    rule_id: uuid.UUID, body: schemas.RuleUpdate, member: CurrentMember, db: DbDep
) -> schemas.RuleOut:
    rule = get_visible_rule(db, member, rule_id)
    if body.category_id is not None:
        get_category(db, member, body.category_id)
        rule.category_id = body.category_id
    if body.conditions is not None:
        _check_conditions(db, member, body.conditions)
        rule.conditions = body.conditions.to_json()
    if body.priority is not None:
        rule.priority = body.priority
    if body.is_active is not None:
        rule.is_active = body.is_active
    db.flush()
    return _out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: uuid.UUID, member: CurrentMember, db: DbDep) -> None:
    db.delete(get_visible_rule(db, member, rule_id))
