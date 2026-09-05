"""Unified AI client — the single entry point every agent uses.

Given an agent_id, it looks up that agent's configured provider+model (from its
ai_config), enforces a per-provider rate limit, calls the provider, falls back to
the agent's secondary provider on failure, logs token usage + estimated cost, and
returns a normalized result. Provider keys are encrypted (same pattern as before)
and decrypted only here at call time.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from .database import get_db
from .logger import get_logger
from .providers import PROVIDERS, estimate_cost, provider_call, list_models
from .security import decrypt, encrypt, last_four

log = get_logger("ai_client")

DEFAULT_CONFIG = {"provider_id": "claude", "model": "claude-sonnet-5", "fallback_provider_id": None, "fallback_model": None}

# Per-provider requests-per-minute limits (in-process sliding window).
_RPM = defaultdict(lambda: 60)
_calls: dict[str, list[float]] = defaultdict(list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- provider settings storage --------------------------------------------
def _providers_col():
    return get_db()["ai_providers"]


def get_provider_record(provider_id: str) -> dict | None:
    return _providers_col().find_one({"provider_id": provider_id})


def get_provider_key(provider_id: str) -> str | None:
    rec = get_provider_record(provider_id)
    if rec and rec.get("api_key_encrypted"):
        try:
            return decrypt(rec["api_key_encrypted"])
        except Exception as exc:  # noqa: BLE001
            log.error("decrypt failed for provider %s: %s", provider_id, exc)
            return None
    # Backward-compat for Claude: fall back to the Phase 2/3 settings key + env.
    if provider_id == "claude":
        doc = get_db()["settings"].find_one({"key_name": "claude_api_key"})
        if doc and doc.get("encrypted_value"):
            try:
                return decrypt(doc["encrypted_value"])
            except Exception:  # noqa: BLE001
                pass
        return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    return None


def get_provider_base_url(provider_id: str) -> str:
    rec = get_provider_record(provider_id)
    if rec and rec.get("base_url"):
        return rec["base_url"]
    return PROVIDERS.get(provider_id, {}).get("base_url", "")


def save_provider(provider_id: str, key: str | None, base_url: str | None) -> None:
    updates: dict = {"provider_id": provider_id, "status": "connected", "last_tested_at": ""}
    if key:
        updates["api_key_encrypted"] = encrypt(key)
        updates["last_four"] = last_four(key)
    if base_url is not None:
        updates["base_url"] = base_url
    _providers_col().update_one({"provider_id": provider_id}, {"$set": updates}, upsert=True)


def delete_provider(provider_id: str) -> None:
    _providers_col().delete_one({"provider_id": provider_id})


def list_providers_public() -> list[dict]:
    stored = {d["provider_id"]: d for d in _providers_col().find({})}
    out = []
    for pid, meta in PROVIDERS.items():
        rec = stored.get(pid)
        has_key = bool((rec and rec.get("api_key_encrypted")) or (pid == "claude" and get_provider_key("claude")))
        out.append({
            "provider_id": pid, "display_name": meta["display_name"], "kind": meta["kind"],
            "needs_base_url": meta["needs_base_url"],
            "base_url": (rec.get("base_url") if rec else "") or meta["base_url"],
            "available_models": (rec.get("models") if rec and rec.get("models") else meta["models"]),
            "is_set": has_key,
            "last_four": rec.get("last_four", "") if rec else "",
            "status": ("connected" if has_key else "not_connected"),
            "last_tested_at": rec.get("last_tested_at", "") if rec else "",
        })
    return out


async def test_provider(provider_id: str, model: str | None = None) -> dict:
    key = get_provider_key(provider_id)
    if not key:
        return {"ok": False, "message": f"No API key set for {provider_id}."}
    meta = PROVIDERS.get(provider_id, {})
    base = get_provider_base_url(provider_id)
    if meta.get("needs_base_url") and not base:
        return {"ok": False, "message": "Set the Base URL for this OpenAI-compatible provider first."}
    m = model or (meta.get("models") or ["gpt-4o-mini"])[-1]
    res = await provider_call(provider_id, key, base, m, "ping", [{"role": "user", "content": "ping"}], 4)
    _providers_col().update_one({"provider_id": provider_id}, {"$set": {"last_tested_at": _now(), "status": "connected" if res["ok"] else "error"}}, upsert=True)
    return {"ok": res["ok"], "message": ("Connection OK." if res["ok"] else res["error"])}


async def list_provider_models(provider_id: str) -> dict:
    """Fetch selectable models for a provider using its saved key + base URL.
    Falls back to the built-in list on failure so the UI always has options."""
    meta = PROVIDERS.get(provider_id)
    builtin = list(meta.get("models") or []) if meta else []
    key = get_provider_key(provider_id)
    if not key:
        return {"ok": False, "models": builtin, "error": f"No API key set for {provider_id}."}
    base = get_provider_base_url(provider_id)
    if meta and meta.get("needs_base_url") and not base:
        return {"ok": False, "models": builtin, "error": "Set the Base URL first."}
    res = await list_models(provider_id, key, base)
    if res["ok"] and res["models"]:
        return res
    # keep built-ins visible if the fetch failed or returned nothing
    return {"ok": res["ok"], "models": res["models"] or builtin, "error": res["error"]}


# ---- rate limiting ---------------------------------------------------------
async def _rate_gate(provider_id: str) -> None:
    limit = _RPM[provider_id]
    now = time.time()
    window = [t for t in _calls[provider_id] if now - t < 60]
    if len(window) >= limit:
        wait = 60 - (now - window[0])
        if wait > 0:
            log.info("Rate limit for %s reached — waiting %.1fs", provider_id, wait)
            await asyncio.sleep(min(wait, 5))  # cap the wait so callers don't hang forever
    _calls[provider_id] = window + [time.time()]


# ---- usage logging ---------------------------------------------------------
def _log_usage(agent_id, provider_id, model, res, purpose, fallback):
    u = res.get("usage", {})
    get_db()["usage_log"].insert_one({
        "agent_id": agent_id, "provider_id": provider_id, "model": model,
        "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
        "est_cost": estimate_cost(model, u.get("input_tokens", 0), u.get("output_tokens", 0)),
        "purpose": purpose, "ok": res["ok"], "fallback": fallback, "at": _now(),
    })


# ---- agent config resolution ----------------------------------------------
def get_agent_config(agent_id: str) -> dict:
    agent = get_db()["agents"].find_one({"id": agent_id})
    cfg = (agent or {}).get("ai_config") or {}
    return {**DEFAULT_CONFIG, **cfg}


# ---- the one call every agent uses ----------------------------------------
async def call_ai(agent_id: str, system: str, messages: list[dict], max_tokens: int = 500, purpose: str = "chat") -> dict:
    """Route to the agent's provider, with fallback. Returns
    {ok, text, provider_used, model_used} or {ok:False, error, error_kind}."""
    cfg = get_agent_config(agent_id)
    attempts = [(cfg["provider_id"], cfg["model"], False)]
    if cfg.get("fallback_provider_id") and cfg.get("fallback_model"):
        attempts.append((cfg["fallback_provider_id"], cfg["fallback_model"], True))

    last = {"ok": False, "error": "No provider configured", "error_kind": "no_provider"}
    for provider_id, model, is_fallback in attempts:
        key = get_provider_key(provider_id)
        base = get_provider_base_url(provider_id)
        if not key:
            last = {"ok": False, "error": f"No API key configured for {provider_id} — add one in Settings → AI Providers.", "error_kind": "no_key"}
            _log_usage(agent_id, provider_id, model, {"ok": False, "usage": {}}, purpose, is_fallback)
            continue
        await _rate_gate(provider_id)
        res = await provider_call(provider_id, key, base, model, system, messages, max_tokens)
        _log_usage(agent_id, provider_id, model, res, purpose, is_fallback)
        if res["ok"]:
            log.info("AI call for %s served by %s/%s%s", agent_id, provider_id, model, " (fallback)" if is_fallback else "")
            return {"ok": True, "text": res["text"], "provider_used": provider_id, "model_used": model, "fallback_used": is_fallback}
        last = {"ok": False, "error": res["error"], "error_kind": res["error_kind"], "provider_used": provider_id}
        if is_fallback:
            log.warning("Fallback provider %s also failed for %s: %s", provider_id, agent_id, res["error"])
    return last
