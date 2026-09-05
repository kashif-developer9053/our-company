"""Provider-independent agent memory (MongoDB). Switching an agent's AI provider
never touches this — memory lives here, not in any provider's context window."""

from __future__ import annotations

from datetime import datetime, timezone

from .database import get_db
from .logger import get_logger

log = get_logger("agent_memory")

MAX_ACTIVITY = 50          # rolling recent-activity entries
MAX_FACTS = 40
MAX_MSGS_PER_SESSION = 30
MAX_SESSIONS = 12


def _col():
    return get_db()["agent_memory"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_memory(agent_id: str) -> dict:
    doc = _col().find_one({"agent_id": agent_id})
    if doc is None:
        agent = get_db()["agents"].find_one({"id": agent_id}) or {}
        doc = {
            "agent_id": agent_id,
            "role_summary": f"{agent.get('name', agent_id)} — {agent.get('responsibility', '')}".strip(" —"),
            "recent_activity": [], "conversation_history": [], "key_facts": [], "last_updated": _now(),
        }
        _col().insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


def set_role_summary(agent_id: str, summary: str) -> None:
    get_memory(agent_id)
    _col().update_one({"agent_id": agent_id}, {"$set": {"role_summary": summary, "last_updated": _now()}})


def add_activity(agent_id: str, summary: str) -> None:
    get_memory(agent_id)
    _col().update_one({"agent_id": agent_id}, {
        "$push": {"recent_activity": {"$each": [{"timestamp": _now(), "summary": summary}], "$slice": -MAX_ACTIVITY}},
        "$set": {"last_updated": _now()},
    })


def add_key_fact(agent_id: str, fact: str) -> None:
    get_memory(agent_id)
    _col().update_one({"agent_id": agent_id}, {
        "$push": {"key_facts": {"$each": [fact], "$slice": -MAX_FACTS}}, "$set": {"last_updated": _now()},
    })


def add_conversation(agent_id: str, session_id: str, role: str, content: str) -> None:
    mem = get_memory(agent_id)
    sessions = mem.get("conversation_history", [])
    sess = next((s for s in sessions if s.get("session_id") == session_id), None)
    entry = {"role": role, "content": content[:4000], "timestamp": _now()}
    if sess is None:
        sessions.append({"session_id": session_id, "messages": [entry], "summary": ""})
    else:
        msgs = sess.get("messages", []) + [entry]
        # If the session has grown past the cap, summarize the oldest turns into a
        # real content summary (never silently drop them) and keep the recent window.
        if len(msgs) > MAX_MSGS_PER_SESSION:
            overflow = msgs[:-MAX_MSGS_PER_SESSION]
            sess["summary"] = _extend_summary(sess.get("summary", ""), overflow)
            msgs = msgs[-MAX_MSGS_PER_SESSION:]
        sess["messages"] = msgs
    # Trim: keep only the most recent sessions (bounded memory).
    sessions = sessions[-MAX_SESSIONS:]
    _col().update_one({"agent_id": agent_id}, {"$set": {"conversation_history": sessions, "last_updated": _now()}})


def _extend_summary(existing: str, trimmed_msgs: list[dict]) -> str:
    """Fold trimmed-off older messages into a short CONTENT summary (not just
    'we talked'). Keeps real substance so long sessions don't lose meaning."""
    lines = []
    for m in trimmed_msgs:
        who = "CEO" if m.get("role") == "user" else "You"
        text = (m.get("content") or "").strip().replace("\n", " ")
        if text:
            lines.append(f"{who}: {text[:200]}")
    chunk = " | ".join(lines)
    combined = (existing + " | " + chunk) if existing else chunk
    return combined[-2000:]  # bounded


def get_session_messages(agent_id: str, session_id: str) -> tuple[list[dict], str]:
    """Return (recent raw messages, summary-of-older-turns) for a session,
    loaded straight from MongoDB. This is the READ side of persistent memory."""
    mem = get_memory(agent_id)
    for s in mem.get("conversation_history", []):
        if s.get("session_id") == session_id:
            return list(s.get("messages", [])), (s.get("summary") or "")
    return [], ""
