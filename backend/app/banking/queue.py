"""Enqueueing background syncs from the API process."""

import logging

from procrastinate.exceptions import AlreadyEnqueued

log = logging.getLogger(__name__)


def enqueue_sync(connection_id: str) -> None:
    """Defer a manual sync; an identical job that is still waiting counts as success."""
    from app.worker import app, sync_connection_task  # noqa: PLC0415 - avoids importing the worker eagerly

    try:
        with app.open():
            sync_connection_task.configure(queueing_lock=f"bank_sync_{connection_id}").defer(
                connection_id=connection_id
            )
    except AlreadyEnqueued:
        log.info("bank sync already queued")
