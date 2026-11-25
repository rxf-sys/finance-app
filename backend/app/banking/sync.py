"""Fetching transactions for bank connections and storing the new ones.

Log lines and stored errors are static: provider bodies and transaction contents never appear.

Where a sync starts, per account:
- after a completed run: that run's start minus an overlap of 7 days;
- before the first run: `Account.sync_from` (set when linking), else 90 days back.
"""

import logging
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banking.client import BankAuthExpired, BankError, BankRateLimited, EnableBankingClient
from app.banking.mapping import MappedTransaction, map_transaction, provider_dedupe_hash
from app.config import Settings, get_settings
from app.deps import MemberContext
from app.finance.contracts import detect_contracts, match_payments
from app.finance.dedupe import compute_dedupe_hash
from app.finance.normalize import normalize_text
from app.finance.rules import apply_rules
from app.finance.transfers import detect_transfers
from app.models import (
    Account,
    BankConnection,
    BankConnectionStatus,
    Notification,
    NotificationKind,
    SyncRun,
    SyncStatus,
    Transaction,
    User,
)
from app.models.base import utcnow
from app.security.crypto import SecretBox

log = logging.getLogger(__name__)

Outcome = Literal["ok", "failed", "stop"]

SESSION_CONTEXT = b"bank_session"
OVERLAP = timedelta(days=7)
DEFAULT_HISTORY = timedelta(days=90)
SYNC_INTERVAL = timedelta(hours=6)
HASH_CHUNK = 1000

ERR_RATE_LIMITED = "The bank limits requests, will retry later"
ERR_EXPIRED = "Bank consent expired, please connect again"
ERR_PROVIDER = "Fetching from the bank failed"


def decrypt_session_id(settings: Settings, connection: BankConnection) -> str | None:
    if connection.session_encrypted is None:
        return None
    box = SecretBox(settings.encryption_key.get_secret_value())
    return box.decrypt(connection.session_encrypted, SESSION_CONTEXT).decode()


def _start_date(db: Session, account: Account, today: date) -> date:
    run = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.account_id == account.id,
            SyncRun.bank_connection_id == account.bank_connection_id,
            SyncRun.status == SyncStatus.COMPLETED,
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    if run is not None:
        return (run.started_at - OVERLAP).date()
    return account.sync_from or today - DEFAULT_HISTORY


def _hashes(account: Account, rows: Sequence[MappedTransaction]) -> list[str]:
    seen: Counter[tuple[date, int, str, str]] = Counter()
    hashes: list[str] = []
    for row in rows:
        if row.entry_reference and account.provider_account_uid:
            hashes.append(provider_dedupe_hash(account.provider_account_uid, row.entry_reference))
            continue
        key = (
            row.booking_date,
            row.amount_cents,
            row.counterparty_iban or "",
            normalize_text(row.purpose or ""),
        )
        hashes.append(
            compute_dedupe_hash(
                account.id,
                row.booking_date,
                row.amount_cents,
                row.counterparty_iban,
                row.purpose,
                seen[key],
            )
        )
        seen[key] += 1
    return hashes


def _existing(db: Session, account: Account, hashes: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for start in range(0, len(hashes), HASH_CHUNK):
        found.update(
            db.scalars(
                select(Transaction.dedupe_hash).where(
                    Transaction.account_id == account.id,
                    Transaction.dedupe_hash.in_(hashes[start : start + HASH_CHUNK]),
                )
            )
        )
    return found


def _owner_context(db: Session, connection: BankConnection) -> MemberContext | None:
    """The connection owner as a household member, or None once they left or were deleted."""
    if connection.owner_user_id is None:
        return None
    user = db.get(User, connection.owner_user_id)
    membership = user.membership if user is not None else None
    if user is None or membership is None or membership.household_id != connection.household_id:
        return None
    return MemberContext(user, membership.household, membership.role)


def _after_ingest(
    db: Session,
    household_id: uuid.UUID,
    new_transactions: Sequence[Transaction],
    owner: MemberContext | None,
) -> None:
    """Everything that runs on freshly fetched rows, in the same order as a CSV import.

    Transfers are paired only with accounts the connection owner can see, like an import by them;
    without an owner nothing is paired.
    """
    if not new_transactions:
        return
    apply_rules(db, household_id, new_transactions)
    if owner is not None:
        detect_transfers(db, household_id, new_transactions, member=owner)
    match_payments(db, household_id, new_transactions)
    detect_contracts(db, household_id, account_ids={t.account_id for t in new_transactions})
    db.flush()


def _ingest(db: Session, account: Account, raw: Iterable[dict[str, Any]]) -> tuple[list[Transaction], int]:
    """Insert unseen booked rows of one account; return them and the number of duplicates."""
    mapped = [
        m
        for item in raw
        if (m := map_transaction(item, account.currency)) is not None and m.currency == account.currency
    ]
    hashes = _hashes(account, mapped)
    known = _existing(db, account, hashes)
    new: list[Transaction] = []
    duplicates = 0
    for row, dedupe_hash in zip(mapped, hashes, strict=True):
        if dedupe_hash in known:
            duplicates += 1
            continue
        known.add(dedupe_hash)
        new.append(
            Transaction(
                id=uuid.uuid4(),
                household_id=account.household_id,
                account_id=account.id,
                booking_date=row.booking_date,
                value_date=row.value_date,
                amount_cents=row.amount_cents,
                currency=row.currency,
                counterparty_name=row.counterparty_name,
                counterparty_iban=row.counterparty_iban,
                purpose=row.purpose,
                booking_text=row.booking_text,
                raw=row.raw,
                dedupe_hash=dedupe_hash,
                splits=[],
                tags=[],
            )
        )
    db.add_all(new)
    db.flush()
    return new, duplicates


def _notify_expired(db: Session, connection: BankConnection, today: date) -> None:
    if connection.owner_user_id is None:
        return
    key = f"sync_failed:{connection.id}:{today.isoformat()}"
    exists = db.scalar(
        select(Notification.id).where(
            Notification.user_id == connection.owner_user_id, Notification.dedupe_key == key
        )
    )
    if exists is not None:
        return
    db.add(
        Notification(
            household_id=connection.household_id,
            user_id=connection.owner_user_id,
            kind=NotificationKind.SYNC_FAILED,
            title="Bankverbindung abgelaufen",
            body=f"Die Zustimmung für {connection.aspsp_name} ist abgelaufen. Bitte verbinde das Konto neu.",
            link=f"/bank?connection={connection.id}",
            dedupe_key=key,
        )
    )


def _mark_expired(db: Session, connection: BankConnection, today: date) -> None:
    connection.status = BankConnectionStatus.EXPIRED
    connection.last_error = ERR_EXPIRED
    _notify_expired(db, connection, today)


def sync_connection(
    db: Session,
    connection: BankConnection,
    *,
    today: date,
    client: EnableBankingClient | None = None,
    settings: Settings | None = None,
) -> None:
    """Sync every linked account. The caller commits. Never raises for provider failures."""
    settings = settings or get_settings()
    # One sync per connection at a time (hourly job and manual task may overlap).
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(connection.id), 0))))
    db.refresh(connection)
    if connection.status is not BankConnectionStatus.ACTIVE:
        return
    now = utcnow()
    if connection.consent_valid_until is not None and connection.consent_valid_until <= now:
        _mark_expired(db, connection, today)
        return
    accounts = db.scalars(
        select(Account)
        .where(Account.bank_connection_id == connection.id, Account.provider_account_uid.is_not(None))
        .order_by(Account.created_at)
    ).all()
    if not accounts:
        connection.last_sync_at = now
        return
    own_client = client is None
    if client is None:
        client = EnableBankingClient.from_settings(settings)
    owner = _owner_context(db, connection)
    failed = False
    try:
        for account in accounts:
            outcome = _sync_account(db, connection, account, client, owner, today=today)
            failed = failed or outcome != "ok"
            if outcome == "stop":
                break
    finally:
        if own_client:
            client.close()
    connection.last_sync_at = now
    if connection.status is BankConnectionStatus.ACTIVE and not failed:
        connection.last_error = None


def _sync_account(
    db: Session,
    connection: BankConnection,
    account: Account,
    client: EnableBankingClient,
    owner: MemberContext | None,
    *,
    today: date,
) -> Outcome:
    """Sync one account. "stop" means the other accounts of the connection should not be tried."""
    started = utcnow()
    run = SyncRun(
        id=uuid.uuid4(),
        household_id=connection.household_id,
        bank_connection_id=connection.id,
        account_id=account.id,
        status=SyncStatus.COMPLETED,
        started_at=started,
    )
    assert account.provider_account_uid is not None  # noqa: S101 - filtered by the query
    outcome: Outcome
    try:
        with db.begin_nested():
            from_date = _start_date(db, account, today)
            raw = client.get_transactions(account.provider_account_uid, from_date)
            new, duplicates = _ingest(db, account, raw)
            _after_ingest(db, account.household_id, new, owner)
        run.rows_new, run.rows_duplicate = len(new), duplicates
    except BankAuthExpired:
        run.status, run.error = SyncStatus.FAILED, ERR_EXPIRED
        _mark_expired(db, connection, today)
        outcome = "stop"
    except BankRateLimited:
        run.status, run.error = SyncStatus.FAILED, ERR_RATE_LIMITED
        connection.last_error = ERR_RATE_LIMITED
        outcome = "stop"
    except BankError:
        run.status, run.error = SyncStatus.FAILED, ERR_PROVIDER
        connection.last_error = ERR_PROVIDER
        outcome = "failed"
    else:
        outcome = "ok"
    run.finished_at = utcnow()
    db.add(run)
    db.flush()
    if outcome != "ok":
        log.warning("bank sync failed for a connection: %s", run.error)
    return outcome


def sync_due_connections(
    db: Session,
    now: datetime,
    *,
    client: EnableBankingClient | None = None,
    settings: Settings | None = None,
) -> int:
    """Sync active connections not fetched for 6 hours (many banks allow 4 unattended fetches a day).

    Commits after each connection so one failure does not undo the others. Returns the number tried.
    """
    cutoff = now - SYNC_INTERVAL
    ids = db.scalars(
        select(BankConnection.id).where(
            BankConnection.status == BankConnectionStatus.ACTIVE,
            (BankConnection.last_sync_at.is_(None)) | (BankConnection.last_sync_at < cutoff),
        )
    ).all()
    done = 0
    for connection_id in ids:
        connection = db.get(BankConnection, connection_id)
        if connection is None:
            continue
        try:
            sync_connection(
                db, connection, today=now.astimezone(UTC).date(), client=client, settings=settings
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            # Only the type: database errors can echo row values.
            log.error("bank sync crashed for a connection: %s", type(exc).__name__)
            continue
        done += 1
    return done
