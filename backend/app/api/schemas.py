"""Request and response models shared by the API routers."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.models import HouseholdRole
from app.security.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Password = Annotated[str, Field(max_length=MAX_PASSWORD_LENGTH)]
NewPassword = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]
TotpCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=8)]


class Me(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: HouseholdRole | None
    household_name: str | None
    has_totp: bool
    passkey_count: int


class LoginRequest(BaseModel):
    email: Email
    password: Password


class LoginResponse(BaseModel):
    status: Literal["ok", "mfa_required"]
    mfa_token: uuid.UUID | None = None
    user: Me | None = None


class TotpLoginRequest(BaseModel):
    mfa_token: uuid.UUID
    code: TotpCode


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeRequest(BaseModel):
    code: TotpCode


class TotpDisableRequest(BaseModel):
    password: Password
    code: TotpCode


class PasswordChangeRequest(BaseModel):
    current_password: Password
    new_password: NewPassword


class WebAuthnOptions(BaseModel):
    challenge_id: uuid.UUID
    options: dict[str, Any]


class PasskeyRegisterRequest(BaseModel):
    challenge_id: uuid.UUID
    name: DisplayName
    credential: dict[str, Any]


class PasskeyLoginRequest(BaseModel):
    challenge_id: uuid.UUID
    credential: dict[str, Any]


class Passkey(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class InviteInfo(BaseModel):
    email: str
    household_name: str
    expires_at: datetime


class InviteAcceptRequest(BaseModel):
    token: Annotated[str, StringConstraints(min_length=20, max_length=100)]
    display_name: DisplayName
    password: NewPassword


class Member(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: HouseholdRole
    joined_at: datetime


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    members: list[Member]


class InviteCreateRequest(BaseModel):
    email: Email
    role: HouseholdRole = HouseholdRole.MEMBER


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: HouseholdRole
    expires_at: datetime


class InviteCreated(InviteOut):
    # Shown once; only the token hash is stored.
    invite_url: str
