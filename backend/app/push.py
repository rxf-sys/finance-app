"""Sending Web Push messages: one delivery, plus the dispatcher that turns notifications into pushes.

Endpoints, payloads and notification texts are never logged; failures log the status code and the
push service host only.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select, update

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import Notification, PushSubscription
from app.models.base import utcnow
from app.security.webpush import (
    MAX_PLAINTEXT,
    VapidKey,
    b64url_decode,
    encrypt,
    validate_endpoint,
)

log = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and the URL of a push endpoint is a secret.
logging.getLogger("httpx").setLevel(logging.WARNING)

TIMEOUT = httpx.Timeout(10.0)
TTL_SECONDS = 86400
BATCH_SIZE = 200
# A notice that could not be pushed within a day is stale; it stays in the app only.
MAX_PUSH_AGE = timedelta(hours=24)
ELLIPSIS = "…"


class Outcome(StrEnum):
    SENT = "sent"
    GONE = "gone"  # the push service says the subscription no longer exists
    FAILED = "failed"


class Subscription(Protocol):
    @property
    def endpoint(self) -> str: ...
    @property
    def p256dh(self) -> str: ...
    @property
    def auth(self) -> str: ...


@dataclass(frozen=True)
class Target:
    """The parts of a subscription needed for sending, detached from the database session."""

    id: uuid.UUID
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class Message:
    target: Target
    payload: bytes


@dataclass(frozen=True)
class DeliveryResult:
    sent: int = 0
    failed: int = 0
    removed: int = 0


def build_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Tests pass an `httpx.MockTransport`, like for the banking client."""
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport)


def _host(endpoint: str) -> str:
    return urlsplit(endpoint).hostname or "unknown"


def _json(title: str, body: str, url: str) -> bytes:
    return json.dumps(
        {"title": title, "body": body, "url": url}, ensure_ascii=False, separators=(",", ":")
    ).encode()


def build_payload(title: str, body: str | None, url: str | None) -> bytes:
    """UTF-8 JSON for the service worker; the body is shortened so the message fits one record."""
    url = url or "/"
    text = body or ""
    encoded = _json(title, text, url)
    if len(encoded) <= MAX_PLAINTEXT:
        return encoded
    # Byte budget for the body (JSON escapes can grow it, hence the loop below).
    budget = MAX_PLAINTEXT - len(_json(title, ELLIPSIS, url))
    if budget < 0:
        raise ValueError("push title and url are too long")
    cut = text.encode()[:budget].decode(errors="ignore").rstrip()
    while True:
        encoded = _json(title, cut + ELLIPSIS, url)
        if len(encoded) <= MAX_PLAINTEXT or not cut:
            return encoded
        cut = cut[: len(cut) - max(1, (len(encoded) - MAX_PLAINTEXT) // 6)]


def send(
    client: httpx.Client, subscription: Subscription, payload: bytes, vapid: VapidKey, subject: str
) -> Outcome:
    host = _host(subscription.endpoint)
    try:
        validate_endpoint(subscription.endpoint)
        body = encrypt(payload, b64url_decode(subscription.p256dh), b64url_decode(subscription.auth))
    except ValueError:
        log.warning("push not sent: invalid subscription, host=%s", host)
        return Outcome.FAILED
    headers = {
        "TTL": str(TTL_SECONDS),
        "Urgency": "normal",
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "Authorization": vapid.authorization(subscription.endpoint, subject),
    }
    try:
        response = client.post(subscription.endpoint, content=body, headers=headers)
    except httpx.TransportError as exc:
        log.warning("push failed: %s, host=%s", type(exc).__name__, host)
        return Outcome.FAILED
    status = response.status_code
    if 200 <= status < 300:
        return Outcome.SENT
    if status in (404, 410):
        return Outcome.GONE
    log.warning("push failed: status=%s, host=%s", status, host)
    return Outcome.FAILED


def deliver(
    client: httpx.Client, messages: list[Message], vapid: VapidKey, subject: str
) -> tuple[list[uuid.UUID], list[uuid.UUID], int]:
    """Send all messages; returns (sent ids, gone ids, failed count)."""
    sent: list[uuid.UUID] = []
    gone: list[uuid.UUID] = []
    failed = 0
    for message in messages:
        match send(client, message.target, message.payload, vapid, subject):
            case Outcome.SENT:
                sent.append(message.target.id)
            case Outcome.GONE:
                gone.append(message.target.id)
            case Outcome.FAILED:
                failed += 1
    return sent, gone, failed


def record_outcomes(sent: list[uuid.UUID], gone: list[uuid.UUID], now: datetime) -> None:
    with get_sessionmaker().begin() as db:
        if gone:
            db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
        if sent:
            db.execute(
                update(PushSubscription).where(PushSubscription.id.in_(sent)).values(last_success_at=now)
            )


def load_vapid(settings: Settings) -> VapidKey | None:
    """The configured key, or None while push is disabled. Raises ValueError for an unusable PEM."""
    key = settings.vapid_private_key
    if not settings.push_enabled or key is None:
        return None
    return VapidKey.from_pem(key.get_secret_value())


def dispatch_pending(settings: Settings | None = None, *, now: datetime | None = None) -> DeliveryResult:
    """Push every notification that has not been handled yet, each at most once.

    Claiming happens in one transaction (`FOR UPDATE SKIP LOCKED`, then `push_handled_at` is set), so
    concurrent workers never pick the same notice. Sending happens afterwards, outside of it: a crash
    in between loses a push but never duplicates one.
    """
    settings = settings or get_settings()
    now = now or utcnow()
    subject = settings.resolved_vapid_subject
    try:
        vapid = load_vapid(settings)
    except ValueError:
        log.error("FA_VAPID_PRIVATE_KEY is not a valid P-256 PEM key; push is paused")
        return DeliveryResult()

    total = DeliveryResult()
    while True:
        messages, claimed = _claim(vapid is not None, now)
        if messages and vapid is not None and subject is not None:
            with build_client() as client:
                sent, gone, failed = deliver(client, messages, vapid, subject)
            record_outcomes(sent, gone, utcnow())
            total = DeliveryResult(total.sent + len(sent), total.failed + failed, total.removed + len(gone))
        if claimed < BATCH_SIZE:
            return total


def _claim(enabled: bool, now: datetime) -> tuple[list[Message], int]:
    """Mark one batch handled and return the messages to send plus the batch size."""
    with get_sessionmaker().begin() as db:
        notices = db.scalars(
            select(Notification)
            .where(Notification.push_handled_at.is_(None))
            .order_by(Notification.created_at, Notification.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()
        messages: list[Message] = []
        if enabled:
            fresh = [n for n in notices if n.created_at >= now - MAX_PUSH_AGE]
            user_ids = {n.user_id for n in fresh}
            by_user: dict[uuid.UUID, list[PushSubscription]] = {}
            if user_ids:
                subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids)))
                for sub in subs:
                    by_user.setdefault(sub.user_id, []).append(sub)
            for notice in fresh:
                payload = build_payload(notice.title, notice.body, notice.link)
                for sub in by_user.get(notice.user_id, []):
                    if sub.household_id == notice.household_id:
                        messages.append(Message(Target(sub.id, sub.endpoint, sub.p256dh, sub.auth), payload))
        for notice in notices:
            notice.push_handled_at = now
        return messages, len(notices)
