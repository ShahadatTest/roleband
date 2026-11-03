"""A tracked region no source can ask about must reach the run record.

The failure this guards against has no other symptom. When nobody queries
Google for Canada, the response is not an error, not drift, and not an anomaly
— it is simply a board with no Canadian roles, which is byte-for-byte what a
genuinely empty Canada looks like. `scanned`/`kept`/`stop_reason`/`outcome` all
describe what the scan *did*; none of them can describe a question it never
sent. `stats["uncovered_locations"]` is the only place that fact exists, so
these tests pin that it is produced, survives collection, and stays out of the
source's health record.
"""

from __future__ import annotations

import pytest

from tests.factories import NoComp, scope_filter
from tracker.connectors.listing.apple import APPLE_LOCATION_CODES as _APPLE_MANIFEST
from tracker.connectors.listing.google import GOOGLE_LOCATION_QUERIES as _GOOGLE_MANIFEST
from tracker.connectors.recipes.outcome import (
    RESETS_ABSENCE,
    SourceOutcome,
    classify_source_outcome,
)
from tracker.enrich.enricher import ScopeFilter
from tracker.platform.ratelimit import RateLimiterPool
from tracker.schema import RawJob

# Apple's manifest is hand-mapped opaque `postLocation-*` codes, so most of the
# planet is genuinely undeclarable there and must be REPORTED rather than
# assumed. Google's is generated per country and covers everything.
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows.collection import collect_source

_ALL_BANDS = frozenset({"staff", "senior", "principal", "director", "manager", "below"})
_ALL_ROLES = frozenset({"engineering_management", "product_management"})
_ALL_TRACKS = frozenset({"management", "individual"})


def _scope(*locations: str) -> ScopeFilter:
    return scope_filter(bands=_ALL_BANDS, roles=_ALL_ROLES, tracks=_ALL_TRACKS, locations=locations, domains=())


class _RecordingGoogle:
    """A real manifest behind a fetch that touches no network."""

    def __init__(self, location_groups=None, manifest=None) -> None:
        from tracker.platform.drift import SchemaDriftDetector  # noqa: PLC0415

        self.company = "google"
        self.location_queries = manifest if manifest is not None else _GOOGLE_MANIFEST
        self.drift = SchemaDriftDetector("google")
        self.truncated = False
        self.query_observations: list = []
        self._enabled = frozenset(location_groups) if location_groups is not None else None

    # -- the two manifest methods under test, copied from BaseAdapter by
    #    delegation so this stub cannot drift away from the real behavior.
    def location_gaps(self):
        from tracker.connectors.listing.base import BaseAdapter  # noqa: PLC0415

        return BaseAdapter.location_gaps(self)

    def planned_location_terms(self):
        from tracker.connectors.listing.base import BaseAdapter  # noqa: PLC0415

        return BaseAdapter.planned_location_terms(self)

    def planned_location_items(self):
        from tracker.connectors.listing.base import BaseAdapter  # noqa: PLC0415

        return BaseAdapter.planned_location_items(self)

    @property
    def _enabled_locations(self):
        return self._enabled

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        # One in-scope US posting per run, so the scan is unambiguously healthy:
        # any gap reported alongside it cannot be an artifact of a failed scan.
        yield RawJob(
            company="google",
            req_id="us-1",
            title="Engineering Manager, Search",
            url="https://example.test/us-1",
            locations=["Mountain View, CA, USA"],
        )


async def _collect_google(*tracked: str, manifest=None):
    return await collect_source(
        "google",
        # Walled: the row a consenting user's follow would produce.
        {"adapter": "google", "consent": SOURCE_REVIEWS["google"].wall_fingerprint},
        _scope(*tracked),
        NoComp(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, location_groups=None, **kw: _RecordingGoogle(
            location_groups=location_groups, manifest=manifest
        ),
    )


@pytest.mark.asyncio
async def test_a_tracked_region_with_no_query_is_named_in_the_run():
    # Apple's manifest declares only the countries its place lookup names a
    # code for; Cuba has none, so tracking it is reported, never silent.
    result = await _collect_google("united_states", "cuba", manifest=_APPLE_MANIFEST)

    assert result.stats["uncovered_locations"] == ["cuba"]
    # The scan still ran and still kept what it could reach: "loud" must not
    # mean "abandon the regions the source CAN serve".
    assert result.stats["scanned"] == 1
    assert result.stats["kept"] == 1
    assert result.stats["errors"] == []


@pytest.mark.asyncio
async def test_a_tracked_country_google_can_serve_reports_no_gap():
    """google's UK term is a country query: `United Kingdom` and `London, UK`
    return the identical req_ids, so the filter is regional and the board is
    fully reachable."""
    result = await _collect_google("uk")

    assert result.stats["uncovered_locations"] == []


def test_coverage_never_flows_up_from_a_metro_to_its_country():
    """The rule itself, pinned independently of any adapter's current terms.

    Asking about a city can never stand in for asking about its country, and no
    future retuning of a query vocabulary may make it appear to. The inverse must
    hold too, or every US metro would report as uncovered behind the
    `united_states` query.
    """
    from tracker.taxonomy.locations import location_group_covers

    assert location_group_covers("london", "uk") is False
    assert location_group_covers("silicon_valley", "united_states") is False
    assert location_group_covers("uk", "london") is True
    assert location_group_covers("united_states", "new_york") is True
    # A country does not reach across into a sibling country.
    assert location_group_covers("uk", "germany") is False


@pytest.mark.asyncio
async def test_a_country_query_covers_its_metros():
    """The inverse must hold, or every US metro would report as uncovered."""
    result = await _collect_google("united_states", "new_york", "austin")

    assert result.stats["uncovered_locations"] == []


@pytest.mark.asyncio
async def test_a_fully_covered_scope_reports_no_gap():
    result = await _collect_google("united_states", "singapore", "london")

    assert result.stats["uncovered_locations"] == []


@pytest.mark.asyncio
async def test_a_coverage_gap_is_not_a_source_failure():
    """The gap is OUR manifest's, never the source's conduct. Routing it through
    health would quarantine a binding for answering every question it was asked
    — a misattribution that suppresses closure across every binding it
    touches."""
    result = await _collect_google("united_states", "cuba", manifest=_APPLE_MANIFEST)

    assert result.stats["uncovered_locations"] == ["cuba"]
    stats = {**result.stats, "list_complete": result.list_complete}
    outcome = classify_source_outcome(stats)
    assert outcome is SourceOutcome.OK
    assert outcome not in RESETS_ABSENCE


def test_coverage_flows_up_to_a_region_but_never_up_to_a_country():
    """The asymmetry, which is the whole rule.

    A region has no postings of its own — a European role is always in some
    European country — so declaring every member country DOES cover Europe.
    A country is different: `uk` has Manchester roles that a `london` query
    never returns, so declaring its metros must NOT cover it. That over-claim
    must not come back through the region door either.
    """
    from tracker.taxonomy.locations import location_group_children, uncovered_groups

    # Every European country declared -> europe is covered.
    europe_members = location_group_children("europe")
    assert uncovered_groups(europe_members, ["europe"]) == set()
    # One missing -> it is not.
    assert uncovered_groups(europe_members[1:], ["europe"]) == {"europe"}
    # A country is never covered by its metros, however complete they look.
    assert uncovered_groups(["london"], ["uk"]) == {"uk"}
    assert uncovered_groups(["silicon_valley"], ["united_states"]) == {"united_states"}
    # ...and the down direction is untouched.
    assert uncovered_groups(["united_states"], ["silicon_valley"]) == set()


def test_a_region_with_no_members_is_never_vacuously_covered():
    """`all([])` is True, so a childless group would report as covered by an
    empty manifest. Metros are childless; they must stay uncovered."""
    from tracker.taxonomy.locations import uncovered_groups

    assert uncovered_groups([], ["silicon_valley"]) == {"silicon_valley"}
    assert uncovered_groups([], ["europe"]) == {"europe"}


class _WithAnUnplacedPosting(_RecordingGoogle):
    async def fetch(self):
        async for raw in super().fetch():
            yield raw
        # A place nothing recognises: listed, and never countable.
        yield RawJob(
            company="google", req_id="nowhere-1", title="Engineering Manager, Ads",
            url="https://example.test/nowhere-1", locations=["Atlantis"],
        )


@pytest.mark.asyncio
async def test_a_scan_reports_the_places_it_asked_and_the_postings_it_could_not_count():
    """The catalog records the places a manifest source was asked,
    so the walk can say a new place is not counted yet, and counts the listed
    postings it had to drop instead of losing them silently."""
    result = await collect_source(
        "google",
        {"adapter": "google", "consent": SOURCE_REVIEWS["google"].wall_fingerprint},
        _scope("united_states"),
        NoComp(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, location_groups=None, **kw: _WithAnUnplacedPosting(location_groups=location_groups),
    )
    asked = {group for group, _ in _RecordingGoogle(location_groups={"united_states"}).planned_location_items()}
    assert result.catalog_places == sorted(asked)
    assert "united_states" in asked and "uk" not in asked
    assert result.catalog_unplaced == 1
    assert result.stats["scanned"] == 2
