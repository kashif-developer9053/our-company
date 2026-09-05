"""Central notification store — the CEO's inbox for anything needing attention.

Every module raises notifications through here (never by writing the collection
directly), so the office UI has ONE place to poll for "what needs the CEO?".

Kinds:
  - approval  : something is blocked waiting on a CEO decision (leads, replies…)
  - config    : something the CEO must configure before work can continue (SMTP…)
  - alert     : a failure/health problem the CEO should know about
  - info      : completed work worth reporting (pipeline finished…)

Notifications are deliberately IDEMPOTENT by `dedupe_key`: raising the same
config/alert twice does not spam the CEO — it just refreshes the existing one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .database import get_db
from .logger import get_logger

log = get_logger("notifications")

KINDS = ("approval", "config", "alert", "info")
MAX_KEEP = 300


def _col():
    return get_db()["notifications"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def notify(kind: str, title: str, body: str = "", *, agent_id: str = "",
           action: str = "", ref_id: str = "", dedupe_key: str = "") -> dict:
    """Create (or refresh) a notification. Never raises — notification failure
    must never break the work that triggered it."""
    try:
        if kind not in KINDS:
            kind = "info"
        doc = {
            "id": f"N-{uuid.uuid4().hex[:8].upper()}",
            "kind": kind,
            "title": title[:200],
            "body": body[:1500],
            "agent_id": agent_id,
            "action": action,      # frontend route/action hint, e.g. "leads_pending"
            "ref_id": ref_id,      # batch id / lead id this refers to
            "dedupe_key": dedupe_key,
            "read": False,
            "resolved": False,
            "created_at": _now(),
        }
        if dedupe_key:
            existing = _col().find_one({"dedupe_key": dedupe_key, "resolved": False})
            if existing:
                _col().update_one({"id": existing["id"]}, {"$set": {
                    "title": doc["title"], "body": doc["body"],
                    "read": False, "created_at": doc["created_at"],
                }})
                return {**existing, **doc, "id": existing["id"]}
        _col().insert_one(dict(doc))
        _prune()
        log.info("notify[%s] %s", kind, title[:80])
        return doc
    except Exception as exc:  # noqa: BLE001
        log.error("notify failed (isolated): %s", exc)
        return {}


def _prune() -> None:
    """Keep the collection bounded — drop the oldest resolved/read entries."""
    try:
        total = _col().count_documents({})
        if total > MAX_KEEP:
            old = list(_col().find({}, {"id": 1, "created_at": 1})
                       .sort("created_at", 1).limit(total - MAX_KEEP))
            _col().delete_many({"id": {"$in": [d["id"] for d in old]}})
    except Exception:  # noqa: BLE001
        pass


def resolve(dedupe_key: str) -> int:
    """Clear an outstanding notification once its cause is fixed (e.g. SMTP set)."""
    try:
        res = _col().update_many({"dedupe_key": dedupe_key, "resolved": False},
                                 {"$set": {"resolved": True, "read": True}})
        return res.modified_count
    except Exception:  # noqa: BLE001
        return 0


def serialize(d: dict) -> dict:
    return {k: d.get(k) for k in
            ("id", "kind", "title", "body", "agent_id", "action", "ref_id",
             "read", "resolved", "created_at")}


def list_notifications(include_resolved: bool = False, limit: int = 50) -> list[dict]:
    q = {} if include_resolved else {"resolved": False}
    docs = list(_col().find(q).sort("created_at", -1).limit(limit))
    return [serialize(d) for d in docs]


def unread_count() -> int:
    try:
        return _col().count_documents({"read": False, "resolved": False})
    except Exception:  # noqa: BLE001
        return 0


def mark_read(notification_id: str) -> bool:
    return _col().update_one({"id": notification_id}, {"$set": {"read": True}}).modified_count > 0


def mark_all_read() -> int:
    return _col().update_many({"read": False}, {"$set": {"read": True}}).modified_count
