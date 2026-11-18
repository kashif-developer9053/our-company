"""City to country lookup, so the hunt form can fill the country in for you.

The CEO asked for this after typing a city and a country that do not go
together ("Islamabad, India"). A mismatch like that is not caught anywhere: the
scraper happily searches the nonsense string, Google Maps returns little or
nothing, and the hunt reports "no leads found" for what looks like a perfectly
reasonable request. The wasted run is bad; the misleading conclusion — that
there are no photographers in Islamabad worth contacting — is worse.

Validating after the fact would only produce an error message. Suggesting the
country as soon as the city is typed removes the possibility instead, which is
what was asked for.

Coverage is deliberately uneven: every Pakistani city we would plausibly hunt,
since that is the home market, plus the large cities of the countries we might
reasonably sell into. It is a convenience, not a gazetteer — an unknown city
simply offers no suggestion and the CEO types the country himself.
"""

from __future__ import annotations

# city (lowercase) -> country, canonical spelling as the scraper wants it.
CITY_COUNTRY: dict[str, str] = {
    # ---- Pakistan: the home market, so the list is thorough -------------
    "islamabad": "Pakistan", "rawalpindi": "Pakistan", "lahore": "Pakistan",
    "karachi": "Pakistan", "faisalabad": "Pakistan", "multan": "Pakistan",
    "peshawar": "Pakistan", "quetta": "Pakistan", "sialkot": "Pakistan",
    "gujranwala": "Pakistan", "hyderabad": "Pakistan", "sukkur": "Pakistan",
    "bahawalpur": "Pakistan", "sargodha": "Pakistan", "abbottabad": "Pakistan",
    "mardan": "Pakistan", "mingora": "Pakistan", "swat": "Pakistan",
    "murree": "Pakistan", "gilgit": "Pakistan", "skardu": "Pakistan",
    "muzaffarabad": "Pakistan", "mirpur": "Pakistan", "jhelum": "Pakistan",
    "gujrat": "Pakistan", "sahiwal": "Pakistan", "okara": "Pakistan",
    "kasur": "Pakistan", "sheikhupura": "Pakistan", "rahim yar khan": "Pakistan",
    "dera ghazi khan": "Pakistan", "larkana": "Pakistan", "nawabshah": "Pakistan",
    "mandi bahauddin": "Pakistan", "chiniot": "Pakistan", "jhang": "Pakistan",
    "wah cantt": "Pakistan", "taxila": "Pakistan", "attock": "Pakistan",
    "chakwal": "Pakistan", "kohat": "Pakistan", "bannu": "Pakistan",
    "dera ismail khan": "Pakistan", "turbat": "Pakistan", "gwadar": "Pakistan",
    "khuzdar": "Pakistan", "zhob": "Pakistan", "chaman": "Pakistan",
    "nowshera": "Pakistan", "charsadda": "Pakistan", "swabi": "Pakistan",
    "haripur": "Pakistan", "mansehra": "Pakistan", "batkhela": "Pakistan",
    "vehari": "Pakistan", "khanewal": "Pakistan", "burewala": "Pakistan",
    "kamoke": "Pakistan", "hafizabad": "Pakistan", "daska": "Pakistan",
    "narowal": "Pakistan", "pakpattan": "Pakistan", "bhakkar": "Pakistan",
    "mianwali": "Pakistan", "layyah": "Pakistan", "muzaffargarh": "Pakistan",
    "kotli": "Pakistan", "bhimber": "Pakistan", "rawalakot": "Pakistan",
    "hunza": "Pakistan", "chitral": "Pakistan", "naran": "Pakistan",
    "kaghan": "Pakistan", "sost": "Pakistan", "jacobabad": "Pakistan",
    "shikarpur": "Pakistan", "khairpur": "Pakistan", "mirpurkhas": "Pakistan",
    "tando adam": "Pakistan", "badin": "Pakistan", "thatta": "Pakistan",
    "dadu": "Pakistan", "ghotki": "Pakistan", "kandhkot": "Pakistan",

    # ---- UAE / Gulf: a common market for Pakistani agencies -------------
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "sharjah": "United Arab Emirates", "ajman": "United Arab Emirates",
    "ras al khaimah": "United Arab Emirates", "fujairah": "United Arab Emirates",
    "al ain": "United Arab Emirates", "umm al quwain": "United Arab Emirates",
    "doha": "Qatar", "al rayyan": "Qatar",
    "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia", "mecca": "Saudi Arabia",
    "medina": "Saudi Arabia", "dammam": "Saudi Arabia", "khobar": "Saudi Arabia",
    "kuwait city": "Kuwait", "manama": "Bahrain", "muscat": "Oman",
    "salalah": "Oman",

    # ---- United Kingdom -------------------------------------------------
    "london": "United Kingdom", "manchester": "United Kingdom",
    "birmingham": "United Kingdom", "leeds": "United Kingdom",
    "glasgow": "United Kingdom", "edinburgh": "United Kingdom",
    "liverpool": "United Kingdom", "bristol": "United Kingdom",
    "sheffield": "United Kingdom", "bradford": "United Kingdom",
    "nottingham": "United Kingdom", "leicester": "United Kingdom",
    "newcastle": "United Kingdom", "cardiff": "United Kingdom",
    "belfast": "United Kingdom", "luton": "United Kingdom",
    "slough": "United Kingdom", "oldham": "United Kingdom",

    # ---- United States / Canada -----------------------------------------
    "new york": "United States", "los angeles": "United States",
    "chicago": "United States", "houston": "United States",
    "phoenix": "United States", "philadelphia": "United States",
    "san antonio": "United States", "san diego": "United States",
    "dallas": "United States", "austin": "United States",
    "san francisco": "United States", "seattle": "United States",
    "denver": "United States", "boston": "United States",
    "atlanta": "United States", "miami": "United States",
    "detroit": "United States", "washington": "United States",
    "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "calgary": "Canada", "ottawa": "Canada", "edmonton": "Canada",
    "mississauga": "Canada", "brampton": "Canada", "surrey": "Canada",

    # ---- India: listed BECAUSE of the Islamabad/India mix-up ------------
    # These are the real Indian cities, so typing one genuinely suggests
    # India — the point is that Islamabad is not among them.
    "delhi": "India", "new delhi": "India", "mumbai": "India",
    "bangalore": "India", "bengaluru": "India", "chennai": "India",
    "kolkata": "India", "pune": "India", "ahmedabad": "India",
    "jaipur": "India", "lucknow": "India", "surat": "India",
    "kanpur": "India", "nagpur": "India", "indore": "India",
    "bhopal": "India", "patna": "India", "ludhiana": "India",
    "agra": "India", "amritsar": "India", "chandigarh": "India",
    "kochi": "India", "coimbatore": "India", "visakhapatnam": "India",
    "gurgaon": "India", "gurugram": "India", "noida": "India",

    # ---- Bangladesh / Sri Lanka / Nepal ---------------------------------
    "dhaka": "Bangladesh", "chittagong": "Bangladesh", "sylhet": "Bangladesh",
    "khulna": "Bangladesh", "rajshahi": "Bangladesh",
    "colombo": "Sri Lanka", "kandy": "Sri Lanka", "galle": "Sri Lanka",
    "kathmandu": "Nepal", "pokhara": "Nepal",

    # ---- Australia / New Zealand ----------------------------------------
    "sydney": "Australia", "melbourne": "Australia", "brisbane": "Australia",
    "perth": "Australia", "adelaide": "Australia", "canberra": "Australia",
    "gold coast": "Australia", "auckland": "New Zealand",
    "wellington": "New Zealand", "christchurch": "New Zealand",

    # ---- Europe ----------------------------------------------------------
    "dublin": "Ireland", "cork": "Ireland",
    "paris": "France", "lyon": "France", "marseille": "France",
    "berlin": "Germany", "munich": "Germany", "hamburg": "Germany",
    "frankfurt": "Germany", "cologne": "Germany",
    "madrid": "Spain", "barcelona": "Spain", "valencia": "Spain",
    "rome": "Italy", "milan": "Italy", "naples": "Italy",
    "amsterdam": "Netherlands", "rotterdam": "Netherlands",
    "brussels": "Belgium", "vienna": "Austria", "zurich": "Switzerland",
    "geneva": "Switzerland", "stockholm": "Sweden", "oslo": "Norway",
    "copenhagen": "Denmark", "helsinki": "Finland", "warsaw": "Poland",
    "prague": "Czech Republic", "budapest": "Hungary", "lisbon": "Portugal",
    "athens": "Greece", "istanbul": "Turkey", "ankara": "Turkey",

    # ---- Africa / Asia (selected) ---------------------------------------
    "cairo": "Egypt", "alexandria": "Egypt", "lagos": "Nigeria",
    "abuja": "Nigeria", "nairobi": "Kenya", "johannesburg": "South Africa",
    "cape town": "South Africa", "durban": "South Africa",
    "casablanca": "Morocco", "tunis": "Tunisia",
    "singapore": "Singapore", "kuala lumpur": "Malaysia",
    "jakarta": "Indonesia", "bangkok": "Thailand", "manila": "Philippines",
    "hong kong": "Hong Kong", "tokyo": "Japan", "osaka": "Japan",
    "seoul": "South Korea", "beijing": "China", "shanghai": "China",
    "shenzhen": "China",
}

# Cities whose name exists in more than one country. Suggesting one would be a
# coin flip presented as a fact, so these deliberately suggest NOTHING and the
# CEO fills the country in himself.
#
# "hyderabad" is the sharp case: it is a large city in Pakistan AND in India.
# It maps to Pakistan above because that is this agency's market, but it is
# listed here so the UI asks rather than assumes.
AMBIGUOUS: set[str] = {
    "hyderabad",     # Pakistan (Sindh) and India (Telangana)
    "surrey",        # Canada (BC) and United Kingdom
    "washington",    # city (DC) and state
    "birmingham",    # United Kingdom and United States (Alabama)
    "newcastle",     # United Kingdom, Australia, South Africa
    "gujrat",        # Pakistan city vs Gujarat, the Indian state
}


def _key(city: str) -> str:
    return " ".join((city or "").strip().lower().split())


def country_for(city: str) -> str:
    """The country this city is in, or "" when unknown or ambiguous."""
    k = _key(city)
    if not k or k in AMBIGUOUS:
        return ""
    return CITY_COUNTRY.get(k, "")


def suggest(city: str) -> dict:
    """What the hunt form needs to fill the country in as the CEO types.

    Returns {country, ambiguous, known}. `ambiguous` true means the name is
    real but belongs to several countries, so ask instead of guessing.
    """
    k = _key(city)
    if not k:
        return {"country": "", "ambiguous": False, "known": False}
    if k in AMBIGUOUS:
        return {"country": "", "ambiguous": True, "known": True}
    country = CITY_COUNTRY.get(k, "")
    return {"country": country, "ambiguous": False, "known": bool(country)}


def mismatch(city: str, country: str) -> str:
    """Explain a city/country pair that cannot be right, else "".

    Only speaks when the city is known AND unambiguous AND the given country
    is a different, recognised country. Silence is the default: a gazetteer
    this small must never block a hunt over a city it has not heard of.
    """
    k = _key(city)
    given = " ".join((country or "").strip().lower().split())
    if not k or not given or k in AMBIGUOUS:
        return ""
    actual = CITY_COUNTRY.get(k)
    if not actual:
        return ""
    if given == actual.lower():
        return ""
    # Accept common alternative spellings of the right answer before objecting.
    aliases = {
        "united arab emirates": {"uae", "u.a.e.", "emirates"},
        "united kingdom": {"uk", "u.k.", "britain", "great britain", "england",
                           "scotland", "wales", "northern ireland"},
        "united states": {"usa", "us", "u.s.", "u.s.a.", "america"},
        "south korea": {"korea"},
        "czech republic": {"czechia"},
    }
    if given in aliases.get(actual.lower(), set()):
        return ""
    return (f"{city.strip().title()} is in {actual}, not {country.strip().title()}. "
            f"Searching the wrong country finds nothing and looks like an empty market.")


def known_cities() -> list[str]:
    """Every city the form can offer, title-cased, for the datalist."""
    return sorted({c.title() for c in CITY_COUNTRY})
