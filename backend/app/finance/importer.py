"""Previewing and committing CSV imports: parsing, deduplication, categorization and transfers.

Error messages that reach the client are static; cell contents never appear in them.
"""

import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from itertools import islice

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import MemberContext
from app.finance.dedupe import compute_dedupe_hash
from app.finance.normalize import normalize_text
from app.finance.rules import apply_rules, load_rules, matches
from app.finance.transfers import detect_transfers
from app.importing import CsvFormat, ParsedRow, ParseResult, RowError, parse
from app.importing._sniff import decode_bytes, read_records
from app.models import Account, Category, ImportRun, ImportStatus, Transaction
from app.models.base import utcnow

PREVIEW_ROWS = 100
PREVIEW_ERRORS = 50
HASH_CHUNK = 1000

CURRENCY_MISMATCH = "currency differs from account currency"


@dataclass(frozen=True)
class PreviewRow:
    line_no: int
    booking_date: date
    amount_cents: int
    currency: str
    counterparty_name: str | None
    purpose: str
    is_duplicate: bool
    suggested_category_id: uuid.UUID | None = None
    suggested_category_name: str | None = None


@dataclass
class ImportPreview:
    rows_total: int
    rows_new: int
    rows_duplicate: int
    rows_skipped: int
    errors_total: int
    rows: list[PreviewRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


@dataclass
class _Plan:
    rows: list[tuple[ParsedRow, str]]  # importable rows with their dedupe hash
    duplicates: set[str]
    errors: list[RowError]
    skipped: int  # footers, unparsable rows and currency mismatches
    total: int


def _parse_file(data: bytes, fmt: CsvFormat) -> ParseResult:
    try:
        return parse(data, fmt)
    except ValueError as exc:  # file-level problem; the parser's messages are static
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _hashes(account: Account, rows: Sequence[ParsedRow]) -> list[str]:
    seen: Counter[tuple[date, int, str, str]] = Counter()
    hashes: list[str] = []
    for row in rows:
        key = (row.booking_date, row.amount_cents, row.counterparty_iban or "", normalize_text(row.purpose))
        hashes.append(
            compute_dedupe_hash(
                account.id,
                row.booking_date,
                row.amount_cents,
                row.counterparty_iban,
                row.purpose,
                seen[key],
            )
        )
        seen[key] += 1
    return hashes


def _chunks(items: Sequence[str]) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), HASH_CHUNK):
        yield items[start : start + HASH_CHUNK]


def _existing_hashes(db: Session, account: Account, hashes: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for chunk in _chunks(hashes):
        found.update(
            db.scalars(
                select(Transaction.dedupe_hash).where(
                    Transaction.account_id == account.id, Transaction.dedupe_hash.in_(chunk)
                )
            )
        )
    return found


def _plan(db: Session, account: Account, data: bytes, fmt: CsvFormat) -> _Plan:
    parsed = _parse_file(data, fmt)
    errors = list(parsed.errors)
    importable: list[ParsedRow] = []
    mismatches = 0
    for row in parsed.rows:
        if row.currency.upper() != account.currency.upper():
            mismatches += 1
            errors.append(RowError(row.line_no, CURRENCY_MISMATCH))
        else:
            importable.append(row)
    errors.sort(key=lambda e: e.line_no)
    hashes = _hashes(account, importable)
    return _Plan(
        rows=list(zip(importable, hashes, strict=True)),
        duplicates=_existing_hashes(db, account, hashes),
        errors=errors,
        skipped=parsed.skipped + len(parsed.errors) + mismatches,
        total=len(parsed.rows) + len(parsed.errors) + parsed.skipped,
    )


def _new_transaction(
    member: MemberContext, account: Account, row: ParsedRow, dedupe_hash: str, run_id: uuid.UUID | None
) -> Transaction:
    return Transaction(
        id=uuid.uuid4(),
        household_id=member.household.id,
        account_id=account.id,
        booking_date=row.booking_date,
        value_date=row.value_date,
        amount_cents=row.amount_cents,
        currency=row.currency,
        counterparty_name=row.counterparty_name,
        counterparty_iban=row.counterparty_iban,
        purpose=row.purpose or None,
        booking_text=row.booking_text,
        raw=row.raw,
        dedupe_hash=dedupe_hash,
        import_run_id=run_id,
        splits=[],  # initialised so the rules engine does not lazy-load per row
        tags=[],
    )


def preview_import(
    db: Session, member: MemberContext, account: Account, data: bytes, fmt: CsvFormat
) -> ImportPreview:
    plan = _plan(db, account, data, fmt)
    rules = load_rules(db, member.household.id)
    out_rows: list[PreviewRow] = []
    for row, dedupe_hash in plan.rows[:PREVIEW_ROWS]:
        is_duplicate = dedupe_hash in plan.duplicates
        category_id: uuid.UUID | None = None
        if not is_duplicate:
            probe = _new_transaction(member, account, row, dedupe_hash, None)
            category_id = next((rule.category_id for rule, cond in rules if matches(cond, probe)), None)
        out_rows.append(
            PreviewRow(
                line_no=row.line_no,
                booking_date=row.booking_date,
                amount_cents=row.amount_cents,
                currency=row.currency,
                counterparty_name=row.counterparty_name,
                purpose=row.purpose,
                is_duplicate=is_duplicate,
                suggested_category_id=category_id,
            )
        )
    wanted = {r.suggested_category_id for r in out_rows if r.suggested_category_id is not None}
    if wanted:
        names = {
            cid: name
            for cid, name in db.execute(
                select(Category.id, Category.name).where(
                    Category.id.in_(wanted), Category.household_id == member.household.id
                )
            )
        }
        out_rows = [
            replace(r, suggested_category_name=names.get(r.suggested_category_id))
            if r.suggested_category_id is not None
            else r
            for r in out_rows
        ]
    duplicates = sum(1 for _, h in plan.rows if h in plan.duplicates)
    return ImportPreview(
        rows_total=plan.total,
        rows_new=len(plan.rows) - duplicates,
        rows_duplicate=duplicates,
        rows_skipped=plan.skipped,
        errors_total=len(plan.errors),
        rows=out_rows,
        errors=plan.errors[:PREVIEW_ERRORS],
    )


def run_import(
    db: Session,
    member: MemberContext,
    account: Account,
    data: bytes,
    fmt: CsvFormat,
    profile_name: str,
    filename: str | None,
) -> ImportRun:
    """Insert the new rows atomically. A concurrent import of the same rows gives 409."""
    plan = _plan(db, account, data, fmt)
    new_rows = [(row, h) for row, h in plan.rows if h not in plan.duplicates]
    now = utcnow()
    run = ImportRun(
        id=uuid.uuid4(),
        household_id=member.household.id,
        account_id=account.id,
        user_id=member.user.id,
        filename=filename,
        profile_name=profile_name,
        status=ImportStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        rows_total=plan.total,
        rows_new=len(new_rows),
        rows_duplicate=len(plan.rows) - len(new_rows),
        rows_skipped=plan.skipped,
    )
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
            transactions = [_new_transaction(member, account, row, h, run.id) for row, h in new_rows]
            db.add_all(transactions)
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Import conflicts with a concurrent import, please retry"
        ) from exc
    apply_rules(db, member.household.id, transactions)
    detect_transfers(db, member.household.id, transactions, member=member)
    db.flush()
    return run


def sample_rows(data: bytes, header_row: int, delimiter: str, limit: int = 5) -> list[list[str]]:
    """The first non-empty records after the header, as strings, for a column mapping UI."""
    records = islice(read_records(decode_bytes(data, "auto"), delimiter, '"'), header_row + 1, None)
    rows: list[list[str]] = []
    for _, cells in records:
        if cells is not None and any(c.strip() for c in cells):
            rows.append([c.strip()[:200] for c in cells])
        if len(rows) >= limit:
            break
    return rows
