"""Pre-send email verification — MX + SMTP RCPT probing.

Motivation: 58 addresses in the database are `info@<domain>` patterns the
verifier invented because no real address was found. They were sent to blind.
Every one that does not exist is a hard bounce, and bounce rate is what gets a
sending domain filtered.

This is the same technique `email-sleuth` uses: ask the receiving mail server
whether it would accept the address, without delivering anything. It is a
standard, non-intrusive SMTP conversation (MAIL FROM / RCPT TO / QUIT).

Honest limits, because a false "invalid" costs a real prospect:
  * Many providers run catch-all, accepting every address. That returns
    "unknown", never "invalid" — we send those, we just do not trust them.
  * Some providers greylist or rate-limit probes, also "unknown".
  * SMTP verification needs outbound port 25. The VPS has it open; many home
    ISPs block it, so the caller must treat "unknown" as "send anyway".
Only a definitive 5xx rejection is treated as invalid.
"""

from __future__ import annotations

import re
import smtplib
import socket
from datetime import datetime, timezone

from shared.logger import get_logger

log = get_logger("agent3.verify")

_ADDR_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)

# Role addresses are real but reach a shared inbox, not a decision maker.
# Not a rejection — a quality signal used to prioritise enrichment.
ROLE_PREFIXES = {"info", "contact", "admin", "office", "hello", "enquiries",
                 "enquiry", "mail", "sales", "reception", "support", "help",
                 "team", "general", "post", "email"}

_MX_CACHE: dict[str, list[str]] = {}


def _domain(addr: str) -> str:
    return addr.split("@")[-1].strip().lower()


def is_role_address(addr: str) -> bool:
    return (addr or "").split("@")[0].strip().lower() in ROLE_PREFIXES


def mx_hosts(domain: str) -> list[str]:
    """MX hosts for a domain, best-priority first. Cached per process."""
    if domain in _MX_CACHE:
        return _MX_CACHE[domain]
    hosts: list[str] = []
    try:
        import dns.resolver  # type: ignore
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        hosts = [str(r.exchange).rstrip(".") for r in sorted(answers, key=lambda r: r.preference)]
    except Exception:  # noqa: BLE001
        # No dnspython, or no MX record. Fall back to the A record: a domain
        # that resolves may still accept mail on itself.
        try:
            socket.getaddrinfo(domain, 25)
            hosts = [domain]
        except Exception:  # noqa: BLE001
            hosts = []
    _MX_CACHE[domain] = hosts
    return hosts


def verify(addr: str, from_addr: str = "verify@example.com", timeout: int = 10) -> dict:
    """Return {status, confidence, reason}.

    status: valid | invalid | unknown | catch_all
    confidence: 0-10, mirroring email-sleuth's scale.
    """
    addr = (addr or "").strip().lower()
    out = {"email": addr, "status": "unknown", "confidence": 0,
           "reason": "", "role": False, "checked_at": datetime.now(timezone.utc).isoformat()}

    if not _ADDR_RE.match(addr):
        return {**out, "status": "invalid", "confidence": 0, "reason": "malformed address"}
    out["role"] = is_role_address(addr)

    dom = _domain(addr)
    hosts = mx_hosts(dom)
    if not hosts:
        return {**out, "status": "invalid", "confidence": 0,
                "reason": "domain has no mail server"}

    host = hosts[0]
    try:
        with smtplib.SMTP(host, 25, timeout=timeout) as s:
            s.ehlo_or_helo_if_needed()
            s.mail(from_addr)
            code, _msg = s.rcpt(addr)

            if code in (250, 251):
                # Does it accept anything? If so, acceptance proves nothing.
                rnd = f"zz{int(datetime.now().timestamp())}zzq@{dom}"
                cc, _ = s.rcpt(rnd)
                if cc in (250, 251):
                    return {**out, "status": "catch_all", "confidence": 5,
                            "reason": "domain accepts all addresses — cannot confirm"}
                return {**out, "status": "valid",
                        "confidence": 7 if out["role"] else 9,
                        "reason": "mail server accepted the address"}

            if 500 <= code < 600:
                return {**out, "status": "invalid", "confidence": 0,
                        "reason": f"mail server rejected it ({code})"}

            return {**out, "status": "unknown", "confidence": 3,
                    "reason": f"inconclusive response ({code})"}

    except (smtplib.SMTPException, socket.timeout, OSError) as exc:
        # Port 25 blocked, greylisting, connection refused — never treat as invalid.
        return {**out, "status": "unknown", "confidence": 3,
                "reason": f"could not complete check ({type(exc).__name__})"}


def should_send(addr: str, result: dict | None = None) -> tuple[bool, str]:
    """Send decision. Only a definitive `invalid` blocks — anything else sends.

    Being conservative here is deliberate: a false negative loses a real
    prospect forever, while an unknown that bounces once is recoverable
    (the webhook suppresses it and it never gets a second attempt).
    """
    r = result or verify(addr)
    if r["status"] == "invalid":
        return False, r["reason"]
    return True, r["status"]
