"""Writes one company's role-catalog snapshot.

The counting lives a tier below, in `taxonomy/role_catalog.py`: tallying titles
and bands is vocabulary work and needs no database. Only this file writes the
rows, which is why it sits here in `scope/`, beside `catalog.py`, the one thing
that reads them back for the scope screen.

Commits nothing. `workflows/run_persistence.py` calls this inside the run's
persist loop and commits after each source; committing here
would split a source's writes across two transactions.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import RoleCatalog, TrackedCompany
from tracker.levels import all_band_slugs
from tracker.taxonomy.role_catalog import CatalogTallies, RoleTally
from tracker.taxonomy.tracks import all_track_slugs

#: Example titles kept per role group. Display evidence, not a sample: the UI
#: shows what the classifier actually read.
MAX_EXAMPLES = 6


def _ordered_band_counts(tally: RoleTally) -> dict[str, int]:
    return {slug: tally.band_counts[slug] for slug in all_band_slugs() if tally.band_counts[slug]}


def _ordered_scope_cells(tally: RoleTally) -> list[dict]:
    """The scope joint as a stable, self-describing list.

    Ordered by (band, track, locations, domains) so the stored JSONB is
    byte-stable across runs that observed the same board: an unordered dump
    would make every nightly rewrite look like a change to anything diffing
    this column.
    """
    return [
        {
            "band": band,
            "track": track,
            "locations": list(locations),
            "domains": list(domains),
            "count": count,
        }
        for (band, track, locations, domains), count in sorted(tally.scope_cells.items())
        if count > 0
    ]


def _ordered_band_track_counts(tally: RoleTally) -> dict[str, dict[str, int]]:
    return {
        band: {
            track: tally.band_track_counts.get(band, Counter())[track]
            for track in all_track_slugs()
            if tally.band_track_counts.get(band, Counter())[track]
        }
        for band in all_band_slugs()
        if tally.band_track_counts.get(band)
    }


def catalog_rows(tallies: CatalogTallies) -> list[dict]:
    """One company's tallies as the `role_catalog` rows they are stored as, one
    per role group: the shape `scope/catalog.py` reads. The one shaping, used
    by the stored catalog and by the catalog built from the posting inventory
    so the two cannot differ in form."""
    return [
        {
            "role_group": role_group,
            "count": tally.count,
            "band_counts": _ordered_band_counts(tally),
            "band_track_counts": _ordered_band_track_counts(tally),
            "scope_cells": _ordered_scope_cells(tally),
            "examples": [title for title, _ in tally.titles.most_common(MAX_EXAMPLES)],
            "domain_counts": dict(tally.domain_counts),
            "domain_examples": tally.domain_examples,
        }
        for role_group, tally in tallies.items()
    ]


def scanned_places(adapter: object | None) -> list[str] | None:
    """The location groups a source that lists only asked-for places was
    queried for (`planned_location_items`), or None when it lists the whole
    board. Duck-typed: test fakes and recipe bridges have no manifest."""
    if adapter is None or getattr(adapter, "location_queries", None) is None:
        return None
    return sorted({group for group, _ in adapter.planned_location_items()})  # type: ignore[attr-defined]


async def persist_company_catalog(
    session: AsyncSession,
    company: str,
    tallies: CatalogTallies,
    *,
    complete: bool,
    error: str | None = None,
    places: list[str] | None = None,
    unplaced: int | None = None,
    unsorted: int | None = None,
) -> str:
    """Persist one company's snapshot without letting partial/error data clobber ready data."""
    tracked = await session.get(TrackedCompany, company)
    if tracked is None:
        return "missing"

    if error:
        tracked.role_catalog_status = "error"
        tracked.role_catalog_error = error[:2000]
        return "error"

    if not complete and tracked.role_catalog_status == "ready":
        return "ready"

    await session.execute(delete(RoleCatalog).where(RoleCatalog.company == company))
    now = datetime.now(UTC)
    for row in catalog_rows(tallies):
        session.add(RoleCatalog(company=company, updated_at=now, **row))
    tracked.role_catalog_status = "ready" if complete else "partial"
    tracked.role_catalog_scanned_at = now
    tracked.role_catalog_places = places
    tracked.role_catalog_unplaced = unplaced
    tracked.role_catalog_unsorted = unsorted
    tracked.role_catalog_error = None
    return tracked.role_catalog_status
