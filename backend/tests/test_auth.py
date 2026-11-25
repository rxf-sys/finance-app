import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog, User
from app.sessions import COOKIE_NAME
from tests.conftest import DEFAULT_PASSWORD, UserFactory, login


def test_health_needs_no_login(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_me_requires_login(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_login_sets_http_only_strict_cookie(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    response = client.post(
        "/api/auth/login", json={"email": "Owner@Example.com ", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "owner"
    cookie = response.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json()["email"] == "owner@example.com"


def test_session_cookie_is_secure_when_configured(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    secure = get_settings().model_copy(update={"cookie_secure": True})
    client.app.dependency_overrides[get_settings] = lambda: secure  # type: ignore[attr-defined]

    response = client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": DEFAULT_PASSWORD}
    )

    assert "secure" in response.headers["set-cookie"].lower()


def test_wrong_password_and_unknown_user_look_the_same(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    wrong = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_account_locks_after_repeated_failures(
    client: TestClient, make_user: UserFactory, db: Session
) -> None:
    make_user()
    for _ in range(get_settings().login_max_failures):
        client.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope"})

    response = client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 429
    failures = db.scalars(select(AuditLog).where(AuditLog.action == "login_failed")).all()
    assert len(failures) == get_settings().login_max_failures


def test_logout_ends_session(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    login(client, "owner@example.com")

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_totp_enrollment_and_login(client: TestClient, make_user: UserFactory, db: Session) -> None:
    make_user()
    login(client, "owner@example.com")
    setup = client.post("/api/auth/totp/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(setup["secret"])

    assert client.post("/api/auth/totp/confirm", json={"code": "000000"}).status_code == 400
    assert client.post("/api/auth/totp/confirm", json={"code": totp.now()}).status_code == 204
    stored = db.scalar(select(User).where(User.email == "owner@example.com"))
    assert stored is not None and stored.totp_secret_encrypted is not None
    assert stored.totp_last_used_step is not None
    assert setup["secret"].encode() not in stored.totp_secret_encrypted
    used_step = stored.totp_last_used_step

    client.post("/api/auth/logout")
    first = client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": DEFAULT_PASSWORD}
    ).json()
    assert first["status"] == "mfa_required" and client.get("/api/auth/me").status_code == 401

    # The code used for confirmation cannot be replayed.
    replay = client.post(
        "/api/auth/login/totp", json={"mfa_token": first["mfa_token"], "code": totp.at(used_step * 30)}
    )
    assert replay.status_code == 401

    next_code = totp.at((used_step + 1) * 30)
    done = client.post("/api/auth/login/totp", json={"mfa_token": first["mfa_token"], "code": next_code})
    assert done.status_code == 200
    assert client.get("/api/auth/me").json()["has_totp"] is True


def test_password_change_requires_current_password(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    login(client, "owner@example.com")
    new = "an even longer passphrase"

    wrong = client.post("/api/auth/password", json={"current_password": "nope", "new_password": new})
    assert wrong.status_code == 400
    ok = client.post("/api/auth/password", json={"current_password": DEFAULT_PASSWORD, "new_password": new})
    assert ok.status_code == 204
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    login(client, "owner@example.com", new)


def test_passkey_options_and_invalid_registration(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    login(client, "owner@example.com")
    options = client.post("/api/auth/passkeys/register/options").json()
    assert options["options"]["rp"]["id"] == "testserver"
    assert options["options"]["authenticatorSelection"]["residentKey"] == "required"

    bogus = {"id": "AAAA", "rawId": "AAAA", "type": "public-key", "response": {}}
    payload = {"challenge_id": options["challenge_id"], "name": "Laptop", "credential": bogus}
    assert client.post("/api/auth/passkeys/register/verify", json=payload).status_code == 400
    # The challenge is single-use, even after a failed attempt.
    assert client.post("/api/auth/passkeys/register/verify", json=payload).status_code == 400
    assert client.get("/api/auth/passkeys").json() == []


def test_passkey_login_with_unknown_credential_fails(client: TestClient) -> None:
    options = client.post("/api/auth/passkeys/login/options").json()
    assert options["options"]["userVerification"] == "required"
    payload = {
        "challenge_id": options["challenge_id"],
        "credential": {"id": "AAAA", "rawId": "AAAA", "type": "public-key", "response": {}},
    }
    assert client.post("/api/auth/passkeys/login/verify", json=payload).status_code == 401
