"""Validation of the Cloudflare Access JWT sent with every proxied request.

See https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
"""

from functools import lru_cache
from typing import Any

import jwt

HEADER_NAME = "Cf-Access-Jwt-Assertion"


class AccessTokenError(Exception):
    pass


class AccessVerifier:
    def __init__(self, team_domain: str, audience: str) -> None:
        self.issuer = f"https://{team_domain}"
        self.audience = audience
        self._jwks = jwt.PyJWKClient(f"{self.issuer}/cdn-cgi/access/certs", lifespan=3600)

    def signing_key(self, token: str) -> Any:
        return self._jwks.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self.signing_key(token),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AccessTokenError(str(exc)) from exc


@lru_cache
def get_verifier(team_domain: str, audience: str) -> AccessVerifier:
    return AccessVerifier(team_domain, audience)
