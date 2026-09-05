"""Settings API — securely store/read API keys + email credentials.

Secret values (Claude key, app passwords) are Fernet-encrypted and never
returned in full (masked preview only). Non-secret values (email addresses) may
be shown in full. Test Connection actions verify Claude / SMTP / IMAP.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.claude_client import test_connection as test_claude_conn
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint
from shared.security import decrypt, encrypt, encryption_secret_is_set, last_four
from shared.settings_store import get_config, set_config

from .settings_model import SUPPORTED_KEYS, SUPPORTED_KEY_NAMES, ConfigWrite, SettingWrite

log = get_logger("settings")
router = APIRouter(prefix="/settings", tags=["settings"])


def _col():
    return get_db()["settings"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
@safe_endpoint("settings")
async def get_settings():
    """Which keys are set + a preview. Secret keys are masked; non-secret keys
    (emails) return their full value. NEVER returns a secret's real value."""
    stored = {d["key_name"]: d for d in _col().find({})}
    out = []
    for k in SUPPORTED_KEYS:
        doc = stored.get(k["key_name"])
        is_set = doc is not None and bool(doc.get("encrypted_value"))
        value = ""
        masked = ""
        if is_set:
            if k["secret"]:
                masked = "••••••••"
            else:
                # Non-secret (email address) — safe to reveal.
                try:
                    value = decrypt(doc["encrypted_value"])
                except Exception:  # noqa: BLE001
                    value = ""
                masked = value
        out.append({
            "key_name": k["key_name"], "label": k["label"], "group": k["group"],
            "secret": k["secret"], "testable": k["testable"],
            "is_set": is_set, "value": value, "masked": masked,
            "updated_at": doc.get("updated_at", "") if doc else "",
        })
    return {
        "ok": True, "keys": out,
        "config": get_config(),
        "encryption_secret_set": encryption_secret_is_set(),
    }


@router.post("")
@safe_endpoint("settings")
async def save_setting(body: SettingWrite):
    if body.key_name not in SUPPORTED_KEY_NAMES:
        raise HTTPException(status_code=400, detail=f"Unsupported key: {body.key_name}")
    raw = body.value.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty value")
    _col().update_one(
        {"key_name": body.key_name},
        {"$set": {
            "key_name": body.key_name, "encrypted_value": encrypt(raw),
            "last_four": last_four(raw), "updated_at": _now(),
        }},
        upsert=True,
    )
    log.info("Stored key '%s'", body.key_name)
    return {"ok": True, "key_name": body.key_name}


@router.delete("/{key_name}")
@safe_endpoint("settings")
async def delete_setting(key_name: str):
    _col().delete_one({"key_name": key_name})
    log.info("Removed key '%s'", key_name)
    return {"ok": True, "deleted": key_name}


@router.post("/imap-same-as-smtp")
@safe_endpoint("settings")
async def imap_same_as_smtp():
    """Copy the stored SMTP email + app password into the IMAP slots (server-side,
    so the secret password never needs to travel to the browser)."""
    from shared.settings_store import get_setting_value
    email_v = get_setting_value("smtp_email")
    pw_v = get_setting_value("smtp_app_password")
    if not email_v or not pw_v:
        raise HTTPException(status_code=400, detail="Set the sending (SMTP) email + password first")
    for name, val in (("imap_email", email_v), ("imap_app_password", pw_v)):
        _col().update_one({"key_name": name}, {"$set": {
            "key_name": name, "encrypted_value": encrypt(val), "last_four": last_four(val), "updated_at": _now(),
        }}, upsert=True)
    return {"ok": True}


@router.get("/config")
@safe_endpoint("settings")
async def read_config():
    return {"ok": True, "config": get_config()}


@router.post("/config")
@safe_endpoint("settings")
async def write_config(body: ConfigWrite):
    return {"ok": True, "config": set_config(body.daily_send_cap)}


# ---- Test Connection actions ----------------------------------------------
@router.post("/test/claude")
@safe_endpoint("settings")
async def test_claude():
    result = await test_claude_conn()
    return {"ok": result["ok"], "message": result["message"]}


@router.post("/test/smtp")
@safe_endpoint("settings")
async def test_smtp_route():
    from agent3.mailer import test_smtp
    import asyncio
    return await asyncio.to_thread(test_smtp)


@router.post("/test/imap")
@safe_endpoint("settings")
async def test_imap_route():
    from agent3.mailer import test_imap
    import asyncio
    return await asyncio.to_thread(test_imap)


# ============================================================================
# Phase 10 — AI providers, company profile, usage/cost (admin-only via router dep)
# ============================================================================
from shared import ai_client, company_profile  # noqa: E402


class ProviderWrite(BaseModel):
    provider_id: str
    api_key: str | None = None
    base_url: str | None = None


@router.get("/providers")
@safe_endpoint("settings")
async def list_providers():
    return {"ok": True, "providers": ai_client.list_providers_public()}


@router.post("/providers")
@safe_endpoint("settings")
async def save_provider_route(body: ProviderWrite):
    from shared.providers import PROVIDERS
    if body.provider_id not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown provider")
    ai_client.save_provider(body.provider_id, (body.api_key or "").strip() or None, body.base_url)
    return {"ok": True}


@router.delete("/providers/{provider_id}")
@safe_endpoint("settings")
async def delete_provider_route(provider_id: str):
    ai_client.delete_provider(provider_id)
    return {"ok": True, "deleted": provider_id}


@router.post("/providers/{provider_id}/test")
@safe_endpoint("settings")
async def test_provider_route(provider_id: str):
    return await ai_client.test_provider(provider_id)


@router.get("/providers/{provider_id}/models")
@safe_endpoint("settings")
async def list_provider_models_route(provider_id: str):
    return await ai_client.list_provider_models(provider_id)


class CompanyProfileBody(BaseModel):
    company_name: str = ""
    website: str = ""
    tagline: str = ""
    services_offered: list[str] = []
    tone_preference: str = "friendly and professional"
    contact_links: list[dict] = []
    outreach_template: str = ""
    contact_email: str = ""
    whatsapp: str = ""
    logo_url: str = ""
    sender_photo_url: str = ""
    address: str = ""
    phone: str = ""
    sender_name: str = ""
    sender_title: str = ""


@router.get("/company")
@safe_endpoint("settings")
async def get_company():
    return {"ok": True, "profile": company_profile.get_profile()}


@router.post("/company")
@safe_endpoint("settings")
async def set_company(body: CompanyProfileBody):
    return {"ok": True, "profile": company_profile.set_profile(body.model_dump())}


@router.get("/usage")
@safe_endpoint("settings")
async def usage_summary(range: str = "week"):
    from datetime import datetime, timedelta, timezone
    days = {"day": 1, "week": 7, "month": 30}.get(range, 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = [r for r in get_db()["usage_log"].find({}) if r.get("at", "") >= cutoff]
    by_agent: dict = {}
    by_provider: dict = {}
    total_cost = 0.0
    for r in rows:
        total_cost += r.get("est_cost", 0)
        a = by_agent.setdefault(r.get("agent_id", "?"), {"calls": 0, "input_tokens": 0, "output_tokens": 0, "est_cost": 0.0, "providers": {}})
        a["calls"] += 1; a["input_tokens"] += r.get("input_tokens", 0); a["output_tokens"] += r.get("output_tokens", 0); a["est_cost"] += r.get("est_cost", 0)
        a["providers"][r.get("provider_id", "?")] = a["providers"].get(r.get("provider_id", "?"), 0) + 1
        p = by_provider.setdefault(r.get("provider_id", "?"), {"calls": 0, "est_cost": 0.0})
        p["calls"] += 1; p["est_cost"] += r.get("est_cost", 0)
    for a in by_agent.values():
        a["est_cost"] = round(a["est_cost"], 5)
    for p in by_provider.values():
        p["est_cost"] = round(p["est_cost"], 5)
    return {"ok": True, "range": range, "total_calls": len(rows), "total_cost": round(total_cost, 5), "by_agent": by_agent, "by_provider": by_provider}
