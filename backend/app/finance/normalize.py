"""Normalization helpers for IBANs and free text."""

import re

_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")


def normalize_iban(value: str) -> str:
    """Strip whitespace, upper-case and validate format plus the ISO 13616 mod-97 checksum."""
    iban = "".join(value.split()).upper()
    if not _IBAN_RE.fullmatch(iban):
        raise ValueError("Invalid IBAN format")
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    if int(numeric) % 97 != 1:
        raise ValueError("Invalid IBAN checksum")
    return iban


def normalize_text(value: str) -> str:
    """Casefold, collapse whitespace and strip, for matching and hashing."""
    return " ".join(value.casefold().split())
