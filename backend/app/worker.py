"""Background job queue (Procrastinate on Postgres).

Run with: procrastinate --app=app.worker.app worker
"""

from datetime import timedelta

import procrastinate
from sqlalchemy import delete, or_, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.finance.contracts import detect_contracts, today_berlin
from app.finance.notifications import generate_notifications
from app.models import AuthChallenge, Household, Invite, UserSession
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


@app.periodic(cron="30 3 * * *", tzinfo="Europe/Berlin")
@app.task(queueing_lock="detect_contracts_nightly")
def detect_contracts_nightly(timestamp: int) -> None:
    """Look for new recurring payments in every household. Contracts keep their account's visibility."""
    with get_sessionmaker().begin() as db:
        for household_id in db.scalars(select(Household.id).order_by(Household.id)).all():
            detect_contracts(db, household_id)


@app.periodic(cron="5 6 * * *", tzinfo="Europe/Berlin")
@app.task(queueing_lock="generate_notifications")
def generate_notifications_daily(timestamp: int) -> None:
    """Create deadline, budget and consent notices; safe to rerun thanks to dedupe keys."""
    with get_sessionmaker().begin() as db:
        generate_notifications(db, today_berlin())
