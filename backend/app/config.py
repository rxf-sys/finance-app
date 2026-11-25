"""Application settings, loaded from environment variables and Docker secrets."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import quote

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DOCKER_SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    """All settings use the ``FA_`` prefix, e.g. ``FA_DB_HOST``.

    Secrets can also be provided as files in ``/run/secrets`` named like the
    variable in lower case, e.g. ``/run/secrets/fa_db_password``.
    """

    model_config = SettingsConfigDict(env_prefix="FA_", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "Finance App"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "finance"
    db_user: str = "finance"
    db_password: SecretStr = SecretStr("")

    # 32 random bytes, base64 encoded. Used to encrypt TOTP secrets at rest.
    encryption_key: SecretStr

    # Public URL of the app, used as WebAuthn origin and for invite links.
    public_origin: str = "http://localhost:5173"
    webauthn_rp_id: str = "localhost"

    cookie_secure: bool = True
    session_idle_minutes: int = 8 * 60
    session_max_age_hours: int = 7 * 24

    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    invite_ttl_hours: int = 72

    # Cloudflare Access: when enabled, every API request except /api/health
    # must carry a valid Cf-Access-Jwt-Assertion header.
    cf_access_enabled: bool = False
    cf_access_team_domain: str | None = None  # e.g. "example.cloudflareaccess.com"
    cf_access_aud: str | None = None
    # Use the Cf-Connecting-IP header as client IP (only behind the tunnel).
    trust_cf_connecting_ip: bool = False

    @model_validator(mode="after")
    def _check_cf_access(self) -> Self:
        if self.cf_access_enabled and not (self.cf_access_team_domain and self.cf_access_aud):
            raise ValueError(
                "FA_CF_ACCESS_TEAM_DOMAIN and FA_CF_ACCESS_AUD are required when FA_CF_ACCESS_ENABLED is true"
            )
        return self

    def _db_auth(self) -> str:
        password = quote(self.db_password.get_secret_value(), safe="")
        return f"{quote(self.db_user, safe='')}:{password}@{self.db_host}:{self.db_port}"

    @property
    def sqlalchemy_url(self) -> str:
        return f"postgresql+psycopg://{self._db_auth()}/{self.db_name}"

    @property
    def psycopg_conninfo(self) -> str:
        return f"postgresql://{self._db_auth()}/{self.db_name}"


@lru_cache
def get_settings() -> Settings:
    secrets_dir = DOCKER_SECRETS_DIR if DOCKER_SECRETS_DIR.is_dir() else None
    return Settings(_secrets_dir=secrets_dir)
