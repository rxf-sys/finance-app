import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.security.webpush import (
    MAX_PLAINTEXT,
    VapidKey,
    b64url_decode,
    b64url_encode,
    encrypt,
    validate_endpoint,
    validate_subscription_keys,
)
from tests.helpers import decrypt_push as _decrypt
from tests.helpers import raw_public as _raw_public

# RFC 8291, section 5 and appendix A.
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
RFC_UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
RFC_AUTH_SECRET = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_HEADER = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vC"
    "YLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
RFC_CIPHERTEXT = "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def _private_key(raw_b64url: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64url_decode(raw_b64url)), ec.SECP256R1())


def test_encrypt_matches_rfc_8291_example() -> None:
    body = encrypt(
        RFC_PLAINTEXT,
        b64url_decode(RFC_UA_PUBLIC),
        b64url_decode(RFC_AUTH_SECRET),
        salt=b64url_decode(RFC_SALT),
        as_private=_private_key(RFC_AS_PRIVATE),
    )
    assert b64url_encode(body[:86]) == RFC_HEADER
    assert b64url_encode(body[86:]) == RFC_CIPHERTEXT


def test_rfc_example_decrypts_with_receiver_key() -> None:
    body = b64url_decode(RFC_HEADER) + b64url_decode(RFC_CIPHERTEXT)
    assert _decrypt(body, _private_key(RFC_UA_PRIVATE), b64url_decode(RFC_AUTH_SECRET)) == RFC_PLAINTEXT


def test_encrypt_round_trip_uses_fresh_salt_and_key() -> None:
    ua_private = ec.generate_private_key(ec.SECP256R1())
    ua_public = _raw_public(ua_private)
    secret = b"0123456789abcdef"
    payload = '{"title":"Kündigungsfrist"}'.encode()

    first = encrypt(payload, ua_public, secret)
    second = encrypt(payload, ua_public, secret)

    assert _decrypt(first, ua_private, secret) == payload
    assert first[:16] != second[:16]  # salt
    assert first[21:86] != second[21:86]  # ephemeral sender key


def test_encrypt_rejects_oversized_payload_and_bad_secret() -> None:
    ua_public = b64url_decode(RFC_UA_PUBLIC)
    secret = b64url_decode(RFC_AUTH_SECRET)
    assert len(encrypt(b"x" * MAX_PLAINTEXT, ua_public, secret)) == 4096
    with pytest.raises(ValueError, match="too large"):
        encrypt(b"x" * (MAX_PLAINTEXT + 1), ua_public, secret)
    with pytest.raises(ValueError, match="16 bytes"):
        encrypt(b"hi", ua_public, secret[:8])


@pytest.mark.parametrize(
    "endpoint",
    [
        ENDPOINT,
        "https://updates.push.services.mozilla.com/wpush/v2/gAAAA",
        "https://web.push.apple.com/QGuQyavXutnMH",
        "https://wns2-am3p.notify.windows.com/w/?token=BQYAAA",
    ],
)
def test_validate_endpoint_accepts_browser_push_services(endpoint: str) -> None:
    validate_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com:8443/fcm/send/abc",
        "https://user:pw@fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com.evil.example/x",
        "https://evilfcm.googleapis.com/x",
        "https://192.168.1.10/x",
        "https://localhost/x",
        "not a url",
    ],
)
def test_validate_endpoint_rejects_other_hosts(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_validate_subscription_keys() -> None:
    validate_subscription_keys(RFC_UA_PUBLIC, RFC_AUTH_SECRET)
    with pytest.raises(ValueError, match="16 bytes"):
        validate_subscription_keys(RFC_UA_PUBLIC, "AAAA")
    with pytest.raises(ValueError, match="P-256"):
        validate_subscription_keys(b64url_encode(b"\x04" + b"\x00" * 64), RFC_AUTH_SECRET)
    with pytest.raises(ValueError, match="base64url"):
        validate_subscription_keys("@@@@", RFC_AUTH_SECRET)


def test_vapid_authorization_header_is_a_valid_es256_token() -> None:
    key = VapidKey.from_pem(VapidKey.generate_pem())

    header = key.authorization(ENDPOINT, "mailto:admin@example.org", now=1_700_000_000)

    token_part, key_part = header.removeprefix("vapid ").split(", ")
    assert key_part == f"k={key.public_key}"
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(key.public_key))
    claims = jwt.decode(
        token_part.removeprefix("t="),
        public,
        algorithms=["ES256"],
        audience="https://fcm.googleapis.com",
        options={"verify_exp": False},
    )
    assert claims == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1_700_000_000 + 12 * 3600,
        "sub": "mailto:admin@example.org",
    }
    assert len(b64url_decode(key.public_key)) == 65


def test_vapid_key_rejects_other_curves() -> None:
    with pytest.raises(ValueError, match="P-256"):
        VapidKey(ec.generate_private_key(ec.SECP384R1()))
