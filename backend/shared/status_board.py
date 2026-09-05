"""The live status board — the single source of truth the office UI reads.

Holds office_open / meeting_in_progress, and composes the current agent list
(from the dynamic registry) into one status object. Exposed via /status routes
(the frontend polls these for live updates).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from agents.agent_registry import list_agents
from shared.database import get_db, backend_name
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

log = get_logger("status")
router = APIRouter(prefix="/status", tags=["status"])

_BOARD_ID = "singleton"


def _col():
    return get_db()["status_board"]


def get_board() -> dict:
    doc = _col().find_one({"_id": _BOARD_ID})
    if doc is None:
        doc = {"_id": _BOARD_ID, "office_open": False, "meeting_in_progress": False}
        _col().insert_one(dict(doc))
    return {
        "office_open": doc.get("office_open", False),
        "meeting_in_progress": doc.get("meeting_in_progress", False),
    }


def build_status() -> dict:
    board = get_board()
    agents = {a["id"]: a for a in list_agents()}
    return {
        "office_open": board["office_open"],
        "meeting_in_progress": board["meeting_in_progress"],
        "agents": agents,
        "backend": backend_name(),
    }


def _set_all_agents_active(active: bool) -> None:
    """On open: wake offline agents (idle, or 'ok' for IT). On close: all offline.
    Manual statuses (working/error/...) are preserved on open."""
    agents = get_db()["agents"]
    for a in agents.find({}):
        if active:
            if a.get("status") == "offline":
                new = "ok" if a.get("role_key") == "it_monitor" else "idle"
                agents.update_one({"id": a["id"]}, {"$set": {"status": new}})
        else:
            agents.update_one({"id": a["id"]}, {"$set": {"status": "offline"}})


class OfficeToggle(BaseModel):
    open: bool


class MeetingToggle(BaseModel):
    in_progress: bool


@router.get("")
@safe_endpoint("status")
async def get_status():
    return {"ok": True, "status": build_status()}


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@router.post("/office")
@safe_endpoint("status")
async def set_office(body: OfficeToggle):
    updates: dict = {"office_open": body.open}
    meeting_started = False
    if body.open:
        board = _col().find_one({"_id": _BOARD_ID}) or {}
        # The daily meeting triggers ONLY on the first open of each calendar day.
        if board.get("last_meeting_date") != _today():
            updates["meeting_in_progress"] = True
            updates["last_meeting_date"] = _today()
            meeting_started = True
    else:
        updates["meeting_in_progress"] = False
    _col().update_one({"_id": _BOARD_ID}, {"$set": updates}, upsert=True)
    _set_all_agents_active(body.open)

    if meeting_started:
        # Supervisor gathers a REAL standup summary from every agent's data.
        from supervisor.supervisor_routes import build_standup, phrase_standup
        standup = build_standup()
        standup["summary"] = await phrase_standup(standup["reports"])
        get_db()["standups"].update_one({"date": standup["date"]}, {"$set": standup}, upsert=True)
        log.info("Daily meeting started + standup generated for %s", standup["date"])

    log.info("Office %s", "opened" if body.open else "closed")
    return {"ok": True, "meeting_started": meeting_started, "status": build_status()}


@router.post("/meeting")
@safe_endpoint("status")
async def set_meeting(body: MeetingToggle):
    _col().update_one(
        {"_id": _BOARD_ID}, {"$set": {"meeting_in_progress": body.in_progress}}, upsert=True
    )
    return {"ok": True, "status": build_status()}
