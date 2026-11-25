"""Background job queue (Procrastinate on Postgres).

Run with: procrastinate --app=app.worker.app worker
"""

import logging
import uuid
from datetime import timedelta

import procrastinate
from sqlalchemy import delete, or_, select

from app.banking.sync import sync_connection, sync_due_connections
from app.config import get_settings
from app.db import get_sessionmaker
from app.finance.contracts import detect_contracts, today_berlin
from app.finance.notifications import generate_notifications
from app.models import AuthChallenge, BankConnection, Household, Invite, UserSession
from app.models.base import utcnow
from app.push import dispatch_pending

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
    # Only after the commit: the dispatcher reads the new notices in its own transaction.
    dispatch_pending()


@app.periodic(cron="*/2 * * * *")
@app.task(queueing_lock="dispatch_push")
def dispatch_push(timestamp: int) -> None:
    """Every 2 minutes: push notifications created since the last run (also by bank syncs)."""
    dispatch_pending()


log = logging.getLogger(__name__)


@app.periodic(cron="23 * * * *")
@app.task(queueing_lock="bank_sync_due")
def sync_bank_connections(timestamp: int) -> None:
    """Hourly: fetch connections whose last fetch is older than 6 hours."""
    if not get_settings().bank_sync_enabled:
        return
    with get_sessionmaker()() as db:
        sync_due_connections(db, utcnow())


@app.task
def sync_connection_task(connection_id: str) -> None:
    """Manual sync requested through the API."""
    settings = get_settings()
    if not settings.bank_sync_enabled:
        return
    with get_sessionmaker().begin() as db:
        connection = db.get(BankConnection, uuid.UUID(connection_id))
        if connection is None:
            return
        sync_connection(db, connection, today=utcnow().date(), settings=settings)
