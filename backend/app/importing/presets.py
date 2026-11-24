"""Built-in formats for banks whose layout was researched with medium confidence.

Headers come from open-source importers, not from bank documents, so detection is a hint and
every preset leaves a column ``None`` where the research did not identify it. Banks without a
reliable source (Sparkasse CSV-MT940, VR banks, Postbank, Consorsbank, comdirect) are handled
by header auto-mapping instead.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice

from app.importing._sniff import HEADER_SEARCH_LINES, normalize, read_records
from app.importing.config import ColumnMap, CsvFormat

_DE_DATES = ["%d.%m.%Y", "%d.%m.%y"]


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    format: CsvFormat
    signature: frozenset[str]
    """Header names that must all be present (loosely compared) for the preset to match."""


PRESETS: tuple[Preset, ...] = (
    Preset(
        key="dkb_2023",
        label="DKB (CSV ab 2023)",
        format=CsvFormat(
            encoding="utf-8-sig",
            delimiter=";",
            date_format=["%d.%m.%y", "%d.%m.%Y"],
            columns=ColumnMap(
                booking_date="Buchungsdatum",
                value_date="Wertstellung",
                amount="Betrag (€)",
                counterparty_name=["Zahlungsempfänger*in", "Zahlungspflichtige*r"],
                counterparty_iban="IBAN",
                purpose="Verwendungszweck",
                booking_text="Umsatztyp",
            ),
        ),
        signature=frozenset(
            {
                "Buchungsdatum",
                "Wertstellung",
                "Status",
                "Zahlungspflichtige*r",
                "Zahlungsempfänger*in",
                "Verwendungszweck",
                "Umsatztyp",
                "IBAN",
                "Betrag (€)",
            }
        ),
    ),
    Preset(
        key="ing_umsatzanzeige",
        label="ING (Umsatzanzeige)",
        format=CsvFormat(
            encoding="iso-8859-1",
            delimiter=";",
            date_format="%d.%m.%Y",
            columns=ColumnMap(
                booking_date="Buchung",
                amount="Betrag",
                # The header has "Währung" twice (balance, then amount); repeats get a _2 suffix.
                currency="Währung_2",
                counterparty_name="Auftraggeber/Empfänger",
                purpose="Verwendungszweck",
                booking_text="Buchungstext",
            ),
        ),
        signature=frozenset(
            {"Buchung", "Auftraggeber/Empfänger", "Buchungstext", "Verwendungszweck", "Betrag", "Währung"}
        ),
    ),
    Preset(
        key="sparkasse_camt",
        label="Sparkasse (CSV-CAMT)",
        format=CsvFormat(
            encoding="iso-8859-1",
            delimiter=";",
            date_format=_DE_DATES,
            columns=ColumnMap(
                booking_date="Buchungstag",
                value_date="Valutadatum",
                amount="Betrag",
                currency="Waehrung",
                counterparty_name="Beguenstigter/Zahlungspflichtiger",
                counterparty_iban="Kontonummer/IBAN",
                purpose="Verwendungszweck",
                booking_text="Buchungstext",
            ),
        ),
        signature=frozenset(
            {
                "Auftragskonto",
                "Buchungstag",
                "Valutadatum",
                "Buchungstext",
                "Verwendungszweck",
                "Beguenstigter/Zahlungspflichtiger",
                "Kontonummer/IBAN",
                "Betrag",
            }
        ),
    ),
    Preset(
        key="n26_en_legacy",
        label="N26 (CSV englisch, älteres Format)",
        format=CsvFormat(
            encoding="utf-8",
            delimiter=",",
            date_format="%Y-%m-%d",
            decimal_separator=".",
            thousands_separator="",
            columns=ColumnMap(
                booking_date="Date",
                amount="Amount (EUR)",
                counterparty_name="Payee",
                purpose="Payment reference",
                booking_text="Transaction type",
            ),
        ),
        signature=frozenset(
            {"Date", "Payee", "Account number", "Transaction type", "Payment reference", "Amount (EUR)"}
        ),
    ),
    Preset(
        key="n26_de_legacy",
        label="N26 (CSV deutsch, älteres Format)",
        format=CsvFormat(
            encoding="utf-8",
            delimiter=",",
            date_format="%Y-%m-%d",
            decimal_separator=".",
            thousands_separator="",
            columns=ColumnMap(
                booking_date="Datum",
                amount="Betrag (EUR)",
                counterparty_name="Empfänger",
                purpose="Verwendungszweck",
                booking_text="Transaktionstyp",
            ),
        ),
        signature=frozenset(
            {"Datum", "Empfänger", "Kontonummer", "Transaktionstyp", "Verwendungszweck", "Betrag (EUR)"}
        ),
    ),
    Preset(
        key="n26_en_newer",
        label="N26 (CSV englisch, neueres Format)",
        format=CsvFormat(
            encoding="utf-8",
            delimiter=",",
            date_format="%Y-%m-%d",
            decimal_separator=".",
            thousands_separator="",
            columns=ColumnMap(
                booking_date="Booking Date",
                value_date="Value Date",
                amount="Amount (EUR)",
                counterparty_name="Partner Name",
                counterparty_iban="Partner Iban",
                purpose="Payment Reference",
                booking_text="Type",
            ),
        ),
        signature=frozenset(
            {
                "Booking Date",
                "Value Date",
                "Partner Name",
                "Partner Iban",
                "Type",
                "Payment Reference",
                "Amount (EUR)",
            }
        ),
    ),
    Preset(
        key="commerzbank",
        label="Commerzbank (Umsatzexport CSV)",
        format=CsvFormat(
            encoding="utf-8-sig",
            delimiter=";",
            date_format="%d.%m.%Y",
            columns=ColumnMap(
                booking_date="Buchungstag",
                value_date="Wertstellung",
                amount="Betrag",
                currency="Währung",
                # Counterparty and purpose columns were not identified by the research, and
                # "IBAN Auftraggeberkonto" is the customer's own account, so those stay None.
                booking_text="Buchungstext",
            ),
        ),
        signature=frozenset(
            {
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
            }
        ),
    ),
)


def get_preset(key: str) -> Preset:
    for preset in PRESETS:
        if preset.key == key:
            return preset
    raise KeyError(key)


def match_preset(headers: Iterable[str]) -> Preset | None:
    """Return the preset whose signature headers are all present; the largest signature wins."""
    present = {normalize(h) for h in headers}
    best: Preset | None = None
    for preset in PRESETS:
        if {normalize(h) for h in preset.signature} <= present and (
            best is None or len(preset.signature) > len(best.signature)
        ):
            best = preset
    return best


def find_preset(text: str) -> Preset | None:
    """Search the top of a decoded file for a preset header row, trying every delimiter."""
    best: Preset | None = None
    for delimiter in (";", ",", "\t"):
        for _, cells in islice(read_records(text, delimiter, '"'), HEADER_SEARCH_LINES):
            if not cells:
                continue
            found = match_preset(cells)
            if found is not None and (best is None or len(found.signature) > len(best.signature)):
                best = found
    return best
