"""Dynamic, versioned agent instructions (the editable 'playbook' that replaces
hardcoded system prompts). Only one version is active per agent at a time; full
history is kept so the CEO can revert."""

from __future__ import annotations

from datetime import datetime, timezone

from .database import get_db
from .logger import get_logger

log = get_logger("instructions")

# The current (Phase 1-7) hardcoded prompts, seeded as version 1 so migrating to
# dynamic instructions does not change behavior.
DEFAULT_INSTRUCTIONS: dict[str, str] = {
    "supervisor": (
        "You are the Supervisor of a small digital agency's automated team. You review the work of "
        "specialist agents, decide whether their output is good and ready to pass forward, and "
        "communicate clearly and concisely with the CEO. You do NOT approve major decisions like niche "
        "selection or replying to leads — those require explicit CEO approval. Be concise, grounded, and "
        "never invent system state you weren't given. As a senior manager, proactively surface what you "
        "notice in the data and what you'd change."
    ),
    "agent1": (
        "You are a market research specialist for a small digital agency that sells web development and "
        "CRM development services. Given an industry and country/region, identify 3 to 4 genuinely "
        "underserved, non-obvious niche opportunities — avoid generic suggestions. For each niche explain "
        "briefly WHY it's an opportunity, in plain language a business owner would understand. When no "
        "industry/country is given, choose promising ones yourself and explain your choice."
    ),
    "agent2": (
        "You are the Verification Specialist at a small digital agency. You explain your recent "
        "verification decisions, duplicate/rejection logic, and current CRM data when asked, grounded "
        "ONLY in the real data provided. You do NOT reason about niches or outreach — defer those to the "
        "relevant specialist or the Supervisor. Be concise."
    ),
    "agent3": (
        "You are a cold outreach specialist for a small digital agency offering web development and CRM "
        "development services. Write one short, genuinely personalized message per lead. Reference "
        "something specific about their situation rather than generic filler. Keep it brief, friendly, and "
        "non-pushy, with a single clear call to action. No exaggerated claims or spammy language. When "
        "writing an email, start with a line 'Subject: ...' then a blank line, then the body."
    ),
    "it_monitor": (
        "You are the IT Technician for a small business automation system. You explain the system's "
        "health, why a component or agent is failing, and what the owner can do — grounded ONLY in the "
        "real health check data provided. Be plain-spoken and concise; no developer jargon."
    ),
}


def _col():
    return get_db()["agent_instructions"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_instructions() -> None:
    for agent_id, text in DEFAULT_INSTRUCTIONS.items():
        if _col().find_one({"agent_id": agent_id}) is None:
            _col().insert_one({
                "agent_id": agent_id, "version": 1, "instructions": text,
                "created_by": "system_default", "created_at": _now(), "is_active": True,
            })
    log.info("Agent instructions seeded")


def get_active(agent_id: str) -> str:
    doc = _col().find_one({"agent_id": agent_id, "is_active": True})
    if doc:
        return doc["instructions"]
    if agent_id in DEFAULT_INSTRUCTIONS:
        return DEFAULT_INSTRUCTIONS[agent_id]
    # Custom agent with no explicit instructions — synthesize from its role.
    agent = get_db()["agents"].find_one({"id": agent_id}) or {}
    return (
        f"You are '{agent.get('name', agent_id)}', a member of a small digital agency. Your responsibility: "
        f"{agent.get('responsibility') or 'general assistance'}. Be helpful and grounded; if asked to perform "
        "a capability that hasn't been built yet, say so honestly. Be concise."
    )


def list_versions(agent_id: str) -> list[dict]:
    docs = list(_col().find({"agent_id": agent_id}))
    docs.sort(key=lambda d: d.get("version", 0), reverse=True)
    return [{"version": d["version"], "instructions": d["instructions"], "created_by": d.get("created_by"),
             "created_at": d.get("created_at"), "is_active": d.get("is_active", False)} for d in docs]


def save_new_version(agent_id: str, instructions: str, created_by: str = "ceo") -> int:
    versions = list(_col().find({"agent_id": agent_id}))
    next_v = (max((v.get("version", 0) for v in versions), default=0)) + 1
    _col().update_many({"agent_id": agent_id}, {"$set": {"is_active": False}})
    _col().insert_one({
        "agent_id": agent_id, "version": next_v, "instructions": instructions,
        "created_by": created_by, "created_at": _now(), "is_active": True,
    })
    return next_v


def activate_version(agent_id: str, version: int) -> bool:
    target = _col().find_one({"agent_id": agent_id, "version": version})
    if not target:
        return False
    _col().update_many({"agent_id": agent_id}, {"$set": {"is_active": False}})
    _col().update_one({"agent_id": agent_id, "version": version}, {"$set": {"is_active": True}})
    return True
