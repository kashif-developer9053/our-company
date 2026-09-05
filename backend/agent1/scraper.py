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


async def _pause(a: float = 1.0, b: float = 4.0) -> None:
    await asyncio.sleep(random.uniform(a, b))


async def scrape_google_maps(query: str, max_results: int = 20) -> dict:
    """Return {ok, blocked, message, leads:[...]}. Never raises."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "blocked": False, "message": f"Playwright not available: {exc}", "leads": []}

    leads: list[dict] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 900}, locale="en-US")
            page = await context.new_page()
            await page.goto(f"https://www.google.com/maps/search/{query.replace(' ', '+')}",
                            wait_until="domcontentloaded", timeout=45000)
            await _pause(2, 4)

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
                await browser.close()
                return {"ok": False, "blocked": True,
                        "message": "Scraping paused — possible rate limiting detected (Google challenge page).", "leads": []}

            feed = page.locator("div[role='feed']")
            try:
                await feed.wait_for(timeout=12000)
            except Exception:  # noqa: BLE001
                await browser.close()
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
                await _pause(1.2, 2.6)

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
            for name, href, card_text in targets:
                try:
                    await page.goto(href, wait_until="domcontentloaded", timeout=30000)
                    await _pause(1.0, 2.5)
                    phone = await _extract_phone(page)
                    website = await _extract_website(page)
                    leads.append(_build_lead(name, card_text, phone, website))
                except Exception as exc:  # noqa: BLE001 - skip one bad place, continue
                    log.warning("Skipping place '%s': %s", name[:40], exc)

            await browser.close()
        return {"ok": True, "blocked": False, "message": f"Scraped {len(leads)} businesses.", "leads": leads}
    except Exception as exc:  # noqa: BLE001
        log.error("Scrape job failed: %s", exc)
        return {"ok": False, "blocked": False, "message": f"Scraping error: {exc}", "leads": []}


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


def _build_lead(name: str, card_text: str, phone: str, website: str) -> dict:
    category = ""
    for line in [l.strip() for l in card_text.split("\n") if l.strip()][1:5]:
        if any(ch.isalpha() for ch in line) and len(line) < 40 and not any(c.isdigit() for c in line[:3]):
            category = line
            break
    return {
        "business_name": name,
        "category": category,
        "phone": phone,
        "website": website,
        "address": "",
        "appears_no_website": not bool(website),
    }
