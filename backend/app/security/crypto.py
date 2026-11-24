"""Symmetric encryption for small secrets at rest (AES-256-GCM)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


class SecretBox:
    """Encrypts with a 256-bit key. Output layout: nonce (12 bytes) || ciphertext."""

    def __init__(self, key_b64: str) -> None:
        key = base64.b64decode(key_b64, validate=True)
        if len(key) != 32:
            raise ValueError("encryption key must be 32 bytes, base64 encoded")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, context: bytes) -> bytes:
        nonce = os.urandom(NONCE_SIZE)
        return nonce + self._aead.encrypt(nonce, plaintext, context)

    def decrypt(self, blob: bytes, context: bytes) -> bytes:
        return self._aead.decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], context)


def generate_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()
