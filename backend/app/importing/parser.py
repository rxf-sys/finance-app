"""Turn bank CSV bytes into typed rows. Pure: no database, no I/O.

Row-level problems never raise; they become ``RowError`` entries. Error messages are static
English strings and never echo cell contents (transaction data must not end up in logs).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import islice

from app.importing._sniff import (
    HEADER_SEARCH_LINES,
    decode_bytes,
    dedupe_headers,
    normalize,
    read_records,
)
from app.importing.config import ColumnMap, CsvFormat, as_list
from app.importing.presets import find_preset

MAX_ROWS = 100_000
_MAX_INTEGER_DIGITS = 15
_CURRENCY_TOKEN = re.compile(r"^(?:€|EUR)|(?:€|EUR)$", re.IGNORECASE)
_DIGITS = re.compile(r"[0-9]+")
_ALPHA_DIRECTIVES = ("%b", "%B", "%a", "%A")


@dataclass(frozen=True)
class ParsedRow:
    line_no: int
    booking_date: date
    value_date: date | None
    amount_cents: int
    currency: str = "EUR"
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    purpose: str = ""
    booking_text: str | None = None
    balance_cents: int | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RowError:
    line_no: int
    message: str


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    skipped: int = 0


def parse_amount_cents(text: str, decimal_separator: str = ",", thousands_separator: str = ".") -> int:
    """Parse a localised money string to exact integer cents.

    Accepts ``1.234,56``, ``-12,30``, ``12,30-``, ``+5,00``, ``12,30 €``, ``EUR 12,30`` and
    non-breaking spaces. More than two significant decimals, misplaced thousands separators
    and garbage raise ``ValueError``.
    """
    value = "".join(text.replace("\u2212", "-").split())
    value = _CURRENCY_TOKEN.sub("", value, count=1)
    value = _CURRENCY_TOKEN.sub("", value, count=1)

    negative = False
    leading_sign = value.startswith(("+", "-"))
    if leading_sign:
        negative = value[0] == "-"
        value = value[1:]
    if value.endswith(("+", "-")):
        if leading_sign:
            raise ValueError("invalid amount")
        negative = value[-1] == "-"
        value = value[:-1]

    integer_part, separator, fraction = value.partition(decimal_separator)
    if (separator and not fraction) or not _DIGITS.fullmatch(fraction or "0"):
        raise ValueError("invalid amount")
    if thousands_separator.strip() and thousands_separator in integer_part:
        grouped = rf"[0-9]{{1,3}}(?:{re.escape(thousands_separator)}[0-9]{{3}})+"
        if not re.fullmatch(grouped, integer_part):
            raise ValueError("invalid amount")
        integer_part = integer_part.replace(thousands_separator, "")
    if not _DIGITS.fullmatch(integer_part or "0") or (not integer_part and not fraction):
        raise ValueError("invalid amount")
    if len(integer_part) > _MAX_INTEGER_DIGITS:
        raise ValueError("amount out of range")

    cents = Decimal(f"{integer_part or '0'}.{fraction or '0'}").scaleb(2)
    if cents != cents.to_integral_value():
        raise ValueError("invalid amount: more than 2 decimals")
    return -int(cents) if negative else int(cents)


def _parse_date(text: str, formats: list[str]) -> date | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class _Columns:
    """Column positions resolved against the actual header row."""

    booking_date: int
    value_date: int | None
    amount: int | None
    debit: int | None
    credit: int | None
    sign: int | None
    currency: int | None
    counterparty_name: list[int]
    counterparty_iban: list[int]
    purpose: list[int]
    booking_text: int | None
    balance: int | None


def _resolve(headers: list[str], columns: ColumnMap) -> _Columns:
    index: dict[str, int] = {}
    for position, header in enumerate(headers):
        index.setdefault(normalize(header), position)

    def one(name: str | None) -> int | None:
        return None if name is None else index.get(normalize(name))

    def many(names: str | list[str] | None) -> list[int]:
        found = (index.get(normalize(name)) for name in as_list(names))
        return [position for position in found if position is not None]

    booking_date = one(columns.booking_date)
    if booking_date is None:
        raise ValueError("booking date column not found")
    resolved = _Columns(
        booking_date=booking_date,
        value_date=one(columns.value_date),
        amount=one(columns.amount),
        debit=one(columns.debit),
        credit=one(columns.credit),
        sign=one(columns.sign_column),
        currency=one(columns.currency),
        counterparty_name=many(columns.counterparty_name),
        counterparty_iban=many(columns.counterparty_iban),
        purpose=many(columns.purpose),
        booking_text=one(columns.booking_text),
        balance=one(columns.balance),
    )
    if columns.amount is not None and resolved.amount is None:
        raise ValueError("amount column not found")
    if columns.amount is None and resolved.debit is None and resolved.credit is None:
        raise ValueError("debit/credit columns not found")
    if columns.sign_column is not None and resolved.sign is None:
        raise ValueError("sign column not found")
    return resolved


def _required_headers(columns: ColumnMap) -> set[str]:
    names = [columns.booking_date]
    if columns.amount is not None:
        names.append(columns.amount)
    else:
        names.extend(name for name in (columns.debit, columns.credit) if name is not None)
    return {normalize(name) for name in names}


def _find_header(records: Iterator[tuple[int, list[str] | None]], fmt: CsvFormat) -> tuple[list[str], int]:
    """Consume records up to and including the header; return its cells and line number."""
    required = _required_headers(fmt.columns)
    for position, (line_no, cells) in enumerate(islice(records, _header_limit(fmt))):
        if fmt.header_row is not None:
            if position < fmt.header_row:
                continue
            if cells is None:
                raise ValueError("malformed header row")
            return dedupe_headers(cells), line_no
        if cells is None:
            continue
        headers = dedupe_headers(cells)
        if required <= {normalize(h) for h in headers}:
            return headers, line_no
    raise ValueError("header row not found")


def _header_limit(fmt: CsvFormat) -> int:
    return HEADER_SEARCH_LINES if fmt.header_row is None else fmt.header_row + 1


def _cell(cells: list[str], index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return cells[index].strip()


def _first_non_empty(cells: list[str], indexes: list[int]) -> str:
    return next((value for i in indexes if (value := _cell(cells, i))), "")


def _amount(cells: list[str], cols: _Columns, fmt: CsvFormat, markers: frozenset[str]) -> int:
    decimal, thousands = fmt.decimal_separator, fmt.thousands_separator
    if cols.amount is not None:
        raw = _cell(cells, cols.amount)
        if not raw:
            raise ValueError("missing amount")
        value = parse_amount_cents(raw, decimal, thousands)
        marker = _cell(cells, cols.sign).upper()
        if marker:
            return -abs(value) if marker in markers else abs(value)
        return value
    total = 0
    found = False
    for index, sign in ((cols.credit, 1), (cols.debit, -1)):
        raw = _cell(cells, index)
        if raw:
            total += sign * abs(parse_amount_cents(raw, decimal, thousands))
            found = True
    if not found:
        raise ValueError("missing amount")
    return total


def _is_footer(raw_date: str, fmt: CsvFormat) -> bool:
    """A row whose date cell is empty or a text label (``Summe``, ``Kontostand``) is not a booking."""
    if not raw_date:
        return True
    allows_letters = any(d in f for f in fmt.date_formats for d in _ALPHA_DIRECTIVES)
    return not allows_letters and any(ch.isalpha() for ch in raw_date)


def _build_row(
    line_no: int,
    cells: list[str],
    headers: list[str],
    cols: _Columns,
    fmt: CsvFormat,
    markers: frozenset[str],
    booking_date: date,
) -> ParsedRow:
    formats = fmt.date_formats
    value_date: date | None = None
    raw_value_date = _cell(cells, cols.value_date)
    if raw_value_date:
        value_date = _parse_date(raw_value_date, formats)
        if value_date is None:
            raise ValueError("invalid value date")

    amount_cents = _amount(cells, cols, fmt, markers)

    currency = _cell(cells, cols.currency).upper() or "EUR"
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("invalid currency")

    raw_balance = _cell(cells, cols.balance)
    balance_cents = (
        parse_amount_cents(raw_balance, fmt.decimal_separator, fmt.thousands_separator)
        if raw_balance
        else None
    )

    iban = "".join(_first_non_empty(cells, cols.counterparty_iban).split()).upper()
    purpose = " ".join(v for i in cols.purpose if (v := _cell(cells, i)))
    return ParsedRow(
        line_no=line_no,
        booking_date=booking_date,
        value_date=value_date,
        amount_cents=amount_cents,
        currency=currency,
        counterparty_name=_first_non_empty(cells, cols.counterparty_name) or None,
        counterparty_iban=iban or None,
        purpose=purpose,
        booking_text=_cell(cells, cols.booking_text) or None,
        balance_cents=balance_cents,
        raw={header: _cell(cells, i) for i, header in enumerate(headers)},
    )


def parse(data: bytes, fmt: CsvFormat) -> ParseResult:
    """Parse a bank CSV with an explicit format.

    Raises ``ValueError`` for file-level problems (undecodable bytes, no header row, a configured
    required column missing, more than ``MAX_ROWS`` data rows). Row-level problems are collected
    in ``ParseResult.errors`` instead.
    """
    text = decode_bytes(data, fmt.encoding)
    records = read_records(text, fmt.delimiter, fmt.quotechar)
    headers, _ = _find_header(records, fmt)
    cols = _resolve(headers, fmt.columns)
    markers = frozenset(m.strip().upper() for m in fmt.columns.debit_markers)
    formats = fmt.date_formats

    result = ParseResult()
    count = 0
    for line_no, cells in records:
        if cells is not None and not any(c.strip() for c in cells):
            continue
        count += 1
        if count > MAX_ROWS:
            raise ValueError("too many rows")
        if cells is None:
            result.errors.append(RowError(line_no, "malformed CSV record"))
            continue
        raw_date = _cell(cells, cols.booking_date)
        if _is_footer(raw_date, fmt):
            result.skipped += 1
            continue
        booking_date = _parse_date(raw_date, formats)
        if booking_date is None:
            result.errors.append(RowError(line_no, "invalid booking date"))
            continue
        try:
            row = _build_row(line_no, cells, headers, cols, fmt, markers, booking_date)
        except ValueError as exc:
            result.errors.append(RowError(line_no, str(exc)))
        else:
            result.rows.append(row)
    return result


def detect_preset(data: bytes) -> str | None:
    """Return the key of the built-in preset whose signature headers appear in the file."""
    preset = find_preset(decode_bytes(data, "auto"))
    return None if preset is None else preset.key
