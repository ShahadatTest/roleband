"""Source trust ranking + per-field freshness policy.

The stale-data problem is structural, not incidental: a source can keep calling a
company private long after it listed, or report a headcount years out of date.
No single source is authoritative, so the substrate stores *claims* (see
`company_fact`) and resolves them by (trust, recency) — never by "last writer wins".

Two orthogonal dimensions:

- **Trust** (`SOURCE_TRUST`): how much we believe a source when sources disagree.
  Higher wins. `manual` outranks everything — a human correction is final.
- **Freshness** (`FIELD_TTL_DAYS`): how long a claim about a given field stays
  current. `ticker` almost never changes; `headcount` rots in months. A claim past
  its TTL is `stale` and becomes a candidate for the manual-enrichment workflow.

Adding a source = one entry here. Nothing else in the resolver changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    rank: int  # higher = more trusted
    kind: str  # human | official | estimated | dataset | seed | inferred


# Ordered by trust. `rank` is what the resolver compares.
SOURCES: dict[str, Source] = {
    # A human looked at it and pinned it. Final word, by construction.
    "manual": Source("manual", "Manual (you)", 100, "human"),
    # Primary/regulatory filings — authoritative for identity + officer comp.
    "sec_edgar": Source("sec_edgar", "SEC EDGAR", 80, "official"),
    # Government wage disclosures — authoritative for real base wages.
    "dol_lca": Source("dol_lca", "DOL LCA", 75, "official"),
    # Market data feed — authoritative for live ticker/price.
    "market": Source("market", "Market data", 70, "official"),
    # Our level atlas, where the employer states the fact itself.
    "employer": Source("employer", "Employer-stated", 80, "official"),
    # Our level atlas, where employees and the press report the fact, weighed across
    # independent sources: above any single report, below an employer.
    "estimated": Source("estimated", "Estimated", 55, "estimated"),
    "reported": Source("estimated", "Estimated", 55, "estimated"),
    # A plugin's claims are not listed: the registry ranks them from the
    # plugin's manifest (capped at 50) against its own claims only and labels
    # them with its name (`plugins.registry.Providers`); they never compete with
    # ours.
    # Our dataset's identity (`levels/atlas/company_identity.csv`): above
    # the code seed, below live market data and a pin.
    "roleband": Source("roleband", "Built-in data", 60, "dataset"),
    # Identity declared in tracker/blueprint.py (display, public/ticker, brand
    # color). A curated code-level seed: below every live source so any real
    # observation supersedes it, but far above a bare inference.
    "blueprint": Source("blueprint", "Blueprint seed", 30, "seed"),
    # Our own inference (e.g. "public company -> equity is probably RSUs"). Ranked
    # below every real source so ANY observation supersedes it, but it keeps a field
    # populated-and-labelled instead of silently blank.
    "heuristic": Source("heuristic", "Inferred", 5, "inferred"),
}

DEFAULT_RANK = 10


def rank(source: str) -> int:
    s = SOURCES.get(source)
    return s.rank if s else DEFAULT_RANK


def label(source: str) -> str:
    s = SOURCES.get(source)
    return s.label if s else source


def rank_with(overrides: Mapping[str, int] | None, source: str) -> int:
    """A claim source's trust: the registry's (a plugin's manifest rank, capped)
    where it ranks the source, else the table's. The one place this falls back."""
    return (overrides or {}).get(source, rank(source))


def label_with(overrides: Mapping[str, str] | None, source: str) -> str:
    """What a person reads for a claim source: the registry's name for it (a
    plugin's, or its adopter's), else the table's."""
    return (overrides or {}).get(source) or label(source)


def is_manual(source: str) -> bool:
    return source == "manual"


# How long a claim about each field stays current, in days. Anything not listed
# uses DEFAULT_TTL_DAYS. This is what turns "we have a value" into "we have a value
# we still believe".
FIELD_TTL_DAYS: dict[str, int] = {
    # Structural facts — change rarely, but when they change they REALLY matter
    # (an IPO flips is_public/ticker and rewrites the whole equity story).
    "is_public": 90,
    "ticker": 90,
    "year_founded": 3650,
    "hq_city": 730,
    "website": 730,
    # Comp mechanics — revisit a couple times a year.
    "equity_vehicle": 180,
    "vesting_schedule": 365,
    # Fast-rotting.
    "headcount": 120,
}
DEFAULT_TTL_DAYS = 180


def ttl_days(field: str) -> int:
    return FIELD_TTL_DAYS.get(field, DEFAULT_TTL_DAYS)


# Fields whose disagreement is meaningful enough to raise a conflict badge.
# (Numeric drift on headcount is normal; a ticker disagreement is not.)
HARD_CONFLICT_FIELDS = frozenset({"is_public", "ticker", "equity_vehicle"})

# Relative tolerance before two numeric claims count as conflicting.
NUMERIC_CONFLICT_TOLERANCE = 0.15
