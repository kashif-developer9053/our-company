"""CRM API — full CRUD for leads, backed by MongoDB, plus computed report stats.
Replaces the Phase 1.6 mock lead data."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

from .leads_model import SEED_LEADS, LeadCreate, LeadUpdate, serialize

log = get_logger("crm")
router = APIRouter(prefix="/leads", tags=["crm"])


def _col():
    return get_db()["leads"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_leads(rows: list[dict], source: str = "agent1", last_action: str = "Added by Agent 1 (research)",
              require_reason: bool = True) -> dict:
    """Insert leads into the CRM, skipping duplicates by (business_name + city).

    HARD RULE: an agent-sourced lead must carry a `collection_reason` explaining
    why it is a prospect. Leads without one are refused (counted in `no_reason`)
    rather than silently stored. Manual CEO entry passes require_reason=False.

    Returns {added, skipped, no_reason, ids}.
    """
    col = _col()
    added, skipped, no_reason, ids = 0, 0, 0, []
    allowed = {"business_name", "niche", "country", "city", "phone", "email", "website", "status", "notes",
               # evidence for WHY this lead was collected (see agent1/site_auditor.py)
               "collection_reason", "opportunity_score", "site_audit", "pitch_points", "discovery_source",
               # approval-gate + contact provenance (batch_id is what the CEO approves against)
               "batch_id", "email_confidence", "email_source_url", "contact_verified", "has_working_website"}
    for row in rows:
        name = str(row.get("business_name", "")).strip()
        if not name:
            skipped += 1
            continue
        # Never store a lead we cannot justify.
        if require_reason and not str(row.get("collection_reason", "")).strip():
            no_reason += 1
            log.warning("Refused lead '%s' — no collection_reason", name)
            continue
        city = str(row.get("city", "")).strip()
        # de-dupe: same business name in the same city already exists
        if col.find_one({"business_name": name, "city": city}):
            skipped += 1
            continue
        clean = {k: row[k] for k in allowed if k in row and row[k] is not None}
        clean.setdefault("status", "new")
        lead = {
            "id": f"L-{uuid.uuid4().hex[:6].upper()}",
            "country": "", "phone": "", "email": "", "website": "", "notes": "",
            **clean,
            "source": source,
            "last_action": last_action,
            "last_action_timestamp": _now(),
            "created_at": _now(),
        }
        col.insert_one(dict(lead))
        added += 1
        ids.append(lead["id"])
    log.info("add_leads(%s): added=%d skipped=%d no_reason=%d", source, added, skipped, no_reason)
    return {"added": added, "skipped": skipped, "no_reason": no_reason, "ids": ids}


def seed_leads() -> None:
    """Demo leads are DISABLED.

    The CEO works with real, audited leads only — fake ones make it impossible to
    tell a genuine empty database (e.g. a failed Atlas connection) from a working
    one. Set SEED_DEMO_LEADS=1 to restore the old demo data for a fresh install.
    """
    import os

    if os.environ.get("SEED_DEMO_LEADS", "").lower() not in ("1", "true", "yes"):
        return
    col = _col()
    if col.count_documents({}) == 0:
        for i, lead in enumerate(SEED_LEADS):
            col.insert_one({
                "id": f"L-{1042 - i}",
                "country": "Pakistan", "phone": "", "email": "", "website": "", "notes": "",
                "created_at": _now(),
                **lead,
            })
        log.info("Seeded %d demo leads (SEED_DEMO_LEADS enabled)", col.count_documents({}))


def _compute_stats(leads: list[dict]) -> dict:
    def has(*statuses):
        return sum(1 for l in leads if l["status"] in statuses)

    return {
        "leadsFound": len(leads),
        "leadsVerified": has("verified", "mailed", "replied", "not_interested", "interested_awaiting_review"),
        "emailsSent": has("mailed", "replied", "not_interested", "interested_awaiting_review"),
        "repliesReceived": has("replied", "not_interested", "interested_awaiting_review"),
        "interested": has("interested_awaiting_review"),
        "notInterested": has("not_interested"),
        "pendingResponse": has("mailed"),
    }


# ---- report stats (used by the Reports dashboard) --------------------------
@router.get("/stats")
@safe_endpoint("crm")
async def lead_stats():
    # Counting via aggregation instead of pulling every document: this used to
    # transfer the whole collection (~40s) just to tally statuses.
    # Rejected leads are excluded from headline stats (not real pipeline output).
    counts = {d["_id"]: d["n"] for d in _col().aggregate([
        {"$match": {"status": {"$ne": "rejected"}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ])}
    total = sum(counts.values())

    def has(*statuses):
        return sum(counts.get(s, 0) for s in statuses)

    stats = {
        "leadsFound": total,
        "leadsVerified": has("verified", "mailed", "replied", "not_interested", "interested_awaiting_review"),
        "emailsSent": has("mailed", "replied", "not_interested", "interested_awaiting_review"),
        "repliesReceived": has("replied", "not_interested", "interested_awaiting_review"),
        "interested": has("interested_awaiting_review"),
        "notInterested": has("not_interested"),
        "pendingResponse": has("mailed"),
    }
    return {"ok": True, "stats": stats, "total": total}


# ---- CRUD ------------------------------------------------------------------
@router.get("")
@safe_endpoint("crm")
async def list_leads(
    status: Optional[str] = Query(default=None),
    niche: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
):
    query: dict = {}
    if status:
        query["status"] = status  # explicit status (incl. "rejected") is queryable
    else:
        query["status"] = {"$ne": "rejected"}  # default view hides rejected leads
    if niche:
        query["niche"] = niche
    if q:
        # Filter in MongoDB, not in Python — matching 375 docs client-side meant
        # transferring every one of them first.
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"business_name": rx}, {"niche": rx}, {"city": rx}]

    # The list view never renders the heavy fields. Fetching them made this
    # endpoint transfer ~560KB and take 45s; excluding them takes ~1s.
    # `site_audit` and `outreach_history` are loaded per-lead on demand instead.
    projection = {"_id": 0, "site_audit": 0, "outreach_history": 0, "suggested_reply": 0}
    docs = [serialize(d) for d in
            _col().find(query, projection).sort("last_action_timestamp", -1).limit(limit)]
    return {"ok": True, "leads": docs}


@router.get("/{lead_id}")
@safe_endpoint("crm")
async def get_lead(lead_id: str):
    doc = _col().find_one({"id": lead_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"ok": True, "lead": serialize(doc)}


@router.post("")
@safe_endpoint("crm")
async def create_lead(body: LeadCreate):
    lead = {
        "id": f"L-{uuid.uuid4().hex[:6].upper()}",
        **body.model_dump(),
        "last_action": "Manually added",
        "last_action_timestamp": _now(),
        "created_at": _now(),
    }
    _col().insert_one(dict(lead))
    log.info("Created lead %s (%s)", lead["id"], lead["business_name"])
    return {"ok": True, "lead": serialize(lead)}


@router.put("/{lead_id}")
@safe_endpoint("crm")
async def update_lead(lead_id: str, body: LeadUpdate):
    col = _col()
    if col.find_one({"id": lead_id}) is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        updates["last_action_timestamp"] = _now()
        if "status" in updates and "last_action" not in updates:
            updates["last_action"] = f"Status set to {updates['status']}"
        col.update_one({"id": lead_id}, {"$set": updates})
    doc = col.find_one({"id": lead_id})
    return {"ok": True, "lead": serialize(doc)}


@router.delete("/{lead_id}")
@safe_endpoint("crm")
async def delete_lead(lead_id: str):
    col = _col()
    if col.find_one({"id": lead_id}) is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    col.delete_one({"id": lead_id})
    log.info("Deleted lead %s", lead_id)
    return {"ok": True, "deleted": lead_id}
