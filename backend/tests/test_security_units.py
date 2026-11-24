import pyotp
import pytest
from cryptography.exceptions import InvalidTag

from app.security import totp
from app.security.crypto import SecretBox, generate_key
from app.security.passwords import hash_password, verify_password


def test_secret_box_roundtrip_and_context_binding() -> None:
    box = SecretBox(generate_key())
    blob = box.encrypt(b"JBSWY3DPEHPK3PXP", b"totp:user-1")

    assert box.decrypt(blob, b"totp:user-1") == b"JBSWY3DPEHPK3PXP"
    with pytest.raises(InvalidTag):
        box.decrypt(blob, b"totp:user-2")


def test_secret_box_rejects_short_key() -> None:
    with pytest.raises(ValueError):
        SecretBox("c2hvcnQ=")


def test_password_hashing() -> None:
    hashed = hash_password("a long enough password")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a long enough password")
    assert not verify_password(hashed, "wrong")
    assert not verify_password(None, "anything")


def test_totp_window_and_replay() -> None:
    secret = pyotp.random_base32()
    now = 1_800_000_000.0
    step = int(now // 30)
    code = pyotp.TOTP(secret).at(now)

    assert totp.match_step(secret, code, None, now=now) == step
    assert totp.match_step(secret, code, step, now=now) is None  # already used
    assert totp.match_step(secret, pyotp.TOTP(secret).at(now - 30), None, now=now) == step - 1
    assert totp.match_step(secret, pyotp.TOTP(secret).at(now - 90), None, now=now) is None
    assert totp.match_step(secret, "12345a", None, now=now) is None
