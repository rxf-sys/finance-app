"""Time-based one-time passwords (RFC 6238) with replay protection."""

import time

import pyotp

STEP_SECONDS = 30
# Accept the previous and next 30 s window to tolerate clock drift.
VALID_WINDOW = 1


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def match_step(secret: str, code: str, last_used_step: int | None, now: float | None = None) -> int | None:
    """Return the matched time step, or None if the code is invalid or already used."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    for step in range(current - VALID_WINDOW, current + VALID_WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if pyotp.utils.strings_equal(totp.at(step * STEP_SECONDS), code):
            return step
    return None
