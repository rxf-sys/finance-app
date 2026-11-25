"""Guess a ``CsvFormat`` for a CSV from an unknown bank by looking at its header and first rows."""

import re
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from typing import Literal

from app.importing._sniff import HEADER_SEARCH_LINES, decode_bytes, dedupe_headers, normalize, read_records
from app.importing.config import ColumnMap, CsvFormat
from app.importing.presets import match_preset

_DELIMITERS: tuple[Literal[";"], Literal["\t"], Literal[","]] = (";", "\t", ",")
_SAMPLE_ROWS = 20

_SYNONYMS: dict[str, list[str]] = {
    "booking_date": ["Buchungstag", "Buchungsdatum", "Buchung", "Datum", "Date", "Booking Date"],
    "value_date": ["Wertstellung", "Valuta", "Valutadatum", "Value Date", "Wertstellung (Valuta)"],
    "amount": ["Betrag", "Betrag (€)", "Umsatz", "Umsatz in EUR", "Amount", "Amount (EUR)"],
    "debit": ["Soll"],
    "credit": ["Haben"],
    "currency": ["Währung", "Waehrung", "Currency"],
    "counterparty_name": [
        "Auftraggeber/Empfänger",
        "Zahlungsempfänger*in",
        "Zahlungspflichtige*r",
        "Beguenstigter/Zahlungspflichtiger",
        "Begünstigter/Zahlungspflichtiger",
        "Name Zahlungsbeteiligter",
        "Empfänger",
        "Payee",
        "Partner Name",
    ],
    "counterparty_iban": [
        "IBAN",
        "Kontonummer/IBAN",
        "IBAN Zahlungsbeteiligter",
        "Account number",
        "Partner Iban",
    ],
    "purpose": ["Verwendungszweck", "Payment reference", "Vorgang/Verwendungszweck"],
    "booking_text": ["Buchungstext", "Umsatzart", "Umsatztyp", "Transaction type", "Transaktionstyp", "Type"],
    "balance": ["Saldo", "Kontostand"],
}
_LOOKUP: dict[str, str] = {normalize(name): field for field, names in _SYNONYMS.items() for name in names}
_MULTI_FIELDS = ("counterparty_name", "counterparty_iban", "purpose")

_DATE_CANDIDATES = [
    "%d.%m.%Y",
    "%d.%m.%y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%y",
]
_GROUPED_DOT = re.compile(r"[0-9]{1,3}(?:\.[0-9]{3})+")


@dataclass(frozen=True)
class SuggestedFormat:
    format: CsvFormat | None
    """``None`` when no header row with a date-like and an amount-like column was found."""
    preset_key: str | None
    headers: list[str]
    header_row: int | None
    confidence: Literal["high", "medium", "low"]
    unmapped_required: list[str]
    unmapped_headers: list[str]


def _map_headers(headers: list[str]) -> dict[str, list[int]]:
    """Assign each header to a field by synonym; a header feeds at most one field."""
    mapping: dict[str, list[int]] = {}
    for position, header in enumerate(headers):
        field = _LOOKUP.get(normalize(header))
        if field is None:
            continue
        slots = mapping.setdefault(field, [])
        if not slots or field in _MULTI_FIELDS:
            slots.append(position)
    return mapping


def _is_header(mapping: dict[str, list[int]]) -> bool:
    has_amount = "amount" in mapping or "debit" in mapping or "credit" in mapping
    return "booking_date" in mapping and has_amount


def _find_header(text: str, delimiter: str) -> tuple[int, list[str], dict[str, list[int]]] | None:
    for position, (_, cells) in enumerate(islice(read_records(text, delimiter, '"'), HEADER_SEARCH_LINES)):
        if not cells:
            continue
        headers = dedupe_headers(cells)
        mapping = _map_headers(headers)
        if _is_header(mapping):
            return position, headers, mapping
    return None


def _sample_rows(text: str, delimiter: str, header_position: int) -> list[list[str]]:
    rows: list[list[str]] = []
    records = islice(read_records(text, delimiter, '"'), header_position + 1, None)
    for _, cells in records:
        if cells is not None and any(c.strip() for c in cells):
            rows.append(cells)
        if len(rows) >= _SAMPLE_ROWS:
            break
    return rows


def _column_samples(rows: list[list[str]], positions: list[int]) -> list[str]:
    values = (row[p].strip() for row in rows for p in positions if p < len(row))
    return [v for v in values if v]


def _try_date(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value, fmt)
    except ValueError:
        return False
    return True


def _infer_date_formats(samples: list[str]) -> list[str] | None:
    """Prefer one format covering every sample; otherwise combine formats greedily."""
    if not samples:
        return None
    for fmt in _DATE_CANDIDATES:
        if all(_try_date(s, fmt) for s in samples):
            return [fmt]
    remaining = set(samples)
    chosen: list[str] = []
    for fmt in _DATE_CANDIDATES:
        covered = {s for s in remaining if _try_date(s, fmt)}
        if covered:
            chosen.append(fmt)
            remaining -= covered
    return chosen if chosen and not remaining else None


def _infer_decimal_separator(samples: list[str]) -> Literal[",", "."]:
    """Vote on definite evidence; a lone ``1.234`` reads as a German thousands group."""
    comma_votes = 0
    dot_votes = 0
    for sample in samples:
        value = "".join(sample.split()).strip("+-€").removeprefix("EUR").removesuffix("EUR").strip("+-")
        if "," in value and "." in value:
            if value.rfind(",") > value.rfind("."):
                comma_votes += 1
            else:
                dot_votes += 1
        elif "," in value:
            comma_votes += 1
        elif "." in value:
            if _GROUPED_DOT.fullmatch(value):
                comma_votes += 1
            else:
                dot_votes += 1
    return "." if dot_votes > comma_votes else ","


def _as_name(headers: list[str], positions: list[int]) -> str | list[str] | None:
    names = [headers[p] for p in positions]
    if not names:
        return None
    return names[0] if len(names) == 1 else names


def _build_columns(headers: list[str], mapping: dict[str, list[int]]) -> ColumnMap:
    def first(field: str) -> str | None:
        positions = mapping.get(field)
        return headers[positions[0]] if positions else None

    amount = first("amount")
    return ColumnMap(
        booking_date=headers[mapping["booking_date"][0]],
        value_date=first("value_date"),
        amount=amount,
        debit=None if amount else first("debit"),
        credit=None if amount else first("credit"),
        currency=first("currency"),
        counterparty_name=_as_name(headers, mapping.get("counterparty_name", [])),
        counterparty_iban=_as_name(headers, mapping.get("counterparty_iban", [])),
        purpose=_as_name(headers, mapping.get("purpose", [])),
        booking_text=first("booking_text"),
        balance=first("balance"),
    )


def suggest_format(data: bytes) -> SuggestedFormat:
    """Suggest a ``CsvFormat`` for an unknown file.

    The header row is the first of the top 30 records containing a date-like and an amount-like
    column. If its headers match a built-in preset, that preset's format is returned.
    """
    text = decode_bytes(data, "auto")

    best: tuple[Literal[";", "\t", ","], int, list[str], dict[str, list[int]]] | None = None
    for delimiter in _DELIMITERS:
        found = _find_header(text, delimiter)
        if found is not None and (best is None or len(found[2]) > len(best[3])):
            best = (delimiter, *found)
    if best is None:
        return SuggestedFormat(
            format=None,
            preset_key=None,
            headers=[],
            header_row=None,
            confidence="low",
            unmapped_required=["booking_date", "amount"],
            unmapped_headers=[],
        )

    delimiter, header_position, headers, mapping = best
    mapped = {p for positions in mapping.values() for p in positions}
    unmapped_headers = [h for p, h in enumerate(headers) if p not in mapped and h]

    preset = match_preset(headers)
    if preset is not None and preset.format.delimiter == delimiter:
        return SuggestedFormat(
            format=preset.format,
            preset_key=preset.key,
            headers=headers,
            header_row=header_position,
            confidence="high",
            unmapped_required=[],
            unmapped_headers=unmapped_headers,
        )

    rows = _sample_rows(text, delimiter, header_position)
    date_positions = mapping["booking_date"] + mapping.get("value_date", [])
    date_formats = _infer_date_formats(_column_samples(rows, date_positions))
    amount_positions = mapping.get("amount") or (mapping.get("debit", []) + mapping.get("credit", []))
    decimal = _infer_decimal_separator(_column_samples(rows, amount_positions))

    unmapped_required = [] if date_formats else ["date_format"]
    fmt = CsvFormat(
        encoding="auto",
        delimiter=delimiter,
        header_row=header_position,
        date_format=date_formats or "%d.%m.%Y",
        decimal_separator=decimal,
        thousands_separator="." if decimal == "," else ",",
        columns=_build_columns(headers, mapping),
    )
    return SuggestedFormat(
        format=fmt,
        preset_key=None,
        headers=headers,
        header_row=header_position,
        confidence="low" if unmapped_required else "medium",
        unmapped_required=unmapped_required,
        unmapped_headers=unmapped_headers,
    )
