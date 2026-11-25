"""Contracts, budgets, bank connections and in-app notifications (Phase 2)."""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey
from app.models.finance import Account, Category


def _pg_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class ContractKind(enum.StrEnum):
    SUBSCRIPTION = "subscription"
    INSURANCE = "insurance"
    UTILITIES = "utilities"
    TELECOM = "telecom"
    RENT = "rent"
    LOAN = "loan"
    OTHER = "other"


class ContractInterval(enum.StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"


class ContractStatus(enum.StrEnum):
    DETECTED = "detected"  # suggestion; never counted until the user confirms it
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    IGNORED = "ignored"  # rejected suggestion; detection must not propose it again


class BankProvider(enum.StrEnum):
    ENABLE_BANKING = "enable_banking"


class BankConnectionStatus(enum.StrEnum):
    PENDING = "pending"  # waiting for the bank redirect
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class SyncStatus(enum.StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class NotificationKind(enum.StrEnum):
    CONTRACT_NOTICE = "contract_notice"  # cancellation deadline coming up
    PRICE_CHANGE = "price_change"
    BUDGET_WARNING = "budget_warning"
    CONSENT_EXPIRY = "consent_expiry"
    SYNC_FAILED = "sync_failed"


class Contract(UUIDPrimaryKey, CreatedAt, Base):
    """A recurring payment. Visible like its account; without an account it is household-wide."""

    __tablename__ = "contracts"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[ContractKind] = mapped_column(_pg_enum(ContractKind, "contract_kind"))
    status: Mapped[ContractStatus] = mapped_column(_pg_enum(ContractStatus, "contract_status"), index=True)
    # Normalized counterparty name or IBAN that links payments to this contract.
    counterparty_key: Mapped[str] = mapped_column(String(200))
    counterparty_iban: Mapped[str | None] = mapped_column(String(34))
    interval: Mapped[ContractInterval] = mapped_column(_pg_enum(ContractInterval, "contract_interval"))
    expected_amount_cents: Mapped[int] = mapped_column(BigInteger)  # signed, like transactions
    amount_tolerance_pct: Mapped[int] = mapped_column(default=10)
    last_payment_date: Mapped[date | None]
    next_due_date: Mapped[date | None]
    start_date: Mapped[date | None]
    min_term_end: Mapped[date | None]  # end of the minimum term
    notice_period_days: Mapped[int | None]
    customer_number: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]

    account: Mapped[Account | None] = relationship()
    category: Mapped[Category | None] = relationship()
    price_changes: Mapped[list["ContractPriceChange"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ContractPriceChange.effective_date"
    )


class ContractPriceChange(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "contract_price_changes"

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    old_amount_cents: Mapped[int] = mapped_column(BigInteger)
    new_amount_cents: Mapped[int] = mapped_column(BigInteger)
    effective_date: Mapped[date]
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None]

    contract: Mapped[Contract] = relationship(back_populates="price_changes")


class Budget(UUIDPrimaryKey, CreatedAt, Base):
    """Monthly spending limit for a category (a top-level budget includes its children)."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("household_id", "category_id"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # positive monthly limit
    rollover: Mapped[bool] = mapped_column(default=False)

    category: Mapped[Category] = relationship()


class BankConnection(UUIDPrimaryKey, CreatedAt, Base):
    """Consent at one bank through a provider. Accounts link to it via Account.bank_connection_id."""

    __tablename__ = "bank_connections"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    provider: Mapped[BankProvider] = mapped_column(_pg_enum(BankProvider, "bank_provider"))
    aspsp_name: Mapped[str] = mapped_column(String(100))
    aspsp_country: Mapped[str] = mapped_column(String(2))
    status: Mapped[BankConnectionStatus] = mapped_column(
        _pg_enum(BankConnectionStatus, "bank_connection_status")
    )
    # Random value sent as OAuth `state`; stored hashed, cleared after the callback.
    auth_state_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Provider session id, AES-GCM encrypted with the app key (context "bank_session").
    session_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    consent_valid_until: Mapped[datetime | None]
    last_sync_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)


class SyncRun(UUIDPrimaryKey, Base):
    __tablename__ = "sync_runs"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    bank_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    status: Mapped[SyncStatus] = mapped_column(_pg_enum(SyncStatus, "sync_status"))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    rows_new: Mapped[int] = mapped_column(default=0)
    rows_duplicate: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Notification(UUIDPrimaryKey, CreatedAt, Base):
    """In-app notice for one user. `dedupe_key` stops the same notice from being created twice."""

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[NotificationKind] = mapped_column(_pg_enum(NotificationKind, "notification_kind"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200))  # in-app path, e.g. "/contracts/<id>"
    dedupe_key: Mapped[str] = mapped_column(String(200))
    read_at: Mapped[datetime | None]
