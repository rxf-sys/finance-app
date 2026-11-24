"""All ORM models, imported here so Alembic sees the full metadata."""

from app.models.audit import AuditLog
from app.models.auth import AuthChallenge, ChallengePurpose, UserSession, WebAuthnCredential
from app.models.base import Base
from app.models.finance import (
    Account,
    AccountKind,
    AccountVisibility,
    Category,
    CategoryKind,
    CategoryRule,
    CategorySource,
    ImportProfile,
    ImportRun,
    ImportStatus,
    RuleSource,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionTag,
)
from app.models.identity import Household, HouseholdMember, HouseholdRole, Invite, User

__all__ = [
    "Account",
    "AccountKind",
    "AccountVisibility",
    "AuditLog",
    "AuthChallenge",
    "Base",
    "Category",
    "CategoryKind",
    "CategoryRule",
    "CategorySource",
    "ChallengePurpose",
    "Household",
    "HouseholdMember",
    "HouseholdRole",
    "ImportProfile",
    "ImportRun",
    "ImportStatus",
    "Invite",
    "RuleSource",
    "Tag",
    "Transaction",
    "TransactionSplit",
    "TransactionTag",
    "User",
    "UserSession",
    "WebAuthnCredential",
]
