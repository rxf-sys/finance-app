"""Low-level delivery of in-app notifications, shared by contract matching and the daily job."""

import uuid
from collections.abc import Iterable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Notification, NotificationKind
from app.models.base import utcnow


def format_eur(cents: int) -> str:
    """German money format for notification texts, e.g. 123456 -> "1.234,56 EUR"."""
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", ".") + f",{rest:02d} EUR"


def deliver(
    db: Session,
    household_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    *,
    kind: NotificationKind,
    title: str,
    body: str | None,
    link: str | None,
    dedupe_key: str,
) -> int:
    """Insert one row per user; rows that already exist for (user, dedupe_key) are skipped.

    Returns the number of rows actually created.
    """
    rows = [
        {
            "id": uuid.uuid4(),
            "household_id": household_id,
            "user_id": user_id,
            "kind": kind,
            "title": title[:200],
            "body": body,
            "link": link,
            "dedupe_key": dedupe_key[:200],
            "created_at": utcnow(),
        }
        for user_id in user_ids
    ]
    if not rows:
        return 0
    result = db.execute(
        insert(Notification)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(Notification.id)
    )
    return len(result.all())
