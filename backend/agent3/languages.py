"""Which languages to offer for a lead, based on where the business is.

The WhatsApp desk offered English and Roman Urdu for every lead, which is
right for Pakistan and wrong everywhere else — a clinic in Jubail was being
messaged in Roman Urdu, and one in Mexico in a language nobody there reads.

Business language, not official language: Gulf businesses conduct a great deal
of work in English, so it stays on the list alongside Arabic rather than being
replaced by it. The aim is to offer the two or three a business owner there
would actually accept a message in, not to be exhaustive.

Country is the reliable signal, but 129 leads have no country recorded, so the
city is used as a fallback — a lead in Jubail is in Saudi Arabia whether or not
anyone wrote that down.
"""

from __future__ import annotations

# code -> (label, prompt instruction). The instruction is what the writer is
# told; "write in X" alone produces stilted translation, so each says how the
# language is actually used on WhatsApp.
LANGUAGES: dict[str, tuple[str, str]] = {
    "english": ("English", "Write in simple, clear English."),
    "roman_urdu": (
        "Roman Urdu",
        "Write in ROMAN URDU — Urdu typed in English letters, the way Pakistanis "
        "actually message on WhatsApp. NOT English, and not Urdu script. Keep "
        "product words in English (website, system, software, portal)."),
    "arabic": (
        "Arabic",
        "Write in ARABIC script, in the polite business register used on WhatsApp "
        "in the Gulf. Keep product words in English (website, system, software) — "
        "that is how they are said there. Begin with السلام عليكم."),
    "spanish": (
        "Spanish",
        "Write in SPANISH, in the polite 'usted' business register used in Mexico "
        "and Latin America. Keep product words in English where that is normal "
        "(website, software, marketing)."),
    "french": (
        "French",
        "Write in FRENCH, in the polite 'vous' business register. Keep product "
        "words in English where that is normal (website, software)."),
}

# Country -> languages to offer, best first. The first entry becomes the
# default button on each row.
_BY_COUNTRY: dict[str, tuple[str, ...]] = {
    "pakistan": ("roman_urdu", "english"),
    "saudi arabia": ("arabic", "english"),
    "united arab emirates": ("arabic", "english"),
    "uae": ("arabic", "english"),
    "qatar": ("arabic", "english"),
    "kuwait": ("arabic", "english"),
    "oman": ("arabic", "english"),
    "bahrain": ("arabic", "english"),
    "egypt": ("arabic", "english"),
    "jordan": ("arabic", "english"),
    "mexico": ("spanish", "english"),
    "spain": ("spanish", "english"),
    "argentina": ("spanish", "english"),
    "colombia": ("spanish", "english"),
    "chile": ("spanish", "english"),
    "france": ("french", "english"),
    "morocco": ("french", "arabic", "english"),
    "india": ("english",),
    "ireland": ("english",),
    "united kingdom": ("english",),
    "uk": ("english",),
    "united states": ("english",),
    "usa": ("english",),
    "canada": ("english",),
    "australia": ("english",),
}

# City -> country, for the many leads collected without a country recorded.
# Only cities we have actually hunted in; a missing entry simply falls back to
# English, which is never wrong, only sometimes suboptimal.
_CITY_COUNTRY: dict[str, str] = {
    # Pakistan
    "islamabad": "pakistan", "lahore": "pakistan", "karachi": "pakistan",
    "rawalpindi": "pakistan", "faisalabad": "pakistan", "haripur": "pakistan",
    "abbotabad": "pakistan", "abbottabad": "pakistan", "peshawar": "pakistan",
    "multan": "pakistan", "gujranwala": "pakistan", "sialkot": "pakistan",
    "quetta": "pakistan", "hyderabad": "pakistan", "gujrat": "pakistan",
    # Saudi Arabia
    "jubail": "saudi arabia", "riyadh": "saudi arabia", "jeddah": "saudi arabia",
    "dammam": "saudi arabia", "khobar": "saudi arabia", "mecca": "saudi arabia",
    "medina": "saudi arabia", "dhahran": "saudi arabia", "taif": "saudi arabia",
    # Gulf
    "dubai": "united arab emirates", "abu dhabi": "united arab emirates",
    "sharjah": "united arab emirates", "doha": "qatar", "manama": "bahrain",
    "muscat": "oman", "kuwait city": "kuwait",
    # Elsewhere
    "mexico": "mexico", "mexico city": "mexico", "guadalajara": "mexico",
    "monterrey": "mexico", "dublin": "ireland", "cork": "ireland",
    "london": "united kingdom", "manchester": "united kingdom",
    "birmingham": "united kingdom", "leeds": "united kingdom",
    "cardiff": "united kingdom",
}


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def languages_for(country: str = "", city: str = "") -> list[str]:
    """Language codes to offer for a lead, best first. Always at least English."""
    key = _norm(country)
    if key not in _BY_COUNTRY:
        # No country recorded, or one we do not know: infer from the city.
        key = _CITY_COUNTRY.get(_norm(city), "")
    codes = list(_BY_COUNTRY.get(key, ("english",)))
    if "english" not in codes:
        codes.append("english")
    return codes


def label_for(code: str) -> str:
    return LANGUAGES.get(code, LANGUAGES["english"])[0]


def instruction_for(code: str) -> str:
    """The wording handed to the message writer for this language."""
    return LANGUAGES.get(code, LANGUAGES["english"])[1]
