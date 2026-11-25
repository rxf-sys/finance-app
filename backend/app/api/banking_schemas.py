"""Request and response models for /bank-connections."""

import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import AccountKind, AccountVisibility, BankConnectionStatus, SyncStatus

CountryCode = Field(pattern=r"^[A-Z]{2}$")


class AspspOut(BaseModel):
    name: str
    country: str
    logo: str | None = None


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspsp_name: str = Field(min_length=1, max_length=100)
    country: str = CountryCode


class ConnectionStarted(BaseModel):
    connection_id: uuid.UUID
    redirect_url_to_bank: str


class LinkedAccountOut(BaseModel):
    account_id: uuid.UUID
    name: str
    provider_account_uid: str | None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    aspsp_name: str
    country: str
    status: BankConnectionStatus
    consent_valid_until: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    accounts: list[LinkedAccountOut]


class ProviderAccountOut(BaseModel):
    uid: str
    iban_masked: str | None
    name: str | None
    currency: str | None
    linked_account_id: uuid.UUID | None


class NewAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    kind: AccountKind = AccountKind.GIRO
    visibility: AccountVisibility = AccountVisibility.SHARED


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_account_uid: str = Field(min_length=1, max_length=100)
    account_id: uuid.UUID | None = None
    new_account: NewAccount | None = None
    sync_from: date | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        if (self.account_id is None) == (self.new_account is None):
            raise ValueError("Provide exactly one of account_id and new_account")
        return self


class LinkOut(BaseModel):
    account_id: uuid.UUID
    sync_from: date


class SyncQueued(BaseModel):
    status: str = "queued"


class SyncRunOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID | None
    status: SyncStatus
    started_at: datetime
    finished_at: datetime | None
    rows_new: int
    rows_duplicate: int
    error: str | None
