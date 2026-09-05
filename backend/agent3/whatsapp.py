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


def looks_mobile(number: str, dial: str = _DEFAULT_DIAL) -> bool:
    """Heuristic: is this a mobile (WhatsApp-capable) rather than a landline?

    We cannot truly verify a number is on WhatsApp without contacting Meta, which
    is exactly what we avoid. For Pakistan, mobiles are 92 3xx xxxxxxx — landlines
    start 92 21/42/51 etc. Outside PK we accept anything plausible.
    """
    if not number:
        return False
    if number.startswith(dial):
        rest = number[len(dial):]
        return rest.startswith("3") and len(rest) == 10
    return True


def wa_link(number: str, message: str) -> str:
    """Build the click-to-send link. Opens WhatsApp with the text pre-typed —
    the CEO still has to press send."""
    if not number:
        return ""
    return f"https://wa.me/{number}?text={quote(message or '', safe='')}"


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
    }
