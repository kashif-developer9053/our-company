"""Agent 1 real scraping — Google Maps business search via Playwright.

Respectful behavior: randomized delays, a capped batch per run, a realistic
user-agent, gradual scrolling, and graceful per-result failure handling. If
Google blocks/rate-limits or shows a consent/CAPTCHA wall, we detect it, stop
cleanly, and report it (the caller sets Agent 1 to "error").

Strategy: collect place links from the results feed, then open each place to
read the publicly-shown phone/website/address from its detail panel.
"""

from __future__ import annotations

import asyncio
import random
import re

from shared.logger import get_logger

log = get_logger("agent1.scraper")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


# How many business detail pages to read at once. Each is an independent URL,
# so waiting for them one at a time was pure latency: the server sat idle
# between round trips to Google.
#
# Measured on the VPS against Lahore, 5 results, three runs each:
#   css blocked, 4 tabs ... [60, 47, 42]  avg 50s
#   css allowed, 4 tabs ... [40, 43, 44]  avg 42s   <- kept
#   css allowed, 2 tabs ... [42, 61, 41]  avg 48s
#
# Four tabs beat two, so the earlier guess that a small VPS would contend on
# renderer processes was wrong — the time is spent waiting on Google, not on
# CPU, and more overlap helps.
#
# Read the spread, not just the average: one run of the last config took 61s
# while two took ~41s. Google's own variance is ±20s, wider than the gap
# between these settings, so treat 42 vs 48 as "no worse" rather than proof.
# Anything tuned here needs three runs minimum, or it is noise.
_DETAIL_CONCURRENCY = 4

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


async def scrape_google_maps(query: str, max_results: int = 20) -> dict:
    """Return {ok, blocked, message, leads:[...]}. Never raises."""
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
            context = await browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 900}, locale="en-US")

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
                            wait_until="domcontentloaded", timeout=45000)
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
                await feed.wait_for(timeout=12000)
            except Exception:  # noqa: BLE001
                if "google.com/maps" not in page.url:
                    return {"ok": False, "blocked": True, "message": "Scraping paused — redirected away from Maps (possible block).", "leads": []}
                return {"ok": True, "blocked": False, "message": "No results feed found (0 businesses).", "leads": []}

            # Collect place links + names (scroll gradually to load more).
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

            anchors = feed.locator(place_sel)
            n = min(await anchors.count(), max_results)
            targets = []
            for i in range(n):
                a = anchors.nth(i)
                name = ((await a.get_attribute("aria-label")) or "").strip()
                href = (await a.get_attribute("href")) or ""
                # Category/address are visible on the list card already.
                card_text = ""
                try:
                    card_text = await a.locator("xpath=../..").inner_text()
                except Exception:  # noqa: BLE001
                    pass
                if name and href:
                    targets.append((name, href, card_text))

            # Visit each place to read phone + website from the detail panel.
            #
            # These were done strictly one after another on a single tab, so
            # 20 businesses meant 20 sequential page loads plus 20 pauses —
            # the bulk of the 39s a Lahore search took, and the reason a
            # Memphis search never finished. They are independent reads of
            # independent URLs, so they run in parallel now, a few tabs at a
            # time.
            #
            # _DETAIL_CONCURRENCY is deliberately modest: the point is to stop
            # waiting on round trips, not to hammer Google. Four tabs is a
            # browser with four tabs open, which is what a person has.
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

            async def _detail(name: str, href: str, card_text: str):
                async with sem:
                    tab = None
                    try:
                        tab = await context.new_page()
                        await tab.goto(href, wait_until="domcontentloaded", timeout=30000)
                        await _pause(0.3, 0.8)
                        phone = await _extract_phone(tab)
                        website = await _extract_website(tab)
                        return _build_lead(name, card_text, phone, website)
                    except Exception as exc:  # noqa: BLE001 - one bad place is survivable
                        log.warning("Skipping place '%s': %s", name[:40], exc)
                        return None
                    finally:
                        # A leaked tab is a leaked renderer process. With dozens
                        # of rounds a hunt would walk the server's memory up.
                        if tab is not None:
                            try:
                                await tab.close()
                            except Exception:  # noqa: BLE001
                                pass

            results = await asyncio.gather(
                *(_detail(n, h, c) for n, h, c in targets),
                return_exceptions=True)
            leads.extend(r for r in results if isinstance(r, dict))

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


async def _extract_phone(page) -> str:
    try:
        btn = page.locator("button[data-item-id^='phone']")
        if await btn.count():
            label = (await btn.first.get_attribute("aria-label")) or ""
            m = re.search(r"(\+?[\d][\d\s().-]{6,}\d)", label)
            if m:
                return m.group(1).strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


async def _extract_website(page) -> str:
    try:
        a = page.locator("a[data-item-id='authority']")
        if await a.count():
            return (await a.first.get_attribute("href")) or ""
    except Exception:  # noqa: BLE001
        pass
    return ""


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


def _build_lead(name: str, card_text: str, phone: str, website: str) -> dict:
    category = ""
    for line in [l.strip() for l in card_text.split("\n") if l.strip()][1:5]:
        if any(ch.isalpha() for ch in line) and len(line) < 40 and not any(c.isdigit() for c in line[:3]):
            category = line
            break
    rating, reviews = _parse_rating(card_text)
    return {
        "business_name": name,
        "category": category,
        "phone": phone,
        "website": website,
        "address": "",
        "appears_no_website": not bool(website),
        "rating": rating,
        "reviews_count": reviews,
    }
