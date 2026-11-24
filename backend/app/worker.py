"""Background job queue (Procrastinate on Postgres).

Run with: procrastinate --app=app.worker.app worker
"""

from datetime import timedelta

import procrastinate
from sqlalchemy import delete, or_

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import AuthChallenge, Invite, UserSession
from app.models.base import utcnow

app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_conninfo))

# Keep expired invites a while so the owner can still see they lapsed.
INVITE_RETENTION = timedelta(days=30)


@app.periodic(cron="17 3 * * *")
@app.task(queueing_lock="cleanup_expired")
def cleanup_expired(timestamp: int) -> None:
    """Remove expired sessions, challenges and old invites once a day."""
    settings = get_settings()
    now = utcnow()
    idle_cutoff = now - timedelta(minutes=settings.session_idle_minutes)
    with get_sessionmaker().begin() as db:
        db.execute(
            delete(UserSession).where(
                or_(UserSession.expires_at <= now, UserSession.last_seen_at <= idle_cutoff)
            )
        )
        db.execute(delete(AuthChallenge).where(AuthChallenge.expires_at <= now))
        db.execute(delete(Invite).where(Invite.expires_at <= now - INVITE_RETENTION))
