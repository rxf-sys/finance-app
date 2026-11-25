import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance import export as export_module
from app.finance.contracts import today_berlin
from app.models import AccountVisibility, AuditLog, Tag, TransactionSplit
from tests.helpers import World, make_account, make_category, make_tx

URL = "/api/export/transactions"
ARROW = f" {chr(0x203A)} "


def _csv_rows(response: Any) -> list[list[str]]:
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:], newline=""), delimiter=";"))


def test_csv_content_and_headers(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, "Giro")
    hid = account.household_id
    food = make_category(db, hid, "Essen")
    eating = make_category(db, hid, "Restaurant", parent=food)
    tx = make_tx(
        db,
        account,
        -123_456,
        date(2026, 3, 5),
        counterparty_name='Café; "Süß"',
        counterparty_iban="DE89370400440532013000",
        purpose="Zeile 1\nZeile 2",
        booking_text="Lastschrift",
        category=eating,
    )
    tx.value_date = date(2026, 3, 6)
    tx.note = "Notiz"
    tag_b, tag_a = (
        Tag(id=uuid.uuid4(), household_id=hid, name="b"),
        Tag(id=uuid.uuid4(), household_id=hid, name="a"),
    )
    db.add_all([tag_a, tag_b])
    db.flush()
    tx.tags.extend([tag_b, tag_a])
    make_tx(db, account, 500_000, date(2026, 3, 1), category=food)
    db.commit()

    response = world.owner.get(URL)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="buchungen-{today_berlin().isoformat()}.csv"'
    )
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in response.content
    rows = _csv_rows(response)
    assert rows[0] == [
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
    ]
    # Ordered by booking date.
    assert rows[1][0] == "01.03.2026"
    assert rows[1][3] == "5000,00"
    assert rows[1][9] == "Essen"
    assert rows[2] == [
        "05.03.2026",
        "06.03.2026",
        "Giro",
        "-1234,56",
        "EUR",
        'Café; "Süß"',
        "DE89370400440532013000",
        "Zeile 1\nZeile 2",
        "Lastschrift",
        f"Essen{ARROW}Restaurant",
        "a, b",
        "Notiz",
        "nein",
    ]


def test_filters_and_audit(world: World, db: Session) -> None:
    first = make_account(db, world.owner_user, "Eins")
    second = make_account(db, world.owner_user, "Zwei")
    make_tx(db, first, -100, date(2026, 1, 10))
    make_tx(db, first, -200, date(2026, 2, 10))
    make_tx(db, second, -300, date(2026, 2, 11))

    rows = _csv_rows(world.owner.get(URL, params={"from": "2026-02-01", "to": "2026-02-10"}))
    assert [r[3] for r in rows[1:]] == ["-2,00"]
    rows = _csv_rows(world.owner.get(URL, params={"account_id": str(second.id)}))
    assert [r[3] for r in rows[1:]] == ["-3,00"]
    assert world.owner.get(URL, params={"from": "2026-03-01", "to": "2026-02-01"}).status_code == 422
    assert world.owner.get(URL, params={"format": "pdf"}).status_code == 422
    assert world.owner.get(URL, params={"account_id": str(uuid.uuid4())}).status_code == 404

    audit = db.scalars(select(AuditLog).where(AuditLog.action == "export_transactions")).all()
    assert len(audit) == 2
    assert audit[0].details == {"format": "csv", "rows": "1"}
    assert "-2,00" not in str(audit[0].details)


def test_transfer_flag(world: World, db: Session) -> None:
    first = make_account(db, world.owner_user, "Eins")
    second = make_account(db, world.owner_user, "Zwei")
    out = make_tx(db, first, -1000, date(2026, 1, 10))
    inc = make_tx(db, second, 1000, date(2026, 1, 10))
    out.transfer_peer_id, inc.transfer_peer_id = inc.id, out.id
    db.commit()
    assert [r[12] for r in _csv_rows(world.owner.get(URL))[1:]] == ["ja", "ja"]


def test_splits_one_row_each(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    hid = account.household_id
    food = make_category(db, hid, "Essen")
    misc = make_category(db, hid, "Sonstiges")
    tx = make_tx(db, account, -20_000, date(2026, 1, 10), counterparty_name="Markt", purpose="Einkauf")
    tx.note = "Gesamt"
    db.add_all(
        [
            TransactionSplit(
                transaction_id=tx.id, position=0, amount_cents=-8_000, category_id=food.id, note="Obst"
            ),
            TransactionSplit(transaction_id=tx.id, position=1, amount_cents=-12_000, category_id=misc.id),
        ]
    )
    db.commit()
    rows = _csv_rows(world.owner.get(URL))[1:]
    assert [(r[3], r[9], r[11]) for r in rows] == [
        ("-80,00", "Essen", "Gesamt | Obst"),
        ("-120,00", "Sonstiges", "Gesamt"),
    ]
    assert all(r[5] == "Markt" and r[7] == "Einkauf" for r in rows)


DANGEROUS = ["=1+1", "+49 123", "-cmd", "@SUM(A1)", "\tTab", "\rCR"]


def test_csv_formula_injection(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, "=Konto")
    for index, value in enumerate(DANGEROUS):
        tx = make_tx(
            db,
            account,
            -100 - index,
            date(2026, 1, 10 + index),
            counterparty_name=value,
            purpose=value,
            booking_text=value,
        )
        tx.note = value
    db.commit()
    rows = _csv_rows(world.owner.get(URL))[1:]
    assert rows[0][2] == "'=Konto"
    for row, value in zip(rows, DANGEROUS, strict=True):
        assert row[5] == "'" + value
        assert row[7] == "'" + value
        assert row[8] == "'" + value
        assert row[11] == "'" + value
        assert row[3].startswith("-")  # amounts stay plain numbers
    assert not any(cell.startswith(("=", "+", "@", "\t", "\r")) for row in rows for cell in row)


def test_xlsx_values_types_and_layout(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, "Giro")
    category = make_category(db, account.household_id, "Essen")
    tx = make_tx(
        db,
        account,
        -123_456,
        date(2026, 3, 5),
        counterparty_name='=HYPERLINK("http://evil")',
        purpose="-1+1",
        category=category,
    )
    tx.value_date = date(2026, 3, 6)
    db.commit()
    make_tx(db, account, 5, date(2026, 3, 7))

    response = world.owner.get(URL, params={"format": "xlsx"})
    assert response.status_code == 200
    assert response.headers["content-type"] == export_module.XLSX_MEDIA_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('.xlsx"')
    workbook = load_workbook(io.BytesIO(response.content))
    sheet = workbook.active
    assert sheet is not None
    header = [c.value for c in sheet[1]]
    assert header == list(export_module.HEADERS)
    assert all(c.font.bold for c in sheet[1])
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:M3"
    assert sheet.column_dimensions["H"].width and sheet.column_dimensions["H"].width > 20

    row = sheet[2]
    assert row[0].value.date() == date(2026, 3, 5)
    assert row[0].number_format == "DD.MM.YYYY"
    assert row[1].value.date() == date(2026, 3, 6)
    assert isinstance(row[3].value, (int, float))
    assert Decimal(str(row[3].value)) == Decimal("-1234.56")
    assert "€" in row[3].number_format
    assert row[2].value == "Giro"
    assert row[5].value == '\'=HYPERLINK("http://evil")'
    assert row[5].data_type == "s"
    assert row[7].value == "'-1+1"
    assert row[9].value == "Essen"
    assert row[12].value == "nein"
    assert sheet[3][1].value is None


def test_privacy_and_isolation(world: World, db: Session) -> None:
    shared = make_account(db, world.owner_user, "Gemeinsam")
    secret = make_account(db, world.owner_user, "Geheim", AccountVisibility.PRIVATE)
    make_tx(db, shared, -100, date(2026, 1, 10), counterparty_name="sichtbar")
    make_tx(db, secret, -200, date(2026, 1, 11), counterparty_name="versteckt")

    for fmt in ("csv", "xlsx"):
        member = world.member.get(URL, params={"format": fmt})
        assert member.status_code == 200
        assert b"versteckt" not in member.content
        assert world.member.get(URL, params={"format": fmt, "account_id": str(secret.id)}).status_code == 404
        stranger = world.stranger.get(URL, params={"format": fmt})
        assert stranger.status_code == 200
        assert b"sichtbar" not in stranger.content
    assert [r[5] for r in _csv_rows(world.member.get(URL))[1:]] == ["sichtbar"]
    assert len(_csv_rows(world.stranger.get(URL))) == 1
    assert [r[5] for r in _csv_rows(world.owner.get(URL))[1:]] == ["sichtbar", "versteckt"]
    assert world.stranger.get(URL, params={"account_id": str(shared.id)}).status_code == 404


def test_row_limit(world: World, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    account = make_account(db, world.owner_user)
    for day in (1, 2, 3):
        make_tx(db, account, -100, date(2026, 1, day))
    monkeypatch.setattr(export_module, "MAX_EXPORT_ROWS", 2)
    response = world.owner.get(URL)
    assert response.status_code == 422
    assert "Too many transactions" in response.json()["detail"]
    assert world.owner.get(URL, params={"to": "2026-01-02"}).status_code == 200
    assert db.scalars(select(AuditLog).where(AuditLog.action == "export_transactions")).all()
