"""Company profile (single document) — real business identity used to ground
Agent 3's outreach and Agent 1's niche reasoning."""

from __future__ import annotations

from .database import get_db

_ID = "singleton"
DEFAULT = {
    "company_name": "", "website": "", "tagline": "",
    "services_offered": [], "tone_preference": "friendly and professional",
    "contact_links": [], "outreach_template": "",
    # Real contact details Agent 3 must sign every cold email with.
    "contact_email": "", "whatsapp": "", "phone": "", "logo_url": "", "sender_photo_url": "", "address": "",
    "sender_name": "", "sender_title": "",
}


def _col():
    return get_db()["company_profile"]


def get_profile() -> dict:
    doc = _col().find_one({"_id": _ID})
    if doc is None:
        return dict(DEFAULT)
    doc.pop("_id", None)
    return {**DEFAULT, **doc}


def set_profile(data: dict) -> dict:
    clean = {k: data.get(k, DEFAULT[k]) for k in DEFAULT}
    _col().update_one({"_id": _ID}, {"$set": clean}, upsert=True)
    return get_profile()


def profile_as_context() -> str:
    """A compact text block for injecting into agent prompts. Empty if unset."""
    p = get_profile()
    if not p.get("company_name") and not p.get("services_offered"):
        return ""
    links = "; ".join(f"{l.get('label')}: {l.get('url')}" for l in p.get("contact_links", []) if l.get("url"))
    contact = "; ".join(x for x in (
        f"email {p['contact_email']}" if p.get("contact_email") else "",
        f"WhatsApp {p['whatsapp']}" if p.get("whatsapp") else "",
        f"phone {p['phone']}" if p.get("phone") else "",
    ) if x)
    signer = " ".join(x for x in (p.get("sender_name", ""), f"({p['sender_title']})" if p.get("sender_title") else "") if x)
    parts = [
        f"Company: {p['company_name']}" + (f" ({p['website']})" if p.get("website") else ""),
        f"Tagline: {p['tagline']}" if p.get("tagline") else "",
        f"Services: {', '.join(p['services_offered'])}" if p.get("services_offered") else "",
        f"Preferred tone: {p['tone_preference']}" if p.get("tone_preference") else "",
        f"Real contact details (use these verbatim, never invent others): {contact}" if contact else "",
        f"Sign emails as: {signer}" if signer else "",
        f"Links to include: {links}" if links else "",
        f"Outreach template/structure to follow:\n{p['outreach_template']}" if p.get("outreach_template") else "",
    ]
    return "\n".join(x for x in parts if x)


def outreach_identity() -> dict:
    """Just the facts Agent 3 needs to sign an email (no prompt formatting)."""
    p = get_profile()
    return {
        "company_name": p.get("company_name", ""), "website": p.get("website", ""),
        "contact_email": p.get("contact_email", ""), "whatsapp": p.get("whatsapp", ""),
        "phone": p.get("phone", ""), "sender_name": p.get("sender_name", ""),
        "sender_title": p.get("sender_title", ""),
        "links": [l for l in p.get("contact_links", []) if l.get("url")],
        "services": p.get("services_offered", []),
        "tone": p.get("tone_preference", ""),
        "template": p.get("outreach_template", ""),
    }
