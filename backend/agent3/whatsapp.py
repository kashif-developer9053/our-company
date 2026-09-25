"""WhatsApp outreach — click-to-send, never automated.

Pakistani SMEs overwhelmingly use WhatsApp rather than email, so this is a real
channel here. But automated sending (unofficial libraries, or the official API
without per-contact opt-in) is what gets numbers permanently banned.

So this module only PREPARES: it validates the number, writes a short message
from the lead's own site audit, and builds a wa.me link. The CEO reviews and
presses send in WhatsApp themselves — a human typing in a normal chat, which is
exactly what it is. Nothing here ever contacts WhatsApp's servers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from shared.logger import get_logger

from .languages import label_for as _lang_label
from .languages import languages_for as _languages_for

log = get_logger("agent3.whatsapp")

# Status values for the WhatsApp pipeline, kept separate from email statuses.
WA_STATUSES = ("not_contacted", "message_sent", "replied", "interested", "not_interested", "invalid_number")

# Country dial codes we can normalise confidently. Pakistan first — it is the
# primary market for this channel.
_DEFAULT_DIAL = "92"
_LOCAL_PREFIX_TRIM = ("0",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalise_number(raw: str, default_dial: str = _DEFAULT_DIAL) -> str:
    """Return a wa.me-ready number (digits only, country code, no +) or "".

    wa.me rejects spaces, dashes and a leading +, and a local "03xx" number must
    become "923xx". Anything that cannot be made into a plausible mobile number
    returns "" so the UI can mark it unusable rather than opening a broken chat.
    """
    digits = re.sub(r"[^\d+]", "", str(raw or ""))
    if not digits:
        return ""
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith(_LOCAL_PREFIX_TRIM):
        # Local format (0300…) -> prepend the country dial code.
        digits = default_dial + digits.lstrip("0")
    elif not digits.startswith(default_dial):
        # Bare local number with no leading zero.
        if len(digits) <= 10:
            digits = default_dial + digits
    # Plausible international mobile length.
    if not (10 <= len(digits) <= 15):
        return ""
    return digits


# Landline prefixes by country code. A landline can never have WhatsApp, so a
# lead whose ONLY contact is one is unreachable on this channel.
#
# Previously only Pakistan was checked and everything else returned True, so
# Saudi landlines like +966 13 361 6665 were being queued as WhatsApp leads —
# 13 is the Eastern Province area code and will never answer on WhatsApp.
_LANDLINE_PREFIXES: dict[str, tuple[str, ...]] = {
    "92":  ("21", "22", "41", "42", "44", "48", "51", "53", "55", "61", "62",
            "64", "68", "71", "74", "81", "86", "91", "92", "99"),   # PK cities
    "966": ("11", "12", "13", "14", "16", "17"),                     # SA regions
    "971": ("2", "3", "4", "6", "7", "9"),                           # UAE emirates
    "44":  ("1", "2"),                                               # UK geographic
    "353": ("1", "21", "22", "23", "24", "25", "26", "27", "28", "29",
            "4", "5", "6", "9"),                                     # IE geographic
    "1":   (),                                                       # NANP: not separable
    "91":  ("11", "22", "33", "44", "20", "40", "79", "80"),         # IN metros
}

# Mobile prefixes, checked first — a positive match is stronger evidence than
# the absence of a landline prefix.
_MOBILE_PREFIXES: dict[str, tuple[str, ...]] = {
    "92":  ("3",),          # 92 3xx xxxxxxx
    "966": ("5",),          # 966 5x xxx xxxx
    "971": ("5",),
    "44":  ("7",),
    "353": ("8",),
    "91":  ("6", "7", "8", "9"),
}


def looks_mobile(number: str, dial: str = _DEFAULT_DIAL) -> bool:
    """Is this plausibly a mobile, and therefore WhatsApp-capable?

    A heuristic, not proof: only Meta can say whether a number has a WhatsApp
    account. This rules out numbers that certainly CANNOT — landlines — which
    is most of the waste. Unknown country codes are accepted rather than
    dropped, since a false negative loses a real lead.
    """
    if not number:
        return False
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) < 8:
        return False

    # Longest country code first: 966 must beat 9, 353 must beat 3.
    for cc in sorted(_LANDLINE_PREFIXES, key=len, reverse=True):
        if not digits.startswith(cc):
            continue
        rest = digits[len(cc):]
        if not rest:
            return False
        mobiles = _MOBILE_PREFIXES.get(cc, ())
        if mobiles and rest.startswith(mobiles):
            return True
        if rest.startswith(_LANDLINE_PREFIXES[cc]):
            return False
        # A country we know but a prefix we do not recognise: if we know its
        # mobile range and this is not in it, treat it as a landline.
        return not mobiles

    return True    # unknown country code — keep it rather than lose a lead


def wa_link(number: str, message: str) -> str:
    """Build the click-to-send link. Opens WhatsApp with the text pre-typed —
    the CEO still has to press send.

    Stays on web.whatsapp.com deliberately. api.whatsapp.com is a landing page
    that redirects here, so pointing an already-open WhatsApp Web tab at it
    navigated away from the live session and reloaded — the reuse only works
    when the URL shares the tab's own origin. app_absent=0 keeps it from
    prompting to open the desktop app.
    """
    if not number:
        return ""
    return (f"https://web.whatsapp.com/send?phone={number}"
            f"&text={quote(message or '', safe='')}"
            f"&type=phone_number&app_absent=0")


def wa_state(lead: dict) -> dict:
    """Our outreach state for this lead.

    NOTE: `whatsapp` may already hold a LIST — the website miner stores any
    wa.me links it scraped there. Only a dict is our state; anything else is
    treated as "no state yet" so both can coexist.
    """
    wa = lead.get("whatsapp")
    return wa if isinstance(wa, dict) else {}


def status_of(lead: dict) -> str:
    return wa_state(lead).get("status") or "not_contacted"


def serialize(lead: dict) -> dict:
    """The WhatsApp view of a lead, for the CRM's WhatsApp tab."""
    raw = lead.get("phone") or ""
    number = normalise_number(raw)
    wa = wa_state(lead)
    audit = lead.get("site_audit")
    return {
        "id": lead.get("id"),
        "business_name": lead.get("business_name", ""),
        "niche": lead.get("niche", ""),
        "city": lead.get("city", ""),
        "phone_raw": raw,
        "number": number,
        "usable": bool(number) and looks_mobile(number),
        "status": wa.get("status") or "not_contacted",
        "remarks": wa.get("remarks", ""),
        "message": wa.get("message", ""),
        "sent_at": wa.get("sent_at", ""),
        "updated_at": wa.get("updated_at", ""),
        "collection_reason": lead.get("collection_reason", ""),
        "opportunity_score": lead.get("opportunity_score", 0),
        "site_audit": audit if isinstance(audit, dict) else {},
        # The single headline problem, so the list can be filtered and scanned
        # without loading every lead's full audit.
        "issue": _headline_issue(lead),
        # yes / no / unknown / "" when never checked. "no" for a landline is
        # decided locally and costs nothing.
        "has_whatsapp": (lead.get("wa_verified") or {}).get("verdict", ""),
        # Languages worth offering for this lead's country/city, best first.
        "languages": [{"code": c, "label": _lang_label(c)}
                      for c in _languages_for(lead.get("country", ""), lead.get("city", ""))],
        # Where this number came from. A person we contacted asked how we got
        # his details and we could not answer from the UI — anyone messaging a
        # stranger should be able to say where the number came from before
        # they press send.
        "source": _source_label(lead),
        "source_url": (lead.get("social_url") or lead.get("website") or ""),
        "collected_at": str(lead.get("created_at") or "")[:10],
        "created_at": lead.get("created_at", ""),
    }


# Problems worth filtering by, strongest first: the first one a lead has is the
# one worth leading a message with.
_ISSUE_ORDER = (
    ("no_website", "No website"),
    ("site_unreachable", "Site doesn't load"),
    ("http_error", "Site shows an error"),
    ("no_reviews", "No Google reviews"),
    ("poor_rating", "Low rating"),
    ("very_slow", "Very slow site"),
    ("slow", "Slow site"),
    ("not_mobile_friendly", "Not mobile friendly"),
    ("no_https", "Not secure"),
    ("no_contact_route", "No way to contact"),
    ("no_contact_form", "No enquiry form"),
    ("outdated_cms", "Outdated software"),
)


# Raw source values, mapped to something a person can read aloud. If someone
# asks "where did you get my number", the answer has to be in front of you.
_SOURCE_LABELS = {
    "agent1_harvest": "Google Maps listing",
    "agent1_google_maps": "Google Maps listing",
    "agent1_scrape": "Google Maps listing",
    "agent1_custom_web_crawler": "their website",
    "agent1_social_miner": "public Facebook/Instagram page",
    "agent1_multi_source": "Google Maps + web search",
    "manual": "added by hand",
}


def _source_label(lead: dict) -> str:
    """Where this lead's details came from, in plain words."""
    disc = (lead.get("discovery_source") or "").strip().lower()
    if "facebook" in disc:
        return "public Facebook page"
    if "instagram" in disc:
        return "public Instagram page"
    if "duckduckgo" in disc or "yahoo" in disc:
        return "web search result"
    if "google_maps" in disc:
        return "Google Maps listing"
    return _SOURCE_LABELS.get((lead.get("source") or "").strip().lower(), "")


def _headline_issue(lead: dict) -> str:
    """The strongest problem this lead has, as a short label."""
    audit = lead.get("site_audit")
    if not isinstance(audit, dict):
        # site_audit is projected away on the list endpoint for speed, so fall
        # back to the flag the scraper sets when there was no site at all.
        return "No website" if lead.get("appears_no_website") else ""
    codes = {f.get("code") for f in (audit.get("findings") or [])}
    if not codes and lead.get("appears_no_website"):
        return "No website"
    for code, label in _ISSUE_ORDER:
        if code in codes:
            return label
    return ""
