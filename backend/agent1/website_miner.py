"""Built-in SME website discovery and public contact extraction.

This crawler is owned by the application. It uses ordinary HTTP requests and
deterministic HTML parsing only: no Claude, NVIDIA, LLM, paid search API, or
third-party crawling service is involved. Every accepted contact keeps the
public page URL where it was found.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from shared.logger import get_logger

log = get_logger("agent1.website_miner")

_USER_AGENT = "AI-Agency-SME-Crawler/1.0"
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_MAILTO_RE = re.compile(r"href\s*=\s*[\"']mailto:([^\"'?#]+)", re.I)
_TEL_RE = re.compile(r"href\s*=\s*[\"']tel:([^\"'?#]+)", re.I)
_CF_EMAIL_RE = re.compile(r"data-cfemail\s*=\s*[\"']([0-9a-f]{6,})[\"']", re.I)
_PHONE_RE = re.compile(r"(?:\+|00)?\d[\d\s().-]{5,}\d")
_PHONE_CONTEXT_RE = re.compile(r"\b(?:phone|tel|telephone|call|mobile|whatsapp)\b", re.I)
_ADDRESS_CONTEXT_RE = re.compile(r"\b(?:address|head office|registered office|branch|showroom|location)\b", re.I)
_ADDRESS_TOKEN_RE = re.compile(
    r"\b(?:road|rd\.?|street|st\.?|avenue|ave\.?|lane|boulevard|building|plaza|floor|suite|unit|block|sector|phase|estate|park|zone|highway|chowk|area)\b",
    re.I,
)
_AT_RE = re.compile(r"\s*(?:\[at\]|\(at\)|\s+at\s+)\s*", re.I)
_DOT_RE = re.compile(r"\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*", re.I)
_CONTACT_HINTS = (
    "contact", "get-in-touch", "reach", "support", "enquiry", "enquiries",
    "about", "team", "location", "branch", "office", "connect",
)
_PREFERRED_LOCALS = ("info", "contact", "hello", "office", "admin", "accounts", "sales", "support")
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "proton.me", "protonmail.com",
}
_PLACEHOLDER_DOMAINS = {"example.com", "email.com", "domain.com", "yourdomain.com"}
_BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_NO_REPLY_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply"}
_EXCLUDED_DISCOVERY_DOMAINS = {
    "duckduckgo.com", "google.com", "bing.com", "facebook.com", "instagram.com",
    "linkedin.com", "youtube.com", "x.com", "twitter.com", "pinterest.com",
    "wikipedia.org", "yelp.com", "tripadvisor.com", "yellowpages.com",
}
_DIRECTORY_DOMAIN_HINTS = (
    "directory", "yellowpage", "businesslist", "infomedia", "kompass",
    "listing", "lookup", "clutch", "ensun", "dnb", "aeroleads", "urdupoint",
)
_DIRECTORY_PATH_HINTS = ("/listing-category/", "/category/", "/directory/", "/business-directory/", "/list/")
_GENERIC_PAGE_TITLES = {
    "home", "homepage", "welcome", "contact", "contact us", "about", "about us",
    "get in touch", "our company", "official website",
}
_LISTING_TITLE_RE = re.compile(
    r"\b(?:list of|business directory|company directory|directory of|top\s+\d+|best\s+\w+\s+companies|companies in)\b",
    re.I,
)
_MAX_SEARCH_RESULTS = 20
_MAX_PAGES_PER_SITE = 5
_MAX_BODY_BYTES = 2_000_000
_MAX_REDIRECTS = 4
_MAX_SITE_CONCURRENCY = 3
_SEARCH_TIMEOUT = 15.0
_PAGE_TIMEOUT = 20.0
_POLITE_DELAY_SECONDS = 0.6
_MAX_BROWSER_FALLBACK_SITES = 3
_MAX_BROWSER_PAGES_PER_SITE = 2


@dataclass
class CrawledPage:
    url: str
    html: str
    visible_text: str
    title: str
    links: list[dict[str, str]]
    json_ld: list[str]
    addresses: list[str]
    forms: list[str]
    structured_values: list[dict[str, str]]


class _PageParser(HTMLParser):
    """Small parser for visible text, links, forms, and structured contacts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.json_ld: list[str] = []
        self.addresses: list[str] = []
        self.forms: list[str] = []
        self.structured_values: list[dict[str, str]] = []
        self._hidden_depth = 0
        self._in_title = False
        self._anchor: dict[str, Any] | None = None
        self._json_ld_parts: list[str] | None = None
        self._address_depth = 0
        self._address_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "script" and "ld+json" in values.get("type", "").lower():
            self._json_ld_parts = []
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._hidden_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._anchor = {"href": values.get("href", ""), "class": values.get("class", ""), "text_parts": []}
        if tag == "address":
            self._address_depth += 1
            if self._address_depth == 1:
                self._address_parts = []
        if tag == "form":
            self.forms.append(values.get("action", ""))
        itemprop = values.get("itemprop", "").lower()
        structured_value = values.get("content", "") or values.get("href", "")
        if itemprop and structured_value:
            self.structured_values.append({"itemprop": itemprop, "value": structured_value})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "template"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag == "script" and self._json_ld_parts is not None:
            raw = "".join(self._json_ld_parts).strip()
            if raw:
                self.json_ld.append(raw)
            self._json_ld_parts = None
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._anchor is not None:
            self.links.append({
                "href": self._anchor["href"],
                "class": self._anchor["class"],
                "text": " ".join(" ".join(self._anchor["text_parts"]).split()),
            })
            self._anchor = None
        if tag == "address" and self._address_depth:
            self._address_depth -= 1
            if self._address_depth == 0:
                value = " ".join(" ".join(self._address_parts).split())
                if value:
                    self.addresses.append(value)
                self._address_parts = []

    def handle_data(self, data: str) -> None:
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if not self._hidden_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self.text_parts.append(cleaned)
                if self._anchor is not None:
                    self._anchor["text_parts"].append(cleaned)
                if self._address_depth:
                    self._address_parts.append(cleaned)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_url(raw: str) -> str:
    value = html.unescape((raw or "").strip())
    if value.startswith("//"):
        value = f"https:{value}"
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or port not in (None, 80, 443):
        return ""
    return parsed._replace(fragment="").geturl()


def _domain(url: str) -> str:
    host = (urlparse(_normalise_url(url)).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _same_domain(left: str, right: str) -> bool:
    a, b = _domain(left), _domain(right)
    return bool(a and b) and (a == b or a.endswith(f".{b}") or b.endswith(f".{a}"))


async def _is_public_url(url: str) -> bool:
    parsed = urlparse(_normalise_url(url))
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443)
        ips = {ipaddress.ip_address(item[4][0]) for item in addresses}
    except (OSError, ValueError):
        return False
    return bool(ips) and all(ip.is_global for ip in ips)


def _unwrap_search_url(href: str) -> str:
    raw = unquote((href or "").strip())
    if raw.startswith("//"):
        raw = f"https:{raw}"
    parsed = urlparse(raw)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        raw = unquote(parse_qs(parsed.query).get("uddg", [""])[0])
    return _normalise_url(raw)


def _unwrap_yahoo_url(href: str) -> str:
    raw = html.unescape((href or "").strip())
    if "r.search.yahoo.com" in raw and "/RU=" in raw:
        raw = unquote(raw.split("/RU=", 1)[1].split("/RK=", 1)[0])
    return _normalise_url(raw)


def _excluded_discovery_url(url: str) -> bool:
    domain = _domain(url)
    path = urlparse(url).path.lower()
    if not domain:
        return True
    if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in _EXCLUDED_DISCOVERY_DOMAINS):
        return True
    return any(hint in domain for hint in _DIRECTORY_DOMAIN_HINTS) or any(hint in path for hint in _DIRECTORY_PATH_HINTS)


def _clean_business_name(title: str, url: str) -> str:
    value = re.sub(r"\s+", " ", (title or "")).strip()
    parts = [part.strip() for part in re.split(r"\s(?:\||-|\u2013|\u2014|::)\s", value) if part.strip()]
    candidate = next((part for part in parts if part.lower() not in _GENERIC_PAGE_TITLES), "")
    if candidate:
        return candidate[:160]
    host = _domain(url).split(".", 1)[0].replace("-", " ").replace("_", " ")
    return host.title()[:160]


def _looks_like_listing(title: str, url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(_LISTING_TITLE_RE.search(title or "")) or any(
        marker in path for marker in ("/business-directory/", "/company-directory/", "/list-of-")
    )


def _structured_business_name(result: Any) -> str:
    """Prefer an explicit Organization/LocalBusiness name from JSON-LD."""
    accepted_types = {
        "organization", "localbusiness", "corporation", "store", "professionalservice",
        "financialservice", "accountingservice", "manufacturer",
    }
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        raw_types = node.get("@type", [])
        types = {str(value).lower() for value in _iter_values(raw_types)}
        name = " ".join(str(node.get("name", "")).split())
        if types.intersection(accepted_types) and 2 <= len(name) <= 160 and not _LISTING_TITLE_RE.search(name):
            found.append(name)
        for child in node.values():
            walk(child)

    for raw in getattr(result, "json_ld", []) or []:
        try:
            walk(json.loads(raw.strip().removeprefix("<!--").removesuffix("-->")))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return min(found, key=len) if found else ""


def _parse_html(url: str, page_html: str) -> CrawledPage:
    parser = _PageParser()
    try:
        parser.feed(page_html)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        log.debug("HTML parser recovered from malformed markup at %s: %s", url, exc)
    return CrawledPage(
        url=url,
        html=page_html,
        visible_text="\n".join(parser.text_parts),
        title=" ".join(" ".join(parser.title_parts).split()),
        links=parser.links,
        json_ld=parser.json_ld,
        addresses=parser.addresses,
        forms=parser.forms,
        structured_values=parser.structured_values,
    )


def _parse_search_results(page_html: str) -> list[dict]:
    page = _parse_html("https://html.duckduckgo.com/", page_html)
    results: list[dict] = []
    seen: set[str] = set()
    for anchor in page.links:
        if "result__a" not in anchor.get("class", "").split():
            continue
        url = _unwrap_search_url(anchor.get("href", ""))
        domain = _domain(url)
        if not url or not domain:
            continue
        if _excluded_discovery_url(url):
            continue
        if _looks_like_listing(anchor.get("text", ""), url):
            continue
        if domain in seen:
            continue
        seen.add(domain)
        results.append({
            "url": url,
            "business_name": _clean_business_name(anchor.get("text", ""), url),
            "discovery_source": "duckduckgo_web_search",
        })
    return results


def _parse_yahoo_results(page_html: str) -> list[dict]:
    page = _parse_html("https://search.yahoo.com/", page_html)
    results: list[dict] = []
    seen: set[str] = set()
    for anchor in page.links:
        classes = anchor.get("class", "").split()
        if not {"d-ib", "va-top", "mt-38"}.issubset(classes):
            continue
        url = _unwrap_yahoo_url(anchor.get("href", ""))
        domain = _domain(url)
        if not url or not domain or domain in seen or _excluded_discovery_url(url) or _looks_like_listing(anchor.get("text", ""), url):
            continue
        seen.add(domain)
        results.append({
            "url": url,
            "business_name": _clean_business_name(anchor.get("text", ""), url),
            "discovery_source": "yahoo_web_search",
        })
    return results


async def discover_business_websites(
    query: str,
    max_results: int = _MAX_SEARCH_RESULTS,
    seed_urls: list[str] | None = None,
) -> dict:
    """Find direct business websites without a paid search or AI API."""
    limit = max(1, min(max_results, _MAX_SEARCH_RESULTS))
    found: list[dict] = []
    seen: set[str] = set()

    for raw_url in seed_urls or []:
        url = _normalise_url(raw_url)
        domain = _domain(url)
        if not url or not domain or domain in seen or not await _is_public_url(url):
            continue
        seen.add(domain)
        found.append({"url": url, "business_name": _clean_business_name("", url), "discovery_source": "manual_seed"})
        if len(found) >= limit:
            return {"ok": True, "websites": found, "message": f"Prepared {len(found)} business websites."}

    searches = (f"{query} business contact", f"{query} company email")
    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_7_8) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(_SEARCH_TIMEOUT), headers=headers, follow_redirects=True) as client:
        for search in searches:
            sources = (
                ("DuckDuckGo", f"https://html.duckduckgo.com/html/?q={quote_plus(search)}", _parse_search_results),
                ("Yahoo", f"https://search.yahoo.com/search?p={quote_plus(search)}", _parse_yahoo_results),
            )
            for source_name, url, parser in sources:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    log.warning("%s website discovery query failed: %s", source_name, exc)
                    continue
                for item in parser(response.text):
                    domain = _domain(item["url"])
                    if domain in seen or not await _is_public_url(item["url"]):
                        continue
                    seen.add(domain)
                    found.append(item)
                    if len(found) >= limit:
                        return {"ok": True, "websites": found, "message": f"Discovered {len(found)} business websites."}
    return {
        "ok": True,
        "websites": found,
        "message": f"Discovered {len(found)} business websites." if found else "No independent business websites were discovered.",
    }


def _usable_email(raw: str, website_domain: str, allow_external: bool = False) -> str:
    email_value = raw.strip(" \t\r\n.,;:()[]<>\"'").lower()
    if not _EMAIL_RE.fullmatch(email_value) or email_value.endswith(_BAD_EMAIL_SUFFIXES):
        return ""
    local, domain = email_value.rsplit("@", 1)
    if local in _NO_REPLY_LOCALS or domain in _PLACEHOLDER_DOMAINS:
        return ""
    belongs_to_site = domain == website_domain or domain.endswith(f".{website_domain}")
    if not allow_external and not belongs_to_site and domain not in _FREE_EMAIL_DOMAINS:
        return ""
    return email_value


def _email_rank(email_value: str, website_domain: str) -> tuple[int, int, str]:
    local, domain = email_value.rsplit("@", 1)
    domain_rank = 0 if domain == website_domain or domain.endswith(f".{website_domain}") else 1
    try:
        local_rank = _PREFERRED_LOCALS.index(local)
    except ValueError:
        local_rank = len(_PREFERRED_LOCALS)
    return domain_rank, local_rank, email_value


def _valid_phone(raw: str) -> str:
    phone = unquote(raw).strip(" \t\r\n.,;:()[]<>\"'")
    digits = re.sub(r"\D", "", phone)
    return phone if 7 <= len(digits) <= 15 else ""


def _phone_key(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return digits[2:] if digits.startswith("00") else digits


def _decode_cf_email(encoded: str) -> str:
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except (ValueError, IndexError):
        return ""


def _deobfuscate_emails(text: str) -> str:
    return _DOT_RE.sub(".", _AT_RE.sub("@", html.unescape(text)))


def _page_text(result: Any) -> str:
    return "\n".join(
        part for part in (
            getattr(result, "html", "") or "",
            getattr(result, "visible_text", "") or "",
            getattr(result, "cleaned_html", "") or "",
            getattr(result, "markdown", "") or "",
        ) if isinstance(part, str) and part
    )


_SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
}


def _social_platform(raw_url: str) -> tuple[str, str]:
    url = _normalise_url(raw_url)
    host = _domain(url)
    if not url or not host:
        return "", ""
    for social_host, platform in _SOCIAL_HOSTS.items():
        if host == social_host or host.endswith(f".{social_host}"):
            path = urlparse(url).path.lower()
            if any(part in path for part in ("/share", "/sharer", "/intent", "/login")):
                return "", ""
            return platform, url
    return "", ""


def _whatsapp_contact(raw_url: str) -> tuple[str, str]:
    raw = html.unescape((raw_url or "").strip())
    if raw.lower().startswith("whatsapp://"):
        number = parse_qs(urlparse(raw).query).get("phone", [""])[0]
        phone = _valid_phone(unquote(number))
        return (phone, raw) if phone else ("", "")
    url = _normalise_url(raw)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "wa.me" or host.endswith(".wa.me"):
        number = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"api.whatsapp.com", "web.whatsapp.com"}:
        number = parse_qs(parsed.query).get("phone", [""])[0]
    else:
        return "", ""
    phone = _valid_phone(unquote(number))
    return (phone, url) if phone else ("", "")


def _normalise_address(raw: str) -> str:
    value = " ".join(html.unescape(str(raw or "")).split()).strip(" ,;|")
    return value[:400] if 8 <= len(value) <= 1000 else ""


def _address_from_json(value: Any) -> str:
    if isinstance(value, str):
        return _normalise_address(value)
    if not isinstance(value, dict):
        return ""
    fields = (
        "streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry",
    )
    country = value.get("addressCountry", "")
    if isinstance(country, dict):
        country = country.get("name", "")
    parts = [country if key == "addressCountry" else value.get(key, "") for key in fields]
    return _normalise_address(", ".join(str(part) for part in parts if part))


def _iter_values(value: Any):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield item
    else:
        yield value


def _structured_contacts(result: Any, website_domain: str) -> dict:
    contacts = {
        "emails": set(), "phones": set(), "fax_numbers": set(), "addresses": set(),
        "whatsapp": set(), "social_profiles": {},
    }

    def add_link(raw: str) -> None:
        phone, link = _whatsapp_contact(raw)
        if phone and link:
            contacts["whatsapp"].add((phone, link))
            return
        platform, social_url = _social_platform(raw)
        if platform and social_url:
            contacts["social_profiles"].setdefault(platform, set()).add(social_url)

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        for raw_key, value in node.items():
            key = str(raw_key).lower()
            if key == "email":
                for item in _iter_values(value):
                    email_value = _usable_email(str(item).removeprefix("mailto:"), website_domain, allow_external=True)
                    if email_value:
                        contacts["emails"].add(email_value)
            elif key in {"telephone", "phone", "mobilephone"}:
                for item in _iter_values(value):
                    phone = _valid_phone(str(item).removeprefix("tel:"))
                    if phone:
                        contacts["phones"].add(phone)
            elif key in {"faxnumber", "fax"}:
                for item in _iter_values(value):
                    phone = _valid_phone(str(item))
                    if phone:
                        contacts["fax_numbers"].add(phone)
            elif key == "address":
                for item in _iter_values(value):
                    address = _address_from_json(item)
                    if address:
                        contacts["addresses"].add(address)
            elif key == "sameas":
                for item in _iter_values(value):
                    add_link(str(item))
            walk(value)

    for raw in getattr(result, "json_ld", []) or []:
        try:
            walk(json.loads(raw.strip().removeprefix("<!--").removesuffix("-->")))
        except (json.JSONDecodeError, TypeError, ValueError):
            log.debug("Ignored malformed JSON-LD at %s", getattr(result, "url", ""))

    for item in getattr(result, "structured_values", []) or []:
        prop, value = item.get("itemprop", ""), item.get("value", "")
        if prop == "email":
            email_value = _usable_email(value.removeprefix("mailto:"), website_domain, allow_external=True)
            if email_value:
                contacts["emails"].add(email_value)
        elif prop in {"telephone", "phone"}:
            phone = _valid_phone(value.removeprefix("tel:"))
            if phone:
                contacts["phones"].add(phone)
    return contacts


def _extract_page_contacts(result: Any, website_domain: str) -> dict:
    text = _page_text(result)
    source_url = getattr(result, "url", "") or ""
    searchable = _deobfuscate_emails(text)
    raw_emails = set(_EMAIL_RE.findall(searchable))
    explicit_emails = set()
    for value in _MAILTO_RE.findall(text):
        explicit_emails.update(_EMAIL_RE.findall(unquote(value)))
    raw_emails.update(_decode_cf_email(value) for value in _CF_EMAIL_RE.findall(text))
    emails = {_usable_email(value, website_domain) for value in raw_emails if value}
    emails.update(_usable_email(value, website_domain, allow_external=True) for value in explicit_emails)
    emails.discard("")

    raw_phones = {_valid_phone(value) for value in _TEL_RE.findall(text)}
    visible_text = getattr(result, "visible_text", "") or ""
    lines = visible_text.splitlines()
    for index, line in enumerate(lines):
        if _PHONE_CONTEXT_RE.search(line):
            context_window = " ".join(lines[index:index + 3])
            raw_phones.update(_valid_phone(value) for value in _PHONE_RE.findall(context_window))
    raw_phones.discard("")
    structured = _structured_contacts(result, website_domain)
    emails.update(structured["emails"])
    raw_phones.update(structured["phones"])

    whatsapp: set[tuple[str, str]] = set(structured["whatsapp"])
    social_profiles: dict[str, set[str]] = structured["social_profiles"]
    for item in getattr(result, "links", []) or []:
        raw_href = item.get("href", "")
        phone, link = _whatsapp_contact(raw_href)
        if phone and link:
            whatsapp.add((phone, link))
            raw_phones.add(phone)
            continue
        platform, social_url = _social_platform(raw_href)
        if platform and social_url:
            social_profiles.setdefault(platform, set()).add(social_url)

    addresses = set(structured["addresses"])
    addresses.update(filter(None, (_normalise_address(value) for value in getattr(result, "addresses", []) or [])))
    for index, line in enumerate(lines):
        if not _ADDRESS_CONTEXT_RE.search(line):
            continue
        candidate = _normalise_address(" ".join(lines[index:index + 4]))
        if candidate and any(char.isdigit() for char in candidate) and _ADDRESS_TOKEN_RE.search(candidate):
            addresses.add(candidate)
    contact_forms = set()
    for action in getattr(result, "forms", []) or []:
        form_url = _normalise_url(urljoin(source_url, action)) if action else _normalise_url(source_url)
        form_context = f"{urlparse(source_url).path} {urlparse(form_url).path}".lower() if form_url else ""
        if form_url and _same_domain(source_url, form_url) and any(hint in form_context for hint in _CONTACT_HINTS[:6]):
            contact_forms.add(form_url)

    return {
        "source_url": source_url,
        "emails": emails,
        "phones": raw_phones,
        "fax_numbers": structured["fax_numbers"],
        "whatsapp": whatsapp,
        "social_profiles": social_profiles,
        "addresses": addresses,
        "contact_forms": contact_forms,
    }


def _contact_links(result: Any, seed_url: str) -> list[str]:
    links = getattr(result, "links", None) or []
    if isinstance(links, dict):
        links = links.get("internal", [])
    ranked: list[tuple[int, str]] = []
    for item in links:
        href = _normalise_url(urljoin(seed_url, item.get("href", "")))
        if not href or not _same_domain(seed_url, href) or href.rstrip("/") == seed_url.rstrip("/"):
            continue
        label = f"{item.get('text', '')} {urlparse(href).path}".lower()
        score = next((i for i, hint in enumerate(_CONTACT_HINTS) if hint in label), 99)
        if score < 99:
            ranked.append((score, href))
    ordered: list[str] = []
    for _, url in sorted(ranked, key=lambda value: value[0]):
        if url not in ordered:
            ordered.append(url)
    for path in ("/contact", "/contact-us", "/about", "/locations", "/branches"):
        fallback = urljoin(seed_url, path)
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered[: _MAX_PAGES_PER_SITE - 1]


class CustomSMECrawler:
    """Bounded, polite same-domain crawler with robots and redirect checks."""

    def __init__(self) -> None:
        self._robots: dict[str, RobotFileParser | bool] = {}
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(_MAX_SITE_CONCURRENCY)

    async def _wait_for_host(self, url: str) -> None:
        host = _domain(url)
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last_request.get(host, 0.0)
            if elapsed < _POLITE_DELAY_SECONDS:
                await asyncio.sleep(_POLITE_DELAY_SECONDS - elapsed)
            self._last_request[host] = time.monotonic()

    async def _robots_allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        cached = self._robots.get(origin)
        if cached is not None:
            return cached if isinstance(cached, bool) else cached.can_fetch(_USER_AGENT, url)
        robots_url = f"{origin}/robots.txt"
        try:
            if not await _is_public_url(robots_url):
                self._robots[origin] = False
                return False
            await self._wait_for_host(robots_url)
            response = await client.get(robots_url, follow_redirects=False)
            if response.status_code in (401, 403):
                self._robots[origin] = False
                return False
            if response.status_code == 200:
                parser = RobotFileParser(robots_url)
                parser.parse(response.text[:500_000].splitlines())
                self._robots[origin] = parser
                return parser.can_fetch(_USER_AGENT, url)
        except httpx.HTTPError as exc:
            log.debug("robots.txt unavailable for %s: %s", origin, exc)
        self._robots[origin] = True
        return True

    async def _fetch_page(self, client: httpx.AsyncClient, url: str, seed_url: str) -> tuple[CrawledPage | None, str]:
        current = _normalise_url(url)
        for _ in range(_MAX_REDIRECTS + 1):
            if not current or not _same_domain(seed_url, current) or not await _is_public_url(current):
                return None, "Blocked unsafe or cross-domain URL."
            if not await self._robots_allowed(client, current):
                return None, "Blocked by robots.txt."
            try:
                await self._wait_for_host(current)
                async with client.stream("GET", current, follow_redirects=False) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        current = _normalise_url(urljoin(current, response.headers.get("location", "")))
                        continue
                    if response.status_code >= 400:
                        return None, f"HTTP {response.status_code}."
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                        return None, f"Unsupported content type: {content_type.split(';', 1)[0]}."
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
                        return None, "Page is larger than the crawler limit."
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_BODY_BYTES:
                            return None, "Page is larger than the crawler limit."
                    encoding = response.charset_encoding or "utf-8"
                    return _parse_html(current, bytes(body).decode(encoding, errors="replace")), ""
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                return None, f"Connection failed: {type(exc).__name__}."
            except httpx.HTTPError as exc:
                return None, f"HTTP error: {type(exc).__name__}."
        return None, "Too many redirects."

    async def crawl_site(self, item: dict) -> dict:
        async with self._semaphore:
            provided_url = item["url"]
            parsed_seed = urlparse(provided_url)
            seed_url = f"{parsed_seed.scheme}://{parsed_seed.netloc}/"
            pages: list[CrawledPage] = []
            errors: list[str] = []
            headers = {
                "user-agent": _USER_AGENT,
                "accept": "text/html,application/xhtml+xml",
                "accept-language": "en-US,en;q=0.8",
            }
            limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
            async with httpx.AsyncClient(timeout=httpx.Timeout(_PAGE_TIMEOUT), headers=headers, limits=limits) as client:
                home, error = await self._fetch_page(client, seed_url, seed_url)
                if home is None and provided_url.rstrip("/") != seed_url.rstrip("/"):
                    home, error = await self._fetch_page(client, provided_url, seed_url)
                if home is None:
                    return {"item": item, "pages": [], "errors": [error]}
                pages.append(home)
                contact_urls = _contact_links(home, home.url)
                if provided_url.rstrip("/") != home.url.rstrip("/"):
                    contact_urls.insert(0, provided_url)
                for contact_url in list(dict.fromkeys(contact_urls)):
                    if len(pages) >= _MAX_PAGES_PER_SITE:
                        break
                    page, error = await self._fetch_page(client, contact_url, home.url)
                    if page is not None and all(existing.url != page.url for existing in pages):
                        pages.append(page)
                    elif error:
                        errors.append(error)
            return {"item": item, "pages": pages, "errors": errors}


async def _render_missing_contacts(results: list[Any]) -> int:
    """Use a bounded local browser only when static pages expose no email."""
    if os.environ.get("ENABLE_BROWSER_CONTACT_FALLBACK", "true").lower() not in ("1", "true", "yes"):
        return 0
    candidates = []
    for result in results:
        if isinstance(result, Exception) or not result.get("pages"):
            continue
        pages = result["pages"]
        site_domain = _domain(pages[0].url)
        if any(_extract_page_contacts(page, site_domain)["emails"] for page in pages):
            continue
        candidates.append(result)
        if len(candidates) >= _MAX_BROWSER_FALLBACK_SITES:
            break
    if not candidates:
        return 0

    try:
        from playwright.async_api import async_playwright
        from agent1.scraper import _launch_browser
    except Exception as exc:  # noqa: BLE001
        log.info("Browser contact fallback unavailable: %s", exc)
        return 0

    rendered = 0
    public_hosts: dict[str, bool] = {}
    try:
        async with async_playwright() as playwright:
            browser = await _launch_browser(playwright)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )

            async def guard_request(route) -> None:
                request = route.request
                parsed = urlparse(request.url)
                if parsed.scheme in {"data", "blob"}:
                    await route.continue_()
                    return
                if parsed.scheme not in {"http", "https"} or request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                    return
                host = (parsed.hostname or "").lower()
                if host not in public_hosts:
                    public_hosts[host] = await _is_public_url(request.url)
                if public_hosts[host]:
                    await route.continue_()
                else:
                    await route.abort()

            await context.route("**/*", guard_request)
            for result in candidates:
                original_pages: list[CrawledPage] = result["pages"]
                ordered_pages = sorted(
                    original_pages,
                    key=lambda item: (0 if any(hint in urlparse(item.url).path.lower() for hint in _CONTACT_HINTS) else 1),
                )
                for original in ordered_pages[:_MAX_BROWSER_PAGES_PER_SITE]:
                    page = await context.new_page()
                    try:
                        await page.goto(original.url, wait_until="domcontentloaded", timeout=20_000)
                        await page.wait_for_timeout(750)
                        if not _same_domain(original.url, page.url):
                            continue
                        rendered_page = _parse_html(page.url, await page.content())
                        result["pages"].append(rendered_page)
                        rendered += 1
                    except Exception as exc:  # noqa: BLE001
                        log.debug("Browser fallback skipped %s: %s", original.url, exc)
                    finally:
                        await page.close()
            await browser.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("Browser contact fallback failed safely: %s", exc)
    return rendered


async def mine_business_websites(query: str, max_results: int = 10, seed_urls: list[str] | None = None) -> dict:
    """Discover and crawl public SME sites with no AI or paid API calls."""
    discovery = await discover_business_websites(query, max_results=max_results, seed_urls=seed_urls)
    websites = discovery["websites"]
    if not websites:
        return {
            "ok": True, "message": discovery["message"], "leads": [], "discovered": 0,
            "crawled": 0, "email_ready": 0, "ai_used": False, "crawler_engine": "built_in_http",
        }

    crawler = CustomSMECrawler()
    results = await asyncio.gather(*(crawler.crawl_site(item) for item in websites), return_exceptions=True)
    browser_pages = await _render_missing_contacts(results)
    leads: list[dict] = []
    failed_sites = 0

    for result in results:
        if isinstance(result, Exception):
            failed_sites += 1
            log.error("Website crawl failed in isolation: %s", result)
            continue
        item = result["item"]
        pages: list[CrawledPage] = result["pages"]
        if not pages:
            failed_sites += 1
            log.info("Could not crawl %s: %s", _domain(item["url"]), "; ".join(result["errors"][:2]))
            continue

        site_domain = _domain(pages[0].url)
        page_name = _structured_business_name(pages[0]) or _clean_business_name(pages[0].title, item["url"])
        discovered_name = str(item.get("business_name", "")).strip()
        if discovered_name and len(page_name.split()) > 6 and len(discovered_name.split()) <= 6:
            page_name = discovered_name
        item["business_name"] = page_name
        if _looks_like_listing(pages[0].title, pages[0].url):
            failed_sites += 1
            log.info("Skipped listing page masquerading as a business site: %s", pages[0].url)
            continue
        emails: dict[str, str] = {}
        phones: dict[str, tuple[str, str]] = {}
        fax_numbers: dict[str, tuple[str, str]] = {}
        whatsapp: dict[str, dict[str, str]] = {}
        addresses: dict[str, tuple[str, str]] = {}
        contact_forms: dict[str, str] = {}
        social_profiles: dict[str, dict[str, str]] = {}
        for page in pages:
            contacts = _extract_page_contacts(page, site_domain)
            for email_value in contacts["emails"]:
                emails.setdefault(email_value, page.url)
            for phone in contacts["phones"]:
                phones.setdefault(_phone_key(phone), (phone, page.url))
            for fax in contacts["fax_numbers"]:
                fax_numbers.setdefault(_phone_key(fax), (fax, page.url))
            for number, link in contacts["whatsapp"]:
                whatsapp.setdefault(_phone_key(number), {"number": number, "url": link, "source_url": page.url})
            for address in contacts["addresses"]:
                addresses.setdefault(address.casefold(), (address, page.url))
            for form_url in contacts["contact_forms"]:
                contact_forms.setdefault(form_url, page.url)
            for platform, urls in contacts["social_profiles"].items():
                platform_urls = social_profiles.setdefault(platform, {})
                for social_url in urls:
                    platform_urls.setdefault(social_url, page.url)

        sorted_emails = sorted(emails, key=lambda value: _email_rank(value, site_domain))
        email_value = sorted_emails[0] if sorted_emails else ""
        sorted_phones = [phones[key][0] for key in sorted(phones)]
        phone = sorted_phones[0] if sorted_phones else ""
        sorted_faxes = [fax_numbers[key][0] for key in sorted(fax_numbers)]
        sorted_addresses = sorted((value[0] for value in addresses.values()), key=str.casefold)
        sorted_forms = sorted(contact_forms)
        sorted_socials = {platform: sorted(urls) for platform, urls in sorted(social_profiles.items())}
        whatsapp_contacts = [whatsapp[key] for key in sorted(whatsapp)]
        parsed_website = urlparse(pages[0].url)
        website_root = f"{parsed_website.scheme}://{parsed_website.netloc}/"
        evidence = []
        evidence.extend({"type": "email", "value": value, "source_url": emails[value]} for value in sorted_emails)
        evidence.extend({"type": "phone", "value": display, "source_url": source} for display, source in phones.values())
        evidence.extend({"type": "fax", "value": display, "source_url": source} for display, source in fax_numbers.values())
        evidence.extend({"type": "whatsapp", "value": item["url"], "label": item["number"], "source_url": item["source_url"]} for item in whatsapp_contacts)
        evidence.extend({"type": "address", "value": value, "source_url": addresses[value.casefold()][1]} for value in sorted_addresses)
        evidence.extend({"type": "contact_form", "value": value, "source_url": contact_forms[value]} for value in sorted_forms)
        for platform, urls in sorted_socials.items():
            evidence.extend({"type": platform, "value": value, "source_url": social_profiles[platform][value]} for value in urls)
        leads.append({
            "business_name": item["business_name"],
            "category": query,
            "phone": phone,
            "email": email_value,
            "phones": sorted_phones,
            "emails": sorted_emails,
            "fax_numbers": sorted_faxes,
            "whatsapp": whatsapp_contacts,
            "social_profiles": sorted_socials,
            "addresses": sorted_addresses,
            "contact_forms": sorted_forms,
            "website": website_root,
            "address": sorted_addresses[0] if sorted_addresses else "",
            "source": "agent1_custom_web_crawler",
            "discovery_source": item["discovery_source"],
            "source_url": item["url"],
            "email_source_url": emails.get(email_value, ""),
            "phone_source_url": phones.get(_phone_key(phone), ("", ""))[1] if phone else "",
            "email_confidence": "published" if email_value else "none",
            "contact_evidence": evidence,
            "crawled_pages": list(dict.fromkeys(page.url for page in pages)),
            "discovered_at": _now(),
            "appears_no_website": False,
            "website_reachable": True,
            "crawler_engine": "built_in_http+local_browser" if browser_pages else "built_in_http",
            "ai_used": False,
        })

    email_ready = sum(bool(lead["email"]) for lead in leads)
    return {
        "ok": True,
        "message": f"Crawled {len(leads)} business websites and found {email_ready} businesses with published email addresses.",
        "leads": leads,
        "discovered": len(websites),
        "crawled": len(leads),
        "failed_sites": failed_sites,
        "email_ready": email_ready,
        "contacts_found": sum(len(lead["contact_evidence"]) for lead in leads),
        "browser_fallback_pages": browser_pages,
        "ai_used": False,
        "crawler_engine": "built_in_http+local_browser" if browser_pages else "built_in_http",
    }
