"""WhatsApp call outreach — the cold caller's queue.

Messaging and calling are different jobs. A message is written once and sent;
a call is a conversation someone has to prepare for, and the person making it
is not the person who collected the lead. So a lead that has been messaged can
be pushed onto a CALL queue, where it keeps everything the caller needs in one
place: what the business is, why we approached them, and what to actually say.

A lead stays on the WhatsApp desk after being queued. It is the same lead,
worked two ways — the desk shows the message thread, this shows the call.

The caller is not technical and is not the CEO. He sees his queue and nothing
else, so every field here is phrased to be read aloud or filled in quickly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.database import get_db
from shared.logger import get_logger

log = get_logger("agent3.calls")

# The cold-call funnel, in the order a call actually moves through it.
# `terminal` marks an outcome that ends the lead's life on the queue, so the
# caller's list stays short and the dashboard can count what is still open.
CALL_STATUSES: dict[str, dict] = {
    "to_call":       {"label": "To call",          "terminal": False, "tone": "neutral"},
    "no_answer":     {"label": "No answer",        "terminal": False, "tone": "warn"},
    "call_back":     {"label": "Call back later",  "terminal": False, "tone": "warn"},
    "interested":    {"label": "Interested",       "terminal": False, "tone": "good"},
    "meeting_fixed": {"label": "Meeting fixed",    "terminal": True,  "tone": "good"},
    "not_interested": {"label": "Not interested",  "terminal": True,  "tone": "bad"},
    "wrong_number":  {"label": "Wrong number",     "terminal": True,  "tone": "bad"},
}
DEFAULT_STATUS = "to_call"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _leads():
    return get_db()["leads"]


def call_state(lead: dict) -> dict:
    """Our call-outreach state for this lead, or {} if never queued."""
    st = lead.get("call_outreach")
    return st if isinstance(st, dict) else {}


def is_queued(lead: dict) -> bool:
    return bool(call_state(lead).get("queued_at"))


def queue(lead_id: str, by: str = "") -> tuple[bool, str]:
    """Put a lead on the call queue. Idempotent.

    Queuing does not remove the lead from the WhatsApp desk: the CEO may still
    message them, and the caller needs to see that a message was already sent
    so he does not open the call by introducing the company twice.
    """
    lead = _leads().find_one({"id": lead_id})
    if not lead:
        return False, "Lead not found"
    if not (lead.get("phone") or "").strip():
        return False, "This lead has no phone number to call"
    if is_queued(lead):
        return True, "Already on the call list"

    _leads().update_one({"id": lead_id}, {"$set": {"call_outreach": {
        "status": DEFAULT_STATUS,
        "remarks": "",
        "queued_at": _now(),
        "queued_by": by,
        "calls_made": 0,
        "last_call_at": "",
        "history": [],
    }}})
    log.info("Queued %s for call outreach", lead.get("business_name", lead_id))
    return True, "Added to the call list"


def unqueue(lead_id: str) -> tuple[bool, str]:
    """Take a lead off the call queue, keeping its history for the record."""
    lead = _leads().find_one({"id": lead_id})
    if not lead or not is_queued(lead):
        return False, "That lead is not on the call list"
    st = call_state(lead)
    st["removed_at"] = _now()
    st["queued_at"] = ""          # what is_queued tests
    _leads().update_one({"id": lead_id}, {"$set": {"call_outreach": st}})
    return True, "Removed from the call list"


def update(lead_id: str, status: str = "", remarks: str | None = None,
           logged_call: bool = False, by: str = "") -> tuple[bool, str]:
    """Record what happened on a call.

    Every change is appended to `history` as well as replacing the current
    value. A caller who marks "not interested" by mistake, or a CEO asking why
    a lead was dropped, both need the trail — a single overwritten field
    answers neither.
    """
    lead = _leads().find_one({"id": lead_id})
    if not lead:
        return False, "Lead not found"
    st = call_state(lead)
    if not st:
        return False, "That lead is not on the call list"

    if status and status not in CALL_STATUSES:
        return False, f"Unknown call status '{status}'"

    entry: dict = {"at": _now(), "by": by}
    if status and status != st.get("status"):
        entry["status"] = status
        st["status"] = status
    if remarks is not None and remarks != st.get("remarks"):
        entry["remarks"] = remarks[:2000]
        st["remarks"] = remarks[:2000]
    if logged_call:
        st["calls_made"] = int(st.get("calls_made") or 0) + 1
        st["last_call_at"] = _now()
        st["last_call_day"] = _today()
        entry["called"] = True

    if len(entry) > 2:            # more than just at/by
        st.setdefault("history", []).append(entry)
        st["history"] = st["history"][-40:]
    st["updated_at"] = _now()

    _leads().update_one({"id": lead_id}, {"$set": {"call_outreach": st}})
    return True, "Saved"


def stats(day: str = "") -> dict:
    """Numbers for the caller's dashboard: today's work and what is open.

    Deliberately the handful of figures a caller can act on, not a full
    analytics page. "How many have I called today" and "how many are left"
    are the two that change behaviour.
    """
    day = day or _today()
    rows = list(_leads().find(
        {"call_outreach.queued_at": {"$nin": ["", None]}},
        {"call_outreach": 1, "business_name": 1}))

    by_status = {k: 0 for k in CALL_STATUSES}
    calls_today = 0
    open_count = 0
    for r in rows:
        st = r.get("call_outreach") or {}
        s = st.get("status") or DEFAULT_STATUS
        if s in by_status:
            by_status[s] += 1
        if st.get("last_call_day") == day:
            calls_today += 1
        if not CALL_STATUSES.get(s, {}).get("terminal"):
            open_count += 1

    return {
        "day": day,
        "total": len(rows),
        "open": open_count,
        "calls_today": calls_today,
        "by_status": by_status,
        "labels": {k: v["label"] for k, v in CALL_STATUSES.items()},
        "tones": {k: v["tone"] for k, v in CALL_STATUSES.items()},
    }
