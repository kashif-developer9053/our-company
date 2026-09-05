"""Auth dependencies used to protect routes.

get_current_user  -> requires a valid, non-revoked session for ANY protected route.
require_admin     -> additionally requires role == "admin" (Settings, Users).
Both enforce server-side — the frontend hiding things is never trusted alone.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.database import get_db

from .security_auth import TokenError, decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if cred is None or not cred.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(cred.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    user = get_db()["users"].find_one({"id": payload["sub"]})
    if user is None or not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="Account not found or disabled")
    # Attach the raw payload so routes (e.g. logout) can revoke it.
    user["_token_payload"] = payload
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
