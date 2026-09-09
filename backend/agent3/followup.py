"""Follow-up sequencing — the highest-value gap in the outreach flow.

The data that motivated this: of 37 cold emails actually sent, 30 never
received a single follow-up. In cold outreach most replies arrive on emails
2-4, not email 1, so roughly two thirds of the available replies were being
left on the table.

Design decisions worth knowing:

* Follow-ups are DRAFTS, not sends. They join the same review queue as the
  first email and obey the same daily cap and the same approval gate. Nothing
  reaches a prospect without the CEO seeing it.
* Any inbound reply stops the sequence immediately and permanently. Emailing
  someone who already answered is the fastest way to lose them.
* Each step has its own angle. A follow-up that just says "bumping this" four
  times is why people mark mail as spam; a breakup email reliably outperforms
  every other step in the sequence, so it is the one we never skip.
* Steps are derived from `outreach_history`, which we already store. No new
  per-lead scheduling state to drift out of sync.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent2.icp import classify
from shared.logger import get_logger

log = get_logger("agent3.followup")

# step -> (days after the previous email, angle handed to the writer)
SEQUENCE = [
    (3, "gentle_bump"),
    (7, "new_angle"),
    (14, "breakup"),
]

# Written as instructions to the email writer, not as templates. Templates are
# recognisable after a handful of sends; a fresh generation per lead is not.
ANGLE_BRIEF = {
    "gentle_bump": (
        "This is a SHORT follow-up to an email they did not answer. Under 60 words. "
        "Assume the first email got buried, not rejected — say so lightly and without "
        "guilt-tripping. Do not repeat the original pitch, do not re-list anything, and "
        "do not add new problems. One friendly line plus one easy question."
    ),
    "new_angle": (
        "This is a second follow-up. They have ignored two emails, so the first angle "
        "did not land — try a DIFFERENT one. Talk about what their competitors are "
        "doing well online, or what a customer experiences when they look this business "
        "up. Keep it under 90 words. Do not mention that you already emailed twice."
    ),
    "breakup": (
        "This is the final email in the sequence. Politely close the file: say you will "
        "stop following up, leave the door open with no guilt and no pressure, and keep "
        "it warm and short — under 60 words. No pitch, no new information, no bullet "
        "points. This should read like a courteous professional moving on."
    ),
}


def _parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        # outreach_history also holds RFC-2822 dates from IMAP replies.
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(str(ts))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            return None


def sequence_state(lead: dict) -> dict:
    """Where this lead sits in the sequence, derived purely from its history."""
    hist = lead.get("outreach_history") or []
    outbound = [h for h in hist if h.get("type") in ("email", "followup")]
    replied = any(h.get("type") == "reply" for h in hist)

    last_at = None
    for h in outbound:
        d = _parse(h.get("sent_at") or h.get("at") or "")
        if d and (last_at is None or d > last_at):
            last_at = d

    return {
        "sent_count": len(outbound),
        "replied": replied,
        "last_sent_at": last_at,
        "step": len(outbound) - 1,   # 0 = only the first email has gone out
    }


def next_step_due(lead: dict, now: datetime | None = None) -> tuple[bool, str, str]:
    """Return (is_due, angle, reason). Pure function — easy to test, no I/O."""
    now = now or datetime.now(timezone.utc)
    st = sequence_state(lead)

    if st["replied"]:
        return False, "", "they replied — sequence stopped"
    if lead.get("followup_opted_out") or lead.get("do_not_contact"):
        return False, "", "opted out"
    if st["sent_count"] == 0:
        return False, "", "no first email sent yet"

    step = st["step"]
    if step >= len(SEQUENCE):
        return False, "", "sequence complete"
    if not st["last_sent_at"]:
        return False, "", "no readable send date"

    wait_days, angle = SEQUENCE[step]
    due_at = st["last_sent_at"] + timedelta(days=wait_days)
    if now < due_at:
        left = (due_at - now).days
        return False, angle, f"due in {max(0, left)}d"

    # A step that fell far past its window should not pretend to be a timely
    # nudge — "just bumping this" two weeks late reads as automation. Skip
    # ahead to the step that actually matches how long it has been.
    overdue = (now - due_at).days
    if overdue > 7 and step + 1 < len(SEQUENCE):
        for later in range(len(SEQUENCE) - 1, step, -1):
            if (now - st["last_sent_at"]).days >= SEQUENCE[later][0]:
                angle = SEQUENCE[later][1]
                return True, angle, f"step {later + 1} due ({angle}, {overdue}d overdue)"

    return True, angle, f"step {step + 1} due ({angle})"


def due_leads(leads_col, limit: int = 50) -> list[tuple[dict, str]]:
    """Leads whose next follow-up is due now, best-fit first."""
    now = datetime.now(timezone.utc)
    out: list[tuple[dict, str, int]] = []
    for lead in leads_col.find({
        "outreach_history.type": {"$in": ["email", "followup"]},
        "status": {"$nin": ["rejected", "do_not_contact"]},
    }):
        # A lead with no address cannot be followed up by email.
        if not (lead.get("email") or "").strip():
            continue
        # The ICP gate was added after these were mailed, so the backlog still
        # contains competitors. Do not compound the original mistake.
        if classify(lead)[0] != "keep":
            continue
        due, angle, _why = next_step_due(lead, now)
        if due:
            out.append((lead, angle, int(lead.get("fit_score") or 0)))
    out.sort(key=lambda x: -x[2])
    return [(l, a) for l, a, _ in out[:limit]]
