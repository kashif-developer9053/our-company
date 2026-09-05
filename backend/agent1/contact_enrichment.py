"""Bounded public-email discovery for websites returned by Google Maps."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import httpx

from shared.logger import get_logger

log = get_logger("agent1.contact_enrichment")

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_MAX_HTML_BYTES = 750_000
_MAX_PAGES = 3
_REDIRECTS = {301, 302, 303, 307, 308}
_CONTACT_HINTS = ("contact", "about", "team", "support", "reach-us", "get-in-touch")
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "proton.me", "protonmail.com",
}
_PLACEHOLDER_DOMAINS = {"example.com", "email.com", "domain.com", "yourdomain.com"}
_BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_PREFERRED_LOCALS = ("info", "contact", "hello", "office", "admin", "accounts", "sales", "support")


class _ContactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.emails: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        if href.lower().startswith("mailto:"):
            self.emails.update(_EMAIL_RE.findall(unquote(href[7:].split("?", 1)[0])))
        elif href:
            self.links.append(href)

    def handle_data(self, data: str) -> None:
        self.emails.update(_EMAIL_RE.findall(data))


def _normalise_url(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    return raw


async def _is_public_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if parsed.username or parsed.password or host == "localhost" or host.endswith(".local"):
        return False
    if parsed.port not in (None, 80, 443):
        return False
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443)
        ips = {ipaddress.ip_address(item[4][0]) for item in addresses}
    except Exception:  # noqa: BLE001
        return False
    return bool(ips) and all(ip.is_global for ip in ips)


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    current = url
    for _ in range(4):
        if not await _is_public_url(current):
            return ""
        try:
            async with client.stream("GET", current, follow_redirects=False) as response:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location", "")
                    if not location:
                        return ""
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    return ""
                content_type = response.headers.get("content-type", "").lower()
                if content_type and "html" not in content_type:
                    return ""
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_HTML_BYTES:
                        body.extend(chunk[: _MAX_HTML_BYTES - len(body)])
                        break
                    body.extend(chunk)
                return bytes(body).decode(response.encoding or "utf-8", errors="ignore")
        except (httpx.HTTPError, OSError):
            return ""
    return ""


def _select_email(emails: set[str], expected_domain: str) -> str:
    usable: list[str] = []
    for raw in emails:
        email = raw.strip(" \t\r\n.,;:()[]<>\"'").lower()
        if not _EMAIL_RE.fullmatch(email) or email.endswith(_BAD_EMAIL_SUFFIXES):
            continue
        local, domain = email.rsplit("@", 1)
        if domain in _PLACEHOLDER_DOMAINS:
            continue
        domain_matches = domain == expected_domain or domain.endswith(f".{expected_domain}")
        if not domain_matches and domain not in _FREE_EMAIL_DOMAINS:
            continue
        usable.append(email)
    if not usable:
        return ""

    def rank(email: str) -> tuple[int, int, str]:
        local, domain = email.rsplit("@", 1)
        domain_rank = 0 if domain == expected_domain or domain.endswith(f".{expected_domain}") else 1
        try:
            local_rank = _PREFERRED_LOCALS.index(local)
        except ValueError:
            local_rank = len(_PREFERRED_LOCALS)
        return domain_rank, local_rank, email

    return sorted(set(usable), key=rank)[0]


async def discover_public_email(website: str, client: httpx.AsyncClient | None = None) -> str:
    base = _normalise_url(website)
    if not base:
        return ""
    expected_domain = (urlparse(base).hostname or "").lower()
    if expected_domain.startswith("www."):
        expected_domain = expected_domain[4:]

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers={"user-agent": "Mozilla/5.0 (compatible; AI-Agency-Contact-Enrichment/1.0)"},
        )
    try:
        pages = [base]
        seen: set[str] = set()
        found: set[str] = set()
        while pages and len(seen) < _MAX_PAGES:
            url = pages.pop(0)
            if url in seen:
                continue
            seen.add(url)
            html = await _fetch_html(client, url)
            if not html:
                continue
            parser = _ContactParser()
            parser.feed(html)
            found.update(parser.emails)
            selected = _select_email(found, expected_domain)
            if selected:
                return selected
            for href in parser.links:
                candidate = urljoin(url, href)
                parsed = urlparse(candidate)
                host = (parsed.hostname or "").lower()
                if host.startswith("www."):
                    host = host[4:]
                if host == expected_domain and any(hint in parsed.path.lower() for hint in _CONTACT_HINTS):
                    clean = candidate.split("#", 1)[0]
                    if clean not in seen and clean not in pages:
                        pages.append(clean)
            if len(seen) == 1 and len(pages) < 2:
                pages.extend(urljoin(base, path) for path in ("/contact", "/about") if urljoin(base, path) not in pages)
        return _select_email(found, expected_domain)
    finally:
        if owns_client:
            await client.aclose()


async def enrich_lead_emails(leads: list[dict], concurrency: int = 4) -> int:
    """Add only publicly found emails to raw leads. Returns number enriched."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    enriched = 0
    limits = httpx.Limits(max_connections=max(2, concurrency), max_keepalive_connections=max(2, concurrency))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        limits=limits,
        headers={"user-agent": "Mozilla/5.0 (compatible; AI-Agency-Contact-Enrichment/1.0)"},
    ) as client:
        async def enrich(lead: dict) -> None:
            nonlocal enriched
            if lead.get("email") or not lead.get("website"):
                return
            async with semaphore:
                email = await discover_public_email(lead["website"], client)
            if email:
                lead["email"] = email
                lead["email_confidence"] = "found"
                lead["email_source"] = "public_website"
                enriched += 1

        await asyncio.gather(*(enrich(lead) for lead in leads))
    if enriched:
        log.info("Found published email addresses for %d scraped leads", enriched)
    return enriched
