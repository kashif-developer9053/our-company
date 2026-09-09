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
from .scraper import scrape_google_maps
from .site_auditor import audit_leads
from .website_miner import mine_business_websites

log = get_logger("agent1.harvester")

# Query shapes that surface different businesses for the same niche.
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
) -> dict:
    """Search repeatedly until `target` qualified leads are collected.

    `progress` is an optional callable(str) used to report live status.
    `exclude_keys` lets a follow-up run skip businesses already collected.
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

    for template in _QUERY_TEMPLATES:
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
        # 2) Our own web crawler (good for published emails)
        try:
            mined = await mine_business_websites(query, max_results=_PER_ROUND)
            if mined.get("ok"):
                fresh.extend(mined.get("leads", []))
        except Exception as exc:  # noqa: BLE001
            log.error("Web mining round failed (isolated): %s", exc)

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

        # 4) Audit their sites so every kept lead has evidenced problems.
        try:
            await audit_leads(fresh, concurrency=_AUDIT_CONCURRENCY)
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
            if not lead.get("site_audit", {}).get("qualified"):
                rejected["good_site"] += 1
                continue
            lead["contact_verified"] = contact_desc
            lead["niche"] = lead.get("niche") or niche
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
        for template in _WIDEN_TEMPLATES:
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
                await audit_leads(wider, concurrency=_AUDIT_CONCURRENCY)
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
                if not lead.get("site_audit", {}).get("qualified"):
                    rejected["good_site"] += 1
                    continue
                lead["contact_verified"] = contact_desc
                lead["niche"] = lead.get("niche") or niche
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
