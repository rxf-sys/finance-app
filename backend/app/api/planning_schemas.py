"""Request and response models for contracts, budgets, 'frei verfügbar' and notifications."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.api.finance_schemas import Cents
from app.models import ContractInterval, ContractKind, ContractStatus, NotificationKind

ContractName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]

# ---------------------------------------------------------------- contracts


class ContractCreate(BaseModel):
    name: ContractName
    kind: ContractKind = ContractKind.OTHER
    interval: ContractInterval
    expected_amount_cents: Cents = Field(description="Signed: negative is a payment")
    amount_tolerance_pct: int = Field(default=10, ge=0, le=100)
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    # Optional counterparty so that later payments are matched to this contract.
    counterparty_name: ShortText | None = None
    counterparty_iban: str | None = None
    start_date: date | None = None
    min_term_end: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    next_due_date: date | None = None
    customer_number: ShortText | None = None
    note: LongText | None = None


class ContractUpdate(BaseModel):
    name: ContractName | None = None
    kind: ContractKind | None = None
    interval: ContractInterval | None = None
    expected_amount_cents: Cents | None = None
    amount_tolerance_pct: int | None = Field(default=None, ge=0, le=100)
    start_date: date | None = None
    min_term_end: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    customer_number: ShortText | None = None
    note: LongText | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None  # explicit null makes the contract household-wide


class PriceChangeOut(BaseModel):
    id: uuid.UUID
    old_amount_cents: int
    new_amount_cents: int
    effective_date: date
    transaction_id: uuid.UUID | None
    acknowledged_at: datetime | None


class ContractOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: ContractKind
    status: ContractStatus
    interval: ContractInterval
    account_id: uuid.UUID | None
    category_id: uuid.UUID | None
    expected_amount_cents: int
    amount_tolerance_pct: int
    monthly_amount_cents: int
    last_payment_date: date | None
    next_due_date: date | None
    start_date: date | None
    min_term_end: date | None
    notice_period_days: int | None
    cancellation_deadline: date | None
    customer_number: str | None
    note: str | None
    is_manual: bool
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    payments_count: int
    unacknowledged_price_change: PriceChangeOut | None


class ContractTransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    booking_date: date
    amount_cents: int
    counterparty_name: str | None
    purpose: str | None


class ContractDetail(ContractOut):
    price_changes: list[PriceChangeOut]
    transactions: list[ContractTransactionOut]


class KindSummary(BaseModel):
    kind: ContractKind
    count: int
    monthly_cost_cents: int


class ContractSummary(BaseModel):
    monthly_cost_cents: int
    monthly_income_cents: int
    by_kind: list[KindSummary]
    detected_count: int


class CancellationLetter(BaseModel):
    subject: str
    body: str
    recipient_name: str


# ---------------------------------------------------------------- budgets


class BudgetCreate(BaseModel):
    category_id: uuid.UUID
    amount_cents: int = Field(gt=0, le=10**13)
    rollover: bool = False


class BudgetUpdate(BaseModel):
    amount_cents: int | None = Field(default=None, gt=0, le=10**13)
    rollover: bool | None = None


class BudgetOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    amount_cents: int
    rollover: bool


class BudgetStatusOut(BudgetOut):
    month: str
    spent_cents: int
    limit_cents: int
    remaining_cents: int
    pct: int
    state: str


# ---------------------------------------------------------------- available


class AvailableItem(BaseModel):
    contract_id: uuid.UUID
    name: str
    due_date: date
    amount_cents: int


class AvailableOut(BaseModel):
    balance_cents: int
    upcoming_out_cents: int
    upcoming_in_cents: int
    available_cents: int
    items: list[AvailableItem]


# ---------------------------------------------------------------- notifications


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: NotificationKind
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    count: int


class ReadAllResult(BaseModel):
    updated: int


# ---------------------------------------------------------------- forecast


class ForecastDay(BaseModel):
    date: date
    balance_cents: int


class ForecastMonth(BaseModel):
    month: str
    income_cents: int
    contracts_cents: int = Field(description="Signed sum of contract payments in the month")
    variable_cents: int = Field(description="Expected variable spending, negative")
    end_balance_cents: int


class ForecastEventOut(BaseModel):
    date: date
    kind: Literal["contract", "income"]
    name: str
    amount_cents: int
    contract_id: uuid.UUID | None


class ForecastAssumptions(BaseModel):
    income_baseline_cents: int
    income_day: int | None
    variable_baseline_cents: int
    months_used: int


class ForecastOut(BaseModel):
    """Projected end-of-day balances of the spendable accounts; months cover only days after today."""

    start_balance_cents: int
    as_of: date
    horizon_end: date
    daily: list[ForecastDay]
    months: list[ForecastMonth]
    lowest: ForecastDay
    events: list[ForecastEventOut]
    assumptions: ForecastAssumptions
    insufficient_history: bool
