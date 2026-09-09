"""Agent 1 (Researcher) — real Claude-backed niche finding + approval checkpoint.

IMPORTANT PHASE-3 BOUNDARY: approving a niche only RECORDS the decision. It does
NOT trigger any scraping or lead generation — that is Phase 4.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.ai_context import agent_chat, agent_task
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint
from supervisor.supervisor_routes import review_niches

from .niche_model import NicheRequest, parse_niches, parse_result, serialize

log = get_logger("agent1")
router = APIRouter(prefix="/agent1", tags=["agent1"])

SYSTEM = (
    "You are a market research specialist for a small digital agency that sells web development, "
    "CRM and ERP development services. Given an industry and country/region, identify 3 to 4 "
    "genuinely underserved, non-obvious niche opportunities \u2014 avoid generic suggestions like "
    "'dentists need websites'. Instead reason about specific, less-competitive angles: a particular "
    "sub-vertical, an operational pain point competitors miss, or an audience segment other agencies "
    "overlook. For each niche explain briefly WHY it's an opportunity, in plain language a business "
    "owner would understand.\n\n"
    "CRITICAL \u2014 a niche is a TYPE OF BUSINESS WE WOULD SELL TO, and it is used verbatim as a "
    "Google Maps search query. It must name businesses that BUY software, never businesses that "
    "SELL it, and never a solution description.\n"
    "  GOOD: 'dental clinics', 'textile mills', 'immigration solicitors', 'private "
    "physiotherapy clinics', 'wholesale pharmacy distributors'\n"
    "  BAD:  'ERP for small manufacturers', 'CRM solutions for clinics', 'custom software for "
    "retailers', 'digital transformation consultants'\n"
    "Anything phrased as 'X for Y', or naming ERP/CRM/software/web/IT/apps, is WRONG: searching it "
    "returns our own competitors, and we then cold-email software houses offering to build them "
    "software. Name the industry itself, as its owner would describe their own business.\n"
    "Each niche must be 2 to 4 words, plural, and searchable on a map."
)

CHAT_SYSTEM = (
    "You are Agent 1, the Researcher at a small digital agency. You can discuss your niche research, "
    "your reasoning, and your current task with the CEO. Be concise and friendly. For questions outside "
    "your role (system status, other agents, approvals), politely defer to the Supervisor."
)


def _set_status(status: str, task: str = "") -> None:
    """Update Agent 1's status board entry. `task` is the live one-line progress
    the office UI shows under the character (cleared when not working)."""
    get_db()["agents"].update_one({"id": "agent1"}, {"$set": {"status": status, "task": task}})


def _col():
    return get_db()["niche_suggestions"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/find-niches")
@safe_endpoint("agent1")
async def find_niches(body: NicheRequest):
    _set_status("working")
    industry_in = (body.industry or "").strip()
    country_in = (body.country or "").strip()
    city_in = (body.city or "").strip()
    self_select = not industry_in or not country_in  # missing either => self-pick

    if not self_select:
        # ---- Path A: CEO supplied industry + country (unchanged behavior) ----
        where = f"{industry_in} in {city_in + ', ' if city_in else ''}{country_in}"
        prompt = (
            f"Industry/region: {where}.\n"
            "Return ONLY a JSON array of 3-4 objects, each exactly "
            '{"niche_name": string, "reasoning": string}. No text outside the JSON.'
        )
        res = await agent_task("agent1", prompt, task_hint=where, max_tokens=900, purpose="niche", activity=f"Generated niches for {where}")
        if not res["ok"]:
            _set_status("error")
            return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}
        niches = parse_niches(res["text"])
        industry_used, country_used, selection_reasoning = industry_in, country_in, None
    else:
        # ---- Path B: Agent 1 self-selects the missing industry and/or country ----
        if not industry_in and not country_in:
            constraint = (
                "No specific industry or country was provided. Using your own market research "
                "judgment, choose ONE industry and ONE country/region that represents a genuinely "
                "promising, underserved opportunity for a small digital agency offering web "
                "development and CRM development services. Briefly explain why you chose this "
                "industry and country."
            )
        elif country_in and not industry_in:
            constraint = (
                f"The country/region is fixed as {country_in}. Using your own judgment, choose ONE "
                f"industry within {country_in} that is a genuinely promising, underserved opportunity "
                "for a small digital agency offering web + CRM development. Briefly explain why you "
                "chose that industry."
            )
        else:  # industry_in and not country_in
            constraint = (
                f"The industry is fixed as {industry_in}. Using your own judgment, choose ONE "
                f"country/region where {industry_in} is a genuinely promising, underserved opportunity "
                "for a small digital agency offering web + CRM development. Briefly explain why you "
                "chose that country."
            )
        prompt = (
            f"{constraint}\n\n"
            "Then, within that space, identify 3 to 4 non-obvious, underserved niche opportunities, "
            "each with a short explanation of why it's an opportunity.\n"
            "Every niche must name a TYPE OF BUSINESS THAT BUYS software (e.g. 'dental clinics', "
            "'textile mills'), never one that sells it, and never a solution phrase like 'ERP for "
            "manufacturers' \u2014 the niche is used directly as a Google Maps search, so a solution "
            "phrase returns our own competitors.\n"
            "Return ONLY a JSON object exactly: "
            '{"industry": string, "country": string, "selection_reasoning": string, '
            '"niches": [{"niche_name": string, "reasoning": string}, ...]}. No text outside the JSON.'
        )
        res = await agent_task("agent1", prompt, task_hint=constraint, max_tokens=1100, purpose="niche", activity="Self-selected a niche space")
        if not res["ok"]:
            _set_status("error")
            return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}
        parsed = parse_result(res["text"])
        niches = parsed["niches"]
        # Respect any value the CEO did provide; fill the rest from Agent 1's pick.
        industry_used = industry_in or parsed["industry"] or "(unspecified)"
        country_used = country_in or parsed["country"] or "(unspecified)"
        selection_reasoning = parsed["selection_reasoning"] or "Agent 1 selected this space using its own judgment."

    if not niches:
        _set_status("idle")
        return {"ok": False, "error": "Agent 1 got a response but couldn't parse niche suggestions. Try again."}

    record = {
        "id": f"niche_{uuid.uuid4().hex[:8]}",
        "industry": industry_used, "country": country_used, "city": city_in,
        "selection_reasoning": selection_reasoning,
        "niches": niches, "status": "awaiting_supervisor_review",
        "supervisor_note": "", "approved_niche": "", "created_at": _now(),
    }
    _col().insert_one(dict(record))

    # Supervisor sanity-check runs automatically BEFORE the CEO sees anything.
    review = await review_niches(niches, industry_used, country_used)
    note = review["note"] if review["ok"] else f"Supervisor review unavailable: {review['error']}"
    _col().update_one({"id": record["id"]}, {"$set": {"supervisor_note": note, "status": "awaiting_ceo_approval"}})

    _set_status("idle")  # Agent 1 waits; the workflow sub-state lives on the record.
    return {"ok": True, "record": serialize(_col().find_one({"id": record["id"]}))}


@router.get("/niches/pending")
@safe_endpoint("agent1")
async def pending_niches():
    docs = list(_col().find({"status": "awaiting_ceo_approval"}))
    docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return {"ok": True, "pending": [serialize(d) for d in docs]}


@router.post("/niches/{niche_id}/approve")
@safe_endpoint("agent1")
async def approve_niche(niche_id: str, body: dict):
    doc = _col().find_one({"id": niche_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Niche set not found")
    chosen = body.get("niche_name", "")
    names = [n["niche_name"] for n in doc["niches"]]
    if chosen not in names:
        raise HTTPException(status_code=400, detail="That niche is not part of this set")
    # Record the CEO's decision, then (Phase 4) automatically kick off the
    # background lead-generation pipeline for the approved niche.
    niches = [{**n, "selected": (n["niche_name"] == chosen)} for n in doc["niches"]]
    _col().update_one({"id": niche_id}, {"$set": {"niches": niches, "approved_niche": chosen, "status": "approved"}})
    record = _col().find_one({"id": niche_id})
    from pipeline.pipeline_routes import trigger_pipeline  # local import avoids cycle
    trigger_pipeline(record)
    log.info("CEO approved niche '%s' (set %s) — lead-gen pipeline started", chosen, niche_id)
    return {"ok": True, "approved_niche": chosen, "note": "Niche approved — lead generation has started."}


@router.post("/niches/{niche_id}/reject-all")
@safe_endpoint("agent1")
async def reject_all(niche_id: str):
    doc = _col().find_one({"id": niche_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Niche set not found")
    _col().update_one({"id": niche_id}, {"$set": {"status": "rejected"}})
    _set_status("idle")
    return {"ok": True, "note": "All suggestions rejected. Request a new set when ready."}


@router.post("/chat")
@safe_endpoint("agent1")
async def chat(body: ChatBody):
    # Status is left as-is (frontend sets "in_ceo_office" while chatting).
    latest = list(_col().find({}))
    latest.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    ctx = ""
    if latest:
        d = latest[0]
        ctx = (
            f"Your most recent niche research was for {d['industry']} in {d['country']}. "
            f"Suggestions: {', '.join(n['niche_name'] for n in d['niches'])}. Status: {d['status']}."
        )
    res = await agent_chat("agent1", body.message, body.history, extra_context=f"(Context: {ctx})" if ctx else None)
    if res["ok"]:
        return {"ok": True, "reply": res["text"]}
    return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}


class HarvestBody(BaseModel):
    niche: str
    city: str = ""
    country: str = ""
    target: int = 50
    exclude_existing: bool = True   # skip businesses already in the CRM


@router.post("/harvest-leads")
@safe_endpoint("agent1")
async def harvest_leads_route(body: HarvestBody):
    """Search continuously until `target` QUALIFIED leads are found.

    Qualified = has a verified (never guessed) contact method AND a website with
    real, evidenced problems. Results are staged as a pending batch for the CEO
    to approve — nothing enters the working CRM automatically.
    """
    import uuid as _uuid

    from crm.leads_routes import add_leads
    from shared import notifications

    from .lead_harvester import harvest_leads

    target = max(1, min(body.target, 200))
    where = ", ".join(x for x in (body.city, body.country) if x) or "your area"

    # Don't re-collect businesses we already hold.
    exclude: set[str] = set()
    if body.exclude_existing:
        for d in get_db()["leads"].find({}, {"business_name": 1, "website": 1}):
            site = (d.get("website") or "").strip().lower()
            if site:
                host = site.split("//")[-1].split("/")[0]
                exclude.add(host[4:] if host.startswith("www.") else host)
            elif d.get("business_name"):
                exclude.add(d["business_name"].strip().lower())

    _set_status("working", f"Hunting {target} qualified leads: {body.niche} in {where}")
    try:
        result = await harvest_leads(
            body.niche, body.city, body.country, target=target, exclude_keys=exclude,
            progress=lambda m: _set_status("working", m[:120]),
        )
    except Exception as exc:  # noqa: BLE001
        _set_status("error", f"Lead hunt failed: {exc}")
        log.error("Harvest failed (isolated): %s", exc)
        return {"ok": False, "error": f"Lead hunt failed: {exc}"}

    leads = result["leads"]
    if not leads:
        _set_status("idle")
        return {"ok": True, "added": 0, "batch_id": "", **result,
                "next_options": _next_options(body.niche, result)}

    # Stage as a pending batch awaiting CEO approval.
    batch_id = f"harvest_{_uuid.uuid4().hex[:8]}"
    for lead in leads:
        lead["status"] = "pending_approval"
        lead["batch_id"] = batch_id
    stored = add_leads(leads, source="agent1_harvest",
                       last_action=f"Harvested + audited by Agent 1 ({body.niche})")

    notifications.notify(
        "approval",
        f"{stored['added']} qualified leads ready for review",
        f"Agent 1 examined {result['examined']} businesses across {result['rounds']} searches for "
        f"'{body.niche}' in {where}. Every lead has a verified contact and evidenced website problems.",
        agent_id="agent1", action="leads_pending", ref_id=batch_id,
    )
    _set_status("idle")
    return {"ok": True, "batch_id": batch_id, **stored, **result,
            "next_options": _next_options(body.niche, result)}


def _next_options(niche: str, result: dict) -> list[dict]:
    """What Agent 1 offers to do next once a harvest finishes."""
    options = [
        {"action": "more_same_niche",
         "label": f"Find more leads in '{niche}'",
         "hint": ("There may be more to find — I'll skip everything already collected."
                  if result.get("complete")
                  else "I may have exhausted this niche/area, so this could return few results.")},
        {"action": "different_niche",
         "label": "Search a different niche",
         "hint": "Tell me the new niche and I'll start a fresh hunt."},
        {"action": "widen_location",
         "label": "Widen the location",
         "hint": "Search a bigger area (whole country) for the same niche."},
        {"action": "stop",
         "label": "Stop here",
         "hint": "Review and approve what I've found."},
    ]
    return options


class GenerateLeadsBody(BaseModel):
    niche: str
    city: str = ""
    country: str = ""
    count: int = 7


@router.post("/generate-leads")
@safe_endpoint("agent1")
async def generate_leads(body: GenerateLeadsBody):
    """Agent 1 researches leads for a niche and writes them DIRECTLY into the CRM
    leads table (deduped), instead of only printing them in chat."""
    from .niche_model import _load_json
    from crm.leads_routes import add_leads

    n = max(1, min(body.count, 25))
    where = ", ".join(x for x in (body.city, body.country) if x) or "the target region"
    prompt = (
        f"Generate {n} realistic potential B2B lead companies for the niche '{body.niche}' in {where}. "
        "These are prospects a digital agency (web + CRM development) could sell to. "
        "Put the primary pain point and any contact-source hint in 'notes'. "
        "Leave website as \"\" if unknown. Do not invent phone numbers or emails.\n\n"
        "CRITICAL OUTPUT RULE: Respond with ONLY a raw JSON array and NOTHING else — no reasoning, "
        "no preamble, no explanation, no markdown fences. Your entire reply must start with '[' and end with ']'. "
        "Each element is an object with exactly these keys: "
        "business_name, niche, city, country, website, notes.\n"
        "Example: [{\"business_name\":\"Acme Corp\",\"niche\":\"" + body.niche + "\",\"city\":\"" + (body.city or "") +
        "\",\"country\":\"" + (body.country or "") + "\",\"website\":\"\",\"notes\":\"pain point here\"}]"
    )
    res = await agent_task("agent1", prompt, task_hint=f"lead research: {body.niche} {where}",
                           max_tokens=2200, purpose="task", activity=f"Researched leads for {body.niche} in {where}")
    if not res["ok"]:
        return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}

    raw = _load_json(res["text"])
    rows = raw if isinstance(raw, list) else (raw.get("leads") if isinstance(raw, dict) else None)
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "error": "Agent 1 did not return parseable lead data. Try again or reduce the count.",
                "raw": res["text"][:500]}

    # Normalize + fill niche/city/country defaults from the request.
    prepared = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        prepared.append({
            "business_name": r.get("business_name") or r.get("company_name") or r.get("name") or "",
            "niche": r.get("niche") or body.niche,
            "city": r.get("city") or body.city,
            "country": r.get("country") or body.country,
            "website": r.get("website") or "",
            "notes": r.get("notes") or r.get("primary_pain_point") or "",
            "status": "new",
        })
    # HARD RULE: never store a lead without a documented reason. Audit every
    # candidate's website; drop the ones whose site is already fine (they are not
    # prospects for web/SEO work) and attach the evidence to the rest.
    from .site_auditor import audit_leads
    _set_status("working", f"Auditing {len(prepared)} websites")
    try:
        await audit_leads(prepared)
    except Exception as exc:  # noqa: BLE001 - audit failure must not store blind leads
        _set_status("idle")
        log.error("Lead audit failed (isolated): %s", exc)
        return {"ok": False, "error": f"Could not audit these leads, so none were saved: {exc}"}

    qualified = [l for l in prepared if l.get("site_audit", {}).get("qualified")]
    dropped = len(prepared) - len(qualified)
    # Belt-and-braces: anything still missing a reason is never stored.
    qualified = [l for l in qualified if l.get("collection_reason")]

    if not qualified:
        _set_status("idle")
        return {"ok": True, "added": 0, "skipped": 0, "dropped_no_reason": dropped,
                "note": (f"Checked {len(prepared)} businesses — none qualified. Their websites are "
                         "already in good shape, so there is no problem for us to solve."),
                "niche": body.niche, "city": body.city, "country": body.country}

    result = add_leads(qualified, source="agent1", last_action=f"Researched + audited by Agent 1 ({body.niche})")
    _set_status("idle")
    return {"ok": True, **result, "dropped_no_reason": dropped,
            "niche": body.niche, "city": body.city, "country": body.country}
