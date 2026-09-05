"""IT Technician API — runs health checks, rolls up status, generates diagnosis,
and updates the office status board. Fully safe-wrapped."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.deps import require_admin
from shared.claude_client import call_claude
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

from .health import (
    check_agents,
    check_claude,
    check_error_spike,
    check_imap,
    check_mongo,
    check_smtp,
    rollup,
)

log = get_logger("it_monitor")
router = APIRouter(prefix="/it-monitor", tags=["it_monitor"])

DIAG_SYSTEM = (
    "You are an IT support specialist for a small internal business automation system. Given health "
    "check data, explain in plain, non-technical language what appears to be wrong, and suggest one or "
    "two concrete, specific steps the business owner (not a developer) could take to fix it. Be brief."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_it_status(overall: str, task: str) -> None:
    # 🟢 ok / 🟡 warning / 🔴 risk map directly onto the IT agent's status.
    get_db()["agents"].update_one({"id": "it_monitor"}, {"$set": {"status": overall, "task": task}})


def _fallback_diagnosis(components: dict) -> str:
    lines = []
    c = components
    if c["claude_api"]["status"] in ("fail", "unconfigured"):
        lines.append("• The Claude AI connection isn't working — go to Settings and add or refresh your Claude API key.")
    if c["mongodb"]["status"] == "fail":
        lines.append("• The database isn't responding — check that your database service is running and its connection string is correct.")
    if c["smtp"]["status"] == "fail":
        lines.append("• Email sending failed to sign in — your Gmail app password may be wrong or expired; generate a new one in Settings → Email Sending.")
    elif c["smtp"]["status"] == "unconfigured":
        lines.append("• Email sending isn't set up yet — add your Gmail address + app password in Settings.")
    if c["imap"]["status"] == "fail":
        lines.append("• Reading replies failed to sign in — refresh the Gmail app password for the inbox in Settings → Email Inbox.")
    elif c["imap"]["status"] == "unconfigured":
        lines.append("• Reading replies isn't set up yet — add the inbox credentials in Settings.")
    for a in c.get("agents", []):
        if a["status"] in ("error", "risk"):
            mins = a.get("stuck_minutes", 0)
            lines.append(f"• {a['name']} has been in an error state for ~{mins} min — open it to see the specific error; it may recover on its next run.")
    if c.get("error_spike", {}).get("spike"):
        lines.append("• There's been an unusual spike in errors recently — review recent activity.")
    return "\n".join(lines) or "Something needs attention — see the component breakdown."


async def run_health_check() -> dict:
    """Run all checks, roll up, diagnose if needed, persist, update status board.
    Never raises."""
    try:
        components = {
            "claude_api": await check_claude(),
            "mongodb": check_mongo(),
            "smtp": check_smtp(),
            "imap": check_imap(),
            "agents": check_agents(),
            "error_spike": check_error_spike(),
        }
        overall = rollup(components)

        # Diagnosis only when NOT ok. If Claude itself is up, ask it; otherwise
        # (Claude is the thing that's down) fall back to a rule-based explanation.
        if overall == "ok":
            explanation = "All systems normal."
        elif components["claude_api"]["status"] == "ok":
            res = await call_claude(DIAG_SYSTEM, [{"role": "user", "content": json.dumps(components, default=str)}], max_tokens=400)
            explanation = res["text"] if res["ok"] else _fallback_diagnosis(components)
        else:
            explanation = _fallback_diagnosis(components)

        record = {
            "id": f"hc_{uuid.uuid4().hex[:8]}",
            "overall": overall, "checked_at": _now(),
            "components": components, "explanation": explanation, "created_at": _now(),
        }
        get_db()["health_checks"].insert_one(dict(record))

        task = {"ok": "All systems normal", "warning": "Warning — needs attention", "risk": "Risk — action needed"}[overall]
        _set_it_status(overall, task)

        record.pop("_id", None)
        return record
    except Exception as exc:  # noqa: BLE001 - the monitor itself must never crash the app
        log.error("Health check job failed (isolated): %s", exc)
        return {"overall": "unknown", "checked_at": _now(), "components": {}, "explanation": f"Health check error: {exc}"}


def _latest() -> dict | None:
    docs = list(get_db()["health_checks"].find({}))
    if not docs:
        return None
    docs.sort(key=lambda d: d.get("checked_at", ""), reverse=True)
    d = docs[0]
    d.pop("_id", None)
    return d


@router.get("/status")
@safe_endpoint("it_monitor")
async def get_status():
    latest = _latest()
    if latest is None:
        latest = await run_health_check()  # run one on first request
    return {"ok": True, "health": latest}


@router.post("/check")
@safe_endpoint("it_monitor")
async def check_now():
    return {"ok": True, "health": await run_health_check()}


CHAT_SYSTEM = (
    "You are the IT Technician for a small business automation system. You explain the system's health, "
    "why a component or agent is failing, and what the owner can do — grounded ONLY in the real health "
    "check data provided. Be plain-spoken and concise; no developer jargon."
)


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/chat")
@safe_endpoint("it_monitor")
async def chat(body: ChatBody):
    from shared.ai_context import agent_chat
    latest = _latest() or await run_health_check()
    ctx = json.dumps({"overall": latest.get("overall"), "components": latest.get("components"), "explanation": latest.get("explanation")}, default=str)
    res = await agent_chat("it_monitor", body.message, body.history, extra_context=f"(Latest health check, use only these facts: {ctx})", max_tokens=450)
    if res["ok"]:
        return {"ok": True, "reply": res["text"]}
    return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}


# ============================================================================
# Phase 8 — IT Technician builds NEW agents (admin-only, CEO-approved).
# ============================================================================
import uuid as _uuid  # noqa: E402

from .agent_builder import build_agent, deploy_agent, reject_request  # noqa: E402


class NewAgentRequest(BaseModel):
    agent_name: str
    description: str
    needs_reasoning: bool = True


class RejectBody(BaseModel):
    feedback: str = ""


def _serialize_req(d: dict) -> dict:
    return {k: d.get(k) for k in (
        "request_id", "agent_name", "description_given", "status", "files_added", "files_modified",
        "test_results", "warnings", "overall_ready", "generated_at", "feedback", "live_agent_id", "deployed_file",
    )}


@router.post("/request-new-agent")
@safe_endpoint("it_monitor")
async def request_new_agent(body: NewAgentRequest, _: dict = Depends(require_admin)):
    request_id = f"req_{_uuid.uuid4().hex[:8]}"
    get_db()["agent_build_requests"].insert_one({
        "request_id": request_id, "agent_name": body.agent_name.strip(),
        "description_given": body.description.strip(), "status": "building",
        "test_results": [], "warnings": [], "overall_ready": False, "generated_at": _now(),
    })
    # Background build — returns immediately.
    asyncio.create_task(build_agent(request_id, body.agent_name.strip(), body.description.strip(), body.needs_reasoning))
    return {"ok": True, "request_id": request_id, "message": "IT Technician is working on this — you'll get a report when it's ready."}


@router.get("/agent-requests")
@safe_endpoint("it_monitor")
async def list_agent_requests(_: dict = Depends(require_admin)):
    docs = list(get_db()["agent_build_requests"].find({}))
    docs.sort(key=lambda d: d.get("generated_at", ""), reverse=True)
    return {"ok": True, "requests": [_serialize_req(d) for d in docs]}


@router.post("/agent-requests/{request_id}/approve")
@safe_endpoint("it_monitor")
async def approve_request(request_id: str, _: dict = Depends(require_admin)):
    doc = get_db()["agent_build_requests"].find_one({"request_id": request_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if doc.get("status") == "approved":
        raise HTTPException(status_code=400, detail="Already approved")
    agent = deploy_agent(request_id)
    return {"ok": True, "message": f"New agent '{agent['name']}' is now live.", "agent": agent}


@router.post("/agent-requests/{request_id}/reject")
@safe_endpoint("it_monitor")
async def reject_agent_request(request_id: str, body: RejectBody, _: dict = Depends(require_admin)):
    doc = get_db()["agent_build_requests"].find_one({"request_id": request_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Request not found")
    reject_request(request_id, body.feedback)
    return {"ok": True, "message": "Request rejected — nothing was applied to the live app."}
