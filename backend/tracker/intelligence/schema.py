"""The disclosed-comp MODEL contract: turning a model's raw answer into a
`DisclosedComp`, and refusing the ones it cannot ground.

The reading of a pay band is vocabulary and lives in `tracker/pay_disclosure.py`.
What stays here is the part that only exists because a model might
answer: coercion of arbitrary JSON, and `snippet_grounded`, the gate that made a
quoted band verbatim-checkable against the posting.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from tracker.pay_disclosure import (
    MAX_COMP,
    DisclosedComp,
    basis_at,
    derive_bonus_pct,
    locate_pay_span,
    quote_at,
)
from tracker.pay_period import PayPeriod
from tracker.platform.util import normalize_text

__all__ = [
    "DISCLOSED_COMP_SCHEMA",
    "coerce_disclosed_comp",
    "snippet_grounded",
]

# The on-device model has been observed returning the literal string "CURRENCY"
# for this field, so it is validated against a real ISO-4217 allowlist rather than
# trusted as free text. Anything unrecognized becomes None.
_CURRENCIES = frozenset(
    {
        "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "SGD", "HKD", "JPY", "CNY",
        "KRW", "INR", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "ILS", "AED",
        "BRL", "MXN", "ZAR", "TWD",
    }
)


# The structured-generation target handed to the provider: the Pydantic model
# above. The Apple adapter translates it into an `@fm.generable` spec; the
# chat-shaped backends carry its JSON schema in the prompt (`structured.py`).
DISCLOSED_COMP_SCHEMA = DisclosedComp


def snippet_grounded(snippet: str | None, description_text: str) -> bool:
    """True iff `snippet` occurs verbatim (post-normalization) in the posting and
    actually looks like a pay reference (has a digit, non-trivial length)."""
    if not snippet or not isinstance(snippet, str):
        return False
    norm = normalize_text(snippet)
    if len(norm) < 4 or not any(ch.isdigit() for ch in norm):
        return False
    return norm in normalize_text(description_text)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def _enum(value: object, enum_cls, default):
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().lower())
        except ValueError:
            return default
    return default


def coerce_disclosed_comp(raw: object, description_text: str) -> DisclosedComp:
    """Validate raw model output into a grounded `DisclosedComp`.

    Any failure — not a dict, `disclosed` false, no usable bound, out-of-range value,
    or bounds that cannot be located together in the posting — yields
    `DisclosedComp(disclosed=False)`. The stored `source_snippet` is sliced from the
    posting at the band's located span (`quote_at`), never taken from the model.
    """
    if not isinstance(raw, dict) or not raw.get("disclosed"):
        return DisclosedComp(disclosed=False)

    base_min = _as_int(raw.get("base_min"))
    base_max = _as_int(raw.get("base_max"))
    if base_min is None and base_max is None:
        return DisclosedComp(disclosed=False)

    # Ordering of two numbers in prose is ambiguous; normalize before locating them.
    if base_min is not None and base_max is not None and base_min > base_max:
        base_min, base_max = base_max, base_min
    for bound in (base_min, base_max):
        if bound is not None and not (0 <= bound <= MAX_COMP):
            return DisclosedComp(disclosed=False)

    # THE grounding gate: the bounds must literally co-occur in one short span of the
    # posting. The span we find — not the model's snippet — becomes the stored quote,
    # so it is verbatim by construction.
    bounds = [b for b in (base_min, base_max) if b is not None]
    span = locate_pay_span(description_text, bounds)
    if span is None:
        return DisclosedComp(disclosed=False)
    snippet = quote_at(description_text, span)
    basis = basis_at(description_text, span)

    currency = raw.get("currency")
    currency = currency.strip().upper() if isinstance(currency, str) else ""
    currency = currency if currency in _CURRENCIES else None
    confidence = raw.get("confidence")
    confidence = confidence if confidence in ("high", "low") else "low"

    try:
        return DisclosedComp(
            disclosed=True,
            base_min=base_min,
            base_max=base_max,
            currency=currency,
            # NOT the model's label: it reads an additive "+ 25% bonus target +
            # equity" tail as evidence the band is total, and guesses "base" on
            # bands that state no basis at all. Derived from the text instead.
            pay_basis=basis,
            pay_period=_enum(raw.get("pay_period"), PayPeriod, PayPeriod.unclear),
            source_snippet=str(snippet)[:240],
            confidence=confidence,
            bonus_pct=derive_bonus_pct(description_text, span, basis),
        ).located(span)
    except ValidationError:
        return DisclosedComp(disclosed=False)
