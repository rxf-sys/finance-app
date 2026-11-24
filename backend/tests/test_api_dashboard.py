from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from app.finance import reporting
from tests.helpers import IBAN_A, IBAN_B, World

DASHBOARD = "/api/dashboard"


def _account(client: TestClient, name: str, **extra: Any) -> str:
    response = client.post("/api/accounts", json={"name": name, "kind": "giro", **extra})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _category(client: TestClient, name: str, kind: str = "expense", parent_id: str | None = None) -> str:
    body: dict[str, Any] = {"name": name, "kind": kind}
    if parent_id:
        body["parent_id"] = parent_id
    return str(client.post("/api/categories", json=body).json()["id"])


def _tx(client: TestClient, account: str, amount: int, day: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        "/api/transactions",
        json={"account_id": account, "booking_date": day, "amount_cents": amount, **extra},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _build(world: World) -> dict[str, str]:
    giro = _account(world.owner, "Giro", opening_balance_cents=100_000, iban=IBAN_A)
    savings = _account(world.owner, "Sparen", iban=IBAN_B)
    private = _account(world.owner, "Privat", visibility="private", opening_balance_cents=7_000)
    archived = _account(world.owner, "Alt", opening_balance_cents=999)
    world.owner.patch(f"/api/accounts/{archived}", json={"is_archived": True})
    income = _category(world.owner, "Einnahmen", "income")
    housing = _category(world.owner, "Wohnen")
    rent = _category(world.owner, "Miete", parent_id=housing)
    food = _category(world.owner, "Lebensmittel")
    umbuchung = _category(world.owner, "Umbuchung", "transfer")

    _tx(world.owner, giro, 300_000, "2026-03-01", category_id=income)
    _tx(world.owner, giro, -100_000, "2026-03-03", category_id=rent)
    _tx(world.owner, giro, -20_000, "2026-03-04", category_id=food)
    _tx(world.owner, giro, -5_000, "2026-03-10")
    split = _tx(world.owner, giro, -30_000, "2026-03-12", category_id=food)
    world.owner.put(
        f"/api/transactions/{split['id']}/splits",
        json=[{"amount_cents": -10_000, "category_id": food}, {"amount_cents": -20_000, "category_id": rent}],
    )
    _tx(world.owner, giro, -50_000, "2026-03-15", counterparty_iban=IBAN_B)
    _tx(world.owner, savings, 50_000, "2026-03-16")  # pairs with the row above
    _tx(world.owner, giro, -7_000, "2026-03-20", category_id=umbuchung)
    _tx(world.owner, giro, -2_000, "2026-02-10", category_id=food)
    _tx(world.owner, private, -9_999, "2026-03-05", category_id=food)
    _tx(world.owner, private, 1_234, "2026-03-06")
    return {"giro": giro, "savings": savings, "private": private, "archived": archived}


def test_dashboard_for_a_month(world: World) -> None:
    ids = _build(world)

    body = world.member.get(DASHBOARD, params={"month": "2026-03"}).json()

    assert body["month"] == "2026-03"
    assert [(a["name"], a["balance_cents"], a["is_mine"]) for a in body["accounts"]] == [
        ("Giro", 100_000 + 300_000 - 100_000 - 20_000 - 5_000 - 30_000 - 50_000 - 7_000 - 2_000, False),
        ("Sparen", 50_000, False),
    ]
    assert ids["private"] not in str(body) and ids["archived"] not in str(body)
    assert body["net_worth_cents"] == sum(a["balance_cents"] for a in body["accounts"])
    assert body["income_cents"] == 300_000
    assert body["expense_cents"] == 100_000 + 20_000 + 30_000 + 5_000
    assert body["net_cents"] == 300_000 - 155_000
    assert [(c["name"], c["amount_cents"]) for c in body["top_categories"]] == [
        ("Wohnen", 120_000),
        ("Lebensmittel", 30_000),
        (None, 5_000),
    ]
    assert body["top_categories"][0]["icon"] is None and body["top_categories"][2]["category_id"] is None
    assert body["uncategorized_count"] == 1


def test_dashboard_trend_has_twelve_months_ending_with_the_selected_one(world: World) -> None:
    _build(world)

    trend = world.member.get(DASHBOARD, params={"month": "2026-03"}).json()["trend"]

    assert len(trend) == 12
    assert (trend[0]["month"], trend[-1]["month"]) == ("2025-04", "2026-03")
    by_month = {p["month"]: (p["income_cents"], p["expense_cents"]) for p in trend}
    assert by_month["2026-02"] == (0, 2_000)
    assert by_month["2026-03"] == (300_000, 155_000)
    assert by_month["2025-12"] == (0, 0)


def test_dashboard_defaults_to_the_current_month_in_berlin(world: World) -> None:
    account = _account(world.owner, "Giro")
    current = reporting.current_month()
    _tx(world.owner, account, -4_200, current.replace(day=1).isoformat())

    body = world.owner.get(DASHBOARD).json()

    assert body["month"] == reporting.month_key(current)
    assert body["expense_cents"] == 4_200
    assert body["trend"][-1] == {"month": body["month"], "income_cents": 0, "expense_cents": 4_200}
    assert date.fromisoformat(f"{body['month']}-01") == current


def test_dashboard_owner_sees_private_accounts(world: World) -> None:
    ids = _build(world)

    body = world.owner.get(DASHBOARD, params={"month": "2026-03"}).json()

    names = {a["name"]: a for a in body["accounts"]}
    assert set(names) == {"Giro", "Sparen", "Privat"}  # archived stays out
    assert names["Privat"]["balance_cents"] == 7_000 - 9_999 + 1_234 and names["Privat"]["is_mine"] is True
    assert body["income_cents"] == 300_000 + 1_234
    assert body["expense_cents"] == 155_000 + 9_999
    assert ids["private"] in {a["id"] for a in body["accounts"]}


def test_dashboard_top_categories_are_limited_to_six(world: World) -> None:
    account = _account(world.owner, "Giro")
    for index in range(8):
        category = _category(world.owner, f"K{index}")
        _tx(world.owner, account, -(index + 1) * 100, "2026-03-01", category_id=category)

    top = world.owner.get(DASHBOARD, params={"month": "2026-03"}).json()["top_categories"]

    assert [c["amount_cents"] for c in top] == [800, 700, 600, 500, 400, 300]


def test_dashboard_validation(world: World) -> None:
    for month in ("2026-13", "2026-00", "2026-3", "26-03", "march", "2026-03-01", ""):
        assert world.owner.get(DASHBOARD, params={"month": month}).status_code == 422, month
    assert world.owner.get(DASHBOARD, params={"month": "1999-01"}).status_code == 200


def test_dashboard_is_isolated_between_households(world: World) -> None:
    _build(world)

    body = world.stranger.get(DASHBOARD, params={"month": "2026-03"}).json()

    assert body["accounts"] == [] and body["net_worth_cents"] == 0
    assert (body["income_cents"], body["expense_cents"], body["net_cents"]) == (0, 0, 0)
    assert body["top_categories"] == [] and body["uncategorized_count"] == 0
    assert all(p["income_cents"] == p["expense_cents"] == 0 for p in body["trend"])


def test_dashboard_requires_login(client: TestClient) -> None:
    assert client.get(DASHBOARD).status_code == 401
