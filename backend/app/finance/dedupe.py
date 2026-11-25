"""Deduplication hashes for transactions."""

import hashlib
import uuid
from datetime import date

from app.finance.normalize import normalize_text


def compute_dedupe_hash(
    account_id: uuid.UUID,
    booking_date: date,
    amount_cents: int,
    counterparty_iban: str | None,
    purpose: str | None,
    occurrence: int,
) -> str:
    """Hash of the identifying fields; `occurrence` is the 0-based index among identical rows in a file."""
    key = (
        f"{account_id}|{booking_date.isoformat()}|{amount_cents}|{counterparty_iban or ''}"
        f"|{normalize_text(purpose or '')}|{occurrence}"
    )
    return hashlib.sha256(key.encode()).hexdigest()


def random_dedupe_hash() -> str:
    """For manual entries, which must never collide with an import."""
    return hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()
