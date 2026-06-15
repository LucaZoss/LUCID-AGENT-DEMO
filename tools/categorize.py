"""
categorize_transaction — deterministic spending categorizer.

Priority order (first substring match wins, case-insensitive):
  1. savings  — explicit savings vehicles (VIAC, Swissquote, Säule …)
  2. want     — dining, entertainment, streaming, clothing, electronics, gym
  3. need     — groceries, housing, health insurance, pharma, transport, telecom

More-specific patterns are listed before broader ones within each tier so that
"Coop To Go" → want (matches "to go") before "Coop" → need.

The LLM fallback for truly ambiguous merchants (e.g. Manor for groceries vs.
clothing) is deliberately absent here — that belongs in a future skill. For now,
we resolve ambiguity conservatively: when a merchant could be need or want, we
prefer want (the safer assumption for budget-overspend detection).
"""

from __future__ import annotations

from contracts import Transaction

# (substring, category) — checked in order; first match wins.
_RULES: list[tuple[str, str]] = [
    # ── Savings ─────────────────────────────────────────────────────────────
    ("viac",          "savings"),
    ("frankly",       "savings"),
    ("swissquote",    "savings"),
    ("sparkonto",     "savings"),
    ("säule",         "savings"),
    ("3a",            "savings"),
    ("yuh",           "savings"),
    ("neon invest",   "savings"),

    # ── Wants: dining & cafés ────────────────────────────────────────────────
    ("starbucks",     "want"),
    ("mcdonald",      "want"),
    ("burger king",   "want"),
    ("subway",        "want"),
    ("tibits",        "want"),
    ("zeughauskeller","want"),
    ("lily's",        "want"),
    ("les halles",    "want"),
    ("sprüngli",      "want"),
    ("moods",         "want"),
    ("halle 6",       "want"),     # Halle 622
    ("kaufleuten",    "want"),
    ("bächli",        "want"),
    ("to go",         "want"),     # Coop To Go, Migros To Go — before "coop"/"migros"
    ("restaurant",    "want"),     # Migros Restaurant, Restaurant Helvetia — before "migros"
    ("café",          "want"),
    ("cafe ",         "want"),
    ("canteen",       "want"),
    ("mensa",         "want"),
    ("bistro",        "want"),
    ("brasserie",     "want"),
    ("bar ",          "want"),
    ("kebab",         "want"),
    ("pizza",         "want"),
    ("sushi",         "want"),

    # ── Wants: entertainment ─────────────────────────────────────────────────
    ("kino",          "want"),
    ("netflix",       "want"),
    ("spotify",       "want"),
    ("disney",        "want"),
    ("apple tv",      "want"),
    ("amazon prime",  "want"),

    # ── Wants: clothing & lifestyle ──────────────────────────────────────────
    ("zara",          "want"),
    ("h&m",           "want"),
    ("manor",         "want"),     # dept store — clothing/lifestyle in demo
    ("globus",        "want"),
    ("zalando",       "want"),
    ("pull&bear",     "want"),
    ("uniqlo",        "want"),
    ("peek",          "want"),

    # ── Wants: electronics & online ──────────────────────────────────────────
    ("digitec",       "want"),
    ("interdiscount", "want"),
    ("microspot",     "want"),
    ("amazon eu",     "want"),
    ("amazon.de",     "want"),
    ("fust",          "want"),

    # ── Wants: fitness (discretionary) ──────────────────────────────────────
    ("fitnesspark",   "want"),
    ("mcfit",         "want"),
    ("holmes place",  "want"),
    ("bodystreet",    "want"),
    ("fitness",       "want"),

    # ── Needs: groceries ─────────────────────────────────────────────────────
    ("coop",          "need"),
    ("migros",        "need"),
    ("aldi",          "need"),
    ("lidl",          "need"),
    ("denner",        "need"),
    ("volg",          "need"),
    ("spar",          "need"),
    ("rewe",          "need"),

    # ── Needs: housing ───────────────────────────────────────────────────────
    ("immobilien",    "need"),
    ("miete",         "need"),
    ("wohnbau",       "need"),

    # ── Needs: health insurance ──────────────────────────────────────────────
    ("helsana",       "need"),
    ("swica",         "need"),
    ("css",           "need"),
    ("sanitas",       "need"),
    ("concordia",     "need"),
    ("visana",        "need"),
    ("krankenversicherung", "need"),

    # ── Needs: pharma / medical ──────────────────────────────────────────────
    ("apotheke",      "need"),
    ("amavita",       "need"),
    ("zur rose",      "need"),
    ("toppharm",      "need"),
    ("boots",         "need"),
    ("drogerie",      "need"),

    # ── Needs: transport ─────────────────────────────────────────────────────
    ("sbb",           "need"),
    ("halbtax",       "need"),
    ("postauto",      "need"),
    ("postbus",       "need"),
    ("zvv",           "need"),
    ("tpg",           "need"),

    # ── Needs: telecom ───────────────────────────────────────────────────────
    ("swisscom",      "need"),
    ("sunrise",       "need"),
    ("salt mobile",   "need"),
    ("upc",           "need"),
    ("quickline",     "need"),

    # ── Needs: utilities ─────────────────────────────────────────────────────
    ("ewz",           "need"),
    ("energie",       "need"),
    ("strom",         "need"),
    ("erdgas",        "need"),
    ("wasser",        "need"),
]


def categorize_transaction(txn: Transaction) -> str:
    """Return 'need' | 'want' | 'savings' for an outflow transaction.

    Raises ValueError for income (amount >= 0); income is not spending and
    should never reach the categorizer.
    """
    if txn.amount >= 0:
        raise ValueError(
            f"categorize_transaction expects an outflow (negative amount); "
            f"got {txn.amount:.2f} from '{txn.merchant}'. "
            "Filter income out before calling."
        )

    key = txn.merchant.lower()
    for pattern, category in _RULES:
        if pattern in key:
            return category

    # Unrecognised merchant — default to 'want'.
    # The LLM skill can override this for ambiguous cases in a later phase.
    return "want"
