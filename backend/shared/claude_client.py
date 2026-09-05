"""Backward-compatible Claude helper — now a thin layer over the unified
multi-provider client. Existing callers (IT diagnosis, agent code-gen) keep
working unchanged; new agent code uses ai_client.call_ai(agent_id, ...)."""

from __future__ import annotations

import asyncio

from .ai_client import get_provider_base_url, get_provider_key, test_provider
from .logger import get_logger
from .providers import provider_call

log = get_logger("claude_client")

DEFAULT_MODEL = "claude-sonnet-5"
_MAX_RETRIES = 2


def get_claude_key() -> str | None:
    return get_provider_key("claude")


def key_status() -> dict:
    return {"configured": get_claude_key() is not None}


async def call_claude(system: str, messages: list[dict], max_tokens: int = 1024, model: str = DEFAULT_MODEL) -> dict:
    """Direct Claude call (used by non-agent-scoped features like IT diagnosis and
    code generation). Retries transient failures. Returns {ok, text|error, error_kind}."""
    key = get_claude_key()
    if not key:
        return {"ok": False, "error": "No Claude API key configured — add one in Settings.", "error_kind": "no_key"}
    base = get_provider_base_url("claude")
    last = {"ok": False, "error": "unknown", "error_kind": "unknown"}
    for attempt in range(_MAX_RETRIES + 1):
        res = await provider_call("claude", key, base, model, system, messages, max_tokens)
        if res["ok"]:
            return {"ok": True, "text": res["text"]}
        last = {"ok": False, "error": res["error"], "error_kind": res["error_kind"]}
        if res["error_kind"] in ("invalid_key", "unknown"):
            break  # non-transient
        if attempt < _MAX_RETRIES:
            await asyncio.sleep(0.6 * (attempt + 1))
    return last


async def test_connection() -> dict:
    return await test_provider("claude")
