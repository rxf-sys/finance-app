import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AccountVisibility
from tests.helpers import World, make_account, make_tx

BASE = "/api/categories"


def _create(client: TestClient, name: str, **extra: Any) -> dict[str, Any]:
    response = client.post(BASE, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_create_top_level_and_child_inherits_kind_and_color(world: World) -> None:
    top = _create(world.owner, "Wohnen", kind="expense", icon="house", color="chart-2")
    child = _create(world.owner, "Miete", parent_id=top["id"], kind="income")  # kind is ignored

    assert (top["parent_id"], top["kind"], top["icon"], top["color"]) == (None, "expense", "house", "chart-2")
    assert (child["parent_id"], child["kind"], child["color"]) == (top["id"], "expense", "chart-2")
    assert child["transaction_count"] == 0
    listed = world.member.get(BASE).json()
    assert [c["name"] for c in listed] == ["Wohnen", "Miete"]  # top level first


def test_create_validation(world: World) -> None:
    top = _create(world.owner, "Wohnen", kind="expense")
    child = _create(world.owner, "Miete", parent_id=top["id"])

    assert world.owner.post(BASE, json={"name": "Ohne Art"}).status_code == 422
    assert world.owner.post(BASE, json={"name": "", "kind": "expense"}).status_code == 422
    assert world.owner.post(BASE, json={"name": "x", "kind": "weird"}).status_code == 422
    assert (
        world.owner.post(BASE, json={"name": "x", "kind": "expense", "icon": "Not Valid!"}).status_code == 422
    )
    # Only two levels: a child cannot be a parent.
    assert world.owner.post(BASE, json={"name": "Tief", "parent_id": child["id"]}).status_code == 422
    assert world.owner.post(BASE, json={"name": "Waise", "parent_id": str(uuid.uuid4())}).status_code == 404


def test_duplicate_names_conflict_per_level(world: World) -> None:
    top = _create(world.owner, "Wohnen", kind="expense")
    other = _create(world.owner, "Freizeit", kind="expense")
    _create(world.owner, "Sonstiges", parent_id=top["id"])

    assert world.owner.post(BASE, json={"name": "Wohnen", "kind": "income"}).status_code == 409
    assert world.owner.post(BASE, json={"name": "Sonstiges", "parent_id": top["id"]}).status_code == 409
    _create(world.owner, "Sonstiges", parent_id=other["id"])  # same name under another parent is fine
    assert world.owner.patch(f"{BASE}/{other['id']}", json={"name": "Wohnen"}).status_code == 409
    # The session is still usable after a conflict.
    assert world.owner.get(BASE).status_code == 200


def test_update_category_and_kind_propagates_to_children(world: World) -> None:
    top = _create(world.owner, "Einnahmen", kind="expense")
    child = _create(world.owner, "Gehalt", parent_id=top["id"])

    changed = world.member.patch(
        f"{BASE}/{top['id']}", json={"kind": "income", "name": "Einkünfte", "icon": "wallet"}
    )
    assert changed.status_code == 200
    assert (changed.json()["kind"], changed.json()["name"], changed.json()["icon"]) == (
        "income",
        "Einkünfte",
        "wallet",
    )
    kinds = {c["name"]: c["kind"] for c in world.owner.get(BASE).json()}
    assert kinds == {"Einkünfte": "income", "Gehalt": "income"}

    renamed = world.owner.patch(f"{BASE}/{child['id']}", json={"name": "Lohn", "color": "chart-4"}).json()
    assert (renamed["name"], renamed["color"]) == ("Lohn", "chart-4")
    cleared = world.owner.patch(f"{BASE}/{child['id']}", json={"color": None}).json()
    assert cleared["color"] is None
    assert world.owner.patch(f"{BASE}/{child['id']}", json={"kind": "expense"}).status_code == 422
    assert world.owner.patch(f"{BASE}/{top['id']}", json={"icon": "No Good"}).status_code == 422


def test_delete_category_cascades_children_and_clears_transactions(world: World, db: Session) -> None:
    top = _create(world.owner, "Wohnen", kind="expense")
    child = _create(world.owner, "Miete", parent_id=top["id"])
    account = world.owner.post("/api/accounts", json={"name": "Giro", "kind": "giro"}).json()
    tx = world.owner.post(
        "/api/transactions",
        json={
            "account_id": account["id"],
            "booking_date": "2026-01-01",
            "amount_cents": -5,
            "category_id": child["id"],
        },
    ).json()
    assert tx["category_source"] == "manual"
    rule = world.owner.post(
        "/api/rules", json={"category_id": child["id"], "conditions": {"direction": "out"}}
    ).json()

    assert world.owner.delete(f"{BASE}/{top['id']}").status_code == 204

    assert world.owner.get(BASE).json() == []
    assert rule["id"] not in [r["id"] for r in world.owner.get("/api/rules").json()]
    after = world.owner.get(f"/api/transactions/{tx['id']}").json()
    assert (after["category_id"], after["category_source"], after["rule_id"]) == (None, None, None)
    assert world.owner.delete(f"{BASE}/{top['id']}").status_code == 404


def test_transaction_count_includes_splits_and_hides_private_accounts(world: World, db: Session) -> None:
    food = _create(world.owner, "Lebensmittel", kind="expense")
    private = make_account(db, world.owner_user, "Privat", visibility=AccountVisibility.PRIVATE)
    shared = make_account(db, world.owner_user, "Gemeinsam")
    make_tx(db, shared, -100, category_id=uuid.UUID(food["id"]))
    make_tx(db, private, -100, category_id=uuid.UUID(food["id"]))
    split_parent = make_tx(db, shared, -300)
    world.owner.put(
        f"/api/transactions/{split_parent.id}/splits",
        json=[{"amount_cents": -100, "category_id": food["id"]}, {"amount_cents": -200}],
    )

    def count(client: TestClient) -> int:
        return int(next(c for c in client.get(BASE).json() if c["id"] == food["id"])["transaction_count"])

    assert count(world.owner) == 3
    assert count(world.member) == 2


def test_seed_defaults_once(world: World) -> None:
    response = world.owner.post(f"{BASE}/defaults")
    assert response.status_code == 201
    created = response.json()
    assert len(created) == 60
    assert world.owner.post(f"{BASE}/defaults").status_code == 409
    assert world.member.post(f"{BASE}/defaults").status_code == 409
    # Another household has no categories yet and may seed its own.
    assert len(world.stranger.post(f"{BASE}/defaults").json()) == 60
    assert len(world.owner.get(BASE).json()) == 60


def test_categories_are_isolated_between_households(world: World) -> None:
    mine = _create(world.owner, "Wohnen", kind="expense")
    child = _create(world.owner, "Miete", parent_id=mine["id"])

    assert world.stranger.get(BASE).json() == []
    assert world.stranger.patch(f"{BASE}/{mine['id']}", json={"name": "x"}).status_code == 404
    assert world.stranger.delete(f"{BASE}/{mine['id']}").status_code == 404
    assert world.stranger.post(BASE, json={"name": "Kind", "parent_id": mine["id"]}).status_code == 404
    # Names do not clash across households.
    assert world.stranger.post(BASE, json={"name": "Wohnen", "kind": "expense"}).status_code == 201
    assert world.owner.get(f"{BASE}").json()[1]["id"] == child["id"]
