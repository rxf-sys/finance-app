"""The single place that decides which accounts and transactions a household member may see.

An account is visible when it belongs to the member's household and is either shared or owned by
the member. A transaction is visible iff its account is. Anything else is reported as 404, never
403, so ids of hidden rows do not leak.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.deps import MemberContext
from app.models import Account, AccountVisibility, Transaction


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
