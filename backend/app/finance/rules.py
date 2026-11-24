"""Categorization rules: condition model, matching, bulk application and learning from corrections."""

import uuid
from collections.abc import Iterable
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app.deps import MemberContext
from app.finance.access import visible_transaction_clause
from app.finance.normalize import normalize_iban, normalize_text
from app.models import CategoryRule, CategorySource, RuleSource, Transaction

_MAX_CENTS = 10**13


class RuleConditions(BaseModel):
    """All set fields must match (AND). Text fields are stored normalized."""

    model_config = ConfigDict(extra="forbid")

    counterparty_contains: str | None = Field(default=None, max_length=200)
    counterparty_iban: str | None = None
    purpose_contains: str | None = Field(default=None, max_length=200)
    booking_text_contains: str | None = Field(default=None, max_length=100)
    amount_min_cents: int | None = Field(default=None, ge=-_MAX_CENTS, le=_MAX_CENTS)
    amount_max_cents: int | None = Field(default=None, ge=-_MAX_CENTS, le=_MAX_CENTS)
    direction: Literal["in", "out"] | None = None
    account_id: uuid.UUID | None = None

    @field_validator("counterparty_contains", "purpose_contains", "booking_text_contains")
    @classmethod
    def _normalize_text_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("Must not be empty")
        return normalized

    @field_validator("counterparty_iban")
    @classmethod
    def _normalize_iban_field(cls, value: str | None) -> str | None:
        return None if value is None else normalize_iban(value)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if not self.model_fields_set or all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("At least one condition is required")
        if (
            self.amount_min_cents is not None
            and self.amount_max_cents is not None
            and self.amount_min_cents > self.amount_max_cents
        ):
            raise ValueError("amount_min_cents must not exceed amount_max_cents")
        return self

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def _contains(needle: str, haystack: str | None) -> bool:
    return haystack is not None and needle in normalize_text(haystack)


def _same_iban(wanted: str, actual: str | None) -> bool:
    return actual is not None and "".join(actual.split()).upper() == wanted


def matches(cond: RuleConditions, tx: Transaction) -> bool:
    """AND of all set conditions; text matching is a substring test on normalized text."""
    checks = (
        cond.counterparty_contains is None or _contains(cond.counterparty_contains, tx.counterparty_name),
        cond.counterparty_iban is None or _same_iban(cond.counterparty_iban, tx.counterparty_iban),
        cond.purpose_contains is None or _contains(cond.purpose_contains, tx.purpose),
        cond.booking_text_contains is None or _contains(cond.booking_text_contains, tx.booking_text),
        cond.amount_min_cents is None or tx.amount_cents >= cond.amount_min_cents,
        cond.amount_max_cents is None or tx.amount_cents <= cond.amount_max_cents,
        cond.direction is None or (tx.amount_cents > 0) == (cond.direction == "in"),
        cond.account_id is None or tx.account_id == cond.account_id,
    )
    return all(checks)


def _parse(rule: CategoryRule) -> RuleConditions | None:
    try:
        return RuleConditions.model_validate(rule.conditions)
    except ValidationError:
        return None  # a corrupt stored rule must not break categorization


def load_rules(db: Session, household_id: uuid.UUID) -> list[tuple[CategoryRule, RuleConditions]]:
    """Active rules in evaluation order: manual before learned, priority ascending, oldest first."""
    rules = db.scalars(
        select(CategoryRule)
        .where(CategoryRule.household_id == household_id, CategoryRule.is_active.is_(True))
        .order_by(
            case((CategoryRule.source == RuleSource.MANUAL, 0), else_=1),
            CategoryRule.priority,
            CategoryRule.created_at,
            CategoryRule.id,
        )
    )
    parsed = ((rule, _parse(rule)) for rule in rules)
    return [(rule, cond) for rule, cond in parsed if cond is not None]


def assign_category(
    db: Session,
    tx: Transaction,
    category_id: uuid.UUID | None,
    source: CategorySource | None,
    rule_id: uuid.UUID | None,
) -> None:
    tx.category_id = category_id
    tx.category_source = source
    tx.rule_id = rule_id
    db.expire(tx, ["category"])  # the relationship would otherwise keep the old category


def apply_rules(db: Session, household_id: uuid.UUID, transactions: Iterable[Transaction]) -> int:
    """Categorize non-manual, unsplit transactions with the first matching rule; return changes.

    A transaction that matched a rule earlier but matches none now keeps its category.
    """
    rules = load_rules(db, household_id)
    changed = 0
    for tx in transactions:
        if tx.category_source is CategorySource.MANUAL or tx.splits:
            continue
        for rule, cond in rules:
            if matches(cond, tx):
                if tx.category_id != rule.category_id or tx.rule_id != rule.id or tx.category_source is None:
                    assign_category(db, tx, rule.category_id, CategorySource.RULE, rule.id)
                    changed += 1
                break
    return changed


def learn_from_correction(
    db: Session, member: MemberContext, tx: Transaction, category_id: uuid.UUID
) -> CategoryRule | None:
    """Remember a manual categorization as a learned rule keyed on IBAN, else on counterparty name."""
    conditions: dict[str, Any] | None = None
    if tx.counterparty_iban:
        try:
            conditions = {"counterparty_iban": normalize_iban(tx.counterparty_iban)}
        except ValueError:
            conditions = None  # malformed IBAN in the bank export: fall back to the name
    if conditions is None and tx.counterparty_name:
        name = normalize_text(tx.counterparty_name)
        if name:
            conditions = {"counterparty_contains": name}
    if conditions is None:
        return None

    household_id = member.household.id
    for rule, cond in load_rules(db, household_id):
        if rule.source is RuleSource.MANUAL and rule.category_id == category_id and matches(cond, tx):
            return None

    existing = db.scalar(
        select(CategoryRule).where(
            CategoryRule.household_id == household_id,
            CategoryRule.source == RuleSource.LEARNED,
            CategoryRule.conditions == conditions,
        )
    )
    if existing is not None:
        existing.category_id = category_id
        existing.is_active = True
        return existing
    rule = CategoryRule(
        id=uuid.uuid4(),
        household_id=household_id,
        category_id=category_id,
        conditions=conditions,
        source=RuleSource.LEARNED,
        created_by_id=member.user.id,
        priority=100,
        is_active=True,
    )
    db.add(rule)
    db.flush()
    return rule


def apply_rule_to_similar(
    db: Session, member: MemberContext, rule: CategoryRule, exclude_id: uuid.UUID
) -> int:
    """Apply one rule to the other non-manual, unsplit transactions the member can see."""
    cond = _parse(rule)
    if cond is None:
        return 0
    candidates = db.scalars(
        select(Transaction)
        .where(
            visible_transaction_clause(member),
            Transaction.id != exclude_id,
            Transaction.category_source.is_distinct_from(CategorySource.MANUAL),
        )
        .options(selectinload(Transaction.splits))
    )
    changed = 0
    for tx in candidates:
        if tx.splits or not matches(cond, tx):
            continue
        if tx.category_id != rule.category_id or tx.rule_id != rule.id:
            assign_category(db, tx, rule.category_id, CategorySource.RULE, rule.id)
            changed += 1
    return changed


def apply_rules_for_member(db: Session, member: MemberContext) -> int:
    """Run all rules over every non-manual transaction the member can see."""
    transactions = db.scalars(
        select(Transaction)
        .where(
            visible_transaction_clause(member),
            Transaction.category_source.is_distinct_from(CategorySource.MANUAL),
        )
        .options(selectinload(Transaction.splits))
    )
    return apply_rules(db, member.household.id, transactions)
