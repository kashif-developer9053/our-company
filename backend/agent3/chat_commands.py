"""Turn a plain-English chat message into an outreach action.

The chat could only ever talk about the work; anything that actually wrote
emails had to be driven from the Outreach screen. This closes that gap for the
one thing worth automating from chat:

    "pick a niche name schools and write 20 22 emails and including the faults
     related also write them we can make lms, school management, attendance
     management system etc for you"

Parsing is deliberately deterministic rather than another model call. The
instruction is short and formulaic, a regex answers it in microseconds with no
token cost, and — more importantly — a model asked to "decide whether to send
emails" is a model that can be talked into sending emails. Here the worst case
is that a command is not recognised, and the chat simply replies as before.

Nothing is ever sent. This produces DRAFTS, which land in the same approval
queue as everything else.
"""

from __future__ import annotations

import re

from shared.logger import get_logger

log = get_logger("agent3.chat_commands")

# Only fire on an explicit instruction to write/draft/prepare email. Merely
# mentioning emails ("how many emails went out?") must never trigger a batch.
_WRITE_VERB = re.compile(
    r"\b(?:write|draft|prepare|compose|create|generate|make)\b[^.?!]{0,40}?"
    r"\b(?:e?-?mails?|messages?|outreach)\b",
    re.I,
)
# ...or the reversed phrasing: "20 emails for schools, write them".
_WRITE_VERB_ALT = re.compile(
    r"\b(?:e?-?mails?|outreach)\b[^.?!]{0,30}?\b(?:write|draft|prepare|compose)\b",
    re.I,
)

# "20", "20 22", "20-22", "20 to 22" -> take the LOWER bound. Over-drafting
# costs model calls and clutters the review queue; under-drafting does not.
_COUNT = re.compile(
    r"\b(\d{1,3})\s*(?:[-–]|to|or|,)?\s*(\d{1,3})?\s*(?=e?-?mails?\b|messages?\b)|"
    r"\b(?:write|draft|prepare|compose|create|generate|make)\s+(\d{1,3})\s*(?:[-–]|to|or)?\s*(\d{1,3})?\b",
    re.I,
)

# Ordered most-explicit first: an explicit "niche X" beats an incidental
# "emails for X", so the CEO can always be unambiguous when they want to be.
_NICHE_PATTERNS = (
    # "niche name schools", "niche is textile mills", "niche: gyms"
    re.compile(r"\bniche\s+(?:name[d]?|called|is|=|:)?\s*([a-z0-9&'\- ]{3,40}?)"
               r"(?=\s+(?:and|then|write|draft|prepare|compose|in|near)\b|\s*[,.]|$)", re.I),
    # "pick a schools niche", "use the textile mills niche"
    re.compile(r"\b(?:pick|choose|select|use|target)\s+(?:a\s+|the\s+)?(?:niche\s+)?"
               r"(?:name[d]?\s+|called\s+)?([a-z0-9&'\- ]{3,40}?)\s+niche\b", re.I),
    # "schools niche"
    re.compile(r"\b([a-z0-9&'\- ]{3,40}?)\s+niche\b", re.I),
    # "emails for dental clinics", "emails to gyms". Anchored on the noun
    # rather than a bare "for", which also appears in "for you"/"for them".
    re.compile(r"\b(?:e?-?mails?|messages?|outreach|leads?)\s+(?:for|to)\s+(?:the\s+)?"
               r"([a-z0-9&'\- ]{3,40}?)"
               r"(?=\s+(?:and|then|also|we|in|near|because)\b|\s*[,.]|$)", re.I),
)

_CITY = re.compile(r"\b(?:in|from|based in|located in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")

# Words that are never the niche, even when the grammar suggests they are.
_NOT_A_NICHE = {
    "a", "an", "the", "them", "email", "emails", "mail", "mails", "lead", "leads",
    "some", "more", "new", "all", "any", "that", "this", "it", "me", "us", "you",
    "one", "two", "each", "every", "which", "what", "our", "their", "write",
}


def _clean_niche(raw: str) -> str:
    n = re.sub(r"\s+", " ", (raw or "")).strip(" ,.;:'\"-").lower()
    # Trim a trailing instruction that the match swept up.
    n = re.split(r"\b(?:and|then|also|write|draft|please|including|we)\b", n)[0].strip()
    n = n.strip(" ,.;:'\"-")
    if not n or n in _NOT_A_NICHE or len(n) < 3:
        return ""
    if all(w in _NOT_A_NICHE for w in n.split()):
        return ""
    return n


def parse(message: str) -> dict | None:
    """Return {count, niche, city, extra_services} for a write-emails command.

    None means "not a command" — the caller should fall through to normal chat.
    """
    msg = (message or "").strip()
    if not msg or len(msg) > 2000:
        return None
    if not (_WRITE_VERB.search(msg) or _WRITE_VERB_ALT.search(msg)):
        return None

    count = 10
    m = _COUNT.search(msg)
    if m:
        nums = [int(g) for g in m.groups() if g and g.isdigit()]
        if nums:
            count = max(1, min(min(nums), 50))

    niche = ""
    for pattern in _NICHE_PATTERNS:
        hit = pattern.search(msg)
        if hit:
            niche = _clean_niche(hit.group(1))
            if niche:
                break

    city = ""
    hit = _CITY.search(msg)
    if hit:
        city = hit.group(1).strip()

    return {
        "count": count,
        "niche": niche,
        "city": city,
        # Anything the CEO wants pitched beyond the website itself, e.g.
        # "we can make lms, school management, attendance management system".
        "extra_services": _extra_services(msg),
    }


_SERVICE_LEAD_IN = re.compile(
    r"\b(?:we can (?:also )?(?:make|build|provide|offer|develop)|also (?:mention|include|tell|write)|"
    r"tell them we (?:can|do)|offer(?:ing)?)\b(.{4,220})",
    re.I | re.S,
)


def _extra_services(message: str) -> str:
    """The services the CEO named in the instruction, as free text.

    Passed to the writer verbatim rather than parsed into a list: the whole
    point is that they said it in their own words, and a school hears
    "attendance system" more clearly than any canonical service name we hold.
    """
    hit = _SERVICE_LEAD_IN.search(message or "")
    if not hit:
        return ""
    text = hit.group(1)
    # Stop at the end of that clause.
    text = re.split(r"[.?!\n]", text)[0]
    text = re.sub(r"\b(?:for you|for them|etc\.?|blah blah)\b", "", text, flags=re.I)
    # "also write them we can make lms" leaves a dangling pronoun on the front.
    text = re.sub(r"^\s*(?:them|it|us|that|this)\b\s*", "", text, flags=re.I)
    text = re.sub(r"^\s*we can (?:also )?(?:make|build|provide|offer|develop)\b\s*", "",
                  text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return text[:200]
