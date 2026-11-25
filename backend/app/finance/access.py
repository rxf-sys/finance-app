"""The single place that decides which accounts and transactions a household member may see.

An account is visible when it belongs to the member's household and is either shared or owned by
the member. A transaction is visible iff its account is. A contract is visible when it belongs to the
household and has no account or a visible one. Anything else is reported as 404, never
403, so ids of hidden rows do not leak.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.deps import MemberContext
from app.models import Account, AccountVisibility, Contract, HouseholdMember, Transaction


def visible_account_clause(member: MemberContext) -> ColumnElement[bool]:
    return and_(
        Account.household_id == member.household.id,
        or_(Account.visibility == AccountVisibility.SHARED, Account.owner_user_id == member.user.id),
    )


def visible_transaction_clause(member: MemberContext) -> ColumnElement[bool]:
    """Transaction-level filter: same household and a visible account."""
    return and_(
        Transaction.household_id == member.household.id,
        Transaction.account_id.in_(select(Account.id).where(visible_account_clause(member))),
    )


def get_visible_account(db: Session, member: MemberContext, account_id: uuid.UUID) -> Account:
    account = db.scalar(select(Account).where(Account.id == account_id, visible_account_clause(member)))
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


def get_visible_transaction(db: Session, member: MemberContext, transaction_id: uuid.UUID) -> Transaction:
    transaction = db.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id, visible_transaction_clause(member))
        .options(
            selectinload(Transaction.splits),
            selectinload(Transaction.tags),
            selectinload(Transaction.category),
        )
    )
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return transaction


def visible_contract_clause(member: MemberContext) -> ColumnElement[bool]:
    """Contract-level filter: same household, and either household-wide or on a visible account."""
    return and_(
        Contract.household_id == member.household.id,
        or_(
            Contract.account_id.is_(None),
            Contract.account_id.in_(select(Account.id).where(visible_account_clause(member))),
        ),
    )


def get_visible_contract(db: Session, member: MemberContext, contract_id: uuid.UUID) -> Contract:
    contract = db.scalar(select(Contract).where(Contract.id == contract_id, visible_contract_clause(member)))
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    return contract


def account_audience(db: Session, household_id: uuid.UUID, account_id: uuid.UUID | None) -> list[uuid.UUID]:
    """User ids of the household members who can see an account (everybody when there is none).

    Mirrors `visible_account_clause` for background jobs that have no acting member.
    """
    members = select(HouseholdMember.user_id).where(HouseholdMember.household_id == household_id)
    if account_id is not None:
        account = db.scalar(
            select(Account).where(Account.id == account_id, Account.household_id == household_id)
        )
        if account is None:
            return []
        if account.visibility is AccountVisibility.PRIVATE:
            members = members.where(HouseholdMember.user_id == account.owner_user_id)
    return list(db.scalars(members.order_by(HouseholdMember.user_id)))
