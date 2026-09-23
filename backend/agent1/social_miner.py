"""Find businesses that exist only on Facebook or Instagram.

The whole pipeline assumed a business has a website: Google Maps gives the
phone, the crawler reads the site. That misses a large part of the Pakistani
market — shops, salons, small manufacturers and traders who run everything
from a Facebook page and never registered on Maps at all.

They are also the BEST prospects we can find. "No website at all" is the
strongest pitch in the audit scoring, and there is no incumbent developer to
displace. A business with a working site is a harder sell than one with none.

How this works, and why:

  * Facebook blocks scraping outright — both www and mbasic return 400 to a
    plain HTTP client. So we never fetch Facebook directly. Search engines
    index those pages perfectly well, so we read the search results instead.
  * Instagram does answer (HTTP 200) and its profile HTML carries a phone
    number for business accounts, so those are fetched directly.
  * The output is a WhatsApp lead, not an email lead. These businesses rarely
    publish an email, but they always answer a phone — and WhatsApp is how
    business is actually done here.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus

import httpx

from shared.logger import get_logger

log = get_logger("agent1.social_miner")

_UA = {
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "accept": "text/html,application/xhtml+xml",
    "accept-language": "en-US,en;q=0.9",
}
_TIMEOUT = 20.0

# Facebook page handles that are site furniture rather than a business.
_FB_NON_PAGES = {
    "sharer", "tr", "profile", "people", "pages", "login", "dialog", "help",
    "privacy", "policies", "legal", "terms", "settings", "groups", "events",
    "marketplace", "watch", "gaming", "business", "ads", "about", "careers",
    "home", "recover", "reg", "photo", "video", "story", "permalink",
    "sharer.php", "plugins", "connect", "l.php", "flx", "hashtag",
}

# Pakistani numbers: mobile is 03xx-xxxxxxx, landline 0xx-xxxxxxx, and both
# appear with or without the +92 country code.
_PHONE_RE = re.compile(
    r"(?:\+?92|0092)?[\s\-.]?(3\d{2})[\s\-.]?(\d{7})"      # mobile
    r"|(?:\+?92|0092)?[\s\-.]?(\d{2,4})[\s\-.]?(\d{6,8})"  # landline
)

# Numbers that are obviously placeholders, not real contacts. Instagram's HTML
# carries several of these in its own scripts.
_FAKE_NUMBERS = {"3456000000", "1234567890", "0000000000", "1111111111",
                 "3001234567", "9999999999", "1234567", "0000000"}


def _clean_phone(raw: str) -> str:
    """Normalise to digits, or "" when it is not a plausible PK number."""
    digits = re.sub(r"\D", "", raw or "")
    digits = digits.lstrip("0")
    if digits.startswith("92"):
        digits = digits[2:]
    if not digits or digits in _FAKE_NUMBERS:
        return ""
    # A Pakistani mobile is 3XXXXXXXXX (10 digits after the country code).
    if len(digits) == 10 and digits.startswith("3"):
        if digits in _FAKE_NUMBERS:
            return ""
        return f"92{digits}"
    # Landlines: 9-11 digits including the city code. Kept, but they are not
    # WhatsApp-reachable, so the caller decides what to do with them.
    if 9 <= len(digits) <= 11:
        return f"92{digits}"
    return ""


def _extract_phones(text: str, limit: int = 4) -> list[str]:
    out: list[str] = []
    for m in _PHONE_RE.finditer(text or ""):
        phone = _clean_phone(m.group(0))
        if phone and phone not in out:
            out.append(phone)
            if len(out) >= limit:
                break
    return out


def _clean_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw or "").strip(" -|·—")
    # Strip the platform suffix search engines append.
    name = re.split(r"\s*[|\-–—]\s*(?:Facebook|Instagram|Home)\b", name, flags=re.I)[0]
    name = re.sub(r"\s*\(\d+\)\s*$", "", name)          # "(12)" notification count
    return name.strip()[:120]


async def _search(client: httpx.AsyncClient, query: str) -> str:
    """Search for a query, trying each engine until one answers usefully.

    Both engines throttle: DuckDuckGo starts returning HTTP 202 with an empty
    result body after a burst, and Yahoo intermittently answers 500 to the same
    request that succeeds on retry. Neither is reliable alone, so try both and
    treat a 202 as a failure — it looks like success but carries no results.
    """
    engines = (
        ("DuckDuckGo", f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"),
        ("Yahoo", f"https://search.yahoo.com/search?p={quote_plus(query)}"),
    )
    for name, url in engines:
        for attempt in (1, 2):
            try:
                r = await client.get(url)
                r.raise_for_status()
                # 202 = accepted but throttled; the body has no results in it.
                if r.status_code == 202 or len(r.text) < 6000:
                    raise httpx.HTTPError(f"throttled ({r.status_code})")
                return r.text
            except httpx.HTTPError as exc:
                if attempt == 2:
                    log.warning("%s search failed for %r: %s", name, query[:50], exc)
                else:
                    await asyncio.sleep(2.0)
    return ""


_ANCHOR = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.{0,200}?)</a>', re.I | re.S)
# DuckDuckGo wraps results as /l/?uddg=<url-encoded target>, so the handle has
# to be read after decoding rather than straight out of the href.
_FB_HANDLE = re.compile(r'facebook\.com(?:/pages)?/([A-Za-z0-9._-]{4,60})', re.I)
_IG_HANDLE = re.compile(r'instagram\.com/([A-Za-z0-9._]{3,40})', re.I)


def _parse_social(html: str, platform: str) -> list[dict]:
    """Business pages found in a search result page."""
    from urllib.parse import unquote

    out: list[dict] = []
    seen: set[str] = set()
    handle_re = _FB_HANDLE if platform == "facebook" else _IG_HANDLE
    for m in _ANCHOR.finditer(html or ""):
        href = unquote(unquote(m.group(1)))   # twice: DDG double-encodes some
        hit = handle_re.search(href)
        if not hit:
            continue
        handle = hit.group(1).strip("/.")
        if not handle or handle.lower() in _FB_NON_PAGES or handle.lower() in seen:
            continue
        if handle.isdigit():          # numeric ids are usually posts, not pages
            continue
        label = _clean_name(re.sub(r"<[^>]+>", " ", m.group(2)))
        if not label or len(label) < 3:
            continue
        seen.add(handle.lower())
        out.append({
            "handle": handle,
            "business_name": label,
            "profile_url": (f"https://www.facebook.com/{handle}" if platform == "facebook"
                            else f"https://www.instagram.com/{handle}/"),
            "platform": platform,
        })
    return out


async def _instagram_phone(client: httpx.AsyncClient, handle: str) -> str:
    """Instagram answers HTTP 200 and business profiles expose a phone."""
    try:
        r = await client.get(f"https://www.instagram.com/{handle}/")
        if r.status_code != 200:
            return ""
        phones = _extract_phones(r.text, limit=3)
        return phones[0] if phones else ""
    except httpx.HTTPError:
        return ""


async def discover_social_businesses(niche: str, where: str = "",
                                     max_results: int = 30) -> dict:
    """Businesses running on Facebook/Instagram rather than a website.

    Returns {ok, leads:[...]}. Each lead has no website by definition, which
    the site auditor treats as the strongest possible pitch.
    """
    place = (where or "").strip()
    n = (niche or "").strip()
    if not n:
        return {"ok": False, "error": "No niche given.", "leads": []}

    queries = [
        f"site:facebook.com {n} {place}".strip(),
        f"site:facebook.com {n} {place} contact number".strip(),
        f"facebook page {n} {place} whatsapp".strip(),
        f"site:instagram.com {n} {place}".strip(),
        f"{n} {place} facebook page no website".strip(),
    ]

    found: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT), headers=_UA,
                                 follow_redirects=True) as client:
        for query in queries:
            if len(found) >= max_results:
                break
            html = await _search(client, query)
            if not html:
                continue
            platform = "instagram" if "instagram.com" in query else "facebook"
            # A phone often sits in the result snippet itself, which costs
            # nothing to read and saves a profile fetch.
            snippet_phones = _extract_phones(re.sub(r"<[^>]+>", " ", html), limit=12)

            for item in _parse_social(html, platform):
                key = item["handle"].lower()
                if key in found:
                    continue
                found[key] = {**item, "phone": ""}
                if len(found) >= max_results:
                    break
            # Assign snippet phones only when we found exactly one page in the
            # page, otherwise we cannot tell which number belongs to whom.
            if len(snippet_phones) == 1 and len(found) == 1:
                only = next(iter(found.values()))
                only["phone"] = only["phone"] or snippet_phones[0]
            await asyncio.sleep(1.0)

        # Instagram profiles are fetchable, so fill missing numbers from there.
        ig = [v for v in found.values() if v["platform"] == "instagram" and not v["phone"]]
        for item in ig[:15]:
            item["phone"] = await _instagram_phone(client, item["handle"])
            await asyncio.sleep(0.8)

    leads = []
    for item in found.values():
        leads.append({
            "business_name": item["business_name"],
            "phone": f"+{item['phone']}" if item["phone"] else "",
            "website": "",                       # the entire point: they have none
            "appears_no_website": True,
            "social_url": item["profile_url"],
            "social_platform": item["platform"],
            "source": "agent1_social_miner",
            "discovery_source": f"{item['platform']}_search",
            "category": niche,
        })
    with_phone = sum(1 for l in leads if l["phone"])
    log.info("Social miner: %d pages for %r (%d with a phone).", len(leads), n, with_phone)
    return {"ok": True, "leads": leads,
            "message": f"Found {len(leads)} social-only businesses, {with_phone} with a phone."}
