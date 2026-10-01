"""Continuous lead harvesting until a target number of QUALIFIED leads is met.

A lead only counts toward the target when BOTH are true:
  1. It has a real, verified way to contact them — an email actually published on
     their own site (never an `info@domain` guess) or a valid phone number.
  2. Its website has real, evidenced problems we can fix (site audit qualified).

The harvester runs several search rounds with varied query phrasings, because a
single search engine query caps out at ~20 results. It stops as soon as the
target is reached, the query variants run out, or the time budget expires — so
it never spins forever.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from shared.logger import get_logger

from .contact_enrichment import enrich_lead_emails
from .purposes import diagnose as diagnose_purposes
from .purposes import reason_line as purpose_reason
from .scraper import scrape_google_maps
from .service_targets import is_website_service
from .service_targets import qualifies as service_qualifies
from .site_auditor import audit_leads
from .social_miner import discover_social_businesses
from .website_miner import mine_business_websites

log = get_logger("agent1.harvester")




def _swept_niche(lead: dict, query: str = "") -> str:
    """What trade a swept business is, when no niche was searched for.

    A sweep asks about a place, so nothing names the trade. Maps puts it on
    the list card ("Solar energy company", "Furniture store") and the scraper
    already reads it — but that field also catches opening hours and phone
    numbers when the card shows no category, so anything of that shape is
    discarded rather than stored as a trade.
    """
    cat = str(lead.get("category") or "").strip()
    if not cat:
        return ""
    low = cat.lower()
    if any(x in low for x in ("open", "closes", "closed", "24 hours", "+", "·")):
        return ""
    if len(cat) > 60 or cat == (lead.get("business_name") or "").strip():
        return ""
    # The web crawler stores the SEARCH that found a business in `category`
    # (website_miner.py), so on a sweep that field reads "businesses in
    # Sialkot, Pakistan" — the query, not a trade. Maps is the only source
    # that puts a real category there.
    if query and cat.strip().lower() == query.strip().lower():
        return ""
    return cat

def _qualifies(service: str, lead: dict, sweep: bool) -> tuple[bool, str]:
    """Is this lead worth keeping, given what the hunt is looking for?"""
    if not sweep:
        return service_qualifies(service, lead)

    # A niche hunt asks for one trade, so what comes back is roughly right.
    # A sweep asks a whole town and gets software houses, chain branches and
    # government offices mixed in with the shops. Agent 2 would reject those
    # later anyway, so checking here only saves the audit — but it also keeps
    # the sweep's own count honest about what it actually found.
    from agent2.icp import classify
    verdict, why = classify(lead)
    if verdict != "keep":
        return False, why
    # An area sweep has no service to test against. The honest question is
    # whether the diagnosis found anything we could sell them — if it did not,
    # there is no message to write and the lead is worthless.
    if diagnose_purposes(lead):
        return True, ""
    return False, "nothing we can honestly sell them"

def _stamp_purpose(lead: dict, service: str) -> None:
    """Record WHY this lead was collected, so outreach can pitch the right thing.

    Every lead carries `purposes` — an ordered list of what we could honestly
    sell them, strongest first — and a plain-English `collection_reason` built
    from it. The outreach writers read `purposes`; nothing downstream has to
    re-derive the diagnosis from the audit, which is how messages about H1 tags
    used to reach businesses collected for CRM work.

    The service being hunted is passed as a bias, not a verdict: if it applies
    at all it leads the pitch, but a lead that only fits something else still
    gets pitched the thing that actually fits.
    """
    lead["service_target"] = service
    purposes = diagnose_purposes(lead, wanted=service)
    lead["purposes"] = purposes
    reason = purpose_reason(purposes, lead)
    # A website lead keeps the auditor's own summary, which names the actual
    # fault; for everything else the auditor has nothing useful to say.
    if is_website_service(service) and (lead.get("site_audit") or {}).get("summary"):
        lead["collection_reason"] = lead["site_audit"]["summary"]
    elif reason:
        lead["collection_reason"] = reason

# Query shapes that surface different businesses for the same niche.
# An AREA SWEEP names no trade at all. The CEO asked for "a location, and all
# the niches there" — not furniture in Sialkot, then clothing in Sialkot, which
# is just a niche hunt wearing a hat.
#
# Maps answers a location-only query with whatever it has, mixed: on "businesses
# in Sialkot" it returned sports manufacturers, trading companies and
# enterprises together. The wording matters more than it looks. "shops in X"
# comes back full of shopping malls and Outfitters branches, and a bare "X"
# returns nothing at all, so both are avoided.
#
# The variety comes from asking the same place in different ways, and from
# naming the commercial districts where the small businesses actually are.
_AREA_TEMPLATES = (
    "businesses in {where}",
    "companies in {where}",
    "small businesses in {where}",
    "local business {where}",
    "family business {where}",
    "traders in {where}",
    "manufacturers in {where}",
    "suppliers in {where}",
    "services in {where}",
    "enterprises in {where}",
    # Proximity is how Maps ranks, so naming the commercial part of a town
    # surfaces businesses a centre-weighted search never reaches. These work
    # anywhere; the local district words come from _AREA_DISTRICTS below.
    "businesses main road {where}",
    "shops main market {where}",
    "businesses commercial area {where}",
    "businesses industrial area {where}",
    "businesses town centre {where}",
    "businesses high street {where}",
    "businesses old town {where}",
    "businesses station road {where}",
    "trading company {where}",
    "industries in {where}",
    "workshop {where}",
    "store {where} contact number",
    "office {where} phone number",
)

# District words are local. "Cantt", "Saddar" and "GT Road" name real
# commercial areas in Pakistan and return nothing in Trier; a sweep there was
# spending rounds on queries that could not match. Only the ones belonging to
# the country being swept are appended.
_AREA_DISTRICTS = {
    "pakistan": ("main bazar", "cantt", "saddar", "model town",
                 "satellite town", "civil lines", "gt road", "college road"),
    "india": ("main bazar", "civil lines", "mg road", "market road",
              "industrial estate"),
    "bangladesh": ("bazar", "new market", "industrial area"),
    "united arab emirates": ("industrial area", "souk", "deira", "free zone"),
    "saudi arabia": ("souq", "industrial city", "king fahd road"),
    "united kingdom": ("high street", "retail park", "industrial estate",
                       "trading estate"),
    "ireland": ("main street", "industrial estate", "retail park"),
    "germany": ("innenstadt", "gewerbegebiet", "hauptstrasse", "altstadt"),
    "united states": ("downtown", "main street", "business district"),
}


def _area_queries(country: str) -> tuple[str, ...]:
    """Location-only query templates, with the district words of that country.

    A sweep searches the PLACE, so the only variation available is how the
    place is described. Mixing in the wrong country's districts wastes rounds.
    """
    key = (country or "").strip().lower()
    local = ()
    # An empty country must not match: `"" in name` is true for every entry,
    # which quietly gave a sweep of an unnamed country Pakistani districts.
    if key:
        for name, words in _AREA_DISTRICTS.items():
            if key == name or key in name or name in key:
                local = words
                break
    return _AREA_TEMPLATES + tuple(
        "businesses " + w + " {where}" for w in local)

_QUERY_TEMPLATES = (
    "{niche} in {where}",
    "{niche} {where} contact",
    "best {niche} in {where}",
    "{niche} services {where}",
    "top {niche} companies {where}",
    "{niche} near {where}",
    "local {niche} {where}",
    "{niche} company {where} email",
    "affordable {niche} {where}",
    "{niche} {where} phone number",
    "list of {niche} in {where}",
    "{niche} directory {where}",
    "small {niche} business {where}",
    "{niche} {where} about us",
    # Maps ranks by proximity, so naming a sub-area surfaces businesses the
    # centre-weighted searches never return. This is the highest-yield way to
    # keep mining a niche the plain queries have exhausted.
    "{niche} main road {where}",
    "{niche} town centre {where}",
    "{niche} {where} branch",
    "new {niche} {where}",
    "{niche} clinic {where}",
    "private {niche} {where}",
    "{niche} centre {where}",
    "{niche} {where} opening hours",
    "family {niche} {where}",
    "{niche} specialist {where}",
    "24 hour {niche} {where}",
    "{niche} {where} reviews",
    "cheap {niche} {where}",
    "{niche} consultancy {where}",
)

# A round costs about 3-5 minutes, nearly all of it in Maps and the web
# crawler. At 30 minutes a hunt got through only ~6 rounds, which is not enough
# to reach a 20+ target once duplicates are excluded.
_DEFAULT_TIME_BUDGET = 3600  # seconds; a hard ceiling on one harvest run

# Consecutive rounds returning nothing new before we call a niche exhausted.
# This was 3, which quit far too early: once part of a niche is collected,
# every known business counts as "nothing new", so a niche that still had
# plenty left looked dead. The later query templates are the most
# differentiated, so it is worth pushing through a few empty rounds to reach
# them.
_BARREN_LIMIT = 6

# Businesses pulled per search round. Three filters run in series afterwards
# (already-known, verified contact, evidenced site problems), and they multiply:
# at 20 per round a first hunt yielded only three or four qualified leads. One
# search returning 40 costs little more than one returning 20.
_PER_ROUND = 40

# Below this many qualified leads a run is considered "thin" and tolerates far
# more empty rounds before giving up — the point at which persistence is worth
# most is precisely when little has been found.
_PERSIST_UNTIL = 20
_BARREN_LIMIT_THIN = 12

# A hunt returning fewer than this has not really answered the question, so it
# escalates to nearby-area searches before reporting back.
_MIN_ACCEPTABLE = 20

# Used only for that escalation: same niche, deliberately looser geography.
_WIDEN_TEMPLATES = (
    "{niche} near {where}",
    "{niche} {country}",
    "best {niche} {country}",
    "{niche} services near {where}",
    "{niche} in {country} contact",
)
# Widening a sweep means the surrounding towns, not a broader trade. With an
# empty niche the templates above would render as " near Sialkot".
_AREA_WIDEN_TEMPLATES = (
    "businesses near {where}",
    "businesses in {country}",
    "small businesses {country}",
    "traders near {where}",
    "manufacturers in {country}",
)
_AUDIT_CONCURRENCY = 12      # sites audited in parallel (each is a light HTTP GET)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lead_key(lead: dict) -> str:
    site = (lead.get("website") or "").strip().lower()
    if site:
        host = site.split("//")[-1].split("/")[0]
        return host[4:] if host.startswith("www.") else host
    return (lead.get("business_name") or "").strip().lower()


def has_real_contact(lead: dict) -> tuple[bool, str]:
    """A contact route we actually observed — never a guessed address.

    "Guessed" means `info@<domain>` invented purely because the domain resolves.
    Nobody checked that the mailbox exists, so these are the addresses that hard
    bounce, and bounce rate is what gets a sending domain filtered.

    This gate is about EMAILABILITY specifically. A listed phone number is a
    real contact route, but it does not make a guessed address safe to mail —
    an earlier version accepted the lead on the strength of the phone and then
    the outreach agent mailed the invented address anyway. A phone-only lead is
    therefore kept only when it carries no fabricated email to mail.
    """
    email = (lead.get("email") or "").strip()
    confidence = (lead.get("email_confidence") or "").strip().lower()
    source_url = (lead.get("email_source_url") or "").strip()

    if email:
        # Observed on the site, or reported by a miner that recorded where.
        if confidence in ("found", "published") or source_url:
            return True, f"published email {email}"
        if confidence == "verified_guess":
            # A pattern address the receiving mail server confirmed exists.
            return True, f"verified address {email}"
        if confidence == "guessed":
            return False, f"only a guessed address ({email}) — not verified, likely to bounce"
        # Blank confidence means nothing recorded the provenance. Treating that
        # as "published" is how invented addresses slipped through before, so
        # an unattributed address is not trusted.
        return False, f"email {email} has no recorded source — cannot confirm it is real"

    phone = (lead.get("phone") or "").strip()
    if phone:
        return True, f"listed phone {phone}"
    if lead.get("whatsapp"):
        return True, "WhatsApp contact"
    return False, "no verified contact method (guessed addresses don't count)"


def _merge(existing: dict[str, dict], incoming: list[dict]) -> int:
    """Merge new leads into the pool, filling blanks on duplicates. Returns
    how many genuinely new businesses were added."""
    added = 0
    for lead in incoming:
        key = _lead_key(lead)
        if not key:
            continue
        if key in existing:
            for field, value in lead.items():
                if value and not existing[key].get(field):
                    existing[key][field] = value
        else:
            existing[key] = dict(lead)
            added += 1
    return added


async def harvest_leads(
    niche: str,
    city: str = "",
    country: str = "",
    target: int = 50,
    time_budget: int = _DEFAULT_TIME_BUDGET,
    exclude_keys: set[str] | None = None,
    progress=None,
    service: str = "website",
    sweep: bool = False,
) -> dict:
    """Search repeatedly until `target` qualified leads are collected.

    `progress` is an optional callable(str) used to report live status.
    `exclude_keys` lets a follow-up run skip businesses already collected.

    `sweep` means an area sweep, where no service was chosen: the caller is
    asking "what is here and what does it need". The service test is wrong
    then — it would reject every business with a working website, which is
    most of them, and those are exactly the ones that need a till or a CRM.
    The question becomes whether we can honestly sell them anything at all.
    """
    where = ", ".join(x for x in (city, country) if x) or "your area"
    started = time.perf_counter()
    exclude = exclude_keys or set()

    pool: dict[str, dict] = {}       # every business seen this run
    qualified: dict[str, dict] = {}  # those meeting BOTH criteria
    rejected = {"no_contact": 0, "good_site": 0, "guessed_email_only": 0}
    rounds_run = 0
    barren_rounds = 0  # consecutive rounds that surfaced no new businesses

    def say(msg: str) -> None:
        log.info(msg)
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    # A sweep asks about the PLACE; a niche hunt asks about the trade.
    templates = _area_queries(country) if sweep else _QUERY_TEMPLATES
    for template in templates:
        if len(qualified) >= target:
            break
        if time.perf_counter() - started > time_budget:
            say(f"Time budget reached after {rounds_run} search rounds.")
            break

        rounds_run += 1
        query = template.format(niche=niche, where=where)
        say(f"Round {rounds_run}: searching '{query}' ({len(qualified)}/{target} qualified so far)")

        fresh: list[dict] = []
        # 1) Google Maps (good for phone numbers + addresses)
        try:
            maps = await scrape_google_maps(query, max_results=_PER_ROUND)
            if maps.get("ok"):
                fresh.extend(maps.get("leads", []))
        except Exception as exc:  # noqa: BLE001 - one source failing is survivable
            log.error("Maps round failed (isolated): %s", exc)
        # 2) Our own web crawler (good for published emails).
        #
        #    A sweep skips it. Maps answers a location query with ~12 results
        #    that carry a category and a review count; the crawler answers the
        #    same query from search results, with neither. On a sweep that
        #    matters: the size filter and the chain filter both need those
        #    numbers, and without them a sweep of Sialkot came back with eight
        #    businesses of unknown size, no trade, and mostly the weakest
        #    pitch we have. There are 30 area queries to work through instead,
        #    each returning real Maps data.
        if not sweep:
            try:
                mined = await mine_business_websites(query, max_results=_PER_ROUND)
                if mined.get("ok"):
                    fresh.extend(mined.get("leads", []))
            except Exception as exc:  # noqa: BLE001
                log.error("Web mining round failed (isolated): %s", exc)
        # 3) Businesses that exist only on Facebook/Instagram. Maps and the web
        #    crawler both assume a website, so these were invisible — yet "no
        #    website at all" is the strongest pitch we have. Run once per hunt
        #    rather than per round: the queries do not vary by template and the
        #    engines throttle quickly.
        # A sweep has no trade to search social for, and "business in Sialkot"
        # on Facebook returns pages, not businesses.
        if rounds_run == 1 and not sweep:
            try:
                social = await discover_social_businesses(
                    niche, where, max_results=_PER_ROUND)
                if social.get("ok") and social.get("leads"):
                    fresh.extend(social["leads"])
                    say(f"Social search added {len(social['leads'])} businesses with no website.")
            except Exception as exc:  # noqa: BLE001
                log.error("Social mining failed (isolated): %s", exc)

        # Drop anything already collected in a previous run or round.
        raw_count = len(fresh)
        fresh = [l for l in fresh if _lead_key(l) and _lead_key(l) not in exclude and _lead_key(l) not in pool]
        if not fresh:
            barren_rounds += 1
            say(f"Round {rounds_run}: all {raw_count} results were already known — nothing new.")
            # If several rounds in a row surface nothing new, this niche/area is
            # genuinely exhausted; stop rather than burning the whole budget.
            # Be far more stubborn while the haul is still thin. Quitting after
            # a few empty rounds is reasonable once there is a decent pile, but
            # when almost nothing has been found the remaining templates are
            # exactly what might work, so push on through the empty ones.
            limit = _BARREN_LIMIT if len(qualified) >= _PERSIST_UNTIL else _BARREN_LIMIT_THIN
            if barren_rounds >= limit:
                say(f"{barren_rounds} rounds with no new businesses and "
                    f"{len(qualified)} qualified so far — this niche/area looks exhausted. "
                    f"Try widening the location or a different niche.")
                break
            continue
        barren_rounds = 0
        _merge(pool, fresh)

        # 3) Find REAL published emails for the new candidates.
        try:
            await enrich_lead_emails(fresh, concurrency=8)
        except Exception as exc:  # noqa: BLE001
            log.error("Enrichment failed (isolated): %s", exc)

        # 4) Audit their sites. For a website hunt this is the qualifying
        #    test; for CRM/ERP/booking it only answers "does their site work",
        #    which the purpose diagnosis needs — so it must not also claim the
        #    collection reason.
        try:
            await audit_leads(fresh, concurrency=_AUDIT_CONCURRENCY,
                              set_reason=is_website_service(service))
        except Exception as exc:  # noqa: BLE001
            log.error("Audit failed (isolated): %s", exc)

        # 5) Apply BOTH gates.
        for lead in fresh:
            key = _lead_key(lead)
            if key in qualified:
                continue
            contact_ok, contact_desc = has_real_contact(lead)
            if not contact_ok:
                rejected["no_contact"] += 1
                if (lead.get("email_confidence") or "") == "guessed":
                    rejected["guessed_email_only"] += 1
                continue
            # For website work the audit decides. For CRM/ERP/booking the
            # audit is the wrong test — a business with a perfect site may
            # still be running stock on paper — so size decides instead.
            # A sweep asks neither: it keeps whatever we can sell something to.
            fits, why_not = _qualifies(service, lead, sweep)
            if not fits:
                rejected["good_site"] += 1
                continue
            lead["contact_verified"] = contact_desc
            _stamp_purpose(lead, service)
            lead["niche"] = lead.get("niche") or niche or _swept_niche(lead, query)
            lead["city"] = lead.get("city") or city
            lead["country"] = lead.get("country") or country
            qualified[key] = lead
            if len(qualified) >= target:
                break

        say(f"Round {rounds_run} done — {len(qualified)}/{target} qualified "
            f"({rejected['no_contact']} no contact, {rejected['good_site']} site already fine)")

    # Still short after every template? The businesses are usually there, just
    # not ranking under this exact city wording. Retry with nearby-area phrasing
    # before giving up, rather than handing back a near-empty result and making
    # the CEO work out that "widen the location" was the missing step.
    if (len(qualified) < min(target, _MIN_ACCEPTABLE)
            and city
            and time.perf_counter() - started < time_budget * 0.75):
        say(f"Only {len(qualified)} found in {where} — widening to the surrounding area.")
        for template in (_AREA_WIDEN_TEMPLATES if sweep else _WIDEN_TEMPLATES):
            if len(qualified) >= target or time.perf_counter() - started > time_budget:
                break
            rounds_run += 1
            query = template.format(niche=niche, where=where, country=country or where)
            say(f"Round {rounds_run} (widened): '{query}' ({len(qualified)}/{target})")
            wider: list[dict] = []
            try:
                mres = await scrape_google_maps(query, max_results=_PER_ROUND)
                if mres.get("ok"):
                    wider.extend(mres.get("leads", []))
            except Exception as exc:  # noqa: BLE001
                log.error("Widened maps round failed (isolated): %s", exc)
            try:
                if not sweep:
                    wres = await mine_business_websites(query, max_results=_PER_ROUND)
                    if wres.get("ok"):
                        wider.extend(wres.get("leads", []))
            except Exception as exc:  # noqa: BLE001
                log.error("Widened mining round failed (isolated): %s", exc)

            wider = [l for l in wider
                     if _lead_key(l) and _lead_key(l) not in exclude and _lead_key(l) not in pool]
            if not wider:
                continue
            _merge(pool, wider)
            try:
                await enrich_lead_emails(wider, concurrency=8)
                await audit_leads(wider, concurrency=_AUDIT_CONCURRENCY,
                                  set_reason=is_website_service(service))
            except Exception as exc:  # noqa: BLE001
                log.error("Widened enrichment/audit failed (isolated): %s", exc)
            for lead in wider:
                key = _lead_key(lead)
                if key in qualified:
                    continue
                contact_ok, contact_desc = has_real_contact(lead)
                if not contact_ok:
                    rejected["no_contact"] += 1
                    continue
                fits, why_not = _qualifies(service, lead, sweep)
                if not fits:
                    rejected["good_site"] += 1
                    continue
                lead["contact_verified"] = contact_desc
                _stamp_purpose(lead, service)
                lead["niche"] = lead.get("niche") or niche or _swept_niche(lead, query)
                lead["city"] = lead.get("city") or city
                lead["country"] = lead.get("country") or country
                qualified[key] = lead
                if len(qualified) >= target:
                    break

    elapsed = int(time.perf_counter() - started)
    leads = list(qualified.values())
    leads.sort(key=lambda l: l.get("opportunity_score", 0), reverse=True)

    complete = len(leads) >= target
    if complete:
        message = f"Found {len(leads)} qualified leads for {niche} in {where}."
    else:
        # Explain WHICH constraint ran out, so the CEO knows what to change.
        if barren_rounds >= 3:
            why = (f"I ran out of new businesses — searches kept returning the same {len(pool)} "
                   f"companies I had already checked.")
        elif time.perf_counter() - started > time_budget:
            why = f"I hit the {time_budget // 60}-minute time limit for one hunt."
        else:
            why = (f"I used all {rounds_run} search phrasings I have for this niche and only "
                   f"{len(pool)} distinct businesses exist in these results.")
        message = (
            f"Found {len(leads)} of the {target} you asked for, in {niche} ({where}). {why} "
            f"Of the {len(pool)} businesses I examined, {rejected['no_contact']} had no verified "
            f"contact (guessed addresses don't count) and {rejected['good_site']} already have good "
            f"websites, so they aren't prospects. To get more, try a wider location or another niche."
        )

    return {
        "ok": True,
        "leads": leads,
        "found": len(leads),
        "target": target,
        "complete": complete,
        "rounds": rounds_run,
        "examined": len(pool),
        "rejected": rejected,
        "elapsed_seconds": elapsed,
        "niche": niche,
        "city": city,
        "country": country,
        "message": message,
        "harvested_at": _now(),
    }
