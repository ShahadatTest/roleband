"""Deterministic pre-filter — decide, with zero model cost, whether a posting is
even worth an on-device call.

Most postings don't disclose pay. A posting only reaches the model if its text
carries a monetary signal or an explicit salary-range phrase. This is recall-
favoring on purpose: a false positive just wastes one cheap local call, while a
false negative silently drops a real disclosure, so the bar is intentionally low.
"""

from __future__ import annotations

import re

from tracker.pay_numbers import CURRENCY_CODE

# A currency-ish signal: a symbol next to digits, a NNN,NNN group, an "NNNk"
# figure, or an ISO currency code. The codes are the parser's own
# (`pay_numbers.CURRENCY_CODE`): a code the parser reads but this signal
# misses would mark a posting stating "SEK 900000 - 1200000" processed with no
# band before the parser could read it.
_MONEY_RE = re.compile(
    r"[$£€]\s?\d"
    r"|(?<!\d)\d{2,3},\d{3}(?!\d)"
    r"|\b\d{2,3}\s?[kK]\b"
    r"|" + CURRENCY_CODE,
)

# Explicit pay-band phrasing even when the number is spelled oddly.
_PHRASE_RE = re.compile(
    r"salary\s+range"
    r"|pay\s+range"
    r"|pay\s+band"
    r"|base\s+salary"
    r"|annual\s+salary"
    r"|annual\s+compensation"
    r"|compensation\s+range"
    r"|expected\s+salary"
    r"|salary\s+is\b",
    re.IGNORECASE,
)


def has_pay_pattern(description_text: str | None) -> bool:
    if not description_text:
        return False
    return bool(_MONEY_RE.search(description_text) or _PHRASE_RE.search(description_text))


def needs_relevance_review(
    *,
    in_scope: bool,
    domains: list[str] | None,
    family: str | None,
    review_families: tuple[str, ...] | frozenset[str],
) -> bool:
    """Deterministic gate for the relevance_review advisory.

    A posting earns a model call only when all three hold:
      - it SURVIVED the deterministic scope gate (`in_scope`) — out-of-scope rows
        are already handled and reviewing them buys nothing;
      - the domain ladder could NOT place it (`domains` NULL or empty) — the
        fail-open volume is exactly where noise hides;
      - its family is one where surface indicators mislead (a "Senior Director,
        Product Management" title reads identically across every world). An
        empty `review_families` disables the family narrowing rather than the
        task — deliberate, so operators can widen with one setting.
    """
    if not in_scope:
        return False
    if domains:
        return False
    if review_families and family not in review_families:
        return False
    return True
