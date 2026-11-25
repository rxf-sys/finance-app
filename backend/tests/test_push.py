"""Push API, sending and dispatching, against a fake push service (httpx.MockTransport)."""

import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import push
from app.api import push as push_api
from app.config import Settings, get_settings
from app.models import AuditLog, Notification, NotificationKind, PushSubscription, User
from app.models.base import utcnow
from app.push import Outcome, build_payload, dispatch_pending, in_quiet_hours, send
from app.security.webpush import MAX_PLAINTEXT, VapidKey, b64url_encode
from tests.helpers import World, decrypt_push, raw_public

SECRET_PATH = "/fcm/send/secret-token-1"
_REAL_BUILD_CLIENT = push.build_client
FCM = "https://fcm.googleapis.com"
AUTH_SECRET = b"0123456789abcdef"


class Receiver:
    """A browser: a P-256 key pair and an auth secret, as in a real subscription."""

    def __init__(self, endpoint: str = FCM + SECRET_PATH) -> None:
        self.endpoint = endpoint
        self.private = ec.generate_private_key(ec.SECP256R1())

    def keys(self) -> dict[str, str]:
        return {"p256dh": b64url_encode(raw_public(self.private)), "auth": b64url_encode(AUTH_SECRET)}

    def json(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "expirationTime": None, "keys": self.keys()}

    def decrypt(self, request: httpx.Request) -> dict[str, str]:
        result: dict[str, str] = json.loads(decrypt_push(request.content, self.private, AUTH_SECRET))
        return result


class FakePushService:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status_by_path: dict[str, int] = {}
        self.default_status = 201
        self.error: Exception | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status_by_path.get(request.url.path, self.default_status))

    def client(self) -> httpx.Client:
        return _REAL_BUILD_CLIENT(httpx.MockTransport(self.handler))


@pytest.fixture
def vapid_pem() -> str:
    return VapidKey.generate_pem()


@pytest.fixture
def settings(vapid_pem: str) -> Settings:
    return get_settings().model_copy(
        update={"vapid_private_key": SecretStr(vapid_pem), "vapid_subject": "mailto:admin@example.com"}
    )


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakePushService:
    fake = FakePushService()
    monkeypatch.setattr(push, "build_client", lambda transport=None: fake.client())
    return fake


@pytest.fixture
def enabled(client: TestClient, settings: Settings, service: FakePushService) -> Iterator[FakePushService]:
    def provide_client() -> Iterator[httpx.Client]:
        yield service.client()

    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    client.app.dependency_overrides[push_api.get_push_client] = provide_client  # type: ignore[attr-defined]
    yield service
    client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def _subs(db: Session) -> list[PushSubscription]:
    db.expire_all()
    return list(db.scalars(select(PushSubscription).order_by(PushSubscription.endpoint)))


def _add_sub(db: Session, user: User, receiver: Receiver) -> PushSubscription:
    assert user.membership is not None
    sub = PushSubscription(
        household_id=user.membership.household_id,
        user_id=user.id,
        endpoint=receiver.endpoint,
        **receiver.keys(),
    )
    db.add(sub)
    db.commit()
    return sub


def _add_notice(
    db: Session,
    user: User,
    *,
    title: str = "Kündigungsfrist läuft ab",
    body: str | None = "Netflix: bis 30.11.",
    link: str | None = "/contracts/1",
    age: timedelta = timedelta(0),
    handled: bool = False,
) -> Notification:
    assert user.membership is not None
    notice = Notification(
        household_id=user.membership.household_id,
        user_id=user.id,
        kind=NotificationKind.CONTRACT_NOTICE,
        title=title,
        body=body,
        link=link,
        dedupe_key=str(uuid.uuid4()),
        created_at=utcnow() - age,
        push_handled_at=utcnow() if handled else None,
    )
    db.add(notice)
    db.commit()
    return notice


# --- settings -----------------------------------------------------------------------------------


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, encryption_key=SecretStr("x"), **values)


def test_push_enabled_needs_key_and_subject(vapid_pem: str) -> None:
    key = SecretStr(vapid_pem)
    assert not _settings(public_origin="https://fin.example").push_enabled
    assert not _settings(public_origin="http://localhost", vapid_private_key=key).push_enabled
    assert not _settings(
        public_origin="https://fin.example", vapid_private_key=SecretStr("  \n")
    ).push_enabled
    assert _settings(public_origin="https://fin.example", vapid_private_key=key).push_enabled
    explicit = _settings(
        public_origin="http://localhost", vapid_private_key=key, vapid_subject="mailto:a@b.de"
    )
    assert explicit.push_enabled
    assert explicit.resolved_vapid_subject == "mailto:a@b.de"
    assert _settings(public_origin="https://fin.example").resolved_vapid_subject == "https://fin.example"


def test_vapid_subject_must_be_mailto_or_https() -> None:
    with pytest.raises(ValueError, match="FA_VAPID_SUBJECT"):
        _settings(vapid_subject="admin@example.com")


# --- API ----------------------------------------------------------------------------------------


def test_config_reports_disabled_and_enabled(world: World, client: TestClient, settings: Settings) -> None:
    assert world.owner.get("/api/push/config").json() == {"enabled": False, "public_key": None}

    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    try:
        body = world.owner.get("/api/push/config").json()
    finally:
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
    assert body["enabled"] is True
    assert body["public_key"] == VapidKey.from_pem(settings.vapid_private_key.get_secret_value()).public_key  # type: ignore[union-attr]


def test_endpoints_require_login(client: TestClient) -> None:
    assert client.get("/api/push/config").status_code == 401
    assert client.post("/api/push/test").status_code == 401
    assert client.post("/api/push/unsubscribe", json={"endpoint": FCM}).status_code == 401


def test_subscribe_stores_row_and_audits_host_only(
    world: World, enabled: FakePushService, db: Session
) -> None:
    receiver = Receiver()

    response = world.owner.post(
        "/api/push/subscriptions", json=receiver.json(), headers={"User-Agent": "U" * 300}
    )

    assert response.status_code == 204
    (sub,) = _subs(db)
    assert sub.endpoint == receiver.endpoint
    assert sub.user_id == world.owner_user.id
    assert sub.p256dh == receiver.keys()["p256dh"]
    assert sub.user_agent == "U" * 200
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "push_subscribe")).one()
    assert audit.details == {"host": "fcm.googleapis.com"}
    assert SECRET_PATH not in json.dumps(audit.details)


def test_subscribe_same_endpoint_updates_and_moves_to_caller(
    world: World, enabled: FakePushService, db: Session
) -> None:
    first = Receiver()
    world.owner.post("/api/push/subscriptions", json=first.json())
    renewed = Receiver(first.endpoint)

    response = world.stranger.post("/api/push/subscriptions", json=renewed.json())

    assert response.status_code == 204
    (sub,) = _subs(db)
    assert sub.user_id == world.stranger_user.id
    assert sub.household_id == world.stranger_user.membership.household_id  # type: ignore[union-attr]
    assert sub.p256dh == renewed.keys()["p256dh"]


def test_subscribe_validates_input(world: World, enabled: FakePushService, db: Session) -> None:
    good = Receiver()

    def post(**over: Any) -> httpx.Response:
        body = good.json() | over
        response: httpx.Response = world.owner.post("/api/push/subscriptions", json=body)
        return response

    foreign = post(endpoint="https://evil.example/push")
    assert foreign.status_code == 422
    assert "known push service" in foreign.json()["detail"]
    assert post(endpoint="http://fcm.googleapis.com/x").status_code == 422
    bad_auth = post(keys={"p256dh": good.keys()["p256dh"], "auth": b64url_encode(b"short")})
    assert bad_auth.status_code == 422
    assert "16 bytes" in bad_auth.json()["detail"]
    assert post(keys={"p256dh": b64url_encode(b"\x04" * 65), "auth": good.keys()["auth"]}).status_code == 422
    assert post(keys={"p256dh": "***", "auth": good.keys()["auth"]}).status_code == 422
    assert world.owner.post("/api/push/subscriptions", json={"endpoint": good.endpoint}).status_code == 422
    assert _subs(db) == []


def test_subscribe_and_test_answer_503_when_disabled(world: World, db: Session) -> None:
    response = world.owner.post("/api/push/subscriptions", json=Receiver().json())
    assert response.status_code == 503
    assert response.json()["detail"] == "Push is not configured"
    assert world.owner.post("/api/push/test").status_code == 503
    assert _subs(db) == []


def test_unsubscribe_deletes_own_row_and_audits(world: World, enabled: FakePushService, db: Session) -> None:
    receiver = Receiver()
    world.owner.post("/api/push/subscriptions", json=receiver.json())

    assert world.owner.post("/api/push/unsubscribe", json={"endpoint": receiver.endpoint}).status_code == 204

    assert _subs(db) == []
    assert db.scalars(select(AuditLog).where(AuditLog.action == "push_unsubscribe")).one().details == {
        "host": "fcm.googleapis.com"
    }
    # Unknown endpoints are fine too and leave no audit entry.
    assert world.owner.post("/api/push/unsubscribe", json={"endpoint": receiver.endpoint}).status_code == 204
    assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "push_unsubscribe")))) == 1


def test_unsubscribe_cannot_delete_someone_elses_endpoint(
    world: World, enabled: FakePushService, db: Session
) -> None:
    mine, theirs = Receiver(FCM + "/fcm/send/a"), Receiver(FCM + "/fcm/send/b")
    world.owner.post("/api/push/subscriptions", json=mine.json())
    world.member.post("/api/push/subscriptions", json=theirs.json())

    same_household = world.owner.post("/api/push/unsubscribe", json={"endpoint": theirs.endpoint})
    other_household = world.stranger.post("/api/push/unsubscribe", json={"endpoint": mine.endpoint})

    assert same_household.status_code == other_household.status_code == 204
    assert [s.endpoint for s in _subs(db)] == [mine.endpoint, theirs.endpoint]
    assert db.scalars(select(AuditLog).where(AuditLog.action == "push_unsubscribe")).first() is None


def test_test_push_reaches_only_callers_subscriptions(
    world: World, enabled: FakePushService, db: Session
) -> None:
    owner_phone, owner_laptop = Receiver(FCM + "/fcm/send/phone"), Receiver(FCM + "/fcm/send/laptop")
    member_phone, stranger_phone = Receiver(FCM + "/fcm/send/member"), Receiver(FCM + "/fcm/send/stranger")
    for client, receiver in (
        (world.owner, owner_phone),
        (world.owner, owner_laptop),
        (world.member, member_phone),
        (world.stranger, stranger_phone),
    ):
        client.post("/api/push/subscriptions", json=receiver.json())

    response = world.owner.post("/api/push/test")

    assert response.json() == {"sent": 2, "failed": 0, "removed": 0}
    assert sorted(r.url.path for r in enabled.requests) == ["/fcm/send/laptop", "/fcm/send/phone"]
    request = next(r for r in enabled.requests if r.url.path == "/fcm/send/phone")
    assert owner_phone.decrypt(request) == {
        "title": "Testbenachrichtigung",
        "body": "Push-Benachrichtigungen funktionieren auf diesem Gerät.",
        "url": "/",
    }
    assert all(
        s.last_success_at is not None for s in _subs(db) if "phone" in s.endpoint or "laptop" in s.endpoint
    )
    untouched = [s for s in _subs(db) if s.endpoint.endswith(("member", "stranger"))]
    assert len(untouched) == 2 and all(s.last_success_at is None for s in untouched)


def test_test_push_removes_gone_and_counts_failures(
    world: World, enabled: FakePushService, db: Session
) -> None:
    for name in ("gone", "broken", "fine"):
        world.owner.post("/api/push/subscriptions", json=Receiver(f"{FCM}/fcm/send/{name}").json())
    enabled.status_by_path = {"/fcm/send/gone": 410, "/fcm/send/broken": 500}

    response = world.owner.post("/api/push/test")

    assert response.json() == {"sent": 1, "failed": 1, "removed": 1}
    assert [s.endpoint.rsplit("/", 1)[1] for s in _subs(db)] == ["broken", "fine"]


# --- sending ------------------------------------------------------------------------------------


def _sub_of(receiver: Receiver) -> PushSubscription:
    return PushSubscription(endpoint=receiver.endpoint, **receiver.keys())


def test_send_sets_headers_and_encrypts(vapid_pem: str, service: FakePushService) -> None:
    receiver = Receiver()
    vapid = VapidKey.from_pem(vapid_pem)

    with service.client() as client:
        outcome = send(
            client, _sub_of(receiver), b'{"title":"t","body":"b","url":"/"}', vapid, "mailto:a@b.de"
        )

    assert outcome is Outcome.SENT
    (request,) = service.requests
    assert request.method == "POST" and str(request.url) == receiver.endpoint
    assert request.headers["TTL"] == "86400"
    assert request.headers["Urgency"] == "normal"
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["Content-Type"] == "application/octet-stream"
    assert request.headers["Authorization"].startswith("vapid t=")
    assert request.headers["Authorization"].endswith(f"k={vapid.public_key}")
    assert receiver.decrypt(request) == {"title": "t", "body": "b", "url": "/"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, Outcome.SENT), (201, Outcome.SENT), (404, Outcome.GONE), (410, Outcome.GONE)]
    + [(code, Outcome.FAILED) for code in (301, 400, 401, 413, 429, 500, 503)],
)
def test_send_maps_status_codes(
    status: int, expected: Outcome, vapid_pem: str, service: FakePushService
) -> None:
    service.default_status = status
    with service.client() as client:
        outcome = send(client, _sub_of(Receiver()), b"{}", VapidKey.from_pem(vapid_pem), "mailto:a@b.de")
    assert outcome is expected


def test_send_treats_transport_errors_as_failed(
    vapid_pem: str, service: FakePushService, caplog: pytest.LogCaptureFixture
) -> None:
    service.error = httpx.ConnectTimeout("timed out")
    with caplog.at_level(logging.WARNING), service.client() as client:
        outcome = send(client, _sub_of(Receiver()), b"{}", VapidKey.from_pem(vapid_pem), "mailto:a@b.de")
    assert outcome is Outcome.FAILED
    assert "fcm.googleapis.com" in caplog.text and SECRET_PATH not in caplog.text


def test_send_refuses_foreign_endpoints_without_a_request(vapid_pem: str, service: FakePushService) -> None:
    receiver = Receiver("https://169.254.169.254/latest/meta-data")
    with service.client() as client:
        outcome = send(client, _sub_of(receiver), b"{}", VapidKey.from_pem(vapid_pem), "mailto:a@b.de")
    assert outcome is Outcome.FAILED
    assert service.requests == []


def test_build_payload_fits_one_record_and_keeps_unicode() -> None:
    short = json.loads(build_payload("Titel", "Größe €", None))
    assert short == {"title": "Titel", "body": "Größe €", "url": "/"}

    for body in ("ä" * 5000, "€" * 5000, "x" * 100_000):
        payload = build_payload("T" * 200, body, "/contracts/" + "u" * 100)
        assert len(payload) <= MAX_PLAINTEXT
        decoded = json.loads(payload)
        assert decoded["title"] == "T" * 200
        assert decoded["body"].endswith("…") and set(decoded["body"][:-1]) <= set(body)


# --- dispatching --------------------------------------------------------------------------------


def _handled(db: Session, notice: Notification) -> bool:
    db.refresh(notice)
    return notice.push_handled_at is not None


@pytest.mark.parametrize(
    ("utc", "quiet"),
    [
        (datetime(2026, 11, 25, 20, 59, tzinfo=UTC), False),  # 21:59 CET
        (datetime(2026, 11, 25, 21, 0, tzinfo=UTC), True),  # 22:00 CET
        (datetime(2026, 11, 26, 2, 0, tzinfo=UTC), True),  # 03:00 CET
        (datetime(2026, 11, 26, 5, 59, tzinfo=UTC), True),  # 06:59 CET
        (datetime(2026, 11, 26, 6, 0, tzinfo=UTC), False),  # 07:00 CET
        (datetime(2026, 7, 1, 19, 59, tzinfo=UTC), False),  # 21:59 CEST
        (datetime(2026, 7, 1, 20, 0, tzinfo=UTC), True),  # 22:00 CEST
        (datetime(2026, 7, 2, 5, 0, tzinfo=UTC), False),  # 07:00 CEST
    ],
)
def test_quiet_hours_are_22_to_7_berlin_time(utc: datetime, quiet: bool) -> None:
    assert in_quiet_hours(utc) is quiet


def test_dispatch_waits_during_quiet_hours(
    world: World, settings: Settings, service: FakePushService, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_sub(db, world.owner_user, Receiver(FCM + "/fcm/send/phone"))
    notice = _add_notice(db, world.owner_user)
    monkeypatch.setattr(push, "in_quiet_hours", lambda _moment: True)

    assert dispatch_pending(settings).sent == 0
    assert service.requests == []
    assert not _handled(db, notice)

    monkeypatch.setattr(push, "in_quiet_hours", lambda _moment: False)
    assert dispatch_pending(settings).sent == 1
    assert _handled(db, notice)


def test_dispatch_without_push_marks_handled_even_at_night(
    world: World, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    notice = _add_notice(db, world.owner_user)
    monkeypatch.setattr(push, "in_quiet_hours", lambda _moment: True)

    dispatch_pending(get_settings())

    assert _handled(db, notice)


def test_dispatch_sends_notice_to_its_users_devices_only(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    phone, laptop = Receiver(FCM + "/fcm/send/phone"), Receiver(FCM + "/fcm/send/laptop")
    other = Receiver(FCM + "/fcm/send/other")
    _add_sub(db, world.owner_user, phone)
    _add_sub(db, world.owner_user, laptop)
    _add_sub(db, world.member_user, other)
    notice = _add_notice(db, world.owner_user)

    result = dispatch_pending(settings)

    assert (result.sent, result.failed, result.removed) == (2, 0, 0)
    assert sorted(r.url.path for r in service.requests) == ["/fcm/send/laptop", "/fcm/send/phone"]
    request = next(r for r in service.requests if r.url.path.endswith("phone"))
    assert phone.decrypt(request) == {
        "title": "Kündigungsfrist läuft ab",
        "body": "Netflix: bis 30.11.",
        "url": "/contracts/1",
    }
    assert _handled(db, notice)
    assert all(s.last_success_at is not None for s in _subs(db) if s.user_id == world.owner_user.id)


def test_dispatch_never_sends_a_notice_twice(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    _add_sub(db, world.owner_user, Receiver())
    _add_notice(db, world.owner_user)

    dispatch_pending(settings)
    dispatch_pending(settings)

    assert len(service.requests) == 1
    _add_notice(db, world.owner_user, title="Zweite")
    dispatch_pending(settings)
    assert len(service.requests) == 2


def test_dispatch_marks_handled_even_when_sending_fails(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    _add_sub(db, world.owner_user, Receiver())
    notice = _add_notice(db, world.owner_user)
    service.default_status = 500

    assert dispatch_pending(settings).failed == 1
    service.default_status = 201
    assert dispatch_pending(settings).sent == 0

    assert _handled(db, notice)
    assert len(service.requests) == 1


def test_dispatch_deletes_gone_subscriptions_and_keeps_failed_ones(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    for name in ("gone", "broken"):
        _add_sub(db, world.owner_user, Receiver(f"{FCM}/fcm/send/{name}"))
    _add_notice(db, world.owner_user)
    service.status_by_path = {"/fcm/send/gone": 404, "/fcm/send/broken": 503}

    result = dispatch_pending(settings)

    assert (result.sent, result.failed, result.removed) == (0, 1, 1)
    (remaining,) = _subs(db)
    assert remaining.endpoint.endswith("broken") and remaining.last_success_at is None


def test_dispatch_skips_notices_older_than_24_hours(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    _add_sub(db, world.owner_user, Receiver())
    old = _add_notice(db, world.owner_user, age=timedelta(hours=24, minutes=1))
    recent = _add_notice(db, world.owner_user, age=timedelta(hours=23))

    dispatch_pending(settings)

    assert len(service.requests) == 1
    assert _handled(db, old) and _handled(db, recent)


def test_dispatch_when_disabled_only_marks_handled(
    world: World, service: FakePushService, db: Session
) -> None:
    _add_sub(db, world.owner_user, Receiver())
    notice = _add_notice(db, world.owner_user)

    result = dispatch_pending(get_settings())

    assert (result.sent, result.failed, result.removed) == (0, 0, 0)
    assert service.requests == []
    assert _handled(db, notice)


def test_dispatch_with_invalid_key_keeps_notices_pending(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    _add_sub(db, world.owner_user, Receiver())
    notice = _add_notice(db, world.owner_user)
    broken = settings.model_copy(update={"vapid_private_key": SecretStr("not a pem")})

    dispatch_pending(broken)

    assert service.requests == [] and not _handled(db, notice)


def test_dispatch_ignores_already_handled_and_other_household_subscriptions(
    world: World, settings: Settings, service: FakePushService, db: Session
) -> None:
    _add_sub(db, world.owner_user, Receiver(FCM + "/fcm/send/mine"))
    stranger_sub = _add_sub(db, world.stranger_user, Receiver(FCM + "/fcm/send/stranger"))
    _add_notice(db, world.owner_user, handled=True)
    # A row that points at another household must not receive the owner's notice.
    stranger_sub.user_id = world.owner_user.id
    db.commit()
    _add_notice(db, world.owner_user)

    dispatch_pending(settings)

    assert [r.url.path for r in service.requests] == ["/fcm/send/mine"]


def test_dispatch_does_not_log_notice_text_or_endpoint(
    world: World,
    settings: Settings,
    service: FakePushService,
    db: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _add_sub(db, world.owner_user, Receiver())
    _add_notice(db, world.owner_user, title="Geheimer Titel", body="Geheimer Text")
    service.default_status = 500

    with caplog.at_level(logging.DEBUG):
        dispatch_pending(settings)

    assert "status=500" in caplog.text and "fcm.googleapis.com" in caplog.text
    for secret in ("Geheimer", SECRET_PATH):
        assert secret not in caplog.text


def test_dispatch_handles_more_than_one_batch(
    world: World, settings: Settings, service: FakePushService, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(push, "BATCH_SIZE", 2)
    _add_sub(db, world.owner_user, Receiver())
    for index in range(5):
        _add_notice(db, world.owner_user, title=f"N{index}")

    assert dispatch_pending(settings).sent == 5
