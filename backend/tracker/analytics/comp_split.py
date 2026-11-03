"""Heuristic decomposition of a total-comp figure into base / bonus / equity.

We only store a single total-compensation (TC) estimate per role (see
`comp_stats`), but the "stock trajectory" view needs the *equity* slice broken
out so it can flex with a stock-price scenario. A pay source may expose only
median TC (not the base/stock/bonus split), so rather than persist
a real split we derive one at read time from public comp norms:

    equity_pct rises with seniority; bonus is a flat target slice; base is the
    remainder.

The split is intentionally coarse and labelled as an estimate in the UI. A
role's equity only tracks a real, liquid stock price for *public* companies:
those the atlas lists, or whose grants track a listed parent (`ticker_for`).
Everything else is treated as private/illiquid; its equity slice is still shown
for context but flagged as not price-linked.
"""

from __future__ import annotations

from tracker.levels.identity import grant_ticker, identity_for, listed_ticker
from tracker.schema import LevelBand

# Which companies trade, and which listed stock a subsidiary's grants track, is
# the atlas's (`tracker.levels.identity`, `company_identity.csv` `listed` /
# `ticker` / `grant_ticker`).
#
# The one exception: a subsidiary outside the atlas whose employees are granted
# its listed parent's stock. Add a company to the atlas rather than a
# row here; an atlas company is never read from this table.
PARENT_TICKERS_OUTSIDE_ATLAS: dict[str, str] = {
    "linkedin": "MSFT",
}

# Share of TC that is equity, by seniority band. Senior packages tip more toward
# stock, so the equity slice (and thus stock-price sensitivity) grows with level.
_EQUITY_PCT_BY_BAND: dict[LevelBand, float] = {
    LevelBand.SENIOR: 0.35,
    LevelBand.STAFF: 0.45,
    LevelBand.PRINCIPAL: 0.52,
    LevelBand.DIRECTOR_PLUS: 0.58,
}
_DEFAULT_EQUITY_PCT = 0.40

# Per-company multiplier on the band equity share. Netflix famously pays mostly
# cash (you elect your own salary/stock split), so its equity slice is thin.
# OpenAI skews the other way: its per-level splits run well above the generic
# bands at every level. It only bites where no observed split exists; the 0.80
# clamp bounds it.
_EQUITY_MULT: dict[str, float] = {
    "netflix": 0.4,
    "openai": 1.4,
}

# Flat target-bonus share of TC. Coarse but keeps base = TC - equity - bonus
# sensible across bands.
BONUS_PCT = 0.12

# Guard rails so overrides can never drive base negative.
_EQUITY_PCT_MIN = 0.0
_EQUITY_PCT_MAX = 0.80


def is_public(company: str) -> bool:
    """True if the company's equity tracks a liquid, publicly-listed ticker."""
    return ticker_for(company) is not None


def ticker_for(company: str) -> str | None:
    """The ticker a company's RSUs track, or None if private/illiquid."""
    return parent_ticker(company) or listed_ticker(company)


def parent_ticker(company: str) -> str | None:
    """The listed parent's ticker a subsidiary's grants track, or None."""
    if identity_for(company) is not None:
        return grant_ticker(company)
    return PARENT_TICKERS_OUTSIDE_ATLAS.get(company)


def equity_pct(company: str, band: LevelBand) -> float:
    """Estimated equity share of TC for a company/band, in [0, 0.80]."""
    base = _EQUITY_PCT_BY_BAND.get(band, _DEFAULT_EQUITY_PCT)
    frac = base * _EQUITY_MULT.get(company, 1.0)
    return max(_EQUITY_PCT_MIN, min(_EQUITY_PCT_MAX, frac))


def equity_assumptions() -> dict:
    """The heuristic knobs, for surfacing in the API payload / UI footnote."""
    return {
        "bonus_pct": BONUS_PCT,
        "equity_by_band": {b.value: round(v, 4) for b, v in _EQUITY_PCT_BY_BAND.items()},
    }


def split_tc(total_comp: int, company: str, band: LevelBand) -> dict[str, int]:
    """Decompose a TC figure into {base, bonus, equity} dollars — HEURISTIC.

    Fallback only. Prefer `split_tc_observed`, which uses the real per-level split
    stored in `company_comp_level`. This estimate exists for companies we have
    no observed split for, and it is wrong in ways no guess can anticipate: it would
    invent an ~18% equity slice for Netflix, which actually pays a 0%-stock cash
    election.

    Equity and bonus are shares of TC; base is the remainder, so the three always
    sum back to `total_comp` exactly (no rounding drift).
    """
    ef = equity_pct(company, band)
    equity = round(total_comp * ef)
    bonus = round(total_comp * BONUS_PCT)
    base = total_comp - equity - bonus
    return {"base": base, "bonus": bonus, "equity": equity}


# An observed split, keyed (company_slug, band_value) -> {base_pct, stock_pct,
# bonus_pct}. Sourced from `company_comp_level` (a plugin's per-level rows) and
# passed in by the API so this module stays pure/DB-free.
ObservedSplits = dict[tuple[str, str], dict]

#: A split read from a company's own per-level row, whoever published it. The
#: wire value names the KIND of split, never a site.
SOURCE_OBSERVED = "measured"
SOURCE_HEURISTIC = "heuristic"


def split_tc_observed(
    total_comp: int,
    company: str,
    band: LevelBand,
    observed: ObservedSplits | None = None,
    *,
    heuristic: bool = True,
) -> dict | None:
    """Decompose TC using the REAL split when we have one, else the heuristic.

    Returns {base, bonus, equity, source}. `source` is what lets the UI say whether
    a figure is measured or estimated — the difference is large and material
    (Netflix: observed 0% stock vs heuristic ~18%).

    `heuristic=False` while a plugin answers pay: the heuristic is our data, and
    a plugin's total is never split by it. No observed split is then
    None, not a guess.

    Components always sum back to `total_comp` exactly: base absorbs the rounding.
    """
    row = (observed or {}).get((company, band.value))
    if not row or row.get("stock_pct") is None:
        if not heuristic:
            return None
        return {**split_tc(total_comp, company, band), "source": SOURCE_HEURISTIC}

    equity = round(total_comp * float(row["stock_pct"]))
    bonus = round(total_comp * float(row.get("bonus_pct") or 0.0))
    base = total_comp - equity - bonus
    return {"base": base, "bonus": bonus, "equity": equity, "source": SOURCE_OBSERVED}
