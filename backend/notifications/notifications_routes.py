"""Notification API — the CEO's inbox (bell icon in the office UI)."""

from __future__ import annotations

from fastapi import APIRouter

from shared import notifications
from shared.safe_wrapper import safe_endpoint

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
@safe_endpoint("notifications")
async def list_all(include_resolved: bool = False, limit: int = 50):
    return {
        "ok": True,
        "notifications": notifications.list_notifications(include_resolved, limit),
        "unread": notifications.unread_count(),
    }


@router.get("/count")
@safe_endpoint("notifications")
async def count():
    return {"ok": True, "unread": notifications.unread_count()}


@router.post("/{notification_id}/read")
@safe_endpoint("notifications")
async def read_one(notification_id: str):
    return {"ok": notifications.mark_read(notification_id)}


@router.post("/read-all")
@safe_endpoint("notifications")
async def read_all():
    return {"ok": True, "updated": notifications.mark_all_read()}
