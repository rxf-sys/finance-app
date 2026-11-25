import io
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cli
from app.demo import DEMO_EMAIL, DemoRefusedError, seed_demo
from app.finance.contracts import cancellation_deadline
from app.models import (
    Account,
    AccountVisibility,
    Budget,
    Contract,
    ContractPriceChange,
    ContractStatus,
    HouseholdMember,
    SavingsGoal,
    Transaction,
    User,
)
from tests.conftest import UserFactory

TODAY = date(2026, 11, 25)
PASSWORD = "demo passphrase 2026"


def test_seed_demo_builds_a_complete_household(db: Session) -> None:
    result = seed_demo(db, PASSWORD, today=TODAY)

    assert db.scalar(select(func.count()).select_from(HouseholdMember)) == 2
    accounts = list(db.scalars(select(Account).where(Account.household_id == result.household_id)))
    assert {a.name for a in accounts} == {"Girokonto", "Tagesgeld", "Kreditkarte"}
    assert [a.name for a in accounts if a.visibility is AccountVisibility.PRIVATE] == ["Kreditkarte"]

    transactions = list(
        db.scalars(select(Transaction).where(Transaction.household_id == result.household_id))
    )
    assert len(transactions) == result.transactions > 100
    assert all(tx.category_id is not None for tx in transactions)
    assert max(tx.booking_date for tx in transactions) <= TODAY

    assert db.scalar(select(func.count()).select_from(Budget)) == 3
    assert {g.name for g in db.scalars(select(SavingsGoal))} == {"Sommerurlaub", "Notgroschen"}


def test_seed_demo_pairs_transfers_both_ways(db: Session) -> None:
    seed_demo(db, PASSWORD, today=TODAY)

    paired = list(db.scalars(select(Transaction).where(Transaction.transfer_peer_id.is_not(None))))
    assert paired
    by_id = {tx.id: tx for tx in paired}
    for tx in paired:
        assert tx.transfer_peer_id is not None
        peer = by_id[tx.transfer_peer_id]
        assert peer.transfer_peer_id == tx.id
        assert peer.amount_cents == -tx.amount_cents


def test_seed_demo_confirms_only_fixed_costs(db: Session) -> None:
    result = seed_demo(db, PASSWORD, today=TODAY)

    confirmed = {
        c.name for c in db.scalars(select(Contract).where(Contract.status == ContractStatus.CONFIRMED))
    }
    assert {"Wohnbau Lindenhof eG", "Stadtwerke Lindenhof", "Funkwerk Mobil", "Kinowelt Stream"} <= confirmed
    assert "Drogerie Klar" not in confirmed
    assert len(confirmed) == result.contracts


def test_seed_demo_shows_a_deadline_and_a_price_change(db: Session) -> None:
    seed_demo(db, PASSWORD, today=TODAY)

    power = db.scalar(select(Contract).where(Contract.name == "Stadtwerke Lindenhof"))
    assert power is not None
    deadline = cancellation_deadline(power, TODAY)
    assert deadline is not None and 0 <= (deadline - TODAY).days <= 30

    change = db.scalar(select(ContractPriceChange))
    assert change is not None
    assert (change.old_amount_cents, change.new_amount_cents) == (-1_999, -2_199)
    assert change.acknowledged_at is None


def test_seed_demo_refuses_a_database_with_users(db: Session, make_user: UserFactory) -> None:
    make_user()

    with pytest.raises(DemoRefusedError):
        seed_demo(db, PASSWORD, today=TODAY)


def test_cli_seed_demo_reads_the_password_from_stdin(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))

    assert cli.main(["seed-demo", "--password-stdin"]) == 0
    assert db.scalar(select(User.email).where(User.email == DEMO_EMAIL)) == DEMO_EMAIL


def test_cli_seed_demo_rejects_a_short_password(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))

    assert cli.main(["seed-demo", "--password-stdin"]) == 1
    assert db.scalar(select(func.count()).select_from(User)) == 0
