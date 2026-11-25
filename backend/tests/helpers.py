"""Builders for finance tests."""

import uuid
from dataclasses import dataclass
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.deps import MemberContext
from app.finance.dedupe import random_dedupe_hash
from app.models import (
    Account,
    AccountKind,
    AccountVisibility,
    Category,
    CategoryKind,
    Contract,
    ContractInterval,
    ContractKind,
    ContractStatus,
    Transaction,
    User,
)

IBAN_A = "DE89370400440532013000"
IBAN_B = "DE02120300000000202051"
IBAN_C = "DE75512108001245126199"
IBAN_EXTERNAL = "GB82WEST12345698765432"


def member_of(user: User) -> MemberContext:
    assert user.membership is not None
    return MemberContext(user, user.membership.household, user.membership.role)


def make_account(
    db: Session,
    user: User,
    name: str = "Giro",
    visibility: AccountVisibility = AccountVisibility.SHARED,
    iban: str | None = None,
    opening: int = 0,
    kind: AccountKind = AccountKind.GIRO,
) -> Account:
    assert user.membership is not None
    account = Account(
        id=uuid.uuid4(),
        household_id=user.membership.household_id,
        owner_user_id=user.id,
        visibility=visibility,
        name=name,
        kind=kind,
        iban=iban,
        currency="EUR",
        opening_balance_cents=opening,
        is_archived=False,
    )
    db.add(account)
    db.commit()
    return account


def make_tx(
    db: Session,
    account: Account,
    amount_cents: int,
    booking_date: date = date(2026, 1, 15),
    counterparty_name: str | None = None,
    counterparty_iban: str | None = None,
    purpose: str | None = None,
    booking_text: str | None = None,
    category: Category | None = None,
    category_id: uuid.UUID | None = None,
) -> Transaction:
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=account.household_id,
        account_id=account.id,
        booking_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty_name=counterparty_name,
        counterparty_iban=counterparty_iban,
        purpose=purpose,
        booking_text=booking_text,
        dedupe_hash=random_dedupe_hash(),
        category_id=category.id if category else category_id,
    )
    db.add(tx)
    db.commit()
    return tx


def make_category(
    db: Session,
    household_id: uuid.UUID,
    name: str,
    kind: CategoryKind = CategoryKind.EXPENSE,
    parent: Category | None = None,
) -> Category:
    category = Category(
        id=uuid.uuid4(),
        household_id=household_id,
        parent_id=parent.id if parent else None,
        name=name,
        kind=parent.kind if parent else kind,
    )
    db.add(category)
    db.commit()
    return category


@dataclass
class World:
    """Two households: owner and member share one, `stranger` lives in another."""

    owner: TestClient
    member: TestClient
    stranger: TestClient
    owner_user: User
    member_user: User
    stranger_user: User


def make_contract(
    db: Session,
    household_id: uuid.UUID,
    *,
    account: Account | None = None,
    name: str = "Netflix",
    key: str = "netflix",
    status: ContractStatus = ContractStatus.CONFIRMED,
    interval: ContractInterval = ContractInterval.MONTHLY,
    amount_cents: int = -999,
    kind: ContractKind = ContractKind.SUBSCRIPTION,
    last_payment_date: date | None = None,
    next_due_date: date | None = None,
    min_term_end: date | None = None,
    notice_period_days: int | None = None,
) -> Contract:
    contract = Contract(
        id=uuid.uuid4(),
        household_id=household_id,
        account_id=account.id if account else None,
        name=name,
        kind=kind,
        status=status,
        counterparty_key=key,
        interval=interval,
        expected_amount_cents=amount_cents,
        amount_tolerance_pct=10,
        last_payment_date=last_payment_date,
        next_due_date=next_due_date,
        min_term_end=min_term_end,
        notice_period_days=notice_period_days,
    )
    db.add(contract)
    db.commit()
    return contract
