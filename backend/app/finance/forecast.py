"""Balance forecast: today's balance plus contract payments, expected income and variable spending.

`compute_forecast` is pure (no database); `load_forecast` gathers its inputs for one member.
Assumptions, all deliberately simple:

- Only the spendable accounts count (see `available.spendable_stats`); future-dated bookings
  are ignored for the start balance.
- Contract events follow the schedule of confirmed contracts. A contract that is due today or
  earlier and has not been matched yet is expected tomorrow, then follows its schedule.
- Income and variable spending are baselines: the median over the last three complete calendar
  months of lines that are neither transfers nor linked to a contract. A month only counts when
  the account data covers it from its first day.
- Income is one event on the median day of the month of each month's largest credit.
"""

import calendar
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.deps import MemberContext
from app.finance import reporting
from app.finance.access import visible_contract_clause, visible_transaction_clause
from app.finance.available import spendable_stats
from app.finance.contracts import add_interval, add_months_clamped
from app.models import Category, Contract, ContractInterval, ContractStatus, Transaction

HISTORY_MONTHS = 3
INCOME_RECEIVED_SHARE_PCT = 50
MAX_CONTRACT_STEPS = 400  # a weekly contract over three months needs ~14; guards against bad data


@dataclass(frozen=True)
class ContractSpec:
    id: uuid.UUID
    name: str
    interval: ContractInterval
    amount_cents: int  # signed
    next_due_date: date | None


@dataclass(frozen=True)
class HistoryLine:
    """A counted line: not a transfer, not linked to a contract."""

    booking_date: date
    amount_cents: int


@dataclass(frozen=True)
class ForecastEvent:
    date: date
    kind: str  # "contract" | "income"
    name: str
    amount_cents: int
    contract_id: uuid.UUID | None


@dataclass(frozen=True)
class DailyBalance:
    date: date
    balance_cents: int


@dataclass(frozen=True)
class MonthForecast:
    month: str
    income_cents: int
    contracts_cents: int  # signed sum of contract events
    variable_cents: int  # negative
    end_balance_cents: int


@dataclass(frozen=True)
class Assumptions:
    income_baseline_cents: int
    income_day: int | None
    variable_baseline_cents: int
    months_used: int


@dataclass(frozen=True)
class Forecast:
    start_balance_cents: int
    as_of: date
    horizon_end: date
    daily: list[DailyBalance]
    months: list[MonthForecast]
    lowest: DailyBalance
    events: list[ForecastEvent]
    assumptions: Assumptions
    insufficient_history: bool


def median_int(values: Sequence[int]) -> int:
    """Median, rounded down for an even count; 0 for no values."""
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def month_length(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def _contract_events(contract: ContractSpec, today: date, horizon_end: date) -> list[ForecastEvent]:
    due = contract.next_due_date
    if due is None:
        return []
    events: list[ForecastEvent] = []

    def add(day: date) -> None:
        events.append(ForecastEvent(day, "contract", contract.name, contract.amount_cents, contract.id))

    steps = 0
    if due <= today:
        add(today + timedelta(days=1))  # payment not seen yet: expect it tomorrow
        while due <= today and steps < MAX_CONTRACT_STEPS:
            due = add_interval(due, contract.interval)
            steps += 1
    while due <= horizon_end and steps < MAX_CONTRACT_STEPS:
        add(due)
        due = add_interval(due, contract.interval)
        steps += 1
    return [e for e in events if today < e.date <= horizon_end]


def _in_month(lines: Sequence[HistoryLine], first: date) -> list[HistoryLine]:
    return [ln for ln in lines if (ln.booking_date.year, ln.booking_date.month) == (first.year, first.month)]


def _baselines(lines: Sequence[HistoryLine], months: Sequence[date]) -> tuple[int, int | None, int]:
    """(income baseline, median day of the largest credit, variable spending baseline)."""
    income_totals: list[int] = []
    spend_totals: list[int] = []
    largest_days: list[int] = []
    for first in months:
        in_month = _in_month(lines, first)
        credits = [ln for ln in in_month if ln.amount_cents > 0]
        income_totals.append(sum(ln.amount_cents for ln in credits))
        spend_totals.append(-sum(ln.amount_cents for ln in in_month if ln.amount_cents < 0))
        if credits:
            best = max(credits, key=lambda ln: (ln.amount_cents, -ln.booking_date.toordinal()))
            largest_days.append(best.booking_date.day)
    day = median_int(largest_days) if largest_days else None
    return median_int(income_totals), day, median_int(spend_totals)


def _baseline_flows(
    today: date,
    horizon_end: date,
    lines: Sequence[HistoryLine],
    income_baseline: int,
    income_day: int | None,
    variable_baseline: int,
) -> tuple[list[ForecastEvent], dict[date, int]]:
    """Expected income events and per-day variable spending (negative) up to the horizon."""
    this_month = today.replace(day=1)
    so_far = _in_month(lines, this_month)
    received = sum(ln.amount_cents for ln in so_far if ln.amount_cents > 0)
    spent = -sum(ln.amount_cents for ln in so_far if ln.amount_cents < 0)
    income: list[ForecastEvent] = []
    variable: dict[date, int] = defaultdict(int)
    month = this_month
    while month <= horizon_end:
        length = month_length(month)
        if income_baseline > 0 and income_day is not None:
            when = month.replace(day=min(income_day, length))
            include = today < when <= horizon_end
            if include and month == this_month:
                include = received * 100 < income_baseline * INCOME_RECEIVED_SHARE_PCT
            if include:
                income.append(ForecastEvent(when, "income", "Income", income_baseline, None))
        if variable_baseline > 0:
            if month == this_month:
                total = max(0, variable_baseline - spent)
                span_start, span_len = today + timedelta(days=1), length - today.day
            else:
                total, span_start, span_len = variable_baseline, month, length
            for i in range(min(span_len, (horizon_end - span_start).days + 1)):
                # Integer spread: the shares of a whole span add up to `total` exactly.
                share = total * (i + 1) // span_len - total * i // span_len
                variable[span_start + timedelta(days=i)] -= share
        month = reporting.add_months(month, 1)
    return income, variable


def compute_forecast(
    *,
    today: date,
    months: int,
    start_balance_cents: int,
    contracts: Sequence[ContractSpec],
    lines: Sequence[HistoryLine],
    first_activity: date | None,
) -> Forecast:
    """Project the balance from `today` to `today + months` calendar months (end-of-day balances).

    `lines` must cover the last three complete months and the current month up to `today`.
    `first_activity` is the earliest booking date in scope; months starting before it are not used.
    """
    horizon_end = add_months_clamped(today, months)
    this_month = today.replace(day=1)
    history = [reporting.add_months(this_month, -n) for n in range(HISTORY_MONTHS, 0, -1)]
    used = [m for m in history if first_activity is not None and first_activity <= m]
    insufficient = not used

    income_baseline, income_day, variable_baseline = (0, None, 0)
    if not insufficient:
        income_baseline, income_day, variable_baseline = _baselines(lines, used)

    events: list[ForecastEvent] = []
    for contract in contracts:
        events.extend(_contract_events(contract, today, horizon_end))

    income_events, variable_by_day = _baseline_flows(
        today, horizon_end, lines, income_baseline, income_day, variable_baseline
    )
    events.extend(income_events)
    income_by_day: dict[date, int] = defaultdict(int)
    for event in income_events:
        income_by_day[event.date] += event.amount_cents

    events.sort(key=lambda e: (e.date, e.kind, e.name))
    contract_by_day: dict[date, int] = defaultdict(int)
    for event in events:
        if event.kind == "contract":
            contract_by_day[event.date] += event.amount_cents

    daily = [DailyBalance(today, start_balance_cents)]
    balance = start_balance_cents
    # month key -> [income, contracts, variable, end balance]; the current month is always present.
    rows: dict[str, list[int]] = {reporting.month_key(this_month): [0, 0, 0, start_balance_cents]}
    day = today
    while day < horizon_end:
        day += timedelta(days=1)
        inc, con, var = income_by_day[day], contract_by_day[day], variable_by_day[day]
        balance += inc + con + var
        daily.append(DailyBalance(day, balance))
        row = rows.setdefault(reporting.month_key(day.replace(day=1)), [0, 0, 0, 0])
        row[0] += inc
        row[1] += con
        row[2] += var
        row[3] = balance
    return Forecast(
        start_balance_cents=start_balance_cents,
        as_of=today,
        horizon_end=horizon_end,
        daily=daily,
        months=[MonthForecast(key, r[0], r[1], r[2], r[3]) for key, r in sorted(rows.items())],
        lowest=min(daily, key=lambda d: (d.balance_cents, d.date)),
        events=events,
        assumptions=Assumptions(income_baseline, income_day, variable_baseline, len(used)),
        insufficient_history=insufficient,
    )


def load_forecast(db: Session, member: MemberContext, today: date, months: int) -> Forecast:
    stats = spendable_stats(db, member)
    account_ids = [s.account.id for s in stats]
    opening = sum(s.account.opening_balance_cents for s in stats)
    scope = (visible_transaction_clause(member), Transaction.account_id.in_(account_ids))
    booked = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            *scope, Transaction.booking_date <= today
        )
    )
    first_activity = db.scalar(select(func.min(Transaction.booking_date)).where(*scope))

    contract_rows = db.scalars(
        select(Contract)
        .where(
            visible_contract_clause(member),
            Contract.status == ContractStatus.CONFIRMED,
            Contract.account_id.is_(None) | Contract.account_id.in_(account_ids),
        )
        .order_by(Contract.name, Contract.id)
    )
    contracts = [
        ContractSpec(c.id, c.name, c.interval, c.expected_amount_cents, c.next_due_date)
        for c in contract_rows
    ]

    first = reporting.add_months(today.replace(day=1), -HISTORY_MONTHS)
    lines = reporting.effective_lines(member, first, today + timedelta(days=1))
    category = aliased(Category)
    line_rows = db.execute(
        select(lines.c.booking_date, lines.c.amount_cents)
        .select_from(lines.outerjoin(category, category.id == lines.c.category_id))
        .where(
            lines.c.account_id.in_(account_ids),
            lines.c.contract_id.is_(None),
            ~reporting.is_transfer(lines, category),
        )
    )
    return compute_forecast(
        today=today,
        months=months,
        start_balance_cents=opening + int(booked or 0),
        contracts=contracts,
        lines=[HistoryLine(d, int(a)) for d, a in line_rows],
        first_activity=first_activity,
    )
