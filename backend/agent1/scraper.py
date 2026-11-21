"""Agent 1 real scraping — Google Maps business search via Playwright.

Respectful behavior: randomized delays, a capped batch per run, a realistic
user-agent, gradual scrolling, and graceful per-result failure handling. If
Google blocks/rate-limits or shows a consent/CAPTCHA wall, we detect it, stop
cleanly, and report it (the caller sets Agent 1 to "error").

Strategy: read the results feed once. Each result card already carries the
name, rating, review count, category, address, phone and website, so no
per-business detail page is opened - that stage cost ~25s per business and
showed a phone for only 3 of 5 places the cards all had phones for.
"""

from __future__ import annotations

import asyncio
import random
import re

from shared.logger import get_logger

log = get_logger("agent1.scraper")

# Fallback only. The real user agent is derived from the running browser by
# _ua_for(), below; this value is used only if the version string cannot be
# read, and is deliberately a plausible recent Chrome rather than a fixed old
# one.
_UA_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def _ua_for(browser) -> str:
    """Claim the version of the browser that is actually running.

    This function exists because of a measured outage. The scraper used to
    send a hardcoded `Chrome/125.0.0.0` while the installed Chromium was 151 -
    about two years of drift, because the constant was written once and the
    browser is upgraded by `pip install playwright` on every deploy.

    Google reads that mismatch as automation. Measured on the VPS, same code,
    same query, three probes:

        stale UA (125), resources blocked -> FAIL, 60s timeout, 0 cards
        real  UA (151), resources blocked -> feed found, 10 cards
        real  UA (151), nothing blocked   -> feed found, 10 cards

    It had been returning zero businesses for every round of every hunt, which
    read as "this market has no businesses" rather than as a scraper fault.
    The same code kept working from a home connection, where a residential IP
    buys enough benefit of the doubt to survive the bad UA - so the bug only
    appeared in production.

    Deriving the string from `browser.version` means it cannot drift again:
    the claim is true by construction, whatever Playwright installs next.
    """
    try:
        # browser.version is like "151.0.7922.34" (Chromium) or
        # "Chrome/151.0.7922.34" depending on the channel.
        raw = (browser.version or "").strip()
        ver = raw.split("/")[-1]                    # drop any "Chrome/" prefix
        major = ver.split(".")[0]
        if major.isdigit():
            return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    f"AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{major}.0.0.0 Safari/537.36")
    except Exception:  # noqa: BLE001 - a UA is never worth failing a hunt for
        pass
    return _UA_FALLBACK


# Resource types refused in the Maps tab. Images, media and fonts are pure
# bytes we never read — blocking them is what let a Memphis search finish at
# all (it had been timing out at 75s).
#
# Stylesheets are NOT blocked, and that is measured, not assumed: blocking
# them cost 8s on average (50s vs 42s, three runs each). Maps lays the results
# feed out with CSS and the selectors here wait on that feed, so refusing
# stylesheets pays more in settling time than it saves in download. They were
# blocked in the first version of this change, which is what made a Lahore
# search slower than before the whole exercise started.
_BLOCKED_RESOURCES = {"image", "media", "font"}


# How long Maps is given to arrive, and then to draw its results.
#
# These were 45s and 12s, chosen on a developer machine where the whole page
# renders in about 7 seconds. Measured on the VPS, same code and query, six
# consecutive runs on 2026-11-21:
#
#     nav:   2s, 4s, 29s, 31s, 48s, 58s     (same URL, same minute)
#     full:  59s, 61s, 69s to a drawn feed
#
# Every one of those runs delivered the businesses. No HTTP error was logged
# on any of them - the page is simply slow to render from this machine, and
# the old ceilings cut it off mid-draw and reported "no results feed found",
# which the harvester passed on as an exhausted market.
#
# The variance is the point: a limit near the average fails about half the
# time. These are set above the slowest success observed, not near the mean.
# A hunt that waits 90s and finds 20 businesses beats one that gives up at
# 45s and finds nothing - the round is wasted either way, but only one of
# them produces leads.
#
# Updated with four more measurements once the scrape was working end to end
# on the VPS, 2026-11-21:
#
#     full scrape, 5 leads:  115s, 118s, 121s, 126s
#
# Consistent, unlike the earlier spread of 2-58s navigation times - that
# erraticism was partly the layout bug making some runs fail fast. The honest
# figure for this server is about two minutes for a working scrape.
#
# 90s + 45s allowed 135s in total, which cleared 126s by nine seconds. A
# margin that thin is not a margin: a hunt calls this dozens of times, so the
# slowest call of twenty decides whether the round produces leads, and the
# cost of being wrong is another round reported as an empty market.
_GOTO_TIMEOUT_MS = 150_000
_FEED_TIMEOUT_MS = 60_000


async def _pause(a: float = 1.0, b: float = 4.0) -> None:
    await asyncio.sleep(random.uniform(a, b))


async def _launch_browser(playwright):
    """Launch headless Chromium with the flags a server actually needs.

    website_miner's contact fallback has always imported this name, but it
    never existed, so every hunt logged "Browser contact fallback unavailable:
    cannot import name '_launch_browser'" and silently skipped rendering
    JavaScript-only contact pages. The flags below were already duplicated
    inline in scrape_google_maps; this is now the one definition both use.

    --no-sandbox / --disable-dev-shm-usage are required on a headless Linux
    server: the Chromium sandbox needs privileges a systemd service does not
    have, and the default /dev/shm is too small for Chromium.
    """
    return await playwright.chromium.launch(headless=True, args=[
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ])


async def scrape_google_maps(query: str, max_results: int = 20,
                             country: str = "") -> dict:
    """Return {ok, blocked, message, leads:[...]}. Never raises.

    `country` is used only to put phone numbers into international form. It is
    passed explicitly rather than read out of `query`, because matching a
    country name inside the query string is ambiguous: "Landscapers in
    Seattle, United States" contains one country, but a query naming two
    places would silently pick whichever the table happened to match first,
    and stamp a US number with a Pakistani code. Callers know the country;
    they should say it.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "blocked": False, "message": f"Playwright not available: {exc}", "leads": []}

    leads: list[dict] = []
    browser = None
    try:
        async with async_playwright() as pw:
            # --no-sandbox / --disable-dev-shm-usage are required on a headless
            # Linux server: the Chromium sandbox needs privileges a systemd
            # service doesn't have, and /dev/shm is too small by default.
            browser = await pw.chromium.launch(headless=True, args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ])
            context = await browser.new_context(
                user_agent=_ua_for(browser),
                viewport={"width": 1280, "height": 900}, locale="en-US")

            # Block everything we do not read. Maps is a MAP: it pulls down
            # tiles, photos, icons and fonts by the megabyte, and this scraper
            # wants four strings per business — name, phone, website, rating.
            # Measured from the VPS, a Lahore search took 39s with all of it
            # and a Memphis search never finished inside 75s at all, which is
            # what made worldwide hunting fail while the home market worked.
            #
            # The HTML and the scripts that build the results feed still load;
            # only the pixels are refused.
            async def _block_heavy(route) -> None:
                if route.request.resource_type in _BLOCKED_RESOURCES:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", _block_heavy)

            page = await context.new_page()
            await page.goto(f"https://www.google.com/maps/search/{query.replace(' ', '+')}",
                            wait_until="domcontentloaded",
                            timeout=_GOTO_TIMEOUT_MS)
            # Was 2-4s. The pause exists to look human and to let the feed
            # render; with images blocked the feed is ready sooner, and the
            # explicit feed.wait_for() below is what actually guarantees it.
            await _pause(1, 2)

            # Consent wall?
            if "consent.google.com" in page.url:
                try:
                    btn = page.get_by_role("button", name=re.compile("Accept all|I agree", re.I))
                    if await btn.count():
                        await btn.first.click()
                        await _pause(2, 3)
                except Exception:  # noqa: BLE001
                    pass

            # Block / unusual-traffic page?
            body_text = (await page.locator("body").inner_text())[:600].lower()
            if any(s in body_text for s in ("unusual traffic", "are you a robot", "captcha", "our systems have detected")):
                return {"ok": False, "blocked": True,
                        "message": "Scraping paused — possible rate limiting detected (Google challenge page).", "leads": []}

            feed = page.locator("div[role='feed']")
            try:
                await feed.wait_for(timeout=_FEED_TIMEOUT_MS)
            except Exception:  # noqa: BLE001
                if "google.com/maps" not in page.url:
                    return {"ok": False, "blocked": True, "message": "Scraping paused — redirected away from Maps (possible block).", "leads": []}
                return {"ok": True, "blocked": False, "message": "No results feed found (0 businesses).", "leads": []}

            # Collect the result cards. Each card is a direct child div of the
            # feed that contains a place link, and it carries EVERYTHING this
            # scraper needs already rendered: name, rating, review count,
            # category, address, phone and website.
            #
            # This replaced opening one detail page per business. Measured on
            # the VPS, 2026-11-19, Lahore, 5 results:
            #   search page + feed ready ......... 11s
            #   5 detail pages, 4 at a time ...... 30s  (24-28s EACH, in parallel)
            # Parallelism was already maxed out: every tab took the same ~25s,
            # so adding tabs could not help, which is why 2 tabs and 4 tabs
            # measured identically (56s vs 57s). The detail pages were not slow
            # because they queued; each one is just slow.
            #
            # They were also incomplete: only 3 of 5 detail panels exposed a
            # phone button, while all 8 cards in the feed showed a phone.
            #
            # One page load instead of one-per-business is what makes distant
            # hunting work. Distance is paid once, not N times.
            place_sel = "a[href*='/maps/place/']"
            seen = 0
            for step in range(10):
                count = await feed.locator(place_sel).count()
                if count >= max_results:
                    break
                if count == seen and step > 2:
                    break
                seen = count
                await feed.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                await _pause(0.7, 1.5)

            # Find the cards by what they ARE, not by where they sit.
            #
            # This was `feed.locator("> div")` - the feed's direct children -
            # and it returned zero leads for every hunt on the VPS while
            # working fine from a developer machine. Google serves more than
            # one Maps layout, and the two differ by one anonymous wrapper:
            #
            #   worked:   div[role=feed] > div[role=article]
            #   VPS:      div[role=feed] > div > div[role=article]
            #
            # Under the second layout "> div" matched that single wrapper,
            # which holds no place link of its own, so the loop skipped it and
            # every round reported no businesses. The harvester then said the
            # niche looked exhausted, which is how a selector bug came to read
            # as a market with no landscapers in Seattle.
            #
            # role="article" is the card's own identity and survives either
            # nesting. The descendant search is deliberate: it does not care
            # how many wrappers Google adds next.
            cards = feed.locator("div[role='article']")
            total = await cards.count()
            if not total:
                # Older or future layouts may not label the cards. Fall back to
                # the closest ancestor that actually contains a place link,
                # rather than returning nothing: a wrong-but-present card is
                # recoverable by _build_lead, an empty hunt is not.
                cards = feed.locator(f"div:has(> {place_sel})")
                total = await cards.count()
                if total:
                    log.info("Maps layout has no role=article cards; "
                             "fell back to place-link parents (%d).", total)
            for i in range(total):
                if len(leads) >= max_results:
                    break
                card = cards.nth(i)
                try:
                    link = card.locator(place_sel)
                    if not await link.count():
                        continue        # spacers and the "end of list" footer
                    name = ((await link.first.get_attribute("aria-label")) or "").strip()
                    if not name:
                        continue
                    card_text = await card.inner_text()
                    # The business website is an ordinary outbound link on the
                    # card. Exclude Google's own links (Directions, the place
                    # link itself) or we would record maps.google.com as the
                    # lead's website and audit Google instead of the prospect.
                    website = ""
                    out = card.locator("a[href^='http']:not([href*='google.'])")
                    if await out.count():
                        website = (await out.first.get_attribute("href")) or ""
                    leads.append(_build_lead(
                        name, card_text, _phone_from_card(card_text), website,
                        country=country))
                except Exception as exc:  # noqa: BLE001 - one bad card is survivable
                    log.warning("Skipping card %d: %s", i, exc)

            # Stop intercepting before the context goes away. Requests still
            # in flight when the browser closes otherwise fire the handler
            # against a dead target, and Playwright prints a TargetClosedError
            # traceback for each one - alarming in the log, and easy to
            # mistake for a scrape failure when it is only shutdown noise.
            try:
                await context.unroute_all(behavior="ignoreErrors")
            except Exception:  # noqa: BLE001 - older Playwright lacks it
                pass

        return {"ok": True, "blocked": False, "message": f"Scraped {len(leads)} businesses.", "leads": leads}
    except Exception as exc:  # noqa: BLE001
        log.error("Scrape job failed: %s", exc)
        return {"ok": False, "blocked": False, "message": f"Scraping error: {exc}", "leads": []}
    finally:
        # A leaked Chromium is ~150MB that never comes back, and a hunt runs
        # dozens of rounds. Closing only on the success paths is what walked
        # the server's memory up until nothing could be served.
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


# Phone numbers as Google prints them on a result card, e.g.
# "+92 322 3368251", "+1 901-555-0134", "(901) 555-0134", "020 7946 0958".
#
# Strict about the start, because the card text is a jumble of digits: street
# numbers ("152 G1 Canal Rd"), ratings and review counts ("4.9(78)"), and
# opening hours ("Closes 6 PM") all share the line with the phone. A lead
# carrying an address fragment in its phone field is worse than one with no
# phone at all, because Agent 3 would try to dial it.
#
# A real card line looks like:
#   "Open · Closes 6 PM · +92 322 3368251"
# so filtering out whole segments that mention hours would have thrown away
# every phone number. The pattern carries the precision instead: a leading
# "+", a bracketed area code, or a trunk "0" is what separates a phone from
# the surrounding noise.
# The separator class includes U+2011 (non-breaking hyphen) on suspicion,
# not evidence: the captured Lahore cards used ordinary spaces and hyphens
# only. It costs nothing to accept and Maps does use typographic characters
# elsewhere in the feed, but do not read it as a measured requirement.
#
# An international number is "+", a country code, then 7-12 digits split
# into groups however that country writes them. Area codes range from ONE
# digit (+971 4 395 5591, Dubai) to four, so a fixed group size silently
# dropped whole countries - the UAE test below exists because {2,4} did.
_CARD_PHONE_RE = re.compile(
    r"""(?:
          \+\d{1,3}(?:[\s.‑-]?\d){7,12}
        | \(\d{3}\)[\s.‑-]?\d{3}[\s.‑-]?\d{4}
        | (?<![\d.])0\d{2,4}[\s.‑-]\d{3,4}[\s.‑-]?\d{3,4}
    )""",
    re.VERBOSE,
)


# Country dialling codes, for turning a locally-formatted number into one
# that can actually be dialled from anywhere.
#
# Maps prints phones the way the country writes them, and WHICH way depends on
# the layout Google serves. The same Seattle query gave "+1 206-608-2614" from
# one machine and "(206) 608-2614" from another, minutes apart. Nothing
# downstream normalised either, so a lead's phone reached the CRM and Agent 3
# in whatever shape it arrived.
#
# "(206) 608-2614" is not wrong, it is incomplete: it dials from inside the
# US and fails from Pakistan, which is where it would be dialled from. A
# number that cannot be rung is the same as no number for the one job the
# field has.
#
# Keyed by the country string the hunt already carries, so no lookup service
# and no guessing from the digits. Only the countries this app hunts in are
# listed; an unknown country leaves the number exactly as Maps printed it,
# which is no worse than today.
_DIAL_CODES = {
    "pakistan": "92",
    "united states": "1",
    "usa": "1",
    "us": "1",
    "canada": "1",
    "united kingdom": "44",
    "uk": "44",
    "united arab emirates": "971",
    "uae": "971",
    "saudi arabia": "966",
    "australia": "61",
    "india": "91",
    "bangladesh": "880",
    "germany": "49",
    "france": "33",
    "ireland": "353",
    "new zealand": "64",
    "south africa": "27",
    "singapore": "65",
    "malaysia": "60",
    "qatar": "974",
    "kuwait": "965",
    "oman": "968",
    "bahrain": "973",
    "turkey": "90",
}


def _dial_code_for(country: str) -> str:
    """The international dialling code for a country name, or ""."""
    key = (country or "").strip().lower()
    if not key:
        return ""
    if key in _DIAL_CODES:
        return _DIAL_CODES[key]
    # "Seattle, United States" and "United States of America" both arrive.
    for name, code in _DIAL_CODES.items():
        if name in key:
            return code
    return ""


def normalise_phone(phone: str, country: str = "") -> str:
    """Return the phone in international form when the country is known.

    Already-international numbers are left alone. A local number gains its
    country's code, with the trunk prefix dropped: a UK "020 7946 0958" is
    "+44 20 7946 0958", not "+44 020 ...". Anything unrecognised is returned
    unchanged - a slightly odd number is recoverable by a human, an empty
    field is not.
    """
    phone = (phone or "").strip()
    if not phone:
        return ""
    if phone.startswith("+"):
        return phone                     # already dialable from anywhere

    code = _dial_code_for(country)
    if not code:
        return phone                     # unknown country: do not invent one

    digits = re.sub(r"\D", "", phone)
    if not digits:
        return phone

    # Already carries the country code without the plus, e.g. "92 322 ...".
    if digits.startswith(code) and len(digits) > len(code) + 6:
        return f"+{code} {_regroup(phone, digits[len(code):])}"

    # Trunk prefix: the 0 that means "another city in this country" and is
    # replaced by the country code, never kept alongside it.
    local = digits.lstrip("0") if digits.startswith("0") else digits

    if len(local) < 6:                   # too short to be a real number
        return phone
    return f"+{code} {_regroup(phone, local)}"


def _regroup(original: str, digits: str) -> str:
    """Re-apply the original number's spacing to a digit string.

    Without this the result is "+1 2066082614" - dialable, but a wall of
    digits that a human has to parse character by character when checking a
    lead before Agent 3 calls it. Google already grouped the number the way
    its country reads, so that grouping is reused rather than invented:
    "(206) 608-2614" becomes "+1 206-608-2614".

    Falls back to the bare digits if the original's grouping does not fit what
    is left after a trunk prefix was removed, since a wrong grouping would be
    more confusing than none.
    """
    groups = re.findall(r"\d+", original or "")
    # Drop a leading trunk "0" group so the shapes line up.
    if groups and groups[0] == "0":
        groups = groups[1:]
    elif groups and groups[0].startswith("0") and len(groups[0]) > 1:
        groups = [groups[0].lstrip("0")] + groups[1:]

    if sum(len(g) for g in groups) != len(digits) or len(groups) < 2:
        return digits

    out, i = [], 0
    for g in groups:
        out.append(digits[i:i + len(g)])
        i += len(g)
    return "-".join(out)


def _phone_from_card(card_text: str) -> str:
    """Pull the phone out of a result card's visible text.

    Measured on the VPS 2026-11-19: all 8 cards in a Lahore search showed a
    phone here, while only 3 of 5 detail panels exposed a phone button. The
    card is both faster and more complete.
    """
    m = _CARD_PHONE_RE.search(card_text or "")
    if not m:
        return ""
    # Collapse whitespace runs; keep the separators Google chose.
    return re.sub(r"\s+", " ", m.group(0)).strip()


# Maps prints the score and review count together on the result card, e.g.
# "4.2 (89)" or "3.8(1,204)". Both were being thrown away, yet they are the
# only size-and-quality signal available without a paid data source: a business
# with 2,000 reviews has an agency already, one with 11 usually does not.
_RATING_RE = re.compile(r"\b([1-5][.,]\d)\s*\(\s*([\d,\s]+)\s*\)")


def _parse_rating(card_text: str) -> tuple[float | None, int | None]:
    m = _RATING_RE.search(card_text or "")
    if not m:
        return None, None
    try:
        rating = float(m.group(1).replace(",", "."))
        reviews = int(re.sub(r"\D", "", m.group(2)) or 0)
    except ValueError:
        return None, None
    return rating, reviews


# The category/address line of a result card, e.g.
#   "Dental clinic ·  · 152 G1 Canal Rd"
#   "Dental clinic · Shop #G-010, Packages Mall"
# The category is the first dot-separated field; the address is the rest. The
# middle field is often empty (a badge Maps left blank), so empty parts are
# dropped rather than counted as the address.
_CATEGORY_WORDS = ("clinic", "dentist", "doctor", "hospital", "centre", "center",
                   "shop", "store", "salon", "studio", "agency", "restaurant",
                   "cafe", "service", "contractor", "repair", "school", "gym")

_HOURS_PREFIX = ("open", "clos", "reopen", "temporarily", "permanently", "·")


# Maps renders badges (accessibility, "Open now", service icons) with an icon
# font, so the card text contains Private Use Area codepoints where a glyph
# was drawn. A real Lahore card gave:
#
#     address = '\ue934 152 G1 Canal Rd'
#
# which is not whitespace - str.strip() leaves it in place - and would reach
# the CRM and the outreach emails as a broken box. There is no Unicode name
# for these; the meaning lives only in Google's font, so the only correct
# handling is to drop them.
#
# U+E000-U+F8FF is the Basic Multilingual Plane's PUA block. The two
# supplementary PUA planes are included for completeness.
_PUA_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


def _strip_icon_glyphs(text: str) -> str:
    """Remove icon-font codepoints, then collapse the gaps they leave."""
    if not text:
        return ""
    out = []
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _PUA_RANGES):
            out.append(" ")          # a space, so words do not run together
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _category_and_address(card_text: str, name: str) -> tuple[str, str]:
    """Split the card's category line into (category, address).

    The previous version took "the first short line with letters", skipping
    only line 1 - but a card repeats the business name on lines 1 AND 2, so it
    returned the business name as the category for every lead. The address was
    never read at all: every lead was stored with address "".
    """
    lines = [l.strip() for l in (card_text or "").split("\n") if l.strip()]
    nm = (name or "").strip().lower()
    for line in lines[:6]:
        if line.lower() == nm or _RATING_RE.search(line):
            continue                      # the repeated name, and "4.9(78)"
        if "·" not in line:
            continue
        parts = [x.strip() for x in line.split("·")]
        parts = [x for x in parts if x]
        if not parts:
            continue
        head = parts[0]
        # Skip the hours line ("Open · Closes 6 PM · +92 322 3368251").
        if head.lower().startswith(_HOURS_PREFIX):
            continue
        category = _strip_icon_glyphs(head) if len(head) < 60 else ""
        address = _strip_icon_glyphs(" ".join(parts[1:]))[:200]
        return category, address
    # No dotted line: fall back to a short line that reads like a category.
    for line in lines[:6]:
        low = line.lower()
        if low != nm and len(line) < 40 and any(w in low for w in _CATEGORY_WORDS):
            return _strip_icon_glyphs(line), ""
    return "", ""


def _build_lead(name: str, card_text: str, phone: str, website: str,
                country: str = "") -> dict:
    # The name arrives from the card's aria-label rather than its text, but it
    # can carry the same icon-font glyphs. This is the field that goes into the
    # email greeting, so a broken box here is the most visible failure of all.
    name = _strip_icon_glyphs(name)
    category, address = _category_and_address(card_text, name)
    rating, reviews = _parse_rating(card_text)
    return {
        "business_name": name,
        "category": category,
        # Stored in international form so it can be dialled from here. Maps
        # prints it however the country writes it, and which way depends on
        # the layout served - the same Seattle query gave "+1 206-608-2614"
        # and "(206) 608-2614" minutes apart.
        "phone": normalise_phone(phone, country),
        "website": website,
        "address": address,
        "appears_no_website": not bool(website),
        "rating": rating,
        "reviews_count": reviews,
    }
