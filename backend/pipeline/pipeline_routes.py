"""Lead-generation pipeline: scrape (Agent 1) -> verify (Agent 2) -> store + summary.

Triggered automatically after the CEO approves a niche. Runs as a background
asyncio task so the approval request returns immediately. Every stage updates the
status board (Agent 1/2 working -> idle, or error) which the office UI polls.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from agent1.contact_enrichment import enrich_lead_emails
from agent1.scraper import scrape_google_maps
from agent1.site_auditor import audit_leads
from agent1.website_miner import mine_business_websites
from agent2.verifier import verify_and_store
from shared import notifications
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

log = get_logger("pipeline")
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_MAX_LEADS = 20      # respectful batch cap per approved niche run (Google Maps)
_MAX_WEB_LEADS = 12  # additional businesses discovered by our own web crawler


def _lead_key(lead: dict) -> str:
    """Dedupe key: prefer website domain, else business name."""
    site = (lead.get("website") or "").strip().lower()
    if site:
        host = site.split("//")[-1].split("/")[0]
        return host[4:] if host.startswith("www.") else host
    return (lead.get("business_name") or "").strip().lower()


def _merge_leads(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Merge two discovery sources, keeping the richer record for duplicates."""
    merged: dict[str, dict] = {}
    for lead in [*primary, *extra]:
        key = _lead_key(lead)
        if not key:
            continue
        if key in merged:
            # Fill blanks on the existing record rather than dropping data.
            for field, value in lead.items():
                if value and not merged[key].get(field):
                    merged[key][field] = value
        else:
            merged[key] = dict(lead)
    return list(merged.values())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_agent(agent_id: str, status: str, task: str = "") -> None:
    get_db()["agents"].update_one({"id": agent_id}, {"$set": {"status": status, "task": task}})


def _runs():
    return get_db()["pipeline_runs"]


async def run_lead_pipeline(record: dict) -> None:
    """The full background job. Never raises (isolated)."""
    niche_name = record.get("approved_niche") or record.get("industry", "")
    industry = record.get("industry", "")
    country = record.get("country", "")
    city = record.get("city", "") or ""
    where = f"{city + ', ' if city else ''}{country}"
    query = f"{industry} in {where}".strip()

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    _runs().insert_one({
        "id": run_id, "niche_name": niche_name, "industry": industry, "country": country, "city": city,
        "status": "running", "found": 0, "verified": 0, "rejected": 0, "reasons": {},
        "message": "", "created_at": _now(), "finished_at": "",
    })

    try:
        # ---- Agent 1: scrape ----
        _set_agent("agent1", "working", f"Scraping leads: {niche_name} in {city or country}")
        res = await scrape_google_maps(query, max_results=_MAX_LEADS)

        if not res["ok"]:
            # Blocked / failed: stop cleanly, mark Agent 1 error (isolated) + tell the CEO.
            _set_agent("agent1", "error", res["message"])
            _finish(run_id, "error", res["message"], {"found": 0, "verified": 0, "rejected": 0, "reasons": {}})
            notifications.notify(
                "alert", f"Lead search failed for '{niche_name}'", res["message"],
                agent_id="agent1", action="pipeline", ref_id=run_id,
                dedupe_key=f"pipeline_fail_{niche_name}",
            )
            log.warning("Pipeline stopped: %s", res["message"])
            return

        raw = list(res["leads"])

        # ---- Agent 1b: also discover businesses via web search + site crawl ----
        # Google Maps misses SMEs that only have a website. This is our own
        # crawler (no AI, no paid API) and it respects robots.txt.
        try:
            _set_agent("agent1", "working", f"Searching the web for: {niche_name}")
            mined = await mine_business_websites(query, max_results=_MAX_WEB_LEADS)
            if mined.get("ok") and mined.get("leads"):
                raw = _merge_leads(raw, mined["leads"])
                log.info("Website miner added leads; total now %d", len(raw))
        except Exception as exc:  # noqa: BLE001 - miner failure never kills the run
            log.error("Website miner failed (isolated): %s", exc)

        # ---- Agent 1c: find real public emails for leads that lack one ----
        try:
            _set_agent("agent1", "working", "Finding public contact emails")
            found = await enrich_lead_emails(raw)
            log.info("Contact enrichment found %d real emails", found)
        except Exception as exc:  # noqa: BLE001
            log.error("Contact enrichment failed (isolated): %s", exc)

        # ---- Agent 1d: audit each site => WHY is this a lead? ----
        # Every lead must carry a concrete, evidence-based reason. Businesses
        # whose site is already good are dropped: they are not real prospects.
        rejected_good_site = 0
        try:
            _set_agent("agent1", "working", f"Auditing {len(raw)} websites for issues")
            await audit_leads(raw)
            qualified = [l for l in raw if l.get("site_audit", {}).get("qualified", True)]
            rejected_good_site = len(raw) - len(qualified)
            raw = qualified
            log.info("Site audit qualified %d leads, dropped %d with good sites",
                     len(raw), rejected_good_site)
        except Exception as exc:  # noqa: BLE001
            log.error("Site audit failed (isolated): %s", exc)

        _set_agent("agent1", "idle", "")

        # ---- Agent 2: verify (deterministic; blocking I/O -> threadpool) ----
        _set_agent("agent2", "working", f"Verifying {len(raw)} leads")
        summary = await asyncio.to_thread(verify_and_store, raw, niche_name, country, city, run_id)
        summary["rejected_good_site"] = rejected_good_site
        _set_agent("agent2", "idle", "")

        r = summary["reasons"]
        msg = (
            f"Lead generation complete for {niche_name} in {city or country}: "
            f"{summary['found']} businesses found, {summary['verified']} verified and awaiting your "
            f"approval, {summary['rejected']} rejected ({r.get('duplicate', 0)} duplicates, "
            f"{r.get('no_contact', 0)} no contact method available)."
        )
        _finish(run_id, "complete", msg, summary)

        # APPROVAL CHECKPOINT: tell the CEO there is a batch to review.
        if summary["verified"]:
            notifications.notify(
                "approval",
                f"{summary['verified']} new leads need your approval",
                f"Agent 1 found {summary['found']} businesses for '{niche_name}' in "
                f"{city or country}. Agent 2 verified {summary['verified']} of them. "
                f"Review and approve to add them to your CRM.",
                agent_id="agent2", action="leads_pending", ref_id=run_id,
            )
        log.info(msg)
    except Exception as exc:  # noqa: BLE001 - pipeline failure never crashes the app
        log.error("Pipeline crashed (isolated): %s", exc)
        _set_agent("agent1", "idle", "")
        _set_agent("agent2", "idle", "")
        _finish(run_id, "error", f"Pipeline error: {exc}", {"found": 0, "verified": 0, "rejected": 0, "reasons": {}})


def _finish(run_id: str, status: str, message: str, summary: dict) -> None:
    _runs().update_one({"id": run_id}, {"$set": {
        "status": status, "message": message, "finished_at": _now(),
        "found": summary.get("found", 0), "verified": summary.get("verified", 0),
        "rejected": summary.get("rejected", 0), "reasons": summary.get("reasons", {}),
    }})


def trigger_pipeline(record: dict) -> None:
    """Fire-and-forget the pipeline from the approval endpoint."""
    asyncio.create_task(run_lead_pipeline(record))


def _serialize_run(d: dict) -> dict:
    return {k: d.get(k) for k in
            ("id", "niche_name", "industry", "country", "city", "status", "found", "verified", "rejected", "reasons", "message", "created_at", "finished_at")}


@router.get("/runs")
@safe_endpoint("pipeline")
async def list_runs():
    docs = list(_runs().find({}))
    docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return {"ok": True, "runs": [_serialize_run(d) for d in docs[:20]]}


# ---- CEO approval gate for scraped leads -----------------------------------
def _leads():
    return get_db()["leads"]


UNBATCHED = "unbatched"


def _batch_query(batch_id: str) -> dict:
    """Match a batch by id, INCLUDING legacy/partial leads that never got one.

    Leads written before batch_id was persisted (or by any path that omits it)
    carry None/missing. The UI groups those under "unbatched", so approving that
    group must match exactly those documents — not a literal "unbatched" string.
    """
    if batch_id == UNBATCHED:
        return {"$or": [{"batch_id": None}, {"batch_id": ""}, {"batch_id": {"$exists": False}}]}
    return {"batch_id": batch_id}


@router.get("/pending-leads")
@safe_endpoint("pipeline")
async def pending_leads():
    """Batches of verified leads waiting on the CEO, newest first."""
    from crm.leads_model import serialize as ser_lead
    docs = list(_leads().find({"status": "pending_approval"}))
    batches: dict[str, dict] = {}
    for d in docs:
        bid = d.get("batch_id") or UNBATCHED
        b = batches.setdefault(bid, {"batch_id": bid, "niche": d.get("niche", ""),
                                     "city": d.get("city", ""), "country": d.get("country", ""),
                                     "created_at": d.get("created_at", ""), "leads": []})
        b["leads"].append(ser_lead(d))
    out = sorted(batches.values(), key=lambda b: b["created_at"], reverse=True)
    return {"ok": True, "batches": out, "total": len(docs)}


@router.post("/pending-leads/{batch_id}/approve")
@safe_endpoint("pipeline")
async def approve_batch(batch_id: str, body: dict | None = None):
    """CEO approves the batch -> leads become live CRM leads.

    Optional body {"lead_ids": [...]} approves only those; the rest are rejected.
    """
    body = body or {}
    only = body.get("lead_ids")
    q = {**_batch_query(batch_id), "status": "pending_approval"}
    if only:
        # Approve exactly what the CEO ticked. The unticked ones are LEFT PENDING
        # (never auto-rejected) — they may simply want to review them later, and
        # silently discarding real leads is not recoverable.
        n = _leads().update_many({**q, "id": {"$in": only}}, {"$set": {
            "status": "verified", "last_action": "Approved by CEO",
            "last_action_timestamp": _now()}}).modified_count
    else:
        n = _leads().update_many(q, {"$set": {
            "status": "verified", "last_action": "Approved by CEO",
            "last_action_timestamp": _now()}}).modified_count

    notifications.resolve(f"leads_batch_{batch_id}")
    for nd in get_db()["notifications"].find({"ref_id": batch_id, "kind": "approval"}):
        get_db()["notifications"].update_one({"id": nd["id"]}, {"$set": {"resolved": True, "read": True}})

    # Hand off to Agent 3: draft outreach for the freshly approved leads.
    handoff = {"started": False, "reason": ""}
    if n:
        from agent3.agent3_routes import handoff_after_approval
        handoff = await handoff_after_approval(batch_id)
    log.info("CEO approved %d leads in batch %s", n, batch_id)
    return {"ok": True, "approved": n, "outreach": handoff}


@router.post("/pending-leads/{batch_id}/reject")
@safe_endpoint("pipeline")
async def reject_batch(batch_id: str):
    n = _leads().update_many({**_batch_query(batch_id), "status": "pending_approval"}, {"$set": {
        "status": "rejected", "rejection_reason": "rejected_by_ceo",
        "last_action": "Rejected by CEO", "last_action_timestamp": _now()}}).modified_count
    for nd in get_db()["notifications"].find({"ref_id": batch_id, "kind": "approval"}):
        get_db()["notifications"].update_one({"id": nd["id"]}, {"$set": {"resolved": True, "read": True}})
    return {"ok": True, "rejected": n}
