"""How a posting writes an amount of money: numbers and currencies.

The grammar both the band reader (`pay_disclosure`) and the period rule
(`pay_period`) build on, and nothing else: one written number and every value
it can mean ("104.800" is European thousands, "$1.250M" a decimal), the k/m
suffixes, and the currency table with its codes. Read `pay_disclosure`'s
docstring for how a band is chosen and grounded.
"""

from __future__ import annotations

import re

#: One written number: digits and comma groups, then dot groups of exactly
#: three digits (European thousands, "104.800", "1.250.000"), then at most one
#: decimal part. A looser `(?:\.\d+)*` would read a date ("01.10.2024") as
#: ONE number that has no value, which `explicit_amount` cannot read.
AMOUNT = r"\d[\d,]*(?:\.\d{3}(?!\d))*(?:\.\d+)?"

# Numbers written in a pay snippet, including k/m shorthand ("$180K" -> 180 and
# 180000), so we can check the model's bounds against what the text actually says.
# The suffix is a token of its own: without the lookahead the "M" of
# "Massachusetts" or "monthly" after a band would read as millions, the pair
# would fail the ratio check, and the band would be lost.
NUM_RE = re.compile(r"(" + AMOUNT + r")\s*([kKmM](?![A-Za-z]))?")


#: "104.800" and "1.250.000": a dot followed by groups of exactly three digits
#: is a thousands separator, the European way of writing 104,800.
#: Read as a decimal, "€104.800—€165.700 EUR" would be a €104 salary. Only
#: without a comma and without a k/m suffix ("$1.250M" is
#: 1.25 million), and no pay is written to three decimal places.
_DOTTED_THOUSANDS_RE = re.compile(r"\d{1,3}(?:\.\d{3})+")


def number_readings(raw: str, suffix: str | None = None) -> list[float]:
    """Every value `raw` can mean, the thousands reading first."""
    readings: list[float] = []
    if not suffix and "," not in raw and _DOTTED_THOUSANDS_RE.fullmatch(raw):
        readings.append(float(raw.replace(".", "")))
    try:
        readings.append(float(raw.replace(",", "")))
    except ValueError:
        pass
    return readings


#: What one unit of a currency is worth in US dollars, ONLY to place an amount
#: in a size class. The classes are ~10x apart, so a static factor cannot move
#: a real salary into the wrong one; this is not a conversion anyone sees.
#: Reviewed like any vocabulary literal. An unknown currency reads as dollars.
USD_PER_UNIT: dict[str, float] = {
    "USD": 1.0, "CAD": 0.73, "AUD": 0.66, "NZD": 0.60, "SGD": 0.75, "HKD": 0.13,
    "GBP": 1.27, "EUR": 1.08, "CHF": 1.13, "SEK": 0.095, "NOK": 0.094, "DKK": 0.145,
    "PLN": 0.25, "CZK": 0.044, "ILS": 0.27, "AED": 0.27, "INR": 0.012, "JPY": 0.0067,
    "KRW": 0.00073, "CNY": 0.14, "BRL": 0.18, "MXN": 0.055, "ZAR": 0.055,
}

#: Every code the size table knows, as a token of its own, so "USDC" does not
#: read as dollars. Public
#: because the pass's pre-filter must admit every code this parser reads
#: (`intelligence.prefilter`).
CURRENCY_CODE = r"(?<![A-Za-z])(?:" + "|".join(sorted(USD_PER_UNIT)) + r")(?![A-Za-z])"


def explicit_amount(raw: str, suffix: str | None) -> int | None:
    """The amount `raw` states, or None when it has no reading at all
    ("120.000.00": dotted thousands with a dot decimal). The caller rejects
    the candidate: an unreadable number is a missed band, never a crash."""
    readings = number_readings(raw, suffix)
    if not readings:
        return None
    value = readings[0]
    if (suffix or "").lower() == "k":
        value *= 1_000
    elif (suffix or "").lower() == "m":
        value *= 1_000_000
    return int(value)
