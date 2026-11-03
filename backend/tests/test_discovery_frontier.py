"""A discovery probe reads until it catches up, not until an allowance runs out.

A constant depth (say 2 pages per location, whether the board moved by 3
postings or 300) stops at `ceiling`, our bound, over a listing still serving
items, so the probe can never demonstrate it read back past the newest posting
we already hold. A burst falls off the end of the slice and waits up to 24h for
the next reconcile.

The frontier stop makes depth follow the board: page until a row is one
we recognize on a newest-first listing. The constant stays as a backstop when the frontier
cannot end (first run against an empty database, or a burst past the allowance).

The negative case matters most and is tested hardest: RECONCILE must never stop
early. It is the only closure authority, and a listing it cut short is a listing
it cannot speak for.
"""

from __future__ import annotations

import pytest

from tracker.connectors.listing.base import BaseAdapter
from tracker.platform.paging import StopReason
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import RawJob


def _job(index: int) -> RawJob:
    return RawJob(
        company="acme",
        req_id=f"req-{index}",
        title="Engineering Manager",
        url=f"https://example.test/{index}",
    )


class _PagedSource(BaseAdapter):
    """A newest-first board of `pages` pages, 3 rows each, that never runs dry."""

    name = "paged"
    discovery_max_pages = 6
    discovery_frontier_ordered = True

    def __init__(self, *args, pages: int = 10, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pages = pages
        self.pages_fetched = 0
        self._limiter = RateLimiter(0.0)

    async def fetch(self):
        async def fetch_page(index: int, stop):
            self.pages_fetched += 1
            if index >= self._pages:
                return []
            start = index * 3
            return [_job(start + offset) for offset in range(3)]

        async for job in self.paged_listing(fetch_page, max_pages=100, query_key="q"):
            yield job


def _keys(*indexes: int) -> set[str]:
    return {_job(i).dedupe_key() for i in indexes}


async def _run(**kwargs) -> _PagedSource:
    adapter = _PagedSource("acme", **kwargs)
    [job async for job in adapter.fetch()]
    return adapter


@pytest.mark.asyncio
async def test_a_probe_stops_on_the_page_that_reaches_a_known_row():
    # Page 0 (req 0,1,2) is all new; page 1 holds req 4, which we already have.
    adapter = await _run(discovery=True, known_keys=_keys(4))

    assert adapter.pages_fetched == 2
    assert adapter.query_observations[0].stop_reason is StopReason.FRONTIER


@pytest.mark.asyncio
async def test_a_probe_reads_deeper_when_the_board_moved_more():
    """Depth follows the board. The same source, the same constant, a different
    amount of new material — and a different number of requests."""
    shallow = await _run(discovery=True, known_keys=_keys(4))
    deep = await _run(discovery=True, known_keys=_keys(10))

    assert shallow.pages_fetched == 2
    assert deep.pages_fetched == 4


@pytest.mark.asyncio
async def test_one_known_row_among_new_ones_still_ends_the_probe():
    """The listing is newest-first, so a row we hold dates the rest of the page:
    everything below it is older and has already been through a scan. Requiring
    the whole page to be known never fires on a large board: we keep a small
    share of its rows, so no page is ever entirely familiar."""
    adapter = await _run(discovery=True, known_keys=_keys(5))

    assert adapter.pages_fetched == 2
    assert adapter.query_observations[0].stop_reason is StopReason.FRONTIER


@pytest.mark.asyncio
async def test_an_unordered_source_never_stops_at_the_frontier():
    """The inference needs newest-first. Without that guarantee a recognized row
    says nothing about what sits below it, so the backstop is the only safe
    bound."""

    class _Unordered(_PagedSource):
        discovery_frontier_ordered = False

    adapter = _Unordered("acme", discovery=True, known_keys=_keys(4))
    [job async for job in adapter.fetch()]

    assert adapter.pages_fetched == _PagedSource.discovery_max_pages
    assert adapter.query_observations[0].stop_reason is StopReason.CEILING


@pytest.mark.asyncio
async def test_the_backstop_still_bounds_a_probe_that_never_catches_up():
    """First run against an empty database: nothing is known, so the frontier
    can never fire and the allowance is the only thing left to stop it."""
    adapter = await _run(discovery=True, known_keys=set())

    assert adapter.pages_fetched == _PagedSource.discovery_max_pages
    assert adapter.query_observations[0].stop_reason is StopReason.CEILING


@pytest.mark.asyncio
async def test_reconcile_never_stops_at_the_frontier():
    """The load-bearing negative. Reconcile is the only closure authority; a
    listing it cut short is one it cannot claim to have enumerated, so knowing
    a page is stale must not shorten it."""
    adapter = await _run(discovery=False, known_keys=_keys(4))

    assert adapter.pages_fetched > 2
    assert adapter.query_observations[0].stop_reason is not StopReason.FRONTIER


@pytest.mark.asyncio
async def test_a_probe_with_no_frontier_supplied_behaves_as_before():
    """CLI, smoke and standalone tests pass no key set; the probe must fall back
    to the backstop rather than stopping on the first page."""
    adapter = await _run(discovery=True)

    assert adapter.pages_fetched == _PagedSource.discovery_max_pages
    assert adapter.query_observations[0].stop_reason is StopReason.CEILING


@pytest.mark.asyncio
async def test_a_frontier_stop_never_claims_the_listing_was_enumerated():
    """A frontier stop is OUR bound over a listing still serving rows. It must
    suppress the completeness claim exactly as a ceiling hit does, or a partial
    probe would look like a full board read."""
    adapter = await _run(discovery=True, known_keys=_keys(4))

    assert adapter.truncated is True


@pytest.mark.asyncio
async def test_a_natural_end_is_still_exhausted_not_frontier():
    """A board that genuinely runs out has ended itself; that is a different
    claim from us deciding we had seen enough, and must stay distinguishable."""
    adapter = _PagedSource("acme", pages=2, discovery=True, known_keys=_keys(99))
    [job async for job in adapter.fetch()]

    assert adapter.query_observations[0].stop_reason is StopReason.EXHAUSTED
    assert adapter.truncated is False
