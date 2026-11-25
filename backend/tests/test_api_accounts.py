from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance import reporting
from app.models import AuditLog
from tests.helpers import IBAN_A, IBAN_B, World, make_tx, member_of

BASE = "/api/accounts"


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body = {"name": "Giro", "kind": "giro", **overrides}
    response = client.post(BASE, json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_create_and_list_account(world: World) -> None:
    created = _create(world.owner, iban="de89 3704 0044 0532 0130 00", opening_balance_cents=12_345)

    assert created["iban"] == IBAN_A
    assert created["visibility"] == "shared"
    assert created["is_mine"] is True and created["owner_user_id"] == str(world.owner_user.id)
    assert (created["balance_cents"], created["transaction_count"], created["last_booking_date"]) == (
        12_345,
        0,
        None,
    )
    listed = world.member.get(BASE).json()
    assert [a["id"] for a in listed] == [created["id"]]
    assert listed[0]["is_mine"] is False


def test_list_sorts_archived_last_and_reports_balance(world: World, db: Session) -> None:
    first = _create(world.owner, name="Zeta", opening_balance_cents=1_000)
    archived = _create(world.owner, name="Alpha")
    world.owner.patch(f"{BASE}/{archived['id']}", json={"is_archived": True})
    _create(world.owner, name="Beta")
    account = next(
        a for a in reporting.account_stats(db, member_of(world.owner_user)) if a.account.name == "Zeta"
    ).account
    make_tx(db, account, -250)
    make_tx(db, account, 100)

    listed = world.owner.get(BASE).json()

    assert [a["name"] for a in listed] == ["Beta", "Zeta", "Alpha"]
    zeta = listed[1]
    assert zeta["id"] == first["id"]
    assert (zeta["balance_cents"], zeta["transaction_count"]) == (850, 2)
    assert zeta["last_booking_date"] == "2026-01-15"


def test_create_validation(world: World) -> None:
    assert world.owner.post(BASE, json={"name": "x", "kind": "giro", "iban": "DE00"}).status_code == 422
    assert (
        world.owner.post(
            BASE, json={"name": "x", "kind": "giro", "iban": "DE89370400440532013001"}
        ).status_code
        == 422
    )
    assert world.owner.post(BASE, json={"name": "  ", "kind": "giro"}).status_code == 422
    assert world.owner.post(BASE, json={"name": "x", "kind": "boat"}).status_code == 422
    assert (
        world.owner.post(BASE, json={"name": "x", "kind": "giro", "visibility": "secret"}).status_code == 422
    )
    assert (
        world.owner.post(
            BASE, json={"name": "x", "kind": "giro", "opening_balance_cents": 10**15}
        ).status_code
        == 422
    )
    # An empty IBAN is treated as none.
    assert _create(world.owner, iban="  ")["iban"] is None


def test_duplicate_iban_in_household_is_409_but_allowed_across_households(world: World) -> None:
    _create(world.owner, iban=IBAN_A)

    assert world.member.post(BASE, json={"name": "Zweit", "kind": "giro", "iban": IBAN_A}).status_code == 409
    _create(world.stranger, iban=IBAN_A)

    other = _create(world.owner, name="Andere", iban=IBAN_B)
    response = world.owner.patch(f"{BASE}/{other['id']}", json={"iban": IBAN_A})
    assert response.status_code == 409


def test_private_account_is_hidden_from_other_members(world: World) -> None:
    private = _create(world.owner, name="Privat", visibility="private")

    assert world.member.get(BASE).json() == []
    assert world.member.patch(f"{BASE}/{private['id']}", json={"name": "x"}).status_code == 404
    assert world.member.delete(f"{BASE}/{private['id']}").status_code == 404
    assert world.member.get(f"{BASE}/{private['id']}/balance-history").status_code == 404
    # Not even the household owner may see another member's private account.
    mine = _create(world.member, name="Meins", visibility="private")
    assert world.owner.get(BASE).json()[0]["id"] == private["id"]
    assert world.owner.delete(f"{BASE}/{mine['id']}").status_code == 404


def test_update_account(world: World) -> None:
    account = _create(world.owner, iban=IBAN_A)
    url = f"{BASE}/{account['id']}"

    updated = world.member.patch(
        url, json={"name": " Haushalt ", "kind": "savings", "opening_balance_cents": 500, "is_archived": True}
    ).json()
    assert (updated["name"], updated["kind"], updated["opening_balance_cents"], updated["is_archived"]) == (
        "Haushalt",
        "savings",
        500,
        True,
    )
    assert updated["iban"] == IBAN_A  # untouched when absent
    assert updated["balance_cents"] == 500

    assert world.owner.patch(url, json={"iban": None}).json()["iban"] is None
    assert world.owner.patch(url, json={"iban": "nope"}).status_code == 422
    assert world.owner.patch(url, json={"name": ""}).status_code == 422
    assert world.owner.patch(url, json={}).status_code == 200


def test_only_the_account_owner_may_make_an_account_private(world: World) -> None:
    account = _create(world.owner)
    url = f"{BASE}/{account['id']}"

    assert world.member.patch(url, json={"visibility": "private"}).status_code == 403
    assert world.owner.patch(url, json={"visibility": "private"}).json()["visibility"] == "private"
    assert world.member.get(BASE).json() == []
    # Keeping it private is fine for the owner; making it shared again works too.
    assert world.owner.patch(url, json={"visibility": "private", "name": "A"}).status_code == 200
    assert world.owner.patch(url, json={"visibility": "shared"}).json()["visibility"] == "shared"
    assert world.stranger.patch(url, json={"visibility": "private"}).status_code == 404


def test_delete_permissions_cascade_and_audit(world: World, db: Session) -> None:
    mine = _create(world.member, name="Mitglied")
    other = _create(world.owner, name="Inhaber")
    owner_account = next(
        a.account
        for a in reporting.account_stats(db, member_of(world.owner_user))
        if a.account.name == "Inhaber"
    )
    make_tx(db, owner_account, -100, purpose="Geheimer Verwendungszweck")
    make_tx(db, owner_account, -200)

    # A plain member can delete their own account, not the owner's.
    assert world.member.delete(f"{BASE}/{other['id']}").status_code == 403
    assert world.member.delete(f"{BASE}/{mine['id']}").status_code == 204
    # The household owner can delete any visible account, including one they do not own.
    third = _create(world.member, name="Noch eins")
    assert world.owner.delete(f"{BASE}/{third['id']}").status_code == 204
    assert world.owner.delete(f"{BASE}/{other['id']}").status_code == 204
    assert world.owner.delete(f"{BASE}/{other['id']}").status_code == 404

    db.expire_all()
    assert world.owner.get("/api/transactions").json() == {"items": [], "total": 0}
    deleted = db.scalars(
        select(AuditLog).where(AuditLog.action == "account_deleted").order_by(AuditLog.id)
    ).all()
    assert [entry.details["transaction_count"] for entry in deleted] == ["0", "0", "2"]
    assert all("Geheimer" not in str(entry.details) for entry in deleted)
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "account_created")) is not None


def test_delete_unpairs_the_peer_transaction(world: World, db: Session) -> None:
    a = _create(world.owner, name="A")
    b = _create(world.owner, name="B")
    out = world.owner.post(
        "/api/transactions", json={"account_id": a["id"], "booking_date": "2026-01-01", "amount_cents": -100}
    ).json()
    back = world.owner.post(
        "/api/transactions", json={"account_id": b["id"], "booking_date": "2026-01-01", "amount_cents": 100}
    ).json()
    assert (
        world.owner.post(f"/api/transactions/{out['id']}/transfer", json={"peer_id": back["id"]}).status_code
        == 200
    )

    assert world.owner.delete(f"{BASE}/{a['id']}").status_code == 204

    detail = world.owner.get(f"/api/transactions/{back['id']}").json()
    assert detail["transfer_peer_id"] is None


def test_balance_history(world: World, db: Session) -> None:
    account = _create(world.owner, opening_balance_cents=1_000)
    this_month = reporting.current_month()
    for month_offset, amount in ((-2, -300), (0, 50)):
        date_ = reporting.add_months(this_month, month_offset).replace(day=10)
        response = world.owner.post(
            "/api/transactions",
            json={"account_id": account["id"], "booking_date": date_.isoformat(), "amount_cents": amount},
        )
        assert response.status_code == 201

    history = world.owner.get(f"{BASE}/{account['id']}/balance-history", params={"months": 3}).json()

    assert [p["balance_cents"] for p in history] == [700, 700, 750]
    assert history[-1]["month"] == reporting.month_key(this_month)
    assert len(world.owner.get(f"{BASE}/{account['id']}/balance-history").json()) == 12
    assert world.owner.get(f"{BASE}/{account['id']}/balance-history", params={"months": 0}).status_code == 422


def test_accounts_are_isolated_between_households(world: World) -> None:
    mine = _create(world.owner)

    assert world.stranger.get(BASE).json() == []
    assert world.stranger.patch(f"{BASE}/{mine['id']}", json={"name": "x"}).status_code == 404
    assert world.stranger.delete(f"{BASE}/{mine['id']}").status_code == 404
    assert world.stranger.get(f"{BASE}/{mine['id']}/balance-history").status_code == 404
    assert world.owner.get(BASE).json()[0]["name"] == "Giro"
