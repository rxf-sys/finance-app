"""Sessions, passkeys and short-lived authentication challenges."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey
from app.models.identity import User


class UserSession(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()


class WebAuthnCredential(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    transports: Mapped[list[str]] = mapped_column(JSONB, default=list)
    name: Mapped[str] = mapped_column(String(100))
    last_used_at: Mapped[datetime | None]


class ChallengePurpose(enum.StrEnum):
    MFA_LOGIN = "mfa_login"
    WEBAUTHN_REGISTER = "webauthn_register"
    WEBAUTHN_LOGIN = "webauthn_login"


class AuthChallenge(UUIDPrimaryKey, CreatedAt, Base):
    """Single-use challenge. Its random UUID is handed to the client as reference."""

    __tablename__ = "auth_challenges"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[ChallengePurpose] = mapped_column(
        Enum(
            ChallengePurpose,
            name="challenge_purpose",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    challenge: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]
