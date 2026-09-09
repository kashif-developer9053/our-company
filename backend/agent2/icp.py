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
    pts = 50
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

    # Opportunity: a broken/absent site is the whole pitch.
    audit = lead.get("site_audit") or {}
    findings = audit.get("findings") or []
    serious = sum(1 for f in findings if f.get("severity") in ("critical", "high"))
    if not lead.get("website"):
        pts += 20; why.append("no website at all — strongest pitch")
    elif not lead.get("has_working_website"):
        pts += 15; why.append("website does not load")
    elif serious >= 3:
        pts += 14; why.append(f"{serious} serious website problems")
    elif serious >= 1:
        pts += 8; why.append(f"{serious} website problem(s)")
    elif findings:
        pts += 3; why.append("minor website problems")
    else:
        pts -= 10; why.append("website looks healthy — weak pitch")

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
