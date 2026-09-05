"""Deterministic website audit — turns a prospect's site into concrete,
evidence-backed reasons to contact them.

NO AI is used here. Every finding is a fact observed in the fetched HTML/headers
(missing meta description, no HTTPS, no mobile viewport, slow response, etc.),
so the "why we collected this lead" note is always defensible and specific.

Design rule: a lead is only worth collecting if we can name a problem we can
actually fix. `audit_site()` returns findings + a qualification verdict; leads
whose site is already excellent are REJECTED as poor prospects rather than
padding the CRM.
"""

from __future__ import annotations

import asyncio
import re
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from shared.logger import get_logger

log = get_logger("agent1.site_auditor")

_UA = "Mozilla/5.0 (compatible; AI-Agency-SiteAudit/1.0)"
_TIMEOUT = 15
_MAX_BYTES = 1_500_000

# Severity drives the sales pitch: "critical" = strong reason to call today.
CRITICAL, HIGH, MEDIUM, LOW = "critical", "high", "medium", "low"

# Weight per severity — used to score how good a prospect this is.
_WEIGHT = {CRITICAL: 40, HIGH: 20, MEDIUM: 10, LOW: 4}

# A site scoring at/above this is a genuine opportunity worth contacting.
QUALIFY_THRESHOLD = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finding(code: str, severity: str, title: str, evidence: str, pitch: str) -> dict:
    """One observed problem. `evidence` is what we actually saw; `pitch` is the
    service angle it justifies."""
    return {"code": code, "severity": severity, "title": title,
            "evidence": evidence[:300], "pitch": pitch}


# ---------------------------------------------------------------------------
# Individual checks. Each takes what it needs and returns findings (never raises).
# ---------------------------------------------------------------------------
def _check_transport(url: str, response: httpx.Response | None, error: str) -> list[dict]:
    out = []
    parsed = urlparse(url)
    if error:
        out.append(_finding(
            "site_unreachable", CRITICAL, "Website does not load",
            f"Request to {url} failed: {error}",
            "Their site is effectively invisible to customers — a rebuild or migration is urgently needed."))
        return out
    if response is None:
        return out
    if parsed.scheme != "https":
        out.append(_finding(
            "no_https", CRITICAL, "No HTTPS (insecure site)",
            f"Site served over {parsed.scheme.upper()} at {url}",
            "Browsers mark it 'Not secure' and Google demotes it — SSL setup + migration."))
    if response.status_code >= 400:
        out.append(_finding(
            "http_error", CRITICAL, f"Site returns HTTP {response.status_code}",
            f"{url} responded {response.status_code}",
            "Customers hitting an error page are lost sales — needs immediate fixing."))
    return out


def _check_speed(elapsed_ms: int, size_bytes: int) -> list[dict]:
    out = []
    if elapsed_ms > 4000:
        out.append(_finding(
            "very_slow", CRITICAL, "Very slow page load",
            f"Homepage took {elapsed_ms} ms to respond",
            "Over half of visitors abandon a site this slow — performance optimisation."))
    elif elapsed_ms > 2000:
        out.append(_finding(
            "slow", HIGH, "Slow page load",
            f"Homepage took {elapsed_ms} ms to respond",
            "Speed optimisation would cut bounce rate and improve Google ranking."))
    if size_bytes > 3_000_000:
        out.append(_finding(
            "heavy_page", MEDIUM, "Very heavy page weight",
            f"Homepage HTML/assets ~{size_bytes // 1024} KB",
            "Image compression and asset optimisation to speed the site up."))
    return out


def _check_seo(html: str) -> list[dict]:
    out = []
    low = html.lower()

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = (title_m.group(1).strip() if title_m else "")
    if not title:
        out.append(_finding(
            "no_title", CRITICAL, "Missing page title",
            "No <title> tag found on the homepage",
            "Google has nothing to show in results — foundational SEO fix."))
    elif len(title) < 15:
        out.append(_finding(
            "weak_title", MEDIUM, "Very short page title",
            f"Title is only {len(title)} chars: '{title[:60]}'",
            "A descriptive, keyword-led title would lift search visibility."))

    if not re.search(r"<meta[^>]+name=[\"']description[\"']", html, re.I):
        out.append(_finding(
            "no_meta_description", HIGH, "No meta description",
            "No <meta name=\"description\"> on the homepage",
            "Google writes its own snippet — a written description improves click-through."))

    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if not h1s:
        out.append(_finding(
            "no_h1", HIGH, "No H1 heading",
            "No <h1> element found",
            "Search engines can't identify the page topic — on-page SEO work."))

    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    if imgs:
        no_alt = [i for i in imgs if not re.search(r"\balt\s*=", i, re.I)]
        if len(no_alt) >= max(3, len(imgs) // 2):
            out.append(_finding(
                "images_missing_alt", MEDIUM, "Images missing alt text",
                f"{len(no_alt)} of {len(imgs)} images have no alt attribute",
                "Hurts accessibility and image search — quick SEO/accessibility win."))

    if "application/ld+json" not in low and "itemtype" not in low:
        out.append(_finding(
            "no_structured_data", MEDIUM, "No structured data (schema.org)",
            "No JSON-LD or microdata markup detected",
            "Adding LocalBusiness schema unlocks rich results in Google."))

    if not re.search(r"<meta[^>]+property=[\"']og:", html, re.I):
        out.append(_finding(
            "no_open_graph", LOW, "No Open Graph tags",
            "No og: meta tags found",
            "Shared links look broken on social/WhatsApp — quick metadata fix."))
    return out


def _check_mobile(html: str) -> list[dict]:
    out = []
    if not re.search(r"<meta[^>]+name=[\"']viewport[\"']", html, re.I):
        out.append(_finding(
            "not_mobile_friendly", CRITICAL, "Not mobile-friendly",
            "No responsive viewport meta tag — site won't adapt to phones",
            "Most local traffic is mobile; Google ranks mobile-first. Responsive rebuild."))
    return out


def _check_conversion(html: str, base_url: str) -> list[dict]:
    out = []
    low = html.lower()
    has_form = "<form" in low
    has_mailto = "mailto:" in low
    has_tel = "tel:" in low
    has_whatsapp = "wa.me" in low or "api.whatsapp.com" in low

    if not (has_form or has_mailto or has_tel):
        out.append(_finding(
            "no_contact_route", CRITICAL, "No clear way to make contact",
            "No contact form, mailto: link or tel: link found on the homepage",
            "Visitors who want to buy can't reach them — enquiry form + click-to-call."))
    elif not has_form:
        out.append(_finding(
            "no_contact_form", MEDIUM, "No enquiry form",
            "Contact details exist but there is no form to capture leads",
            "A lead-capture form turns anonymous visits into contactable enquiries."))
    if not has_whatsapp:
        out.append(_finding(
            "no_whatsapp", LOW, "No WhatsApp contact option",
            "No wa.me / WhatsApp link detected",
            "WhatsApp click-to-chat typically lifts local enquiry volume."))
    return out


def _check_tech_debt(html: str, headers: dict) -> list[dict]:
    out = []
    low = html.lower()
    if re.search(r"wordpress|wp-content", low):
        gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', html, re.I)
        ver = gen.group(1) if gen else ""
        m = re.search(r"wordpress\s*([\d.]+)", ver, re.I)
        if m:
            try:
                major = int(m.group(1).split(".")[0])
                if major < 6:
                    out.append(_finding(
                        "outdated_cms", HIGH, f"Outdated CMS ({ver})",
                        f"Generator meta reports {ver}",
                        "Old WordPress versions are a known security risk — upgrade/maintenance plan."))
            except ValueError:
                pass
    if re.search(r"<(table)[^>]*>\s*<tr", low) and low.count("<table") > 3:
        out.append(_finding(
            "table_layout", HIGH, "Outdated table-based layout",
            f"{low.count('<table')} <table> elements used for page structure",
            "Legacy markup that breaks on mobile — modern responsive rebuild."))
    if "<font" in low or "bgcolor=" in low:
        out.append(_finding(
            "legacy_html", MEDIUM, "Legacy HTML tags in use",
            "Deprecated <font>/bgcolor attributes found",
            "The site is visibly dated — a modern redesign would lift credibility."))
    # Only real embedded Flash objects — not the word "flash" in unrelated JS/CSS.
    if re.search(r"\.swf\b|application/x-shockwave-flash|<embed[^>]+swf", low):
        out.append(_finding(
            "flash_content", HIGH, "Flash content detected",
            "Embedded .swf / Shockwave object found",
            "Flash is dead in all browsers — that content is invisible today."))
    return out


def _check_analytics(html: str) -> list[dict]:
    low = html.lower()
    if not re.search(r"googletagmanager|google-analytics|gtag\(|plausible|matomo|fathom", low):
        return [_finding(
            "no_analytics", MEDIUM, "No web analytics installed",
            "No Google Analytics / GTM / privacy-analytics snippet detected",
            "They have no idea where enquiries come from — analytics + reporting setup.")]
    return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def audit_site(website: str, client: httpx.AsyncClient | None = None) -> dict:
    """Audit one website. Never raises.

    Returns {ok, url, findings[], score, severity_counts, qualified, headline, summary}
    """
    result = {
        "ok": False, "url": website, "findings": [], "score": 0,
        "severity_counts": {}, "qualified": False, "headline": "",
        "summary": "", "audited_at": _now(),
    }
    if not website:
        return result

    url = website if "://" in website else f"https://{website}"
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True,
            headers={"user-agent": _UA},
            verify=ssl.create_default_context(),
        )

    findings: list[dict] = []
    try:
        start = time.perf_counter()
        response, error = None, ""
        try:
            response = await client.get(url)
        except Exception as exc:  # noqa: BLE001 - a dead site is itself a finding
            error = f"{type(exc).__name__}"
            # An https failure may just mean the site is http-only — retry once.
            if url.startswith("https://"):
                try:
                    url = "http://" + url[len("https://"):]
                    response = await client.get(url)
                    error = ""
                except Exception as exc2:  # noqa: BLE001
                    error = f"{type(exc2).__name__}"
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        findings += _check_transport(str(response.url) if response else url, response, error)

        if response is not None and response.status_code < 400:
            html = response.text[:_MAX_BYTES]
            headers = dict(response.headers)
            findings += _check_speed(elapsed_ms, len(response.content))
            findings += _check_seo(html)
            findings += _check_mobile(html)
            findings += _check_conversion(html, url)
            findings += _check_tech_debt(html, headers)
            findings += _check_analytics(html)
            result["ok"] = True
        elif error:
            result["ok"] = True  # the audit itself succeeded: the site is down

    except Exception as exc:  # noqa: BLE001
        log.error("Audit failed in isolation for %s: %s", website, exc)
    finally:
        if owns_client:
            await client.aclose()

    counts: dict[str, int] = {}
    score = 0
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        score += _WEIGHT.get(f["severity"], 0)

    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    result["findings"] = findings
    result["score"] = score
    result["severity_counts"] = counts
    # Qualify only on a real problem: a critical/high finding, or enough medium
    # ones to matter. LOW-only noise (e.g. "no WhatsApp") never qualifies a lead.
    substantial = counts.get(CRITICAL, 0) + counts.get(HIGH, 0)
    result["qualified"] = bool(substantial) or counts.get(MEDIUM, 0) >= 3
    result["headline"] = findings[0]["title"] if findings else "No significant issues found"
    result["summary"] = build_reason(result)  # after `qualified` is set above
    return result


def build_reason(audit: dict) -> str:
    """Human-readable 'why we collected this lead' for the CRM remarks field."""
    findings = audit.get("findings", [])
    if not findings:
        return ("Their website is already in good shape — no clear web/SEO problem to solve, "
                "so this is a weak prospect for web services.")
    top = findings[:3]
    bits = "; ".join(f"{f['title']} ({f['evidence']})" for f in top)
    extra = len(findings) - len(top)
    tail = f" +{extra} more issue(s)." if extra > 0 else ""
    if not audit.get("qualified", True):
        return (f"Weak prospect — their site is broadly fine. Only minor points found: {bits}.{tail} "
                "Not worth outreach for web/SEO services.")
    return f"Collected because their site has fixable problems: {bits}.{tail}"


def build_pitch_points(audit: dict) -> list[str]:
    """The service angles this audit justifies — fed to Agent 3 for the email."""
    return [f["pitch"] for f in audit.get("findings", [])[:4]]


async def audit_leads(leads: list[dict], concurrency: int = 5) -> int:
    """Audit every lead that has a website. Attaches audit data in place.

    Leads with NO website get a 'no website at all' reason (the strongest pitch
    for a web-development agency). Returns how many were audited.
    """
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True,
                                 headers={"user-agent": _UA}) as client:
        async def one(lead: dict) -> bool:
            site = (lead.get("website") or "").strip()
            if not site:
                lead["site_audit"] = {
                    "ok": True, "url": "", "findings": [_finding(
                        "no_website", CRITICAL, "No website at all",
                        "No website listed on their public business profile",
                        "They have no web presence — a new website is the entire opportunity.")],
                    "score": _WEIGHT[CRITICAL], "severity_counts": {CRITICAL: 1},
                    "qualified": True, "headline": "No website at all",
                    "audited_at": _now(),
                }
                lead["site_audit"]["summary"] = build_reason(lead["site_audit"])
                lead["collection_reason"] = lead["site_audit"]["summary"]
                lead["opportunity_score"] = lead["site_audit"]["score"]
                lead["pitch_points"] = build_pitch_points(lead["site_audit"])
                return True
            async with sem:
                audit = await audit_site(site, client)
            lead["site_audit"] = audit
            lead["collection_reason"] = audit["summary"]
            lead["opportunity_score"] = audit["score"]
            lead["pitch_points"] = build_pitch_points(audit)
            return audit["ok"]

        results = await asyncio.gather(*(one(l) for l in leads), return_exceptions=True)
    return sum(1 for r in results if r is True)
