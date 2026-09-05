"""Password hashing (bcrypt) + JWT session tokens with server-side revocation.

Passwords are hashed with bcrypt — plaintext is never stored or logged. Tokens
are real JWTs with a short expiry, and logout adds the token's jti to a
revocation list checked on every request (so logout truly invalidates)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from shared.database import get_db
from shared.logger import get_logger

log = get_logger("auth")

_ALGO = "HS256"
_EXPIRY_HOURS = 4


def _secret() -> str:
    # Reuse ENCRYPTION_SECRET if a dedicated AUTH_SECRET isn't set; fall back to
    # an insecure dev value with a warning (production must set one).
    s = os.environ.get("AUTH_SECRET") or os.environ.get("ENCRYPTION_SECRET")
    if not s:
        log.warning("AUTH_SECRET/ENCRYPTION_SECRET not set — using insecure dev fallback.")
        s = "dev-insecure-auth-secret"
    return s


# ---- password hashing ------------------------------------------------------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


# ---- JWT -------------------------------------------------------------------
def create_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(hours=_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGO])
    except jwt.ExpiredSignatureError:
        raise TokenError("Session expired")
    except jwt.PyJWTError:
        raise TokenError("Invalid session")
    if get_db()["revoked_tokens"].find_one({"jti": payload.get("jti")}):
        raise TokenError("Session ended")
    return payload


def revoke_token(payload: dict) -> None:
    get_db()["revoked_tokens"].insert_one({"jti": payload.get("jti"), "revoked_at": datetime.now(timezone.utc).isoformat()})
