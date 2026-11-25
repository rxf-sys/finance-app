"""Web Push: browser subscriptions of the current user and a test message.

The endpoint of a subscription is a secret only that browser knows: it is never returned, logged or
written to the audit log (only the push service host is).
"""

from collections.abc import Iterator
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update

from app.api.common import conflict_on_duplicate
from app.config import Settings
from app.deps import CurrentMember, DbDep, SettingsDep
from app.models import PushSubscription
from app.models.base import utcnow
from app.push import Message, Target, build_client, build_payload, deliver, load_vapid
from app.security.webpush import validate_endpoint, validate_subscription_keys
from app.sessions import audit

router = APIRouter(prefix="/push", tags=["push"])

USER_AGENT_MAX = 200
ENDPOINT_MAX = 2048
TEST_TITLE = "Testbenachrichtigung"
TEST_BODY = "Push-Benachrichtigungen funktionieren auf diesem Gerät."


class PushConfig(BaseModel):
    enabled: bool
    public_key: str | None


class SubscriptionKeys(BaseModel):
    p256dh: Annotated[str, Field(min_length=1, max_length=100)]
    auth: Annotated[str, Field(min_length=1, max_length=30)]


class SubscriptionIn(BaseModel):
    """Shaped like the browser's `PushSubscription.toJSON()`."""

    model_config = ConfigDict(populate_by_name=True)

    endpoint: Annotated[str, Field(min_length=1, max_length=ENDPOINT_MAX)]
    expiration_time: Annotated[float | None, Field(alias="expirationTime")] = None
    keys: SubscriptionKeys


class UnsubscribeIn(BaseModel):
    endpoint: Annotated[str, Field(min_length=1, max_length=ENDPOINT_MAX)]


class PushTestResult(BaseModel):
    sent: int
    failed: int
    removed: int


def require_push(settings: SettingsDep) -> Settings:
    if not settings.push_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push is not configured")
    return settings


PushSettings = Annotated[Settings, Depends(require_push)]


def get_push_client() -> Iterator[httpx.Client]:
    client = build_client()
    try:
        yield client
    finally:
        client.close()


def _host(endpoint: str) -> str:
    return urlsplit(endpoint).hostname or "unknown"


@router.get("/config")
def get_config(_member: CurrentMember, settings: SettingsDep) -> PushConfig:
    try:
        key = load_vapid(settings)
    except ValueError:
        key = None
    return PushConfig(enabled=key is not None, public_key=key.public_key if key else None)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(
    body: SubscriptionIn,
    member: CurrentMember,
    db: DbDep,
    request: Request,
    settings: PushSettings,
    user_agent: Annotated[str | None, Header()] = None,
) -> None:
    try:
        validate_endpoint(body.endpoint)
        validate_subscription_keys(body.keys.p256dh, body.keys.auth)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    agent = user_agent[:USER_AGENT_MAX] if user_agent else None
    with conflict_on_duplicate(db, "Subscription is being registered, try again"):
        row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
        if row is None:
            row = PushSubscription(endpoint=body.endpoint)
            db.add(row)
        # An existing endpoint moves to the caller: only the browser itself can know it.
        row.household_id = member.household.id
        row.user_id = member.user.id
        row.p256dh = body.keys.p256dh
        row.auth = body.keys.auth
        row.user_agent = agent
    audit(db, request, settings, "push_subscribe", member.user, host=_host(body.endpoint))


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    body: UnsubscribeIn, member: CurrentMember, db: DbDep, request: Request, settings: SettingsDep
) -> None:
    deleted = db.execute(
        delete(PushSubscription)
        .where(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.user_id == member.user.id,
            PushSubscription.household_id == member.household.id,
        )
        .returning(PushSubscription.id)
    ).all()
    if deleted:
        audit(db, request, settings, "push_unsubscribe", member.user, host=_host(body.endpoint))


@router.post("/test")
def send_test(
    member: CurrentMember,
    db: DbDep,
    settings: PushSettings,
    client: Annotated[httpx.Client, Depends(get_push_client)],
) -> PushTestResult:
    try:
        vapid = load_vapid(settings)
    except ValueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push is not configured") from exc
    subject = settings.resolved_vapid_subject
    if vapid is None or subject is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push is not configured")
    subscriptions = db.scalars(
        select(PushSubscription).where(
            PushSubscription.user_id == member.user.id, PushSubscription.household_id == member.household.id
        )
    ).all()
    payload = build_payload(TEST_TITLE, TEST_BODY, "/")
    messages = [Message(Target(s.id, s.endpoint, s.p256dh, s.auth), payload) for s in subscriptions]
    sent, gone, failed = deliver(client, messages, vapid, subject)
    if gone:
        db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
    if sent:
        db.execute(
            update(PushSubscription).where(PushSubscription.id.in_(sent)).values(last_success_at=utcnow())
        )
    return PushTestResult(sent=len(sent), failed=failed, removed=len(gone))
