"""The Supervisor — a real Claude-backed reasoning agent.

Reviews Agent 1's niche suggestions and chats with the CEO, grounded in real
system data pulled from the database (never guessing system state).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from shared.ai_context import agent_chat, agent_task
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

log = get_logger("supervisor")
router = APIRouter(prefix="/supervisor", tags=["supervisor"])

SYSTEM = (
    "You are the Supervisor of a small digital agency's automated team. You review the work of "
    "specialist agents (a Researcher, a Verifier, an Outreach specialist, and an IT Technician), "
    "decide whether their output is good and ready to pass forward, and communicate clearly and "
    "concisely with the CEO (a human). You do NOT have authority to approve major decisions like "
    "niche selection or replying to leads — those require explicit CEO approval. Be concise, grounded, "
    "and never invent system state you weren't given."
)


def _set_status(agent_id: str, status: str) -> None:
    get_db()["agents"].update_one({"id": agent_id}, {"$set": {"status": status}})


def _system_snapshot() -> str:
    """A compact, factual snapshot of current system state for grounding."""
    agents = list(get_db()["agents"].find({}))
    leads = list(get_db()["leads"].find({}))
    niches = list(get_db()["niche_suggestions"].find({"status": "awaiting_ceo_approval"}))
    runs = list(get_db()["pipeline_runs"].find({}))
    runs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    agent_lines = "; ".join(f"{a['name']} ({a['role_key']}) = {a.get('status')}" for a in agents)
    lead_counts: dict = {}
    for l in leads:
        lead_counts[l["status"]] = lead_counts.get(l["status"], 0) + 1
    pending = "; ".join(
        f"{n['industry']}/{n['country']}: {', '.join(x['niche_name'] for x in n['niches'])}" for n in niches
    ) or "none"
    run_lines = "; ".join(
        f"{r.get('niche_name')} ({r.get('status')}): {r.get('verified', 0)} verified / {r.get('found', 0)} found" for r in runs[:5]
    ) or "none yet"
    return (
        f"CURRENT SYSTEM STATE (facts):\n"
        f"- Agents: {agent_lines}\n"
        f"- Leads by status: {lead_counts or 'none'} (total {len(leads)})\n"
        f"- Niche sets awaiting CEO approval: {pending}\n"
        f"- Recent lead-gen runs: {run_lines}\n"
    )


# Reusable review logic (also called internally by Agent 1).
async def review_niches(niches: list[dict], industry: str, country: str) -> dict:
    _set_status("supervisor", "working")
    try:
        listing = "\n".join(f"- {n['niche_name']}: {n['reasoning']}" for n in niches)
        prompt = (
            f"Agent 1 (Researcher) proposed these niche opportunities for {industry} in {country}:\n\n"
            f"{listing}\n\n"
            "Sanity-check them: are they real, reasonable, distinct business opportunities (not nonsense "
            "or duplicates)? Reply in 1-2 short sentences as a note to the CEO. Start with either "
            "'Approved for CEO review:' or 'Concern:'."
        )
        res = await agent_task("supervisor", prompt, task_hint="niche review", max_tokens=200, purpose="review")
        if res["ok"]:
            _set_status("supervisor", "idle")
            return {"ok": True, "note": res["text"]}
        _set_status("supervisor", "error")
        return {"ok": False, "error": res["error"]}
    except Exception as exc:  # noqa: BLE001
        _set_status("supervisor", "error")
        return {"ok": False, "error": str(exc)}


def build_standup() -> dict:
    """Gather a REAL status summary from each agent's actual data (no per-agent
    Claude calls — pulled straight from the DB). Optionally phrased by Claude."""
    db = get_db()
    leads = list(db["leads"].find({}))
    pending_niches = db["niche_suggestions"].count_documents({"status": "awaiting_ceo_approval"})
    runs = list(db["pipeline_runs"].find({}))
    runs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    latest_run = runs[0] if runs else None

    def n(status):
        return sum(1 for l in leads if l.get("status") == status)

    verified = n("verified")
    mailed = n("mailed")
    interested = n("interested_awaiting_review")
    not_interested = n("not_interested")
    replied = n("replied") + interested + not_interested
    health = None
    hc = list(db["health_checks"].find({}))
    if hc:
        hc.sort(key=lambda d: d.get("checked_at", ""), reverse=True)
        health = hc[0].get("overall")

    reports = [
        {"agent": "Agent 1 — Researcher",
         "text": (f"{pending_niches} niche set(s) awaiting your approval. "
                  + (f"Last scrape: {latest_run['found']} businesses found for {latest_run['niche_name']}." if latest_run else "No scrapes run yet."))},
        {"agent": "Agent 2 — Verifier",
         "text": (f"{verified} verified lead(s) in the CRM. "
                  + (f"Last run verified {latest_run['verified']} / rejected {latest_run['rejected']}." if latest_run else "No verification runs yet."))},
        {"agent": "Agent 3 — Outreach",
         "text": f"{mailed} email(s) awaiting reply, {replied} repl(y/ies) received, {interested} interested lead(s) awaiting your review."},
        {"agent": "IT Technician",
         "text": (f"System health: {health}." if health else "No health check run yet.")},
    ]

    # Optional single Claude call to phrase it as a coherent standup (skipped if no key).
    summary = ""
    return {"date": _today(), "reports": reports, "summary": summary}


async def phrase_standup(reports: list[dict]) -> str:
    listing = "\n".join(f"- {r['agent']}: {r['text']}" for r in reports)
    res = await agent_task("supervisor", f"Summarize this morning standup for the CEO in 2-3 friendly sentences:\n{listing}", max_tokens=200, purpose="standup")
    return res["text"] if res["ok"] else ""


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@router.get("/standup")
@safe_endpoint("supervisor")
async def get_standup():
    db = get_db()
    docs = list(db["standups"].find({}))
    docs.sort(key=lambda d: d.get("date", ""), reverse=True)
    if docs:
        d = docs[0]
        d.pop("_id", None)
        return {"ok": True, "standup": d}
    # None stored yet — build a fresh one on demand.
    return {"ok": True, "standup": build_standup()}


class ReviewBody(BaseModel):
    niches: list[dict]
    industry: str = ""
    country: str = ""


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/review-niches")
@safe_endpoint("supervisor")
async def review_niches_route(body: ReviewBody):
    result = await review_niches(body.niches, body.industry, body.country)
    return {"ok": result["ok"], **result}


# ============================================================================
# Phase 10 — Senior Supervisor: strategic review + underperformance coaching.
# ============================================================================
import uuid as _uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from shared import instructions as _instr  # noqa: E402


def _perf_data() -> dict:
    db = get_db()
    leads = list(db["leads"].find({}))
    def c(*s): return sum(1 for l in leads if l.get("status") in s)
    mailed = c("mailed")
    replied = c("replied", "interested_awaiting_review", "not_interested")
    interested = c("interested_awaiting_review")
    verified = c("verified")
    rejected_leads = c("rejected")
    # reply rate by niche
    by_niche: dict = {}
    for l in leads:
        n = l.get("niche", "?")
        d = by_niche.setdefault(n, {"mailed": 0, "interested": 0})
        if l.get("status") in ("mailed", "replied", "interested_awaiting_review", "not_interested"):
            d["mailed"] += 1
        if l.get("status") == "interested_awaiting_review":
            d["interested"] += 1
    niche_rejections = db["niche_suggestions"].count_documents({"status": "rejected"})
    hc = list(db["health_checks"].find({}))
    hc.sort(key=lambda d: d.get("checked_at", ""), reverse=True)
    return {
        "mailed": mailed, "replied": replied, "interested": interested, "verified": verified,
        "rejected_leads": rejected_leads,
        "reply_rate": round(replied / mailed, 3) if mailed else 0,
        "by_niche": by_niche, "niche_rejections": niche_rejections,
        "health": hc[0].get("overall") if hc else None,
    }


def _detect_underperformance(perf: dict) -> list[dict]:
    """Simple, explainable thresholds → flagged agents needing coaching."""
    flags = []
    if perf["mailed"] >= 5 and perf["reply_rate"] < 0.1:
        flags.append({"agent_id": "agent3", "reason": f"Low reply rate ({perf['reply_rate']*100:.0f}%) across {perf['mailed']} emails — outreach messaging may need adjustment."})
    total_verify = perf["verified"] + perf["rejected_leads"]
    if total_verify >= 5 and perf["rejected_leads"] / total_verify > 0.5:
        flags.append({"agent_id": "agent2", "reason": f"High rejection rate ({perf['rejected_leads']}/{total_verify}) — verification may be too strict or lead sources weak."})
    if perf["niche_rejections"] >= 2:
        flags.append({"agent_id": "agent1", "reason": f"{perf['niche_rejections']} niche sets rejected by the CEO — niche targeting may be off."})
    return flags


async def run_strategic_review() -> dict:
    perf = _perf_data()
    # Deterministic observations (facts), then optional Claude-phrased strategy.
    observations = []
    best_niche = None
    for n, d in perf["by_niche"].items():
        if d["mailed"] >= 3:
            rate = d["interested"] / d["mailed"]
            if best_niche is None or rate > best_niche[1]:
                best_niche = (n, rate)
    if best_niche and best_niche[1] > 0:
        observations.append(f"'{best_niche[0]}' is your best-performing niche so far ({best_niche[1]*100:.0f}% interested).")
    observations.append(f"Overall reply rate is {perf['reply_rate']*100:.0f}% across {perf['mailed']} emails sent.")
    if perf["health"] and perf["health"] != "ok":
        observations.append(f"System health is currently '{perf['health']}' — see the IT Technician.")

    flags = _detect_underperformance(perf)

    prompt = (
        "You are the senior Supervisor. Given this real performance data, write 2-4 sentences of strategic "
        f"direction for the CEO (which industries/niches to prioritize, what to watch).\nDATA: {perf}\n"
        f"OBSERVATIONS: {observations}"
    )
    res = await agent_task("supervisor", prompt, task_hint="strategic review", max_tokens=350, purpose="strategy")
    strategy = res["text"] if res["ok"] else "(Strategic narrative needs a configured AI provider; observations above are from real data.)"

    # Create coaching proposals (NOT applied — CEO must approve).
    db = get_db()
    proposals = []
    for f in flags:
        current = _instr.get_active(f["agent_id"])
        coaching = f"\n\nCOACHING NOTE (proposed {datetime.now(timezone.utc).strftime('%Y-%m-%d')}): {f['reason']} Adjust your approach accordingly."
        pid = f"prop_{_uuid.uuid4().hex[:8]}"
        proposal = {
            "id": pid, "agent_id": f["agent_id"], "reason": f["reason"],
            "current_instructions": current, "proposed_instructions": current + coaching,
            "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db["coaching_proposals"].insert_one(dict(proposal))
        proposals.append({k: proposal[k] for k in ("id", "agent_id", "reason", "status")})

    review = {
        "id": f"sr_{_uuid.uuid4().hex[:8]}", "created_at": datetime.now(timezone.utc).isoformat(),
        "perf": perf, "observations": observations, "strategy": strategy,
        "proposals": proposals,
    }
    db["strategic_reviews"].update_one({"id": review["id"]}, {"$set": review}, upsert=True)
    return review


@router.post("/strategic-review")
@safe_endpoint("supervisor")
async def strategic_review_now():
    return {"ok": True, "review": await run_strategic_review()}


@router.get("/strategic-review")
@safe_endpoint("supervisor")
async def latest_strategic_review():
    docs = list(get_db()["strategic_reviews"].find({}))
    docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    if not docs:
        return {"ok": True, "review": None}
    d = docs[0]; d.pop("_id", None)
    return {"ok": True, "review": d}


@router.get("/proposals")
@safe_endpoint("supervisor")
async def list_proposals():
    docs = list(get_db()["coaching_proposals"].find({"status": "pending"}))
    for d in docs:
        d.pop("_id", None)
    return {"ok": True, "proposals": docs}


@router.post("/proposals/{proposal_id}/approve")
@safe_endpoint("supervisor")
async def approve_proposal(proposal_id: str):
    db = get_db()
    p = db["coaching_proposals"].find_one({"id": proposal_id})
    if p is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    # CEO-approved: NOW apply the instruction change (new active version).
    v = _instr.save_new_version(p["agent_id"], p["proposed_instructions"], created_by="supervisor")
    db["coaching_proposals"].update_one({"id": proposal_id}, {"$set": {"status": "approved", "applied_version": v}})
    return {"ok": True, "message": f"Applied — {p['agent_id']} instructions updated to v{v}.", "version": v}


@router.post("/proposals/{proposal_id}/reject")
@safe_endpoint("supervisor")
async def reject_proposal(proposal_id: str):
    get_db()["coaching_proposals"].update_one({"id": proposal_id}, {"$set": {"status": "rejected"}})
    return {"ok": True}


@router.post("/chat")
@safe_endpoint("supervisor")
async def chat(body: ChatBody):
    # NOTE: status is left as-is (the frontend sets "in_ceo_office" while the chat
    # window is open, which walks the Supervisor to the CEO office). We ground the
    # reply in a real snapshot of system state so it can't hallucinate.
    snapshot = _system_snapshot()
    res = await agent_chat("supervisor", body.message, body.history,
                           extra_context=snapshot + "\n(Use only the facts above for system state.)", max_tokens=600)
    if res["ok"]:
        return {"ok": True, "reply": res["text"]}
    return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}
