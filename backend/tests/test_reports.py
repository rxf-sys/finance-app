from datetime import date

from sqlalchemy.orm import Session

from app.finance.reports import savings_rate_bp
from app.models import AccountVisibility, CategoryKind, TransactionSplit
from tests.helpers import World, make_account, make_category, make_tx

YEAR = "/api/reports/year"
CATEGORIES = "/api/reports/categories"


def test_savings_rate_bp() -> None:
    assert savings_rate_bp(0, -100) is None
    assert savings_rate_bp(10_000, 2_500) == 2_500
    assert savings_rate_bp(30_000, 10_000) == 3_333
    assert savings_rate_bp(30_000, 20_000) == 6_667
    assert savings_rate_bp(10_000, -5_000) == -5_000


def test_year_report(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    other = make_account(db, world.owner_user, "Zweit")
    secret = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    make_tx(db, account, 300_000, date(2026, 1, 25))
    make_tx(db, account, -100_000, date(2026, 1, 3))
    make_tx(db, account, -50_000, date(2026, 3, 3))
    make_tx(db, account, 10_000, date(2025, 12, 31))  # other year
    make_tx(db, account, 10_000, date(2027, 1, 1))  # other year
    out = make_tx(db, account, -7_000, date(2026, 2, 2))
    inc = make_tx(db, other, 7_000, date(2026, 2, 2))
    out.transfer_peer_id, inc.transfer_peer_id = inc.id, out.id
    make_tx(db, secret, 999_999, date(2026, 1, 5))
    db.commit()

    body = world.member.get(YEAR, params={"year": 2026}).json()
    assert body["year"] == 2026
    assert [m["month"] for m in body["months"]] == [f"2026-{n:02d}" for n in range(1, 13)]
    jan, feb, mar = body["months"][:3]
    assert (jan["income_cents"], jan["expense_cents"], jan["saldo_cents"]) == (300_000, -100_000, 200_000)
    assert jan["savings_rate_bp"] == 6_667
    assert (feb["income_cents"], feb["expense_cents"], feb["savings_rate_bp"]) == (0, 0, None)
    assert (mar["income_cents"], mar["expense_cents"], mar["saldo_cents"]) == (0, -50_000, -50_000)
    assert mar["savings_rate_bp"] is None
    assert (body["income_cents"], body["expense_cents"], body["saldo_cents"]) == (300_000, -150_000, 150_000)
    assert body["savings_rate_bp"] == 5_000

    owner = world.owner.get(YEAR, params={"year": 2026}).json()
    assert owner["income_cents"] == 300_000 + 999_999


def test_year_report_validation_and_isolation(world: World, db: Session) -> None:
    make_tx(db, make_account(db, world.owner_user), 100, date(2026, 1, 1))
    assert world.owner.get(YEAR).status_code == 422
    assert world.owner.get(YEAR, params={"year": 1800}).status_code == 422
    body = world.stranger.get(YEAR, params={"year": 2026}).json()
    assert body["income_cents"] == 0 and body["expense_cents"] == 0
    assert body["savings_rate_bp"] is None


def test_category_report(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    hid = account.household_id
    food = make_category(db, hid, "Essen")
    eating = make_category(db, hid, "Restaurant", parent=food)
    market = make_category(db, hid, "Supermarkt", parent=food)
    car = make_category(db, hid, "Auto")
    salary = make_category(db, hid, "Gehalt", CategoryKind.INCOME)
    transfer = make_category(db, hid, "Umbuchung", CategoryKind.TRANSFER)

    make_tx(db, account, -3_000, date(2026, 1, 5), category=eating)
    make_tx(db, account, -2_000, date(2026, 2, 5), category=eating)
    make_tx(db, account, -10_000, date(2026, 1, 6), category=market)
    make_tx(db, account, -500, date(2026, 1, 7), category=food)
    make_tx(db, account, -40_000, date(2026, 12, 31), category=car)
    make_tx(db, account, -1_234, date(2026, 5, 1))  # uncategorized
    make_tx(db, account, -9_999, date(2026, 5, 2), category=transfer)  # excluded
    make_tx(db, account, 700, date(2026, 1, 8), category=market)  # refund: not an expense
    make_tx(db, account, -9_999, date(2025, 12, 31), category=car)
    make_tx(db, account, 250_000, date(2026, 1, 25), category=salary)
    split = make_tx(db, account, -6_000, date(2026, 3, 9), category=car)  # parent category is ignored
    db.add_all(
        [
            TransactionSplit(transaction_id=split.id, position=0, amount_cents=-4_000, category_id=market.id),
            TransactionSplit(transaction_id=split.id, position=1, amount_cents=-2_000, category_id=car.id),
        ]
    )
    db.commit()

    body = world.member.get(CATEGORIES, params={"year": 2026, "kind": "expense"}).json()
    assert body["kind"] == "expense"
    names = [r["name"] for r in body["rows"]]
    assert names == ["Auto", "Essen"]  # 42,000 before 19,500
    auto, essen = body["rows"]
    assert auto["total_cents"] == -42_000
    assert auto["months_cents"][11] == -40_000
    assert auto["months_cents"][2] == -2_000
    assert auto["children"] == []
    assert essen["total_cents"] == -(3_000 + 2_000 + 10_000 + 500 + 4_000)
    assert essen["months_cents"][0] == -(3_000 + 10_000 + 500)
    assert essen["months_cents"][1] == -2_000
    assert essen["months_cents"][2] == -4_000
    assert [(c["name"], c["total_cents"]) for c in essen["children"]] == [
        ("Supermarkt", -14_000),
        ("Restaurant", -5_000),
    ]
    assert len(essen["months_cents"]) == 12
    assert body["uncategorized"]["category_id"] is None
    assert body["uncategorized"]["months_cents"][4] == -1_234
    assert body["uncategorized"]["total_cents"] == -1_234
    assert body["totals_cents"][0] == -(3_000 + 10_000 + 500)
    assert body["totals_cents"][4] == -1_234
    assert body["total_cents"] == -(42_000 + 19_500 + 1_234)
    assert sum(body["totals_cents"]) == body["total_cents"]

    income = world.member.get(CATEGORIES, params={"year": 2026, "kind": "income"}).json()
    assert [(r["name"], r["total_cents"]) for r in income["rows"]] == [("Essen", 700), ("Gehalt", 250_000)][
        ::-1
    ]
    assert income["rows"][1]["children"][0]["name"] == "Supermarkt"
    assert income["total_cents"] == 250_700
    assert income["uncategorized"]["total_cents"] == 0

    assert world.member.get(CATEGORIES, params={"year": 2026, "kind": "bogus"}).status_code == 422


def test_category_report_isolation(world: World, db: Session) -> None:
    shared = make_account(db, world.owner_user)
    secret = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    cat = make_category(db, shared.household_id, "Hobby")
    make_tx(db, shared, -1_000, date(2026, 4, 1), category=cat)
    make_tx(db, secret, -5_000, date(2026, 4, 2), category=cat)

    member = world.member.get(CATEGORIES, params={"year": 2026}).json()
    assert member["total_cents"] == -1_000
    owner = world.owner.get(CATEGORIES, params={"year": 2026}).json()
    assert owner["total_cents"] == -6_000
    stranger = world.stranger.get(CATEGORIES, params={"year": 2026}).json()
    assert stranger["rows"] == [] and stranger["total_cents"] == 0
    assert stranger["totals_cents"] == [0] * 12
