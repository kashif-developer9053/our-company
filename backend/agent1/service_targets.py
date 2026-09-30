"""Who to hunt when you are selling something other than a website.

Website work is sold on a visible defect — no site, site down, slow — and the
audit finds that from outside. CRM, ERP and booking work cannot be detected
that way: a business with a flawless website may still be tracking enquiries in
a notebook. Qualifying those leads on website faults is simply the wrong test,
and it rejects the best prospects, because a company that already invested in
its site is a company that invests.

So for non-website services the filter changes shape:

  * the NICHE carries the signal — a business type that inherently runs
    bookings, stock or client files is a prospect whatever its website looks
    like;
  * SIZE decides whether they will buy from us. A business large enough to
    already run this software has it, and Bata or Honda will never answer a
    cold message. A one-person shop has nothing to systematise. The target is
    the middle: established enough to feel the pain, small enough that one
    person decides.
"""

from __future__ import annotations

# service -> what it means and who buys it.
#
# `niches` are Google Maps search terms: a business TYPE, never a solution
# phrase, since searching "CRM for clinics" returns CRM vendors.
SERVICES: dict[str, dict] = {
    "website": {
        "label": "Website design / redevelopment",
        "signal": "site_defect",
        "niches": [],          # any niche; the audit decides
        "pain": "customers looking them up online find nothing, or a site that fails",
    },
    "crm": {
        "label": "CRM / customer & enquiry management",
        "signal": "niche",
        # Businesses whose money depends on chasing enquiries and repeat
        # customers. They lose deals in a notebook, which is the pitch.
        "niches": [
            "real estate agents", "property dealers", "travel agencies",
            "insurance agents", "recruitment agencies", "law firms",
            "immigration consultants", "tour operators", "car dealerships",
            "interior designers", "event planners", "wedding planners",
            "freight forwarders", "advertising agencies",
        ],
        "pain": "enquiries arrive by phone and WhatsApp and get lost before anyone follows up",
    },
    "erp": {
        "label": "ERP / inventory & production",
        "signal": "niche",
        # Anyone holding stock or running production. Spreadsheets stop
        # working somewhere around the second warehouse.
        "niches": [
            "furniture manufacturers", "textile mills", "garment factories",
            "food processing units", "packaging companies", "steel traders",
            "chemical distributors", "auto parts wholesalers",
            "pharmaceutical distributors", "electronics wholesalers",
            "construction material suppliers", "paper mills",
            "plastic manufacturers", "tile and sanitary distributors",
        ],
        "pain": "stock, orders and production are tracked on paper or in spreadsheets",
    },
    "booking": {
        "label": "Appointment / booking system",
        "signal": "niche",
        # Time-slot businesses. Every phone booking is staff time, and every
        # missed call is a lost slot.
        "niches": [
            "dental clinics", "physiotherapy clinics", "skin clinics",
            "diagnostic labs", "veterinary clinics", "beauty salons",
            "barber shops", "spas", "gyms", "fitness studios",
            "driving schools", "photography studios", "car service centres",
        ],
        "pain": "every appointment is booked by phone, and missed calls are lost bookings",
    },
    "lms": {
        "label": "School / learning management",
        "signal": "niche",
        "niches": [
            "private schools", "montessori schools", "tuition centres",
            "coaching academies", "language institutes", "computer training centres",
            "driving schools", "vocational training institutes",
        ],
        "pain": "admissions, fees, attendance and results are kept on paper",
    },
    "pos": {
        "label": "Point of sale / retail system",
        "signal": "niche",
        "niches": [
            "furniture showrooms", "electronics showrooms", "clothing stores",
            "shoe stores", "mobile phone shops", "hardware stores",
            "pharmacies", "grocery stores", "bakeries", "restaurants",
            "cafes", "auto parts shops",
        ],
        "pain": "sales and stock are recorded by hand, so nobody knows what is selling",
    },
}

DEFAULT_SERVICE = "website"

# Size window for a software sale, in Google reviews. Below the floor a
# business is too small to have the problem; above the ceiling it is large
# enough to already own the software and to ignore a cold message.
#
# Chosen from the data: local shops and clinics sit in the tens, established
# regional firms in the low hundreds, national chains in the thousands.
SOFTWARE_MIN_REVIEWS = 5
# Lowered from 800 on the CEO's call. At 800 the net was catching established
# regional firms that already run a system and never answer cold outreach; the
# businesses that actually reply sit well under a hundred reviews.
SOFTWARE_MAX_REVIEWS = 100


def get(service: str) -> dict:
    return SERVICES.get((service or "").strip().lower(), SERVICES[DEFAULT_SERVICE])


def is_website_service(service: str) -> bool:
    return get(service).get("signal") == "site_defect"


def niches_for(service: str) -> list[str]:
    return list(get(service).get("niches") or [])


def qualifies(service: str, lead: dict) -> tuple[bool, str]:
    """Is this lead worth collecting for the service being sold?

    For website work the site audit already decided, so this defers to it.
    For everything else the audit is the wrong test and size is the real one.
    """
    if is_website_service(service):
        audit = lead.get("site_audit") or {}
        if audit.get("qualified"):
            return True, ""
        return False, "website is fine — nothing to sell them"

    reviews = lead.get("reviews_count")
    if isinstance(reviews, int):
        if reviews > SOFTWARE_MAX_REVIEWS:
            return False, (f"{reviews:,} reviews — big enough to already run this "
                           f"software, and too big to answer a cold message")
        if reviews < SOFTWARE_MIN_REVIEWS:
            return False, (f"only {reviews} reviews — likely too small to have the "
                           f"problem this software solves")

    # No review data is not a rejection: plenty of real businesses have none,
    # and the ICP gate already removes the national brands by name.
    return True, ""


def collection_reason(service: str, lead: dict) -> str:
    """Why this lead was collected, in terms of what we are selling."""
    cfg = get(service)
    if is_website_service(service):
        return (lead.get("site_audit") or {}).get("summary", "")
    name = lead.get("business_name") or "This business"
    reviews = lead.get("reviews_count")
    size = f" ({reviews} reviews)" if isinstance(reviews, int) and reviews else ""
    return (f"{name}{size} is the kind of business where {cfg['pain']} — "
            f"a fit for {cfg['label'].lower()}.")
