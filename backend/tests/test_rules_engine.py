"""apply_rules and learn_from_correction against a real database."""

import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.finance.access import visible_transaction_clause
from app.finance.rules import (
    RuleConditions,
    apply_rule_to_similar,
    apply_rules,
    apply_rules_for_member,
    learn_from_correction,
    load_rules,
)
from app.models import (
    AccountVisibility,
    CategoryRule,
    CategorySource,
    HouseholdRole,
    RuleSource,
    Transaction,
    TransactionSplit,
)
from app.models.base import utcnow
from tests.conftest import UserFactory
from tests.helpers import IBAN_A, make_account, make_category, make_tx, member_of


def _rule(
    db: Session,
    household_id: uuid.UUID,
    category_id: uuid.UUID,
    conditions: RuleConditions,
    source: RuleSource = RuleSource.MANUAL,
    priority: int = 100,
    is_active: bool = True,
    age_minutes: int = 0,
) -> CategoryRule:
    rule = CategoryRule(
        id=uuid.uuid4(),
        household_id=household_id,
        category_id=category_id,
        priority=priority,
        conditions=conditions.to_json(),
        source=source,
        is_active=is_active,
        created_at=utcnow() - timedelta(minutes=age_minutes),
    )
    db.add(rule)
    db.commit()
    return rule


def test_apply_rules_categorizes_with_first_matching_rule(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    household_id = account.household_id
    groceries = make_category(db, household_id, "Lebensmittel")
    other = make_category(db, household_id, "Sonstiges")
    rule = _rule(db, household_id, groceries.id, RuleConditions(counterparty_contains="rewe"))
    hit = make_tx(db, account, -500, counterparty_name="REWE Markt")
    miss = make_tx(db, account, -500, counterparty_name="Bäckerei")
    _rule(db, household_id, other.id, RuleConditions(counterparty_contains="rewe"), priority=200)

    assert apply_rules(db, household_id, [hit, miss]) == 1

    assert (hit.category_id, hit.category_source, hit.rule_id) == (groceries.id, CategorySource.RULE, rule.id)
    assert (miss.category_id, miss.category_source, miss.rule_id) == (None, None, None)
    # A second run changes nothing.
    assert apply_rules(db, household_id, [hit, miss]) == 0


def test_apply_rules_never_touches_manual_categories(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    household_id = account.household_id
    groceries = make_category(db, household_id, "Lebensmittel")
    fun = make_category(db, household_id, "Freizeit")
    _rule(db, household_id, groceries.id, RuleConditions(counterparty_contains="rewe"))
    manual = make_tx(db, account, -500, counterparty_name="REWE", category=fun)
    manual.category_source = CategorySource.MANUAL
    db.commit()

    assert apply_rules(db, household_id, [manual]) == 0
    assert manual.category_id == fun.id and manual.rule_id is None

    assert apply_rules_for_member(db, member_of(user)) == 0
    db.refresh(manual)
    assert manual.category_id == fun.id


def test_apply_rules_skips_split_transactions(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    household_id = account.household_id
    groceries = make_category(db, household_id, "Lebensmittel")
    _rule(db, household_id, groceries.id, RuleConditions(counterparty_contains="rewe"))
    tx = make_tx(db, account, -500, counterparty_name="REWE")
    tx.splits = [
        TransactionSplit(id=uuid.uuid4(), position=0, amount_cents=-200),
        TransactionSplit(id=uuid.uuid4(), position=1, amount_cents=-300),
    ]
    db.commit()

    assert apply_rules(db, household_id, [tx]) == 0
    assert tx.category_id is None


def test_apply_rules_keeps_category_when_the_rule_no_longer_matches(
    db: Session, make_user: UserFactory
) -> None:
    user = make_user()
    account = make_account(db, user)
    household_id = account.household_id
    groceries = make_category(db, household_id, "Lebensmittel")
    rule = _rule(db, household_id, groceries.id, RuleConditions(counterparty_contains="rewe"))
    tx = make_tx(db, account, -500, counterparty_name="REWE")
    assert apply_rules(db, household_id, [tx]) == 1

    rule.conditions = RuleConditions(counterparty_contains="edeka").to_json()
    db.commit()

    assert apply_rules(db, household_id, [tx]) == 0
    assert (tx.category_id, tx.category_source, tx.rule_id) == (groceries.id, CategorySource.RULE, rule.id)


def test_rule_order_is_manual_first_then_priority_then_age(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    household_id = make_account(db, user).household_id
    category = make_category(db, household_id, "X")
    cond = RuleConditions(counterparty_contains="x")
    learned_first = _rule(db, household_id, category.id, cond, RuleSource.LEARNED, priority=1)
    manual_late = _rule(db, household_id, category.id, cond, priority=50, age_minutes=1)
    manual_early_low = _rule(db, household_id, category.id, cond, priority=5)
    manual_old = _rule(db, household_id, category.id, cond, priority=50, age_minutes=10)
    inactive = _rule(db, household_id, category.id, cond, priority=0, is_active=False)

    order = [rule.id for rule, _ in load_rules(db, household_id)]

    assert order == [manual_early_low.id, manual_old.id, manual_late.id, learned_first.id]
    assert inactive.id not in order


def test_manual_rule_wins_over_learned_rule(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    household_id = account.household_id
    learned_cat = make_category(db, household_id, "Gelernt")
    manual_cat = make_category(db, household_id, "Manuell")
    _rule(
        db, household_id, learned_cat.id, RuleConditions(counterparty_contains="rewe"), RuleSource.LEARNED, 1
    )
    _rule(db, household_id, manual_cat.id, RuleConditions(counterparty_contains="rewe"), priority=900)
    tx = make_tx(db, account, -500, counterparty_name="REWE")

    apply_rules(db, household_id, [tx])

    assert tx.category_id == manual_cat.id


def test_learn_creates_iban_rule(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    category = make_category(db, account.household_id, "Gehalt")
    tx = make_tx(db, account, 250000, counterparty_name="Arbeitgeber AG", counterparty_iban=IBAN_A)

    rule = learn_from_correction(db, member_of(user), tx, category.id)

    assert rule is not None
    assert rule.source is RuleSource.LEARNED and rule.category_id == category.id
    assert rule.conditions == {"counterparty_iban": IBAN_A}
    assert rule.created_by_id == user.id and rule.priority == 100


def test_learn_falls_back_to_normalized_counterparty_name(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    category = make_category(db, account.household_id, "Lebensmittel")

    named = make_tx(db, account, -500, counterparty_name="  REWE   Markt ")
    rule = learn_from_correction(db, member_of(user), named, category.id)
    assert rule is not None and rule.conditions == {"counterparty_contains": "rewe markt"}

    bad_iban = make_tx(db, account, -500, counterparty_name="Edeka", counterparty_iban="DE00BROKEN")
    fallback = learn_from_correction(db, member_of(user), bad_iban, category.id)
    assert fallback is not None and fallback.conditions == {"counterparty_contains": "edeka"}


def test_learn_skips_without_iban_and_name(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    category = make_category(db, account.household_id, "Sonstiges")

    for tx in (make_tx(db, account, -500), make_tx(db, account, -500, counterparty_name="   ")):
        assert learn_from_correction(db, member_of(user), tx, category.id) is None

    assert db.scalar(select(CategoryRule.id)) is None


def test_learn_updates_existing_learned_rule_instead_of_duplicating(
    db: Session, make_user: UserFactory
) -> None:
    user = make_user()
    account = make_account(db, user)
    first = make_category(db, account.household_id, "Erste")
    second = make_category(db, account.household_id, "Zweite")
    tx = make_tx(db, account, -500, counterparty_name="Kiosk")
    rule = learn_from_correction(db, member_of(user), tx, first.id)
    assert rule is not None
    rule.is_active = False

    again = learn_from_correction(db, member_of(user), tx, second.id)

    assert again is not None and again.id == rule.id
    assert again.category_id == second.id and again.is_active
    assert len(db.scalars(select(CategoryRule)).all()) == 1


def test_learn_skips_when_manual_rule_already_gives_the_same_category(
    db: Session, make_user: UserFactory
) -> None:
    user = make_user()
    account = make_account(db, user)
    household_id = account.household_id
    groceries = make_category(db, household_id, "Lebensmittel")
    other = make_category(db, household_id, "Sonstiges")
    _rule(db, household_id, groceries.id, RuleConditions(counterparty_contains="rewe"))
    tx = make_tx(db, account, -500, counterparty_name="REWE Markt")

    assert learn_from_correction(db, member_of(user), tx, groceries.id) is None
    # A different category is a real correction and is learned.
    assert learn_from_correction(db, member_of(user), tx, other.id) is not None
    # An inactive manual rule does not count.
    db.execute(update(CategoryRule).values(is_active=False).where(CategoryRule.source == RuleSource.MANUAL))
    db.commit()
    assert learn_from_correction(db, member_of(user), tx, groceries.id) is not None


def test_apply_rule_to_similar_only_touches_visible_non_manual(db: Session, make_user: UserFactory) -> None:
    owner = make_user()
    partner = make_user("partner@example.com", role=HouseholdRole.MEMBER)
    shared = make_account(db, owner, "Gemeinsam")
    private = make_account(db, owner, "Privat", AccountVisibility.PRIVATE)
    household_id = shared.household_id
    category = make_category(db, household_id, "Lebensmittel")
    fun = make_category(db, household_id, "Freizeit")
    source_tx = make_tx(db, shared, -100, counterparty_name="REWE")
    similar = make_tx(db, shared, -200, counterparty_name="Rewe Markt")
    unrelated = make_tx(db, shared, -300, counterparty_name="Kino")
    hidden = make_tx(db, private, -400, counterparty_name="REWE")
    manual = make_tx(db, shared, -500, counterparty_name="REWE", category=fun)
    manual.category_source = CategorySource.MANUAL
    db.commit()
    rule = _rule(
        db, household_id, category.id, RuleConditions(counterparty_contains="rewe"), RuleSource.LEARNED
    )

    assert apply_rule_to_similar(db, member_of(partner), rule, source_tx.id) == 1
    db.commit()

    for tx in (source_tx, similar, unrelated, hidden, manual):
        db.refresh(tx)
    assert similar.category_id == category.id and similar.category_source is CategorySource.RULE
    assert source_tx.category_id is None  # excluded explicitly
    assert unrelated.category_id is None
    assert hidden.category_id is None  # private account of someone else
    assert manual.category_id == fun.id

    assert apply_rules_for_member(db, member_of(partner)) == 1  # only source_tx is left; hidden stays out
    db.commit()
    db.refresh(hidden)
    assert hidden.category_id is None
    assert apply_rules_for_member(db, member_of(owner)) == 1
    assert (
        db.scalar(
            select(Transaction.id).where(
                visible_transaction_clause(member_of(partner)), Transaction.id == hidden.id
            )
        )
        is None
    )
