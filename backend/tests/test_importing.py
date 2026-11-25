"""Tests for ``app.importing``. All data is synthetic; nothing here touches the database itself.

Note: ``tests/conftest.py`` has a session-scoped autouse ``database`` fixture, so the whole suite
(including this file) needs Docker for the throwaway Postgres container.
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pytest
from pydantic import ValidationError

from app.importing import (
    MAX_ROWS,
    PRESETS,
    ColumnMap,
    CsvFormat,
    ParsedRow,
    detect_preset,
    get_preset,
    parse,
    parse_amount_cents,
    suggest_format,
)

IBAN = "DE89370400440532013000"


def build_csv(
    headers: Sequence[str],
    rows: Sequence[dict[str, str]],
    *,
    delimiter: str = ";",
    encoding: str = "utf-8",
    prefix: Sequence[str] = (),
    suffix: Sequence[str] = (),
    newline: str = "\n",
) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, quoting=csv.QUOTE_ALL, lineterminator=newline)
    for line in prefix:
        out.write(line + newline)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    for line in suffix:
        out.write(line + newline)
    return out.getvalue().encode(encoding)


def simple_format(**overrides: object) -> CsvFormat:
    columns = ColumnMap(booking_date="Datum", amount="Betrag")
    return CsvFormat(columns=columns).model_copy(update=overrides)


# --- presets ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PresetCase:
    key: str
    data: bytes
    dates: list[date]
    cents: list[int]
    name: str | None = None
    iban: str | None = None


def _dkb_case() -> PresetCase:
    headers = [
        "Buchungsdatum",
        "Wertstellung",
        "Status",
        "Zahlungspflichtige*r",
        "Zahlungsempfänger*in",
        "Verwendungszweck",
        "Umsatztyp",
        "IBAN",
        "Betrag (€)",
        "Gläubiger-ID",
        "Mandatsreferenz",
        "Kundenreferenz",
    ]
    rows = [
        {
            "Buchungsdatum": "05.01.24",
            "Wertstellung": "05.01.24",
            "Status": "Gebucht",
            "Zahlungsempfänger*in": "Vermieter Muster GmbH",
            "Verwendungszweck": "Miete Januar",
            "Umsatztyp": "Ausgang",
            "IBAN": "de89 3704 0044 0532 0130 00",
            "Betrag (€)": "-1.234,56",
        },
        {
            "Buchungsdatum": "15.01.24",
            "Wertstellung": "15.01.24",
            "Status": "Gebucht",
            "Zahlungspflichtige*r": "Beispiel AG",
            "Verwendungszweck": "Gehalt",
            "Umsatztyp": "Eingang",
            "IBAN": IBAN,
            "Betrag (€)": "2.500,00",
        },
        {
            "Buchungsdatum": "20.01.24",
            "Wertstellung": "21.01.24",
            "Status": "Gebucht",
            "Zahlungsempfänger*in": "Muster Markt",
            "Verwendungszweck": "Einkauf",
            "Umsatztyp": "Ausgang",
            "IBAN": IBAN,
            "Betrag (€)": "-12,30 €",
        },
    ]
    prefix = [f'"Girokonto";"{IBAN}"', '"Kontostand vom 31.01.2024:";"1.234,56 EUR"', ""]
    return PresetCase(
        "dkb_2023",
        build_csv(headers, rows, prefix=prefix, encoding="utf-8-sig"),
        [date(2024, 1, 5), date(2024, 1, 15), date(2024, 1, 20)],
        [-123456, 250000, -1230],
        name="Vermieter Muster GmbH",
        iban=IBAN,
    )


def _ing_case() -> PresetCase:
    headers = [
        "Buchung",
        "Auftraggeber/Empfänger",
        "Buchungstext",
        "Verwendungszweck",
        "Saldo",
        "Währung",
        "Betrag",
        "Währung",
    ]
    rows = [
        ["03.01.2024", "Bäckerei Müller", "Lastschrift", "Brötchen", "1.000,00", "EUR", "-5,60", "EUR"],
        ["10.01.2024", "Beispiel AG", "Gutschrift", "Gehalt", "3.494,40", "EUR", "2.500,00", "EUR"],
        ["11.01.2024", "Muster Strom", "Lastschrift", "Abschlag", "3.400,40", "EUR", "-94,00", "EUR"],
    ]
    prefix = [
        "Umsatzanzeige;Datei erstellt am: 01.02.2024 10:00",
        "",
        f"IBAN;{IBAN}",
        "Kontoname;Girokonto",
        "Zeitraum;01.01.2024 - 31.01.2024",
        "",
        "In der CSV-Datei finden Sie alle bereits gebuchten Umsätze.",
        "",
    ]
    out = io.StringIO()
    for line in prefix:
        out.write(line + "\n")
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return PresetCase(
        "ing_umsatzanzeige",
        out.getvalue().encode("iso-8859-1"),
        [date(2024, 1, 3), date(2024, 1, 10), date(2024, 1, 11)],
        [-560, 250000, -9400],
        name="Bäckerei Müller",
    )


def _sparkasse_case() -> PresetCase:
    headers = [
        "Auftragskonto",
        "Buchungstag",
        "Valutadatum",
        "Buchungstext",
        "Verwendungszweck",
        "Glaeubiger ID",
        "Mandatsreferenz",
        "Kundenreferenz (End-to-End)",
        "Sammlerreferenz",
        "Lastschrift Ursprungsbetrag",
        "Auslagenersatz Ruecklastschrift",
        "Beguenstigter/Zahlungspflichtiger",
        "Kontonummer/IBAN",
        "BIC (SWIFT-Code)",
        "Betrag",
        "Waehrung",
        "Info",
    ]
    rows = [
        {
            "Auftragskonto": IBAN,
            "Buchungstag": "03.01.24",
            "Valutadatum": "03.01.24",
            "Buchungstext": "LASTSCHRIFT",
            "Verwendungszweck": "Rechnung 1",
            "Beguenstigter/Zahlungspflichtiger": "Muster GmbH",
            "Kontonummer/IBAN": IBAN,
            "Betrag": "-1.234,56",
            "Waehrung": "EUR",
        },
        {
            "Auftragskonto": IBAN,
            "Buchungstag": "04.01.2024",
            "Valutadatum": "04.01.2024",
            "Buchungstext": "GUTSCHRIFT",
            "Verwendungszweck": "Erstattung",
            "Beguenstigter/Zahlungspflichtiger": "Beispiel AG",
            "Betrag": "2500,50",
            "Waehrung": "EUR",
        },
        {
            "Auftragskonto": IBAN,
            "Buchungstag": "05.01.24",
            "Valutadatum": "05.01.24",
            "Buchungstext": "KARTENZAHLUNG",
            "Verwendungszweck": "Markt",
            "Betrag": "-68",
            "Waehrung": "EUR",
        },
    ]
    return PresetCase(
        "sparkasse_camt",
        build_csv(headers, rows, encoding="iso-8859-1", newline="\r\n"),
        [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)],
        [-123456, 250050, -6800],
        name="Muster GmbH",
        iban=IBAN,
    )


def _n26_case(key: str, headers: list[str], date_col: str, amount_col: str, name_col: str) -> PresetCase:
    rows = [
        {date_col: "2024-01-05", name_col: "Muster GmbH", amount_col: "-12.30"},
        {date_col: "2024-01-06", name_col: "Beispiel AG", amount_col: "1500.00"},
        {date_col: "2024-01-07", name_col: "Kiosk", amount_col: "-0.5"},
    ]
    return PresetCase(
        key,
        build_csv(headers, rows, delimiter=","),
        [date(2024, 1, 5), date(2024, 1, 6), date(2024, 1, 7)],
        [-1230, 150000, -50],
        name="Muster GmbH",
    )


def _commerzbank_case() -> PresetCase:
    headers = [
        "Buchungstag",
        "Wertstellung",
        "Umsatzart",
        "Buchungstext",
        "Betrag",
        "Währung",
        "Auftraggeberkonto",
        "Bankleitzahl Auftraggeberkonto",
        "IBAN Auftraggeberkonto",
        "Kategorie",
    ]
    base = {"Umsatzart": "Lastschrift", "Währung": "EUR", "IBAN Auftraggeberkonto": IBAN}
    rows = [
        {
            **base,
            "Buchungstag": "03.01.2024",
            "Wertstellung": "03.01.2024",
            "Buchungstext": "A",
            "Betrag": "-1.234,56",
        },
        {
            **base,
            "Buchungstag": "04.01.2024",
            "Wertstellung": "05.01.2024",
            "Buchungstext": "B",
            "Betrag": "2.500,00",
        },
        {
            **base,
            "Buchungstag": "05.01.2024",
            "Wertstellung": "05.01.2024",
            "Buchungstext": "C",
            "Betrag": "-0,99",
        },
    ]
    return PresetCase(
        "commerzbank",
        build_csv(headers, rows, encoding="utf-8-sig"),
        [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)],
        [-123456, 250000, -99],
    )


PRESET_CASES = [
    _dkb_case(),
    _ing_case(),
    _sparkasse_case(),
    _n26_case(
        "n26_en_legacy",
        [
            "Date",
            "Payee",
            "Account number",
            "Transaction type",
            "Payment reference",
            "Category (optional)",
            "Amount (EUR)",
            "Amount (Foreign Currency)",
            "Type Foreign Currency",
            "Exchange Rate",
        ],
        "Date",
        "Amount (EUR)",
        "Payee",
    ),
    _n26_case(
        "n26_de_legacy",
        [
            "Datum",
            "Empfänger",
            "Kontonummer",
            "Transaktionstyp",
            "Verwendungszweck",
            "Kategorie (optional)",
            "Betrag (EUR)",
            "Betrag (Fremdwährung)",
            "Fremdwährung",
            "Wechselkurs",
        ],
        "Datum",
        "Betrag (EUR)",
        "Empfänger",
    ),
    _n26_case(
        "n26_en_newer",
        [
            "Booking Date",
            "Value Date",
            "Partner Name",
            "Partner Iban",
            "Type",
            "Payment Reference",
            "Category (optional)",
            "Account Name",
            "Amount (EUR)",
            "Original Amount",
            "Original Currency",
            "Exchange Rate",
        ],
        "Booking Date",
        "Amount (EUR)",
        "Partner Name",
    ),
    _commerzbank_case(),
]


def test_every_preset_has_a_case() -> None:
    assert {c.key for c in PRESET_CASES} == {p.key for p in PRESETS}
    assert all(p.label and p.signature for p in PRESETS)


@pytest.mark.parametrize("case", PRESET_CASES, ids=lambda c: c.key)
def test_preset_detection_and_parse(case: PresetCase) -> None:
    assert detect_preset(case.data) == case.key

    result = parse(case.data, get_preset(case.key).format)

    assert result.errors == []
    assert result.skipped == 0
    assert [r.booking_date for r in result.rows] == case.dates
    assert [r.amount_cents for r in result.rows] == case.cents
    assert result.rows[0].counterparty_name == case.name
    assert result.rows[0].counterparty_iban == case.iban
    assert all(r.currency == "EUR" for r in result.rows)


@pytest.mark.parametrize("case", PRESET_CASES, ids=lambda c: c.key)
def test_automap_recognises_preset(case: PresetCase) -> None:
    suggestion = suggest_format(case.data)

    assert suggestion.preset_key == case.key
    assert suggestion.format == get_preset(case.key).format
    assert suggestion.confidence == "high"


def test_preset_only_maps_researched_columns() -> None:
    assert get_preset("ing_umsatzanzeige").format.columns.counterparty_iban is None
    commerz = get_preset("commerzbank").format.columns
    assert commerz.counterparty_name is None
    assert commerz.counterparty_iban is None
    assert commerz.purpose is None


def test_dkb_value_date_and_booking_text() -> None:
    case = _dkb_case()
    row = parse(case.data, get_preset("dkb_2023").format).rows[2]

    assert row.value_date == date(2024, 1, 21)
    assert row.booking_text == "Ausgang"
    assert row.purpose == "Einkauf"


def test_ing_uses_second_waehrung_column() -> None:
    headers = ["Buchung", "Betrag", "Währung", "Währung"]
    data = build_csv(headers, [{"Buchung": "03.01.2024", "Betrag": "1,00"}])
    # Rebuild by hand so the two currency cells differ.
    text = data.decode().splitlines()[0] + '\n"03.01.2024";"1,00";"USD";"CHF"\n'
    fmt = get_preset("ing_umsatzanzeige").format

    rows = parse(text.encode("iso-8859-1"), fmt).rows

    assert rows[0].currency == "CHF"
    assert rows[0].raw["Währung"] == "USD"
    assert rows[0].raw["Währung_2"] == "CHF"


def test_detect_preset_returns_none_for_unknown_bank() -> None:
    assert detect_preset(b"Datum;Betrag\n01.01.2024;1,00\n") is None
    assert detect_preset(b"") is None


# --- auto-mapping ----------------------------------------------------------------------------


def test_automap_unknown_bank_with_metadata_lines() -> None:
    headers = [
        "Datum",
        "Valuta",
        "Name Zahlungsbeteiligter",
        "IBAN Zahlungsbeteiligter",
        "Verwendungszweck",
        "Umsatzart",
        "Betrag",
        "Währung",
        "Saldo",
        "Notiz",
    ]
    rows = [
        {
            "Datum": "05.01.2024",
            "Valuta": "06.01.2024",
            "Name Zahlungsbeteiligter": "Muster GmbH",
            "IBAN Zahlungsbeteiligter": IBAN,
            "Verwendungszweck": "Rechnung 7",
            "Umsatzart": "Überweisung",
            "Betrag": "-1.234,56",
            "Währung": "EUR",
            "Saldo": "10.000,00",
        },
        {
            "Datum": "20.01.2024",
            "Name Zahlungsbeteiligter": "Beispiel AG",
            "Verwendungszweck": "Gehalt",
            "Umsatzart": "Gutschrift",
            "Betrag": "2.500,00",
            "Währung": "EUR",
            "Saldo": "12.500,00",
        },
    ]
    prefix = ["Kontoauszug Girokonto;", f"Konto;{IBAN}", "Zeitraum;01.01.2024 - 31.01.2024", ""]
    data = build_csv(headers, rows, prefix=prefix, encoding="cp1252", delimiter=";")

    suggestion = suggest_format(data)

    assert suggestion.preset_key is None
    assert suggestion.format is not None
    assert suggestion.headers == headers
    assert suggestion.header_row == 4
    assert suggestion.unmapped_required == []
    assert suggestion.unmapped_headers == ["Notiz"]
    assert suggestion.confidence == "medium"
    fmt = suggestion.format
    assert fmt.delimiter == ";"
    assert fmt.date_formats == ["%d.%m.%Y"]
    assert (fmt.decimal_separator, fmt.thousands_separator) == (",", ".")
    cols = fmt.columns
    assert (cols.booking_date, cols.value_date, cols.amount) == ("Datum", "Valuta", "Betrag")
    assert cols.counterparty_name == "Name Zahlungsbeteiligter"
    assert cols.counterparty_iban == "IBAN Zahlungsbeteiligter"
    assert (cols.currency, cols.balance, cols.booking_text) == ("Währung", "Saldo", "Umsatzart")

    result = parse(data, fmt)
    assert result.errors == []
    assert [r.amount_cents for r in result.rows] == [-123456, 250000]
    assert result.rows[0].balance_cents == 1000000
    assert result.rows[0].booking_text == "Überweisung"
    assert result.rows[0].line_no == 6


def test_automap_english_comma_dot_layout() -> None:
    data = b"Date,Payee,Amount\n2024-01-05,Shop,-12.30\n2024-01-06,Employer,1234.50\n"

    suggestion = suggest_format(data)

    assert suggestion.format is not None
    assert suggestion.format.delimiter == ","
    assert suggestion.format.date_formats == ["%Y-%m-%d"]
    assert suggestion.format.decimal_separator == "."
    assert [r.amount_cents for r in parse(data, suggestion.format).rows] == [-1230, 123450]


def test_automap_debit_credit_columns() -> None:
    data = b"Buchungstag;Soll;Haben\n05.01.2024;12,30;\n06.01.2024;;1.000,00\n"

    suggestion = suggest_format(data)

    assert suggestion.format is not None
    assert suggestion.format.columns.amount is None
    assert (suggestion.format.columns.debit, suggestion.format.columns.credit) == ("Soll", "Haben")
    assert [r.amount_cents for r in parse(data, suggestion.format).rows] == [-1230, 100000]


def test_automap_ignores_decoration_in_header_names() -> None:
    data = "BUCHUNGSTAG;Betrag (€);Zahlungsempfänger*in;Zahlungspflichtige*r\n05.01.2024;-1,00;A;\n".encode()

    fmt = suggest_format(data).format

    assert fmt is not None
    assert fmt.columns.counterparty_name == ["Zahlungsempfänger*in", "Zahlungspflichtige*r"]


def test_automap_two_digit_year_and_tab_delimiter() -> None:
    data = b"Datum\tBetrag\n05.01.24\t-1,00\n06.01.24\t2,00\n"

    fmt = suggest_format(data).format

    assert fmt is not None
    assert fmt.delimiter == "\t"
    assert fmt.date_formats == ["%d.%m.%y"]


def test_automap_without_header_reports_unmapped() -> None:
    suggestion = suggest_format(b"foo;bar\n1;2\n")

    assert suggestion.format is None
    assert suggestion.confidence == "low"
    assert "booking_date" in suggestion.unmapped_required


def test_automap_header_beyond_30_lines_is_not_found() -> None:
    data = b"meta;x\n" * 30 + b"Datum;Betrag\n05.01.2024;1,00\n"

    assert suggest_format(data).format is None


def test_automap_without_data_rows_flags_date_format() -> None:
    suggestion = suggest_format(b"Datum;Betrag\n")

    assert suggestion.format is not None
    assert suggestion.unmapped_required == ["date_format"]
    assert suggestion.confidence == "low"


# --- encodings -------------------------------------------------------------------------------


def test_cp1252_file_with_umlauts_auto_detected() -> None:
    data = build_csv(
        ["Datum", "Betrag", "Name"],
        [{"Datum": "05.01.2024", "Betrag": "-3,50", "Name": "Bäckerei Müller & Söhne \u2013 Straße €"}],
        encoding="cp1252",
    )
    fmt = CsvFormat(
        columns=ColumnMap(booking_date="Datum", amount="Betrag", counterparty_name="Name"),
    )

    for encoding in ("auto", "cp1252"):
        row = parse(data, fmt.model_copy(update={"encoding": encoding})).rows[0]
        assert row.counterparty_name == "Bäckerei Müller & Söhne \u2013 Straße €"


def test_utf8_bom_is_stripped() -> None:
    data = build_csv(["Datum", "Betrag"], [{"Datum": "05.01.2024", "Betrag": "1,00"}], encoding="utf-8-sig")
    assert data.startswith(b"\xef\xbb\xbf")

    for encoding in ("auto", "utf-8", "utf-8-sig"):
        result = parse(data, simple_format(encoding=encoding))
        assert [r.amount_cents for r in result.rows] == [100]
        assert list(result.rows[0].raw) == ["Datum", "Betrag"]

    assert suggest_format(data).headers == ["Datum", "Betrag"]


def test_explicit_utf8_with_invalid_bytes_raises() -> None:
    with pytest.raises(ValueError, match="not valid utf-8"):
        parse(b"Datum;Betrag\n05.01.2024;1,\xe4\n", simple_format(encoding="utf-8"))


# --- money -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("1.234,56", 123456),
        ("-1.234.567,89", -123456789),
        ("-12,30", -1230),
        ("12,30-", -1230),
        ("+5,00", 500),
        ("5", 500),
        ("0,5", 50),
        ("-68", -6800),
        (",50", 50),
        ("12,30 €", 1230),
        ("12,30€", 1230),
        ("12,30 EUR", 1230),
        ("EUR 12,30", 1230),
        ("-12,30 eur", -1230),
        ("\u00a01.234,56\u00a0€", 123456),
        ("\u221212,30", -1230),
        ("12,300", 1230),
        ("0,00", 0),
    ],
)
def test_parse_amount_german(text: str, cents: int) -> None:
    assert parse_amount_cents(text) == cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("-12.30", -1230),
        ("1,234.56", 123456),
        ("0.1", 10),
        ("5", 500),
        ("1234.50", 123450),
        ("12.30-", -1230),
    ],
)
def test_parse_amount_dot_decimal(text: str, cents: int) -> None:
    assert parse_amount_cents(text, ".", ",") == cents


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "abc",
        "12,345",
        "1,2,3",
        "12.30",
        "1.2.3,4",
        "--5",
        "-5-",
        "+-5",
        "12,",
        "€",
        "1 2,00x",
        "٣,00",
    ],
)
def test_parse_amount_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError, match="amount"):
        parse_amount_cents(text)


def test_parse_amount_rejects_more_than_two_decimals_and_huge_values() -> None:
    with pytest.raises(ValueError, match="more than 2 decimals"):
        parse_amount_cents("0,001")
    with pytest.raises(ValueError, match="out of range"):
        parse_amount_cents("9" * 16)


def test_parse_amount_is_exact() -> None:
    # 0.1 + 0.2 style float traps must not occur.
    assert parse_amount_cents("0,29") == 29
    assert parse_amount_cents("1.000.000,07") == 100000007


# --- row handling ----------------------------------------------------------------------------


def test_trailing_minus_and_thousands_in_file() -> None:
    data = b"Datum;Betrag\n05.01.2024;1.234,56-\n06.01.2024;12.345,00\n"

    assert [r.amount_cents for r in parse(data, simple_format()).rows] == [-123456, 1234500]


def test_debit_credit_columns() -> None:
    fmt = CsvFormat(columns=ColumnMap(booking_date="Datum", debit="Soll", credit="Haben"))
    data = (
        b"Datum;Soll;Haben\n"
        b"05.01.2024;12,30;\n"
        b"06.01.2024;;1.000,00\n"
        b"07.01.2024;-5,00;\n"
        b"08.01.2024;;\n"
        b"09.01.2024;10,00;4,00\n"
    )

    result = parse(data, fmt)

    assert [r.amount_cents for r in result.rows] == [-1230, 100000, -500, -600]
    assert [(e.line_no, e.message) for e in result.errors] == [(5, "missing amount")]


def test_sign_marker_column() -> None:
    columns = ColumnMap(booking_date="Datum", amount="Betrag", sign_column="S/H", debit_markers=["S"])
    data = (
        b"Datum;Betrag;S/H\n05.01.2024;12,30;S\n06.01.2024;1.000,00;H\n07.01.2024;5,00;s\n08.01.2024;-2,00;\n"
    )

    result = parse(data, CsvFormat(columns=columns))

    assert [r.amount_cents for r in result.rows] == [-1230, 100000, -500, -200]


def test_malformed_date_and_amount_become_row_errors() -> None:
    data = (
        b"Datum;Betrag;Valuta\n"
        b"05.01.2024;1,00;\n"
        b"31.02.2024;2,00;\n"
        b"2024-01-05;3,00;\n"
        b"06.01.2024;abc;\n"
        b"07.01.2024;1,234;\n"
        b"08.01.2024;;\n"
        b"09.01.2024;4,00;99.99.2024\n"
        b"10.01.2024;5,00;\n"
    )
    fmt = CsvFormat(columns=ColumnMap(booking_date="Datum", amount="Betrag", value_date="Valuta"))

    result = parse(data, fmt)

    assert [r.amount_cents for r in result.rows] == [100, 500]
    assert [(e.line_no, e.message) for e in result.errors] == [
        (3, "invalid booking date"),
        (4, "invalid booking date"),
        (5, "invalid amount"),
        (6, "invalid amount: more than 2 decimals"),
        (7, "missing amount"),
        (8, "invalid value date"),
    ]
    assert result.skipped == 0


def test_error_messages_do_not_echo_cell_contents() -> None:
    result = parse(b"Datum;Betrag\n05.01.2024;SECRET-TOKEN\n12.99.2024;1,00\n", simple_format())

    assert result.errors
    assert all("SECRET" not in e.message and "12.99" not in e.message for e in result.errors)


def test_footer_and_summary_lines_are_skipped() -> None:
    data = (
        b"Datum;Betrag\n"
        b"05.01.2024;1,00\n"
        b"\n"
        b";;\n"
        b"Summe;1,00\n"
        b"Kontostand;1.234,56\n"
        b";2,00\n"
        b"Erstellt am 01.02.2024;\n"
    )

    result = parse(data, simple_format())

    assert len(result.rows) == 1
    assert result.errors == []
    assert result.skipped == 4  # blank lines are ignored silently and not counted


def test_identical_rows_are_both_kept() -> None:
    data = b"Datum;Betrag\n05.01.2024;-9,99\n05.01.2024;-9,99\n"

    rows = parse(data, simple_format()).rows

    assert len(rows) == 2
    assert rows[0].line_no == 2
    assert rows[1].line_no == 3
    assert rows[0].booking_date == rows[1].booking_date
    assert rows[0].amount_cents == rows[1].amount_cents


def test_counterparty_and_purpose_lists() -> None:
    columns = ColumnMap(
        booking_date="Datum",
        amount="Betrag",
        counterparty_name=["A", "B"],
        counterparty_iban=["IBAN1", "IBAN2"],
        purpose=["P1", "P2", "P3"],
    )
    data = (
        b"Datum;Betrag;A;B;IBAN1;IBAN2;P1;P2;P3\n"
        b"05.01.2024;1,00;;Second;;de89 3704 0044 0532 0130 00;one;;three\n"
        b"06.01.2024;1,00;;;;;;;\n"
    )

    first, second = parse(data, CsvFormat(columns=columns)).rows

    assert first.counterparty_name == "Second"
    assert first.counterparty_iban == IBAN
    assert first.purpose == "one three"
    assert (second.counterparty_name, second.counterparty_iban, second.purpose) == (None, None, "")
    assert second.booking_text is None
    assert second.currency == "EUR"
    assert second.balance_cents is None


def test_raw_contains_every_header() -> None:
    data = b"Datum;Betrag;Extra\n05.01.2024;1,00;hello\n"

    assert parse(data, simple_format()).rows[0].raw == {
        "Datum": "05.01.2024",
        "Betrag": "1,00",
        "Extra": "hello",
    }


def test_short_rows_and_invalid_currency_do_not_raise() -> None:
    columns = ColumnMap(booking_date="Datum", amount="Betrag", currency="Cur")
    data = b"Datum;Betrag;Cur\n05.01.2024\n06.01.2024;1,00;E1R\n07.01.2024;1,00;usd\n"

    result = parse(data, CsvFormat(columns=columns))

    assert [(e.line_no, e.message) for e in result.errors] == [(2, "missing amount"), (3, "invalid currency")]
    assert [r.currency for r in result.rows] == ["USD"]


def test_quoted_fields_with_delimiters_and_newlines() -> None:
    columns = ColumnMap(booking_date="Datum", amount="Betrag", purpose="Zweck")
    data = b'Datum;Betrag;Zweck\n05.01.2024;1,00;"a;b\nc"\n06.01.2024;2,00;x\n'

    rows = parse(data, CsvFormat(columns=columns)).rows

    assert rows[0].purpose == "a;b\nc"
    assert rows[0].line_no == 3
    assert rows[1].line_no == 4


def test_explicit_header_row() -> None:
    data = b"Datum;Betrag\nfoo;bar\nDatum;Betrag\n05.01.2024;1,00\n"

    result = parse(data, simple_format(header_row=2))

    assert [r.amount_cents for r in result.rows] == [100]


def test_missing_header_or_column_raises_value_error() -> None:
    with pytest.raises(ValueError, match="header row not found"):
        parse(b"foo;bar\n1;2\n", simple_format())
    with pytest.raises(ValueError, match="header row not found"):
        parse(b"", simple_format())
    with pytest.raises(ValueError, match="amount column not found"):
        parse(
            b"Datum;Betrag\n",
            simple_format(header_row=0, columns=ColumnMap(booking_date="Datum", amount="X")),
        )


# --- guards and validation -------------------------------------------------------------------


def test_too_many_rows_guard() -> None:
    line = b"05.01.2024;1,00\n"
    header = b"Datum;Betrag\n"

    assert len(parse(header + line * MAX_ROWS, simple_format()).rows) == MAX_ROWS
    with pytest.raises(ValueError, match="too many rows"):
        parse(header + line * (MAX_ROWS + 1), simple_format())


def test_column_map_rejects_amount_together_with_debit() -> None:
    with pytest.raises(ValidationError, match="exactly one of amount or debit/credit"):
        ColumnMap(booking_date="Datum", amount="Betrag", debit="Soll")
    with pytest.raises(ValidationError, match="exactly one of amount or debit/credit"):
        ColumnMap(booking_date="Datum", amount="Betrag", credit="Haben")


def test_column_map_requires_an_amount_source() -> None:
    with pytest.raises(ValidationError):
        ColumnMap(booking_date="Datum")


def test_column_map_sign_column_rules() -> None:
    with pytest.raises(ValidationError, match="together"):
        ColumnMap(booking_date="Datum", amount="Betrag", sign_column="S/H")
    with pytest.raises(ValidationError, match="together"):
        ColumnMap(booking_date="Datum", amount="Betrag", debit_markers=["S"])
    with pytest.raises(ValidationError, match="requires amount"):
        ColumnMap(booking_date="Datum", debit="Soll", sign_column="S/H", debit_markers=["S"])


def test_models_forbid_unknown_fields() -> None:
    columns = ColumnMap(booking_date="Datum", amount="Betrag")
    with pytest.raises(ValidationError):
        ColumnMap.model_validate({"booking_date": "Datum", "amount": "Betrag", "bogus": 1})
    with pytest.raises(ValidationError):
        CsvFormat.model_validate({"columns": columns.model_dump(), "bogus": 1})


def test_csv_format_validation() -> None:
    columns = ColumnMap(booking_date="Datum", amount="Betrag")
    with pytest.raises(ValidationError):
        CsvFormat(columns=columns, encoding="utf-16")
    with pytest.raises(ValidationError):
        CsvFormat(columns=columns, delimiter="|")
    with pytest.raises(ValidationError, match="strptime"):
        CsvFormat(columns=columns, date_format="no directives")
    with pytest.raises(ValidationError, match="strptime"):
        CsvFormat(columns=columns, date_format=[])
    with pytest.raises(ValidationError, match="differ"):
        CsvFormat(columns=columns, decimal_separator=",", thousands_separator=",")
    with pytest.raises(ValidationError):
        CsvFormat(columns=columns, header_row=-1)


def test_date_format_list_is_tried_in_order() -> None:
    fmt = simple_format(date_format=["%d.%m.%y", "%Y-%m-%d"])
    data = b"Datum;Betrag\n05.01.24;1,00\n2024-01-06;2,00\n"

    rows: list[ParsedRow] = parse(data, fmt).rows

    assert [r.booking_date for r in rows] == [date(2024, 1, 5), date(2024, 1, 6)]
