"""Agent 2 (Verifier) — deterministic lead verification. NO Claude/AI calls.

Given raw scraped leads, it dedupes, validates phone/website, guesses an email
when possible, rejects leads with no contact method, and stores clean leads in
the main `leads` CRM collection (status "verified"). Rejected leads are kept in
the same collection with status "rejected" + a reason (hidden from default views
but queryable), so nothing silently disappears.
"""

from __future__ import annotations

import re
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from agent2.icp import qualify
from shared.database import get_db
from shared.logger import get_logger
from shared.settings_store import get_icp

log = get_logger("agent2")

_PHONE_RE = re.compile(r"[+()\-\s\d]{7,}")
_DIGITS_RE = re.compile(r"\d")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _leads():
    return get_db()["leads"]


def _domain(website: str) -> str:
    if not website:
        return ""
    url = website if "://" in website else f"http://{website}"
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:  # noqa: BLE001
        return ""


def _valid_phone(phone: str) -> bool:
    if not phone or not _PHONE_RE.fullmatch(phone.strip()):
        return False
    digits = "".join(_DIGITS_RE.findall(phone))
    return 7 <= len(digits) <= 15


def _website_loads(website: str) -> bool:
    """Lightweight check that the site responds. A dead/no site is NOT a rejection
    (it's a useful sales signal) — we just flag it."""
    if not website:
        return False
    url = website if "://" in website else f"http://{website}"
    try:
        with httpx.Client(timeout=6, follow_redirects=True) as c:
            r = c.get(url, headers={"user-agent": "Mozilla/5.0"})
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


def _domain_resolves(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, None)
        return True
    except Exception:  # noqa: BLE001
        return False


def _email_for(lead: dict, domain: str) -> tuple[str, str]:
    """Return (email, confidence) where confidence is found|guessed|none.

    A guessed address is only ever `info@<domain>` invented because the domain
    resolved. A resolving domain says nothing about whether that mailbox
    exists, so these bounce — and bounce rate is what gets a sending domain
    filtered. We therefore ask the receiving mail server whether it would
    accept the address before keeping it.

    Only a definitive rejection discards the guess: a catch-all domain,
    greylisting or a blocked port 25 all come back "unknown", and those are
    kept (still marked `guessed`) so the pre-send check can decide later.
    """
    scraped = (lead.get("email") or "").strip()
    if scraped and "@" in scraped:
        return scraped, "found"
    if not domain or not _domain_resolves(domain):
        return "", "none"

    candidate = f"info@{domain}"
    try:
        from agent3.verify_email import verify as _verify
        res = _verify(candidate, timeout=8)
        if res["status"] == "invalid":
            log.info("Discarded guessed address %s: %s", candidate, res["reason"])
            return "", "none"
        if res["status"] == "valid":
            # The mail server confirmed this mailbox exists.
            return candidate, "verified_guess"
    except Exception as exc:  # noqa: BLE001 - verification must never block intake
        log.warning("Could not verify %s (%s) - keeping as guessed", candidate, exc)
    return candidate, "guessed"


def _is_duplicate(business_name: str, phone: str, domain: str) -> bool:
    col = _leads()
    if business_name and phone and col.find_one({"business_name": business_name, "phone": phone}):
        return True
    if domain:
        # Same website domain already present among non-rejected leads.
        for existing in col.find({"status": {"$ne": "rejected"}}):
            if _domain(existing.get("website", "")) == domain and domain:
                return True
    return False


def verify_and_store(raw_leads: list[dict], niche: str, country: str, city: str,
                     batch_id: str = "") -> dict:
    """Run verification over a raw batch and persist results. Returns a summary.

    APPROVAL GATE: verified leads are stored as `pending_approval` and tagged with
    `batch_id`. They only become live CRM leads ("verified") once the CEO approves
    the batch — nothing enters the working CRM automatically.
    """
    col = _leads()
    verified = 0
    reasons = {"duplicate": 0, "invalid_phone": 0, "no_contact": 0,
               "competitor": 0, "blocked": 0, "junk": 0}
    icp = get_icp()

    for raw in raw_leads:
        try:
            name = (raw.get("business_name") or "").strip()
            if not name:
                continue
            website = (raw.get("website") or "").strip()
            domain = _domain(website)
            phone_raw = (raw.get("phone") or "").strip()
            phone_ok = _valid_phone(phone_raw)
            phone = phone_raw if phone_ok else ""

            # 1) ICP gate. Cheapest check and the one that prevents the most
            #    damage: never pitch web/ERP work to a web/ERP company.
            verdict, why = _icp_verdict(raw, name, niche, icp)
            if verdict != "keep":
                _store_rejected(raw, niche, country, city, verdict, why)
                reasons[verdict] = reasons.get(verdict, 0) + 1
                continue

            # 2) Duplicate check.
            if _is_duplicate(name, phone, domain):
                _store_rejected(raw, niche, country, city, "duplicate")
                reasons["duplicate"] += 1
                continue

            # 3) Phone validity (informational — only matters for contactability).
            if phone_raw and not phone_ok:
                reasons["invalid_phone"] += 1  # counted, but not an auto-reject on its own

            # 4) Website liveness = a flag, never a rejection reason.
            has_site = _website_loads(website) if website else False
            # 5) Email (found / guessed / none).
            email, email_conf = _email_for(raw, domain)

            # 6) No working contact method at all -> reject.
            if not phone and email_conf == "none":
                _store_rejected(raw, niche, country, city, "no_contact")
                reasons["no_contact"] += 1
                continue

            # Fit score ranks the CEO review queue: best prospects first,
            # instead of whatever happened to be scraped first.
            _fit = qualify({**raw, "business_name": name, "niche": niche, "city": city,
                            "email": email, "email_confidence": email_conf,
                            "phone": phone, "website": website,
                            "has_working_website": has_site}, icp)

            col.insert_one({
                "id": f"L-{uuid.uuid4().hex[:6].upper()}",
                "business_name": name,
                "niche": niche, "country": country, "city": city,
                "phone": phone, "email": email, "website": website,
                # Awaiting the CEO's review — NOT yet a live CRM lead.
                "status": "pending_approval",
                "batch_id": batch_id,
                "has_working_website": has_site,
                "email_confidence": email_conf,
                "source": raw.get("source", "agent1_scrape"),
                "discovery_source": raw.get("discovery_source", ""),
                "notes": raw.get("category", ""),
                # WHY this lead was collected — evidence-based, from the site audit.
                "collection_reason": raw.get("collection_reason", ""),
                "opportunity_score": raw.get("opportunity_score", 0),
                "fit_score": _fit.get("fit_score", 0),
                "fit_reasons": _fit.get("fit_reasons", []),
                "site_audit": raw.get("site_audit", {}),
                "pitch_points": raw.get("pitch_points", []),
                "last_action": "Verified by Agent 2 — awaiting CEO approval",
                "last_action_timestamp": _now(),
                "created_at": _now(),
            })
            verified += 1
        except Exception as exc:  # noqa: BLE001 - one bad lead never breaks the batch
            log.error("Verify failed for a lead, skipping: %s", exc)

    return {
        "found": len(raw_leads),
        "verified": verified,
        "rejected": sum(v for k, v in reasons.items() if k != "invalid_phone"),
        "reasons": reasons,
    }


def _icp_verdict(raw: dict, name: str, niche: str, icp: dict) -> tuple[str, str]:
    """Competitor / blocked / junk gate. Returns (verdict, human reason)."""
    res = qualify({**raw, "business_name": name, "niche": niche}, icp)
    return res["verdict"], res.get("reject_reason", "")


def _store_rejected(raw: dict, niche: str, country: str, city: str,
                    reason: str, detail: str = "") -> None:
    _leads().insert_one({
        "id": f"R-{uuid.uuid4().hex[:6].upper()}",
        "business_name": (raw.get("business_name") or "").strip(),
        "niche": niche, "country": country, "city": city,
        "phone": (raw.get("phone") or "").strip(),
        "email": (raw.get("email") or "").strip(),
        "website": (raw.get("website") or "").strip(),
        "status": "rejected",
        "rejection_reason": reason,
        "rejection_detail": detail,
        "source": "agent1_scrape",
        "last_action": f"Rejected by Agent 2: {reason}" + (f" — {detail}" if detail else ""),
        "last_action_timestamp": _now(),
        "created_at": _now(),
    })
