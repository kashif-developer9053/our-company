"""Lead data model + seed data for the CRM."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

LEAD_STATUSES = [
    "new",
    "pending_approval",   # verified by Agent 2, waiting on the CEO to release into the CRM
    "verified",
    "rejected",
    "mailed",
    "replied",
    "not_interested",
    "interested_awaiting_review",
]


class LeadCreate(BaseModel):
    business_name: str = Field(min_length=1, max_length=120)
    niche: str = Field(default="", max_length=120)
    country: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    status: str = "new"
    notes: str = ""


class LeadUpdate(BaseModel):
    business_name: Optional[str] = None
    niche: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    status: Optional[str] = None
    last_action: Optional[str] = None
    notes: Optional[str] = None
    call_scheduled: Optional[str] = None  # Phase 5 cold-call stub (manual set)


def serialize(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "business_name": doc.get("business_name", ""),
        "niche": doc.get("niche", ""),
        "country": doc.get("country", ""),
        "city": doc.get("city", ""),
        "phone": doc.get("phone", ""),
        "email": doc.get("email", ""),
        "website": doc.get("website", ""),
        "status": doc.get("status", "new"),
        "last_action": doc.get("last_action", ""),
        "last_action_timestamp": doc.get("last_action_timestamp", ""),
        "notes": doc.get("notes", ""),
        "created_at": doc.get("created_at", ""),
        # Phase 4 fields (from the scrape + verify pipeline).
        "has_working_website": doc.get("has_working_website"),
        "email_confidence": doc.get("email_confidence", ""),
        "rejection_reason": doc.get("rejection_reason", ""),
        "source": doc.get("source", ""),
        "discovery_source": doc.get("discovery_source", ""),
        # Why this lead was collected + the evidence behind it.
        "collection_reason": doc.get("collection_reason", ""),
        "opportunity_score": doc.get("opportunity_score", 0),
        "site_audit": doc.get("site_audit", {}),
        "pitch_points": doc.get("pitch_points", []),
        # Phase 5 outreach fields.
        "outreach_history": doc.get("outreach_history", []),
        "reply_classification": doc.get("reply_classification", ""),
        "reply_reasoning": doc.get("reply_reasoning", ""),
        "suggested_reply": doc.get("suggested_reply", ""),
        "call_scheduled": doc.get("call_scheduled", ""),
    }


# Seed leads (mirrors the Phase 1.6 mock so the UI has content on first run).
SEED_LEADS = [
    {"business_name": "SmileBright Dental", "niche": "Dentists", "city": "Islamabad", "status": "interested_awaiting_review", "last_action": "Positive reply received", "last_action_timestamp": "2026-07-24 10:14"},
    {"business_name": "Capital Ortho Clinic", "niche": "Dentists", "city": "Islamabad", "status": "replied", "last_action": "Reply received (unclear)", "last_action_timestamp": "2026-07-24 10:09"},
    {"business_name": "PearlCare Dentistry", "niche": "Dentists", "city": "Islamabad", "status": "mailed", "last_action": "Cold email sent", "last_action_timestamp": "2026-07-24 09:58"},
    {"business_name": "Northside Family Dental", "niche": "Dentists", "city": "Islamabad", "status": "not_interested", "last_action": "Marked not interested (auto)", "last_action_timestamp": "2026-07-24 09:52"},
    {"business_name": "BlueSky Physio", "niche": "Physiotherapists", "city": "Lahore", "status": "interested_awaiting_review", "last_action": "Positive reply received", "last_action_timestamp": "2026-07-24 09:47"},
    {"business_name": "MoveWell Rehab", "niche": "Physiotherapists", "city": "Lahore", "status": "mailed", "last_action": "Cold email sent", "last_action_timestamp": "2026-07-24 09:40"},
    {"business_name": "GreenLeaf Accounting", "niche": "Accountants", "city": "Karachi", "status": "replied", "last_action": "Reply received (question)", "last_action_timestamp": "2026-07-24 09:33"},
    {"business_name": "Ledger & Co.", "niche": "Accountants", "city": "Karachi", "status": "verified", "last_action": "Verified into CRM", "last_action_timestamp": "2026-07-24 09:25"},
    {"business_name": "Prime Tax Advisors", "niche": "Accountants", "city": "Karachi", "status": "not_interested", "last_action": "Marked not interested (auto)", "last_action_timestamp": "2026-07-24 09:18"},
    {"business_name": "UrbanCut Salon", "niche": "Salons", "city": "Islamabad", "status": "mailed", "last_action": "Cold email sent", "last_action_timestamp": "2026-07-24 09:10"},
    {"business_name": "Glow Aesthetics", "niche": "Salons", "city": "Islamabad", "status": "interested_awaiting_review", "last_action": "Positive reply received", "last_action_timestamp": "2026-07-23 17:04"},
    {"business_name": "FitZone Gym", "niche": "Gyms", "city": "Rawalpindi", "status": "new", "last_action": "Scraped", "last_action_timestamp": "2026-07-23 16:41"},
]
