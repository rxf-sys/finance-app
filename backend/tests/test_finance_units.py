"""Pure unit tests: IBAN and text normalization, dedupe hashes, rule matching, default categories."""

import hashlib
import uuid
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance.dedupe import compute_dedupe_hash, random_dedupe_hash
from app.finance.default_categories import COLOR_TOKENS, DEFAULT_TREE, seed_default_categories
from app.finance.normalize import normalize_iban, normalize_text
from app.finance.rules import RuleConditions, matches
from app.models import Category, CategoryKind, Household, Transaction
from tests.helpers import IBAN_A, IBAN_EXTERNAL


def test_normalize_iban_accepts_spaced_lowercase() -> None:
    assert normalize_iban(" de89 3704 0044 0532 0130 00 ") == IBAN_A
    assert normalize_iban(IBAN_EXTERNAL) == IBAN_EXTERNAL
    assert normalize_iban("FR14 2004 1010 0505 0001 3M02 606") == "FR1420041010050500013M02606"


@pytest.mark.parametrize(
    "value",
    [
        "DE89370400440532013001",  # checksum off by one
        "DE00370400440532013000",  # check digits 00
        "DE8937040044053201300",  # a digit missing
        "XX",  # too short
        "",
        "1234567890123456",  # no country code
        "DE89-3704-0044-0532-0130-00",  # separators other than spaces
        "DE89370400440532013000" + "0" * 20,  # too long
    ],
)
def test_normalize_iban_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError, match="IBAN"):
        normalize_iban(value)


def test_normalize_text_casefolds_and_collapses_whitespace() -> None:
    assert normalize_text("  REWE \n Markt\tGmbH ") == "rewe markt gmbh"
    assert normalize_text("Straße") == normalize_text("STRASSE")
    assert normalize_text("   ") == ""


def test_dedupe_hash_is_stable_and_matches_the_documented_format() -> None:
    account_id = uuid.UUID(int=1)
    args = (account_id, date(2026, 3, 1), -1250, IBAN_A, "  Miete  März ", 0)
    first = compute_dedupe_hash(*args)
    assert first == compute_dedupe_hash(*args)
    expected = f"{account_id}|2026-03-01|-1250|{IBAN_A}|miete märz|0"
    assert first == hashlib.sha256(expected.encode()).hexdigest()
    assert len(first) == 64


def test_dedupe_hash_changes_with_each_field() -> None:
    account_id = uuid.UUID(int=1)
    base = compute_dedupe_hash(account_id, date(2026, 3, 1), -1250, None, "x", 0)
    variants = [
        compute_dedupe_hash(uuid.UUID(int=2), date(2026, 3, 1), -1250, None, "x", 0),
        compute_dedupe_hash(account_id, date(2026, 3, 2), -1250, None, "x", 0),
        compute_dedupe_hash(account_id, date(2026, 3, 1), -1251, None, "x", 0),
        compute_dedupe_hash(account_id, date(2026, 3, 1), -1250, IBAN_A, "x", 0),
        compute_dedupe_hash(account_id, date(2026, 3, 1), -1250, None, "y", 0),
        compute_dedupe_hash(account_id, date(2026, 3, 1), -1250, None, "x", 1),
    ]
    assert len({base, *variants}) == 7
    # A missing purpose and an empty one hash alike.
    assert compute_dedupe_hash(account_id, date(2026, 3, 1), 1, None, None, 0) == compute_dedupe_hash(
        account_id, date(2026, 3, 1), 1, None, "", 0
    )


def test_random_dedupe_hash_is_unique() -> None:
    assert random_dedupe_hash() != random_dedupe_hash()
    assert len(random_dedupe_hash()) == 64


def _tx(**kwargs: object) -> Transaction:
    defaults: dict[str, object] = {
        "account_id": uuid.UUID(int=7),
        "amount_cents": -1999,
        "counterparty_name": "REWE Markt GmbH",
        "counterparty_iban": IBAN_A,
        "purpose": "Einkauf 12.03.",
        "booking_text": "Lastschrift",
    }
    return Transaction(**{**defaults, **kwargs})


def test_rule_conditions_need_at_least_one_field_and_reject_unknown() -> None:
    with pytest.raises(ValidationError):
        RuleConditions()
    with pytest.raises(ValidationError):
        RuleConditions(counterparty_contains="x", color="red")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RuleConditions(counterparty_contains="   ")
    with pytest.raises(ValidationError):
        RuleConditions(counterparty_iban="DE89370400440532013001")
    with pytest.raises(ValidationError):
        RuleConditions(amount_min_cents=10, amount_max_cents=5)
    with pytest.raises(ValidationError):
        RuleConditions(direction="sideways")


def test_rule_conditions_normalize_and_serialize_to_json() -> None:
    account_id = uuid.uuid4()
    cond = RuleConditions(
        counterparty_contains="  REWE  ",
        counterparty_iban="de89 3704 0044 0532 0130 00",
        account_id=account_id,
    )
    assert cond.to_json() == {
        "counterparty_contains": "rewe",
        "counterparty_iban": IBAN_A,
        "account_id": str(account_id),
    }
    assert RuleConditions.model_validate(cond.to_json()) == cond


def test_matches_text_is_a_normalized_substring_test() -> None:
    tx = _tx()
    assert matches(RuleConditions(counterparty_contains="rewe markt"), tx)
    assert matches(RuleConditions(counterparty_contains="REWE"), tx)
    assert not matches(RuleConditions(counterparty_contains="edeka"), tx)
    assert matches(RuleConditions(purpose_contains="einkauf"), tx)
    assert matches(RuleConditions(booking_text_contains="lastschrift"), tx)
    assert not matches(RuleConditions(booking_text_contains="gutschrift"), tx)


def test_matches_missing_fields_never_match_text_conditions() -> None:
    tx = _tx(counterparty_name=None, purpose=None, booking_text=None, counterparty_iban=None)
    assert not matches(RuleConditions(counterparty_contains="rewe"), tx)
    assert not matches(RuleConditions(purpose_contains="x"), tx)
    assert not matches(RuleConditions(booking_text_contains="x"), tx)
    assert not matches(RuleConditions(counterparty_iban=IBAN_A), tx)


def test_matches_iban_ignores_spacing_and_case_of_stored_value() -> None:
    assert matches(
        RuleConditions(counterparty_iban=IBAN_A), _tx(counterparty_iban="de89 3704 0044 0532 0130 00")
    )
    assert not matches(RuleConditions(counterparty_iban=IBAN_EXTERNAL), _tx())


def test_matches_amount_uses_the_signed_amount() -> None:
    tx = _tx(amount_cents=-1999)
    assert matches(RuleConditions(amount_min_cents=-2000, amount_max_cents=-1000), tx)
    assert not matches(RuleConditions(amount_min_cents=1000), tx)  # an expense is not "at least +10 EUR"
    assert matches(RuleConditions(amount_max_cents=-1999), tx)
    assert not matches(RuleConditions(amount_max_cents=-2000), tx)


def test_matches_direction_and_account() -> None:
    assert matches(RuleConditions(direction="out"), _tx(amount_cents=-5))
    assert not matches(RuleConditions(direction="in"), _tx(amount_cents=-5))
    assert matches(RuleConditions(direction="in"), _tx(amount_cents=5))
    assert matches(RuleConditions(account_id=uuid.UUID(int=7)), _tx())
    assert not matches(RuleConditions(account_id=uuid.UUID(int=8)), _tx())


def test_matches_requires_all_conditions() -> None:
    tx = _tx()
    assert matches(RuleConditions(counterparty_contains="rewe", direction="out", amount_max_cents=-1), tx)
    assert not matches(RuleConditions(counterparty_contains="rewe", direction="in"), tx)


def test_default_tree_shape() -> None:
    names = [top.name for top in DEFAULT_TREE]
    assert len(names) == len(set(names)) == 15
    assert all(top.icon for top in DEFAULT_TREE)
    assert {top.name for top in DEFAULT_TREE if top.kind is CategoryKind.INCOME} == {"Einnahmen"}
    assert {top.name for top in DEFAULT_TREE if top.kind is CategoryKind.TRANSFER} == {"Umbuchung"}
    assert sum(len(top.children) for top in DEFAULT_TREE) == 45
    assert len(COLOR_TOKENS) == 8


def test_seed_default_categories_creates_tree_with_inherited_kind_and_color(db: Session) -> None:
    household = Household(id=uuid.uuid4(), name="Seed")
    db.add(household)
    db.flush()

    created = seed_default_categories(db, household.id)
    db.commit()

    categories = db.scalars(select(Category).where(Category.household_id == household.id)).all()
    assert created == len(categories) == 15 + 45
    by_id = {c.id: c for c in categories}
    for category in categories:
        if category.parent_id is not None:
            parent = by_id[category.parent_id]
            assert parent.parent_id is None
            assert (category.kind, category.color) == (parent.kind, parent.color)
        else:
            assert category.icon and category.color in COLOR_TOKENS
    umbuchung = next(c for c in categories if c.name == "Umbuchung")
    assert {c.name for c in categories if c.parent_id == umbuchung.id} == {"Eigene Konten", "Sparen"}
