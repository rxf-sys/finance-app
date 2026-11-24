"""Shared FastAPI dependencies."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Household, HouseholdRole, User
from app.security.cloudflare_access import HEADER_NAME, AccessTokenError, get_verifier
from app.sessions import COOKIE_NAME, load_session

DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_cloudflare_access(request: Request, settings: SettingsDep) -> None:
    """Reject requests that did not pass Cloudflare Access (when enabled)."""
    if not settings.cf_access_enabled:
        return
    token = request.headers.get(HEADER_NAME)
    if not token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cloudflare Access token missing")
    team_domain, audience = settings.cf_access_team_domain, settings.cf_access_aud
    if not (team_domain and audience):
        raise RuntimeError("Cloudflare Access is enabled but not configured")
    try:
        get_verifier(team_domain, audience).verify(token)
    except AccessTokenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cloudflare Access token invalid") from exc


def current_user(
    db: DbDep,
    settings: SettingsDep,
    session_token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User:
    if session_token:
        session = load_session(db, session_token, settings)
        if session is not None:
            return session.user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")


CurrentUser = Annotated[User, Depends(current_user)]


@dataclass(frozen=True)
class MemberContext:
    user: User
    household: Household
    role: HouseholdRole

    @property
    def is_owner(self) -> bool:
        return self.role is HouseholdRole.OWNER


def current_member(user: CurrentUser) -> MemberContext:
    if user.membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User belongs to no household")
    return MemberContext(user, user.membership.household, user.membership.role)


CurrentMember = Annotated[MemberContext, Depends(current_member)]


def current_owner(member: CurrentMember) -> MemberContext:
    if not member.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the household owner can do this")
    return member


CurrentOwner = Annotated[MemberContext, Depends(current_owner)]
