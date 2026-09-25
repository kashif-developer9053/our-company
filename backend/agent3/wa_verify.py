"""Check whether a number actually has WhatsApp, via a third-party validator.

Why a third party rather than doing it ourselves: the unofficial libraries that
can query WhatsApp directly work by pairing as YOUR account, so every check is
made by your number. Meta bans on that pattern — a normal person does not look
up two hundred strangers in an hour — and the ban is permanent and takes your
conversations with it. A hosted validator runs the checks on its own
infrastructure, so nothing touches the number the business runs on.

Two layers, cheapest first:

  * `looks_mobile()` already rejects landlines for free. A landline can never
    have WhatsApp, and that removes most of the waste at no cost.
  * This module confirms the rest. A mobile number can still have no WhatsApp
    account, and only the provider knows.

Provider-agnostic on purpose: CheckNumber.AI is the default because it states
plainly that it never binds your account, but the request shape is ordinary
JSON and the base URL is configurable, so swapping provider is a settings
change rather than a code change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from shared.logger import get_logger
from shared.settings_store import get_setting_value

log = get_logger("agent3.wa_verify")

_DEFAULT_BASE = "https://api.checknumber.ai/v1"
_TIMEOUT = 25.0

# Verdicts stored on the lead.
HAS_WA = "yes"
NO_WA = "no"
UNKNOWN = "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_key() -> str:
    return (get_setting_value("wa_validator_key") or "").strip()


def _base_url() -> str:
    return (get_setting_value("wa_validator_base_url") or _DEFAULT_BASE).rstrip("/")


def _read_verdict(payload: dict) -> str:
    """Normalise whatever shape the provider returns into yes/no/unknown.

    Validators disagree on field names — exists, is_valid, status, whatsapp —
    so check the common ones rather than binding to one provider's schema.
    """
    if not isinstance(payload, dict):
        return UNKNOWN
    for key in ("exists", "is_whatsapp", "has_whatsapp", "whatsapp", "is_valid", "valid"):
        if key in payload:
            val = payload[key]
            if isinstance(val, bool):
                return HAS_WA if val else NO_WA
            if isinstance(val, str):
                low = val.strip().lower()
                if low in ("true", "yes", "valid", "active", "registered"):
                    return HAS_WA
                if low in ("false", "no", "invalid", "not_found", "unregistered"):
                    return NO_WA
    status = str(payload.get("status") or payload.get("result") or "").strip().lower()
    if status in ("valid", "exists", "active", "registered", "success"):
        return HAS_WA
    if status in ("invalid", "not_found", "unregistered", "inactive"):
        return NO_WA
    return UNKNOWN


async def check_number(client: httpx.AsyncClient, number: str, key: str, base: str) -> dict:
    """Check one number. Never raises — an unreachable provider is 'unknown'."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if not digits:
        return {"number": number, "verdict": UNKNOWN, "error": "no number"}
    try:
        r = await client.post(
            f"{base}/whatsapp/check",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json={"number": digits},
        )
        if r.status_code == 401:
            return {"number": digits, "verdict": UNKNOWN, "error": "validator rejected the API key"}
        if r.status_code == 402:
            return {"number": digits, "verdict": UNKNOWN, "error": "validator credit exhausted"}
        if r.status_code != 200:
            return {"number": digits, "verdict": UNKNOWN,
                    "error": f"validator returned {r.status_code}"}
        data = r.json()
        # Some providers nest the result.
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        return {"number": digits, "verdict": _read_verdict(payload), "raw": payload}
    except httpx.HTTPError as exc:
        return {"number": digits, "verdict": UNKNOWN, "error": f"{type(exc).__name__}"}


async def verify_leads(limit: int = 200, recheck: bool = False) -> dict:
    """Check the WhatsApp status of leads that have a usable number.

    Only leads without a verdict are checked unless `recheck` is set, so
    repeated runs cost nothing for numbers already known.
    """
    from shared.database import get_db
    from .whatsapp import looks_mobile, normalise_number

    key = _api_key()
    if not key:
        return {"ok": False,
                "error": ("No WhatsApp validator key configured. Add 'wa_validator_key' in "
                          "Settings → API Keys. A landline is already filtered for free; "
                          "this confirms whether a mobile actually has WhatsApp.")}

    db = get_db()
    query: dict = {"phone": {"$nin": ["", None]}}
    if not recheck:
        query["wa_verified.verdict"] = {"$exists": False}

    leads = list(db["leads"].find(query, {"id": 1, "phone": 1, "business_name": 1})
                 .limit(max(1, min(limit, 2000))))
    if not leads:
        return {"ok": True, "checked": 0, "message": "Every number already has a verdict."}

    base = _base_url()
    counts: dict[str, int] = {HAS_WA: 0, NO_WA: 0, UNKNOWN: 0, "skipped_landline": 0}
    errors: set[str] = set()

    async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT)) as client:
        for lead in leads:
            number = normalise_number(lead.get("phone", ""))
            # Do not spend a paid check on a number that cannot have WhatsApp.
            if not number or not looks_mobile(number):
                db["leads"].update_one({"id": lead["id"]}, {"$set": {"wa_verified": {
                    "verdict": NO_WA, "reason": "landline", "at": _now()}}})
                counts["skipped_landline"] += 1
                continue

            res = await check_number(client, number, key, base)
            record = {"verdict": res["verdict"], "at": _now()}
            if res.get("error"):
                errors.add(res["error"])
                record["error"] = res["error"]
            db["leads"].update_one({"id": lead["id"]}, {"$set": {"wa_verified": record}})
            counts[res["verdict"]] = counts.get(res["verdict"], 0) + 1
            await asyncio.sleep(0.15)   # stay friendly with the provider

    log.info("WhatsApp verification: %s", counts)
    return {"ok": True, "checked": len(leads), "counts": counts,
            "errors": sorted(errors)[:3]}
