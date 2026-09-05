"""User management. Admin-only except /users/me/password (self-service).

Delete policy: hard delete is allowed but guarded — you cannot delete yourself
or the last remaining admin. To disable someone without removing them, set
is_active=false (soft disable) via PUT.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth.deps import get_current_user, require_admin
from auth.security_auth import hash_password, verify_password
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

from .users_model import ROLES, PasswordReset, SelfPasswordChange, UserCreate, UserUpdate, serialize, valid_email

log = get_logger("users")
router = APIRouter(prefix="/users", tags=["users"])


def _col():
    return get_db()["users"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_admin_count() -> int:
    return _col().count_documents({"role": "admin", "is_active": True})


# ---- self-service (any logged-in user) — defined BEFORE /{id} routes -------
@router.put("/me/password")
@safe_endpoint("users")
async def change_my_password(body: SelfPasswordChange, user: dict = Depends(get_current_user)):
    # Current password required even for admins (safety check).
    if not verify_password(body.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    _col().update_one({"id": user["id"]}, {"$set": {"password_hash": hash_password(body.new_password)}})
    log.info("User %s changed their own password", user["email"])
    return {"ok": True}


@router.put("/me")
@safe_endpoint("users")
async def update_my_profile(body: UserUpdate, user: dict = Depends(get_current_user)):
    updates = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.email is not None:
        if not valid_email(body.email):
            raise HTTPException(status_code=400, detail="Invalid email")
        updates["email"] = body.email.strip().lower()
    if updates:
        _col().update_one({"id": user["id"]}, {"$set": updates})
    return {"ok": True, "user": serialize(_col().find_one({"id": user["id"]}))}


# ---- admin-only ------------------------------------------------------------
@router.get("")
@safe_endpoint("users")
async def list_users(_: dict = Depends(require_admin)):
    return {"ok": True, "users": [serialize(d) for d in _col().find({})]}


@router.post("")
@safe_endpoint("users")
async def create_user(body: UserCreate, _: dict = Depends(require_admin)):
    if not valid_email(body.email):
        raise HTTPException(status_code=400, detail="Invalid email")
    email = body.email.strip().lower()
    if _col().find_one({"email": email}):
        raise HTTPException(status_code=400, detail="A user with that email already exists")
    role = body.role if body.role in ROLES else "user"
    # Admin may set a password, or we generate a temporary one shown once.
    temp = None
    pwd = body.password
    if not pwd:
        temp = uuid.uuid4().hex[:10]
        pwd = temp
    user = {
        "id": f"u_{uuid.uuid4().hex[:10]}",
        "name": body.name.strip(),
        "email": email,
        "password_hash": hash_password(pwd),
        "role": role,
        "is_active": True,
        "created_at": _now(),
        "last_login": "",
    }
    _col().insert_one(dict(user))
    log.info("Admin created user %s (%s)", email, role)
    return {"ok": True, "user": serialize(user), "temporary_password": temp}


@router.put("/{user_id}")
@safe_endpoint("users")
async def update_user(user_id: str, body: UserUpdate, admin: dict = Depends(require_admin)):
    doc = _col().find_one({"id": user_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.email is not None:
        if not valid_email(body.email):
            raise HTTPException(status_code=400, detail="Invalid email")
        updates["email"] = body.email.strip().lower()
    if body.role is not None and body.role in ROLES:
        updates["role"] = body.role
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    # Guard: don't strip the last active admin (by role change or deactivation).
    if doc.get("role") == "admin" and doc.get("is_active", True):
        demoting = updates.get("role", "admin") != "admin" or updates.get("is_active", True) is False
        if demoting and _active_admin_count() <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote/disable the last active admin")
    _col().update_one({"id": user_id}, {"$set": updates})
    return {"ok": True, "user": serialize(_col().find_one({"id": user_id}))}


@router.put("/{user_id}/password")
@safe_endpoint("users")
async def reset_user_password(user_id: str, body: PasswordReset, _: dict = Depends(require_admin)):
    if _col().find_one({"id": user_id}) is None:
        raise HTTPException(status_code=404, detail="User not found")
    _col().update_one({"id": user_id}, {"$set": {"password_hash": hash_password(body.new_password)}})
    log.info("Admin reset password for user %s", user_id)
    return {"ok": True}


@router.delete("/{user_id}")
@safe_endpoint("users")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    doc = _col().find_one({"id": user_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if doc.get("role") == "admin" and doc.get("is_active", True) and _active_admin_count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last active admin")
    _col().delete_one({"id": user_id})
    log.info("Admin deleted user %s", user_id)
    return {"ok": True, "deleted": user_id}
