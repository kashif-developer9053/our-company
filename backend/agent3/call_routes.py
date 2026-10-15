"""API for the cold caller's WhatsApp call desk.

Two audiences hit these routes. The CEO queues leads and watches the numbers;
the caller works the queue. The caller's account can reach ONLY these routes —
not the CRM, not email, not lead hunting — and that is enforced here rather
than by hiding buttons, because a hidden button is not a permission.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.deps import get_current_user
from shared.database import get_db
from shared.logger import get_logger
from shared.safe_wrapper import safe_endpoint

from . import call_outreach as co
from .call_script import build as build_script
from .whatsapp import normalise_number, wa_state

router = APIRouter(prefix="/calls", tags=["call-outreach"])
log = get_logger("agent3.call_routes")


def _leads():
    return get_db()["leads"]


def _can_queue(user: dict) -> bool:
    """Only the CEO decides who gets phoned. The caller works the list."""
    return user.get("role") in ("admin", "user")


class QueueBody(BaseModel):
    lead_id: str


class UpdateBody(BaseModel):
    lead_id: str
    status: str = ""
    remarks: str | None = None
    logged_call: bool = False


def _card(lead: dict, caller_name: str = "") -> dict:
    """Everything the caller needs about one lead, on one card.

    He should never have to open another screen mid-call, so the business
    facts, the reason we approached them, and the script all travel together.
    """
    st = co.call_state(lead)
    wa = wa_state(lead)
    number = normalise_number(lead.get("phone", ""))
    purposes = lead.get("purposes") or []
    return {
        "id": lead.get("id"),
        "business_name": lead.get("business_name", ""),
        "niche": lead.get("niche", ""),
        "city": lead.get("city", ""),
        "country": lead.get("country", ""),
        "phone": lead.get("phone", ""),
        "number": number,
        "website": lead.get("website", ""),
        # WHY we approached them — the caller is asked this on every call.
        "purposes": purposes,
        "why": lead.get("collection_reason", ""),
        "rating": lead.get("rating"),
        "reviews_count": lead.get("reviews_count"),
        # Where the number came from, so he can answer "how did you get this?"
        "source": lead.get("source", ""),
        "collected_at": str(lead.get("created_at") or "")[:10],
        # Has he already been messaged? Changes how the call opens.
        "message_status": wa.get("status", ""),
        "message_sent_at": wa.get("sent_at", ""),
        "message_text": wa.get("message", ""),
        # Call state
        "status": st.get("status") or co.DEFAULT_STATUS,
        "remarks": st.get("remarks", ""),
        "calls_made": st.get("calls_made", 0),
        "last_call_at": st.get("last_call_at", ""),
        "queued_at": st.get("queued_at", ""),
        "history": st.get("history", [])[-8:],
        # What to say
        "script": build_script(lead, caller_name),
        # Opens a WhatsApp voice call for this contact.
        "wa_call_link": f"https://wa.me/{number}" if number else "",
    }


@router.post("/queue")
@safe_endpoint("agent3")
async def queue_lead(body: QueueBody, user: dict = Depends(get_current_user)):
    """Send a lead to the call list. CEO only."""
    if not _can_queue(user):
        raise HTTPException(status_code=403,
                            detail="Only the CEO can add leads to the call list")
    ok, msg = co.queue(body.lead_id, by=user.get("name") or user.get("email", ""))
    return {"ok": ok, "message": msg} if ok else {"ok": False, "error": msg}


@router.post("/unqueue")
@safe_endpoint("agent3")
async def unqueue_lead(body: QueueBody, user: dict = Depends(get_current_user)):
    if not _can_queue(user):
        raise HTTPException(status_code=403,
                            detail="Only the CEO can change the call list")
    ok, msg = co.unqueue(body.lead_id)
    return {"ok": ok, "message": msg} if ok else {"ok": False, "error": msg}


@router.get("/queue")
@safe_endpoint("agent3")
async def list_queue(status: str = "open", limit: int = 200,
                     user: dict = Depends(get_current_user)):
    """The call list. `status` is a status key, "open", or "all".

    Open-first by default: a caller wants the next number to ring, not a
    history of everyone he has already finished with.
    """
    q: dict = {"call_outreach.queued_at": {"$nin": ["", None]}}
    if status and status not in ("all", "open"):
        q["call_outreach.status"] = status

    rows = list(_leads().find(q).limit(max(1, min(limit, 500))))
    caller = user.get("name") or ""
    cards = [_card(r, caller) for r in rows]

    if status == "open":
        cards = [c for c in cards
                 if not co.CALL_STATUSES.get(c["status"], {}).get("terminal")]

    # To-call first, then the ones needing another attempt, then the rest.
    order = {"to_call": 0, "call_back": 1, "no_answer": 2, "interested": 3}
    cards.sort(key=lambda c: (order.get(c["status"], 9),
                              c.get("last_call_at") or "",
                              -(c.get("opportunity_score") or 0)))
    return {"ok": True, "leads": cards, "stats": co.stats(),
            "statuses": [{"key": k, "label": v["label"], "tone": v["tone"]}
                         for k, v in co.CALL_STATUSES.items()]}


@router.get("/lead/{lead_id}")
@safe_endpoint("agent3")
async def one_lead(lead_id: str, user: dict = Depends(get_current_user)):
    lead = _leads().find_one({"id": lead_id})
    if not lead or not co.is_queued(lead):
        raise HTTPException(status_code=404, detail="That lead is not on the call list")
    return {"ok": True, "lead": _card(lead, user.get("name") or "")}


@router.post("/update")
@safe_endpoint("agent3")
async def update_lead(body: UpdateBody, user: dict = Depends(get_current_user)):
    """Record a call outcome. The caller's main action."""
    ok, msg = co.update(body.lead_id, status=body.status, remarks=body.remarks,
                        logged_call=body.logged_call,
                        by=user.get("name") or user.get("email", ""))
    return {"ok": ok, "message": msg} if ok else {"ok": False, "error": msg}


@router.get("/stats")
@safe_endpoint("agent3")
async def call_stats(day: str = "", user: dict = Depends(get_current_user)):
    return {"ok": True, **co.stats(day)}
