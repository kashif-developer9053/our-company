"""What this KIND of business would actually buy from us.

Outreach was pitching one thing — "your website is missing or weak" — to every
lead regardless of industry. That is a two-line message with nothing in it for
the reader, and it throws away the larger sale: a school does not just need a
website, it needs admissions enquiries, fee tracking, attendance and results.

This maps a niche to the systems that industry genuinely runs on, so the writer
can offer the website AND the software that fits, in the prospect's own
vocabulary. A school hears "attendance and exam results"; a clinic hears
"appointments and patient records". Neither hears "ERP".

Kept deterministic and data-driven rather than asked of the model: the model
invents plausible-sounding systems ("student CRM suite") that we would then
have to explain, and the phrasing here is what a Pakistani business owner
actually calls these things.
"""

from __future__ import annotations

import re

# Ordered: the first pattern that matches a niche wins, so put the specific
# ones before the general. Each entry lists systems in the order we would
# naturally pitch them — the most obviously useful first.
_NICHE_SERVICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"school|academy|college|montessori|education|tuition|institute|campus",
     ("a learning management system (LMS) for online classes and assignments",
      "a school management system for admissions, fees and records",
      "attendance management for students and staff",
      "an exam and result management system",
      "a parent portal with fee vouchers and progress reports")),

    (r"university|higher education",
     ("a learning management system for course delivery",
      "a student information and enrolment system",
      "an examination and transcript system",
      "a research and faculty portal")),

    (r"clinic|hospital|medical|dental|doctor|physio|ultrasound|skin|surgeon|health|pharma?cy",
     ("an appointment booking system patients can use online",
      "a patient record and history system",
      "automated appointment reminders on WhatsApp and SMS",
      "billing, invoicing and insurance claim tracking",
      "a doctor scheduling and clinic management system")),

    (r"lab|diagnostic|patholog",
     ("an online test booking and report delivery system",
      "a lab information management system",
      "automated report delivery to patients on WhatsApp")),

    (r"solicitor|law|legal|advocate|attorney|barrister|conveyanc",
     ("a case and matter management system",
      "a client intake and enquiry system",
      "document management with deadline and hearing reminders",
      "time tracking and billing")),

    (r"account|audit|tax|bookkeep|acca|ca firm",
     ("a client portal for documents and approvals",
      "practice management with deadline tracking",
      "automated invoicing and payment reminders",
      "a secure document management system")),

    # Deliberately no bare "ERP" here. An owner recognises "production planning
    # and order tracking" instantly; "an ERP" is a category name they then have
    # to decode, and it reads like every other vendor's brochure.
    (r"textile|mill|manufactur|factory|industr|packaging|spinning|garment",
     ("a production planning and order tracking system",
      "inventory and raw material management",
      "a barcode-based stock and dispatch system",
      "supplier and purchase order management",
      "production reporting dashboards")),

    (r"restaurant|cafe|food|bakery|catering|broast|pizza|hotel|dhaba",
     ("online ordering direct from your own site, without commission",
      "a point-of-sale and billing system",
      "table booking and delivery order management",
      "inventory and daily sales reporting")),

    (r"gym|fitness|salon|spa|beauty|parlour|barber",
     ("an online booking and class scheduling system",
      "membership and package management with renewal reminders",
      "automated reminders on WhatsApp",
      "attendance and trainer scheduling")),

    (r"furniture|showroom|store|shop|retail|mart|electronic|mobile|hardware",
     ("an online store so you can sell beyond walk-in customers",
      "inventory and stock management across branches",
      "a point-of-sale and billing system",
      "a customer database with follow-up reminders")),

    (r"real estate|propert|builder|construction|marketing|estate agent",
     ("a property listing portal with search and filters",
      "a system to track leads, viewings and follow-ups",
      "a project and installment tracking system",
      "automated client follow-up on WhatsApp")),

    (r"travel|tour|hajj|umrah|visa|ticket",
     ("an online booking and enquiry system",
      "a package and itinerary management system",
      "a customer database with automated follow-up",
      "payment and installment tracking")),

    (r"transport|logistic|courier|cargo|freight|movers",
     ("a shipment tracking system your customers can use",
      "fleet and driver management",
      "automated delivery updates on WhatsApp",
      "billing and consignment management")),

    (r"ngo|charity|welfare|trust|foundation",
     ("a donation system with online payments",
      "a donor management and receipting system",
      "a beneficiary and project tracking system")),

    (r"agri|farm|dairy|poultry|seed|fertiliz",
     ("an inventory and supply tracking system",
      "an order and distribution management system",
      "a dealer and customer portal")),
)

# Used when the niche does not match anything above. Deliberately broad but
# still concrete — never "digital transformation".
_DEFAULT_SERVICES = (
    "a customer management system (CRM) to track enquiries and follow-ups",
    "business automation to remove repetitive manual work",
    "inventory or order management",
    "automated customer follow-up on WhatsApp",
)


def services_for(niche: str, limit: int = 4) -> list[str]:
    """The systems this kind of business would plausibly buy, best first."""
    text = (niche or "").strip().lower()
    if text:
        for pattern, services in _NICHE_SERVICES:
            if re.search(pattern, text):
                return list(services[:limit])
    return list(_DEFAULT_SERVICES[:limit])


def services_line(niche: str, limit: int = 3) -> str:
    """The same list as one natural phrase, for dropping into a prompt."""
    items = services_for(niche, limit)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def audience_for(niche: str) -> str:
    """Who the business is actually trying to reach.

    "Customers" is vague and makes copy generic; a school is chasing parents,
    a clinic patients, a law firm clients. Naming them is what makes a message
    sound like it was written for that business.
    """
    text = (niche or "").strip().lower()
    if re.search(r"school|academy|college|montessori|education|tuition|institute|campus", text):
        return "parents looking for a school"
    if re.search(r"university|higher education", text):
        return "prospective students"
    if re.search(r"clinic|hospital|medical|dental|doctor|physio|health|lab|diagnostic", text):
        return "patients looking for treatment"
    if re.search(r"solicitor|law|legal|advocate|attorney", text):
        return "clients needing legal help"
    if re.search(r"account|audit|tax|bookkeep", text):
        return "businesses looking for an accountant"
    if re.search(r"restaurant|cafe|food|bakery|hotel", text):
        return "people deciding where to eat"
    if re.search(r"gym|fitness|salon|spa|beauty|parlour", text):
        return "people looking to book"
    if re.search(r"textile|mill|manufactur|factory|industr", text):
        return "buyers and distributors checking you out"
    if re.search(r"real estate|propert|builder|construction", text):
        return "buyers searching for property"
    return "customers looking for what you offer"
