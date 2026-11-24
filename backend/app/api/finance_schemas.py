"""Request and response models for accounts, categories, rules, tags, transactions and the dashboard."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.finance.normalize import normalize_iban
from app.finance.rules import RuleConditions
from app.models import AccountKind, AccountVisibility, CategoryKind, CategorySource, RuleSource

MAX_CENTS = 10**13  # 100 billion euros: far beyond any household, well inside bigint
Cents = Annotated[int, Field(ge=-MAX_CENTS, le=MAX_CENTS)]
AccountName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
IconName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+$", max_length=40)]
ColorToken = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+$", max_length=20)]


def _optional_iban(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return normalize_iban(value)  # ValueError becomes a 422


# ---------------------------------------------------------------- accounts


class AccountCreate(BaseModel):
    name: AccountName
    kind: AccountKind
    visibility: AccountVisibility = AccountVisibility.SHARED
    iban: str | None = None
    opening_balance_cents: Cents = 0

    _iban = field_validator("iban")(_optional_iban)


class AccountUpdate(BaseModel):
    name: AccountName | None = None
    kind: AccountKind | None = None
    visibility: AccountVisibility | None = None
    iban: str | None = None  # explicit null clears it
    opening_balance_cents: Cents | None = None
    is_archived: bool | None = None

    _iban = field_validator("iban")(_optional_iban)


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: AccountKind
    visibility: AccountVisibility
    iban: str | None
    currency: str
    opening_balance_cents: int
    balance_cents: int
    is_archived: bool
    owner_user_id: uuid.UUID | None
    is_mine: bool
    transaction_count: int
    last_booking_date: date | None


class BalancePoint(BaseModel):
    month: str  # YYYY-MM
    balance_cents: int


# ---------------------------------------------------------------- categories


class CategoryCreate(BaseModel):
    name: CategoryName
    parent_id: uuid.UUID | None = None
    kind: CategoryKind | None = None  # required for top-level, ignored for children
    icon: IconName | None = None
    color: ColorToken | None = None


class CategoryUpdate(BaseModel):
    name: CategoryName | None = None
    kind: CategoryKind | None = None
    icon: IconName | None = None
    color: ColorToken | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    kind: CategoryKind
    icon: str | None
    color: str | None
    transaction_count: int


# ---------------------------------------------------------------- rules


class RuleCreate(BaseModel):
    category_id: uuid.UUID
    conditions: RuleConditions
    priority: int = Field(default=100, ge=0, le=10_000)
    is_active: bool = True


class RuleUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    conditions: RuleConditions | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None


class RuleOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    conditions: dict[str, Any]
    priority: int
    source: RuleSource
    is_active: bool
    created_by_id: uuid.UUID | None
    created_at: datetime


class RulesApplied(BaseModel):
    updated: int


# ---------------------------------------------------------------- tags


class TagWrite(BaseModel):
    name: TagName


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


# ---------------------------------------------------------------- transactions


class SplitIn(BaseModel):
    amount_cents: Cents
    category_id: uuid.UUID | None = None
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None


class SplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    amount_cents: int
    category_id: uuid.UUID | None
    note: str | None


class TransactionCreate(BaseModel):
    account_id: uuid.UUID
    booking_date: date
    value_date: date | None = None
    amount_cents: Cents
    counterparty_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    counterparty_iban: str | None = None
    purpose: Annotated[str, StringConstraints(max_length=2000)] | None = None
    booking_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None
    category_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    _iban = field_validator("counterparty_iban")(_optional_iban)

    @field_validator("amount_cents")
    @classmethod
    def _non_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Amount must not be zero")
        return value


class TransactionUpdate(BaseModel):
    category_id: uuid.UUID | None = None  # explicit null clears the category
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    learn: bool = True
    apply_to_similar: bool = False


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    booking_date: date
    value_date: date | None
    amount_cents: int
    currency: str
    counterparty_name: str | None
    counterparty_iban: str | None
    purpose: str | None
    booking_text: str | None
    category_id: uuid.UUID | None
    category_source: CategorySource | None
    rule_id: uuid.UUID | None
    transfer_peer_id: uuid.UUID | None  # only set when the peer is visible to the caller
    is_transfer: bool
    note: str | None
    import_run_id: uuid.UUID | None
    created_at: datetime
    splits: list[SplitOut]
    tags: list[TagOut]


class TransactionDetail(TransactionOut):
    raw: dict[str, Any] | None


class TransactionUpdated(TransactionDetail):
    similar_updated: int


class TransactionList(BaseModel):
    items: list[TransactionOut]
    total: int


class TransferRequest(BaseModel):
    peer_id: uuid.UUID


# ---------------------------------------------------------------- dashboard


class DashboardAccount(BaseModel):
    id: uuid.UUID
    name: str
    kind: AccountKind
    visibility: AccountVisibility
    balance_cents: int
    is_mine: bool


class TopCategory(BaseModel):
    category_id: uuid.UUID | None
    name: str | None
    icon: str | None
    color: str | None
    amount_cents: int


class TrendPoint(BaseModel):
    month: str
    income_cents: int
    expense_cents: int


class DashboardOut(BaseModel):
    month: str
    accounts: list[DashboardAccount]
    net_worth_cents: int
    income_cents: int
    expense_cents: int
    net_cents: int
    top_categories: list[TopCategory]
    trend: list[TrendPoint]
    uncategorized_count: int
