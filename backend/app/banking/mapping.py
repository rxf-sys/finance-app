"""Convert Enable Banking transactions to the fields of our Transaction model.

The transaction schema is only partly verified (see the research notes), so every field access is
tolerant: a missing or oddly shaped field yields None instead of an error. Rows without a usable
amount or booking date are skipped.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from app.finance.normalize import normalize_iban

BOOKED = "BOOK"


@dataclass(frozen=True)
class MappedTransaction:
    booking_date: date
    value_date: date | None
    amount_cents: int
    currency: str
    counterparty_name: str | None
    counterparty_iban: str | None
    purpose: str | None
    booking_text: str | None
    entry_reference: str | None
    raw: dict[str, Any]


def provider_dedupe_hash(account_uid: str, entry_reference: str) -> str:
    return hashlib.sha256(f"eb|{account_uid}|{entry_reference}".encode()).hexdigest()


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] or None


def _cents(amount: Any) -> int | None:
    if not isinstance(amount, str | int):
        return None
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return int((abs(value) * 100).to_integral_value(rounding=ROUND_HALF_EVEN))


def account_iban(account: dict[str, Any]) -> str | None:
    """IBAN of a provider account. The nesting is unverified: look in account_id and all_account_ids."""
    candidates: list[Any] = []
    account_id = account.get("account_id")
    if isinstance(account_id, dict):
        candidates.append(account_id.get("iban"))
    elif isinstance(account_id, str):
        candidates.append(account_id)
    candidates.append(account.get("iban"))
    others = account.get("all_account_ids")
    if isinstance(others, list):
        for item in others:
            if isinstance(item, dict):
                if str(item.get("scheme_name", "")).upper() == "IBAN":
                    candidates.append(item.get("identification"))
                candidates.append(item.get("iban"))
    for candidate in candidates:
        if isinstance(candidate, str):
            try:
                return normalize_iban(candidate)
            except ValueError:
                continue
    return None


def _party(tx: dict[str, Any], party_key: str, account_key: str) -> tuple[str | None, str | None]:
    party = tx.get(party_key)
    name = _text(party.get("name"), 200) if isinstance(party, dict) else None
    account = tx.get(account_key)
    iban: str | None = None
    if isinstance(account, dict) and isinstance(account.get("iban"), str):
        try:
            iban = normalize_iban(account["iban"])
        except ValueError:
            iban = None
    return name, iban


def _purpose(tx: dict[str, Any]) -> str | None:
    info = tx.get("remittance_information")
    if isinstance(info, str):
        return _text(info, 2000)
    if isinstance(info, list):
        return _text(" ".join(part for part in info if isinstance(part, str)), 2000)
    return None


def _booking_text(tx: dict[str, Any]) -> str | None:
    code = tx.get("bank_transaction_code")
    if isinstance(code, dict):
        return _text(code.get("description"), 100) or _text(code.get("code"), 100)
    return _text(code, 100)


def map_transaction(tx: dict[str, Any], default_currency: str = "EUR") -> MappedTransaction | None:
    """Return the mapped booked transaction, or None for pending, unusable or non-booked entries."""
    if tx.get("status") != BOOKED:
        return None
    amount = tx.get("transaction_amount")
    if not isinstance(amount, dict):
        return None
    cents = _cents(amount.get("amount"))
    if cents is None:
        return None
    indicator = tx.get("credit_debit_indicator")
    if indicator == "DBIT":
        cents = -cents
    elif indicator != "CRDT" and str(amount.get("amount", "")).strip().startswith("-"):
        # No indicator: fall back to the sign of the amount itself.
        cents = -cents
    booking = (
        _date(tx.get("booking_date")) or _date(tx.get("value_date")) or _date(tx.get("transaction_date"))
    )
    if booking is None:
        return None
    currency = amount.get("currency")
    # The counterparty of a debit is the creditor, of a credit the debtor.
    if indicator == "CRDT":
        name, iban = _party(tx, "debtor", "debtor_account")
    else:
        name, iban = _party(tx, "creditor", "creditor_account")
    reference = tx.get("entry_reference")
    return MappedTransaction(
        booking_date=booking,
        value_date=_date(tx.get("value_date")),
        amount_cents=cents,
        currency=currency.upper() if isinstance(currency, str) and len(currency) == 3 else default_currency,
        counterparty_name=name,
        counterparty_iban=iban,
        purpose=_purpose(tx),
        booking_text=_booking_text(tx),
        entry_reference=reference.strip() if isinstance(reference, str) and reference.strip() else None,
        raw=tx,
    )
