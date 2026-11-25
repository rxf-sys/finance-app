import base64
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance.contracts import today_berlin
from app.importing import get_preset
from app.models import (
    AccountVisibility,
    AuditLog,
    CategoryKind,
    Contract,
    ContractInterval,
    ContractPriceChange,
    ContractStatus,
    Notification,
    NotificationKind,
)
from tests.helpers import World, make_account, make_category, make_contract, make_tx, member_of

CONTRACTS = "/api/contracts"
BUDGETS = "/api/budgets"
NOTIFICATIONS = "/api/notifications"


def _recent_series() -> list[date]:
    """Three payments 30 days apart, the last one 10 days ago, relative to the real today."""
    today = today_berlin()
    return [today - timedelta(days=n) for n in (70, 40, 10)]


def _json(response: Any, expected: int = 200) -> Any:
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


# ---------------------------------------------------------------- contracts


def test_manual_contract_lifecycle(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    created = _json(
        world.owner.post(
            CONTRACTS,
            json={
                "name": "Fitnessstudio",
                "kind": "other",
                "interval": "yearly",
                "expected_amount_cents": -24000,
                "account_id": str(account.id),
                "customer_number": "K-123",
                "min_term_end": (today_berlin() + timedelta(days=100)).isoformat(),
                "notice_period_days": 30,
            },
        ),
        201,
    )
    assert created["status"] == "confirmed"
    assert created["is_manual"] is True
    assert created["monthly_amount_cents"] == -2000
    assert created["cancellation_deadline"] == (today_berlin() + timedelta(days=70)).isoformat()
    url = f"{CONTRACTS}/{created['id']}"

    patched = _json(world.owner.patch(url, json={"name": "Gym", "note": "Notiz", "interval": "monthly"}))
    assert (patched["name"], patched["note"], patched["interval"]) == ("Gym", "Notiz", "monthly")

    assert _json(world.member.get(url))["id"] == created["id"]  # shared account
    assert [c["id"] for c in _json(world.owner.get(CONTRACTS, params={"status": "confirmed"}))] == [
        created["id"]
    ]
    assert _json(world.owner.get(CONTRACTS, params={"status": "detected"})) == []
    assert _json(world.owner.get(CONTRACTS, params={"kind": "other", "account_id": str(account.id)}))

    assert _json(world.owner.post(f"{url}/cancel"))["cancelled_at"] is not None
    assert world.owner.post(f"{url}/cancel").status_code == 409
    assert _json(world.owner.post(f"{url}/reactivate"))["status"] == "confirmed"
    assert _json(world.owner.post(f"{url}/ignore"))["status"] == "ignored"
    assert _json(world.owner.post(f"{url}/reactivate"))["status"] == "detected"
    assert _json(world.owner.post(f"{url}/confirm"))["confirmed_at"] is not None

    _json(world.owner.delete(url), 204)
    assert world.owner.get(url).status_code == 404
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"contract_created", "contract_cancel", "contract_confirm", "contract_deleted"} <= actions


def test_contract_validation(world: World, db: Session) -> None:
    base = {"name": "X", "interval": "monthly", "expected_amount_cents": -100}
    assert world.owner.post(CONTRACTS, json={**base, "expected_amount_cents": 0}).status_code == 422
    assert world.owner.post(CONTRACTS, json={**base, "interval": "daily"}).status_code == 422
    assert world.owner.post(CONTRACTS, json={**base, "name": " "}).status_code == 422
    assert world.owner.post(CONTRACTS, json={**base, "counterparty_iban": "DE00"}).status_code == 422
    assert world.owner.post(CONTRACTS, json={**base, "notice_period_days": -1}).status_code == 422
    assert world.owner.post(CONTRACTS, json={**base, "category_id": str(uuid.uuid4())}).status_code == 404
    assert world.owner.post(CONTRACTS, json={**base, "account_id": str(uuid.uuid4())}).status_code == 404


def test_delete_only_for_manual_or_ignored(world: World, db: Session) -> None:
    hid = member_of(world.owner_user).household.id
    detected = make_contract(db, hid, status=ContractStatus.DETECTED)
    assert world.owner.delete(f"{CONTRACTS}/{detected.id}").status_code == 409
    _json(world.owner.post(f"{CONTRACTS}/{detected.id}/ignore"))
    _json(world.owner.delete(f"{CONTRACTS}/{detected.id}"), 204)


def test_ignored_contract_is_kept_and_not_reproposed_by_detect(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    for d in _recent_series():
        make_tx(db, account, -999, d, counterparty_name="Netflix")
    found = _json(world.owner.post(f"{CONTRACTS}/detect"))
    assert len(found) == 1
    _json(world.owner.post(f"{CONTRACTS}/{found[0]['id']}/ignore"))
    assert _json(world.owner.post(f"{CONTRACTS}/detect")) == []
    assert db.scalar(select(Contract).where(Contract.id == uuid.UUID(found[0]["id"]))) is not None


def test_detect_and_private_contract_hidden_from_member(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    for d in _recent_series():
        make_tx(db, private, -1500, d, counterparty_name="Geheim Abo")
    found = _json(world.member.post(f"{CONTRACTS}/detect"))
    assert found == []  # the member cannot see the private account
    found = _json(world.owner.post(f"{CONTRACTS}/detect"))
    assert len(found) == 1 and found[0]["account_id"] == str(private.id)
    assert found[0]["payments_count"] == 3
    cid = found[0]["id"]

    assert world.member.get(f"{CONTRACTS}/{cid}").status_code == 404
    assert _json(world.member.get(CONTRACTS)) == []
    assert world.member.get(f"{CONTRACTS}/{cid}/cancellation-letter").status_code == 404
    summary = _json(world.member.get(f"{CONTRACTS}/summary"))
    assert summary["detected_count"] == 0
    assert _json(world.owner.get(f"{CONTRACTS}/summary"))["detected_count"] == 1


def test_contract_detail_shows_visible_transactions_and_price_changes(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    hid = account.household_id
    contract = make_contract(db, hid, account=account, last_payment_date=date(2026, 10, 5))
    for i in range(30):
        tx = make_tx(db, account, -999, date(2026, 1, 1) + timedelta(days=i), counterparty_name="Netflix")
        tx.contract_id = contract.id
    change = ContractPriceChange(
        id=uuid.uuid4(),
        contract_id=contract.id,
        old_amount_cents=-999,
        new_amount_cents=-1299,
        effective_date=date(2026, 10, 5),
    )
    db.add(change)
    db.commit()

    listed = _json(world.owner.get(CONTRACTS))[0]
    assert listed["payments_count"] == 30
    assert listed["unacknowledged_price_change"]["id"] == str(change.id)
    detail = _json(world.owner.get(f"{CONTRACTS}/{contract.id}"))
    assert len(detail["transactions"]) == 24
    assert detail["transactions"][0]["booking_date"] == "2026-01-30"
    assert len(detail["price_changes"]) == 1

    ack = f"{CONTRACTS}/{contract.id}/price-changes/{change.id}/acknowledge"
    assert _json(world.owner.post(ack))["acknowledged_at"] is not None
    assert _json(world.owner.get(CONTRACTS))[0]["unacknowledged_price_change"] is None
    other = make_contract(db, hid, key="other")
    assert (
        world.owner.post(f"{CONTRACTS}/{other.id}/price-changes/{change.id}/acknowledge").status_code == 404
    )


def test_contract_account_must_be_visible(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    body = {"name": "X", "interval": "monthly", "expected_amount_cents": -100, "account_id": str(private.id)}
    assert world.member.post(CONTRACTS, json=body).status_code == 404
    assert world.owner.post(CONTRACTS, json=body).status_code == 201
    shared = make_contract(db, member_of(world.owner_user).household.id, key="s")
    assert (
        world.member.patch(f"{CONTRACTS}/{shared.id}", json={"account_id": str(private.id)}).status_code
        == 404
    )


def test_contracts_isolated_between_households(world: World, db: Session) -> None:
    contract = make_contract(db, member_of(world.owner_user).household.id)
    url = f"{CONTRACTS}/{contract.id}"
    assert _json(world.stranger.get(CONTRACTS)) == []
    assert world.stranger.get(url).status_code == 404
    assert world.stranger.patch(url, json={"name": "x"}).status_code == 404
    assert world.stranger.delete(url).status_code == 404
    for action in ("confirm", "cancel", "ignore", "reactivate"):
        assert world.stranger.post(f"{url}/{action}").status_code == 404
    assert world.stranger.get(f"{url}/cancellation-letter").status_code == 404
    ack = f"{url}/price-changes/{uuid.uuid4()}/acknowledge"
    assert world.stranger.post(ack).status_code == 404
    assert _json(world.stranger.post(f"{CONTRACTS}/detect")) == []
    assert _json(world.stranger.get(f"{CONTRACTS}/summary"))["by_kind"] == []


def test_summary_groups_confirmed_by_kind(world: World, db: Session) -> None:
    hid = member_of(world.owner_user).household.id
    make_contract(db, hid, key="a", amount_cents=-1_000)
    make_contract(db, hid, key="b", amount_cents=-12_000, interval=ContractInterval.YEARLY)
    make_contract(db, hid, key="c", amount_cents=-500, status=ContractStatus.DETECTED)
    make_contract(db, hid, key="d", amount_cents=-500, status=ContractStatus.CANCELLED)
    make_contract(db, hid, key="e", amount_cents=30_000)
    summary = _json(world.owner.get(f"{CONTRACTS}/summary"))
    assert summary["monthly_cost_cents"] == 2_000
    assert summary["monthly_income_cents"] == 30_000
    assert summary["detected_count"] == 1
    assert summary["by_kind"] == [{"kind": "subscription", "count": 3, "monthly_cost_cents": 2_000}]


def test_cancellation_letter(world: World, db: Session) -> None:
    contract = make_contract(db, member_of(world.owner_user).household.id, name="Streamo")
    contract.customer_number = "4711"
    db.commit()
    letter = _json(world.member.get(f"{CONTRACTS}/{contract.id}/cancellation-letter"))
    assert letter["recipient_name"] == "Streamo"
    assert "4711" in letter["subject"] and "4711" in letter["body"]
    assert "zum nächstmöglichen Zeitpunkt" in letter["body"]
    assert letter["body"].rstrip().endswith("Member")
    assert "Nach meiner Berechnung" not in letter["body"]  # no term data, so no end date


def test_cancellation_letter_names_the_earliest_end_date(world: World, db: Session) -> None:
    contract = make_contract(
        db,
        member_of(world.owner_user).household.id,
        min_term_end=date(2099, 12, 31),
        notice_period_days=30,
    )
    db.commit()
    letter = _json(world.member.get(f"{CONTRACTS}/{contract.id}/cancellation-letter"))
    assert "zum nächstmöglichen Zeitpunkt. Nach meiner Berechnung ist das der 31.12.2099." in letter["body"]


# ---------------------------------------------------------------- budgets


def test_budget_crud_and_status(world: World, db: Session) -> None:
    hid = member_of(world.owner_user).household.id
    account = make_account(db, world.owner_user)
    food = make_category(db, hid, "Essen")
    income = make_category(db, hid, "Lohn", kind=CategoryKind.INCOME)
    make_tx(db, account, -8_500, date(2026, 11, 3), category=food)

    created = _json(
        world.owner.post(BUDGETS, json={"category_id": str(food.id), "amount_cents": 10_000}), 201
    )
    assert created["category_name"] == "Essen"
    assert world.owner.post(BUDGETS, json={"category_id": str(food.id), "amount_cents": 5}).status_code == 409
    assert (
        world.owner.post(BUDGETS, json={"category_id": str(income.id), "amount_cents": 5}).status_code == 422
    )
    assert world.owner.post(BUDGETS, json={"category_id": str(food.id), "amount_cents": 0}).status_code == 422
    assert (
        world.owner.post(BUDGETS, json={"category_id": str(uuid.uuid4()), "amount_cents": 5}).status_code
        == 404
    )

    url = f"{BUDGETS}/{created['id']}"
    assert _json(world.member.patch(url, json={"amount_cents": 20_000, "rollover": True}))["rollover"] is True
    (status,) = _json(world.owner.get(f"{BUDGETS}/status", params={"month": "2026-11"}))
    assert (status["spent_cents"], status["limit_cents"], status["state"]) == (8_500, 40_000, "ok")
    assert world.owner.get(f"{BUDGETS}/status", params={"month": "2026-13"}).status_code == 422
    assert len(_json(world.owner.get(BUDGETS))) == 1
    _json(world.owner.delete(url), 204)
    assert _json(world.owner.get(BUDGETS)) == []


def test_budgets_isolated_between_households(world: World, db: Session) -> None:
    hid = member_of(world.owner_user).household.id
    food = make_category(db, hid, "Essen")
    created = _json(world.owner.post(BUDGETS, json={"category_id": str(food.id), "amount_cents": 100}), 201)
    url = f"{BUDGETS}/{created['id']}"
    assert _json(world.stranger.get(BUDGETS)) == []
    assert _json(world.stranger.get(f"{BUDGETS}/status")) == []
    assert world.stranger.patch(url, json={"rollover": True}).status_code == 404
    assert world.stranger.delete(url).status_code == 404
    body = {"category_id": str(food.id), "amount_cents": 100}
    assert world.stranger.post(BUDGETS, json=body).status_code == 404


# ---------------------------------------------------------------- available


def test_available_endpoint(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, opening=50_000)
    today = today_berlin()
    due = today + timedelta(days=1)
    make_contract(db, account.household_id, account=account, amount_cents=-1_000, next_due_date=due)
    body = _json(world.owner.get("/api/available"))
    assert body["balance_cents"] == 50_000
    if due.month == today.month:
        assert body["available_cents"] == 49_000
        assert body["items"][0]["amount_cents"] == -1_000
    stranger = _json(world.stranger.get("/api/available"))
    assert (stranger["balance_cents"], stranger["items"]) == (0, [])


# ---------------------------------------------------------------- notifications


def _notify(
    db: Session, user_id: uuid.UUID, household_id: uuid.UUID, key: str, offset: int = 0
) -> Notification:
    note = Notification(
        id=uuid.uuid4(),
        household_id=household_id,
        user_id=user_id,
        kind=NotificationKind.PRICE_CHANGE,
        title=key,
        dedupe_key=key,
    )
    db.add(note)
    db.commit()
    return note


def test_notifications_are_per_user(world: World, db: Session) -> None:
    hid = member_of(world.owner_user).household.id
    first = _notify(db, world.owner_user.id, hid, "one")
    _notify(db, world.owner_user.id, hid, "two")
    theirs = _notify(db, world.member_user.id, hid, "three")

    listed = _json(world.owner.get(NOTIFICATIONS))
    assert [n["title"] for n in listed] == ["two", "one"]
    assert _json(world.owner.get(f"{NOTIFICATIONS}/unread-count")) == {"count": 2}
    assert _json(world.owner.post(f"{NOTIFICATIONS}/{first.id}/read"))["read_at"] is not None
    assert [n["title"] for n in _json(world.owner.get(NOTIFICATIONS, params={"unread_only": True}))] == [
        "two"
    ]

    assert world.owner.post(f"{NOTIFICATIONS}/{theirs.id}/read").status_code == 404
    assert world.stranger.post(f"{NOTIFICATIONS}/{first.id}/read").status_code == 404
    assert _json(world.stranger.get(NOTIFICATIONS)) == []
    assert _json(world.stranger.post(f"{NOTIFICATIONS}/read-all")) == {"updated": 0}

    assert _json(world.owner.post(f"{NOTIFICATIONS}/read-all")) == {"updated": 1}
    assert _json(world.owner.get(f"{NOTIFICATIONS}/unread-count")) == {"count": 0}
    assert _json(world.member.get(f"{NOTIFICATIONS}/unread-count")) == {"count": 1}
    assert world.owner.get(NOTIFICATIONS, params={"limit": 51}).status_code == 422


# ---------------------------------------------------------------- import integration

HEADER = (
    "Auftragskonto;Buchungstag;Valutadatum;Buchungstext;Verwendungszweck;"
    "Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag;Waehrung"
)


def _import(client: TestClient, account_id: uuid.UUID, lines: list[str]) -> None:
    data = ("\n".join([HEADER, *lines]) + "\n").encode("iso-8859-1")
    response = client.post(
        "/api/imports",
        json={
            "account_id": str(account_id),
            "content_base64": base64.b64encode(data).decode(),
            "filename": "u.csv",
            "format": get_preset("sparkasse_camt").format.model_dump(mode="json"),
        },
    )
    assert response.status_code == 201, response.text


def _row(day: str, amount: str) -> str:
    return f"DE00;{day};{day};LASTSCHRIFT;Abo;Streamflix GmbH;;{amount};EUR"


def test_import_detects_contract_and_matches_later_payments(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    start = [d.strftime("%d.%m.%Y") for d in _recent_series()]
    _import(world.owner, account.id, [_row(d, "-12,99") for d in start])

    contracts = _json(world.owner.get(CONTRACTS))
    assert len(contracts) == 1
    assert contracts[0]["status"] == "detected"
    assert contracts[0]["name"] == "Streamflix GmbH"
    assert contracts[0]["expected_amount_cents"] == -1299
    assert contracts[0]["account_id"] == str(account.id)
    assert contracts[0]["payments_count"] == 3
    assert len(_json(world.member.get(CONTRACTS))) == 1
    assert _json(world.stranger.get(CONTRACTS)) == []
