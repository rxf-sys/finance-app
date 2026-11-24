"""Households, users, memberships and invites."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


class HouseholdRole(enum.StrEnum):
    OWNER = "owner"
    MEMBER = "member"


household_role_enum = Enum(
    HouseholdRole, name="household_role", values_callable=lambda e: [m.value for m in e]
)


class Household(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "households"

    name: Mapped[str] = mapped_column(String(100))

    members: Mapped[list["HouseholdMember"]] = relationship(back_populates="household")


class User(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)

    # TOTP secret, AES-GCM encrypted. Set but not enabled while enrollment is pending.
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled_at: Mapped[datetime | None]
    totp_last_used_step: Mapped[int | None]

    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]

    membership: Mapped["HouseholdMember | None"] = relationship(back_populates="user")

    @property
    def has_totp(self) -> bool:
        return self.totp_enabled_at is not None


class HouseholdMember(Base):
    __tablename__ = "household_members"
    # One household per user for now; the composite key keeps the door open.
    __table_args__ = (UniqueConstraint("user_id"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[HouseholdRole] = mapped_column(household_role_enum)
    joined_at: Mapped[datetime]

    household: Mapped[Household] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="membership")


class Invite(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "invites"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[HouseholdRole] = mapped_column(household_role_enum)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]

    household: Mapped[Household] = relationship()
