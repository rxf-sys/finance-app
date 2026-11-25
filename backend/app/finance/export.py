"""Transaction export to CSV and XLSX (German headers, spreadsheet-safe text cells).

Rows are built once (`build_rows`) and rendered by `render_csv` or `render_xlsx`. Visibility is
decided by the caller through `visible_transaction_clause`; nothing here reads other households.
Free text that a spreadsheet could interpret as a formula gets a leading single quote.
"""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, selectinload

from app.deps import MemberContext
from app.finance.access import visible_transaction_clause
from app.models import Category, CategoryKind, Transaction

MAX_EXPORT_ROWS = 100_000
CATEGORY_SEPARATOR = " \u203a "  # single right-pointing angle quote

HEADERS = (
    "Buchungsdatum",
    "Wertstellung",
    "Konto",
    "Betrag",
    "Währung",
    "Gegenpartei",
    "IBAN Gegenpartei",
    "Verwendungszweck",
    "Buchungstext",
    "Kategorie",
    "Tags",
    "Notiz",
    "Umbuchung",
)
_WIDTHS = (14, 14, 22, 14, 9, 28, 26, 50, 18, 28, 20, 30, 11)
_AMOUNT_COLUMN = 3  # zero-based index of "Betrag"
_DATE_COLUMNS = (0, 1)
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
XLSX_DATE_FORMAT = "DD.MM.YYYY"
XLSX_AMOUNT_FORMAT = '#,##0.00 "€"'

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TooManyRowsError(Exception):
    def __init__(self, count: int) -> None:
        super().__init__(f"{count} transactions match; the export is limited to {MAX_EXPORT_ROWS}")
        self.count = count


@dataclass(frozen=True)
class ExportRow:
    booking_date: date
    value_date: date | None
    account: str
    amount_cents: int
    currency: str
    counterparty: str
    counterparty_iban: str
    purpose: str
    booking_text: str
    category: str
    tags: str
    note: str
    transfer: bool


def escape_text(value: str) -> str:
    """Neutralize spreadsheet formulas: prefix a single quote when the text starts dangerously."""
    if value.startswith(_DANGEROUS_PREFIXES):
        return "'" + value
    return value


def format_date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def format_amount(cents: int) -> str:
    """Decimal comma, no thousands separator: -123456 -> '-1234,56'."""
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole},{fraction:02d}"


def _category_names(db: Session, member: MemberContext) -> dict[uuid.UUID, tuple[str, CategoryKind]]:
    categories = {
        c.id: c for c in db.scalars(select(Category).where(Category.household_id == member.household.id))
    }
    names: dict[uuid.UUID, tuple[str, CategoryKind]] = {}
    for category in categories.values():
        parent = categories.get(category.parent_id) if category.parent_id else None
        label = f"{parent.name}{CATEGORY_SEPARATOR}{category.name}" if parent else category.name
        names[category.id] = (label, category.kind)
    return names


def _filters(
    member: MemberContext, date_from: date | None, date_to: date | None, account_id: uuid.UUID | None
) -> list[ColumnElement[bool]]:
    clauses = [visible_transaction_clause(member)]
    if date_from is not None:
        clauses.append(Transaction.booking_date >= date_from)
    if date_to is not None:
        clauses.append(Transaction.booking_date <= date_to)
    if account_id is not None:
        clauses.append(Transaction.account_id == account_id)
    return clauses


def _row(
    tx: Transaction,
    amount_cents: int,
    category: tuple[str, CategoryKind] | None,
    note: str,
) -> ExportRow:
    label, kind = category or ("", None)
    return ExportRow(
        booking_date=tx.booking_date,
        value_date=tx.value_date,
        account=tx.account.name,
        amount_cents=amount_cents,
        currency=tx.currency,
        counterparty=tx.counterparty_name or "",
        counterparty_iban=tx.counterparty_iban or "",
        purpose=tx.purpose or "",
        booking_text=tx.booking_text or "",
        category=label,
        tags=", ".join(t.name for t in tx.tags),
        note=note,
        transfer=tx.transfer_peer_id is not None or kind is CategoryKind.TRANSFER,
    )


def build_rows(
    db: Session,
    member: MemberContext,
    date_from: date | None,
    date_to: date | None,
    account_id: uuid.UUID | None,
) -> list[ExportRow]:
    """Export rows, one per transaction or per split, for the transactions the member may see.

    Raises `TooManyRowsError` when more than `MAX_EXPORT_ROWS` transactions match.
    """
    filters = _filters(member, date_from, date_to, account_id)
    total = int(db.scalar(select(func.count()).select_from(Transaction).where(*filters)) or 0)
    if total > MAX_EXPORT_ROWS:
        raise TooManyRowsError(total)
    transactions = db.scalars(
        select(Transaction)
        .where(*filters)
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.splits),
            selectinload(Transaction.tags),
        )
        .order_by(Transaction.booking_date, Transaction.created_at, Transaction.id)
    )
    names = _category_names(db, member)
    rows: list[ExportRow] = []
    for tx in transactions:
        if tx.splits:
            for split in tx.splits:
                category = names.get(split.category_id) if split.category_id else None
                note = " | ".join(part for part in (tx.note, split.note) if part)
                rows.append(_row(tx, split.amount_cents, category, note))
        else:
            category = names.get(tx.category_id) if tx.category_id else None
            rows.append(_row(tx, tx.amount_cents, category, tx.note or ""))
    return rows


def _text_fields(row: ExportRow) -> list[str]:
    """The text columns in header order, already escaped; the amount slot is left empty."""
    return [
        "",  # booking date
        "",  # value date
        escape_text(row.account),
        "",  # amount
        escape_text(row.currency),
        escape_text(row.counterparty),
        escape_text(row.counterparty_iban),
        escape_text(row.purpose),
        escape_text(row.booking_text),
        escape_text(row.category),
        escape_text(row.tags),
        escape_text(row.note),
        "ja" if row.transfer else "nein",
    ]


def render_csv(rows: list[ExportRow]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(HEADERS)
    for row in rows:
        fields = _text_fields(row)
        fields[0] = format_date(row.booking_date)
        fields[1] = format_date(row.value_date)
        fields[_AMOUNT_COLUMN] = format_amount(row.amount_cents)  # the only unescaped column
        writer.writerow(fields)
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def render_xlsx(rows: list[ExportRow]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Buchungen")
    sheet.freeze_panes = "A2"
    for index, width in enumerate(_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    bold = Font(bold=True)
    header_cells = []
    for title in HEADERS:
        header = WriteOnlyCell(sheet, value=title)
        header.font = bold
        header_cells.append(header)
    sheet.append(header_cells)
    for row in rows:
        cells: list[WriteOnlyCell] = []
        for index, text in enumerate(_text_fields(row)):
            cell = WriteOnlyCell(sheet)
            if index in _DATE_COLUMNS:
                day = row.booking_date if index == 0 else row.value_date
                cell.value = day
                cell.number_format = XLSX_DATE_FORMAT
            elif index == _AMOUNT_COLUMN:
                cell.value = Decimal(row.amount_cents).scaleb(-2)  # exact; the ledger itself stays in cents
                cell.number_format = XLSX_AMOUNT_FORMAT
            else:
                cell.value = text
                cell.data_type = "s"  # never let openpyxl read a leading "=" as a formula
            cells.append(cell)
        sheet.append(cells)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{len(rows) + 1}"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
