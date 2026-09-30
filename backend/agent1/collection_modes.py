"""The three ways to run a lead hunt.

Until now a hunt needed the CEO to supply a niche, which meant every hunt was
limited by whether they had thought of the right business type that morning.
That is real work to do daily, and the niche they pick is a guess at where the
demand is.

The three modes:

  NICHE    — the original. "Find me dentists in Islamabad who need a website."
             Exact control, and still the right tool when you know the target.

  PURPOSE  — "Find me anyone in Lahore who needs a CRM." We already know which
             business types inherently run on enquiries, stock or bookings, so
             the hunt walks that list itself, several niches per run, stopping
             when the target is met. The CEO picks WHAT WE SELL, not who to
             search for.

  AREA     — "Find me small businesses in Gujranwala." No niche and no service:
             sweep the common trades of a place and let the diagnosis decide
             what each one needs. This is how you work a town you have never
             sold into, and it is the only mode that finds a business whose
             trade nobody thought to search for.

AREA needs a size filter the other two do not. A niche search returns what you
asked for; an area sweep returns everything, including the chains. A business
with one branch and forty reviews is the target — big enough to have the
problem, small enough that the owner reads his own WhatsApp.
"""

from __future__ import annotations

import re
from collections import Counter

from shared.logger import get_logger

from .service_targets import SERVICES, niches_for

log = get_logger("agent1.modes")

MODES = ("niche", "purpose", "area")


# A sweep returns whatever is on the road, so it needs the size window the
# niche modes get from the service definition. Below the floor there is nothing
# to systematise; above the ceiling they have a manager for this.
AREA_MIN_REVIEWS = 3
AREA_MAX_REVIEWS = 300

# A chain announces itself by repeating: the same name in several places, or a
# branch marker in the name. One branch is a prospect; eleven is a head office
# with a procurement process.
_BRANCH_MARKER = re.compile(
    r"\b(?:branch|outlet|franchise|chapter no|store no|shop no)\b"
    r"|\b(?:br|blk)[\s.-]*\d+\b",
    re.I)
_CHAIN_THRESHOLD = 3


# Suburb and area words that trail a branch name. Stripped before comparing,
# so "Gourmet Bakers Model Town" and "Gourmet Bakers Gulberg" are seen as one
# chain, while "Al Noor Tailors" keeps the trade word that makes it distinct.
_AREA_WORDS = {
    "town", "city", "road", "rd", "chowk", "colony", "block", "phase",
    "scheme", "market", "bazar", "bazaar", "plaza", "mall", "centre", "center",
    "gulberg", "dha", "cantt", "cantonment", "saddar", "model", "johar",
    "north", "south", "east", "west", "main", "new", "old", "branch",
    "lahore", "karachi", "islamabad", "rawalpindi", "faisalabad", "multan",
    "peshawar", "quetta", "sialkot", "gujranwala", "hyderabad", "sargodha",
}


def resolve(mode: str, niche: str, service: str) -> str:
    """Normalise what the UI sent into one of MODES.

    The UI is the only caller, but a mode that arrives empty or misspelled
    should fall back to the behaviour that existed before modes did, not fail
    the hunt.
    """
    mode = (mode or "").strip().lower()
    if mode in MODES:
        return mode
    return "niche" if (niche or "").strip() else "purpose"


def plan(mode: str, niche: str, service: str, target: int) -> list[str]:
    """The niches this hunt will search, in order.

    One entry means one call to the harvester. The caller stops early once the
    target is met, so a long list costs nothing when the first niche delivers.
    """
    mode = resolve(mode, niche, service)

    if mode == "niche":
        return [niche.strip()] if niche.strip() else []

    if mode == "purpose":
        # The service's own niche list, which is the whole point of the mode:
        # these are the business types that inherently run on the thing we are
        # selling. A website hunt has no such list — anyone can need a website
        # — so it sweeps the area instead of inventing trades.
        wanted = niches_for(service)
        return list(wanted) if wanted else [""]

    # An area sweep searches the PLACE, not a list of trades. One empty entry
    # means one harvest with no niche, which asks Maps "what is in this town"
    # and takes back whatever mix it returns. Walking a list of trades here was
    # a niche hunt in disguise — searching furniture in Sialkot, then clothing
    # in Sialkot — which is exactly what the mode exists to avoid.
    return [""]


def is_small_business(lead: dict) -> tuple[bool, str]:
    """Is this the owner-run business an area sweep is looking for?

    Only used by AREA. The niche modes already have a size test from the
    service definition, and applying this one there would reject leads the CEO
    deliberately searched for.
    """
    name = str(lead.get("business_name") or "")

    if _BRANCH_MARKER.search(name):
        return False, "a branch of a chain — the owner is not who answers"

    reviews = lead.get("reviews_count")
    if isinstance(reviews, int):
        if reviews > AREA_MAX_REVIEWS:
            return False, (f"{reviews:,} reviews — big enough to have someone "
                           f"handling this already")
        if reviews < AREA_MIN_REVIEWS:
            return False, (f"only {reviews} reviews — too small or too new to "
                           f"have the problem")

    # No review count is not a rejection. Plenty of real shops have none, and
    # the ICP gate removes the brands by name.
    return True, ""


def drop_chains(leads: list[dict]) -> tuple[list[dict], int]:
    """Remove businesses whose name repeats across the sweep.

    A sweep of one city turns up "Gourmet Bakers" eleven times. Each looks like
    a small shop on its own; together they are a chain with a head office, and
    none of the eleven numbers reaches anyone who can say yes. This can only be
    seen across the whole result, which is why it is not in is_small_business.
    """
    def key(l: dict) -> str:
        """The part of a name that a chain repeats.

        Keying on the first two words merged businesses that merely share a
        common prefix: "Al Noor Furniture", "Al Noor Medical Store" and "Al
        Noor Tailors" are three unrelated shops, and every second shopfront
        here is an Al Noor or a Bismillah. A chain repeats its trading name
        AND its trade, so the branch/area words are stripped from the end and
        what remains must match in full.
        """
        n = str(l.get("business_name") or "").strip().lower()
        n = _BRANCH_MARKER.sub(" ", n)
        parts = [p for p in re.split(r"[^\w]+", n) if p]
        # Drop a trailing place name: "gourmet bakers model town" -> the chain
        # is "gourmet bakers", but "al noor tailors" keeps its trade word.
        while len(parts) > 2 and parts[-1] in _AREA_WORDS:
            parts.pop()
        return " ".join(parts)

    counts = Counter(key(l) for l in leads if l.get("business_name"))
    chains = {k for k, c in counts.items() if c >= _CHAIN_THRESHOLD}
    if not chains:
        return leads, 0
    kept = [l for l in leads if key(l) not in chains]
    log.info("Area sweep: dropped %d leads from %d chains (%s)",
             len(leads) - len(kept), len(chains), ", ".join(sorted(chains)[:4]))
    return kept, len(leads) - len(kept)


def describe(mode: str, niche: str, service: str, where: str) -> str:
    """One line for the UI and the hunt log, in the CEO's own terms."""
    mode = resolve(mode, niche, service)
    label = SERVICES.get(service, {}).get("label", service)
    if mode == "niche":
        return f"{niche} in {where}"
    if mode == "purpose":
        n = len([x for x in plan(mode, niche, service, 0) if x])
        if n:
            return (f"anyone in {where} who needs {label.lower()} — "
                    f"searching {n} business types")
        return f"anyone in {where} who needs {label.lower()}"
    return f"every kind of small business in {where}"
