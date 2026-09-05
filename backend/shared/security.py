"""Encryption helpers for API keys.

Uses the `cryptography` library's Fernet (AES) symmetric encryption — no custom
crypto. The Fernet key is DERIVED from a single server-side secret,
ENCRYPTION_SECRET, which must be set in the hosting environment. That one secret
protects every stored API key; nothing else needs to live in the environment.

If ENCRYPTION_SECRET is missing we fall back to a clearly-insecure dev value so
the app still runs locally, but we log a loud warning — production MUST set it.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

from .logger import get_logger

log = get_logger("security")

_DEV_FALLBACK = "dev-insecure-encryption-secret-change-me"


def _fernet() -> Fernet:
    secret = os.environ.get("ENCRYPTION_SECRET")
    if not secret:
        log.warning(
            "ENCRYPTION_SECRET is not set — using an INSECURE dev fallback. "
            "Set ENCRYPTION_SECRET in the hosting environment for production."
        )
        secret = _DEV_FALLBACK
    # Derive a valid 32-byte urlsafe Fernet key deterministically from the secret
    # so the same secret always decrypts previously-stored values.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def encryption_secret_is_set() -> bool:
    return bool(os.environ.get("ENCRYPTION_SECRET"))


def last_four(value: str) -> str:
    return value[-4:] if len(value) >= 4 else value
