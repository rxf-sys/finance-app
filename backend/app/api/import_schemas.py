"""Request and response models for CSV imports."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.importing import CsvFormat
from app.models import ImportStatus

ProfileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Filename = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class PresetOut(BaseModel):
    key: str
    label: str
    format: CsvFormat


class AnalyzeRequest(BaseModel):
    content_base64: str
    filename: Filename


class AnalyzeOut(BaseModel):
    format: CsvFormat | None
    preset_key: str | None
    headers: list[str]
    header_row: int | None
    confidence: Literal["high", "medium", "low"]
    unmapped_required: list[str]
    unmapped_headers: list[str]
    sample_rows: list[list[str]]


class PreviewRequest(BaseModel):
    account_id: uuid.UUID
    content_base64: str
    filename: Filename
    format: CsvFormat


class ImportRequest(PreviewRequest):
    profile_name: ProfileName | None = None


class RowErrorOut(BaseModel):
    line_no: int
    message: str


class PreviewRowOut(BaseModel):
    line_no: int
    booking_date: date
    amount_cents: int
    currency: str
    counterparty_name: str | None
    purpose: str
    is_duplicate: bool
    suggested_category_id: uuid.UUID | None
    suggested_category_name: str | None


class PreviewOut(BaseModel):
    rows_total: int
    rows_new: int
    rows_duplicate: int
    rows_skipped: int
    errors_total: int
    rows: list[PreviewRowOut]
    errors: list[RowErrorOut]


class ImportRunOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    user_id: uuid.UUID | None
    filename: str | None
    profile_name: str
    status: ImportStatus
    started_at: datetime
    finished_at: datetime | None
    rows_total: int
    rows_new: int
    rows_duplicate: int
    rows_skipped: int
    error: str | None


class ProfileCreate(BaseModel):
    name: ProfileName
    format: CsvFormat


class ProfileUpdate(BaseModel):
    name: ProfileName | None = None
    format: CsvFormat | None = None


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    format: CsvFormat
    created_at: datetime
