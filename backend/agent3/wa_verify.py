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

Targets WA Validator's documented API (POST /bulk-check/, Bearer auth,
results[].exists). The base URL is a setting, so another provider with the
same shape can be swapped in without a code change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from shared.logger import get_logger
from shared.settings_store import get_setting_value

log = get_logger("agent3.wa_verify")

_DEFAULT_BASE = "https://wavalidator.com/api/v1"
_TIMEOUT = 60.0        # bulk calls are slower than a single lookup
_BULK_SIZE = 50        # numbers per request

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


async def check_batch(client: httpx.AsyncClient, numbers: list[str],
                      key: str, base: str) -> tuple[dict[str, str], str, int | None]:
    """Check up to _BULK_SIZE numbers in one call.

    Returns (verdict by number, error, credits remaining). Bulk rather than
    one-at-a-time because the provider bills per number either way and 372
    separate round trips would take minutes.
    """
    if not numbers:
        return {}, "", None
    try:
        r = await client.post(
            f"{base}/bulk-check/",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json={"numbers": numbers},
        )
        if r.status_code in (401, 403):
            return {}, "the validator rejected the API key", None
        if r.status_code in (402, 429):
            return {}, "validator credits exhausted or rate limited", None
        if r.status_code != 200:
            return {}, f"validator returned {r.status_code}", None

        data = r.json()
        out: dict[str, str] = {}
        for row in data.get("results") or []:
            num = str(row.get("number") or "")
            exists = row.get("exists")
            if exists is True:
                out[num] = HAS_WA
            elif exists is False:
                out[num] = NO_WA
            else:
                out[num] = UNKNOWN
        return out, "", data.get("credits_remaining")
    except httpx.HTTPError as exc:
        return {}, f"could not reach the validator ({type(exc).__name__})", None


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
    credits: int | None = None

    # Settle the landlines locally first — they cost nothing and must never
    # consume a paid credit.
    pending: list[tuple[str, str]] = []          # (lead id, number)
    for lead in leads:
        number = normalise_number(lead.get("phone", ""))
        if not number or not looks_mobile(number):
            db["leads"].update_one({"id": lead["id"]}, {"$set": {"wa_verified": {
                "verdict": NO_WA, "reason": "landline", "at": _now()}}})
            counts["skipped_landline"] += 1
            continue
        pending.append((lead["id"], number))

    async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT)) as client:
        for start in range(0, len(pending), _BULK_SIZE):
            chunk = pending[start:start + _BULK_SIZE]
            verdicts, error, left = await check_batch(
                client, [n for _id, n in chunk], key, base)
            if left is not None:
                credits = left
            if error:
                errors.add(error)
                # Out of credit or a bad key will not fix itself mid-run.
                if "key" in error or "credits" in error:
                    break

            for lead_id, number in chunk:
                verdict = verdicts.get(number, UNKNOWN)
                record = {"verdict": verdict, "at": _now()}
                if error:
                    record["error"] = error
                db["leads"].update_one({"id": lead_id}, {"$set": {"wa_verified": record}})
                counts[verdict] = counts.get(verdict, 0) + 1
            await asyncio.sleep(0.3)   # stay friendly with the provider

    log.info("WhatsApp verification: %s", counts)
    return {"ok": True, "checked": len(leads), "counts": counts,
            "credits_remaining": credits, "errors": sorted(errors)[:3]}
