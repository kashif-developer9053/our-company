"""Central prompt assembly — every agent call is grounded here.

build_system() composes an agent's full system prompt from: its ACTIVE editable
instructions + its persistent memory (role summary, key facts, recent activity) +
the most relevant knowledge-base entries + (for research/outreach agents) the
company profile. The chosen AI provider then only reasons over what this feeds it.
"""

from __future__ import annotations

from . import agent_memory, company_profile, instructions, knowledge_base
from .ai_client import call_ai
from .database import get_db


def _agent(agent_id: str) -> dict:
    return get_db()["agents"].find_one({"id": agent_id}) or {}


def build_system(agent_id: str, task_hint: str = "", draft_instructions: str | None = None) -> str:
    a = _agent(agent_id)
    role = a.get("role_key", "")
    instr = draft_instructions if draft_instructions is not None else instructions.get_active(agent_id)
    mem = agent_memory.get_memory(agent_id)
    kb = knowledge_base.relevant_context(agent_id, task_hint)
    include_company = role in ("researcher", "outreach") or agent_id in ("agent1", "agent3")

    parts = [instr]
    if mem.get("role_summary"):
        parts.append(f"WHO YOU ARE: {mem['role_summary']}")
    if mem.get("key_facts"):
        parts.append("KEY FACTS TO REMEMBER:\n- " + "\n- ".join(mem["key_facts"][-12:]))
    if mem.get("recent_activity"):
        acts = mem["recent_activity"][-6:]
        parts.append("YOUR RECENT ACTIVITY:\n" + "\n".join(f"- {x['timestamp'][:16]}: {x['summary']}" for x in acts))
    if kb:
        parts.append("KNOWLEDGE BASE (use if relevant to the task):\n" + kb)
    if include_company:
        comp = company_profile.profile_as_context()
        if comp:
            parts.append("COMPANY PROFILE (ground your output in this real business):\n" + comp)
    return "\n\n".join(parts)


CHAT_HISTORY_WINDOW = 12  # recent turns fed back to the provider


async def agent_chat(agent_id: str, message: str, history: list[dict], session_id: str = "default",
                     extra_context: str | None = None, max_tokens: int = 500) -> dict:
    system = build_system(agent_id, message)

    # READ PATH: load the REAL persisted conversation for this session from
    # MongoDB — this is what survives new browser sessions and backend restarts.
    # The client-passed `history` is only a live convenience; the DB is truth.
    persisted, older_summary = agent_memory.get_session_messages(agent_id, session_id)
    prior = persisted if persisted else (history or [])

    messages: list[dict] = []
    if extra_context:
        messages.append({"role": "user", "content": extra_context})
    # If older turns were trimmed & summarized, hand the AI that real content
    # summary so long conversations still recall substance, not just "we talked".
    if older_summary:
        messages.append({"role": "user", "content": f"(Summary of earlier in this conversation: {older_summary})"})
    for m in prior[-CHAT_HISTORY_WINDOW:]:
        messages.append({"role": "assistant" if m.get("role") in ("agent", "assistant") else "user",
                         "content": str(m.get("content", ""))})
    messages.append({"role": "user", "content": message})

    res = await call_ai(agent_id, system, messages, max_tokens, purpose="chat")
    if res["ok"]:
        agent_memory.add_conversation(agent_id, session_id, "user", message)
        agent_memory.add_conversation(agent_id, session_id, "agent", res["text"])
        agent_memory.add_activity(agent_id, "Chatted with the CEO")
    return res


async def agent_task(agent_id: str, user_prompt: str, task_hint: str = "", max_tokens: int = 900,
                     purpose: str = "task", activity: str | None = None, draft_instructions: str | None = None) -> dict:
    system = build_system(agent_id, task_hint or user_prompt, draft_instructions=draft_instructions)
    res = await call_ai(agent_id, system, [{"role": "user", "content": user_prompt}], max_tokens, purpose)
    if res["ok"] and activity:
        agent_memory.add_activity(agent_id, activity)
    return res
