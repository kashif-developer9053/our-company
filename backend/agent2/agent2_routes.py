"""Agent 2 (Verifier) chat — a real Claude conversation grounded in the actual
CRM/verification data. Agent 2's verification work itself stays deterministic
(no Claude); this is only for talking to the CEO."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from shared.ai_context import agent_chat
from shared.database import get_db
from shared.safe_wrapper import safe_endpoint

router = APIRouter(prefix="/agent2", tags=["agent2"])

SYSTEM = (
    "You are the Verification Specialist at a small digital agency. You explain your recent verification "
    "decisions, duplicate/rejection logic, and current CRM data when asked, grounded ONLY in the real "
    "data provided. You do NOT reason about niches or outreach — politely defer those to the relevant "
    "specialist or the Supervisor. Be concise."
)


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


def _context() -> str:
    leads = list(get_db()["leads"].find({}))
    def c(s): return sum(1 for l in leads if l.get("status") == s)
    rejected = list(get_db()["leads"].find({"status": "rejected"}))
    reasons: dict = {}
    for r in rejected:
        reasons[r.get("rejection_reason", "?")] = reasons.get(r.get("rejection_reason", "?"), 0) + 1
    return (
        f"REAL DATA — verified in CRM: {c('verified')}; mailed: {c('mailed')}; "
        f"rejected: {len(rejected)} ({reasons or 'none'}); total leads: {len(leads)}."
    )


@router.post("/chat")
@safe_endpoint("agent2")
async def chat(body: ChatBody):
    res = await agent_chat("agent2", body.message, body.history, extra_context=f"(Context, use only these facts: {_context()})", max_tokens=450)
    if res["ok"]:
        return {"ok": True, "reply": res["text"]}
    return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}
