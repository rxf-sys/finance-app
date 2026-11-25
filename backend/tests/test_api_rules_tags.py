import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AccountVisibility, CategorySource, Transaction
from tests.helpers import World, make_account, make_tx

RULES = "/api/rules"
TAGS = "/api/tags"


def _category(client: TestClient, name: str = "Lebensmittel") -> str:
    response = client.post("/api/categories", json={"name": name, "kind": "expense"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _rule(client: TestClient, category_id: str, **conditions: Any) -> dict[str, Any]:
    response = client.post(RULES, json={"category_id": category_id, "conditions": conditions})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# ---------------------------------------------------------------- rules


def test_rule_crud(world: World) -> None:
    food = _category(world.owner)
    other = _category(world.owner, "Sonstiges")

    rule = _rule(world.owner, food, counterparty_contains="  REWE ", direction="out")
    assert rule["conditions"] == {"counterparty_contains": "rewe", "direction": "out"}
    assert (rule["source"], rule["priority"], rule["is_active"]) == ("manual", 100, True)
    assert rule["created_by_id"] == str(world.owner_user.id)

    patched = world.member.patch(
        f"{RULES}/{rule['id']}",
        json={
            "category_id": other,
            "priority": 5,
            "is_active": False,
            "conditions": {"purpose_contains": "Miete"},
        },
    ).json()
    assert (patched["category_id"], patched["priority"], patched["is_active"]) == (other, 5, False)
    assert patched["conditions"] == {"purpose_contains": "miete"}

    second = _rule(world.owner, food, booking_text_contains="lastschrift")
    assert [r["id"] for r in world.member.get(RULES).json()] == [rule["id"], second["id"]]  # priority 5 first

    assert world.owner.delete(f"{RULES}/{rule['id']}").status_code == 204
    assert [r["id"] for r in world.owner.get(RULES).json()] == [second["id"]]
    assert world.owner.delete(f"{RULES}/{rule['id']}").status_code == 404


def test_rule_validation(world: World) -> None:
    food = _category(world.owner)
    post = world.owner.post

    assert post(RULES, json={"category_id": food, "conditions": {}}).status_code == 422
    assert post(RULES, json={"category_id": food, "conditions": {"nonsense": 1}}).status_code == 422
    assert (
        post(RULES, json={"category_id": food, "conditions": {"counterparty_iban": "DE00"}}).status_code
        == 422
    )
    assert post(RULES, json={"category_id": food, "conditions": {"direction": "up"}}).status_code == 422
    assert (
        post(
            RULES, json={"category_id": food, "conditions": {"amount_min_cents": 5, "amount_max_cents": 1}}
        ).status_code
        == 422
    )
    assert (
        post(RULES, json={"category_id": food, "conditions": {"direction": "in"}, "priority": -1}).status_code
        == 422
    )
    assert post(RULES, json={"conditions": {"direction": "in"}}).status_code == 422
    unknown = {"category_id": str(uuid.uuid4()), "conditions": {"direction": "in"}}
    assert post(RULES, json=unknown).status_code == 404
    rule = _rule(world.owner, food, direction="in")
    assert world.owner.patch(f"{RULES}/{rule['id']}", json={"conditions": {}}).status_code == 422
    assert (
        world.owner.patch(f"{RULES}/{rule['id']}", json={"category_id": str(uuid.uuid4())}).status_code == 404
    )


def test_rule_account_condition_requires_a_visible_account(world: World, db: Session) -> None:
    food = _category(world.owner)
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    shared = make_account(db, world.owner_user, "Gemeinsam")

    denied = world.member.post(
        RULES, json={"category_id": food, "conditions": {"account_id": str(private.id)}}
    )
    assert denied.status_code == 404
    assert (
        world.member.post(
            RULES, json={"category_id": food, "conditions": {"account_id": str(shared.id)}}
        ).status_code
        == 201
    )
    assert (
        world.owner.post(
            RULES, json={"category_id": food, "conditions": {"account_id": str(private.id)}}
        ).status_code
        == 201
    )


def test_rules_on_private_accounts_are_hidden_from_other_members(world: World, db: Session) -> None:
    food = _category(world.owner)
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    hidden = _rule(world.owner, food, account_id=str(private.id), counterparty_contains="praxis")
    shared = _rule(world.owner, food, counterparty_contains="rewe")

    assert [r["id"] for r in world.member.get(RULES).json()] == [shared["id"]]
    assert {r["id"] for r in world.owner.get(RULES).json()} == {hidden["id"], shared["id"]}
    url = f"{RULES}/{hidden['id']}"
    assert world.member.patch(url, json={"is_active": False}).status_code == 404
    assert world.member.delete(url).status_code == 404
    assert world.owner.patch(url, json={"is_active": False}).status_code == 200


def test_rule_learned_on_a_private_account_stays_on_it(world: World, db: Session) -> None:
    health = _category(world.owner, "Gesundheit")
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    shared = make_account(db, world.owner_user, "Gemeinsam")
    tx = make_tx(db, private, -8000, counterparty_name="Praxis Dr. Beispiel")
    lookalike = make_tx(db, shared, -8000, counterparty_name="Praxis Dr. Beispiel")
    response = world.owner.patch(f"/api/transactions/{tx.id}", json={"category_id": health, "learn": True})
    assert response.status_code == 200, response.text

    learned = [r for r in world.owner.get(RULES).json() if r["source"] == "learned"]
    assert [r["conditions"].get("account_id") for r in learned] == [str(private.id)]
    assert world.member.get(RULES).json() == []
    db.expire_all()
    assert db.get(Transaction, lookalike.id).category_id is None  # type: ignore[union-attr]


def test_apply_rules_updates_visible_non_manual_transactions(world: World, db: Session) -> None:
    food = _category(world.owner)
    fun = _category(world.owner, "Freizeit")
    shared = make_account(db, world.owner_user, "Gemeinsam")
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    plain = make_tx(db, shared, -100, counterparty_name="REWE")
    hidden = make_tx(db, private, -100, counterparty_name="REWE")
    manual = make_tx(db, shared, -100, counterparty_name="REWE")
    assert (
        world.owner.patch(
            f"/api/transactions/{manual.id}", json={"category_id": fun, "learn": False}
        ).status_code
        == 200
    )
    _rule(world.owner, food, counterparty_contains="rewe")

    assert world.member.post(f"{RULES}/apply").json() == {"updated": 1}
    assert world.member.post(f"{RULES}/apply").json() == {"updated": 0}
    assert world.owner.post(f"{RULES}/apply").json() == {"updated": 1}  # the private one

    db.expire_all()
    for tx, expected in ((plain, food), (hidden, food), (manual, fun)):
        stored = db.get(Transaction, tx.id)
        assert stored is not None and str(stored.category_id) == expected
    assert db.get(Transaction, manual.id).category_source is CategorySource.MANUAL  # type: ignore[union-attr]


def test_rules_are_isolated_between_households(world: World, db: Session) -> None:
    food = _category(world.owner)
    rule = _rule(world.owner, food, counterparty_contains="rewe")
    tx = make_tx(db, make_account(db, world.owner_user), -100, counterparty_name="REWE")

    assert world.stranger.get(RULES).json() == []
    assert world.stranger.patch(f"{RULES}/{rule['id']}", json={"priority": 1}).status_code == 404
    assert world.stranger.delete(f"{RULES}/{rule['id']}").status_code == 404
    assert (
        world.stranger.post(RULES, json={"category_id": food, "conditions": {"direction": "in"}}).status_code
        == 404
    )
    assert world.stranger.post(f"{RULES}/apply").json() == {"updated": 0}
    db.expire_all()
    stored = db.get(Transaction, tx.id)
    assert stored is not None and stored.category_id is None


# ---------------------------------------------------------------- tags


def test_tag_crud(world: World) -> None:
    created = world.owner.post(TAGS, json={"name": " Urlaub "})
    assert created.status_code == 201
    tag = created.json()
    assert tag["name"] == "Urlaub"
    world.member.post(TAGS, json={"name": "Auto"})

    assert [t["name"] for t in world.member.get(TAGS).json()] == ["Auto", "Urlaub"]
    renamed = world.member.patch(f"{TAGS}/{tag['id']}", json={"name": "Reise"})
    assert renamed.json() == {"id": tag["id"], "name": "Reise"}
    assert world.owner.delete(f"{TAGS}/{tag['id']}").status_code == 204
    assert [t["name"] for t in world.owner.get(TAGS).json()] == ["Auto"]
    assert world.owner.delete(f"{TAGS}/{tag['id']}").status_code == 404


def test_tag_validation_and_conflicts(world: World) -> None:
    first = world.owner.post(TAGS, json={"name": "Urlaub"}).json()
    second = world.owner.post(TAGS, json={"name": "Auto"}).json()

    assert world.owner.post(TAGS, json={"name": ""}).status_code == 422
    assert world.owner.post(TAGS, json={"name": "x" * 51}).status_code == 422
    assert world.owner.post(TAGS, json={}).status_code == 422
    assert world.member.post(TAGS, json={"name": "Urlaub"}).status_code == 409
    assert world.owner.patch(f"{TAGS}/{second['id']}", json={"name": "Urlaub"}).status_code == 409
    assert world.owner.patch(f"{TAGS}/{first['id']}", json={"name": "Urlaub"}).status_code == 200  # unchanged


def test_tag_names_are_unique_ignoring_case(world: World) -> None:
    first = world.owner.post(TAGS, json={"name": "Urlaub"}).json()
    second = world.owner.post(TAGS, json={"name": "Auto"}).json()

    assert world.owner.post(TAGS, json={"name": "urlaub"}).status_code == 409
    assert world.member.post(TAGS, json={"name": "URLAUB"}).status_code == 409
    assert world.owner.patch(f"{TAGS}/{second['id']}", json={"name": "uRLAUB"}).status_code == 409
    renamed = world.owner.patch(f"{TAGS}/{first['id']}", json={"name": "urlaub"})  # only the case changes
    assert renamed.status_code == 200 and renamed.json()["name"] == "urlaub"
    assert world.owner.post(TAGS, json={"name": "Urlaub"}).status_code == 409


def test_deleting_a_tag_detaches_it_from_transactions(world: World, db: Session) -> None:
    tag = world.owner.post(TAGS, json={"name": "Urlaub"}).json()
    tx = make_tx(db, make_account(db, world.owner_user), -100)
    assert world.owner.patch(f"/api/transactions/{tx.id}", json={"tag_ids": [tag["id"]]}).json()["tags"] == [
        tag
    ]

    assert world.owner.delete(f"{TAGS}/{tag['id']}").status_code == 204

    assert world.owner.get(f"/api/transactions/{tx.id}").json()["tags"] == []


def test_tags_are_isolated_between_households(world: World) -> None:
    tag = world.owner.post(TAGS, json={"name": "Urlaub"}).json()

    assert world.stranger.get(TAGS).json() == []
    assert world.stranger.patch(f"{TAGS}/{tag['id']}", json={"name": "x"}).status_code == 404
    assert world.stranger.delete(f"{TAGS}/{tag['id']}").status_code == 404
    assert world.stranger.post(TAGS, json={"name": "Urlaub"}).status_code == 201  # same name, other household
    assert [t["id"] for t in world.owner.get(TAGS).json()] == [tag["id"]]
