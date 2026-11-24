from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security import cloudflare_access

TEAM = "example.cloudflareaccess.com"
AUD = "test-audience"
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(audience: str = AUD, expires_in: timedelta = timedelta(minutes=5)) -> str:
    now = datetime.now(UTC)
    claims = {
        "aud": [audience],
        "iss": f"https://{TEAM}",
        "iat": now,
        "exp": now + expires_in,
        "email": "a@b.de",
    }
    return jwt.encode(claims, _key, algorithm="RS256")


@pytest.fixture
def access_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    settings = get_settings().model_copy(
        update={"cf_access_enabled": True, "cf_access_team_domain": TEAM, "cf_access_aud": AUD}
    )
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    monkeypatch.setattr(
        cloudflare_access.AccessVerifier, "signing_key", lambda self, token: _key.public_key()
    )
    yield client


def test_missing_token_is_rejected(access_client: TestClient) -> None:
    assert access_client.get("/api/auth/me").status_code == 403


def test_valid_token_passes_through_to_app_login(access_client: TestClient) -> None:
    response = access_client.get("/api/auth/me", headers={cloudflare_access.HEADER_NAME: _token()})
    assert response.status_code == 401  # Access passed, app login still required


@pytest.mark.parametrize(
    "token",
    [_token(audience="someone-else"), _token(expires_in=timedelta(minutes=-1)), "not-a-jwt"],
    ids=["wrong-audience", "expired", "garbage"],
)
def test_invalid_tokens_are_rejected(access_client: TestClient, token: str) -> None:
    assert (
        access_client.get("/api/auth/me", headers={cloudflare_access.HEADER_NAME: token}).status_code == 403
    )


def test_health_stays_reachable_for_docker(access_client: TestClient) -> None:
    assert access_client.get("/api/health").status_code == 200
