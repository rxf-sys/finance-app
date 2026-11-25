from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance.contracts import (
    add_months_clamped,
    cancellation_deadline,
    cancellation_letter_text,
    detect_contracts,
    earliest_end_date,
    match_payments,
)
from app.models import (
    Account,
    AccountVisibility,
    CategoryKind,
    Contract,
    ContractInterval,
    ContractKind,
    ContractPriceChange,
    ContractStatus,
    Notification,
    NotificationKind,
    Transaction,
)
from tests.helpers import World, make_account, make_category, make_contract, make_tx

TODAY = date(2026, 10, 20)
MONTHLY = [date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)]


def _pay(
    db: Session, account: Account, dates: list[date], amount: int = -999, name: str = "Netflix Intl"
) -> list[Transaction]:
    return [make_tx(db, account, amount, d, counterparty_name=name) for d in dates]


def test_detects_monthly_contract_and_links_payments(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    streaming = make_category(db, account.household_id, "Abos & Medien")
    txs = _pay(db, account, MONTHLY)
    for tx in txs:
        tx.category_id = streaming.id
    db.commit()

    created = detect_contracts(db, account.household_id, today=TODAY)
    db.commit()

    assert len(created) == 1
    contract = created[0]
    assert contract.status is ContractStatus.DETECTED
    assert contract.name == "Netflix Intl"
    assert contract.kind is ContractKind.SUBSCRIPTION
    assert contract.interval is ContractInterval.MONTHLY
    assert contract.expected_amount_cents == -999
    assert contract.last_payment_date == date(2026, 10, 5)
    assert contract.next_due_date == date(2026, 11, 5)
    assert contract.account_id == account.id
    assert contract.category_id == streaming.id
    db.expire_all()
    assert {t.contract_id for t in db.scalars(select(Transaction))} == {contract.id}
    assert detect_contracts(db, account.household_id, today=TODAY) == []


def test_detects_yearly_with_two_payments(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, [date(2025, 11, 10), date(2026, 11, 10)], amount=-12000, name="Haftpflicht AG")
    (contract,) = detect_contracts(db, account.household_id, today=date(2026, 11, 25))
    assert contract.interval is ContractInterval.YEARLY
    assert contract.next_due_date == date(2027, 11, 10)


def test_two_monthly_payments_are_not_enough(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, MONTHLY[1:])
    assert detect_contracts(db, account.household_id, today=TODAY) == []


def test_irregular_payments_are_not_detected(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, [date(2026, 7, 1), date(2026, 7, 11), date(2026, 9, 18), date(2026, 10, 4)])
    assert detect_contracts(db, account.household_id, today=TODAY) == []


def test_stale_series_is_not_detected(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, MONTHLY)
    assert detect_contracts(db, account.household_id, today=date(2026, 12, 1)) == []


def test_amount_outlier_is_ignored(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    txs = _pay(db, account, [date(2026, 7, 5), *MONTHLY])
    outlier = make_tx(db, account, -5000, date(2026, 9, 20), counterparty_name="Netflix Intl")
    (contract,) = detect_contracts(db, account.household_id, today=TODAY)
    db.commit()
    assert contract.expected_amount_cents == -999
    assert outlier.contract_id is None
    assert all(tx.contract_id == contract.id for tx in txs)


def test_incoming_and_transfers_are_skipped(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, MONTHLY, amount=999, name="Arbeitgeber")
    moves = make_category(db, account.household_id, "Umbuchung", kind=CategoryKind.TRANSFER)
    for tx in _pay(db, account, MONTHLY, name="Sparplan"):
        tx.category_id = moves.id
    db.commit()
    assert detect_contracts(db, account.household_id, today=TODAY) == []


def test_ignored_and_cancelled_keys_are_not_reproposed(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, MONTHLY)
    _pay(db, account, MONTHLY, name="Gym")
    hid = account.household_id
    make_contract(db, hid, account=account, key="netflix intl", status=ContractStatus.IGNORED)
    make_contract(db, hid, account=account, key="gym", status=ContractStatus.CANCELLED)
    assert detect_contracts(db, hid, today=TODAY) == []


def test_iban_is_the_key_when_present(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    iban = "DE02120300000000202051"
    for d, name in zip(MONTHLY, ["A GmbH", "A Gmbh", "A"], strict=True):
        make_tx(db, account, -2500, d, counterparty_name=name, counterparty_iban=iban)
    (contract,) = detect_contracts(db, account.household_id, today=TODAY)
    assert contract.counterparty_key == iban
    assert contract.counterparty_iban == iban


def test_private_account_contract_keeps_account_id(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    _pay(db, private, MONTHLY)
    (contract,) = detect_contracts(db, private.household_id, today=TODAY)
    assert contract.account_id == private.id


def test_month_stepping_clamps_to_month_end() -> None:
    assert add_months_clamped(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months_clamped(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months_clamped(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months_clamped(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_next_due_date_for_payment_on_the_31st(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    _pay(db, account, [date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 31)])
    (contract,) = detect_contracts(db, account.household_id, today=date(2026, 11, 5))
    assert contract.next_due_date == date(2026, 11, 30)


def test_match_links_payment_within_tolerance(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    contract = make_contract(
        db, account.household_id, account=account, key="netflix intl",
        last_payment_date=date(2026, 10, 5), next_due_date=date(2026, 11, 5),
    )  # fmt: skip
    tx = make_tx(db, account, -1020, date(2026, 11, 6), counterparty_name="NETFLIX  Intl")
    assert match_payments(db, account.household_id, [tx]) == 1
    db.commit()
    assert tx.contract_id == contract.id
    assert contract.last_payment_date == date(2026, 11, 6)
    assert contract.next_due_date == date(2026, 12, 6)
    assert contract.expected_amount_cents == -999
    assert db.scalars(select(ContractPriceChange)).all() == []


def test_match_ignores_other_account_and_unrelated_amount(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    other = make_account(db, world.owner_user, "Zweit")
    make_contract(
        db, account.household_id, account=account, key="netflix intl",
        last_payment_date=date(2026, 10, 5),
    )  # fmt: skip
    elsewhere = make_tx(db, other, -999, date(2026, 11, 5), counterparty_name="Netflix Intl")
    early = make_tx(db, account, -3000, date(2026, 10, 12), counterparty_name="Netflix Intl")
    assert match_payments(db, account.household_id, [elsewhere, early]) == 0


def test_price_change_is_recorded_and_notified(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    contract = make_contract(
        db, account.household_id, account=account, key="netflix intl",
        last_payment_date=date(2026, 10, 5), next_due_date=date(2026, 11, 5),
    )  # fmt: skip
    tx = make_tx(db, account, -1299, date(2026, 11, 5), counterparty_name="Netflix Intl")
    assert match_payments(db, account.household_id, [tx]) == 1
    db.commit()

    (change,) = db.scalars(select(ContractPriceChange)).all()
    assert (change.old_amount_cents, change.new_amount_cents) == (-999, -1299)
    assert change.effective_date == date(2026, 11, 5)
    assert change.transaction_id == tx.id
    assert contract.expected_amount_cents == -1299
    notes = db.scalars(select(Notification)).all()
    assert {n.user_id for n in notes} == {world.owner_user.id, world.member_user.id}
    assert {n.kind for n in notes} == {NotificationKind.PRICE_CHANGE}


def test_price_change_on_private_account_notifies_owner_only(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    make_contract(
        db, private.household_id, account=private, key="netflix intl",
        last_payment_date=date(2026, 10, 5),
    )  # fmt: skip
    tx = make_tx(db, private, -1299, date(2026, 11, 5), counterparty_name="Netflix Intl")
    match_payments(db, private.household_id, [tx])
    db.commit()
    assert {n.user_id for n in db.scalars(select(Notification))} == {world.owner_user.id}


def _contract(term_end: date | None, notice: int | None) -> Contract:
    return Contract(min_term_end=term_end, notice_period_days=notice)


def test_cancellation_deadline() -> None:
    today = date(2026, 6, 10)
    assert cancellation_deadline(_contract(None, 30), today) is None
    assert cancellation_deadline(_contract(date(2026, 12, 31), None), today) is None
    assert cancellation_deadline(_contract(date(2026, 12, 31), 30), today) == date(2026, 12, 1)
    assert cancellation_deadline(_contract(today, 0), today) == today


def test_cancellation_deadline_renews_monthly_after_minimum_term() -> None:
    # Term ended 31 Jan; next end after 10 Jun is 30 Jun (day clamped), minus 14 days.
    assert cancellation_deadline(_contract(date(2026, 1, 31), 14), date(2026, 6, 10)) == date(2026, 6, 16)
    # Stepping starts from the original date, so the 31st is kept where the month has one.
    assert cancellation_deadline(_contract(date(2026, 1, 31), 0), date(2026, 7, 1)) == date(2026, 7, 31)


def test_cancellation_deadline_skips_deadlines_in_the_past() -> None:
    today = date(2026, 6, 10)
    # Term ends 20 Jun but the 30-day notice ended 21 May: take the next term (20 Jul -> 20 Jun).
    assert cancellation_deadline(_contract(date(2026, 6, 20), 30), today) == date(2026, 6, 20)
    # Minimum term not over yet, yet its deadline passed: the monthly renewal applies as well.
    assert cancellation_deadline(_contract(date(2026, 6, 30), 30), today) == date(2026, 6, 30)
    # Deadline exactly today is still open.
    assert cancellation_deadline(_contract(date(2026, 7, 10), 30), today) == today
    # A long-gone term catches up month by month.
    assert cancellation_deadline(_contract(date(2024, 1, 15), 7), today) == date(2026, 7, 8)


def test_earliest_end_date() -> None:
    today = date(2026, 6, 10)
    assert earliest_end_date(_contract(None, 30), today) is None
    assert earliest_end_date(_contract(date(2026, 12, 31), None), today) is None
    assert earliest_end_date(_contract(date(2026, 12, 31), 30), today) == date(2026, 12, 31)
    # Deadline of the 20 Jun term passed on 21 May: the next term ends 20 Jul.
    assert earliest_end_date(_contract(date(2026, 6, 20), 30), today) == date(2026, 7, 20)
    # Deadline exactly today is still open, so that term end counts.
    assert earliest_end_date(_contract(date(2026, 7, 10), 30), today) == date(2026, 7, 10)
    # Month-end clamping after the minimum term: 31 Jan renews to 30 Jun.
    assert earliest_end_date(_contract(date(2026, 1, 31), 14), today) == date(2026, 6, 30)


def test_cancellation_letter_text() -> None:
    subject, body = cancellation_letter_text(
        contract_name="Streamo", customer_number=None, sender="Anna", end_date=None
    )
    assert subject == "Kündigung meines Vertrags"
    assert "Kundennummer" not in body and "Nach meiner Berechnung" not in body
    assert "zum nächstmöglichen Zeitpunkt.\n\n" in body

    subject, body = cancellation_letter_text(
        contract_name="Streamo", customer_number="4711", sender="Anna", end_date=date(2026, 7, 5)
    )
    assert subject == "Kündigung meines Vertrags (Kundennummer 4711)"
    assert "Kundennummer: 4711\n\n" in body
    assert "zum nächstmöglichen Zeitpunkt. Nach meiner Berechnung ist das der 05.07.2026." in body
    assert body.endswith("Mit freundlichen Grüßen\nAnna")
