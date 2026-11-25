"""SQL reporting: splits, transfers, visibility and balance history."""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.finance import reporting
from app.models import AccountVisibility, CategoryKind, HouseholdRole, TransactionSplit, User
from tests.conftest import UserFactory
from tests.helpers import make_account, make_category, make_tx, member_of

MARCH = date(2026, 3, 1)


def _split(position: int, amount: int, category_id: uuid.UUID | None) -> TransactionSplit:
    return TransactionSplit(id=uuid.uuid4(), position=position, amount_cents=amount, category_id=category_id)


def _scenario(db: Session, make_user: UserFactory) -> tuple[User, User]:
    owner = make_user()
    partner = make_user("partner@example.com", role=HouseholdRole.MEMBER)
    giro = make_account(db, owner, "Giro", opening=100_000)
    savings = make_account(db, owner, "Sparen")
    secret = make_account(db, owner, "Privat", AccountVisibility.PRIVATE)
    hh = giro.household_id
    income = make_category(db, hh, "Einnahmen", kind=CategoryKind.INCOME)
    housing = make_category(db, hh, "Wohnen")
    rent = make_category(db, hh, "Miete", parent=housing)
    food = make_category(db, hh, "Lebensmittel")
    other = make_category(db, hh, "Sonstiges")
    transfer_top = make_category(db, hh, "Umbuchung", kind=CategoryKind.TRANSFER)
    saving = make_category(db, hh, "Sparen", parent=transfer_top)

    make_tx(db, giro, 300_000, date(2026, 3, 1), category=income)
    make_tx(db, giro, -100_000, date(2026, 3, 3), category=rent)
    make_tx(db, giro, -20_000, date(2026, 3, 31), category=food)
    make_tx(db, giro, -5_000, date(2026, 3, 10))  # uncategorized
    make_tx(db, giro, -1_000, date(2026, 2, 28), category=food)  # previous month
    make_tx(db, giro, -777, date(2026, 4, 1), category=food)  # next month

    split_parent = make_tx(db, giro, -30_000, date(2026, 3, 12), category=other)
    split_parent.splits = [_split(0, -10_000, food.id), _split(1, -20_000, rent.id)]

    out = make_tx(db, giro, -50_000, date(2026, 3, 15), category=food)  # paired transfer keeps its category
    back = make_tx(db, savings, 50_000, date(2026, 3, 15))
    out.transfer_peer_id, back.transfer_peer_id = back.id, out.id
    make_tx(db, giro, -7_000, date(2026, 3, 20), category=saving)  # transfer by category
    make_tx(db, giro, 4_000, date(2026, 3, 21), category=transfer_top)

    make_tx(db, secret, -9_999, date(2026, 3, 5), category=food)
    db.commit()
    return owner, partner


def test_monthly_flows_use_splits_and_exclude_transfers(db: Session, make_user: UserFactory) -> None:
    owner, partner = _scenario(db, make_user)

    partner_flows = reporting.monthly_flows(db, member_of(partner), date(2026, 2, 1), date(2026, 4, 1))
    assert partner_flows == [
        ("2026-02", 0, 1_000),
        ("2026-03", 300_000, 100_000 + 20_000 + 30_000 + 5_000),
        ("2026-04", 0, 777),
    ]

    owner_flows = reporting.monthly_flows(db, member_of(owner), MARCH, MARCH)
    assert owner_flows == [("2026-03", 300_000, 155_000 + 9_999)]


def test_monthly_flows_include_empty_months(db: Session, make_user: UserFactory) -> None:
    owner, _ = _scenario(db, make_user)

    flows = reporting.monthly_flows(db, member_of(owner), date(2025, 12, 1), date(2026, 2, 1))

    assert [key for key, _, _ in flows] == ["2025-12", "2026-01", "2026-02"]
    assert flows[0][1:] == (0, 0) and flows[2][1:] == (0, 1_000)


def test_top_categories_group_by_top_level_and_resolve_splits(db: Session, make_user: UserFactory) -> None:
    _, partner = _scenario(db, make_user)

    totals = reporting.top_expense_categories(db, member_of(partner), MARCH)

    assert [(t.name, t.amount_cents) for t in totals] == [
        ("Wohnen", 100_000 + 20_000),  # rent plus the rent part of the split
        ("Lebensmittel", 20_000 + 10_000),
        (None, 5_000),  # uncategorized bucket
    ]
    assert totals[2].category_id is None


def test_top_categories_is_limited_to_six(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    for index in range(8):
        category = make_category(db, account.household_id, f"Kategorie {index}")
        make_tx(db, account, -(index + 1) * 100, MARCH, category=category)

    totals = reporting.top_expense_categories(db, member_of(user), MARCH)

    assert [t.amount_cents for t in totals] == [800, 700, 600, 500, 400, 300]


def test_split_without_category_counts_as_uncategorized(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    account = make_account(db, user)
    food = make_category(db, account.household_id, "Lebensmittel")
    tx = make_tx(db, account, -1_000, MARCH)
    tx.splits = [_split(0, -400, food.id), _split(1, -600, None)]
    db.commit()

    totals = reporting.top_expense_categories(db, member_of(user), MARCH)

    assert [(t.name, t.amount_cents) for t in totals] == [(None, 600), ("Lebensmittel", 400)]
    assert reporting.uncategorized_count(db, member_of(user)) == 0  # split parents are not "uncategorized"


def test_splits_of_a_paired_transfer_are_excluded(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    a, b = make_account(db, user, "A"), make_account(db, user, "B")
    food = make_category(db, a.household_id, "Lebensmittel")
    out = make_tx(db, a, -1_000, MARCH)
    out.splits = [_split(0, -400, food.id), _split(1, -600, food.id)]
    back = make_tx(db, b, 1_000, MARCH)
    out.transfer_peer_id, back.transfer_peer_id = back.id, out.id
    db.commit()

    assert reporting.monthly_flows(db, member_of(user), MARCH, MARCH) == [("2026-03", 0, 0)]
    assert reporting.top_expense_categories(db, member_of(user), MARCH) == []


def test_uncategorized_count_ignores_transfers_and_hidden_accounts(
    db: Session, make_user: UserFactory
) -> None:
    owner, partner = _scenario(db, make_user)

    # only the plain giro row counts: the paired savings row is a transfer, split parents are categorized
    assert reporting.uncategorized_count(db, member_of(partner)) == 1
    assert reporting.uncategorized_count(db, member_of(owner)) == 1


def test_account_stats_and_category_counts(db: Session, make_user: UserFactory) -> None:
    owner, partner = _scenario(db, make_user)

    stats = {s.account.name: s for s in reporting.account_stats(db, member_of(partner))}
    assert set(stats) == {"Giro", "Sparen"}  # the private account is invisible
    giro = stats["Giro"]
    assert giro.transaction_count == 10
    assert giro.last_booking_date == date(2026, 4, 1)
    assert (
        giro.balance_cents
        == 100_000 + 300_000 - 100_000 - 20_000 - 5_000 - 1_000 - 777 - 30_000 - 50_000 - 7_000 + 4_000
    )
    assert stats["Sparen"].balance_cents == 50_000

    owner_stats = reporting.account_stats(db, member_of(owner), include_archived=False)
    assert [s.account.name for s in owner_stats] == ["Giro", "Privat", "Sparen"]

    counts = reporting.category_line_counts(db, member_of(partner))
    # income 1, rent 2 (incl. split part), food 5 (3 plain, split part, paired transfer), two transfer rows
    assert sorted(counts.values()) == [1, 1, 1, 2, 5]


def test_balance_history_fills_months_and_starts_from_prior_balance(
    db: Session, make_user: UserFactory
) -> None:
    user = make_user()
    account = make_account(db, user, opening=1_000)
    this_month = reporting.current_month()
    make_tx(db, account, 100, reporting.add_months(this_month, -6))  # before the window
    make_tx(db, account, -200, reporting.add_months(this_month, -2).replace(day=15))
    make_tx(db, account, 500, this_month)

    history = reporting.balance_history(db, account, 4)

    keys = [reporting.month_key(reporting.add_months(this_month, offset)) for offset in (-3, -2, -1, 0)]
    assert history == [(keys[0], 1_100), (keys[1], 900), (keys[2], 900), (keys[3], 1_400)]


def test_month_helpers() -> None:
    assert reporting.add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert reporting.add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert reporting.parse_month("2026-07") == date(2026, 7, 1)
    assert reporting.month_key(date(2026, 7, 1)) == "2026-07"
