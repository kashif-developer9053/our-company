"""Why a lead was collected, and what to say to them because of it.

A lead used to carry one free-text `collection_reason` written by the site
auditor, so every message opened with a website complaint — including messages
to businesses whose website was fine and who were collected for CRM work. The
reader hears "your site has an H1 problem" and stops reading, correctly.

So a lead now carries `purposes`: an ordered list of what we could sell them,
strongest first. The first drives the pitch; the rest get one clause. Each
purpose knows three things the writer needs:

  * the HOOK — a fact about their business they can verify in ten seconds,
    which is what earns the read;
  * the OUTCOME — what changes for them, never the feature name;
  * the QUESTION — something only they can answer, which is what earns the
    reply. "Can we discuss this?" can be ignored; "how are patients finding
    you at the moment?" is harder to leave.

Diagnosis is deterministic. The evidence is already in the audit, the review
counts and the niche, and a model asked to decide would invent problems it
cannot see.
"""

from __future__ import annotations

import re

# Ordered by how convincing the pitch is when it applies. A business with no
# website at all is the strongest sell we have; a booking system for a busy
# salon is next; a CRM for a quiet office is the weakest.
PURPOSE_ORDER = ("website", "booking", "erp", "crm", "pos", "lms", "seo")

PURPOSES: dict[str, dict] = {
    "website": {
        "label": "Website",
        "systems": "a website",
        # {name}, {city}, {niche} are filled per lead.
        "hook": "they are on Google Maps but have no website, so nobody searching finds them",
        "outcome": "customers can find and contact them without phoning",
        "question": "How are customers finding you at the moment — mostly walk-ins?",
    },
    "booking": {
        "label": "Online booking",
        "systems": "online appointment booking with automatic WhatsApp reminders",
        "hook": "people rate them well, so demand exists, but every appointment is a phone call",
        "outcome": "customers book at 11pm without anyone answering the phone, and reminders cut no-shows",
        "question": "How many bookings do you take a day by phone?",
    },
    "erp": {
        "label": "Inventory & production",
        "systems": "order tracking and inventory in one place",
        "hook": "they take custom or bulk orders, which usually means stock tracked across registers",
        "outcome": "they can see stock and order status without walking to the warehouse",
        "question": "How are you tracking stock at the moment — registers?",
    },
    "crm": {
        "label": "Enquiry & customer management",
        "systems": "a system where every enquiry is logged with a follow-up date",
        "hook": "enquiries are clearly coming in; the loss happens after, when nobody calls back",
        "outcome": "no enquiry goes cold because someone forgot to follow up on day three",
        "question": "How are you tracking enquiries right now — WhatsApp and a diary?",
    },
    "pos": {
        "label": "Point of sale",
        "systems": "billing and stock in one system",
        "hook": "sales and stock are recorded by hand, so nobody knows what is actually selling",
        "outcome": "they can see daily sales and what is running out, without counting",
        "question": "How are you recording daily sales at the moment?",
    },
    "lms": {
        "label": "School management",
        "systems": "admissions, fees and attendance in one system",
        "hook": "admissions, fees and attendance are kept on paper across several registers",
        "outcome": "parents see fees and results online, and staff stop chasing paperwork",
        "question": "How are you handling fee records and attendance at the moment?",
    },
    "seo": {
        "label": "Search visibility",
        "systems": "search and listing work so they appear when people search",
        "hook": "they have a site but competitors appear above them in search",
        "outcome": "they show up when someone searches for what they sell",
        "question": "Where do most of your customers come from — Google or referrals?",
    },
}

# Niches that inherently run on a given system. Matched loosely against the
# lead's niche and category.
# Word boundaries matter: "Smart School" contains "mart", which matched the
# retail pattern and told a school we would build it a till.
_NICHE_SIGNALS: tuple[tuple[str, str], ...] = (
    (r"\b(clinics?|hospitals?|dental|dentists?|doctors?|physio\w*|medical|surgeons?|"
     r"labs?|diagnostics?|veterinar\w*|salons?|spas?|barbers?|gyms?|fitness|"
     r"practitioners?|therap\w*|aesthetics?|opticians?)\b", "booking"),
    (r"\b(manufactur\w*|mills?|factor(?:y|ies)|industr\w*|packing|packaging|"
     r"distribut\w*|wholesale\w*|suppliers?|traders?|textiles?|garments?|steel|"
     r"chemicals?|workshops?|fabricat\w*|printing|printers?|furniture|joinery|"
     r"tshirts?|t-shirts?|apparel|assembl\w*|solar)\b", "erp"),
    (r"\b(real estate|propert\w*|travel|tours?|insurance|recruit\w*|law|legal|"
     r"solicitors?|advocates?|attorneys?|immigration|consultan\w*|agenc(?:y|ies)|"
     r"dealers?|contractors?|builders?|architects?|interior design|designers?|"
     r"call cent\w*|bpo|marketing|brokers?|freight|logistics|movers?|"
     r"events?|caterers?|catering|document management|"
     r"data processing|outsourc\w*|photograph\w*|installers?)\b", "crm"),
    (r"\b(stores?|shops?|marts?|showrooms?|retail|pharmac\w*|grocer\w*|"
     r"baker(?:y|ies)|restaurants?|cafes?|pizza|burgers?|fast food|"
     r"boutiques?|outlets?|electronics|hardware|opticals?|sweets?|"
     r"juice|dhaba|takeaway|supermarkets?|superstores?|kiryana|"
     r"department stores?)\b", "pos"),
    (r"\b(schools?|academy|academies|colleges?|institutes?|tuition|coaching|"
     r"training|universit\w*|madrassa\w*|nurser(?:y|ies)|montessori|"
     r"learning cent\w*|driving school)\b", "lms"),
)

# Website faults that justify a website pitch. Cosmetic findings never do:
# nobody commissions a new site because a meta tag is missing.
_WEBSITE_FAULTS = {"no_website", "site_unreachable", "http_error"}

# Enough of an online presence to imply enquiries are already arriving, which
# is what makes a CRM or booking pitch land rather than sound invented.
_DEMAND_REVIEWS = 15


def _text(lead: dict) -> str:
    return " ".join(str(lead.get(k) or "") for k in
                    ("niche", "category", "business_name", "notes")).lower()


def diagnose(lead: dict, wanted: str = "") -> list[str]:
    """What we could sell this business, strongest pitch first.

    `wanted` biases the result when the CEO is hunting for one service: it is
    placed first if it applies at all, because that is the campaign they are
    running. An empty list means we have nothing honest to sell them.
    """
    found: list[str] = []
    codes = {f.get("code") for f in (lead.get("site_audit") or {}).get("findings", [])}
    text = _text(lead)
    reviews = lead.get("reviews_count")
    has_site = bool((lead.get("website") or "").strip())

    if codes & _WEBSITE_FAULTS or not has_site:
        found.append("website")

    for pattern, purpose in _NICHE_SIGNALS:
        if re.search(pattern, text) and purpose not in found:
            # A software pitch needs evidence the business is actually
            # trading. Review count is the only size signal available; when
            # it is missing we allow it rather than lose a real lead.
            if reviews is None or reviews >= _DEMAND_REVIEWS:
                found.append(purpose)

    # A working site that nobody can find is an SEO pitch, not a rebuild.
    if has_site and "website" not in found and not found:
        found.append("seo")

    if wanted and wanted in PURPOSES:
        if wanted in found:
            found.remove(wanted)
            found.insert(0, wanted)
        elif _plausible(wanted, lead):
            found.insert(0, wanted)

    return sorted(dict.fromkeys(found), key=lambda p: (found.index(p),))[:3]


def _plausible(purpose: str, lead: dict) -> bool:
    """Could we honestly pitch this, even though the niche did not signal it?

    Used when the CEO is running a campaign for one service. Every business
    could use a CRM in principle, so this stays permissive — but never for a
    website pitch, which needs an actual fault.
    """
    if purpose == "website":
        codes = {f.get("code") for f in (lead.get("site_audit") or {}).get("findings", [])}
        return bool(codes & _WEBSITE_FAULTS) or not (lead.get("website") or "").strip()
    return True


def label(purpose: str) -> str:
    return PURPOSES.get(purpose, {}).get("label", purpose)


def brief(purposes: list[str], lead: dict) -> str:
    """The writing brief for a lead: what to lead with, what to mention."""
    if not purposes:
        return ""
    main = PURPOSES.get(purposes[0])
    if not main:
        return ""

    name = lead.get("business_name") or "this business"
    city = lead.get("city") or ""
    rating = lead.get("rating")
    reviews = lead.get("reviews_count")

    # Facts they can check. This is what separates a message that gets read
    # from one that reads as a template.
    evidence = []
    if rating and reviews:
        evidence.append(f"{rating} stars from {reviews} Google reviews")
    elif reviews:
        evidence.append(f"{reviews} Google reviews")
    if not (lead.get("website") or "").strip():
        evidence.append("no website at all")
    elif {f.get("code") for f in (lead.get("site_audit") or {}).get("findings", [])} & _WEBSITE_FAULTS:
        evidence.append("their website does not load")

    # The website hook has two quite different shapes, and using the wrong one
    # is immediately obvious to the reader: telling a business with a broken
    # site that they "have no website" proves you did not look.
    hook = main["hook"]
    if purposes[0] == "website" and (lead.get("website") or "").strip():
        codes = {f.get("code") for f in (lead.get("site_audit") or {}).get("findings", [])}
        if "site_unreachable" in codes:
            hook = ("their website does not open at all, so anyone who clicks it gives up")
        elif "http_error" in codes:
            hook = ("their website shows an error page instead of the business")

    parts = [
        f"MAIN PITCH: {main['label']}.",
        f"THE HOOK — open with this, it is what makes them keep reading: {hook}.",
        f"WHAT WE BUILD: {main['systems']}.",
        f"THE OUTCOME to promise (never the feature name): {main['outcome']}.",
        f"CLOSE WITH THIS QUESTION, or a close variant: \"{main['question']}\"",
    ]
    if evidence:
        parts.insert(1, "VERIFIABLE FACTS about them — quote at least one so it is obvious "
                        f"you actually looked: {name}{' in ' + city if city else ''}, "
                        f"{', '.join(evidence)}.")
    if len(purposes) > 1:
        extra = [PURPOSES[p]["systems"] for p in purposes[1:] if p in PURPOSES]
        if extra:
            parts.append(f"SECONDARY — work in as ONE clause, never a list: we also build "
                         f"{' and '.join(extra)}.")
    return "\n".join(parts)


def reason_line(purposes: list[str], lead: dict) -> str:
    """The remark stored on the lead, explaining why it was collected."""
    if not purposes:
        return ""
    bits = []
    if not (lead.get("website") or "").strip():
        bits.append("no website")
    else:
        codes = {f.get("code") for f in (lead.get("site_audit") or {}).get("findings", [])}
        if "site_unreachable" in codes:
            bits.append("site does not load")
        elif "http_error" in codes:
            bits.append("site returns an error")
    reviews = lead.get("reviews_count")
    if reviews:
        bits.append(f"{reviews} reviews")
    facts = "; ".join(bits)
    names = ", ".join(label(p) for p in purposes)
    return f"Collected for {names}" + (f" — {facts}." if facts else ".")
