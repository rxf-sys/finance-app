import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.finance import reporting
from app.finance.contracts import today_berlin
from app.finance.forecast import ContractSpec, HistoryLine, compute_forecast, median_int
from app.models import AccountVisibility, ContractInterval, ContractStatus
from tests.helpers import World, make_account, make_contract, make_tx

FORECAST = "/api/forecast"


def _spec(
    due: date | None, amount: int = -1000, interval: ContractInterval = ContractInterval.MONTHLY
) -> ContractSpec:
    return ContractSpec(uuid.uuid4(), "Vertrag", interval, amount, due)


def _run(
    today: date,
    months: int = 1,
    contracts: list[ContractSpec] | None = None,
    lines: list[HistoryLine] | None = None,
    start: int = 100_000,
    first_activity: date | None = None,
) -> Any:
    return compute_forecast(
        today=today,
        months=months,
        start_balance_cents=start,
        contracts=contracts or [],
        lines=lines or [],
        first_activity=first_activity,
    )


def _history(today: date, income: int, spend: int, income_day: int = 25) -> list[HistoryLine]:
    lines: list[HistoryLine] = []
    for n in (1, 2, 3):
        first = reporting.add_months(today.replace(day=1), -n)
        lines.append(HistoryLine(first.replace(day=income_day), income))
        lines.append(HistoryLine(first.replace(day=3), -spend))
    return lines


def test_median_int() -> None:
    assert median_int([]) == 0
    assert median_int([5, 1, 3]) == 3
    assert median_int([1, 4]) == 2


def test_no_history_only_contracts() -> None:
    today = date(2026, 11, 10)
    result = _run(today, contracts=[_spec(date(2026, 11, 15), -2000)])
    assert result.insufficient_history is True
    assert result.assumptions.income_baseline_cents == 0
    assert result.assumptions.variable_baseline_cents == 0
    assert result.horizon_end == date(2026, 12, 10)
    assert result.daily[0].balance_cents == 100_000
    assert result.daily[-1].balance_cents == 98_000
    assert result.lowest.balance_cents == 98_000
    assert [(e.date, e.kind) for e in result.events] == [(date(2026, 11, 15), "contract")]
    assert [m.month for m in result.months] == ["2026-11", "2026-12"]
    assert result.months[0].contracts_cents == -2000
    assert result.months[0].end_balance_cents == 98_000


def test_partial_first_month_is_not_history() -> None:
    today = date(2026, 11, 10)
    result = _run(today, lines=_history(today, 200_000, 50_000), first_activity=date(2026, 9, 20))
    assert result.assumptions.months_used == 1  # only October is covered from its first day


def test_month_boundary_and_clamping() -> None:
    today = date(2027, 1, 30)
    result = _run(today, months=2, contracts=[_spec(date(2027, 1, 31), -100)])
    dates = [e.date for e in result.events]
    # 31 Jan, then clamped to 28 Feb; the schedule steps from the previous (clamped) date.
    assert dates[0] == date(2027, 1, 31)
    assert dates[1] == date(2027, 2, 28)
    assert dates[-1] <= result.horizon_end == date(2027, 3, 30)
    assert result.months[0].month == "2027-01"
    assert result.months[0].contracts_cents == -100


def test_leap_february_clamp_of_income_day() -> None:
    today = date(2028, 1, 20)  # 2028 is a leap year
    lines = _history(today, 100_000, 0, income_day=30)
    result = _run(today, months=2, lines=lines, first_activity=date(2020, 1, 1))
    income_dates = [e.date for e in result.events if e.kind == "income"]
    assert income_dates == [date(2028, 1, 30), date(2028, 2, 29)]


def test_past_due_contract_lands_tomorrow_then_follows_schedule() -> None:
    today = date(2026, 11, 20)
    result = _run(today, months=2, contracts=[_spec(date(2026, 11, 5), -500)])
    dates = [e.date for e in result.events]
    assert dates == [date(2026, 11, 21), date(2026, 12, 5), date(2027, 1, 5)]


def test_contract_due_today_is_expected_tomorrow() -> None:
    today = date(2026, 11, 20)
    result = _run(today, contracts=[_spec(today, -500)])
    assert [e.date for e in result.events] == [date(2026, 11, 21), date(2026, 12, 20)]


def test_quarterly_yearly_and_weekly() -> None:
    today = date(2026, 11, 1)
    result = _run(
        today,
        months=3,
        contracts=[
            _spec(date(2026, 11, 15), -300, ContractInterval.QUARTERLY),
            _spec(date(2027, 1, 20), -1200, ContractInterval.YEARLY),
            _spec(date(2026, 11, 2), -10, ContractInterval.WEEKLY),
        ],
    )
    assert result.horizon_end == date(2027, 2, 1)
    by_amount: dict[int, list[date]] = {}
    for event in result.events:
        by_amount.setdefault(event.amount_cents, []).append(event.date)
    assert by_amount[-300] == [date(2026, 11, 15)]  # next quarter is 15 Feb, beyond the horizon
    assert by_amount[-1200] == [date(2027, 1, 20)]
    assert len(by_amount[-10]) == 14
    assert by_amount[-10][1] - by_amount[-10][0] == timedelta(days=7)


def test_positive_contract_counts_as_contract_amount() -> None:
    result = _run(date(2026, 11, 1), contracts=[_spec(date(2026, 11, 5), 7000)])
    assert result.months[0].contracts_cents == 7000
    assert result.daily[-1].balance_cents == 107_000


def test_full_months_use_baselines() -> None:
    today = date(2026, 11, 10)
    lines = _history(today, 300_000, 31_000, income_day=25)
    result = _run(today, months=2, lines=lines, first_activity=date(2026, 1, 1))
    assert result.assumptions.income_baseline_cents == 300_000
    assert result.assumptions.income_day == 25
    assert result.assumptions.variable_baseline_cents == 31_000
    assert result.assumptions.months_used == 3
    assert [(e.date, e.amount_cents) for e in result.events if e.kind == "income"] == [
        (date(2026, 11, 25), 300_000),
        (date(2026, 12, 25), 300_000),
    ]
    # Remaining November (20 days) carries the whole baseline since nothing was spent yet.
    nov = result.months[0]
    assert nov.variable_cents == -31_000
    assert nov.income_cents == 300_000
    dec = result.months[1]
    assert dec.variable_cents == -31_000
    assert dec.income_cents == 300_000


def test_last_month_is_cut_at_horizon_end() -> None:
    today = date(2026, 11, 10)
    lines = _history(today, 300_000, 31_000, income_day=25)
    result = _run(today, months=1, lines=lines, first_activity=date(2026, 1, 1))
    assert result.horizon_end == date(2026, 12, 10)
    assert result.months[1].variable_cents == -(31_000 * 10 // 31)
    assert result.months[1].income_cents == 0
    assert [e.date for e in result.events if e.kind == "income"] == [date(2026, 11, 25)]


def test_current_month_partial_income_and_spending() -> None:
    today = date(2026, 11, 10)
    lines = [
        *_history(today, 300_000, 40_000),
        HistoryLine(date(2026, 11, 1), 200_000),  # 66 percent of the baseline already received
        HistoryLine(date(2026, 11, 5), -15_000),
    ]
    result = _run(today, lines=lines, first_activity=date(2026, 1, 1))
    assert [e for e in result.events if e.kind == "income"] == []
    assert result.months[0].variable_cents == -25_000
    # Remaining spend is zero when the baseline is already used up.
    lines.append(HistoryLine(date(2026, 11, 6), -30_000))
    assert _run(today, lines=lines, first_activity=date(2026, 1, 1)).months[0].variable_cents == 0


def test_income_day_already_passed_this_month() -> None:
    today = date(2026, 11, 28)
    lines = _history(today, 300_000, 0, income_day=25)
    result = _run(today, lines=lines, first_activity=date(2026, 1, 1))
    assert [e.date for e in result.events if e.kind == "income"] == [date(2026, 12, 25)]


def test_today_is_last_day_of_month() -> None:
    today = date(2026, 11, 30)
    lines = _history(today, 100_000, 30_000)
    result = _run(today, lines=lines, first_activity=date(2026, 1, 1))
    assert result.months[0].month == "2026-11"
    assert result.months[0].variable_cents == 0
    assert result.daily[0].balance_cents == 100_000


# ---------------------------------------------------------------- API


def _seed_history(db: Session, account: Any, income: int = 300_000, spend: int = 20_000) -> None:
    today = today_berlin()
    for n in (1, 2, 3):
        first = reporting.add_months(today.replace(day=1), -n)
        make_tx(db, account, income, first.replace(day=1), counterparty_name="Arbeitgeber")
        make_tx(db, account, -spend, first.replace(day=2), counterparty_name="Rewe")


def test_forecast_api_basic(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, opening=1000)
    _seed_history(db, account)
    make_tx(db, account, -500, today_berlin() + timedelta(days=3))  # future-dated: ignored
    response = world.owner.get(FORECAST, params={"months": 2})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start_balance_cents"] == 1000 + 3 * (300_000 - 20_000)
    assert body["as_of"] == today_berlin().isoformat()
    assert body["insufficient_history"] is False
    assert body["assumptions"]["income_baseline_cents"] == 300_000
    assert body["assumptions"]["variable_baseline_cents"] == 20_000
    assert body["assumptions"]["income_day"] == 1
    assert body["daily"][0]["balance_cents"] == body["start_balance_cents"]
    assert world.owner.get(FORECAST, params={"months": 4}).status_code == 422
    assert world.owner.get(FORECAST, params={"months": 0}).status_code == 422


def test_forecast_api_ignores_contract_linked_and_transfers_in_baselines(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    other = make_account(db, world.owner_user, "Zweit")
    _seed_history(db, account)
    contract = make_contract(db, account.household_id, account=account, amount_cents=-9999)
    today = today_berlin()
    first = reporting.add_months(today.replace(day=1), -1)
    linked = make_tx(db, account, -9999, first.replace(day=5))
    linked.contract_id = contract.id
    paired_a = make_tx(db, account, -77_000, first.replace(day=6))
    paired_b = make_tx(db, other, 77_000, first.replace(day=6))
    paired_a.transfer_peer_id = paired_b.id
    paired_b.transfer_peer_id = paired_a.id
    db.commit()
    body = world.owner.get(FORECAST).json()
    assert body["assumptions"]["variable_baseline_cents"] == 20_000
    assert body["assumptions"]["income_baseline_cents"] == 300_000


def test_forecast_api_keeps_payments_of_unconfirmed_contracts_in_baseline(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _seed_history(db, account)
    suggestion = make_contract(db, account.household_id, account=account, status=ContractStatus.DETECTED)
    today = today_berlin()
    for n in (1, 2, 3):
        payment = make_tx(db, account, -999, reporting.add_months(today.replace(day=1), -n).replace(day=10))
        payment.contract_id = suggestion.id
    db.commit()
    body = world.owner.get(FORECAST).json()
    assert body["assumptions"]["variable_baseline_cents"] == 20_000 + 999
    assert all(e["kind"] != "contract" for e in body["events"])


def test_forecast_api_private_accounts_and_contracts_of_others_do_not_count(
    world: World, db: Session
) -> None:
    shared = make_account(db, world.owner_user, "Gemeinsam")
    secret = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE, opening=5_000_000)
    _seed_history(db, shared)
    _seed_history(db, secret, income=900_000, spend=800_000)
    due = today_berlin() + timedelta(days=5)
    make_contract(db, shared.household_id, account=secret, next_due_date=due, amount_cents=-4242)

    owner = world.owner.get(FORECAST).json()
    member = world.member.get(FORECAST).json()
    assert member["start_balance_cents"] == 3 * (300_000 - 20_000)
    assert member["assumptions"]["income_baseline_cents"] == 300_000
    assert member["assumptions"]["variable_baseline_cents"] == 20_000
    assert member["events"] == [] or all(e["amount_cents"] != -4242 for e in member["events"])
    assert owner["start_balance_cents"] == member["start_balance_cents"] + 5_000_000 + 3 * 100_000


def test_forecast_api_stranger_household_and_empty(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _seed_history(db, account)
    make_contract(db, account.household_id, next_due_date=today_berlin() + timedelta(days=2))
    body = world.stranger.get(FORECAST).json()
    assert body["start_balance_cents"] == 0
    assert body["insufficient_history"] is True
    assert body["events"] == []
    assert body["lowest"]["balance_cents"] == 0
