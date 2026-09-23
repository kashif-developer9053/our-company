"""Who opened, who clicked — pulled from Brevo onto each draft.

The outbox showed "sent" and nothing more, so a message that was read three
times looked identical to one that went straight to the bin. Brevo has tracked
this all along and nothing was reading it: 288 sent, 266 delivered, 82 unique
opens, 3 clicks. That gap between opens and replies is the whole problem, and
it was invisible in the app.

Events are matched on the recipient address rather than the message id. Brevo
returns its own generated id, which we never stored when sending, so the
address is the only join available. The cost is that two emails to the same
address cannot be told apart — acceptable here, since a lead gets one email at
a time and what matters is "did this person engage", not which of two.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from shared.database import get_db
from shared.logger import get_logger
from shared.settings_store import get_setting_value

log = get_logger("agent3.engagement")

# Ranked by how much interest each implies, so a later weaker event never
# overwrites a stronger one already recorded.
_RANK = {"delivered": 1, "opened": 2, "clicks": 3, "click": 3,
         "hardBounces": -1, "hard_bounce": -1, "softBounces": -1,
         "soft_bounce": -1, "blocked": -1, "spam": -2, "unsubscribed": -2}

_DISPLAY = {
    3: "clicked", 2: "opened", 1: "delivered",
    -1: "bounced", -2: "complained",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_engagement(days: int = 14, limit: int = 1000) -> dict:
    """Fetch recent Brevo events and stamp them onto the matching drafts."""
    key = (get_setting_value("brevo_api_key") or "").strip()
    if not key:
        return {"ok": False, "error": "No Brevo API key configured."}

    events: list[dict] = []
    offset = 0
    try:
        with httpx.Client(timeout=30, headers={"api-key": key, "accept": "application/json"}) as c:
            # Brevo pages at 100; walk until a short page or the cap.
            while len(events) < limit:
                r = c.get("https://api.brevo.com/v3/smtp/statistics/events",
                          params={"limit": 100, "offset": offset, "days": days})
                if r.status_code != 200:
                    if not events:
                        return {"ok": False, "error": f"Brevo returned {r.status_code}."}
                    break
                batch = r.json().get("events", [])
                events.extend(batch)
                if len(batch) < 100:
                    break
                offset += 100
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not reach Brevo: {exc}"}

    # Strongest event per address, plus when it happened.
    best: dict[str, tuple[int, str]] = {}
    for e in events:
        addr = str(e.get("email") or "").strip().lower()
        rank = _RANK.get(str(e.get("event") or ""), 0)
        if not addr or rank == 0:
            continue
        current = best.get(addr)
        if current is None or rank > current[0]:
            best[addr] = (rank, str(e.get("date") or ""))

    drafts = get_db()["email_drafts"]
    updated = 0
    for addr, (rank, when) in best.items():
        res = drafts.update_many(
            {"to_email": {"$regex": f"^{addr}$", "$options": "i"},
             "status": {"$in": ["sent", "failed"]}},
            {"$set": {"engagement": _DISPLAY.get(rank, "sent"),
                      "engagement_rank": rank,
                      "engagement_at": when,
                      "engagement_synced_at": _now()}},
        )
        updated += res.modified_count

    counts: dict[str, int] = {}
    for rank, _when in best.values():
        label = _DISPLAY.get(rank, "sent")
        counts[label] = counts.get(label, 0) + 1
    log.info("Engagement sync: %d events, %d addresses, %d drafts updated.",
             len(events), len(best), updated)
    return {"ok": True, "events": len(events), "addresses": len(best),
            "drafts_updated": updated, "breakdown": counts}


def summary(days: int = 30) -> dict:
    """Headline engagement figures straight from Brevo's own aggregate."""
    key = (get_setting_value("brevo_api_key") or "").strip()
    if not key:
        return {"ok": False, "error": "No Brevo API key configured."}
    try:
        with httpx.Client(timeout=30, headers={"api-key": key, "accept": "application/json"}) as c:
            r = c.get("https://api.brevo.com/v3/smtp/statistics/aggregatedReport",
                      params={"days": days})
            if r.status_code != 200:
                return {"ok": False, "error": f"Brevo returned {r.status_code}."}
            d = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not reach Brevo: {exc}"}

    delivered = d.get("delivered", 0) or 0
    opens = d.get("uniqueOpens", 0) or 0
    clicks = d.get("uniqueClicks", 0) or 0
    return {
        "ok": True, "days": days,
        "sent": d.get("requests", 0),
        "delivered": delivered,
        "opened": opens,
        "clicked": clicks,
        "hard_bounces": d.get("hardBounces", 0),
        "spam_reports": d.get("spamReports", 0),
        "unsubscribed": d.get("unsubscribed", 0),
        "open_rate_pct": round(100.0 * opens / delivered, 1) if delivered else 0.0,
        "click_rate_pct": round(100.0 * clicks / delivered, 1) if delivered else 0.0,
    }
