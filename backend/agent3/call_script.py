"""The Roman Urdu script a cold caller reads from.

A WhatsApp message is one paragraph the reader can take at their own pace. A
call is different: the first eight seconds decide whether the other person
hangs up, and the caller has no time to think. So the script is written to be
spoken, in the order it is spoken, with the awkward parts already answered.

Roman Urdu, because that is how a cold call in Pakistan actually goes — not
formal Urdu script, which nobody reads aloud naturally, and not English, which
makes a shopkeeper switch to being suspicious.

The script is DERIVED, not written by a model, for the same reason the lead
diagnosis is: a model asked to invent a reason invents a problem the business
does not have, and the caller finds out mid-call.
"""

from __future__ import annotations

from agent1.purposes import PURPOSES

# What we are selling, in the words a caller says out loud. The English
# product names stay where a Pakistani business owner would use them —
# "website" and "system" are loanwords here; "point of sale" is not.
_PITCH_UR: dict[str, dict] = {
    "website": {
        "what": "aap ki business ki apni website",
        "problem": "abhi jab koi Google par aap ka kaam search karta hai, "
                   "to aap ka naam nahi aata — customer kisi aur ke paas chala jata hai",
        "benefit": "log aap ko online dhoond kar seedha call ya WhatsApp kar sakenge",
        "ask": "abhi customers aap tak kaise pohanchte hain — zyada tar walk-in ya "
               "reference se?",
    },
    "booking": {
        "what": "online appointment booking ka system",
        "problem": "har appointment phone par leni parti hai, aur jab line busy ho "
                   "ya raat ho to customer wait nahi karta",
        "benefit": "customer raat ke 11 baje bhi khud appointment book kar lega, "
                   "aur automatic WhatsApp reminder se log bhoolte nahi",
        "ask": "din mein takreeban kitni bookings phone par aati hain?",
    },
    "erp": {
        "what": "stock aur orders ka system",
        "problem": "maal aur orders register ya copy par chalte hain, to pata nahi "
                   "chalta kaunsa order kahan hai aur kya khatam ho raha hai",
        "benefit": "ek jagah se pata chal jayega kaunsa order kis stage par hai aur "
                   "stock mein kya kam hai — godown jane ki zaroorat nahi",
        "ask": "abhi stock aur orders ka hisaab kaise rakhte hain — register par?",
    },
    "crm": {
        "what": "customer aur inquiry management ka system",
        "problem": "inquiries WhatsApp aur phone par aati hain, phir follow-up "
                   "reh jata hai aur customer kisi aur se kaam karwa leta hai",
        "benefit": "har inquiry record ho jayegi follow-up date ke sath, koi "
                   "customer bhoolne se zaya nahi hoga",
        "ask": "inquiries ka record abhi kaise rakhte hain — WhatsApp aur diary par?",
    },
    "pos": {
        "what": "billing aur stock ka point of sale system",
        "problem": "sale aur stock hath se likha jata hai, to mahine ke akhir tak "
                   "pata nahi chalta kya sab se zyada bik raha hai",
        "benefit": "rozana ki sale aur kya khatam ho raha hai, sab screen par "
                   "dikhega — ginti karne ki zaroorat nahi",
        "ask": "rozana ki sale ka hisaab abhi kaise karte hain?",
    },
    "lms": {
        "what": "school management system — admission, fees aur attendance",
        "problem": "admission, fees aur attendance alag alag registers par chalte "
                   "hain, aur parents ko har cheez ke liye school aana parta hai",
        "benefit": "parents online fees aur result dekh sakenge, aur staff ka "
                   "paperwork ka waqt bach jayega",
        "ask": "fees aur attendance ka record abhi kaise manage karte hain?",
    },
    "seo": {
        "what": "Google par aap ki ranking behtar karna",
        "problem": "website to hai, lekin jab koi search karta hai to aap se pehle "
                   "doosri companies aati hain",
        "benefit": "jo log already aap ka kaam search kar rahe hain, wo aap tak "
                   "pohanch jayenge",
        "ask": "zyada tar customers kahan se aate hain — Google se ya reference se?",
    },
}

# Objections a caller actually hears, and what to say back. Each answer is
# short on purpose: a long rebuttal sounds rehearsed and loses the call.
OBJECTIONS: list[dict] = [
    {"q": "\"Abhi zaroorat nahi hai\"",
     "a": "Bilkul sir, abhi kuch khareedna nahi hai. Main sirf 2 minute mein bata "
          "doon ke kaise kaam karta hai — aage aap ki marzi."},
    {"q": "\"Kitna kharcha aayega?\"",
     "a": "Sir ye depend karta hai ke aap ko kitna chahiye. Pehle main aap ka kaam "
          "samajh loon, phir exact quote bhej doon ga — koi charge nahi iska."},
    {"q": "\"WhatsApp par bhej dain\"",
     "a": "Zaroor sir, abhi bhej deta hoon. Bas ek cheez pooch loon taake sahi "
          "cheez bhejoon — {ask_short}"},
    {"q": "\"Hum khud dekh lenge\" / \"Hamara banda hai\"",
     "a": "Theek hai sir. Agar kabhi extra kaam ho ya koi cheez atak jaye to yaad "
          "rakhiyega — hum Islamabad se hi hain."},
    {"q": "\"Busy hoon, baad mein call karain\"",
     "a": "Ji bilkul sir, main waqt zaya nahi karta. Kis waqt call karoon — sham "
          "ko ya kal subah?"},
    {"q": "Koi aur poochta hai \"aap ne number kahan se liya?\"",
     "a": "Sir aap ki business Google Maps par listed hai, wahan se public number "
          "liya tha. Agar aap kahen to dobara call nahi karunga."},
]


def _spoken_name(lead: dict) -> str:
    """The business name as the caller should say it."""
    n = (lead.get("business_name") or "").strip()
    # Strip the bracketed noise Maps listings carry, which nobody says aloud.
    for cut in ("(", "|", " - ", "،"):
        if cut in n:
            n = n.split(cut)[0].strip()
    return n or "aap ki business"


def build(lead: dict, caller_name: str = "") -> dict:
    """The full call script for one lead, in the order it is spoken.

    `caller_name` is whoever is making the call — the script says his name,
    not the CEO's, because the person on the other end will ask for him by it.
    """
    purposes = [p for p in (lead.get("purposes") or []) if p in _PITCH_UR]
    if not purposes:
        purposes = ["website"]
    main = _PITCH_UR[purposes[0]]
    name = _spoken_name(lead)
    # Spoken aloud, so "islamabad" from a scrape becomes "Islamabad".
    city = (lead.get("city") or "").strip().title()

    # Was this lead already messaged? The caller must not re-introduce the
    # company to someone who has our message open in front of them.
    wa = lead.get("whatsapp")
    messaged = bool(isinstance(wa, dict) and wa.get("status") in
                    ("message_sent", "replied", "interested", "not_interested"))

    opening = (
        f"Assalam o alaikum, {name} se baat ho rahi hai?"
        if not messaged else
        f"Assalam o alaikum, {name} se baat ho rahi hai? Sir maine aap ko "
        f"WhatsApp par message kiya tha."
    )

    from shared import company_profile
    prof = company_profile.get_profile()
    who = (caller_name or "").strip() or prof.get("sender_name", "") or "main"
    firm = prof.get("company_name", "") or "hamari company"
    intro = (f"Sir main {who} baat kar raha hoon {firm} se. Hum "
             + (f"{city} mein " if city else "")
             + "software banate hain — websites aur business systems.")

    reason = (f"Aap ko call isliye kiya ke {main['problem']}.")
    offer = (f"Hum {main['what']} bana dete hain, jis se {main['benefit']}.")
    ask = main["ask"]

    extra = ""
    if len(purposes) > 1:
        second = _PITCH_UR[purposes[1]]
        extra = (f"Agar zaroorat ho to {second['what']} bhi hum hi banate hain — "
                 f"lekin pehle ye wala dekh lete hain.")

    close_yes = ("Sir phir aisa karte hain — main aap ko WhatsApp par 2-3 kaam "
                 "bhej deta hoon jo humne pehle kiye hain. Dekh kar bata dijiyega. "
                 "Kal is waqt call kar loon?")
    close_no = ("Koi baat nahi sir, waqt dene ka shukriya. Main apna number "
                "WhatsApp kar deta hoon — kabhi zaroorat ho to yaad kar lijiyega.")

    # Objection answers that reference the ask get it filled in.
    ask_short = ask.rstrip("?") + "?"
    objections = [{"q": o["q"], "a": o["a"].replace("{ask_short}", ask_short)}
                  for o in OBJECTIONS]

    return {
        "language": "roman_urdu",
        "already_messaged": messaged,
        "steps": [
            {"n": 1, "title": "Salam aur confirm karein", "say": opening},
            {"n": 2, "title": "Apna taaruf", "say": intro},
            {"n": 3, "title": "Call ki wajah", "say": reason},
            {"n": 4, "title": "Kya banate hain", "say": offer},
            {"n": 5, "title": "Sawal poochein — phir CHUP rahein",
             "say": ask,
             "note": "Sawal poochne ke baad bolna band kar dein. Jo pehle bolta "
                     "hai wo deal haar jata hai."},
        ],
        "extra_service": extra,
        "close_interested": close_yes,
        "close_not_interested": close_no,
        "objections": objections,
        "rules": [
            "Aahista aur araam se bolein — jaldi bolna sales call lagta hai.",
            "Pehle 10 second mein naam aur wajah bata dein.",
            "Qeemat phone par na batayein. Pehle kaam samjhein.",
            "Agar wo mana kar dein to bahas na karein — shukriya keh kar band karein.",
            "Call ke foran baad status aur remarks update karein.",
        ],
    }
