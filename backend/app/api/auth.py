"""Login, logout, TOTP, passkeys, password change and invite acceptance."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api import schemas
from app.config import Settings
from app.deps import CurrentUser, DbDep, SettingsDep
from app.models import (
    AuthChallenge,
    ChallengePurpose,
    HouseholdMember,
    Invite,
    User,
    WebAuthnCredential,
)
from app.models.base import utcnow
from app.security import totp
from app.security.crypto import SecretBox
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import hash_token
from app.sessions import COOKIE_NAME, audit, end_all_sessions, end_session, start_session

router = APIRouter(prefix="/auth", tags=["auth"])

CHALLENGE_TTL = timedelta(minutes=5)


def me_for(db: Session, user: User) -> schemas.Me:
    passkeys = db.scalar(
        select(func.count()).select_from(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    membership = user.membership
    return schemas.Me(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role if membership else None,
        household_name=membership.household.name if membership else None,
        has_totp=user.has_totp,
        passkey_count=passkeys or 0,
    )


def _secret_box(settings: Settings) -> SecretBox:
    return SecretBox(settings.encryption_key.get_secret_value())


def _totp_context(user: User) -> bytes:
    return b"totp:" + user.id.bytes


def _ensure_not_locked(user: User, now: datetime) -> None:
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts")


def _register_failure(
    db: Session, request: Request, settings: Settings, user: User | None, now: datetime
) -> None:
    """Count a failed attempt and lock the account after too many. Commits immediately,
    because the request ends with an error and would otherwise roll back."""
    if user is not None:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
    audit(db, request, settings, "login_failed", user)
    db.commit()


def _new_challenge(
    db: Session, purpose: ChallengePurpose, user: User | None, challenge: bytes | None = None
) -> AuthChallenge:
    record = AuthChallenge(
        id=uuid.uuid4(),
        purpose=purpose,
        user_id=user.id if user else None,
        challenge=challenge,
        expires_at=utcnow() + CHALLENGE_TTL,
    )
    db.add(record)
    return record


def _consume_challenge(
    db: Session, challenge_id: uuid.UUID, purpose: ChallengePurpose, user: User | None = None
) -> AuthChallenge:
    record = db.get(AuthChallenge, challenge_id, with_for_update=True)
    now = utcnow()
    if (
        record is None
        or record.purpose is not purpose
        or record.consumed_at is not None
        or record.expires_at <= now
        or (user is not None and record.user_id != user.id)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Challenge expired or invalid")
    record.consumed_at = now
    # Persist now: a failed verification later in the request must not make it reusable.
    db.commit()
    return record


@router.post("/login")
def login(
    body: schemas.LoginRequest, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> schemas.LoginResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    now = utcnow()
    if user is not None:
        _ensure_not_locked(user, now)
    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not password_ok or not user.is_active:
        _register_failure(db, request, settings, user, now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    if user.has_totp:
        challenge = _new_challenge(db, ChallengePurpose.MFA_LOGIN, user)
        return schemas.LoginResponse(status="mfa_required", mfa_token=challenge.id)

    start_session(db, request, response, settings, user)
    return schemas.LoginResponse(status="ok", user=me_for(db, user))


@router.post("/login/totp")
def login_totp(
    body: schemas.TotpLoginRequest, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> schemas.LoginResponse:
    now = utcnow()
    challenge = db.get(AuthChallenge, body.mfa_token)
    if (
        challenge is None
        or challenge.purpose is not ChallengePurpose.MFA_LOGIN
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
        or challenge.user_id is None
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login expired, start again")
    user = db.get(User, challenge.user_id, with_for_update=True)
    if user is None or not user.is_active or user.totp_secret_encrypted is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login expired, start again")
    _ensure_not_locked(user, now)

    secret = _secret_box(settings).decrypt(user.totp_secret_encrypted, _totp_context(user)).decode()
    step = totp.match_step(secret, body.code, user.totp_last_used_step)
    if step is None:
        _register_failure(db, request, settings, user, now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")

    challenge.consumed_at = now
    user.totp_last_used_step = step
    start_session(db, request, response, settings, user)
    return schemas.LoginResponse(status="ok", user=me_for(db, user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbDep,
    session_token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> None:
    end_session(db, session_token, response)


@router.get("/me")
def me(user: CurrentUser, db: DbDep) -> schemas.Me:
    return me_for(db, user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: schemas.PasswordChangeRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
) -> None:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    audit(db, request, settings, "password_changed", user)
    end_all_sessions(db, user)
    start_session(db, request, response, settings, user)


# --- TOTP enrollment ---------------------------------------------------------


@router.post("/totp/setup")
def totp_setup(user: CurrentUser, settings: SettingsDep) -> schemas.TotpSetupResponse:
    if user.has_totp:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP is already enabled")
    secret = totp.new_secret()
    user.totp_secret_encrypted = _secret_box(settings).encrypt(secret.encode(), _totp_context(user))
    user.totp_last_used_step = None
    return schemas.TotpSetupResponse(
        secret=secret,
        otpauth_uri=totp.provisioning_uri(secret, user.email, settings.app_name),
    )


@router.post("/totp/confirm", status_code=status.HTTP_204_NO_CONTENT)
def totp_confirm(
    body: schemas.TotpCodeRequest, request: Request, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> None:
    if user.has_totp:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP is already enabled")
    if user.totp_secret_encrypted is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start TOTP setup first")
    secret = _secret_box(settings).decrypt(user.totp_secret_encrypted, _totp_context(user)).decode()
    step = totp.match_step(secret, body.code, None)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.totp_enabled_at = utcnow()
    user.totp_last_used_step = step
    audit(db, request, settings, "totp_enabled", user)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
def totp_disable(
    body: schemas.TotpDisableRequest, request: Request, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> None:
    if not user.has_totp or user.totp_secret_encrypted is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP is not enabled")
    secret = _secret_box(settings).decrypt(user.totp_secret_encrypted, _totp_context(user)).decode()
    if not verify_password(user.password_hash, body.password) or (
        totp.match_step(secret, body.code, user.totp_last_used_step) is None
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password or code is wrong")
    user.totp_secret_encrypted = None
    user.totp_enabled_at = None
    user.totp_last_used_step = None
    audit(db, request, settings, "totp_disabled", user)


# --- Passkeys (WebAuthn) -----------------------------------------------------


def _webauthn_options(record: AuthChallenge, options_json: str) -> schemas.WebAuthnOptions:
    return schemas.WebAuthnOptions(challenge_id=record.id, options=json.loads(options_json))


@router.post("/passkeys/register/options")
def passkey_register_options(user: CurrentUser, db: DbDep, settings: SettingsDep) -> schemas.WebAuthnOptions:
    existing = db.scalars(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.app_name,
        user_id=user.id.bytes,
        user_name=user.email,
        user_display_name=user.display_name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    record = _new_challenge(db, ChallengePurpose.WEBAUTHN_REGISTER, user, options.challenge)
    return _webauthn_options(record, options_to_json(options))


@router.post("/passkeys/register/verify")
def passkey_register_verify(
    body: schemas.PasskeyRegisterRequest,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.Passkey:
    record = _consume_challenge(db, body.challenge_id, ChallengePurpose.WEBAUTHN_REGISTER, user)
    if record.challenge is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Challenge expired or invalid")
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=record.challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.public_origin,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passkey could not be verified") from exc

    transports = body.credential.get("response", {}).get("transports", [])
    credential = WebAuthnCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=[t for t in transports if isinstance(t, str)],
        name=body.name,
        created_at=utcnow(),
    )
    db.add(credential)
    audit(db, request, settings, "passkey_added", user, name=body.name)
    return schemas.Passkey.model_validate(credential, from_attributes=True)


@router.post("/passkeys/login/options")
def passkey_login_options(db: DbDep, settings: SettingsDep) -> schemas.WebAuthnOptions:
    # No allow-list: the browser offers the discoverable passkeys stored for this site.
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    record = _new_challenge(db, ChallengePurpose.WEBAUTHN_LOGIN, None, options.challenge)
    return _webauthn_options(record, options_to_json(options))


@router.post("/passkeys/login/verify")
def passkey_login_verify(
    body: schemas.PasskeyLoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.LoginResponse:
    record = _consume_challenge(db, body.challenge_id, ChallengePurpose.WEBAUTHN_LOGIN)
    raw_id = body.credential.get("rawId") or body.credential.get("id")
    if record.challenge is None or not isinstance(raw_id, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passkey could not be verified")
    try:
        credential_id = base64url_to_bytes(raw_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passkey could not be verified") from exc

    stored = db.scalar(select(WebAuthnCredential).where(WebAuthnCredential.credential_id == credential_id))
    user = db.get(User, stored.user_id) if stored else None
    if stored is None or user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown passkey")
    _ensure_not_locked(user, utcnow())
    try:
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=record.challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.public_origin,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Passkey could not be verified") from exc

    stored.sign_count = verified.new_sign_count
    stored.last_used_at = utcnow()
    start_session(db, request, response, settings, user)
    return schemas.LoginResponse(status="ok", user=me_for(db, user))


@router.get("/passkeys")
def list_passkeys(user: CurrentUser, db: DbDep) -> list[schemas.Passkey]:
    rows = db.scalars(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .order_by(WebAuthnCredential.created_at)
    )
    return [schemas.Passkey.model_validate(row, from_attributes=True) for row in rows]


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_passkey(
    passkey_id: uuid.UUID, request: Request, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> None:
    stored = db.get(WebAuthnCredential, passkey_id)
    if stored is None or stored.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey not found")
    db.delete(stored)
    audit(db, request, settings, "passkey_removed", user, name=stored.name)


# --- Invites -----------------------------------------------------------------


def _open_invite(db: Session, token: str) -> Invite:
    invite = db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)).with_for_update())
    if invite is None or invite.accepted_at is not None or invite.expires_at <= utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found or expired")
    return invite


@router.get("/invites/{token}")
def invite_info(token: str, db: DbDep) -> schemas.InviteInfo:
    invite = _open_invite(db, token)
    return schemas.InviteInfo(
        email=invite.email, household_name=invite.household.name, expires_at=invite.expires_at
    )


@router.post("/invites/accept")
def accept_invite(
    body: schemas.InviteAcceptRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.LoginResponse:
    invite = _open_invite(db, body.token)
    if db.scalar(select(User.id).where(User.email == invite.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    now = utcnow()
    user = User(
        id=uuid.uuid4(),
        email=invite.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        is_active=True,
        failed_login_count=0,
    )
    db.add(user)
    db.add(HouseholdMember(household_id=invite.household_id, user=user, role=invite.role, joined_at=now))
    invite.accepted_at = now
    db.flush()
    audit(db, request, settings, "invite_accepted", user, invite_id=str(invite.id))
    start_session(db, request, response, settings, user)
    return schemas.LoginResponse(status="ok", user=me_for(db, user))
