"""Hydration follows the job's need, not the run's mode.

A run-level `hydrate` flag cannot express "this row has no text", and that
mismatch produces the exact inverse of what is wanted: discovery persists new
roles *without* descriptions (the only rows it writes at all) while reconcile
re-fetches unchanged descriptions every night.

The tests below pin the decision per job: fetch when we lack usable text, skip
when we have it and it is fresh, and never let a skip downgrade a stored
description.
"""

from __future__ import annotations

import pytest

# `test_adapter_smartrecruiters` imports `_SCOPE` and `_NoComp` from this module.
from tests.factories import STAFF_EM_SCOPE as _SCOPE
from tests.factories import DetailSource, detail_posting
from tests.factories import NoComp as _NoComp
from tracker.platform.ratelimit import RateLimiterPool
from tracker.workflows.collection import collect_source
from tracker.workflows.collection_types import ScanMode, SourceLookups


async def _collect(source: DetailSource, **kwargs):
    return await collect_source(
        "acme",
        {"adapter": "greenhouse"},
        _SCOPE,
        _NoComp(),
        max_list=None,
        hydrate=True,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, **kw: source,
        **kwargs,
    )


def _key(index: int) -> str:
    return detail_posting(index).dedupe_key()


@pytest.mark.asyncio
async def test_a_row_with_no_stored_text_is_fetched():
    source = DetailSource()
    await _collect(source)

    assert source.hydrated == ["req-0", "req-1", "req-2"]


@pytest.mark.asyncio
async def test_a_row_with_fresh_text_is_not_fetched_again():
    """A fresh stored description needs no detail request: another read inside
    the freshness window supplies no new evidence."""
    source = DetailSource()
    await _collect(source, lookups=SourceLookups(fresh_description_keys=frozenset({_key(0), _key(2)})))

    assert source.hydrated == ["req-1"]


@pytest.mark.asyncio
async def test_a_new_row_in_discovery_is_fetched():
    """Discovery writes exactly the new rows, and those are the ones a run-level
    flag would leave blank."""
    source = DetailSource()
    result = await _collect(source, scan_mode=ScanMode.DISCOVERY)

    assert source.hydrated == ["req-0", "req-1", "req-2"]
    # The fetched text must reach persistence, not just the adapter's result.
    assert [bool(e.raw.description_html) for e in result.enriched] == [True] * 3


@pytest.mark.asyncio
async def test_discovery_still_skips_rows_it_already_holds_open():
    """The frontier filter is untouched: an already-open row triggers no detail
    request, which is what keeps a 6-hourly probe cheap."""
    source = DetailSource()
    await _collect(
        source,
        scan_mode=ScanMode.DISCOVERY,
        lookups=SourceLookups(existing_open_keys=frozenset({_key(0), _key(1)})),
    )

    assert source.hydrated == ["req-2"]


@pytest.mark.asyncio
async def test_the_discovery_budget_bounds_a_burst_and_counts_what_it_deferred():
    """A probe stays a probe. The deferral must be counted, or a cap reads as
    complete coverage — and the backfill pass is what drains it."""
    source = DetailSource(count=10)
    from tracker.config import get_settings

    settings = get_settings()
    original = settings.scraper_discovery_detail_budget
    try:
        settings.scraper_discovery_detail_budget = 4
        result = await _collect(source, scan_mode=ScanMode.DISCOVERY)
    finally:
        settings.scraper_discovery_detail_budget = original

    assert len(source.hydrated) == 4
    assert result.stats["detail_deferred"] == 6


@pytest.mark.asyncio
async def test_a_reconcile_has_no_detail_budget():
    """Reconcile is authoritative and bounded by its listing. An additional
    detail cap would leave new postings without descriptions."""
    source = DetailSource(count=10)
    result = await _collect(source, scan_mode=ScanMode.RECONCILE)

    assert len(source.hydrated) == 10
    assert result.stats["detail_deferred"] == 0
