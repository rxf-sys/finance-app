"""Bank connections through Enable Banking: consent, account linking and sync control.

A connection belongs to the user who gave the consent. Other household members get 404.
Errors that reach the client are static; provider bodies are never forwarded.
"""

import html
import logging
import secrets
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import banking_schemas as schemas
from app.api.common import conflict_on_duplicate
from app.banking.client import BankAuthExpired, BankError, BankRateLimited, EnableBankingClient
from app.banking.mapping import account_iban
from app.banking.queue import enqueue_sync
from app.banking.sync import SESSION_CONTEXT, SYNC_START_MARKER, decrypt_session_id, marker_started_at
from app.config import Settings
from app.deps import CurrentMember, DbDep, MemberContext, SettingsDep
from app.finance.access import get_visible_account
from app.models import (
    Account,
    AuditLog,
    BankConnection,
    BankConnectionStatus,
    BankProvider,
    SyncRun,
    SyncStatus,
    Transaction,
)
from app.models.base import utcnow
from app.security.crypto import SecretBox
from app.security.tokens import hash_token
from app.sessions import COOKIE_NAME, audit, load_session

log = logging.getLogger(__name__)

MANUAL_SYNC_INTERVAL = timedelta(minutes=15)
PENDING_TTL = timedelta(hours=1)
ASPSP_CACHE_TTL = 3600.0
DEFAULT_CONSENT = timedelta(days=180)
DEFAULT_HISTORY_DAYS = 90
CALLBACK_PATH = "/api/bank-connections/callback"


def require_bank_sync(settings: SettingsDep) -> None:
    if not settings.bank_sync_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Bank sync is not configured")


def get_bank_client(settings: SettingsDep) -> Iterator[EnableBankingClient]:
    client = EnableBankingClient.from_settings(settings)
    try:
        yield client
    finally:
        client.close()


ClientDep = Annotated[EnableBankingClient, Depends(get_bank_client)]

router = APIRouter(prefix="/bank-connections", tags=["bank"], dependencies=[Depends(require_bank_sync)])

_aspsp_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_aspsp_cache() -> None:
    _aspsp_cache.clear()


def _provider_error(exc: BankError) -> HTTPException:
    if isinstance(exc, BankRateLimited):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Bank provider rate limit reached")
    if isinstance(exc, BankAuthExpired):
        return HTTPException(status.HTTP_409_CONFLICT, "Bank consent is no longer valid")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "Bank provider request failed")


def _aspsps(client: EnableBankingClient, country: str) -> list[dict[str, Any]]:
    cached = _aspsp_cache.get(country)
    if cached is not None and time.monotonic() - cached[0] < ASPSP_CACHE_TTL:
        return cached[1]
    try:
        items = client.list_aspsps(country)
    except BankError as exc:
        raise _provider_error(exc) from None
    _aspsp_cache[country] = (time.monotonic(), items)
    return items


def _consent_until(aspsp: dict[str, Any], now: datetime) -> datetime:
    """Maximum consent of the bank (seconds, unverified unit) or 180 days; a minute short of the limit."""
    value = aspsp.get("maximum_consent_validity")
    span = DEFAULT_CONSENT
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        span = timedelta(seconds=value)
    return (now + span - timedelta(minutes=1)).replace(microsecond=0)


def _get_connection(db: Session, member: MemberContext, connection_id: uuid.UUID) -> BankConnection:
    connection = db.scalar(
        select(BankConnection).where(
            BankConnection.id == connection_id,
            BankConnection.household_id == member.household.id,
            BankConnection.owner_user_id == member.user.id,
        )
    )
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank connection not found")
    return connection


def _active(connection: BankConnection) -> None:
    if connection.status is not BankConnectionStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank connection is not active")


def _mask(iban: str | None) -> str | None:
    return None if iban is None else "*" * max(len(iban) - 4, 0) + iban[-4:]


def _session_accounts(
    client: EnableBankingClient, settings: Settings, connection: BankConnection
) -> list[dict[str, Any]]:
    try:
        session_id = decrypt_session_id(settings, connection)
        if session_id is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Bank connection is not active")
        session = client.get_session(session_id)
    except BankError as exc:
        raise _provider_error(exc) from None
    accounts = session.get("accounts")
    return (
        [a for a in accounts if isinstance(a, dict) and isinstance(a.get("uid"), str)]
        if isinstance(accounts, list)
        else []
    )


def _redirect(target: str) -> RedirectResponse:
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _fail(code: str) -> RedirectResponse:
    return _redirect(f"/bank?{urlencode({'error': code})}")


@router.get("/aspsps")
def list_aspsps(
    client: ClientDep, country: Annotated[str, Query(pattern=r"^[A-Z]{2}$")] = "DE"
) -> list[schemas.AspspOut]:
    return [
        schemas.AspspOut(
            name=name,
            country=str(a.get("country") or country),
            logo=a["logo"] if isinstance(a.get("logo"), str) else None,
        )
        for a in _aspsps(client, country)
        if isinstance(name := a.get("name"), str)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def start_connection(
    body: schemas.ConnectionCreate,
    request: Request,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
    client: ClientDep,
) -> schemas.ConnectionStarted:
    aspsp = next((a for a in _aspsps(client, body.country) if a.get("name") == body.aspsp_name), None)
    if aspsp is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown bank")
    state = secrets.token_urlsafe(32)
    connection = BankConnection(
        id=uuid.uuid4(),
        household_id=member.household.id,
        owner_user_id=member.user.id,
        provider=BankProvider.ENABLE_BANKING,
        aspsp_name=body.aspsp_name,
        aspsp_country=body.country,
        status=BankConnectionStatus.PENDING,
        auth_state_hash=hash_token(state),
    )
    db.add(connection)
    db.flush()
    try:
        url = client.start_auth(
            body.aspsp_name,
            body.country,
            f"{settings.public_origin.rstrip('/')}{CALLBACK_PATH}",
            state,
            _consent_until(aspsp, utcnow()),
        )
    except BankError as exc:
        raise _provider_error(exc) from None
    audit(db, request, settings, "bank_connect_started", member.user, connection_id=str(connection.id))
    return schemas.ConnectionStarted(connection_id=connection.id, redirect_url_to_bank=url)


def _optional_member(db: Session, settings: Settings, token: str | None) -> MemberContext | None:
    if not token:
        return None
    session = load_session(db, token, settings)
    if session is None:
        return None
    user = session.user
    membership = user.membership
    if membership is None:
        return None
    return MemberContext(user, membership.household, membership.role)


def _parse_valid_until(session: dict[str, Any]) -> datetime | None:
    access = session.get("access")
    value = access.get("valid_until") if isinstance(access, dict) else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@router.get("/callback")
def callback(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    client: ClientDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    retry: str | None = None,
    session_token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> Response:
    member = _optional_member(db, settings, session_token)
    if member is None:
        if retry is None:
            # The session cookie is SameSite=Strict, so it is not sent on the cross-site navigation
            # back from the bank. A navigation started by this page is same-site and carries it.
            params = {"retry": "1"}
            for key, value in (("code", code), ("state", state), ("error", error)):
                if value is not None:
                    params[key] = value
            target = html.escape(f"{CALLBACK_PATH}?{urlencode(params)}", quote=True)
            return HTMLResponse(
                f'<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
                f'<meta http-equiv="refresh" content="0;url={target}"><title>Weiterleitung</title>',
                headers={"Cache-Control": "no-store"},
            )
        return _fail("login")
    connection = None
    if state:
        connection = db.scalar(
            select(BankConnection).where(
                BankConnection.auth_state_hash == hash_token(state),
                BankConnection.household_id == member.household.id,
                BankConnection.owner_user_id == member.user.id,
                BankConnection.status == BankConnectionStatus.PENDING,
                BankConnection.created_at > utcnow() - PENDING_TTL,
            )
        )
    if connection is None:
        return _fail("invalid_state")
    connection.auth_state_hash = None  # single use, whatever happens next
    if error or not code:
        connection.status = BankConnectionStatus.ERROR
        connection.last_error = "Authorisation was not completed"
        audit(db, request, settings, "bank_connect_failed", member.user, connection_id=str(connection.id))
        return _fail("denied")
    try:
        session = client.create_session(code)
    except BankError as exc:
        connection.status = BankConnectionStatus.ERROR
        connection.last_error = "Creating the bank session failed"
        audit(db, request, settings, "bank_connect_failed", member.user, connection_id=str(connection.id))
        return _fail("rate_limited" if isinstance(exc, BankRateLimited) else "bank_error")
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        connection.status = BankConnectionStatus.ERROR
        connection.last_error = "Creating the bank session failed"
        audit(db, request, settings, "bank_connect_failed", member.user, connection_id=str(connection.id))
        return _fail("bank_error")
    box = SecretBox(settings.encryption_key.get_secret_value())
    connection.session_encrypted = box.encrypt(session_id.encode(), SESSION_CONTEXT)
    connection.consent_valid_until = _parse_valid_until(session)
    connection.status = BankConnectionStatus.ACTIVE
    connection.last_error = None
    audit(db, request, settings, "bank_connected", member.user, connection_id=str(connection.id))
    return _redirect(f"/bank?{urlencode({'connection': str(connection.id)})}")


@router.get("")
def list_connections(member: CurrentMember, db: DbDep) -> list[schemas.ConnectionOut]:
    connections = db.scalars(
        select(BankConnection)
        .where(
            BankConnection.household_id == member.household.id,
            BankConnection.owner_user_id == member.user.id,
            BankConnection.status != BankConnectionStatus.PENDING,
        )
        .order_by(BankConnection.created_at)
    ).all()
    accounts = db.scalars(
        select(Account)
        .where(Account.bank_connection_id.in_([c.id for c in connections]))
        .order_by(Account.name)
    ).all()
    return [
        schemas.ConnectionOut(
            id=c.id,
            aspsp_name=c.aspsp_name,
            country=c.aspsp_country,
            status=c.status,
            consent_valid_until=c.consent_valid_until,
            last_sync_at=c.last_sync_at,
            last_error=c.last_error,
            accounts=[
                schemas.LinkedAccountOut(
                    account_id=a.id, name=a.name, provider_account_uid=a.provider_account_uid
                )
                for a in accounts
                if a.bank_connection_id == c.id
            ],
        )
        for c in connections
    ]


@router.get("/{connection_id}/accounts")
def provider_accounts(
    connection_id: uuid.UUID,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
    client: ClientDep,
) -> list[schemas.ProviderAccountOut]:
    connection = _get_connection(db, member, connection_id)
    _active(connection)
    linked = {
        a.provider_account_uid: a.id
        for a in db.scalars(select(Account).where(Account.bank_connection_id == connection.id))
    }
    out: list[schemas.ProviderAccountOut] = []
    for acc in _session_accounts(client, settings, connection):
        uid = str(acc["uid"])
        name = acc.get("name") or acc.get("product") or acc.get("details")
        currency = acc.get("currency")
        out.append(
            schemas.ProviderAccountOut(
                uid=uid,
                iban_masked=_mask(account_iban(acc)),
                name=name if isinstance(name, str) else None,
                currency=currency if isinstance(currency, str) else None,
                linked_account_id=linked.get(uid),
            )
        )
    return out


@router.post("/{connection_id}/link")
def link_account(
    connection_id: uuid.UUID,
    body: schemas.LinkRequest,
    request: Request,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
    client: ClientDep,
) -> schemas.LinkOut:
    connection = _get_connection(db, member, connection_id)
    _active(connection)
    today = utcnow().date()
    if body.sync_from is not None and body.sync_from > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "sync_from must not be in the future")
    provider = next(
        (a for a in _session_accounts(client, settings, connection) if a["uid"] == body.provider_account_uid),
        None,
    )
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider account not found")
    if db.scalar(
        select(Account.id).where(
            Account.bank_connection_id == connection.id,
            Account.provider_account_uid == body.provider_account_uid,
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider account is already linked")
    iban = account_iban(provider)
    currency = provider.get("currency") if isinstance(provider.get("currency"), str) else None
    last_booking: date | None = None
    if body.account_id is not None:
        account = get_visible_account(db, member, body.account_id)
        if account.bank_connection_id is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Account is already linked to a bank")
        if account.iban and iban and account.iban != iban:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "IBAN does not match the account")
        if currency and currency.upper() != account.currency.upper():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Currency does not match the account")
        last_booking = db.scalar(
            select(func.max(Transaction.booking_date)).where(Transaction.account_id == account.id)
        )
        with conflict_on_duplicate(db, "An account with this IBAN already exists"):
            account.bank_connection_id = connection.id
            account.provider_account_uid = body.provider_account_uid
            if account.iban is None:
                account.iban = iban
    else:
        assert body.new_account is not None  # noqa: S101 - guaranteed by the request model
        account = Account(
            id=uuid.uuid4(),
            household_id=member.household.id,
            owner_user_id=member.user.id,
            visibility=body.new_account.visibility,
            name=body.new_account.name,
            kind=body.new_account.kind,
            iban=iban,
            currency=currency.upper() if currency else "EUR",
            opening_balance_cents=0,
            is_archived=False,
            bank_connection_id=connection.id,
            provider_account_uid=body.provider_account_uid,
        )
        with conflict_on_duplicate(db, "An account with this IBAN already exists"):
            db.add(account)
    sync_from = body.sync_from or (
        last_booking + timedelta(days=1) if last_booking else today - timedelta(days=DEFAULT_HISTORY_DAYS)
    )
    now = utcnow()
    # The start date is kept as a marker run (see app.banking.sync) so no model change is needed.
    db.add(
        SyncRun(
            id=uuid.uuid4(),
            household_id=connection.household_id,
            bank_connection_id=connection.id,
            account_id=account.id,
            status=SyncStatus.COMPLETED,
            started_at=marker_started_at(sync_from),
            finished_at=now,
            error=SYNC_START_MARKER,
        )
    )
    connection.last_sync_at = None  # due at the next hourly run
    audit(
        db, request, settings, "bank_account_linked", member.user,
        connection_id=str(connection.id), account_id=str(account.id),
    )  # fmt: skip
    return schemas.LinkOut(account_id=account.id, sync_from=sync_from)


@router.post("/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def request_sync(
    connection_id: uuid.UUID,
    request: Request,
    response: Response,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.SyncQueued:
    connection = db.scalar(
        select(BankConnection)
        .where(
            BankConnection.id == connection_id,
            BankConnection.household_id == member.household.id,
            BankConnection.owner_user_id == member.user.id,
        )
        .with_for_update()
    )
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank connection not found")
    _active(connection)
    recent = db.scalar(
        select(func.max(AuditLog.at)).where(
            AuditLog.action == "bank_sync_requested",
            AuditLog.details["connection_id"].as_string() == str(connection.id),
            AuditLog.at > utcnow() - MANUAL_SYNC_INTERVAL,
        )
    )
    if recent is not None:
        wait = max(int((recent + MANUAL_SYNC_INTERVAL - utcnow()).total_seconds()), 1)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "A sync was requested recently",
            headers={"Retry-After": str(wait)},
        )
    audit(db, request, settings, "bank_sync_requested", member.user, connection_id=str(connection.id))
    db.flush()
    try:
        enqueue_sync(str(connection.id))
    except Exception as exc:
        log.error("enqueueing a bank sync failed: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not queue the sync") from None
    return schemas.SyncQueued()


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    connection_id: uuid.UUID,
    request: Request,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
    client: ClientDep,
) -> None:
    connection = _get_connection(db, member, connection_id)
    try:
        session_id = decrypt_session_id(settings, connection)
        if session_id is not None:
            client.delete_session(session_id)
    except Exception:  # best effort: the bank-side consent can also be revoked at the bank
        log.warning("deleting the provider session failed; continuing")
    for account in db.scalars(select(Account).where(Account.bank_connection_id == connection.id)):
        account.bank_connection_id = None
        account.provider_account_uid = None
    db.flush()
    audit(db, request, settings, "bank_disconnected", member.user, connection_id=str(connection.id))
    db.delete(connection)


@router.get("/{connection_id}/sync-runs")
def list_sync_runs(connection_id: uuid.UUID, member: CurrentMember, db: DbDep) -> list[schemas.SyncRunOut]:
    connection = _get_connection(db, member, connection_id)
    runs = db.scalars(
        select(SyncRun)
        .where(
            SyncRun.bank_connection_id == connection.id,
            or_(SyncRun.error.is_(None), SyncRun.error != SYNC_START_MARKER),
        )
        .order_by(SyncRun.started_at.desc())
        .limit(20)
    ).all()
    return [
        schemas.SyncRunOut(
            id=r.id,
            account_id=r.account_id,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            rows_new=r.rows_new,
            rows_duplicate=r.rows_duplicate,
            error=r.error,
        )
        for r in runs
    ]
