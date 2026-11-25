"""Web Push message encryption (RFC 8291, aes128gcm) and VAPID authentication (RFC 8292).

Pure functions without I/O; sending lives in `app.push`.
"""

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE = 4096
# A push service must accept at least 4096 bytes of payload (RFC 8030, 7.2).
# Header (86) + padding delimiter (1) + GCM tag (16) leave this much for the plaintext.
MAX_PLAINTEXT = RECORD_SIZE - 86 - 1 - 16
_AUTH_SECRET_SIZE = 16
_SALT_SIZE = 16
_UNCOMPRESSED_POINT_SIZE = 65
# VAPID tokens may live up to 24 hours; 12 leaves room for clock skew.
_VAPID_TTL_SECONDS = 12 * 60 * 60

# Push services of the browsers we support. Subscriptions must point to one of them,
# so the server never sends requests to hosts a member picked (SSRF).
PUSH_SERVICE_SUFFIXES = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, Samsung Internet
    "push.services.mozilla.com",  # Firefox
    "push.apple.com",  # Safari
    "notify.windows.com",  # Edge on Windows
)


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    """Strict base64url decoding; padding is optional, other characters raise ValueError."""
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


def validate_endpoint(endpoint: str) -> None:
    """Raise ValueError unless `endpoint` is an https URL of a known push service."""
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password:
        raise ValueError("push endpoint must be a plain https URL")
    if not any(host == suffix or host.endswith("." + suffix) for suffix in PUSH_SERVICE_SUFFIXES):
        raise ValueError("push endpoint is not a known push service")


def validate_subscription_keys(p256dh: str, auth: str) -> None:
    """Raise ValueError unless the browser keys have the shape RFC 8291 requires."""
    try:
        public = b64url_decode(p256dh)
        secret = b64url_decode(auth)
    except ValueError as exc:
        raise ValueError("subscription keys must be base64url") from exc
    if len(secret) != _AUTH_SECRET_SIZE:
        raise ValueError("auth secret must be 16 bytes")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except ValueError as exc:
        raise ValueError("p256dh is not a P-256 public key") from exc


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _uncompressed(public_key: ec.EllipticCurvePublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt(
    plaintext: bytes,
    ua_public: bytes,
    auth_secret: bytes,
    *,
    salt: bytes | None = None,
    as_private: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """Encrypt one push message for a browser subscription (single aes128gcm record).

    `salt` and `as_private` are generated per message; pass them only to reproduce test vectors.
    """
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("push payload too large")
    if len(auth_secret) != _AUTH_SECRET_SIZE:
        raise ValueError("auth secret must be 16 bytes")
    salt = os.urandom(_SALT_SIZE) if salt is None else salt
    if len(salt) != _SALT_SIZE:
        raise ValueError("salt must be 16 bytes")
    as_private = ec.generate_private_key(ec.SECP256R1()) if as_private is None else as_private
    as_public = _uncompressed(as_private.public_key())
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)

    # RFC 8291, section 3.4: combine the ECDH secret with the auth secret.
    ecdh_secret = as_private.exchange(ec.ECDH(), receiver)
    prk_key = _hmac(auth_secret, ecdh_secret)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hmac(prk_key, key_info + b"\x01")

    # RFC 8188, section 2.2: derive content encryption key and nonce.
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]

    # Single record: the 0x02 delimiter marks it as the last one, no further padding.
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


class VapidKey:
    """The application server's P-256 key pair that identifies it to push services."""

    def __init__(self, private_key: ec.EllipticCurvePrivateKey) -> None:
        if not isinstance(private_key.curve, ec.SECP256R1):
            raise ValueError("VAPID key must be a P-256 key")
        self._private_key = private_key
        self.public_key = b64url_encode(_uncompressed(private_key.public_key()))

    @classmethod
    def from_pem(cls, pem: str) -> "VapidKey":
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("VAPID key must be an EC private key")
        return cls(key)

    @staticmethod
    def generate_pem() -> str:
        key = ec.generate_private_key(ec.SECP256R1())
        return key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()

    def authorization(self, endpoint: str, subject: str, *, now: float | None = None) -> str:
        """Value of the Authorization header for a request to `endpoint` (RFC 8292, section 3)."""
        parts = urlsplit(endpoint)
        issued = int(time.time() if now is None else now)
        token = jwt.encode(
            {"aud": f"{parts.scheme}://{parts.netloc}", "exp": issued + _VAPID_TTL_SECONDS, "sub": subject},
            self._private_key,
            algorithm="ES256",
        )
        return f"vapid t={token}, k={self.public_key}"
