"""
Deterministic pre-LLM mapper: existing category strings → normalized_category keys.

Two entry points:
  map_from_line_category(line_cat)   — old line_category / Labeller labels
  map_from_merchant_key(merchant)    — substring match on lowercase merchant name

Both return a normalized_category key (str) or None when no mapping exists.
None means the transaction should be sent to the LLM for classification.
"""

from __future__ import annotations

# ── Old line_category values + Labeller human-readable labels ───────────────
# None values = savings/investment rows that don't map to the spend taxonomy.
LINE_CATEGORY_TO_NORMALIZED: dict[str, str | None] = {
    # Legacy line_category slugs
    "rent":               "rent",
    "health_insurance":   "health_insurance",
    "groceries":          "groceries_food",
    "transport":          "transport",
    "telecom":            "telecom",
    "utilities":          "housing",
    "dining":             "restaurants",
    "coffee":             "restaurants",
    "entertainment":      "digital_goods",
    "clothing":           "clothing",
    "electronics":        "digital_goods",
    "pharmacy":           "health_other",
    "bars":               "restaurants",
    "streaming":          "digital_goods",
    "savings_transfer":   None,
    "other":              "wants_other",
    "salary":             "salary",
    "refund":             "extras_other",
    "income":             "salary",
    "investment":         None,
    # Labeller human-readable labels (from agents/labeller/tools.py)
    "Grocery Stores":          "groceries_food",
    "Supermarkets":            "groceries_food",
    "Organic & Specialty Food":"groceries_food",
    "Bakeries":                "groceries_food",
    "Electronics Stores":      "digital_goods",
    "Streaming Services":      "digital_goods",
    "Apps & Software":         "digital_goods",
    "Music Streaming":         "digital_goods",
    "Gaming":                  "digital_goods",
    "Cloud Services":          "digital_goods",
    "Restaurants":             "restaurants",
    "Fast Food":               "restaurants",
    "Food Delivery":           "restaurants",
    "Coffee Shops":            "restaurants",
    "Bars & Nightlife":        "restaurants",
    "Bakeries & Cafes":        "restaurants",
    "Catering":                "restaurants",
    "Clothing & Fashion":      "clothing",
    "Shoes":                   "clothing",
    "Sportswear":              "clothing",
    "Public Transport":        "transport",
    "Ride-hailing":            "transport",
    "Bike & Scooter":          "transport",
    "Parking":                 "car",
    "Fuel & Gas":              "car",
    "Car Leasing":             "car",
    "Car Wash":                "car",
    "Auto Parts":              "car",
    "Car Insurance":           "car",
    "Telecommunications":      "telecom",
    "Mobile":                  "telecom",
    "Internet":                "telecom",
    "Insurance":               "health_insurance",
    "Health Insurance":        "health_insurance",
    "Fitness & Sports":        "sports",
    "Sports Equipment":        "sports",
    "Gym":                     "sports",
    "Accommodation":           "travel_holidays",
    "Flights":                 "travel_holidays",
    "Travel Agencies":         "travel_holidays",
    "Car Rental":              "travel_holidays",
    "Pharmacies":              "health_other",
    "Medical Services":        "health_other",
    "Dental":                  "health_other",
    "Optical":                 "health_other",
    "Utilities":               "housing",
    "Home Improvement":        "housing",
    "Furniture & Decor":       "housing",
    "Household Supplies":      "housing",
    "Cleaning Services":       "housing",
    "Wellbeing":               "wellbeing",
    "Spa & Beauty":            "wellbeing",
    "Hair & Grooming":         "wellbeing",
    "Banking Fees":            "extras_other",
    "ATM":                     "extras_other",
    "Taxes":                   "extras_other",
    "Online Shopping":         "wants_other",
    "Department Stores":       "wants_other",
    "Books & Education":       "wants_other",
    "Gifts":                   "wants_other",
    "Charity":                 "wants_other",
    "Entertainment & Culture": "wants_other",
    "Investment & Savings":    None,
    "Transfers":               None,
    "Salary":                  "salary",
    "Twint Incoming":          "twint_credit",
    "Twint Outgoing":          "twint_debit",
}


def map_from_line_category(line_cat: str | None) -> str | None:
    """Return normalized_category key for a known line_category string.

    Returns None when there is no mapping or when the category maps to
    savings/investments (which don't belong in the spend taxonomy).
    """
    if not line_cat:
        return None
    return LINE_CATEGORY_TO_NORMALIZED.get(line_cat)


# ── Merchant substring → normalized_category (Swiss-focused) ────────────────
# Ordered: longer/more-specific patterns first. Case-insensitive (caller lowercases).
_MERCHANT_NORMALIZED_RULES: list[tuple[str, str]] = [
    # Groceries
    ("migros",       "groceries_food"),
    ("coop",         "groceries_food"),
    ("aldi",         "groceries_food"),
    ("lidl",         "groceries_food"),
    ("denner",       "groceries_food"),
    ("volg",         "groceries_food"),
    ("spar",         "groceries_food"),
    ("manor food",   "groceries_food"),
    # Streaming / digital
    ("netflix",      "digital_goods"),
    ("spotify",      "digital_goods"),
    ("disney+",      "digital_goods"),
    ("disney plus",  "digital_goods"),
    ("apple.com/bill","digital_goods"),
    ("google play",  "digital_goods"),
    ("play.google",  "digital_goods"),
    ("adobe",        "digital_goods"),
    ("microsoft",    "digital_goods"),
    ("github",       "digital_goods"),
    ("amazon prime", "digital_goods"),
    ("youtube",      "digital_goods"),
    ("hbo",          "digital_goods"),
    ("twitch",       "digital_goods"),
    ("chatgpt",      "digital_goods"),
    ("openai",       "digital_goods"),
    ("anthropic",    "digital_goods"),
    # Electronics
    ("digitec",      "digital_goods"),
    ("galaxus",      "digital_goods"),
    ("mediamarkt",   "digital_goods"),
    ("apple store",  "digital_goods"),
    # Restaurants / food
    ("starbucks",    "restaurants"),
    ("mcdonalds",    "restaurants"),
    ("mc donalds",   "restaurants"),
    ("burger king",  "restaurants"),
    ("kfc",          "restaurants"),
    ("pizza",        "restaurants"),
    ("sushi",        "restaurants"),
    ("doordash",     "restaurants"),
    ("uber eats",    "restaurants"),
    ("just eat",     "restaurants"),
    ("eat.ch",       "restaurants"),
    ("tibits",       "restaurants"),
    ("five guys",    "restaurants"),
    ("nordsee",      "restaurants"),
    # Clothing
    ("zara",         "clothing"),
    ("h&m",          "clothing"),
    ("hm.com",       "clothing"),
    ("zalando",      "clothing"),
    ("uniqlo",       "clothing"),
    ("c&a",          "clothing"),
    ("about you",    "clothing"),
    ("peek&cloppenburg", "clothing"),
    # Transport (public)
    ("sbb",          "transport"),
    ("bls",          "transport"),
    ("postauto",     "transport"),
    ("zvv",          "transport"),
    ("bvb",          "transport"),   # Basel tram
    ("tpg",          "transport"),   # Geneva tram
    ("reka",         "transport"),
    ("uber",         "transport"),
    # Car
    ("shell",        "car"),
    ("esso",         "car"),
    ("agrola",       "car"),
    ("tamoil",       "car"),
    ("parkings",     "car"),
    ("parking",      "car"),
    ("q8",           "car"),
    ("autec",        "car"),
    # Telecom
    ("swisscom",     "telecom"),
    ("sunrise",      "telecom"),
    ("salt.ch",      "telecom"),
    ("upc",          "telecom"),
    ("wingo",        "telecom"),
    # Health insurance
    ("helsana",      "health_insurance"),
    ("swica",        "health_insurance"),
    ("css versicherung", "health_insurance"),
    ("concordia",    "health_insurance"),
    ("assura",       "health_insurance"),
    ("visana",       "health_insurance"),
    ("sanitas",      "health_insurance"),
    ("atupri",       "health_insurance"),
    # Health other
    ("apotheke",     "health_other"),
    ("pharmacy",     "health_other"),
    ("pharmacie",    "health_other"),
    ("amavita",      "health_other"),
    ("zur rose",     "health_other"),
    ("toppharm",     "health_other"),
    ("notfallapotheke", "health_other"),
    # Sports
    ("fitnesspark",  "sports"),
    ("fitnesscenter", "sports"),
    ("gym",          "sports"),
    ("ochsner sport", "sports"),
    ("decathlon",    "sports"),
    ("intersport",   "sports"),
    # Travel
    ("airbnb",       "travel_holidays"),
    ("booking.com",  "travel_holidays"),
    ("hotels.com",   "travel_holidays"),
    ("expedia",      "travel_holidays"),
    ("lufthansa",    "travel_holidays"),
    ("swiss air",    "travel_holidays"),
    ("swissair",     "travel_holidays"),
    ("easyjet",      "travel_holidays"),
    ("ryanair",      "travel_holidays"),
    ("edelweiss",    "travel_holidays"),
    ("tui",          "travel_holidays"),
    ("kuoni",        "travel_holidays"),
    # Housing
    ("ikea",         "housing"),
    ("do it",        "housing"),   # Do it + Garden CH
    ("bauhaus",      "housing"),
    ("hornbach",     "housing"),
    ("obi ",         "housing"),
    # Wellbeing
    ("douglas",      "wellbeing"),
    ("dm ",          "wellbeing"),
    ("rituals",      "wellbeing"),
    ("l'occitane",   "wellbeing"),
    # Salary / income (exact match heuristics — caller should also check amount > 0)
    ("lohn",         "salary"),
    ("salaire",      "salary"),
    ("gehalt",       "salary"),
    # Twint (refined by amount sign downstream)
    ("twint",        "twint_debit"),
]


def map_from_merchant_key(merchant_lower: str) -> str | None:
    """Return normalized_category key by substring-matching a lowercased merchant.

    Returns None when no pattern matches (transaction goes to the LLM).
    Note: twint rows are returned as 'twint_debit' by default; callers that
    know the sign can upgrade to 'twint_credit' for positive amounts.
    """
    for pattern, norm_key in _MERCHANT_NORMALIZED_RULES:
        if pattern in merchant_lower:
            return norm_key
    return None
