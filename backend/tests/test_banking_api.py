"""Bank connection API and sync, against a fake Enable Banking (httpx.MockTransport)."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api import banking as banking_api
from app.banking.client import EnableBankingClient
from app.banking.sync import SESSION_CONTEXT, sync_connection, sync_due_connections
from app.config import Settings, get_settings
from app.models import (
    Account,
    AuditLog,
    BankConnection,
    BankConnectionStatus,
    Notification,
    NotificationKind,
    SyncRun,
    SyncStatus,
    Transaction,
)
from app.models.base import utcnow
from app.security.crypto import SecretBox
from app.security.tokens import hash_token
from tests.helpers import IBAN_A, IBAN_B, World, make_account, make_tx

SESSION_ID = "session-secret-123"
UID = "uid-1"
TODAY = date.today()


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


class FakeBank:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transactions: list[dict[str, Any]] = []
        self.page_size = 100
        self.status_override: int | None = None
        self.status_body: dict[str, Any] = {}
        self.delete_status = 200
        self.session_calls = 0
        self.auth_state: str | None = None
        self.queued: list[str] = []
        self.accounts = [
            {"uid": UID, "account_id": {"iban": IBAN_A}, "name": "Girokonto", "currency": "EUR"},
            {"uid": "uid-2", "account_id": {"iban": IBAN_B}, "name": "Tagesgeld", "currency": "EUR"},
        ]

    def calls(self, method: str, prefix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.startswith(prefix)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "DELETE":
            return httpx.Response(self.delete_status, json={"message": "ok"})
        if self.status_override is not None and path.endswith("/transactions"):
            return httpx.Response(self.status_override, json=self.status_body)
        if path == "/aspsps":
            return httpx.Response(
                200,
                json={
                    "aspsps": [{"name": "Testbank", "country": "DE", "maximum_consent_validity": 90 * 86400}]
                },
            )
        if path == "/auth":
            body = json.loads(request.content)
            self.auth_state = body["state"]
            return httpx.Response(200, json={"url": "https://bank.example/authorize?s=1"})
        if path == "/sessions" and request.method == "POST":
            self.session_calls += 1
            valid = (utcnow() + timedelta(days=90)).isoformat()
            return httpx.Response(
                200,
                json={"session_id": SESSION_ID, "accounts": self.accounts, "access": {"valid_until": valid}},
            )
        if path == f"/sessions/{SESSION_ID}":
            return httpx.Response(200, json={"accounts": self.accounts})
        if path.endswith("/transactions"):
            key = request.url.params.get("continuation_key")
            start = int(key) if key else 0
            page = self.transactions[start : start + self.page_size]
            nxt = start + self.page_size
            return httpx.Response(
                200,
                json={
                    "transactions": page,
                    "continuation_key": str(nxt) if nxt < len(self.transactions) else None,
                },
            )
        return httpx.Response(404, json={})


def tx(ref: str | None, amount: str, day: int = 1, **over: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": "BOOK",
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "credit_debit_indicator": "DBIT",
        "booking_date": (TODAY - timedelta(days=day)).isoformat(),
        "creditor": {"name": "Rewe"},
        "remittance_information": ["Einkauf"],
    }
    if ref is not None:
        out["entry_reference"] = ref
    out.update(over)
    return out


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(
        update={"enablebanking_app_id": "app-1", "enablebanking_private_key": SecretStr(_pem())}
    )


@pytest.fixture
def bank(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeBank]:
    fake = FakeBank()
    queued = fake.queued
    banking_api.clear_aspsp_cache()
    monkeypatch.setattr(banking_api, "enqueue_sync", queued.append)

    def provide_client() -> Iterator[EnableBankingClient]:
        yield sync_client(fake, settings)

    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    client.app.dependency_overrides[banking_api.get_bank_client] = provide_client  # type: ignore[attr-defined]
    yield fake
    client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def sync_client(bank: FakeBank, settings: Settings) -> EnableBankingClient:
    return EnableBankingClient.from_settings(settings, transport=httpx.MockTransport(bank.handler))


def connect(client: TestClient, bank: FakeBank) -> str:
    started = client.post("/api/bank-connections", json={"aspsp_name": "Testbank", "country": "DE"})
    assert started.status_code == 201, started.text
    assert started.json()["redirect_url_to_bank"] == "https://bank.example/authorize?s=1"
    callback = client.get(
        "/api/bank-connections/callback",
        params={"code": "c1", "state": bank.auth_state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    connection_id: str = started.json()["connection_id"]
    assert callback.headers["location"] == f"/bank?connection={connection_id}"
    return connection_id


def link(client: TestClient, connection_id: str, **body: Any) -> httpx.Response:
    body.setdefault("provider_account_uid", UID)
    response: httpx.Response = client.post(f"/api/bank-connections/{connection_id}/link", json=body)
    return response


def connection_row(db: Session, connection_id: str) -> BankConnection:
    db.expire_all()
    row = db.get(BankConnection, uuid.UUID(connection_id))
    assert row is not None
    return row


def test_unconfigured_returns_503_and_app_starts(world: World) -> None:
    for response in (
        world.owner.get("/api/bank-connections"),
        world.owner.get("/api/bank-connections/aspsps"),
        world.owner.post("/api/bank-connections", json={"aspsp_name": "X", "country": "DE"}),
        world.owner.get("/api/bank-connections/callback"),
    ):
        assert response.status_code == 503
        assert response.json()["detail"] == "Bank sync is not configured"


def test_aspsps_are_cached(world: World, bank: FakeBank) -> None:
    first = world.owner.get("/api/bank-connections/aspsps?country=DE")
    assert first.status_code == 200
    assert first.json() == [{"name": "Testbank", "country": "DE", "logo": None}]
    world.owner.get("/api/bank-connections/aspsps?country=DE")
    assert len(bank.calls("GET", "/aspsps")) == 1


def test_full_flow_stores_session_encrypted(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    started = world.owner.post("/api/bank-connections", json={"aspsp_name": "Testbank", "country": "DE"})
    connection_id = started.json()["connection_id"]
    auth = json.loads(bank.calls("POST", "/auth")[0].content)
    assert auth["redirect_url"] == "http://testserver/api/bank-connections/callback"
    assert auth["aspsp"] == {"name": "Testbank", "country": "DE"}
    valid_until = datetime.fromisoformat(auth["access"]["valid_until"])
    assert timedelta(days=89) < valid_until - utcnow() < timedelta(days=90)
    row = connection_row(db, connection_id)
    assert row.status is BankConnectionStatus.PENDING
    assert row.auth_state_hash == hash_token(str(bank.auth_state))

    callback = world.owner.get(
        "/api/bank-connections/callback",
        params={"code": "c1", "state": bank.auth_state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    row = connection_row(db, connection_id)
    assert row.status is BankConnectionStatus.ACTIVE
    assert row.auth_state_hash is None
    assert row.consent_valid_until is not None
    assert row.session_encrypted is not None
    assert SESSION_ID.encode() not in row.session_encrypted
    box = SecretBox(settings.encryption_key.get_secret_value())
    assert box.decrypt(row.session_encrypted, SESSION_CONTEXT).decode() == SESSION_ID
    actions = db.scalars(select(AuditLog.action)).all()
    assert "bank_connected" in actions
    details = db.scalars(select(AuditLog.details).where(AuditLog.action == "bank_connected")).all()
    assert SESSION_ID not in json.dumps(details)


def test_replayed_state_fails(world: World, bank: FakeBank) -> None:
    connect(world.owner, bank)
    replay = world.owner.get(
        "/api/bank-connections/callback",
        params={"code": "c2", "state": bank.auth_state},
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert replay.headers["location"] == "/bank?error=invalid_state"
    assert bank.session_calls == 1


def test_wrong_and_missing_state_fail(world: World, bank: FakeBank) -> None:
    world.owner.post("/api/bank-connections", json={"aspsp_name": "Testbank", "country": "DE"})
    for params in ({"code": "c", "state": "nope"}, {"code": "c"}):
        response = world.owner.get("/api/bank-connections/callback", params=params, follow_redirects=False)
        assert response.headers["location"] == "/bank?error=invalid_state"
    assert bank.session_calls == 0


def test_foreign_state_is_rejected_and_not_consumed(world: World, bank: FakeBank, db: Session) -> None:
    started = world.owner.post("/api/bank-connections", json={"aspsp_name": "Testbank", "country": "DE"})
    for other in (world.member, world.stranger):
        response = other.get(
            "/api/bank-connections/callback",
            params={"code": "c", "state": bank.auth_state},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/bank?error=invalid_state"
    assert bank.session_calls == 0
    assert connection_row(db, started.json()["connection_id"]).status is BankConnectionStatus.PENDING
    ok = world.owner.get(
        "/api/bank-connections/callback",
        params={"code": "c", "state": bank.auth_state},
        follow_redirects=False,
    )
    assert ok.headers["location"].startswith("/bank?connection=")


def test_callback_without_cookie_bounces_once_for_samesite(
    world: World, bank: FakeBank, client: TestClient
) -> None:
    anonymous = TestClient(client.app)
    first = anonymous.get("/api/bank-connections/callback", params={"code": "c", "state": "s"})
    assert first.status_code == 200
    assert "retry=1" in first.text
    second = anonymous.get(
        "/api/bank-connections/callback",
        params={"code": "c", "state": "s", "retry": "1"},
        follow_redirects=False,
    )
    assert second.headers["location"] == "/bank?error=login"


def test_denied_authorisation(world: World, bank: FakeBank, db: Session) -> None:
    started = world.owner.post("/api/bank-connections", json={"aspsp_name": "Testbank", "country": "DE"})
    response = world.owner.get(
        "/api/bank-connections/callback",
        params={"error": "access_denied", "error_description": "secret", "state": bank.auth_state},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/bank?error=denied"
    assert connection_row(db, started.json()["connection_id"]).status is BankConnectionStatus.ERROR


def test_unknown_bank_is_rejected(world: World, bank: FakeBank) -> None:
    response = world.owner.post("/api/bank-connections", json={"aspsp_name": "Nope", "country": "DE"})
    assert response.status_code == 422


def test_accounts_are_masked(world: World, bank: FakeBank) -> None:
    connection_id = connect(world.owner, bank)
    response = world.owner.get(f"/api/bank-connections/{connection_id}/accounts")
    assert response.status_code == 200
    first = response.json()[0]
    assert first["uid"] == UID
    assert first["iban_masked"] == "*" * 18 + IBAN_A[-4:]
    assert first["linked_account_id"] is None
    assert IBAN_A not in response.text


def test_link_existing_account_checks_iban(world: World, bank: FakeBank, db: Session) -> None:
    connection_id = connect(world.owner, bank)
    wrong = make_account(db, world.owner_user, "Falsch", iban=IBAN_B)
    assert link(world.owner, connection_id, account_id=str(wrong.id)).status_code == 422
    unset = make_account(db, world.owner_user, "Ohne IBAN")
    ok = link(world.owner, connection_id, account_id=str(unset.id))
    assert ok.status_code == 200, ok.text
    db.expire_all()
    linked = db.get(Account, unset.id)
    assert linked is not None
    assert linked.bank_connection_id == uuid.UUID(connection_id)
    assert linked.provider_account_uid == UID
    assert linked.iban == IBAN_A
    again = link(world.owner, connection_id, account_id=str(unset.id))
    assert again.status_code == 409
    listed = world.owner.get(f"/api/bank-connections/{connection_id}/accounts").json()
    assert listed[0]["linked_account_id"] == str(unset.id)


def test_link_requires_exactly_one_target(world: World, bank: FakeBank) -> None:
    connection_id = connect(world.owner, bank)
    assert link(world.owner, connection_id).status_code == 422
    assert (
        link(
            world.owner, connection_id, provider_account_uid="unknown", new_account={"name": "X"}
        ).status_code
        == 404
    )


def test_cannot_link_hidden_account(world: World, bank: FakeBank, db: Session) -> None:
    from app.models import AccountVisibility

    connection_id = connect(world.owner, bank)
    private = make_account(db, world.member_user, "Privat", visibility=AccountVisibility.PRIVATE)
    assert link(world.owner, connection_id, account_id=str(private.id)).status_code == 404


def test_sync_from_defaults_after_csv_history(world: World, bank: FakeBank, db: Session) -> None:
    connection_id = connect(world.owner, bank)
    with_history = make_account(db, world.owner_user, "Mit CSV", iban=IBAN_A)
    make_tx(db, with_history, -500, booking_date=TODAY - timedelta(days=20))
    make_tx(db, with_history, -500, booking_date=TODAY - timedelta(days=30))
    response = link(world.owner, connection_id, account_id=str(with_history.id))
    assert response.json()["sync_from"] == (TODAY - timedelta(days=19)).isoformat()

    fresh = link(
        world.owner,
        connection_id,
        provider_account_uid="uid-2",
        new_account={"name": "Tagesgeld", "kind": "savings"},
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["sync_from"] == (TODAY - timedelta(days=90)).isoformat()
    created = db.get(Account, uuid.UUID(fresh.json()["account_id"]))
    assert created is not None
    assert (created.iban, created.currency) == (IBAN_B, "EUR")


def test_explicit_sync_from_and_future_rejected(world: World, bank: FakeBank) -> None:
    connection_id = connect(world.owner, bank)
    future = (TODAY + timedelta(days=1)).isoformat()
    assert link(world.owner, connection_id, new_account={"name": "A"}, sync_from=future).status_code == 422
    chosen = (TODAY - timedelta(days=10)).isoformat()
    ok = link(world.owner, connection_id, new_account={"name": "A"}, sync_from=chosen)
    assert ok.json()["sync_from"] == chosen


def _linked(world: World, bank: FakeBank, db: Session, **link_body: Any) -> tuple[str, Account]:
    connection_id = connect(world.owner, bank)
    body = link_body or {"new_account": {"name": "Giro"}}
    response = link(world.owner, connection_id, **body)
    assert response.status_code == 200, response.text
    account = db.get(Account, uuid.UUID(response.json()["account_id"]))
    assert account is not None
    return connection_id, account


def _sync(db: Session, bank: FakeBank, settings: Settings, connection_id: str) -> BankConnection:
    row = connection_row(db, connection_id)
    sync_connection(db, row, today=TODAY, client=sync_client(bank, settings), settings=settings)
    db.commit()
    return connection_row(db, connection_id)


def test_sync_inserts_and_skips_duplicates(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, account = _linked(world, bank, db)
    bank.page_size = 2
    bank.transactions = [
        tx("r1", "10.00", 3),
        tx("r2", "20.50", 2),
        tx("r3", "5.00", 1, status="PDNG"),
        tx(None, "7.00", 2),
        tx(None, "7.00", 2),
        tx("r1", "10.00", 3),
    ]
    row = _sync(db, bank, settings, connection_id)
    amounts = sorted(
        db.scalars(select(Transaction.amount_cents).where(Transaction.account_id == account.id)).all()
    )
    assert amounts == [-2050, -1000, -700, -700]
    assert row.last_sync_at is not None
    assert row.last_error is None
    runs = db.scalars(select(SyncRun).where(SyncRun.error.is_(None))).all()
    assert [(r.rows_new, r.status) for r in runs] == [(4, SyncStatus.COMPLETED)]

    row = _sync(db, bank, settings, connection_id)
    assert (
        db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == account.id))
        == 4
    )
    latest = db.scalars(
        select(SyncRun).where(SyncRun.error.is_(None)).order_by(SyncRun.started_at.desc())
    ).first()
    assert latest is not None
    assert (latest.rows_new, latest.rows_duplicate) == (0, 5)
    first_hash = db.scalars(
        select(Transaction.dedupe_hash).where(Transaction.counterparty_name == "Rewe")
    ).first()
    assert first_hash is not None


def test_sync_range_uses_marker_then_overlap(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    chosen = TODAY - timedelta(days=30)
    connection_id, _ = _linked(world, bank, db, new_account={"name": "Giro"}, sync_from=chosen.isoformat())
    _sync(db, bank, settings, connection_id)
    _sync(db, bank, settings, connection_id)
    froms = [r.url.params["date_from"] for r in bank.calls("GET", f"/accounts/{UID}/transactions")]
    assert froms == [chosen.isoformat(), (TODAY - timedelta(days=7)).isoformat()]


def test_sync_applies_rules_and_pairs_transfers(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, account = _linked(world, bank, db)
    other = make_account(db, world.owner_user, "Tagesgeld", iban=IBAN_B)
    make_tx(db, other, 10000, booking_date=TODAY - timedelta(days=1), counterparty_iban=IBAN_A)
    bank.transactions = [tx("t1", "100.00", 1, creditor={"name": "Ich"}, creditor_account={"iban": IBAN_B})]
    _sync(db, bank, settings, connection_id)
    db.expire_all()
    synced = db.scalars(select(Transaction).where(Transaction.account_id == account.id)).one()
    assert synced.transfer_peer_id is not None


def test_expired_session_marks_connection_and_notifies_once(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, _ = _linked(world, bank, db)
    bank.status_override = 401
    row = _sync(db, bank, settings, connection_id)
    assert row.status is BankConnectionStatus.EXPIRED
    assert row.last_error and "consent" in row.last_error
    notes = db.scalars(select(Notification)).all()
    assert len(notes) == 1
    assert notes[0].kind is NotificationKind.SYNC_FAILED
    assert notes[0].user_id == world.owner_user.id
    row.status = BankConnectionStatus.ACTIVE
    db.commit()
    _sync(db, bank, settings, connection_id)
    assert db.scalar(select(func.count()).select_from(Notification)) == 1
    failed = db.scalars(select(SyncRun).where(SyncRun.status == SyncStatus.FAILED)).all()
    assert failed
    assert all(r.error and "consent" in r.error for r in failed)


def test_rate_limit_keeps_connection_active(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, _ = _linked(world, bank, db)
    bank.status_override = 429
    bank.status_body = {"error": "ASPSP_RATE_LIMIT_EXCEEDED", "message": "Max Mustermann"}
    row = _sync(db, bank, settings, connection_id)
    assert row.status is BankConnectionStatus.ACTIVE
    assert row.last_error is not None
    assert "Mustermann" not in row.last_error
    run = db.scalars(select(SyncRun).where(SyncRun.status == SyncStatus.FAILED)).one()
    assert run.error == row.last_error
    assert db.scalar(select(func.count()).select_from(Notification)) == 0


def test_expired_consent_date_marks_without_calling_bank(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, _ = _linked(world, bank, db)
    row = connection_row(db, connection_id)
    row.consent_valid_until = utcnow() - timedelta(minutes=1)
    db.commit()
    row = _sync(db, bank, settings, connection_id)
    assert row.status is BankConnectionStatus.EXPIRED
    assert not bank.calls("GET", f"/accounts/{UID}")


def test_sync_due_connections_respects_six_hour_window(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, _ = _linked(world, bank, db)
    bank.transactions = [tx("d1", "1.00", 1)]
    row = connection_row(db, connection_id)
    row.last_sync_at = utcnow() - timedelta(hours=1)
    db.commit()
    now = datetime.now(UTC)
    assert sync_due_connections(db, now, client=sync_client(bank, settings), settings=settings) == 0
    row = connection_row(db, connection_id)
    row.last_sync_at = utcnow() - timedelta(hours=7)
    db.commit()
    assert sync_due_connections(db, now, client=sync_client(bank, settings), settings=settings) == 1
    assert db.scalar(select(func.count()).select_from(Transaction)) == 1
    assert sync_due_connections(db, now, client=sync_client(bank, settings), settings=settings) == 0


def test_manual_sync_is_throttled(world: World, bank: FakeBank) -> None:
    connection_id = connect(world.owner, bank)
    first = world.owner.post(f"/api/bank-connections/{connection_id}/sync")
    assert first.status_code == 202
    second = world.owner.post(f"/api/bank-connections/{connection_id}/sync")
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
    assert bank.queued == [connection_id]


def test_manual_sync_requires_active_connection(world: World, bank: FakeBank) -> None:
    started = world.owner.post("/api/bank-connections", json={"aspsp_name": "Testbank", "country": "DE"})
    response = world.owner.post(f"/api/bank-connections/{started.json()['connection_id']}/sync")
    assert response.status_code == 409


def test_list_connections_and_sync_runs(
    world: World, bank: FakeBank, db: Session, settings: Settings
) -> None:
    connection_id, account = _linked(world, bank, db)
    bank.transactions = [tx("l1", "3.00", 1)]
    _sync(db, bank, settings, connection_id)
    listed = world.owner.get("/api/bank-connections").json()
    assert len(listed) == 1
    assert listed[0]["status"] == "active"
    assert listed[0]["accounts"] == [
        {"account_id": str(account.id), "name": "Giro", "provider_account_uid": UID}
    ]
    assert "session" not in json.dumps(listed)
    runs = world.owner.get(f"/api/bank-connections/{connection_id}/sync-runs").json()
    assert [r["rows_new"] for r in runs] == [1]


def test_delete_unlinks_but_keeps_data(world: World, bank: FakeBank, db: Session, settings: Settings) -> None:
    connection_id, account = _linked(world, bank, db)
    bank.transactions = [tx("x1", "3.00", 1)]
    _sync(db, bank, settings, connection_id)
    bank.delete_status = 500  # best effort: still succeeds
    response = world.owner.delete(f"/api/bank-connections/{connection_id}")
    assert response.status_code == 204
    assert bank.calls("DELETE", f"/sessions/{SESSION_ID}")
    db.expire_all()
    kept = db.get(Account, account.id)
    assert kept is not None
    assert (kept.bank_connection_id, kept.provider_account_uid) == (None, None)
    assert (
        db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == account.id))
        == 1
    )
    assert db.get(BankConnection, uuid.UUID(connection_id)) is None
    assert "bank_disconnected" in db.scalars(select(AuditLog.action)).all()


def test_connections_are_private_to_their_owner(world: World, bank: FakeBank, db: Session) -> None:
    connection_id, _ = _linked(world, bank, db)
    base = f"/api/bank-connections/{connection_id}"
    for other in (world.member, world.stranger):
        assert other.get("/api/bank-connections").json() == []
        assert other.get(f"{base}/accounts").status_code == 404
        assert other.get(f"{base}/sync-runs").status_code == 404
        assert other.post(f"{base}/sync").status_code == 404
        assert (
            other.post(
                f"{base}/link", json={"provider_account_uid": "uid-2", "new_account": {"name": "X"}}
            ).status_code
            == 404
        )
        assert other.delete(base).status_code == 404
    assert bank.queued == []
    assert world.owner.get(f"{base}/accounts").status_code == 200


def test_enqueue_sync_defers_a_job_once(db: Session) -> None:
    import procrastinate

    from app import worker
    from app.banking.queue import enqueue_sync

    connector = procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_conninfo)
    connection_id = str(uuid.uuid4())
    with worker.app.replace_connector(connector):
        enqueue_sync(connection_id)
        enqueue_sync(connection_id)  # the queueing lock makes the second call a no-op
    jobs = db.execute(
        text("SELECT task_name FROM procrastinate_jobs WHERE args->>'connection_id' = :c"),
        {"c": connection_id},
    ).all()
    assert len(jobs) == 1
    assert jobs[0].task_name.endswith("sync_connection_task")
