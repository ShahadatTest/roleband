"""Resolve competing source claims into one value + a provenance/health verdict.

Pure: no DB, no network, no clock reads except the `now` passed in. Every rule
here is a testable contract.

Resolution order, applied per field:

1. **Manual wins outright.** If a human pinned it, that is the answer — even if it
   is older than a fresh scrape. Otherwise the next refresh would silently undo the
   correction, and "fill it in once" would be a lie.
2. Otherwise: highest source trust, then most recent `observed_at`.

Independently of who wins, we report:

- `freshness`: fresh | aging | stale, from the field's TTL.
- `conflicts`: other sources asserting a materially different value. A conflict does
  NOT block a value — it surfaces a badge, which is the trigger for the manual
  enrichment workflow.

Company-level `data_health` rolls the fields up into one badge:
`ok` | `stale` | `conflict` | `missing`, worst-wins.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime, timedelta

from tracker.profiles import sources


@dataclass
class Claim:
    """One source's assertion about one field."""

    field: str
    value: object
    source: str
    observed_at: datetime
    confidence: float = 1.0


@dataclass
class Resolved:
    field: str
    value: object
    source: str
    observed_at: datetime
    freshness: str  # fresh | aging | stale
    is_manual: bool
    conflicts: list[dict] = dc_field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


FRESH = "fresh"
AGING = "aging"
STALE = "stale"

OK = "ok"
MISSING = "missing"
CONFLICT = "conflict"

# Worst-wins ordering for the company badge.
_HEALTH_SEVERITY = {OK: 0, STALE: 1, CONFLICT: 2, MISSING: 3}


def freshness_of(field: str, observed_at: datetime, now: datetime) -> str:
    """fresh (<50% TTL) | aging (<100%) | stale (past TTL)."""
    ttl = sources.ttl_days(field)
    age = now - observed_at
    if age <= timedelta(days=ttl * 0.5):
        return FRESH
    if age <= timedelta(days=ttl):
        return AGING
    return STALE


def _norm(value: object) -> object:
    """Normalize for comparison so trivial formatting differences aren't conflicts."""
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, bool):
        return value
    return value


def _conflicts_with(winner: object, other: object, field: str) -> bool:
    """Is `other` a materially different claim than `winner`?"""
    a, b = _norm(winner), _norm(other)
    if a == b:
        return False
    if a is None or b is None:
        # A source asserting a value where another asserts nothing is only a
        # conflict for the hard fields (e.g. one says ticker=RDDT, one says none).
        return field in sources.HARD_CONFLICT_FIELDS
    # Numeric drift within tolerance is normal (headcount estimates differ).
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if a == 0 and b == 0:
            return False
        denom = max(abs(a), abs(b)) or 1
        return abs(a - b) / denom > sources.NUMERIC_CONFLICT_TOLERANCE
    return True


def resolve_field(
    claims: list[Claim],
    now: datetime,
    ranks: Mapping[str, int] | None = None,
    labels: Mapping[str, str] | None = None,
) -> Resolved | None:
    """Pick the winning claim for one field and record who disagrees.

    `ranks` and `labels` override `sources.rank` and `sources.label` for sources
    the registry ranks itself: a plugin's fact trust comes from its manifest,
    capped, and its claims read under its name.
    """
    if not claims:
        return None

    manual = [c for c in claims if sources.is_manual(c.source)]
    pool = manual or claims
    # Trust first, then recency. Manual short-circuits the trust comparison because
    # `pool` is already narrowed to it.
    winner = max(pool, key=lambda c: (sources.rank_with(ranks, c.source), c.observed_at))

    conflicts = [
        {
            "source": c.source,
            "source_label": sources.label_with(labels, c.source),
            "value": c.value,
            "observed_at": c.observed_at,
        }
        for c in claims
        if c is not winner and _conflicts_with(winner.value, c.value, winner.field)
    ]

    return Resolved(
        field=winner.field,
        value=winner.value,
        source=winner.source,
        observed_at=winner.observed_at,
        freshness=freshness_of(winner.field, winner.observed_at, now),
        is_manual=sources.is_manual(winner.source),
        conflicts=conflicts,
    )


def resolve_all(
    claims: list[Claim],
    now: datetime,
    ranks: Mapping[str, int] | None = None,
    labels: Mapping[str, str] | None = None,
) -> dict[str, Resolved]:
    """Resolve every field present in `claims`."""
    by_field: dict[str, list[Claim]] = {}
    for c in claims:
        by_field.setdefault(c.field, []).append(c)
    out: dict[str, Resolved] = {}
    for f, cs in by_field.items():
        r = resolve_field(cs, now, ranks, labels)
        if r is not None:
            out[f] = r
    return out


def field_health(resolved: Resolved | None) -> str:
    """Per-field badge.

    A human-pinned field is always OK: the user has adjudicated it, so any lingering
    dissent (a source still calling a listed company private) is informational, not an
    open problem. Without this the conflict badge could never be cleared and the
    review queue would never drain — the workflow would have no exit.
    """
    if resolved is None or resolved.value is None:
        return MISSING
    if resolved.is_manual:
        return OK
    if resolved.conflicts:
        return CONFLICT
    if resolved.freshness == STALE:
        return STALE
    return OK


def company_health(
    resolved: dict[str, Resolved], required: list[str]
) -> dict:
    """Roll fields up into one company badge (worst-wins) + the actionable lists.

    `required` names the fields that must be present for a profile to be usable;
    anything required and absent is `missing` and becomes manual-enrichment work.
    """
    per_field = {f: field_health(resolved.get(f)) for f in required}

    missing = [f for f, h in per_field.items() if h == MISSING]
    conflicted = [f for f, h in per_field.items() if h == CONFLICT]
    stale = [f for f, h in per_field.items() if h == STALE]

    worst = OK
    for h in per_field.values():
        if _HEALTH_SEVERITY[h] > _HEALTH_SEVERITY[worst]:
            worst = h

    return {
        "status": worst,
        "missing": missing,
        "conflicts": conflicted,
        "stale": stale,
        # What the manual workflow should ask the user to fix, worst first.
        "needs_review": missing + conflicted + stale,
    }
