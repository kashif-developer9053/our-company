"""Bounce handling and the suppression list — domain-reputation protection.

Why this exists: 58 of the addresses in the database were *guessed*
(`info@<domain>` invented by the verifier because nothing better was found) and
were mailed with no verification and no bounce tracking whatsoever. The only
recorded send failure was "Lead has no email address", which is a pre-send
check, not a bounce.

That is the classic way to lose a sending domain. Mailbox providers judge a
sender on hard-bounce and complaint rate; sustained bounces above a few percent
gets the whole domain filtered, and nothing in the app would have noticed.

Two independent layers, because either alone leaks:
  * `suppressed` — addresses and domains we must never contact again (hard
    bounce, spam complaint, unsubscribe). Checked immediately before every send.
  * `email_events` — an append-only log of what the provider told us, so the
    real bounce rate is measurable instead of assumed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.database import get_db
from shared.logger import get_logger

log = get_logger("agent3.suppression")

# Provider events that mean "never send here again". A soft bounce (mailbox
# full, greylisted) is deliberately NOT here — those recover, and suppressing
# them would throw away real prospects.
HARD_EVENTS = {"hard_bounce", "hardBounce", "blocked", "spam", "complaint",
               "unsubscribed", "invalid_email", "error"}
SOFT_EVENTS = {"soft_bounce", "softBounce", "deferred"}

# Suppress a whole domain after this many distinct hard bounces on it: the
# domain itself is dead or hostile, so the remaining guesses will bounce too.
DOMAIN_STRIKE_LIMIT = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _suppressed():
    return get_db()["suppressed"]


def _events():
    return get_db()["email_events"]


def _domain_of(addr: str) -> str:
    return addr.split("@")[-1].strip().lower() if "@" in addr else ""


def is_suppressed(addr: str) -> tuple[bool, str]:
    """(blocked, reason). Checked immediately before every send."""
    addr = (addr or "").strip().lower()
    if not addr or "@" not in addr:
        return True, "not a valid address"
    hit = _suppressed().find_one({"_id": addr})
    if hit:
        return True, hit.get("reason", "suppressed")
    dom = _domain_of(addr)
    if dom:
        hit = _suppressed().find_one({"_id": f"@{dom}"})
        if hit:
            return True, hit.get("reason", "domain suppressed")
    return False, ""


def suppress(addr: str, reason: str, source: str = "webhook") -> None:
    """Add one address to the never-contact list (idempotent)."""
    addr = (addr or "").strip().lower()
    if not addr or "@" not in addr:
        return
    _suppressed().update_one(
        {"_id": addr},
        {"$set": {"reason": reason, "source": source, "at": _now()}},
        upsert=True,
    )
    log.info("Suppressed %s (%s)", addr, reason)

    # Enough hard bounces on one domain means the domain is the problem.
    dom = _domain_of(addr)
    if dom:
        strikes = _suppressed().count_documents({"_id": {"$regex": f"@{dom}$"}})
        if strikes >= DOMAIN_STRIKE_LIMIT:
            _suppressed().update_one(
                {"_id": f"@{dom}"},
                {"$set": {"reason": f"{strikes} hard bounces on this domain",
                          "source": "auto", "at": _now()}},
                upsert=True,
            )
            log.warning("Suppressed whole domain @%s after %d bounces", dom, strikes)


def record_event(addr: str, event: str, detail: str = "", message_id: str = "") -> dict:
    """Log a provider event and suppress the address when it is terminal."""
    addr = (addr or "").strip().lower()
    event = (event or "").strip()
    _events().insert_one({
        "email": addr, "event": event, "detail": detail[:300],
        "message_id": message_id, "at": _now(),
    })

    hard = event in HARD_EVENTS
    if hard:
        suppress(addr, f"{event}: {detail[:120]}" if detail else event)
        # Stop the sequence for this lead and mark it plainly in the CRM.
        get_db()["leads"].update_many(
            {"email": {"$regex": f"^{addr}$", "$options": "i"}},
            {"$set": {"status": "undeliverable", "followup_opted_out": True,
                      "last_action": f"Email {event} — will not contact again",
                      "last_action_timestamp": _now()}},
        )
    return {"ok": True, "email": addr, "event": event, "suppressed": hard}


def stats(days: int = 30) -> dict:
    """Bounce/complaint rates — the numbers that decide if it is safe to scale."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    evs = list(_events().find({"at": {"$gte": since}}, {"_id": 0, "event": 1}))
    counts: dict[str, int] = {}
    for e in evs:
        counts[e.get("event", "?")] = counts.get(e.get("event", "?"), 0) + 1

    delivered = counts.get("delivered", 0) + counts.get("request", 0)
    hard = sum(n for k, n in counts.items() if k in HARD_EVENTS)
    soft = sum(n for k, n in counts.items() if k in SOFT_EVENTS)
    total = max(delivered + hard + soft, 1)
    return {
        "days": days,
        "events": counts,
        "delivered": delivered,
        "hard_bounces": hard,
        "soft_bounces": soft,
        # Industry guidance: stay under ~2-3%. Above ~5% providers start
        # filtering the whole sending domain.
        "bounce_rate_pct": round(100.0 * hard / total, 2),
        "suppressed_total": _suppressed().count_documents({}),
        "safe_to_scale": (100.0 * hard / total) < 3.0,
    }
