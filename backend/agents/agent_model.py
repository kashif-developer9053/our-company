"""Agent data model + role metadata for the dynamic agent registry."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Fixed internal role types. "custom" is for CEO-added agents.
ROLE_KEYS = ["supervisor", "researcher", "verifier", "outreach", "it_monitor", "custom"]

VALID_STATUSES = [
    "offline",
    "idle",
    "working",
    "error",
    "in_meeting",
    "in_ceo_office",
    "ok",
    "warning",
    "risk",
]


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    responsibility: str = Field(default="", max_length=400)
    role_key: str = "custom"


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    responsibility: Optional[str] = Field(default=None, max_length=400)
    role_key: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None


def serialize(doc: dict) -> dict:
    """Strip Mongo's _id and return a clean JSON-safe agent object."""
    return {
        "id": doc["id"],
        "name": doc["name"],
        "role_key": doc["role_key"],
        "responsibility": doc.get("responsibility", ""),
        "status": doc.get("status", "offline"),
        "location": doc.get("location", ""),
        "is_default": doc.get("is_default", False),
        "task": doc.get("task", ""),  # live task description (set during pipeline work)
        "ai_config": doc.get("ai_config") or {
            "provider_id": "claude", "model": "claude-sonnet-5",
            "fallback_provider_id": None, "fallback_model": None,
        },
        "created_at": doc.get("created_at", ""),
    }


class AiConfig(BaseModel):
    provider_id: str
    model: str
    fallback_provider_id: Optional[str] = None
    fallback_model: Optional[str] = None


# The 5 original agents. Seeded once; these are editable but NOT deletable.
DEFAULT_AGENTS = [
    {"id": "supervisor", "name": "Supervisor", "role_key": "supervisor",
     "responsibility": "Reviews all agents' work, approves/rejects steps, compiles reports for the CEO.",
     "location": "supervisor_room"},
    {"id": "agent1", "name": "Agent 1", "role_key": "researcher",
     "responsibility": "Finds 3-4 unique niches, then scrapes leads for the approved niche.",
     "location": "desk_1"},
    {"id": "agent2", "name": "Agent 2", "role_key": "verifier",
     "responsibility": "Verifies leads are real and not duplicates, stores them in the CRM.",
     "location": "desk_2"},
    {"id": "agent3", "name": "Agent 3", "role_key": "outreach",
     "responsibility": "Writes and sends personalized cold emails, later cold-calls, handles replies.",
     "location": "desk_3"},
    {"id": "it_monitor", "name": "IT Tech", "role_key": "it_monitor",
     "responsibility": "Monitors health of every module and suggests fixes without stopping the app.",
     "location": "it_room"},
]
