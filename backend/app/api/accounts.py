"""Accounts: list, create, update, delete and balance history."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api import finance_schemas as schemas
from app.api.common import conflict_on_duplicate
from app.deps import CurrentMember, DbDep, MemberContext, SettingsDep
from app.finance import reporting
from app.finance.access import get_visible_account
from app.models import Account, AccountVisibility
from app.sessions import audit

router = APIRouter(prefix="/accounts", tags=["accounts"])

DUPLICATE_IBAN = "An account with this IBAN already exists"


def _out(stats: reporting.AccountStats, member: MemberContext) -> schemas.AccountOut:
    account = stats.account
    return schemas.AccountOut(
        id=account.id,
        name=account.name,
        kind=account.kind,
        visibility=account.visibility,
        iban=account.iban,
        currency=account.currency,
        opening_balance_cents=account.opening_balance_cents,
        balance_cents=stats.balance_cents,
        is_archived=account.is_archived,
        owner_user_id=account.owner_user_id,
        is_mine=account.owner_user_id == member.user.id,
        transaction_count=stats.transaction_count,
        last_booking_date=stats.last_booking_date,
    )


def _single(db: Session, member: MemberContext, account_id: uuid.UUID) -> schemas.AccountOut:
    return _out(reporting.account_stats(db, member, account_id=account_id)[0], member)


@router.get("")
def list_accounts(member: CurrentMember, db: DbDep) -> list[schemas.AccountOut]:
    return [_out(stats, member) for stats in reporting.account_stats(db, member)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_account(
    body: schemas.AccountCreate,
    request: Request,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.AccountOut:
    account = Account(
        id=uuid.uuid4(),
        household_id=member.household.id,
        owner_user_id=member.user.id,
        visibility=body.visibility,
        name=body.name,
        kind=body.kind,
        iban=body.iban,
        currency="EUR",
        opening_balance_cents=body.opening_balance_cents,
        is_archived=False,
    )
    with conflict_on_duplicate(db, DUPLICATE_IBAN):
        db.add(account)
    audit(db, request, settings, "account_created", member.user, account_id=str(account.id))
    return _single(db, member, account.id)


@router.patch("/{account_id}")
def update_account(
    account_id: uuid.UUID, body: schemas.AccountUpdate, member: CurrentMember, db: DbDep
) -> schemas.AccountOut:
    account = get_visible_account(db, member, account_id)
    if body.visibility is AccountVisibility.PRIVATE and account.owner_user_id != member.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the account owner can make an account private")
    fields = body.model_fields_set
    with conflict_on_duplicate(db, DUPLICATE_IBAN):
        for name in ("name", "kind", "visibility", "opening_balance_cents", "is_archived"):
            if name in fields and getattr(body, name) is not None:
                setattr(account, name, getattr(body, name))
        if "iban" in fields:
            account.iban = body.iban
    return _single(db, member, account.id)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: uuid.UUID, request: Request, member: CurrentMember, db: DbDep, settings: SettingsDep
) -> None:
    account = get_visible_account(db, member, account_id)
    if account.owner_user_id != member.user.id and not member.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the account owner can delete this account")
    count = reporting.account_stats(db, member, account_id=account.id)[0].transaction_count
    # Transactions, imports and splits go with the account through ON DELETE CASCADE.
    db.delete(account)
    audit(
        db,
        request,
        settings,
        "account_deleted",
        member.user,
        account_id=str(account.id),
        transaction_count=str(count),
    )


@router.get("/{account_id}/balance-history")
def balance_history(
    account_id: uuid.UUID,
    member: CurrentMember,
    db: DbDep,
    months: Annotated[int, Query(ge=1, le=120)] = 12,
) -> list[schemas.BalancePoint]:
    account = get_visible_account(db, member, account_id)
    return [
        schemas.BalancePoint(month=month, balance_cents=balance)
        for month, balance in reporting.balance_history(db, account, months)
    ]
