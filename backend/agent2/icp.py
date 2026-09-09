"""ICP (Ideal Customer Profile) qualification — deterministic, no AI calls.

Agent 2 verified that a lead is *contactable*. This module decides whether the
lead is *worth contacting*, which is a different question and the one that was
missing. It exists because the outreach data showed two expensive mistakes:

  1. ~10% of everyone we emailed was a software/ERP/web agency — our own
     competitors. We pitched "your website has problems, we can build you one"
     to Odoo implementation partners.
  2. Leads were spread across 8 cities on 3 continents with no focus, so no
     segment ever got enough volume to learn from.

Both are cheap to prevent here and expensive to undo later (a burned domain
reputation and a burned prospect don't come back).
"""

from __future__ import annotations

import re

from shared.logger import get_logger

log = get_logger("agent2.icp")

# --- Hard exclusions -------------------------------------------------------
# Businesses that sell what we sell. Emailing them is worse than a wasted send:
# it makes us look like we never looked at their website. Matched against the
# business name AND the niche/category, because either can give it away.
COMPETITOR_PATTERNS = [
    r"\berp\b", r"\bcrm\b", r"\bodoo\b", r"\bsap\b", r"\bnetsuite\b",
    r"\bsoftware\b", r"\bweb\s*(design|development|solutions?)\b",
    r"\bapp\s*(development|developers?)\b", r"\bdigital\s*(agency|marketing)\b",
    r"\bit\s*(solutions?|services?|company|consult)", r"\binfotech\b",
    r"\btechnolog(y|ies)\b", r"\bsystems?\s*(ltd|inc|pvt)", r"\bsolutions?\s*(pvt|ltd|inc)\b",
    r"\bdevelopers?\b", r"\bwebsite\b", r"\bhosting\b", r"\bseo\b",
    r"\bsofthouse\b", r"\bsoft\s*house\b", r"\bcoding\b", r"\bprogramm(er|ing)\b",
]
_COMPETITOR_RE = re.compile("|".join(COMPETITOR_PATTERNS), re.I)

# Outfits nobody can sell a website to, or that are legally/practically off-limits.
BLOCKED_PATTERNS = [
    r"\bgovernment\b", r"\bministry\b", r"\bmunicipal", r"\bembassy\b",
    r"\bwikipedia\b", r"\bfacebook\b", r"\bgoogle\b", r"\blinkedin\b",
    r"\byelp\b", r"\byellow\s*pages\b", r"\bjustdial\b", r"\bindiamart\b",
    r"\bscribd\b", r"\bcourse\s*hero\b",   # directories/scrapers that leaked in before
    r"\btest\s*compan", r"^test\b", r"\bexample\b", r"\blorem\b",
]
_BLOCKED_RE = re.compile("|".join(BLOCKED_PATTERNS), re.I)

# Placeholder/lorem junk that means the scrape produced garbage.
_JUNK_RE = re.compile(r"excepteur|lorem ipsum|dolor sit|consectetur", re.I)

# Known software/SaaS/data vendors. Their names carry no industry word, so the
# patterns above cannot catch them: "Skrapp.io" and "Quicken Help" read like any
# other business until you look at the domain. These are global products, never
# a local prospect, and several are outright competitors in lead generation.
_VENDOR_DOMAINS = {
    "skrapp.io", "prospeo.io", "hunter.io", "snov.io", "apollo.io", "lusha.com",
    "rocketreach.co", "zoominfo.com", "crunchbase.com", "datanyze.com",
    "signalhire.com", "contactout.com", "leadiq.com", "clearbit.com",
    "quicken.com", "intuit.com", "salesforce.com", "hubspot.com", "zoho.com",
    "freshworks.com", "pipedrive.com", "monday.com", "notion.so", "slack.com",
    "atlassian.com", "zendesk.com", "shopify.com", "wix.com", "squarespace.com",
    "godaddy.com", "wordpress.com", "cloudflare.com", "stackexchange.com",
    "stackoverflow.com", "dynamics.com", "microsoft.com", "oracle.com", "sap.com",
}


def _domain_of(lead: dict) -> str:
    site = str(lead.get("website") or "").strip().lower()
    if not site:
        return ""
    host = site.split("//")[-1].split("/")[0]
    return host[4:] if host.startswith("www.") else host


def classify(lead: dict) -> tuple[str, str]:
    """Return (verdict, reason). verdict is one of keep|competitor|blocked|junk."""
    name = str(lead.get("business_name") or "")
    niche = str(lead.get("niche") or lead.get("category") or lead.get("notes") or "")
    haystack = f"{name} {niche}"

    if _JUNK_RE.search(haystack):
        return "junk", "placeholder/lorem text in the record"

    m = _BLOCKED_RE.search(haystack)
    if m:
        return "blocked", f"not a sellable business ({m.group(0).strip()})"

    # Only the NAME implicates a competitor. A niche of "ERP for manufacturers"
    # is a search term describing who we want to reach, not the lead itself —
    # matching on it rejected exactly the manufacturers we were looking for.
    # Domain is the reliable signal for product companies: the name gives
    # nothing away, but nobody sells a local website rebuild to skrapp.io.
    domain = _domain_of(lead)
    if domain:
        for vendor in _VENDOR_DOMAINS:
            if domain == vendor or domain.endswith(f".{vendor}"):
                return "blocked", f"a software/SaaS vendor ({vendor}), not a local prospect"

    m = _COMPETITOR_RE.search(name)
    if m:
        return "competitor", f"appears to sell IT/web services ({m.group(0).strip()})"

    return "keep", ""


# --- Fit scoring -----------------------------------------------------------
# 0-100. Not a rejection: it ranks the queue so the best leads get worked first
# and the CEO review screen stops being first-in-first-out.

def score(lead: dict, icp: dict | None = None) -> tuple[int, list[str]]:
    """Return (score, reasons). Higher = better prospect."""
    icp = icp or {}
    # Starts low on purpose: the pitch strength below is what should
    # separate leads, and a high base clips everything at 100.
    pts = 20
    why: list[str] = []

    # Reachability. An unreachable lead is worth nothing regardless of fit.
    if (lead.get("email") or "").strip():
        if lead.get("email_confidence") == "found":
            pts += 15; why.append("verified email on file")
        else:
            pts += 6; why.append("email guessed from domain")
    else:
        pts -= 20; why.append("no email address")

    if (lead.get("phone") or "").strip():
        pts += 8; why.append("phone available")

    # Intent: how strong is the pitch, really? Not every finding is equal.
    # "No WhatsApp button" is our single most common finding (90 leads) and is
    # barely a problem; "no website at all" is the strongest pitch we can have.
    # Counting findings therefore ranks the queue almost backwards — weight by
    # what the problem actually costs the business instead.
    audit = lead.get("site_audit") or {}
    findings = audit.get("findings") or []
    codes = {f.get("code", "") for f in findings}

    if not lead.get("website"):
        pts += 25; why.append("no website at all — strongest possible pitch")
    elif codes & {"site_unreachable", "http_error"}:
        pts += 22; why.append("their website is down or erroring")
    elif not lead.get("has_working_website"):
        pts += 18; why.append("website does not load")
    else:
        # Tiered by business impact, highest tier wins.
        HOT = {"no_contact_route", "no_contact_form", "very_slow", "not_mobile_friendly", "no_https"}
        WARM = {"slow", "no_title", "no_h1", "no_meta_description", "outdated_cms",
                "legacy_html", "flash_content", "table_layout"}
        COLD = {"no_whatsapp", "no_analytics", "no_open_graph", "no_structured_data",
                "images_missing_alt", "weak_title"}
        if codes & HOT:
            pts += 16; why.append("losing enquiries directly — urgent, easy to sell")
        elif codes & WARM:
            pts += 9; why.append("visibly dated or hard to find in search")
        elif codes & COLD:
            pts += 2; why.append("only minor polish issues — weak pitch")
        else:
            pts -= 12; why.append("website looks healthy — nothing to sell")

    # Focus: reward the niches and cities we have decided to win.
    target_niches = [x.lower() for x in (icp.get("target_niches") or [])]
    target_cities = [x.lower() for x in (icp.get("target_cities") or [])]
    niche = str(lead.get("niche") or lead.get("category") or "").lower()
    city = str(lead.get("city") or "").strip().lower()

    if target_niches and any(t in niche for t in target_niches):
        pts += 10; why.append("in a target niche")
    elif target_niches:
        pts -= 8; why.append("outside our target niches")

    if target_cities and any(t == city or t in city for t in target_cities):
        pts += 10; why.append("in a target city")
    elif target_cities:
        pts -= 8; why.append("outside our target cities")

    return max(0, min(100, pts)), why


def qualify(lead: dict, icp: dict | None = None) -> dict:
    """One call for Agent 2: verdict + score + human-readable reasons."""
    verdict, reason = classify(lead)
    fit, why = score(lead, icp)
    return {"verdict": verdict, "reject_reason": reason, "fit_score": fit, "fit_reasons": why}
