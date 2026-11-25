"""Declarative description of a bank CSV layout."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type NameOrNames = str | list[str]


def as_list(value: NameOrNames | None) -> list[str]:
    """Normalise a ``str | list[str] | None`` column setting to a list."""
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


class ColumnMap(BaseModel):
    """Which CSV column feeds which field. Values are header names (matched loosely)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    booking_date: str
    value_date: str | None = None
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    sign_column: str | None = None
    debit_markers: list[str] = Field(default_factory=list)
    currency: str | None = None
    counterparty_name: NameOrNames | None = None
    counterparty_iban: NameOrNames | None = None
    purpose: NameOrNames | None = None
    booking_text: str | None = None
    balance: str | None = None

    @model_validator(mode="after")
    def _check_amount_source(self) -> Self:
        has_amount = self.amount is not None
        has_split = self.debit is not None or self.credit is not None
        if has_amount == has_split:
            raise ValueError("set exactly one of amount or debit/credit")
        if bool(self.debit_markers) != (self.sign_column is not None):
            raise ValueError("sign_column and debit_markers must be set together")
        if self.sign_column is not None and not has_amount:
            raise ValueError("sign_column requires amount")
        return self


class CsvFormat(BaseModel):
    """File-level settings plus the column map."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    encoding: Literal["auto", "utf-8", "utf-8-sig", "cp1252", "iso-8859-1"] = "auto"
    delimiter: Literal[";", ",", "\t"] = ";"
    quotechar: str = Field(default='"', min_length=1, max_length=1)
    header_row: int | None = Field(default=None, ge=0)
    """0-based index of the header record; ``None`` auto-detects it."""
    date_format: str | list[str] = "%d.%m.%Y"
    decimal_separator: Literal[",", "."] = ","
    thousands_separator: Literal[".", ",", " ", ""] = "."
    columns: ColumnMap

    @field_validator("date_format")
    @classmethod
    def _check_date_format(cls, value: str | list[str]) -> str | list[str]:
        formats = [value] if isinstance(value, str) else value
        if not formats or any("%" not in fmt for fmt in formats):
            raise ValueError("date_format needs at least one strptime format")
        return value

    @model_validator(mode="after")
    def _check_separators(self) -> Self:
        if self.decimal_separator == self.thousands_separator:
            raise ValueError("decimal and thousands separator must differ")
        return self

    @property
    def date_formats(self) -> list[str]:
        return [self.date_format] if isinstance(self.date_format, str) else list(self.date_format)
