import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.finance.available import available_to_spend
from app.finance.budgets import budget_status
from app.finance.notifications import generate_notifications
from app.models import (
    AccountKind,
    AccountVisibility,
    BankConnection,
    BankConnectionStatus,
    BankProvider,
    Budget,
    ContractInterval,
    ContractStatus,
    Notification,
    NotificationKind,
    Transaction,
    TransactionSplit,
)
from app.models.base import utcnow
from app.worker import detect_contracts_nightly, generate_notifications_daily
from tests.helpers import World, make_account, make_category, make_contract, make_tx, member_of

MONTH = date(2026, 11, 1)
IN_MONTH = date(2026, 11, 10)
LAST_MONTH = date(2026, 10, 10)


def _budget(
    db: Session, household_id: uuid.UUID, category_id: uuid.UUID, cents: int, rollover: bool = False
) -> Budget:
    budget = Budget(
        id=uuid.uuid4(),
        household_id=household_id,
        category_id=category_id,
        amount_cents=cents,
        rollover=rollover,
    )
    db.add(budget)
    db.commit()
    return budget


def test_budget_counts_children_splits_and_skips_transfers(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    other = make_account(db, world.owner_user, "Zweit")
    hid = account.household_id
    food = make_category(db, hid, "Essen")
    eating_out = make_category(db, hid, "Restaurant", parent=food)
    misc = make_category(db, hid, "Sonstiges")
    _budget(db, hid, food.id, 50_000)

    make_tx(db, account, -10_000, IN_MONTH, category=eating_out)
    make_tx(db, account, -5_000, IN_MONTH, category=food)
    make_tx(db, account, 2_000, IN_MONTH, category=food)  # refunds are not netted
    make_tx(db, account, -9_999, date(2026, 12, 1), category=food)  # other month
    split_tx = make_tx(db, account, -20_000, IN_MONTH)
    db.add_all(
        [
            TransactionSplit(
                transaction_id=split_tx.id, position=0, amount_cents=-8_000, category_id=eating_out.id
            ),
            TransactionSplit(
                transaction_id=split_tx.id, position=1, amount_cents=-12_000, category_id=misc.id
            ),
        ]
    )
    out = make_tx(db, account, -7_000, IN_MONTH, category=food)
    inc = make_tx(db, other, 7_000, IN_MONTH, category=food)
    out.transfer_peer_id, inc.transfer_peer_id = inc.id, out.id
    db.commit()

    (status,) = budget_status(db, member_of(world.owner_user), MONTH)
    assert status.spent_cents == 23_000
    assert status.limit_cents == 50_000
    assert status.remaining_cents == 27_000
    assert (status.pct, status.state) == (46, "ok")


def test_budget_on_child_only_counts_that_child(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    food = make_category(db, account.household_id, "Essen")
    child = make_category(db, account.household_id, "Restaurant", parent=food)
    _budget(db, account.household_id, child.id, 10_000)
    make_tx(db, account, -3_000, IN_MONTH, category=child)
    make_tx(db, account, -4_000, IN_MONTH, category=food)
    (status,) = budget_status(db, member_of(world.owner_user), MONTH)
    assert status.spent_cents == 3_000


def test_budget_states(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    cats = [make_category(db, account.household_id, n) for n in ("A", "B", "C")]
    for cat, spent in zip(cats, (7_900, 8_000, 10_000), strict=True):
        _budget(db, account.household_id, cat.id, 10_000)
        make_tx(db, account, -spent, IN_MONTH, category=cat)
    states = [s.state for s in budget_status(db, member_of(world.owner_user), MONTH)]
    assert states == ["ok", "warning", "exceeded"]


def test_budget_only_sees_visible_transactions(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    cat = make_category(db, private.household_id, "Essen")
    _budget(db, private.household_id, cat.id, 10_000)
    make_tx(db, private, -5_000, IN_MONTH, category=cat)
    (mine,) = budget_status(db, member_of(world.owner_user), MONTH)
    (theirs,) = budget_status(db, member_of(world.member_user), MONTH)
    assert (mine.spent_cents, theirs.spent_cents) == (5_000, 0)


def test_budget_rollover_adds_unspent_remainder_once(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    cat = make_category(db, account.household_id, "Essen")
    _budget(db, account.household_id, cat.id, 50_000, rollover=True)
    make_tx(db, account, -30_000, LAST_MONTH, category=cat)
    make_tx(db, account, -10_000, IN_MONTH, category=cat)
    (status,) = budget_status(db, member_of(world.owner_user), MONTH)
    assert status.limit_cents == 70_000
    assert status.remaining_cents == 60_000


def test_budget_rollover_is_never_negative_and_does_not_chain(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    cat = make_category(db, account.household_id, "Essen")
    _budget(db, account.household_id, cat.id, 50_000, rollover=True)
    make_tx(db, account, -80_000, LAST_MONTH, category=cat)
    (status,) = budget_status(db, member_of(world.owner_user), MONTH)
    assert status.limit_cents == 50_000


def test_budget_rollover_does_not_chain(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    cat = make_category(db, account.household_id, "Essen")
    _budget(db, account.household_id, cat.id, 50_000, rollover=True)
    make_tx(db, account, -1_000, date(2026, 8, 10), category=cat)
    member = member_of(world.owner_user)
    (september,) = budget_status(db, member, date(2026, 9, 1))
    (october,) = budget_status(db, member, date(2026, 10, 1))
    assert september.limit_cents == 99_000
    assert october.limit_cents == 100_000  # September's carried-over money is not carried again


def test_available_to_spend_with_weekly_contract(world: World, db: Session) -> None:
    giro = make_account(db, world.owner_user, opening=100_000)
    make_account(db, world.owner_user, "Spar", kind=AccountKind.SAVINGS, opening=500_000)
    archived = make_account(db, world.owner_user, "Alt", opening=77_000)
    archived.is_archived = True
    db.commit()
    hid = giro.household_id
    today = date(2026, 11, 10)
    make_contract(
        db, hid, account=giro, name="Miete", key="m", amount_cents=-5_000, next_due_date=date(2026, 11, 20)
    )
    make_contract(
        db, hid, account=giro, name="Zeitung", key="z", amount_cents=-1_000,
        interval=ContractInterval.WEEKLY, next_due_date=date(2026, 11, 12),
    )  # fmt: skip
    make_contract(db, hid, name="Lohn", key="l", amount_cents=20_000, next_due_date=date(2026, 11, 28))
    make_contract(db, hid, name="Später", key="s", amount_cents=-900, next_due_date=date(2026, 12, 2))
    make_contract(db, hid, name="Heute", key="h", amount_cents=-800, next_due_date=today)
    make_contract(
        db, hid, name="Vorschlag", key="v", amount_cents=-700, status=ContractStatus.DETECTED,
        next_due_date=date(2026, 11, 15),
    )  # fmt: skip

    result = available_to_spend(db, member_of(world.owner_user), today)

    assert result.balance_cents == 100_000
    assert result.upcoming_out_cents == 5_000 + 3_000
    assert result.upcoming_in_cents == 20_000
    assert result.available_cents == 112_000
    assert [(i.name, i.due_date.day) for i in result.items] == [
        ("Zeitung", 12), ("Zeitung", 19), ("Miete", 20), ("Zeitung", 26), ("Lohn", 28),
    ]  # fmt: skip


def test_available_ignores_contracts_on_other_account_kinds(world: World, db: Session) -> None:
    giro = make_account(db, world.owner_user, opening=10_000)
    card = make_account(db, world.owner_user, "Karte", kind=AccountKind.CREDIT_CARD)
    savings = make_account(db, world.owner_user, "Spar", kind=AccountKind.SAVINGS)
    cash = make_account(db, world.owner_user, "Bar", kind=AccountKind.CASH)
    hid = giro.household_id
    due = date(2026, 11, 20)
    make_contract(db, hid, account=giro, key="g", amount_cents=-100, next_due_date=due)
    make_contract(db, hid, account=cash, key="c", amount_cents=-200, next_due_date=due)
    make_contract(db, hid, key="n", amount_cents=-400, next_due_date=due)  # no account
    make_contract(db, hid, account=card, key="k", amount_cents=-800, next_due_date=due)
    make_contract(db, hid, account=savings, key="s", amount_cents=-1_600, next_due_date=due)
    result = available_to_spend(db, member_of(world.owner_user), date(2026, 11, 10))
    assert result.upcoming_out_cents == 700
    assert len(result.items) == 3


def test_available_hides_contracts_on_private_accounts(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE, opening=1_000)
    make_contract(
        db, private.household_id, account=private, amount_cents=-500, next_due_date=date(2026, 11, 20)
    )
    result = available_to_spend(db, member_of(world.member_user), date(2026, 11, 10))
    assert (result.balance_cents, result.upcoming_out_cents, result.items) == (0, 0, [])


def _count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Notification)) or 0)


def test_contract_notice_dedupes_and_respects_visibility(world: World, db: Session) -> None:
    today = date(2026, 11, 10)
    shared = make_account(db, world.owner_user)
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    hid = shared.household_id
    term_end = today + timedelta(days=40)  # with 10 days notice the deadline is in 30 days
    make_contract(db, hid, account=shared, key="a", min_term_end=term_end, notice_period_days=10)
    make_contract(db, hid, account=private, key="b", min_term_end=term_end, notice_period_days=10)

    assert generate_notifications(db, today) == 3  # two users for shared, owner only for private
    db.commit()
    assert generate_notifications(db, today) == 0
    assert generate_notifications(db, today + timedelta(days=1)) == 0  # 29 days left: same threshold
    db.commit()
    assert _count(db) == 3
    private_notes = db.scalars(select(Notification).where(Notification.user_id == world.member_user.id)).all()
    assert len(private_notes) == 1

    # Closer to the deadline the tighter threshold fires once more.
    assert generate_notifications(db, today + timedelta(days=24)) == 3
    db.commit()
    assert _count(db) == 6
    keys = set(db.scalars(select(Notification.dedupe_key)))
    assert any(k.endswith(":7") for k in keys)
    assert all(":deadline:2026-12-10:" in k for k in keys if k.startswith("contract:"))


def test_budget_warning_fires_per_level_once(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    cat = make_category(db, account.household_id, "Essen")
    _budget(db, account.household_id, cat.id, 10_000)
    today = date(2026, 11, 20)
    spend = make_tx(db, account, -8_500, IN_MONTH, category=cat)

    assert generate_notifications(db, today) == 2  # both members
    db.commit()
    assert generate_notifications(db, today) == 0

    spend.amount_cents = -10_500
    db.commit()
    assert generate_notifications(db, today) == 2
    db.commit()
    kinds = {n.kind for n in db.scalars(select(Notification))}
    assert kinds == {NotificationKind.BUDGET_WARNING}
    assert _count(db) == 4


def test_consent_expiry_goes_to_connection_owner_only(world: World, db: Session) -> None:
    db.add(
        BankConnection(
            id=uuid.uuid4(),
            household_id=member_of(world.owner_user).household.id,
            owner_user_id=world.member_user.id,
            provider=BankProvider.ENABLE_BANKING,
            aspsp_name="Testbank",
            aspsp_country="DE",
            status=BankConnectionStatus.ACTIVE,
            consent_valid_until=utcnow() + timedelta(days=10),
        )
    )
    db.commit()
    assert generate_notifications(db, utcnow().date()) == 1
    db.commit()
    (note,) = db.scalars(select(Notification)).all()
    assert note.user_id == world.member_user.id
    assert note.kind is NotificationKind.CONSENT_EXPIRY


def test_daily_jobs_run(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    for d in (date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)):
        make_tx(db, account, -999, d, counterparty_name="Netflix")
    generate_notifications_daily(timestamp=0)
    detect_contracts_nightly(timestamp=0)  # stale relative to the real today: must not fail
    assert db.scalar(select(func.count()).select_from(Transaction)) == 3
