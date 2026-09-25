"""Learn which niches are worth hunting from what actually happened.

Every day started with the CEO inventing a niche by hand, and the system never
noticed that some choices had already failed. The evidence was sitting in the
database unused:

  * solicitors — 75% of the leads were discarded before sending
  * general practitioner clinics — 59% discarded
  * electronics showrooms — 5% discarded
  * schools — 45 emails, 1 reply

A discard is the strongest signal we hold. It is the CEO looking at a real,
verified lead and saying "not this one" — worth far more than any guess a model
makes about a market.

Scoring is deliberately arithmetic rather than a model call. The inputs are
counts we already store, the output has to be explainable ("you discarded 75%
of these"), and a model asked to rank niches would just re-describe its
training data instead of reading ours.
"""

from __future__ import annotations

from collections import defaultdict

from agent2.icp import classify as icp_classify
from shared.database import get_db
from shared.logger import get_logger

log = get_logger("agent1.niche_performance")

# Below this many sent emails a reply rate means nothing. Three replies out of
# four sends is noise, not a trend, and chasing it wastes a week.
_MIN_SENT_FOR_REPLY_SIGNAL = 8

# Below this many leads a discard rate is equally unreliable.
_MIN_LEADS_FOR_DISCARD_SIGNAL = 10

# Placeholder text from a failed scrape, which otherwise scores well because
# nobody ever bothered to discard it.
_JUNK_RE = __import__("re").compile(
    r"lorem|ipsum|dolor|consectetur|excepteur|pariatur|\bminim\b|^test\b|example", __import__("re").I)


def _norm(niche: str) -> str:
    return (niche or "").strip().lower()[:60]


def _unusable_niche(niche: str) -> bool:
    """Niches that must never be recommended back, whatever they scored.

    Two kinds slipped through: lorem-ipsum text from a bad scrape, and search
    phrases like "ERP for small manufacturers" which return ERP vendors — our
    own competitors — rather than manufacturers.
    """
    if _JUNK_RE.search(niche):
        return True
    # Reuse the ICP gate so "what to hunt" and "who to keep" cannot disagree.
    verdict, _ = icp_classify({"business_name": niche, "niche": niche})
    return verdict != "keep"


def collect() -> dict[str, dict]:
    """Per-niche outcome counts, straight from leads and drafts."""
    db = get_db()
    sent_ids = {d.get("lead_id") for d in
                db["email_drafts"].find({"status": "sent"}, {"lead_id": 1})}

    stats: dict[str, dict] = defaultdict(
        lambda: {"leads": 0, "sent": 0, "replied": 0, "discarded": 0,
                 "emailable": 0, "interested": 0})

    # "Did this lead ever reply?" is all we need, so ask the database rather
    # than shipping every lead's full outreach_history — email bodies included
    # — across the connection just to test one flag.
    replied_ids = {d["id"] for d in db["leads"].find(
        {"outreach_history.type": "reply"}, {"id": 1})}

    for lead in db["leads"].find({}, {
            "id": 1, "niche": 1, "email": 1, "status": 1, "do_not_email": 1}):
        niche = _norm(lead.get("niche"))
        if not niche or niche == "?" or _unusable_niche(niche):
            continue
        s = stats[niche]
        s["leads"] += 1
        if (lead.get("email") or "").strip():
            s["emailable"] += 1
        if lead.get("do_not_email"):
            s["discarded"] += 1
        if lead.get("id") in sent_ids:
            s["sent"] += 1
        if lead.get("id") in replied_ids:
            s["replied"] += 1
        if lead.get("status") == "interested_awaiting_review":
            s["interested"] += 1
    return dict(stats)


def score_niche(s: dict) -> tuple[float, list[str]]:
    """Return (score, human reasons). Positive is worth hunting again."""
    score = 0.0
    why: list[str] = []

    # A reply is the only outcome that matters commercially, so it dominates —
    # but only once enough has been sent for the rate to mean anything.
    if s["sent"] >= _MIN_SENT_FOR_REPLY_SIGNAL:
        rate = s["replied"] / s["sent"]
        score += rate * 100
        if rate >= 0.05:
            why.append(f"{s['replied']} replies from {s['sent']} emails")
        elif s["replied"] == 0:
            # Scale with volume: 40 sends and nothing back is a far stronger
            # verdict than 8, and must outweigh "the CEO kept these leads",
            # which is only an opinion formed before anyone replied.
            score -= min(25 + s["sent"], 80)
            why.append(f"no replies from {s['sent']} emails")
        elif rate < 0.03:
            score -= 30
            why.append(f"only {s['replied']} reply from {s['sent']} emails")

    # The CEO rejecting verified leads is a direct verdict on the niche.
    if s["leads"] >= _MIN_LEADS_FOR_DISCARD_SIGNAL:
        disc = s["discarded"] / s["leads"]
        score -= disc * 60
        if disc >= 0.4:
            why.append(f"you discarded {disc*100:.0f}% of these leads")
        elif disc <= 0.1 and s["discarded"] >= 0:
            score += 10
            why.append(f"you kept {100-disc*100:.0f}% of these leads")

    # Reachability. A niche whose businesses never publish an email cannot be
    # worked by email at all, however attractive it looks.
    if s["leads"] >= _MIN_LEADS_FOR_DISCARD_SIGNAL:
        reach = s["emailable"] / s["leads"]
        score += (reach - 0.5) * 30
        if reach < 0.3:
            why.append(f"only {reach*100:.0f}% have an email address")

    if s["interested"]:
        score += s["interested"] * 15
        why.append(f"{s['interested']} marked interested")

    return score, why


_CACHE: dict = {"at": 0.0, "rows": None}
_CACHE_TTL = 300  # seconds


def ranked(force: bool = False) -> list[dict]:
    """Every niche we have worked, best first, with the reasoning.

    Cached: collect() walks every lead and its outreach history, which is
    several seconds against a remote cluster, and these verdicts shift over
    days rather than seconds. Called on every niche suggestion and by the
    dashboard, so recomputing each time made both feel broken.
    """
    import time as _time
    if not force and _CACHE["rows"] is not None and _time.time() - _CACHE["at"] < _CACHE_TTL:
        return _CACHE["rows"]

    out = []
    for niche, s in collect().items():
        score, why = score_niche(s)
        out.append({
            "niche": niche, "score": round(score, 1), "reasons": why,
            "leads": s["leads"], "sent": s["sent"], "replied": s["replied"],
            "discarded": s["discarded"], "emailable": s["emailable"],
            # Enough evidence to trust the verdict?
            "confident": s["sent"] >= _MIN_SENT_FOR_REPLY_SIGNAL
                         or s["leads"] >= _MIN_LEADS_FOR_DISCARD_SIGNAL,
        })
    out.sort(key=lambda x: -x["score"])
    _CACHE["rows"] = out
    _CACHE["at"] = __import__("time").time()
    return out


def avoid_list(limit: int = 12) -> list[str]:
    """Niches the evidence says not to hunt again."""
    return [r["niche"] for r in ranked()
            if r["confident"] and r["score"] < -15][:limit]


def proven_list(limit: int = 8) -> list[str]:
    """Niches that earned replies or that the CEO consistently kept."""
    return [r["niche"] for r in ranked()
            if r["confident"] and r["score"] > 5][:limit]


def briefing() -> str:
    """A short evidence summary to paste into Agent 1's niche prompt."""
    rows = [r for r in ranked() if r["confident"]]
    if not rows:
        return ""
    good = [r for r in rows if r["score"] > 5][:5]
    bad = [r for r in rows if r["score"] < -15][:6]

    parts: list[str] = []
    if good:
        parts.append("WORKED BEFORE (prefer niches like these):\n" + "\n".join(
            f"  - {r['niche']}: {'; '.join(r['reasons']) or 'kept by the CEO'}" for r in good))
    if bad:
        parts.append("ALREADY FAILED (do NOT suggest these or close variants):\n" + "\n".join(
            f"  - {r['niche']}: {'; '.join(r['reasons'])}" for r in bad))
    return "\n\n".join(parts)
