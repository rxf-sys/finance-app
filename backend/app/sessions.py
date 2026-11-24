"""Server-side login sessions stored in Postgres, referenced by an opaque cookie."""

from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, User, UserSession
from app.models.base import utcnow
from app.security.tokens import generate_token, hash_token

COOKIE_NAME = "fa_session"
# Only write last_seen_at when it is older than this, to avoid a write per request.
TOUCH_INTERVAL = timedelta(minutes=1)


def client_ip(request: Request, settings: Settings) -> str | None:
    if settings.trust_cf_connecting_ip:
        forwarded = request.headers.get("Cf-Connecting-IP")
        if forwarded:
            return forwarded[:45]
    return request.client.host if request.client else None


def audit(
    db: Session,
    request: Request,
    settings: Settings,
    action: str,
    user: User | None = None,
    **details: str,
) -> None:
    db.add(
        AuditLog(
            action=action,
            user_id=user.id if user else None,
            ip=client_ip(request, settings),
            details=details,
        )
    )


def start_session(db: Session, request: Request, response: Response, settings: Settings, user: User) -> None:
    token = generate_token()
    now = utcnow()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_max_age_hours),
            ip=client_ip(request, settings),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    )
    user.failed_login_count = 0
    user.locked_until = None
    audit(db, request, settings, "login", user)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_max_age_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def load_session(db: Session, token: str, settings: Settings) -> UserSession | None:
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None:
        return None
    now = utcnow()
    idle_limit = session.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if now >= session.expires_at or now >= idle_limit or not session.user.is_active:
        # Expired rows are removed by the worker's cleanup task.
        return None
    if now - session.last_seen_at > TOUCH_INTERVAL:
        session.last_seen_at = now
    return session


def end_session(db: Session, token: str | None, response: Response) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    response.delete_cookie(COOKIE_NAME, path="/")


def end_all_sessions(db: Session, user: User) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
