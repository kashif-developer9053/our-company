"""Database-backed agent registry + CRUD routes.

Agents are dynamic: the CEO can rename them, edit responsibilities, add custom
agents, and delete custom ones — all via the API, no code changes. Default
agents are protected from deletion in the backend so the UI can't bypass it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from shared.claude_client import call_claude
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

from auth.deps import require_admin
from shared import instructions as instr_mod

from .agent_model import (
    DEFAULT_AGENTS,
    ROLE_KEYS,
    VALID_STATUSES,
    AiConfig,
    AgentCreate,
    AgentUpdate,
    serialize,
)

log = get_logger("agents")
router = APIRouter(prefix="/agents", tags=["agents"])


def _col():
    return get_db()["agents"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_defaults() -> None:
    """Insert the 5 default agents if they're missing (idempotent)."""
    col = _col()
    for a in DEFAULT_AGENTS:
        if col.find_one({"id": a["id"]}) is None:
            col.insert_one({
                **a,
                "status": "offline",
                "is_default": True,
                "created_at": _now(),
            })
    log.info("Agent registry seeded (%d agents present)", col.count_documents({}))


def list_agents() -> list[dict]:
    # Defaults first (stable order), then custom agents by creation time.
    docs = list(_col().find({}))
    docs.sort(key=lambda d: (0 if d.get("is_default") else 1, d.get("created_at", "")))
    return [serialize(d) for d in docs]


def get_agent(agent_id: str) -> dict | None:
    doc = _col().find_one({"id": agent_id})
    return serialize(doc) if doc else None


# ---- routes ----------------------------------------------------------------
@router.get("")
@safe_endpoint("agents")
async def get_agents():
    return {"ok": True, "agents": list_agents()}


@router.post("")
@safe_endpoint("agents")
async def create_agent(body: AgentCreate):
    role_key = body.role_key if body.role_key in ROLE_KEYS else "custom"
    # If the office is already open, the new agent walks straight in (idle);
    # otherwise it stays offline until the office opens.
    board = get_db()["status_board"].find_one({"_id": "singleton"})
    initial_status = "idle" if (board and board.get("office_open")) else "offline"
    agent = {
        "id": f"custom_{uuid.uuid4().hex[:8]}",
        "name": body.name.strip(),
        "role_key": role_key,
        "responsibility": body.responsibility.strip(),
        "status": initial_status,
        "location": "employee_room",
        "is_default": False,
        "created_at": _now(),
    }
    _col().insert_one(dict(agent))
    log.info("Created custom agent %s (%s)", agent["id"], agent["name"])
    return {"ok": True, "agent": serialize(agent)}


@router.put("/{agent_id}")
@safe_endpoint("agents")
async def update_agent(agent_id: str, body: AgentUpdate):
    col = _col()
    doc = col.find_one({"id": agent_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.responsibility is not None:
        updates["responsibility"] = body.responsibility.strip()
    if body.role_key is not None and body.role_key in ROLE_KEYS:
        updates["role_key"] = body.role_key
    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
        updates["status"] = body.status
    if body.location is not None:
        updates["location"] = body.location

    if updates:
        col.update_one({"id": agent_id}, {"$set": updates})
    return {"ok": True, "agent": get_agent(agent_id)}


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/{agent_id}/chat")
@safe_endpoint("agents")
async def chat_with_agent(agent_id: str, body: ChatBody):
    """Generic chat for CEO-added CUSTOM agents, using their stored responsibility
    as the system prompt. (Default agents have their own dedicated chat endpoints.)"""
    doc = _col().find_one({"id": agent_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    system = (
        f"You are '{doc.get('name')}', a team member at a small digital agency. Your stated "
        f"responsibility is: \"{doc.get('responsibility') or 'general assistance'}\". Act as a helpful "
        "assistant grounded in that role. If asked to actually PERFORM a task, honestly note that this "
        "capability hasn't been built yet for this agent. Be concise."
    )
    from shared.ai_context import agent_chat
    res = await agent_chat(agent_id, body.message, body.history, max_tokens=450)
    if res["ok"]:
        return {"ok": True, "reply": res["text"]}
    return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}


# ---- Phase 10: per-agent AI config + editable instructions -----------------
@router.put("/{agent_id}/ai-config")
@safe_endpoint("agents")
async def set_ai_config(agent_id: str, body: AiConfig):
    if _col().find_one({"id": agent_id}) is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Reject unknown providers. Model ids are namespaced (e.g. "nvidia/nemotron",
    # "openai/gpt-4o-mini"), and that namespace has previously leaked into the
    # provider field — saving a config that fails every call with
    # "Unknown provider 'nvidia'". Catch it here instead of at run time.
    from shared.providers import PROVIDERS

    cfg = body.model_dump()
    valid = sorted(PROVIDERS.keys())
    for field in ("provider_id", "fallback_provider_id"):
        pid = cfg.get(field)
        if pid and pid not in PROVIDERS:
            hint = ""
            if "/" in str(cfg.get("model", "")) and pid == str(cfg["model"]).split("/")[0]:
                hint = (f" It looks like the model's namespace was used as the provider — for "
                        f"'{cfg['model']}' on OpenRouter the provider should be 'agent_router'.")
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider '{pid}'. Valid providers: {', '.join(valid)}.{hint}")
    _col().update_one({"id": agent_id}, {"$set": {"ai_config": cfg}})
    return {"ok": True, "agent": get_agent(agent_id)}


@router.get("/{agent_id}/instructions")
@safe_endpoint("agents")
async def get_instructions(agent_id: str):
    return {"ok": True, "active": instr_mod.get_active(agent_id), "versions": instr_mod.list_versions(agent_id)}


class InstrBody(BaseModel):
    instructions: str


@router.post("/{agent_id}/instructions")
@safe_endpoint("agents")
async def save_instructions(agent_id: str, body: InstrBody, _: dict = Depends(require_admin)):
    v = instr_mod.save_new_version(agent_id, body.instructions.strip(), created_by="ceo")
    return {"ok": True, "version": v}


class ActivateBody(BaseModel):
    version: int


@router.post("/{agent_id}/instructions/activate")
@safe_endpoint("agents")
async def activate_instructions(agent_id: str, body: ActivateBody, _: dict = Depends(require_admin)):
    if not instr_mod.activate_version(agent_id, body.version):
        raise HTTPException(status_code=404, detail="Version not found")
    return {"ok": True, "active_version": body.version}


class TestDraftBody(BaseModel):
    draft_instructions: str
    sample_message: str


@router.post("/{agent_id}/instructions/test")
@safe_endpoint("agents")
async def test_draft_instructions(agent_id: str, body: TestDraftBody, _: dict = Depends(require_admin)):
    # Run a sample against DRAFT instructions without saving them (test-before-live).
    from shared.ai_context import agent_task
    res = await agent_task(agent_id, body.sample_message, max_tokens=400, purpose="instr_test", draft_instructions=body.draft_instructions)
    return {"ok": res["ok"], "output": res.get("text", ""), "error": res.get("error")}


@router.delete("/{agent_id}")
@safe_endpoint("agents")
async def delete_agent(agent_id: str):
    col = _col()
    doc = col.find_one({"id": agent_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Backend-enforced: default/core agents can be edited but never deleted.
    if doc.get("is_default"):
        raise HTTPException(status_code=403, detail="Default agents cannot be deleted, only edited.")
    col.delete_one({"id": agent_id})
    log.info("Deleted custom agent %s", agent_id)
    return {"ok": True, "deleted": agent_id}
