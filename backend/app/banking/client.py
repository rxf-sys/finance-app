"""Small typed client for the Enable Banking REST API.

Response bodies can contain account and transaction data, so they are never put into exception
messages or logs. Only a status code and, for control flow, a short upper-case error code are kept.

Source for everything below: https://enablebanking.com/docs/api/reference/ (see the research notes;
fields marked unverified there are read defensively).
"""

import re
import time
from datetime import date, datetime
from typing import Any

import httpx
import jwt

from app.config import Settings

JWT_TTL_SECONDS = 3600
_TOKEN_REFRESH_MARGIN = 300
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_PAGES = 200
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z_]{2,63}$")
_EXPIRED_CODES = {"EXPIRED_SESSION", "SESSION_EXPIRED", "CLOSED_SESSION", "REVOKED_SESSION"}


class BankError(Exception):
    """A failed provider call. The message is static and safe to log."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class BankAuthExpired(BankError):  # noqa: N818 - reads better than "BankAuthExpiredError"
    """The consent or session is no longer valid; the user has to authorise again."""


class BankRateLimited(BankError):  # noqa: N818
    """The bank or the provider limits requests (HTTP 429)."""


def build_jwt(app_id: str, private_key_pem: str, *, now: float | None = None) -> str:
    """RS256 JWT identifying the application.

    Header: typ JWT, alg RS256, kid = application id. Claims: iss "enablebanking.com",
    aud "api.enablebanking.com", iat, exp. Maximum lifetime is 24 h; we use 1 h like the quick start.
    Source: https://enablebanking.com/docs/api/reference/ and https://enablebanking.com/docs/api/quick-start
    """
    issued = int(time.time() if now is None else now)
    return jwt.encode(
        {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": issued,
            "exp": issued + JWT_TTL_SECONDS,
        },
        private_key_pem,
        algorithm="RS256",
        headers={"kid": app_id, "typ": "JWT"},
    )


def _error_code(response: httpx.Response) -> str | None:
    """The provider's error code if the body has one that looks like a code; nothing else is kept."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("error", "code"):
        value = body.get(key)
        if isinstance(value, str) and _ERROR_CODE_RE.fullmatch(value):
            return value
    return None


class EnableBankingClient:
    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        *,
        base_url: str = "https://api.enablebanking.com",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._key = private_key_pem.replace("\\n", "\n")
        self._token: str | None = None
        self._token_exp = 0.0
        self._http = httpx.Client(base_url=base_url, timeout=TIMEOUT, transport=transport)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx.BaseTransport | None = None
    ) -> "EnableBankingClient":
        key = settings.enablebanking_private_key
        if not (settings.enablebanking_app_id and key):
            raise BankError("Bank sync is not configured")
        return cls(
            settings.enablebanking_app_id,
            key.get_secret_value(),
            base_url=settings.enablebanking_api_base,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "EnableBankingClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _auth_header(self) -> dict[str, str]:
        now = time.time()
        if self._token is None or now >= self._token_exp - _TOKEN_REFRESH_MARGIN:
            self._token = build_jwt(self._app_id, self._key, now=now)
            self._token_exp = now + JWT_TTL_SECONDS
        return {"Authorization": f"Bearer {self._token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, params=params, json=json, headers=self._auth_header())
        except httpx.HTTPError:
            # The exception text can contain the URL (account uids); keep the message static.
            raise BankError("Bank provider is unreachable") from None
        if response.status_code >= 400:
            self._raise_for(response)
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError:
            raise BankError("Bank provider returned an invalid response") from None
        if not isinstance(body, dict):
            raise BankError("Bank provider returned an unexpected response")
        return body

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        status = response.status_code
        code = _error_code(response)
        if status == 429:
            raise BankRateLimited("Bank provider rate limit reached", status_code=status, code=code)
        # A 401 can have other causes (a rejected application JWT); the FAQ names EXPIRED_SESSION.
        if status == 401 or (code is not None and (code in _EXPIRED_CODES or "EXPIRED" in code)):
            raise BankAuthExpired("Bank consent is no longer valid", status_code=status, code=code)
        raise BankError(f"Bank provider request failed with status {status}", status_code=status, code=code)

    def list_aspsps(self, country: str) -> list[dict[str, Any]]:
        body = self._request("GET", "/aspsps", params={"country": country})
        items = body.get("aspsps")
        return [a for a in items if isinstance(a, dict)] if isinstance(items, list) else []

    def start_auth(
        self,
        aspsp_name: str,
        country: str,
        redirect_url: str,
        state: str,
        valid_until: datetime,
    ) -> str:
        body = self._request(
            "POST",
            "/auth",
            json={
                "access": {"valid_until": valid_until.isoformat().replace("+00:00", "Z")},
                "aspsp": {"name": aspsp_name, "country": country},
                "state": state,
                "redirect_url": redirect_url,
                "psu_type": "personal",
            },
        )
        url = body.get("url")
        if not isinstance(url, str) or not url:
            raise BankError("Bank provider returned no authorisation URL")
        return url

    def create_session(self, code: str) -> dict[str, Any]:
        return self._request("POST", "/sessions", json={"code": code})

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}")

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"/sessions/{session_id}")

    def get_transactions(
        self, account_uid: str, date_from: date, continuation_key: str | None = None
    ) -> list[dict[str, Any]]:
        """All transactions since `date_from`, following `continuation_key` until it is absent."""
        out: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for _ in range(MAX_PAGES):
            params = {"date_from": date_from.isoformat()}
            if continuation_key:
                params["continuation_key"] = continuation_key
            body = self._request("GET", f"/accounts/{account_uid}/transactions", params=params)
            page = body.get("transactions")
            if isinstance(page, list):
                out.extend(t for t in page if isinstance(t, dict))
            next_key = body.get("continuation_key")
            if not isinstance(next_key, str) or not next_key or next_key in seen_keys:
                return out
            seen_keys.add(next_key)
            continuation_key = next_key
        raise BankError("Bank provider returned too many transaction pages")

    def get_balances(self, account_uid: str) -> list[dict[str, Any]]:
        body = self._request("GET", f"/accounts/{account_uid}/balances")
        items = body.get("balances")
        return [b for b in items if isinstance(b, dict)] if isinstance(items, list) else []
