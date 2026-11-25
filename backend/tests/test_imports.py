import base64
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importing import get_preset
from app.models import Account, AccountVisibility, AuditLog, Transaction
from tests.helpers import IBAN_A, IBAN_B, IBAN_EXTERNAL, World, make_account

IMPORTS = "/api/imports"
FORMAT = get_preset("sparkasse_camt").format.model_dump(mode="json")
HEADER = (
    "Auftragskonto;Buchungstag;Valutadatum;Buchungstext;Verwendungszweck;"
    "Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag;Waehrung"
)


def _line(
    day: str,
    amount: str,
    name: str = "Kaffeebar Muster",
    purpose: str = "Kaffee",
    iban: str = "",
    cur: str = "EUR",
) -> str:
    return f"DE00;{day};{day};LASTSCHRIFT;{purpose};{name};{iban};{amount};{cur}"


def _csv(*lines: str) -> bytes:
    return ("\n".join([HEADER, *lines]) + "\n").encode("iso-8859-1")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _body(account: Account, data: bytes, **extra: Any) -> dict[str, Any]:
    return {
        "account_id": str(account.id),
        "content_base64": _b64(data),
        "filename": "umsaetze.csv",
        "format": FORMAT,
        **extra,
    }


def _import(client: TestClient, account: Account, data: bytes) -> dict[str, Any]:
    response = client.post(IMPORTS, json=_body(account, data))
    assert response.status_code == 201, response.text
    run: dict[str, Any] = response.json()
    return run


def _txs(db: Session, account: Account) -> list[Transaction]:
    db.expire_all()
    return list(
        db.scalars(
            select(Transaction)
            .where(Transaction.account_id == account.id)
            .order_by(Transaction.booking_date, Transaction.amount_cents)
        )
    )


def test_full_import_and_reimport(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    data = _csv(_line("02.01.2026", "-3,50"), _line("03.01.2026", "1.200,00", "Arbeitgeber Muster", "Lohn"))
    run = _import(world.owner, account, data)
    assert (run["rows_total"], run["rows_new"], run["rows_duplicate"], run["rows_skipped"]) == (2, 2, 0, 0)
    assert run["status"] == "completed"
    assert run["filename"] == "umsaetze.csv"
    txs = _txs(db, account)
    assert [t.amount_cents for t in txs] == [-350, 120000]
    assert all(str(t.import_run_id) == run["id"] and t.raw for t in txs)

    again = _import(world.owner, account, data)
    assert (again["rows_new"], again["rows_duplicate"]) == (0, 2)
    assert len(_txs(db, account)) == 2


def test_overlapping_file_imports_only_new_rows(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    first = _csv(_line("02.01.2026", "-3,50"), _line("03.01.2026", "-4,00", purpose="Brot"))
    second = _csv(_line("03.01.2026", "-4,00", purpose="Brot"), _line("04.01.2026", "-9,99", purpose="Buch"))
    _import(world.owner, account, first)
    run = _import(world.owner, account, second)
    assert (run["rows_new"], run["rows_duplicate"]) == (1, 1)
    assert len(_txs(db, account)) == 3


def test_identical_rows_in_one_file_are_both_imported(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    data = _csv(_line("02.01.2026", "-2,00"), _line("02.01.2026", "-2,00"))
    assert _import(world.owner, account, data)["rows_new"] == 2
    assert len(_txs(db, account)) == 2
    again = _import(world.owner, account, data)
    assert (again["rows_new"], again["rows_duplicate"]) == (0, 2)


def test_manual_rule_is_applied_on_import(world: World, db: Session) -> None:
    category = world.owner.post("/api/categories", json={"name": "Genuss", "kind": "expense"}).json()
    rule = world.owner.post(
        "/api/rules",
        json={"category_id": category["id"], "conditions": {"counterparty_contains": "kaffeebar"}},
    ).json()
    account = make_account(db, world.owner_user)
    _import(
        world.owner,
        account,
        _csv(_line("02.01.2026", "-3,50"), _line("03.01.2026", "-8,00", "Tankstelle Muster")),
    )
    by_name = {t.counterparty_name: t for t in _txs(db, account)}
    assert str(by_name["Kaffeebar Muster"].category_id) == category["id"]
    assert str(by_name["Kaffeebar Muster"].rule_id) == rule["id"]
    assert by_name["Tankstelle Muster"].category_id is None


def test_transfer_sides_are_paired(world: World, db: Session) -> None:
    a = make_account(db, world.owner_user, "Giro", iban=IBAN_A)
    b = make_account(db, world.owner_user, "Spar", iban=IBAN_B)
    _import(world.owner, a, _csv(_line("02.01.2026", "-100,00", "Spar", "Umbuchung", IBAN_B)))
    _import(world.owner, b, _csv(_line("03.01.2026", "100,00", "Giro", "Umbuchung", IBAN_A)))
    (tx_a,) = _txs(db, a)
    (tx_b,) = _txs(db, b)
    assert tx_a.transfer_peer_id == tx_b.id
    assert tx_b.transfer_peer_id == tx_a.id


def test_currency_mismatch_row_is_skipped(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    data = _csv(_line("02.01.2026", "-3,50"), _line("03.01.2026", "-5,00", cur="USD"))
    preview = world.owner.post(f"{IMPORTS}/preview", json=_body(account, data)).json()
    assert (preview["rows_new"], preview["rows_skipped"], preview["errors_total"]) == (1, 1, 1)
    assert preview["errors"][0]["message"] == "currency differs from account currency"
    run = _import(world.owner, account, data)
    assert (run["rows_new"], run["rows_skipped"], run["rows_total"]) == (1, 1, 2)
    assert len(_txs(db, account)) == 1


def test_analyze_unknown_layout(world: World) -> None:
    data = b"Datum,Betrag,Text\n2026-01-05,-12.50,Foo\n2026-01-06,3.00,Bar\n"
    response = world.owner.post(
        f"{IMPORTS}/analyze", json={"content_base64": _b64(data), "filename": "x.csv"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"]["delimiter"] == ","
    assert body["format"]["columns"]["booking_date"] == "Datum"
    assert body["preset_key"] is None
    assert body["headers"] == ["Datum", "Betrag", "Text"]
    assert body["sample_rows"] == [["2026-01-05", "-12.50", "Foo"], ["2026-01-06", "3.00", "Bar"]]
    assert "Text" in body["unmapped_headers"]


def test_analyze_detects_preset(world: World) -> None:
    data = _csv(_line("02.01.2026", "-3,50"))
    body = world.owner.post(
        f"{IMPORTS}/analyze", json={"content_base64": _b64(data), "filename": "x.csv"}
    ).json()
    assert body["preset_key"] == "sparkasse_camt"
    assert body["confidence"] == "high"


def test_presets_listed(world: World) -> None:
    keys = {p["key"] for p in world.owner.get(f"{IMPORTS}/presets").json()}
    assert {"dkb_2023", "sparkasse_camt"} <= keys


def test_preview_flags_duplicates_and_suggests_categories(world: World, db: Session) -> None:
    category = world.owner.post("/api/categories", json={"name": "Genuss", "kind": "expense"}).json()
    world.owner.post(
        "/api/rules",
        json={"category_id": category["id"], "conditions": {"counterparty_contains": "kaffeebar"}},
    )
    account = make_account(db, world.owner_user)
    _import(world.owner, account, _csv(_line("02.01.2026", "-3,50")))
    data = _csv(
        _line("02.01.2026", "-3,50"), _line("03.01.2026", "-2,00"), _line("04.01.2026", "-7,00", "Tankstelle")
    )
    preview = world.owner.post(f"{IMPORTS}/preview", json=_body(account, data)).json()
    assert (preview["rows_total"], preview["rows_new"], preview["rows_duplicate"]) == (3, 2, 1)
    rows = preview["rows"]
    assert [r["is_duplicate"] for r in rows] == [True, False, False]
    assert rows[0]["suggested_category_id"] is None
    assert rows[1]["suggested_category_id"] == category["id"]
    assert rows[1]["suggested_category_name"] == "Genuss"
    assert rows[2]["suggested_category_id"] is None
    assert len(_txs(db, account)) == 1  # nothing was written


def test_size_limit_base64_and_missing_column(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    big = _body(account, b"x" * (5 * 1024 * 1024 + 1))
    assert world.owner.post(f"{IMPORTS}/preview", json=big).status_code == 413
    assert (
        world.owner.post(
            f"{IMPORTS}/analyze", json={"content_base64": big["content_base64"], "filename": "a"}
        ).status_code
        == 413
    )

    bad = {**_body(account, _csv(_line("02.01.2026", "-1,00"))), "content_base64": "not base64!!"}
    assert world.owner.post(f"{IMPORTS}/preview", json=bad).status_code == 422

    columns = {**FORMAT["columns"], "booking_date": "Nonexistent"}
    body = _body(account, _csv(_line("02.01.2026", "-1,00")), format={**FORMAT, "columns": columns})
    response = world.owner.post(IMPORTS, json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "header row not found"


def test_private_account_is_hidden_from_other_member(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", visibility=AccountVisibility.PRIVATE)
    data = _csv(_line("02.01.2026", "-3,50"))
    _import(world.owner, private, data)

    body = _body(private, data)
    assert world.member.post(f"{IMPORTS}/preview", json=body).status_code == 404
    assert world.member.post(IMPORTS, json=body).status_code == 404
    assert world.member.get(IMPORTS, params={"account_id": str(private.id)}).status_code == 404
    assert world.member.get(IMPORTS).json() == []
    assert len(world.owner.get(IMPORTS).json()) == 1
    assert len(_txs(db, private)) == 1


def test_other_household_is_isolated(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    data = _csv(_line("02.01.2026", "-3,50"))
    _import(world.owner, account, data)
    profile = world.owner.post(f"{IMPORTS}/profiles", json={"name": "Meine Bank", "format": FORMAT}).json()

    assert world.stranger.post(f"{IMPORTS}/preview", json=_body(account, data)).status_code == 404
    assert world.stranger.post(IMPORTS, json=_body(account, data)).status_code == 404
    assert world.stranger.get(IMPORTS).json() == []
    assert world.stranger.get(f"{IMPORTS}/profiles").json() == []
    url = f"{IMPORTS}/profiles/{profile['id']}"
    assert world.stranger.patch(url, json={"name": "X"}).status_code == 404
    assert world.stranger.delete(url).status_code == 404
    assert len(world.owner.get(f"{IMPORTS}/profiles").json()) == 1


def test_audit_row_has_no_transaction_text(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    run = _import(
        world.owner,
        account,
        _csv(_line("02.01.2026", "-3,50", "Kaffeebar Muster", "Geheimzweck", IBAN_EXTERNAL)),
    )
    db.expire_all()
    (entry,) = db.scalars(select(AuditLog).where(AuditLog.action == "import_completed")).all()
    assert entry.user_id == world.owner_user.id
    assert entry.details["account_id"] == str(account.id)
    assert entry.details["import_run_id"] == run["id"]
    assert entry.details["rows_new"] == "1"
    text = str(entry.details).lower()
    assert not any(s in text for s in ("kaffeebar", "geheimzweck", IBAN_EXTERNAL.lower(), "umsaetze"))


def test_runs_listing_is_newest_first(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user)
    first = _import(world.owner, account, _csv(_line("02.01.2026", "-1,00")))
    second = _import(world.owner, account, _csv(_line("03.01.2026", "-2,00")))
    runs = world.owner.get(IMPORTS, params={"account_id": str(account.id)}).json()
    assert [r["id"] for r in runs] == [second["id"], first["id"]]


def test_profile_crud(world: World) -> None:
    created = world.owner.post(f"{IMPORTS}/profiles", json={"name": "Meine Bank", "format": FORMAT})
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["format"]["columns"]["booking_date"] == "Buchungstag"

    dup = world.member.post(f"{IMPORTS}/profiles", json={"name": "Meine Bank", "format": FORMAT})
    assert dup.status_code == 409

    other = world.member.post(f"{IMPORTS}/profiles", json={"name": "Zweite", "format": FORMAT}).json()
    clash = world.owner.patch(f"{IMPORTS}/profiles/{other['id']}", json={"name": "Meine Bank"})
    assert clash.status_code == 409

    url = f"{IMPORTS}/profiles/{profile['id']}"
    renamed = world.member.patch(url, json={"name": "Umbenannt"}).json()
    assert renamed["name"] == "Umbenannt"
    assert renamed["format"] == profile["format"]
    reformatted = world.owner.patch(url, json={"format": {**FORMAT, "delimiter": ","}}).json()
    assert reformatted["format"]["delimiter"] == ","
    assert reformatted["name"] == "Umbenannt"

    invalid = world.owner.post(f"{IMPORTS}/profiles", json={"name": "Kaputt", "format": {"delimiter": ";"}})
    assert invalid.status_code == 422

    assert [p["name"] for p in world.owner.get(f"{IMPORTS}/profiles").json()] == ["Umbenannt", "Zweite"]
    assert world.owner.delete(url).status_code == 204
    assert world.owner.delete(url).status_code == 404
