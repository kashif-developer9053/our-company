"""Authentication: first-run admin setup, login, logout, and 'me'."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint
from users.users_model import serialize, valid_email

from .deps import get_current_user
from .security_auth import create_token, hash_password, revoke_token, verify_password

log = get_logger("auth")
router = APIRouter(prefix="/auth", tags=["auth"])


def _users():
    return get_db()["users"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SetupBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    password: str = Field(min_length=6, max_length=200)


class LoginBody(BaseModel):
    email: str
    password: str


@router.get("/needs-setup")
@safe_endpoint("auth")
async def needs_setup():
    """True when no users exist yet (first-run). Open endpoint."""
    return {"ok": True, "needs_setup": _users().count_documents({}) == 0}


@router.post("/setup")
@safe_endpoint("auth")
async def setup(body: SetupBody):
    # Only allowed to create the FIRST admin, and never again once users exist.
    if _users().count_documents({}) > 0:
        raise HTTPException(status_code=403, detail="Setup already completed")
    if not valid_email(body.email):
        raise HTTPException(status_code=400, detail="Invalid email")
    user = {
        "id": f"u_{uuid.uuid4().hex[:10]}",
        "name": body.name.strip(),
        "email": body.email.strip().lower(),
        "password_hash": hash_password(body.password),
        "role": "admin",
        "is_active": True,
        "created_at": _now(),
        "last_login": "",
    }
    _users().insert_one(dict(user))
    log.info("First admin created: %s", user["email"])
    token = create_token(user["id"], user["role"])
    return {"ok": True, "token": token, "user": serialize(user)}


@router.post("/login")
@safe_endpoint("auth")
async def login(body: LoginBody):
    email = body.email.strip().lower()
    user = _users().find_one({"email": email})
    if user is None or not verify_password(body.password, user.get("password_hash", "")):
        # Basic brute-force visibility: log repeated failures per account.
        attempts = get_db()["login_attempts"]
        attempts.update_one({"email": email}, {"$inc": {"failures": 1}, "$set": {"last_failure": _now()}}, upsert=True)
        rec = attempts.find_one({"email": email})
        log.warning("Failed login for %s (total failures: %s)", email, rec.get("failures") if rec else 1)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is disabled")

    get_db()["login_attempts"].delete_one({"email": email})  # reset on success
    _users().update_one({"id": user["id"]}, {"$set": {"last_login": _now()}})
    token = create_token(user["id"], user["role"])
    log.info("Login OK: %s (%s)", email, user["role"])
    return {"ok": True, "token": token, "user": serialize(user)}


@router.post("/logout")
@safe_endpoint("auth")
async def logout(user: dict = Depends(get_current_user)):
    revoke_token(user["_token_payload"])  # server-side invalidation
    return {"ok": True}


@router.get("/me")
@safe_endpoint("auth")
async def me(user: dict = Depends(get_current_user)):
    return {"ok": True, "user": serialize(user)}
