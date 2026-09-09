"""Agent 3 (Outreach) — personalized cold emails + reply handling.

Writes a personalized email per lead (Claude), sends via SMTP with randomized
delays + a daily cap, then an interval IMAP job reads replies, classifies them
(Claude), auto-closes negatives, and surfaces interested/question/unclear
replies to the CEO with a suggested response. NOTHING is ever auto-sent to an
interested lead — the CEO must explicitly act.
"""

from __future__ import annotations

import asyncio
import random
import re
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared import company_profile, notifications
from shared.ai_context import agent_chat, agent_task
from shared.claude_client import call_claude
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint
from shared.settings_store import get_config, get_icp

from .email_designer import render_email_html, render_email_lite
from .followup import ANGLE_BRIEF as FOLLOWUP_ANGLE_BRIEF
from .followup import due_leads, next_step_due, sequence_state
from .mailer import fetch_replies, outbound_content_issues, send_email

log = get_logger("agent3")
router = APIRouter(prefix="/agent3", tags=["agent3"])

# Randomized send delay range (seconds). Overridable for testing.
SEND_DELAY = (15, 45)

WRITE_SYSTEM = (
    "You are a top-performing salesperson writing a cold email. You are NOT an auditor, a consultant, "
    "or a report generator. Your only job is to make one busy business owner curious enough to reply.\n\n"
    "THE MOST IMPORTANT RULE — SELL THE PROBLEM, NEVER GIVE AWAY THE FIX:\n"
    "You have private audit data about their website. That is your leverage, not your gift. NEVER list "
    "the technical faults, never quote measurements, tag names or error details, and never explain how "
    "to fix anything. If you hand them a fix-list they will forward it to a cheaper developer and you "
    "get nothing. Instead, translate what you found into the BUSINESS CONSEQUENCE they already feel:\n"
    "  - slow site        -> 'customers give up before your page opens'\n"
    "  - no meta/H1/SEO   -> 'you're invisible when people search for what you sell'\n"
    "  - not mobile-ready -> 'the half of your customers on phones can't use it'\n"
    "  - no contact route -> 'people who want to buy can't find a way to reach you'\n"
    "  - dead/no website  -> 'anyone checking you out finds nothing and moves on'\n"
    "Hint that you know specifically what is wrong, but keep the specifics to yourself — that "
    "curiosity gap is what earns the reply. Never name the fault itself. If you catch yourself "
    "writing a phrase only a developer would use (heading, meta description, tag, alt text, schema, "
    "contact form, load time in seconds, mobile viewport), delete it and write what it costs their "
    "business instead.\n\n"
    "YOUR METHOD:\n"
    "1. Open with a concrete human moment, not a metric: 'someone looked you up on their phone last "
    "night and gave up waiting'. Make them picture the lost customer.\n"
    "2. Be confident and warm, with light knowing humour. Wry, never mocking — you are on their side. "
    "Never insult their business or their website.\n"
    "3. Name the cost of doing nothing in human terms: the enquiries quietly going to the competitor "
    "whose site works. Never invent statistics, percentages or figures.\n"
    "4. Close by offering the WORK, not the audit: that you can update what they already have or "
    "build them something new, whichever suits them, and that you also handle CRM, ERP and other "
    "business software if that is on their list. One easy low-friction line. No pressure, no hard "
    "meeting demand, and never offer to email them a list of what is wrong.\n\n"
    "HARD RULES:\n"
    "- Output ONLY the finished email. No reasoning, no notes to yourself, no headings like 'Subject:' "
    "inside the body, no checklists, no bullet-point plans, no commentary about instructions or "
    "personas. If you think through anything, keep it entirely to yourself.\n"
    "- Every email must be structurally DIFFERENT: vary the opening, rhythm and angle. Never a formula.\n"
    "- Sound like one person typing to another. Contractions, plain words, short sentences.\n"
    "- Banned: 'I hope this email finds you well', 'I wanted to reach out', 'game-changer', "
    "'revolutionise', 'synergy', 'in today's digital landscape', ALL CAPS, multiple exclamation marks.\n"
    "- 80-140 words. Never invent facts, names, prices or contact details.\n"
    "- Do NOT write a greeting, sign-off, signature or contact details — those are added around "
    "your text automatically. Start straight into the first sentence.\n"
    "- Do NOT use alarmist or pressure language: no 'crisis', 'losing thousands', 'act now', "
    "'urgent', fake scarcity or deadlines. Calm specificity is more credible and gets more replies.\n"
    "- The reader should think 'this person actually looked at my business specifically'. Earn that "
    "with real detail — their business name, their city, their industry — never with hype.\n"
    "Start your response with 'Subject: ...' then a blank line, then the email body."
)

CLASSIFY_SYSTEM = (
    "You classify replies to cold outreach emails. Respond ONLY with a JSON object "
    '{"category": one of "negative"|"interested"|"question"|"unclear", "reasoning": string}. '
    "negative = not interested/decline/unsubscribe; interested = positive interest, wants info, asks "
    "pricing/next steps; question = asks something specific needing an answer but not clearly positive/"
    "negative; unclear = doesn't clearly fit."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agents():
    return get_db()["agents"]


def _leads():
    return get_db()["leads"]


def _set_status(status: str, task: str = "") -> None:
    _agents().update_one({"id": "agent3"}, {"$set": {"status": status, "task": task}})


# ---- daily sending cap -----------------------------------------------------
def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _sent_today() -> int:
    doc = get_db()["send_log"].find_one({"_id": _today_key()})
    return int(doc.get("count", 0)) if doc else 0


def _record_send() -> None:
    get_db()["send_log"].update_one({"_id": _today_key()}, {"$inc": {"count": 1}}, upsert=True)


def _remaining_cap() -> int:
    return max(0, get_config()["daily_send_cap"] - _sent_today())


# ---- email generation ------------------------------------------------------
_SIGNOFF_RE = re.compile(
    r"\n\s*(?:best regards|kind regards|warm regards|regards|sincerely|thanks|thank you|cheers|"
    r"best wishes|yours (?:sincerely|faithfully))\s*[,.]?\s*\n",
    re.I,
)


def _parse_email(text: str) -> tuple[str, str]:
    """Split 'Subject: …' from the body and REMOVE any sign-off the model wrote.

    The designer renders the real signature (name, title, email, WhatsApp, site)
    from the company profile, so a model-written one would duplicate it.
    """
    subject = "Quick idea for your business"
    body = text.strip()
    m = re.match(r"\s*subject:\s*(.+)", text, re.I)
    if m:
        subject = m.group(1).strip()
        body = text[m.end():].strip()

    # Cut everything from the first sign-off line onwards.
    cut = _SIGNOFF_RE.split(body, maxsplit=1)
    if len(cut) > 1:
        body = cut[0].strip()
    # Drop a leading greeting — the template renders "Hi {first_name}," itself,
    # using the real contact name (or a neutral fallback), never an invented one.
    body = re.sub(r"^\s*(?:hi|hello|hey|dear|good (?:morning|afternoon|evening))\b[^\n,]{0,40},?\s*\n+",
                  "", body, count=1, flags=re.I).strip()
    # Safety net: drop any trailing contact lines the model appended without a sign-off.
    lines = body.splitlines()
    while lines and re.match(r"^\s*(?:email|e-mail|whatsapp|phone|tel|website|web)\s*[:\-]",
                             lines[-1], re.I):
        lines.pop()

    # Models often skip the valediction and simply sign their name, e.g.
    # "Kashif Rehman — CEO". _SIGNOFF_RE only matches words like "Regards",
    # so that slips through and the template then renders the real signature
    # underneath it — the reader sees the sign-off twice. Drop short trailing
    # lines that read as a name/title rather than as a sentence.
    identity = company_profile.outreach_identity()
    known = [x.lower() for x in (identity.get("sender_name") or "",
                                 identity.get("company_name") or "") if x]
    _NAME_TITLE = re.compile(r"^[A-Z][\w.'-]*(\s+[A-Z][\w.'-]*)*\s*[\u2014\u2013|,-]\s*\w")
    while lines:
        tail = lines[-1].strip()
        if not tail:
            lines.pop()
            continue
        if (len(tail.split()) <= 6
                and not tail.endswith((".", "?", "!"))
                and (any(k and k in tail.lower() for k in known)
                     or _NAME_TITLE.match(tail))):
            lines.pop()
            continue
        break

    return subject, "\n".join(lines).strip()


def _recent_openings(limit: int = 14) -> list[str]:
    """Opening lines already used — fed back so the writer never reuses one.

    Covers BOTH sent mail and drafts still awaiting approval; without the drafts
    a freshly written batch never sees itself and every email opens the same way
    ("I noticed that…"), which is exactly what spam filters look for.
    """
    seen: list[str] = []
    try:
        for d in _drafts().find({}, {"body": 1}).sort("created_at", -1).limit(40):
            first = (str(d.get("body") or "").strip().split("\n")[0])[:110]
            if first and first not in seen:
                seen.append(first)
    except Exception:  # noqa: BLE001
        pass
    try:
        for d in _leads().find({"outreach_history": {"$exists": True, "$ne": []}}).limit(60):
            for h in d.get("outreach_history", []):
                if h.get("type") == "email" and h.get("body"):
                    first = (h["body"].strip().split("\n")[0])[:110]
                    if first and first not in seen:
                        seen.append(first)
    except Exception:  # noqa: BLE001
        pass
    return seen[:limit]


# Rotating opening STRUCTURES. One is picked per lead so the batch never settles
# into a single formula — the "I noticed that…" problem.
_OPENING_STYLES = (
    "Open with a specific moment a customer experiences — put the reader in that scene. "
    "Do NOT start with 'I noticed' or 'I took a look'.",
    "Open with a short, direct question about their business. No preamble.",
    "Open by stating something concrete and factual about their online presence in one blunt "
    "sentence. No 'I noticed', no hedging.",
    "Open by naming their business and city in the first four words, then the observation.",
    "Open with a candid one-line admission that this is a cold email, then get straight to the "
    "point in the next sentence. Dry, not apologetic.",
    "Open with a comparison to a competitor's experience — without naming any competitor.",
    "Open mid-thought, as if continuing a conversation, then explain what prompted it.",
    "Open with the outcome they are missing, stated plainly, before mentioning their site at all.",
)


# Technical finding -> the business consequence the OWNER feels. The email talks
# about the consequence only; the technical detail is what they have to reply to get.
_CONSEQUENCE = {
    "no_website": "anyone who looks them up online finds nothing at all and goes to a competitor",
    "site_unreachable": "their website is not opening for customers who try to visit it",
    "http_error": "visitors are hitting an error page instead of their business",
    "no_https": "browsers are warning visitors that their site is not secure, which scares people off",
    "very_slow": "customers give up and leave before the page even finishes opening",
    "slow": "the site is slow enough that impatient visitors drop off before seeing anything",
    "not_mobile_friendly": "the many customers browsing on phones get an unusable, pinch-and-zoom experience",
    "no_contact_route": "people who actually want to buy cannot find a way to get in touch",
    "no_contact_form": "interested visitors have no quick way to send an enquiry, so most simply don't",
    "no_title": "they are effectively invisible in search results",
    "weak_title": "they look unconvincing in search results next to competitors",
    "no_meta_description": "they are losing clicks in search results to competitors who look more relevant",
    "no_h1": "search engines cannot tell what the business does, so they rank below competitors",
    "no_structured_data": "competitors show up with richer, more clickable search listings than they do",
    "images_missing_alt": "they are missing search traffic and some visitors cannot use the site properly",
    "no_analytics": "they have no idea where their enquiries are coming from or what is being wasted",
    "outdated_cms": "their site is running on out-of-date software that is a real security risk",
    "table_layout": "the site looks dated next to competitors and breaks on phones",
    "legacy_html": "the site looks visibly old, which costs them credibility with new customers",
    "flash_content": "part of their site simply does not display for anyone any more",
    "heavy_page": "the site is heavy enough that mobile users on slower connections give up",
    "no_open_graph": "when someone shares their link on WhatsApp it looks broken and untrustworthy",
    "no_whatsapp": "local customers who prefer WhatsApp have no easy way to message them",
}


def _angle_for(lead: dict) -> str:
    """Deterministic, evidence-based angle so every email opens differently and
    is anchored to something REAL about that specific business."""
    name = lead.get("business_name", "this business")
    city = lead.get("city") or lead.get("country") or ""
    niche = lead.get("niche", "")
    notes = (lead.get("notes") or "").strip()

    # Strongest angle: a real problem we OBSERVED on their site — but expressed as
    # the CONSEQUENCE the owner feels, never as the technical finding itself. The
    # raw evidence is our leverage and stays private.
    audit = lead.get("site_audit") or {}
    findings = audit.get("findings") or []
    if findings:
        consequences = [_CONSEQUENCE.get(f.get("code", ""), "") for f in findings[:3]]
        consequences = [c for c in consequences if c]
        if consequences:
            main = consequences[0]
            extra = (" There is more than one issue like this, which strengthens the case that it is "
                     "costing them enquiries.") if len(consequences) > 1 else ""
            return (
                f"PRIVATE (never state the technical detail): we checked their site and the real-world "
                f"impact is — {main}.{extra}\n"
                f"Open by painting that lost-customer moment in plain human language. Make it clear you "
                f"looked at their site specifically and know what is wrong, but DO NOT name the technical "
                f"faults, measurements or how to fix them. Close by offering the work — updating their "
                f"current site or building a new one — never by offering to send them the findings."
            )
    if notes:
        return f"Their own listing/notes mention: \"{notes[:180]}\". Open by referencing that specific detail."
    if lead.get("website") and not lead.get("has_working_website"):
        return (f"Their listed website ({lead.get('website')}) does not load. Open by mentioning you tried to "
                "visit it and it appears down — helpful, not critical.")
    if not lead.get("website"):
        return (f"{name} has no website listed on their public profile. Open by noting how {niche} businesses "
                f"in {city} are losing enquiries to competitors who are easier to find online.")
    if lead.get("email_confidence") == "guessed":
        return (f"Open by referencing {niche} operations specifically in {city} — a concrete workflow problem "
                "that size of business faces, not a generic pitch.")
    return (f"Open with a specific, verifiable observation about running a {niche} business in {city} — "
            "one operational bottleneck, named concretely.")


async def _write_email(lead: dict, followup_angle: str = "") -> dict:
    identity = company_profile.outreach_identity()
    # A follow-up has its own brief; the first-touch angle would restate the
    # pitch they have already ignored once.
    angle = (FOLLOWUP_ANGLE_BRIEF.get(followup_angle) or _angle_for(lead)
             if followup_angle else _angle_for(lead))
    avoid = _recent_openings()
    # Rotate the opening structure per lead so a batch never uses one formula.
    opening_style = _OPENING_STYLES[
        sum(ord(c) for c in str(lead.get("id") or lead.get("business_name") or "x")) % len(_OPENING_STYLES)
    ]
    avoid_block = ("\n\nDO NOT open with any of these lines or a paraphrase of them — they were used for other "
                   "recipients and repetition gets mail flagged as spam:\n- " + "\n- ".join(avoid)) if avoid else ""

    contact_bits = [x for x in (
        f"email: {identity['contact_email']}" if identity["contact_email"] else "",
        f"WhatsApp: {identity['whatsapp']}" if identity["whatsapp"] else "",
        f"phone: {identity['phone']}" if identity["phone"] else "",
        f"website: {identity['website']}" if identity["website"] else "",
    ) if x]
    for l in identity["links"]:
        contact_bits.append(f"{l.get('label','link')}: {l.get('url')}")

    prompt = (
        f"Write ONE cold outreach email to a specific business.\n\n"
        f"DIRECTION OF THIS EMAIL (do not reverse it): YOU are the seller. You are pitching YOUR "
        f"services (listed under SENDER below) TO the recipient. You are NOT enquiring about, "
        f"applying to, or buying anything from them. Never ask them to send you information, "
        f"pricing, or opportunities. The recipient's own words in 'Public notes' describe THEIR "
        f"business — use them only to understand who they are, never as something you want to buy.\n\n"
        f"RECIPIENT:\n"
        f"- Business: {lead.get('business_name')}\n"
        f"- Industry/niche: {lead.get('niche')}\n"
        f"- Location: {lead.get('city') or ''} {lead.get('country') or ''}\n"
        f"- Website: {lead.get('website') or 'none listed'}"
        f"{' (does not load)' if lead.get('website') and not lead.get('has_working_website') else ''}\n"
        f"- Public notes: {lead.get('notes') or 'none'}\n\n"
        f"YOUR ANGLE FOR THIS SPECIFIC EMAIL:\n{angle}\n\n"
        f"SENDER (you) — use ONLY these real details, never invent contact info:\n"
        f"- Company: {identity['company_name'] or '(not set)'}\n"
        f"- Services you sell: {', '.join(identity['services']) or '(not set)'}\n"
        f"- Contact details to include in the sign-off: {'; '.join(contact_bits) or '(none configured)'}\n"
        f"- Sign as: {identity['sender_name'] or 'the team'}"
        f"{' — ' + identity['sender_title'] if identity['sender_title'] else ''}\n"
        f"- Tone: {identity['tone'] or 'professional and concise'}\n"
        + (f"\nSTRUCTURE TO FOLLOW:\n{identity['template']}\n" if identity["template"] else "")
        + "\nDELIVERABILITY RULES (critical — this must not land in spam):\n"
        "1. Write 90-150 words. Short beats long.\n"
        "2. Plain conversational text. NO marketing hype, NO ALL-CAPS, no exclamation marks, "
        "no words like FREE, GUARANTEE, ACT NOW, LIMITED TIME, 100%, $$$.\n"
        "3. Reference the recipient's actual situation in the first sentence — it must be obvious "
        "this was written for them and could not be sent to anyone else.\n"
        "4. Exactly ONE soft call to action (a question inviting a reply), not a hard sell.\n"
        "5. No attachments, no tracking language, at most one link.\n"
        "6. Do NOT write a greeting, sign-off, signature or contact details. The template renders "
        "the real signature automatically, so anything you add there is stripped and wasted.\n"
        + f"\n\nOPENING STYLE FOR THIS EMAIL (follow it — it is different every time):\n{opening_style}\n"
        "\nSUBJECT LINE: make it specific to THIS business. Do not start with 'Enhancing', "
        "'Improving', 'Optimizing' or 'Boosting' — those are overused and look templated.\n"
        + avoid_block +
        "\n\nOUTPUT FORMAT (exactly):\nSubject: <subject line, under 60 chars, specific, no clickbait>\n\n<email body>"
    )
    res = await agent_task(
        "agent3", prompt,
        task_hint=f"{lead.get('niche','')} {lead.get('business_name','')} {lead.get('notes','')}",
        max_tokens=900, purpose="outreach",
        activity=f"Wrote outreach email to {lead.get('business_name','a lead')}",
    )
    if not res["ok"]:
        return {"ok": False, "error": res["error"], "kind": res.get("error_kind")}
    subject, body = _parse_email(res["text"])

    # SEND-SAFETY GATE: never let model planning, placeholders or a truncated
    # body reach a real prospect. On failure, tell the model exactly what was
    # wrong and regenerate once.
    issues = outbound_content_issues(subject, body)
    if issues:
        log.warning("Draft failed send-safety for %s: %s", lead.get("business_name"), "; ".join(issues))
        retry = await agent_task(
            "agent3",
            f"{prompt}\n\nYour previous draft was REJECTED and cannot be sent because: "
            f"{'; '.join(issues)}. Write it again from scratch. Output only the finished "
            f"email, starting with 'Subject:'. No commentary, no placeholders in brackets.",
            task_hint=f"rewrite {lead.get('business_name','')}",
            max_tokens=900, purpose="outreach_rewrite",
        )
        if not retry["ok"]:
            return {"ok": False, "error": retry["error"], "kind": retry.get("error_kind")}
        subject, body = _parse_email(retry["text"])
        issues = outbound_content_issues(subject, body)

    if issues:
        return {"ok": False, "kind": "unsafe_content",
                "error": "Draft failed send-safety checks twice: " + "; ".join(issues)}

    # Designed HTML version, built from the lead's real audit + your company data.
    html = render_email_lite(body, lead, company_profile.get_profile())
    return {"ok": True, "subject": subject, "body": body, "html": html,
            "spam_flags": _spam_check(subject, body)}


_SPAM_WORDS = ("free", "guarantee", "act now", "limited time", "100%", "risk-free",
               "click here", "buy now", "cash", "winner", "urgent", "no obligation")


def _spam_check(subject: str, body: str) -> list[str]:
    """Deterministic (no-AI) deliverability lint. Flags only — never blocks."""
    flags = []
    text = f"{subject}\n{body}"
    low = text.lower()
    for w in _SPAM_WORDS:
        if w in low:
            flags.append(f"spam-trigger word: '{w}'")
    if subject.isupper() or body.count("!") > 1:
        flags.append("shouty punctuation/caps")
    if len(body.split()) > 220:
        flags.append("too long (>220 words)")
    if body.count("http") > 2:
        flags.append("too many links")
    return flags


class SendBody(BaseModel):
    lead_ids: list[str] | None = None


async def _run_outreach(lead_ids: list[str] | None) -> None:
    """Background batch. Never raises (isolated)."""
    try:
        if lead_ids:
            leads = [d for d in (_leads().find_one({"id": lid}) for lid in lead_ids) if d]
        else:
            leads = list(_leads().find({"status": "verified"}))

        if not leads:
            _set_status("idle", "")
            return

        remaining = _remaining_cap()
        if remaining <= 0:
            _set_status("idle", "")
            log.info("Daily send cap reached — %d leads queued for the next day.", len(leads))
            return
        to_send = leads[:remaining]
        queued = len(leads) - len(to_send)

        sent = 0
        for i, lead in enumerate(to_send):
            _set_status("working", f"Sending outreach: lead {i + 1} of {len(to_send)}")
            # 1) Write (Claude). Claude failure for one lead -> skip, keep going.
            gen = await _write_email(lead)
            if not gen["ok"]:
                log.warning("Skipping %s — email generation failed: %s", lead.get("id"), gen["error"])
                continue
            # 2) Send (SMTP). A hard SMTP failure stops the batch cleanly.
            result = await asyncio.to_thread(send_email, lead.get("email", ""), gen["subject"], gen["body"])
            if not result["ok"]:
                if result["kind"] in ("no_creds", "smtp_auth", "smtp_error"):
                    _set_status("error", result["error"])
                    log.error("Outreach batch stopped after %d sent: %s", sent, result["error"])
                    return
                log.warning("Skipping %s — %s", lead.get("id"), result["error"])
                continue
            # 3) Record on the lead.
            entry = {"type": "email", "subject": gen["subject"], "body": gen["body"],
                     "spam_flags": gen.get("spam_flags", []), "sent_at": _now()}
            _leads().update_one({"id": lead["id"]}, {
                "$set": {"status": "mailed", "last_action": "Cold email sent by Agent 3", "last_action_timestamp": _now()},
                "$push": {"outreach_history": entry},
            })
            _record_send()
            sent += 1
            # 4) Randomized delay between sends (skip after the last one).
            if i < len(to_send) - 1:
                await asyncio.sleep(random.uniform(*SEND_DELAY))

        _set_status("idle", "")
        log.info("Outreach complete: %d sent, %d queued for next day (cap).", sent, queued)
    except Exception as exc:  # noqa: BLE001
        _set_status("error", f"Outreach batch error: {exc}")
        log.error("Outreach batch crashed (isolated): %s", exc)


def _email_configured() -> bool:
    """Either transport counts: Brevo over HTTPS (needs a key + sender address),
    or direct SMTP (needs the mailbox password)."""
    from shared.settings_store import get_setting_value

    sender = get_setting_value("smtp_email")
    if get_setting_value("brevo_api_key") and sender:
        return True
    return bool(sender and get_setting_value("smtp_app_password"))


def _notify_email_missing(context: str = "") -> None:
    notifications.notify(
        "config", "Email is not configured — Agent 3 cannot send",
        "Add your sending address and app password in Settings → Email (SMTP) so "
        "Agent 3 can send the drafted outreach." + (f" {context}" if context else ""),
        agent_id="agent3", action="settings_email", dedupe_key="smtp_missing",
    )


async def handoff_after_approval(batch_id: str) -> dict:
    """Called right after the CEO approves a lead batch: Agent 3 picks the work up.

    If email is configured -> start sending. If not -> raise a config notification
    and leave the leads queued (nothing is lost, nothing is silently dropped).
    """
    from pipeline.pipeline_routes import _batch_query
    lead_ids = [d["id"] for d in _leads().find({**_batch_query(batch_id), "status": "verified"}, {"id": 1})]
    if not lead_ids:
        return {"started": False, "reason": "no approved leads"}
    if not _email_configured():
        _set_status("error", "No email credentials configured")
        _notify_email_missing(f"{len(lead_ids)} approved leads are waiting.")
        return {"started": False, "reason": "email_not_configured", "queued": len(lead_ids)}
    notifications.resolve("smtp_missing")
    # Draft for CEO review — never send straight off a lead approval.
    asyncio.create_task(draft_batch(DraftBatchBody(count=len(lead_ids), lead_ids=lead_ids)))
    return {"started": True, "drafting": True, "count": len(lead_ids)}


# ---- draft -> CEO review -> send ------------------------------------------
# Nothing is ever sent straight from the writer. Agent 3 drafts a batch, the CEO
# previews every email exactly as the recipient will see it, edits or rejects
# any of them, and only approved drafts go out.
def _drafts():
    return get_db()["email_drafts"]


def _preview_html(html: str) -> str:
    """Swap the cid: logo for a data URI so the review iframe can display it.
    Only used for on-screen preview — the sent email keeps the cid: reference."""
    try:
        import base64

        from .email_designer import LOGO_CID, LOGO_FILE

        if not LOGO_FILE.exists() or f"cid:{LOGO_CID}" not in html:
            return html
        b64 = base64.b64encode(LOGO_FILE.read_bytes()).decode("ascii")
        return html.replace(f"cid:{LOGO_CID}", f"data:image/png;base64,{b64}")
    except Exception:  # noqa: BLE001
        return html


class DraftBatchBody(BaseModel):
    count: int = 10
    lead_ids: list[str] | None = None
    city: str | None = None      # target one city at a time
    niche: str | None = None     # and/or one industry


@router.get("/draft-targets")
@safe_endpoint("agent3")
async def draft_targets():
    """Cities and niches that still have un-emailed leads, with counts.

    Feeds the Outreach filter dropdowns so the CEO can see at a glance where
    there is work left — e.g. "Dublin (21)" — instead of guessing.
    """
    already = {d["lead_id"] for d in _drafts().find({"status": {"$in": ["pending", "sent"]}}, {"lead_id": 1})}
    cities: dict[str, int] = {}
    niches: dict[str, int] = {}
    total = 0
    for d in _leads().find({"status": "verified", "email": {"$nin": ["", None]}},
                           {"id": 1, "city": 1, "niche": 1}):
        if d["id"] in already:
            continue
        total += 1
        c = (d.get("city") or "").strip()
        nk = (d.get("niche") or "").strip()
        if c:
            cities[c] = cities.get(c, 0) + 1
        if nk:
            niches[nk] = niches.get(nk, 0) + 1
    tidy = lambda m: [{"value": k, "count": v} for k, v in sorted(m.items(), key=lambda x: -x[1])]
    return {"ok": True, "total": total, "cities": tidy(cities), "niches": tidy(niches)}


@router.post("/draft-batch")
@safe_endpoint("agent3")
async def draft_batch(body: DraftBatchBody):
    """Write N unique emails for approved leads and stage them for review."""
    import uuid as _uuid

    n = max(1, min(body.count, 50))
    if body.lead_ids:
        leads = [d for d in (_leads().find_one({"id": i}) for i in body.lead_ids) if d]
    else:
        # Approved leads that have an address and haven't been emailed yet.
        already = {d["lead_id"] for d in _drafts().find({"status": {"$in": ["pending", "sent"]}}, {"lead_id": 1})}
        # Campaigns run better one city/industry at a time — the copy stays
        # consistent and you can judge what actually gets replies.
        query: dict = {"status": "verified", "email": {"$nin": ["", None]}}
        if body.city:
            query["city"] = {"$regex": f"^{re.escape(body.city.strip())}$", "$options": "i"}
        if body.niche:
            query["niche"] = {"$regex": re.escape(body.niche.strip()), "$options": "i"}
        candidates = [d for d in _leads().find(query) if d["id"] not in already]
        # Write to the best prospects first: those with real audited website faults
        # (highest opportunity score). Leads with no findings give the writer
        # nothing concrete to say, so they go last.
        candidates.sort(key=lambda d: (
            bool((d.get("site_audit") or {}).get("findings")),
            d.get("opportunity_score", 0),
        ), reverse=True)
        leads = candidates[:n]
    if not leads:
        return {"ok": True, "batch_id": "", "drafted": 0,
                "note": "No approved leads are waiting for an email. Approve leads in the CRM first."}

    # Without a company identity the writer invents a role — it has produced
    # emails asking to BUY from the prospect. Refuse rather than send nonsense.
    prof = company_profile.get_profile()
    if not (prof.get("company_name") or "").strip():
        return {"ok": False, "drafted": 0,
                "error": "Set your Company Name in Settings → Company Profile first — without it "
                         "Agent 3 has no identity to write from and produces wrong emails."}

    batch_id = f"draft_{_uuid.uuid4().hex[:8]}"
    drafted, failed = 0, []
    _set_status("working", f"Writing {len(leads)} personalised emails")
    for i, lead in enumerate(leads[:n], start=1):
        _set_status("working", f"Writing email {i} of {min(len(leads), n)}")
        gen = await _write_email(lead)
        if not gen["ok"]:
            failed.append({"lead": lead.get("business_name", ""), "error": gen.get("error", "")})
            continue
        _drafts().insert_one({
            "id": f"D-{_uuid.uuid4().hex[:8].upper()}",
            "batch_id": batch_id,
            "lead_id": lead["id"],
            "business_name": lead.get("business_name", ""),
            "to_email": lead.get("email", ""),
            "subject": gen["subject"],
            "body": gen["body"],
            "html": gen["html"],
            # Preview copy: the review iframe cannot resolve cid: images, so the
            # logo is inlined as a data URI there. The SENT html keeps cid:.
            "preview_html": _preview_html(gen["html"]),
            "spam_flags": gen.get("spam_flags", []),
            "collection_reason": lead.get("collection_reason", ""),
            "opportunity_score": lead.get("opportunity_score", 0),
            "status": "pending",       # pending | approved | rejected | sent | failed
            "edited": False,
            "created_at": _now(),
        })
        drafted += 1
    _set_status("idle")

    if drafted:
        notifications.notify(
            "approval", f"{drafted} emails ready for your review",
            "Agent 3 has written personalised emails. Preview each one and approve before anything is sent.",
            agent_id="agent3", action="drafts_pending", ref_id=batch_id,
        )
    return {"ok": True, "batch_id": batch_id, "drafted": drafted, "failed": failed}


class FollowupBody(BaseModel):
    count: int = 20
    dry_run: bool = False


@router.get("/followups/due")
@safe_endpoint("agent3")
async def followups_due(limit: int = 100):
    """Who is waiting on a follow-up, and which step they are on.

    Read-only: this is the screen that tells the CEO how much is sitting idle.
    """
    rows = []
    for lead, angle in due_leads(_leads(), limit=limit):
        st = sequence_state(lead)
        rows.append({
            "lead_id": lead.get("id"),
            "business_name": lead.get("business_name", ""),
            "email": lead.get("email", ""),
            "city": lead.get("city", ""),
            "niche": lead.get("niche", ""),
            "angle": angle,
            "emails_sent": st["sent_count"],
            "last_sent_at": st["last_sent_at"].isoformat() if st["last_sent_at"] else "",
            "fit_score": lead.get("fit_score", 0),
        })
    return {"ok": True, "total": len(rows), "items": rows}


@router.post("/followups/draft")
@safe_endpoint("agent3")
async def draft_followups(body: FollowupBody):
    """Write follow-up drafts for everyone whose next step is due.

    Drafts only — they land in the same review queue as first-touch emails and
    need the same approval. Nothing is sent from here.
    """
    targets = due_leads(_leads(), limit=max(1, min(body.count, 100)))
    if body.dry_run:
        return {"ok": True, "would_draft": len(targets),
                "items": [{"business_name": l.get("business_name"), "angle": a} for l, a in targets]}
    if not targets:
        return {"ok": True, "drafted": 0, "message": "No follow-ups are due."}

    batch_id = f"FU-{_uuid.uuid4().hex[:8].upper()}"
    asyncio.create_task(_draft_followups_bg(targets, batch_id))
    return {"ok": True, "batch_id": batch_id, "queued": len(targets),
            "message": f"Writing {len(targets)} follow-ups in the background."}


async def _draft_followups_bg(targets: list, batch_id: str) -> None:
    """Background follow-up writer. Never raises (isolated)."""
    drafted = 0
    try:
        _set_status("working", f"Writing {len(targets)} follow-ups")
        for i, (lead, angle) in enumerate(targets, start=1):
            _set_status("working", f"Follow-up {i} of {len(targets)}")
            # Re-check: a reply may have landed while the batch was running.
            fresh = _leads().find_one({"id": lead.get("id")}) or lead
            due, _a, _why = next_step_due(fresh)
            if not due:
                continue
            gen = await _write_email(fresh, followup_angle=angle)
            if not gen["ok"]:
                log.warning("Follow-up draft failed for %s: %s",
                            fresh.get("business_name", ""), gen.get("error", ""))
                continue
            st = sequence_state(fresh)
            _drafts().insert_one({
                "id": f"D-{_uuid.uuid4().hex[:8].upper()}",
                "batch_id": batch_id,
                "lead_id": fresh["id"],
                "business_name": fresh.get("business_name", ""),
                "to_email": fresh.get("email", ""),
                "subject": gen["subject"],
                "body": gen["body"],
                "html": gen["html"],
                "preview_html": _preview_html(gen["html"]),
                "spam_flags": gen.get("spam_flags", []),
                "collection_reason": fresh.get("collection_reason", ""),
                "opportunity_score": fresh.get("opportunity_score", 0),
                "status": "pending",
                "edited": False,
                # Marks this as a sequence step, so the sender records it as a
                # follow-up and the review screen can show which step it is.
                "is_followup": True,
                "followup_angle": angle,
                "followup_step": st["sent_count"],
                "created_at": _now(),
            })
            drafted += 1
        _set_status("idle")
        if drafted:
            notifications.notify(
                "approval", f"{drafted} follow-ups ready for your review",
                "Agent 3 wrote follow-ups for leads that never replied. Approve to send.",
                agent_id="agent3", action="drafts_pending", ref_id=batch_id,
            )
        log.info("Follow-up batch %s: %d drafted.", batch_id, drafted)
    except Exception as exc:  # noqa: BLE001
        _set_status("error", f"Follow-up batch error: {exc}")
        log.error("Follow-up batch crashed (isolated): %s", exc)


def _ser_draft(d: dict) -> dict:
    return {k: d.get(k) for k in
            ("id", "batch_id", "lead_id", "business_name", "to_email", "subject", "body", "html", "preview_html",
             "spam_flags", "collection_reason", "opportunity_score", "status", "edited",
             "created_at", "sent_at", "error")}


@router.get("/drafts")
@safe_endpoint("agent3")
async def list_drafts(status: str = "pending"):
    q = {} if status == "all" else {"status": status}
    docs = list(_drafts().find(q).sort("created_at", -1).limit(200))
    return {"ok": True, "drafts": [_ser_draft(d) for d in docs], "total": len(docs)}


class EditDraftBody(BaseModel):
    subject: str | None = None
    body: str | None = None
    to_email: str | None = None   # CEO can correct/redirect the recipient


@router.put("/drafts/{draft_id}")
@safe_endpoint("agent3")
async def edit_draft(draft_id: str, body: EditDraftBody):
    """CEO edits a draft; the designed HTML is re-rendered from the new copy."""
    d = _drafts().find_one({"id": draft_id})
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    subject = body.subject if body.subject is not None else d.get("subject", "")
    text = body.body if body.body is not None else d.get("body", "")
    to_email = (body.to_email if body.to_email is not None else d.get("to_email", "")).strip()
    if body.to_email is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", to_email):
        raise HTTPException(status_code=400, detail=f"'{to_email}' is not a valid email address.")

    lead = _leads().find_one({"id": d.get("lead_id")}) or {}
    # The footer prints the recipient, so re-render against the edited address.
    html = render_email_lite(text, {**lead, "email": to_email}, company_profile.get_profile())
    _drafts().update_one({"id": draft_id}, {"$set": {
        "subject": subject, "body": text, "to_email": to_email,
        "html": html, "preview_html": _preview_html(html), "edited": True,
        "spam_flags": _spam_check(subject, text)}})
    return {"ok": True, "draft": _ser_draft(_drafts().find_one({"id": draft_id}))}


# ---- WhatsApp outreach (click-to-send, never automated) --------------------
WA_SYSTEM = (
    "You write very short WhatsApp messages for a web development agency contacting a local "
    "business owner. WhatsApp is not email: no subject, no signature, no formal paragraphs.\n\n"
    "RULES:\n"
    "- 2 to 4 short lines, under 60 words total. It must be readable at a glance on a phone.\n"
    "- Open with a respectful greeting appropriate for Pakistan.\n"
    "- Name ONE real problem you observed on their website, as the BUSINESS consequence "
    "(customers leaving, not being found) — never the technical detail, never how to fix it.\n"
    "- End with one easy question inviting a reply.\n"
    "- No hype, no emoji spam (one at most), no ALL CAPS, no links, no price talk.\n"
    "- Sound like a real person typing, not a broadcast."
)


@router.get("/whatsapp/leads")
@safe_endpoint("agent3")
async def whatsapp_leads(status: str = "all", only_usable: bool = True, limit: int = 300):
    """Leads reachable on WhatsApp — those with a usable mobile number."""
    from .whatsapp import serialize as wa_ser

    # One pass over a PROJECTED cursor. `site_audit` is excluded — it is the
    # heaviest field by far and this view only needs the reason line, so pulling
    # it made the endpoint ~40s instead of ~1s.
    projection = {"_id": 0, "site_audit": 0, "outreach_history": 0, "pitch_points": 0,
                  "suggested_reply": 0}
    out: list[dict] = []
    counts: dict[str, int] = {"total": 0, "unusable": 0}
    for lead in _leads().find({"phone": {"$nin": ["", None]}}, projection).limit(1000):
        item = wa_ser(lead)
        if not item["usable"]:
            counts["unusable"] += 1
            if only_usable:
                continue
        else:
            counts["total"] += 1
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        if status != "all" and item["status"] != status:
            continue
        out.append(item)
    out.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    return {"ok": True, "leads": out[:limit], "counts": counts}


class WaMessageBody(BaseModel):
    lead_id: str
    language: str = "english"   # english | roman_urdu


@router.post("/whatsapp/message")
@safe_endpoint("agent3")
async def whatsapp_message(body: WaMessageBody):
    """Write (or re-use) the short message for one lead and return its wa.me link."""
    from .whatsapp import normalise_number, wa_link, wa_state

    lead = _leads().find_one({"id": body.lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    number = normalise_number(lead.get("phone", ""))
    if not number:
        raise HTTPException(status_code=400, detail="This lead has no usable WhatsApp number.")

    angle = _angle_for(lead)
    profile = company_profile.get_profile()
    lang = ("Write in Roman Urdu (Urdu written in English letters), natural and conversational."
            if body.language == "roman_urdu" else "Write in simple, clear English.")
    prompt = (
        f"{lang}\n\n"
        f"BUSINESS: {lead.get('business_name')} — {lead.get('niche','')} in {lead.get('city','')}\n"
        f"YOUR COMPANY: {profile.get('company_name','')} ({', '.join(profile.get('services_offered', [])[:3])})\n"
        f"YOUR NAME: {profile.get('sender_name','')}\n\n"
        f"WHAT YOU FOUND (say the consequence, never the technical detail):\n{angle}\n\n"
        f"Write the WhatsApp message only — no preamble, no quotes around it."
    )
    res = await agent_task("agent3", prompt, max_tokens=400, purpose="whatsapp",
                           draft_instructions=WA_SYSTEM)
    if not res["ok"]:
        return {"ok": False, "error": res["error"]}

    message = res["text"].strip().strip('"')
    _leads().update_one({"id": body.lead_id}, {"$set": {
        "whatsapp.message": message, "whatsapp.updated_at": _now(),
        "whatsapp.status": wa_state(lead).get("status") or "not_contacted",
    }})
    return {"ok": True, "lead_id": body.lead_id, "number": number,
            "message": message, "link": wa_link(number, message)}


class WaUpdateBody(BaseModel):
    status: str | None = None
    remarks: str | None = None
    message: str | None = None


@router.put("/whatsapp/leads/{lead_id}")
@safe_endpoint("agent3")
async def whatsapp_update(lead_id: str, body: WaUpdateBody):
    """Record what happened: message sent, they replied, interested, etc."""
    from .whatsapp import WA_STATUSES, wa_state

    lead = _leads().find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates: dict = {"whatsapp.updated_at": _now()}
    if body.status is not None:
        if body.status not in WA_STATUSES:
            raise HTTPException(status_code=400, detail=f"Unknown status '{body.status}'.")
        updates["whatsapp.status"] = body.status
        if body.status == "message_sent" and not wa_state(lead).get("sent_at"):
            updates["whatsapp.sent_at"] = _now()
    if body.remarks is not None:
        updates["whatsapp.remarks"] = body.remarks[:500]
    if body.message is not None:
        updates["whatsapp.message"] = body.message[:2000]
    _leads().update_one({"id": lead_id}, {"$set": updates})

    from .whatsapp import serialize as wa_ser
    return {"ok": True, "lead": wa_ser(_leads().find_one({"id": lead_id}))}


class ReplyActionBody(BaseModel):
    """A reply is addressed by lead id + the timestamp it arrived."""
    lead_id: str
    received_at: str


def _update_reply(lead_id: str, received_at: str, changes: dict) -> bool:
    """Set flags on one entry inside a lead's outreach_history."""
    lead = _leads().find_one({"id": lead_id})
    if not lead:
        return False
    hist = lead.get("outreach_history") or []
    hit = False
    for h in hist:
        if h.get("type") == "reply" and h.get("received_at", "") == received_at:
            h.update(changes)
            hit = True
    if hit:
        _leads().update_one({"id": lead_id}, {"$set": {"outreach_history": hist}})
    return hit


@router.post("/inbox/read")
@safe_endpoint("agent3")
async def mark_reply_read(body: ReplyActionBody):
    ok = _update_reply(body.lead_id, body.received_at, {"read": True})
    if not ok:
        raise HTTPException(status_code=404, detail="Reply not found")
    return {"ok": True}


@router.post("/inbox/archive")
@safe_endpoint("agent3")
async def archive_reply(body: ReplyActionBody):
    ok = _update_reply(body.lead_id, body.received_at, {"archived": True, "read": True})
    if not ok:
        raise HTTPException(status_code=404, detail="Reply not found")
    return {"ok": True}


@router.post("/inbox/unarchive")
@safe_endpoint("agent3")
async def unarchive_reply(body: ReplyActionBody):
    ok = _update_reply(body.lead_id, body.received_at, {"archived": False})
    if not ok:
        raise HTTPException(status_code=404, detail="Reply not found")
    return {"ok": True}


@router.post("/inbox/delete")
@safe_endpoint("agent3")
async def delete_reply(body: ReplyActionBody):
    """Soft delete — the message stays in the lead's history for the record,
    it just stops appearing in the mailbox."""
    ok = _update_reply(body.lead_id, body.received_at, {"deleted": True})
    if not ok:
        raise HTTPException(status_code=404, detail="Reply not found")
    return {"ok": True}


class InboxReplyBody(BaseModel):
    lead_id: str
    received_at: str
    subject: str | None = None
    body: str


@router.post("/inbox/send-reply")
@safe_endpoint("agent3")
async def send_inbox_reply(body: InboxReplyBody):
    """Reply to a prospect from the mailbox. Plain text: this is a real
    conversation now, not outreach, so no branded template."""
    if not _email_configured():
        _notify_email_missing()
        return {"ok": False, "error": "No email credentials configured — add them in Settings."}
    lead = _leads().find_one({"id": body.lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    to_addr = (lead.get("email") or "").strip()
    if not to_addr:
        return {"ok": False, "error": "This lead has no email address."}

    text = (body.body or "").strip()
    if not text:
        return {"ok": False, "error": "Reply is empty."}
    subject = (body.subject or "").strip() or f"Re: {lead.get('business_name','')}".strip()

    res = await asyncio.to_thread(send_email, to_addr, subject, text, "")
    if not res["ok"]:
        return {"ok": False, "error": res["error"]}

    _leads().update_one({"id": body.lead_id}, {
        "$set": {"last_action": "Replied by CEO", "last_action_timestamp": _now()},
        "$push": {"outreach_history": {
            "type": "reply_sent", "subject": subject, "body": text, "sent_at": _now()}},
    })
    _update_reply(body.lead_id, body.received_at, {"read": True, "replied": True})
    _record_send()
    return {"ok": True, "note": f"Reply sent to {to_addr}."}


@router.get("/mailbox")
@safe_endpoint("agent3")
async def mailbox(folder: str = "drafts", limit: int = 100):
    """Mail-client view of outreach: drafts / sent / replies / failed / rejected.

    Folders are derived from data we already hold — drafts from `email_drafts`,
    and inbound replies from each lead's `outreach_history` — so nothing new is
    stored just to render this.
    """
    folder = (folder or "drafts").lower()
    items: list[dict] = []

    if folder in ("drafts", "sent", "failed", "rejected"):
        status = {"drafts": "pending"}.get(folder, folder)
        for d in _drafts().find({"status": status}).sort("created_at", -1).limit(limit):
            items.append({
                "id": d.get("id"), "kind": "outbound", "business_name": d.get("business_name", ""),
                "to_email": d.get("to_email", ""), "subject": d.get("subject", ""),
                "preview": (d.get("body") or "").strip().replace("\n", " ")[:130],
                "body": d.get("body", ""), "html": d.get("preview_html") or d.get("html", ""),
                "at": d.get("sent_at") or d.get("created_at", ""),
                "status": d.get("status"), "error": d.get("error", ""),
                "edited": bool(d.get("edited")), "spam_flags": d.get("spam_flags", []),
                "collection_reason": d.get("collection_reason", ""),
            })
    elif folder in ("inbox", "archive"):
        # Replies the prospects sent back, newest first. A reply is identified by
        # lead id + received_at, which is stable, so read/archived flags can be
        # written back onto that entry in the lead's outreach_history.
        want_archived = folder == "archive"
        for lead in _leads().find({"outreach_history": {"$exists": True, "$ne": []}}).limit(300):
            for h in lead.get("outreach_history", []):
                if h.get("type") != "reply" or h.get("deleted"):
                    continue
                if bool(h.get("archived")) != want_archived:
                    continue
                items.append({
                    "read": bool(h.get("read")),
                    "archived": bool(h.get("archived")),
                    "id": f"{lead['id']}:{h.get('received_at','')}", "kind": "inbound",
                    "business_name": lead.get("business_name", ""),
                    "to_email": lead.get("email", ""),
                    "subject": h.get("subject", "(reply)"),
                    "preview": (h.get("body") or "").strip().replace("\n", " ")[:130],
                    "body": h.get("body", ""), "html": "",
                    "at": h.get("received_at", ""),
                    "status": lead.get("reply_classification") or "replied",
                    "lead_id": lead["id"],
                    "reply_reasoning": lead.get("reply_reasoning", ""),
                    "suggested_reply": lead.get("suggested_reply", ""),
                })
        items.sort(key=lambda x: x.get("at", ""), reverse=True)
        items = items[:limit]

    counts = {
        "drafts": _drafts().count_documents({"status": "pending"}),
        "sent": _drafts().count_documents({"status": "sent"}),
        "failed": _drafts().count_documents({"status": "failed"}),
        "rejected": _drafts().count_documents({"status": "rejected"}),
        "inbox": 0, "archive": 0, "unread": 0,
    }
    # Reply counts need a scan because the flags live inside outreach_history.
    for lead in _leads().find({"outreach_history.type": "reply"},
                              {"outreach_history": 1}).limit(300):
        for h in lead.get("outreach_history", []):
            if h.get("type") != "reply" or h.get("deleted"):
                continue
            if h.get("archived"):
                counts["archive"] += 1
            else:
                counts["inbox"] += 1
                if not h.get("read"):
                    counts["unread"] += 1
    return {"ok": True, "folder": folder, "items": items, "counts": counts}


class DraftDecision(BaseModel):
    draft_ids: list[str] | None = None
    batch_id: str | None = None


@router.post("/drafts/reject")
@safe_endpoint("agent3")
async def reject_drafts(body: DraftDecision):
    q = _draft_selector(body)
    n = _drafts().update_many({**q, "status": "pending"}, {"$set": {"status": "rejected"}}).modified_count
    return {"ok": True, "rejected": n}


def _draft_selector(body: DraftDecision) -> dict:
    if body.draft_ids:
        return {"id": {"$in": body.draft_ids}}
    if body.batch_id:
        return {"batch_id": body.batch_id}
    return {"id": "__none__"}


@router.post("/drafts/approve-send")
@safe_endpoint("agent3")
async def approve_and_send(body: DraftDecision):
    """CEO-approved drafts are sent — the ONLY path that puts mail on the wire."""
    if not _email_configured():
        _notify_email_missing()
        return {"ok": False, "error": "No email credentials configured — add them in Settings."}
    q = _draft_selector(body)
    ids = [d["id"] for d in _drafts().find({**q, "status": "pending"}, {"id": 1})]
    if not ids:
        return {"ok": True, "sent": 0, "note": "No pending drafts matched."}
    _drafts().update_many({"id": {"$in": ids}}, {"$set": {"status": "approved"}})
    asyncio.create_task(_send_approved(ids))
    return {"ok": True, "approved": len(ids),
            "note": f"Sending {len(ids)} approved email(s) — Agent 3 is working through them."}


async def _send_approved(draft_ids: list[str]) -> None:
    """Background sender for approved drafts. Never raises (isolated)."""
    try:
        sent = 0
        for i, did in enumerate(draft_ids):
            d = _drafts().find_one({"id": did})
            if not d or d.get("status") != "approved":
                continue
            remaining = _remaining_cap()
            if remaining <= 0:
                log.info("Daily cap reached — %d drafts stay approved for tomorrow.", len(draft_ids) - sent)
                break
            _set_status("working", f"Sending approved email {i + 1} of {len(draft_ids)}")
            res = await asyncio.to_thread(send_email, d.get("to_email", ""), d.get("subject", ""),
                                          d.get("body", ""), d.get("html", ""))
            if not res["ok"]:
                _drafts().update_one({"id": did}, {"$set": {"status": "failed", "error": res["error"]}})
                if res.get("kind") in ("no_creds", "smtp_auth"):
                    _set_status("error", res["error"])
                    return
                continue
            _drafts().update_one({"id": did}, {"$set": {"status": "sent", "sent_at": _now()}})
            _leads().update_one({"id": d.get("lead_id")}, {
                "$set": {"status": "mailed",
                         "last_action": ("Follow-up sent by Agent 3" if d.get("is_followup")
                                         else "Cold email sent by Agent 3"),
                         "last_action_timestamp": _now()},
                "$push": {"outreach_history": {
                    "type": "followup" if d.get("is_followup") else "email",
                    "subject": d.get("subject", ""), "body": d.get("body", ""),
                    "html": d.get("html", ""), "sent_at": _now(),
                    "followup_angle": d.get("followup_angle", "")}},
            })
            _record_send()
            sent += 1
            if i < len(draft_ids) - 1:
                await asyncio.sleep(random.uniform(*SEND_DELAY))
        _set_status("idle")
        log.info("Approved-send finished: %d sent.", sent)
    except Exception as exc:  # noqa: BLE001
        _set_status("error", f"Send batch error: {exc}")
        log.error("Approved-send crashed (isolated): %s", exc)


@router.post("/drafts/retry")
@safe_endpoint("agent3")
async def retry_failed(body: DraftDecision):
    """Put failed sends back in the queue and try again.

    A failure is usually transient (blocked port, timeout, provider hiccup), so
    the draft is preserved rather than discarded — this re-approves and resends.
    """
    if not _email_configured():
        _notify_email_missing()
        return {"ok": False, "error": "No email credentials configured — add them in Settings."}
    q = _draft_selector(body) if (body.draft_ids or body.batch_id) else {}
    ids = [d["id"] for d in _drafts().find({**q, "status": "failed"}, {"id": 1})]
    if not ids:
        return {"ok": True, "retried": 0, "note": "No failed emails to retry."}
    _drafts().update_many({"id": {"$in": ids}}, {"$set": {"status": "approved"}, "$unset": {"error": ""}})
    asyncio.create_task(_send_approved(ids))
    return {"ok": True, "retried": len(ids),
            "note": f"Retrying {len(ids)} failed email(s)."}


@router.post("/send-outreach")
@safe_endpoint("agent3")
async def send_outreach(body: SendBody):
    # Fast pre-check so the CEO gets an immediate, clear error if unconfigured.
    if not _email_configured():
        _set_status("error", "No email credentials configured — add them in Settings")
        _notify_email_missing()
        return {"ok": False, "error": "No email credentials configured — add them in Settings"}
    notifications.resolve("smtp_missing")
    asyncio.create_task(_run_outreach(body.lead_ids))
    return {"ok": True, "note": "Outreach started — Agent 3 is sending personalized emails."}


# ---- reply checking + classification --------------------------------------
async def _classify(reply_body: str) -> dict:
    res = await call_claude(CLASSIFY_SYSTEM, [{"role": "user", "content": reply_body[:3000]}], max_tokens=200)
    if not res["ok"]:
        return {"ok": False, "error": res["error"]}
    import json
    txt = res["text"]
    try:
        start = txt.find("{")
        data = json.loads(txt[start:txt.rfind("}") + 1])
        cat = str(data.get("category", "unclear")).lower()
        if cat not in ("negative", "interested", "question", "unclear"):
            cat = "unclear"
        return {"ok": True, "category": cat, "reasoning": str(data.get("reasoning", ""))}
    except Exception:  # noqa: BLE001
        return {"ok": True, "category": "unclear", "reasoning": txt[:200]}


async def _suggest_reply(lead: dict, reply_body: str) -> str:
    prompt = (
        f"Lead {lead.get('business_name')} ({lead.get('niche')}) replied to your cold email:\n\n"
        f"\"{reply_body[:1500]}\"\n\nWrite a short, friendly, helpful reply. Body only, no subject."
    )
    res = await agent_task("agent3", prompt, max_tokens=400, purpose="reply")
    return res["text"] if res["ok"] else ""


async def run_reply_check() -> dict:
    """One reply-check cycle. Never raises. Called on an interval + on demand."""
    try:
        _set_status("working", "Checking inbox for replies")
        result = await asyncio.to_thread(fetch_replies, 14)
        if not result["ok"]:
            if result.get("kind") == "no_creds":
                _set_status("idle", "")  # not configured yet — not an error state
                return {"ok": False, "error": result["error"]}
            _set_status("error", f"Could not check inbox: {result['error']}")
            return {"ok": False, "error": result["error"]}

        cfg = get_db()["config"]
        seen_doc = cfg.find_one({"_id": "imap_seen"}) or {}
        seen = set(seen_doc.get("message_ids", []))
        processed = 0

        for r in result["replies"]:
            mid = r.get("message_id") or f"{r['from_email']}:{r['received_at']}"
            if mid in seen:
                continue
            lead = _leads().find_one({"email": r["from_email"], "status": {"$in": ["mailed", "replied", "interested_awaiting_review"]}})
            seen.add(mid)
            if lead is None:
                continue  # not a reply to one of our leads
            # Store the raw reply on the lead.
            _leads().update_one({"id": lead["id"]}, {"$push": {"outreach_history": {"type": "reply", "body": r["body"], "received_at": r["received_at"]}}})
            # Classify.
            cls = await _classify(r["body"])
            if not cls["ok"]:
                _leads().update_one({"id": lead["id"]}, {"$set": {"status": "replied", "reply_reasoning": "classification unavailable", "last_action": "Reply received (unclassified)", "last_action_timestamp": _now()}})
                processed += 1
                continue
            if cls["category"] == "negative":
                _leads().update_one({"id": lead["id"]}, {"$set": {
                    "status": "not_interested", "reply_classification": "negative", "reply_reasoning": cls["reasoning"],
                    "last_action": "Auto-closed: reply classified negative", "last_action_timestamp": _now()}})
            else:
                suggestion = await _suggest_reply(lead, r["body"])
                _leads().update_one({"id": lead["id"]}, {"$set": {
                    "status": "interested_awaiting_review", "reply_classification": cls["category"], "reply_reasoning": cls["reasoning"],
                    "suggested_reply": suggestion, "last_action": f"Reply ({cls['category']}) — awaiting your review", "last_action_timestamp": _now()}})
            processed += 1

        cfg.update_one({"_id": "imap_seen"}, {"$set": {"message_ids": list(seen)[-500:], "last_checked": _now()}}, upsert=True)
        _set_status("idle", "")
        return {"ok": True, "processed": processed}
    except Exception as exc:  # noqa: BLE001
        _set_status("error", f"Reply check error: {exc}")
        return {"ok": False, "error": str(exc)}


@router.post("/check-replies")
@safe_endpoint("agent3")
async def check_replies():
    return await run_reply_check()


@router.get("/replies/pending")
@safe_endpoint("agent3")
async def pending_replies():
    out = []
    for lead in _leads().find({"status": "interested_awaiting_review"}):
        hist = lead.get("outreach_history", [])
        last_reply = next((h for h in reversed(hist) if h.get("type") == "reply"), None)
        out.append({
            "id": lead["id"], "business_name": lead.get("business_name", ""), "niche": lead.get("niche", ""),
            "email": lead.get("email", ""),
            "reply": last_reply.get("body", "") if last_reply else "",
            "classification": lead.get("reply_classification", ""),
            "reasoning": lead.get("reply_reasoning", ""),
            "suggested_reply": lead.get("suggested_reply", ""),
        })
    return {"ok": True, "pending": out}


class ReplyAction(BaseModel):
    mode: str  # as_is | edit | manual
    body: str | None = None


@router.post("/leads/{lead_id}/reply")
@safe_endpoint("agent3")
async def send_reply(lead_id: str, action: ReplyAction):
    lead = _leads().find_one({"id": lead_id})
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    # HARD RULE: a real send only happens on this explicit CEO action.
    body = action.body if action.mode in ("edit", "manual") else lead.get("suggested_reply", "")
    if not body:
        raise HTTPException(status_code=400, detail="No reply body to send")
    subject = f"Re: your reply — {lead.get('business_name','')}"
    result = await asyncio.to_thread(send_email, lead.get("email", ""), subject, body)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}
    _leads().update_one({"id": lead_id}, {
        "$set": {"status": "replied", "suggested_reply": "", "last_action": f"CEO replied ({action.mode})", "last_action_timestamp": _now()},
        "$push": {"outreach_history": {"type": "reply_sent", "mode": action.mode, "body": body, "sent_at": _now()}},
    })
    return {"ok": True}


CHAT_SYSTEM = (
    "You are the Outreach Specialist at a small digital agency. You discuss your cold-email outreach and "
    "replies, grounded ONLY in the real data provided. Questions outside your scope (niches, verification, "
    "system health) should be politely deferred to the relevant specialist or the Supervisor. Be concise."
)


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


def _chat_context() -> str:
    leads = list(_leads().find({}))
    def c(s): return sum(1 for l in leads if l.get("status") == s)
    return (
        f"REAL DATA — emails awaiting reply (mailed): {c('mailed')}; replies received: "
        f"{c('replied') + c('interested_awaiting_review') + c('not_interested')}; interested awaiting your "
        f"review: {c('interested_awaiting_review')}; not interested: {c('not_interested')}; sent today: {_sent_today()}."
    )


@router.post("/chat")
@safe_endpoint("agent3")
async def chat(body: ChatBody):
    res = await agent_chat("agent3", body.message, body.history, extra_context=f"(Context, use only these facts: {_chat_context()})", max_tokens=450)
    if res["ok"]:
        return {"ok": True, "reply": res["text"]}
    return {"ok": False, "error": res["error"], "error_kind": res.get("error_kind")}


# ---- cold-call STUB (no real dialing) --------------------------------------
class ScheduleCall(BaseModel):
    call_scheduled: str


@router.post("/leads/{lead_id}/schedule-call")
@safe_endpoint("agent3")
async def schedule_call(lead_id: str, body: ScheduleCall):
    if _leads().find_one({"id": lead_id}) is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    # STUB ONLY: records a date. No dialing integration is built in this phase.
    _leads().update_one({"id": lead_id}, {"$set": {"call_scheduled": body.call_scheduled, "last_action": "Call scheduled (stub)", "last_action_timestamp": _now()}})
    return {"ok": True, "call_scheduled": body.call_scheduled}
