"""Enable Banking client and transaction mapping, without database or network."""

import hashlib
import uuid
from datetime import date
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.banking.client import (
    BankAuthExpired,
    BankError,
    BankRateLimited,
    EnableBankingClient,
    build_jwt,
)
from app.banking.mapping import account_iban, map_transaction, provider_dedupe_hash
from app.finance.dedupe import compute_dedupe_hash
from tests.helpers import IBAN_A, IBAN_B


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def pem(rsa_key: rsa.RSAPrivateKey) -> str:
    return rsa_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def test_jwt_header_and_claims(rsa_key: rsa.RSAPrivateKey, pem: str) -> None:
    token = build_jwt("app-123", pem, now=1_800_000_000)
    header = jwt.get_unverified_header(token)
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "app-123"}
    claims = jwt.decode(
        token,
        rsa_key.public_key(),
        algorithms=["RS256"],
        audience="api.enablebanking.com",
        issuer="enablebanking.com",
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iat"] == 1_800_000_000
    assert claims["exp"] - claims["iat"] <= 3600


def _client(pem: str, handler: Any) -> EnableBankingClient:
    return EnableBankingClient("app-1", pem, transport=httpx.MockTransport(handler))


def test_requests_carry_bearer_jwt(pem: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"aspsps": [{"name": "A"}, "junk"]})

    assert _client(pem, handler).list_aspsps("DE") == [{"name": "A"}]
    token = seen[0].headers["Authorization"].removeprefix("Bearer ")
    assert jwt.get_unverified_header(token)["kid"] == "app-1"
    assert seen[0].url.params["country"] == "DE"


def test_transactions_follow_continuation_key(pem: str) -> None:
    keys: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.params.get("continuation_key")
        keys.append(key)
        assert request.url.params["date_from"] == "2026-01-01"
        if key is None:
            return httpx.Response(200, json={"transactions": [{"n": 1}], "continuation_key": "k1"})
        if key == "k1":
            return httpx.Response(200, json={"transactions": [{"n": 2}], "continuation_key": "k2"})
        return httpx.Response(200, json={"transactions": [{"n": 3}], "continuation_key": None})

    rows = _client(pem, handler).get_transactions("uid", date(2026, 1, 1))
    assert [r["n"] for r in rows] == [1, 2, 3]
    assert keys == [None, "k1", "k2"]


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        (401, {}, BankAuthExpired),
        (422, {"error": "EXPIRED_SESSION"}, BankAuthExpired),
        (429, {"error": "ASPSP_RATE_LIMIT_EXCEEDED"}, BankRateLimited),
        (500, {"error": "ASPSP_ERROR"}, BankError),
    ],
)
def test_error_mapping(pem: str, status_code: int, body: dict[str, str], expected: type[BankError]) -> None:
    client = _client(pem, lambda _r: httpx.Response(status_code, json=body))
    with pytest.raises(expected) as info:
        client.get_balances("uid")
    assert type(info.value) is expected


def test_errors_never_contain_response_body(pem: str) -> None:
    secret = "Max Mustermann DE89370400440532013000"
    body = {"message": secret, "error": "SOMETHING", "transactions": [{"note": secret}]}
    client = _client(pem, lambda _r: httpx.Response(400, json=body))
    with pytest.raises(BankError) as info:
        client.get_session("s")
    assert secret not in str(info.value)
    assert secret not in repr(info.value)


def test_network_failure_is_a_static_bank_error(pem: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom to https://api.example/accounts/secret-uid", request=request)

    with pytest.raises(BankError) as info:
        _client(pem, handler).get_balances("secret-uid")
    assert "secret-uid" not in str(info.value)


def _tx(**over: Any) -> dict[str, Any]:
    tx: dict[str, Any] = {
        "entry_reference": "ref-1",
        "status": "BOOK",
        "transaction_amount": {"currency": "EUR", "amount": "12.34"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-03-02",
        "value_date": "2026-03-03",
        "creditor": {"name": " Rewe  Markt "},
        "creditor_account": {"iban": IBAN_B},
        "debtor": {"name": "Ich"},
        "debtor_account": {"iban": IBAN_A},
        "remittance_information": ["Einkauf", "Kasse 4"],
        "bank_transaction_code": {"description": "Kartenzahlung", "code": "PMNT"},
    }
    tx.update(over)
    return tx


def test_debit_is_negative_and_uses_creditor() -> None:
    mapped = map_transaction(_tx())
    assert mapped is not None
    assert mapped.amount_cents == -1234
    assert mapped.counterparty_name == "Rewe Markt"
    assert mapped.counterparty_iban == IBAN_B
    assert mapped.purpose == "Einkauf Kasse 4"
    assert mapped.booking_text == "Kartenzahlung"
    assert mapped.booking_date == date(2026, 3, 2)
    assert mapped.value_date == date(2026, 3, 3)
    assert mapped.raw["entry_reference"] == "ref-1"


def test_credit_is_positive_and_uses_debtor() -> None:
    mapped = map_transaction(_tx(credit_debit_indicator="CRDT"))
    assert mapped is not None
    assert mapped.amount_cents == 1234
    assert mapped.counterparty_name == "Ich"
    assert mapped.counterparty_iban == IBAN_A


@pytest.mark.parametrize(
    ("amount", "cents"), [("0.29", 29), ("1234.5", 123450), ("19.99", 1999), ("100", 10000)]
)
def test_amounts_are_exact_decimals(amount: str, cents: int) -> None:
    mapped = map_transaction(
        _tx(transaction_amount={"currency": "EUR", "amount": amount}, credit_debit_indicator="CRDT")
    )
    assert mapped is not None
    assert mapped.amount_cents == cents


def test_pending_and_unusable_entries_are_skipped() -> None:
    assert map_transaction(_tx(status="PDNG")) is None
    assert map_transaction(_tx(status=None)) is None
    assert map_transaction(_tx(transaction_amount={"amount": "abc"})) is None
    assert map_transaction(_tx(transaction_amount=None)) is None
    assert map_transaction(_tx(booking_date=None, value_date=None, transaction_date=None)) is None


def test_missing_optional_fields_are_tolerated() -> None:
    mapped = map_transaction(
        {
            "status": "BOOK",
            "transaction_amount": {"amount": "5.00"},
            "credit_debit_indicator": "CRDT",
            "booking_date": "2026-03-02",
            "remittance_information": None,
            "creditor": "not-a-dict",
            "debtor_account": {"iban": "not an iban"},
        }
    )
    assert mapped is not None
    assert mapped.counterparty_name is None
    assert mapped.counterparty_iban is None
    assert mapped.purpose is None
    assert mapped.booking_text is None
    assert mapped.entry_reference is None
    assert mapped.currency == "EUR"
    assert mapped.value_date is None


def test_booking_date_falls_back_to_value_date() -> None:
    mapped = map_transaction(_tx(booking_date=None))
    assert mapped is not None
    assert mapped.booking_date == date(2026, 3, 3)


def test_entry_reference_hash_is_provider_scoped() -> None:
    expected = hashlib.sha256(b"eb|uid-1|ref-1").hexdigest()
    assert provider_dedupe_hash("uid-1", "ref-1") == expected
    assert provider_dedupe_hash("uid-2", "ref-1") != expected
    # unlike the CSV hash it does not depend on the local account id or the content
    assert expected != compute_dedupe_hash(uuid.uuid4(), date(2026, 3, 2), -1234, None, None, 0)


def test_account_iban_is_read_from_known_shapes() -> None:
    assert account_iban({"account_id": {"iban": IBAN_A}}) == IBAN_A
    assert account_iban({"iban": IBAN_A.lower()}) == IBAN_A
    assert account_iban({"all_account_ids": [{"scheme_name": "IBAN", "identification": IBAN_B}]}) == IBAN_B
    assert account_iban({"account_id": None}) is None
