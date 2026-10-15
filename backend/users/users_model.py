"""User data model + serializer. password_hash is NEVER serialized out."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

import re

# "caller" is a cold caller: he can reach the WhatsApp call desk and
# nothing else. Enforced by auth.deps.require_staff on every other router.
ROLES = ["admin", "user", "caller"]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    role: str = "user"
    password: Optional[str] = Field(default=None, min_length=6, max_length=200)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=6, max_length=200)


class SelfPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=200)


def serialize(doc: dict) -> dict:
    """Public user shape — password_hash intentionally omitted."""
    return {
        "id": doc["id"],
        "name": doc.get("name", ""),
        "email": doc.get("email", ""),
        "role": doc.get("role", "user"),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at", ""),
        "last_login": doc.get("last_login", ""),
    }
