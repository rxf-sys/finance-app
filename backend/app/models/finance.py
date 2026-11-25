"""Accounts, transactions, categories, rules, tags and CSV imports.

Every table carries household_id so each query can filter by the caller's household
without joins. Money is integer cents (bigint).
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


def _pg_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class AccountKind(enum.StrEnum):
    GIRO = "giro"
    CREDIT_CARD = "credit_card"
    SAVINGS = "savings"
    CASH = "cash"
    OTHER = "other"


class AccountVisibility(enum.StrEnum):
    SHARED = "shared"  # every household member
    PRIVATE = "private"  # only owner_user_id


class CategoryKind(enum.StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class CategorySource(enum.StrEnum):
    RULE = "rule"
    MANUAL = "manual"


class RuleSource(enum.StrEnum):
    MANUAL = "manual"
    LEARNED = "learned"


class ImportStatus(enum.StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class Account(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("household_id", "iban"),
        UniqueConstraint("bank_connection_id", "provider_account_uid"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    visibility: Mapped[AccountVisibility] = mapped_column(_pg_enum(AccountVisibility, "account_visibility"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[AccountKind] = mapped_column(_pg_enum(AccountKind, "account_kind"))
    iban: Mapped[str | None] = mapped_column(String(34))  # normalized: upper case, no spaces
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    opening_balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    is_archived: Mapped[bool] = mapped_column(default=False)
    # Set when the account is synced through a bank connection (Phase 2).
    bank_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="SET NULL"), index=True
    )
    provider_account_uid: Mapped[str | None] = mapped_column(String(100))


class Category(UUIDPrimaryKey, CreatedAt, Base):
    """Two-level tree: top-level categories have parent_id NULL, children one level below."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("household_id", "parent_id", "name", postgresql_nulls_not_distinct=True),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[CategoryKind] = mapped_column(_pg_enum(CategoryKind, "category_kind"))
    icon: Mapped[str | None] = mapped_column(String(40))  # lucide icon name
    color: Mapped[str | None] = mapped_column(String(20))  # palette token, e.g. "chart-3"

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")


class CategoryRule(UUIDPrimaryKey, CreatedAt, Base):
    """All conditions must match (AND). Lower priority value wins; learned rules sit after manual ones."""

    __tablename__ = "category_rules"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(default=100)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[RuleSource] = mapped_column(_pg_enum(RuleSource, "rule_source"))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Tag(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("household_id", "name"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))


class TransactionTag(Base):
    __tablename__ = "transaction_tags"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class ImportProfile(UUIDPrimaryKey, CreatedAt, Base):
    """A saved CSV format. `config` is validated by app.importing (delimiter, columns, ...)."""

    __tablename__ = "import_profiles"
    __table_args__ = (UniqueConstraint("household_id", "name"),)

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ImportRun(UUIDPrimaryKey, Base):
    __tablename__ = "import_runs"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str | None] = mapped_column(String(255))
    profile_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[ImportStatus] = mapped_column(_pg_enum(ImportStatus, "import_status"))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    rows_total: Mapped[int] = mapped_column(default=0)
    rows_new: Mapped[int] = mapped_column(default=0)
    rows_duplicate: Mapped[int] = mapped_column(default=0)
    rows_skipped: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Transaction(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "dedupe_hash"),
        UniqueConstraint("transfer_peer_id"),
        Index("ix_transactions_household_id_booking_date", "household_id", "booking_date"),
        CheckConstraint("transfer_peer_id IS NULL OR transfer_peer_id <> id", name="transfer_not_self"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    booking_date: Mapped[date]
    value_date: Mapped[date | None]
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    counterparty_name: Mapped[str | None] = mapped_column(String(200))
    counterparty_iban: Mapped[str | None] = mapped_column(String(34))
    purpose: Mapped[str | None] = mapped_column(Text)
    booking_text: Mapped[str | None] = mapped_column(String(100))  # e.g. "Lastschrift", "Gutschrift"
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # original CSV row
    # SHA-256 hex over account, dates, amount, counterparty and normalized purpose plus an
    # occurrence index for identical rows in one file; random for manual entries.
    dedupe_hash: Mapped[str] = mapped_column(String(64))

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    category_source: Mapped[CategorySource | None] = mapped_column(
        _pg_enum(CategorySource, "category_source")
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("category_rules.id", ondelete="SET NULL"))
    transfer_peer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    import_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_runs.id", ondelete="SET NULL"))
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), index=True
    )

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    splits: Mapped[list["TransactionSplit"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", order_by="TransactionSplit.position"
    )
    tags: Mapped[list[Tag]] = relationship(secondary="transaction_tags", order_by="Tag.name")


class TransactionSplit(UUIDPrimaryKey, Base):
    """When a transaction has splits, reports use the splits instead of its own category."""

    __tablename__ = "transaction_splits"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(default=0)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)

    transaction: Mapped[Transaction] = relationship(back_populates="splits")
    category: Mapped[Category | None] = relationship()
