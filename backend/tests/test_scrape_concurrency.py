"""Concurrent source collection keeps backend pacing and block handling intact."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import tracker.workflows.pipeline as pipeline_module
from tests.factories import scope_filter
from tracker.connectors import BreakerPool, build_adapter
from tracker.connectors.listing.apple import AppleAdapter
from tracker.connectors.listing.base import RateLimiterPool, SchemaDriftDetector
from tracker.connectors.listing.greenhouse import GreenhouseAdapter
from tracker.connectors.recipes.outcome import (
    RESETS_ABSENCE,
    SourceOutcome,
    classify_source_outcome,
)
from tracker.enrich.enricher import ScopeFilter, annotate
from tracker.enrich.inventory import inventory_row
from tracker.platform.breaker import CircuitOpenError
from tracker.platform.http import RetryDeadlineExceeded
from tracker.schema import RawJob
from tracker.source_policy import collection_access
from tracker.workflows.collection import collect_source, collect_sources
from tracker.workflows.collection_types import ScanMode, SourceCollection, SourceLookups
from tracker.workflows.run_persistence import should_close_missing

EMPTY_SCOPE = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())


@pytest.fixture(autouse=True, scope="module")
def _classifier_warm():
    """Collection classifies each posting as it reads it, and the first
    classification in a process compiles the taxonomy (a fraction of a second,
    more under load). These tests give a source half-second budgets and count the
    postings it read before them, so a cold first posting spends the budget on
    that one-time warm-up: the count then measures the warm-up, not the
    deadline under test. Run alone, or first on an xdist worker, the deadline
    test would read 1 posting instead of 2. Warm it once, up front."""
    raw = RawJob(company="warm", req_id="0", title="Staff Software Engineer",
                 url="https://example.test/warm/0", locations=["London, UK"])
    inventory_row(raw, annotate(raw))


@pytest.mark.parametrize(
    "max_list,list_complete,errors,expected",
    [
        (None, True, [], True),
        (150, True, [], False),
        (None, False, [], False),
        (None, True, ["TimeoutError: collection timed out"], False),
        (None, False, ["DriftError: malformed listing"], False),
    ],
)
def test_close_missing_requires_a_clean_complete_uncapped_listing(
    max_list, list_complete, errors, expected
):
    collection = SourceCollection(
        company="acme",
        enriched=[],
        seen_keys=set(),
        stats={"errors": errors},
        drift=[],
        list_complete=list_complete,
    )

    assert should_close_missing(collection, max_list=max_list) is expected


def test_only_listing_drift_invalidates_closure_evidence():
    detector = SchemaDriftDetector("acme")

    detector.note("detail payload omitted optional field")
    assert detector.listing_complete is True

    detector.invalidate_listing("missing jobs array")
    assert detector.listing_complete is False


@pytest.mark.asyncio
async def test_collection_propagates_fatal_listing_drift_without_source_error():
    class DriftedAdapter:
        def __init__(self):
            self.drift = SchemaDriftDetector("acme")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            self.drift.invalidate_listing("missing jobs array")
            if False:
                yield None

    result = await collect_source(
        "acme",
        {"adapter": "fake"},
        EMPTY_SCOPE,
        object(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *args, **kwargs: DriftedAdapter(),
    )

    assert result.stats["errors"] == []
    assert result.list_complete is False
    assert result.drift[0]["message"] == "missing jobs array"


@pytest.mark.asyncio
async def test_run_pipeline_closes_comp_resolver_when_session_start_fails(monkeypatch):
    class Resolver:
        closed = False

        async def aclose(self):
            self.closed = True

    resolver = Resolver()
    opened = []

    @asynccontextmanager
    async def broken_session_scope():
        # The resolver is built before any session; it reads the reference rows
        # on the run's own session once that holds the lock.
        # That session is the one that fails.
        opened.append(True)
        raise RuntimeError("database unavailable")
        yield None

    monkeypatch.setattr(pipeline_module, "CompResolver", lambda *_providers: resolver)
    monkeypatch.setattr(pipeline_module, "session_scope", broken_session_scope)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await pipeline_module.run_pipeline()

    assert resolver.closed is True


@pytest.mark.asyncio
async def test_independent_sources_begin_collection_concurrently():
    """A slow backend must not delay the initial request to another backend."""
    release = asyncio.Event()
    started = {"first": asyncio.Event(), "second": asyncio.Event()}

    class WaitingAdapter:
        def __init__(self, company: str) -> None:
            self.company = company
            self.drift = SchemaDriftDetector(company)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def fetch(self):
            started[self.company].set()
            await release.wait()
            if False:  # make this an async generator without yielding a job
                yield None

        async def hydrate(self, job: RawJob) -> None:
            return None

    def factory(company: str, adapter: str, board_token: str | None, **kwargs):
        return WaitingAdapter(company)

    collection_task = asyncio.create_task(
        collect_sources(
            {"first": {"adapter": "greenhouse"}, "second": {"adapter": "ashby"}},
            EMPTY_SCOPE,
            object(),
            max_list=None,
            hydrate=False,
            max_concurrent_sources=2,
            adapter_factory=factory,
        )
    )
    await asyncio.wait_for(
        asyncio.gather(*(event.wait() for event in started.values())), timeout=0.2
    )
    release.set()
    collections = await collection_task

    assert all(not collection.stats["errors"] for collection in collections.values())


@pytest.mark.asyncio
async def test_companies_on_one_backend_use_one_collection_stream():
    release = asyncio.Event()
    started = {"first": asyncio.Event(), "second": asyncio.Event()}

    class WaitingAdapter:
        def __init__(self, company: str) -> None:
            self.company = company
            self.drift = SchemaDriftDetector(company)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def fetch(self):
            started[self.company].set()
            await release.wait()
            if False:
                yield None

        async def hydrate(self, job: RawJob) -> None:
            return None

    def factory(company: str, adapter: str, board_token: str | None, **kwargs):
        return WaitingAdapter(company)

    collection_task = asyncio.create_task(
        collect_sources(
            {"first": {"adapter": "greenhouse"}, "second": {"adapter": "greenhouse"}},
            EMPTY_SCOPE,
            object(),
            max_list=None,
            hydrate=False,
            max_concurrent_sources=5,
            adapter_factory=factory,
        )
    )
    await asyncio.wait_for(started["first"].wait(), timeout=0.2)
    await asyncio.sleep(0)

    assert started["second"].is_set() is False

    release.set()
    collections = await collection_task
    assert started["second"].is_set() is True
    assert all(not collection.stats["errors"] for collection in collections.values())


@pytest.mark.asyncio
async def test_collection_tracks_out_of_scope_source_keys_and_catalog_inventory():
    class InventoryAdapter:
        def __init__(self):
            self.drift = SchemaDriftDetector("acme")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            yield RawJob(
                company="acme",
                req_id="junior",
                title="Junior Software Engineer",
                url="https://example.test/junior",
                locations=["London, UK"],
            )

    def factory(*args, **kwargs):
        return InventoryAdapter()

    scope = ScopeFilter(
        enabled_bands=frozenset({"staff"}),
        enabled_roles=frozenset({"software_engineering"}),
        enabled_tracks=frozenset({"management", "product_program", "technical"}),
        enabled_locations=frozenset({"silicon_valley", "uk", "singapore"}),
        enabled_domains=frozenset(),
    )
    result = await collect_source(
        "acme",
        {"adapter": "fake"},
        scope,
        object(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=factory,
    )

    assert result.seen_keys == {"acme:junior"}
    assert result.scope_by_key == {"acme:junior": False}
    assert result.enriched == []
    assert result.catalog["software_engineering"].band_counts == {"entry": 1}  # Junior is Entry
    assert result.list_complete is True


@pytest.mark.asyncio
async def test_discovery_frontier_skips_existing_open_job_before_hydration_and_comp():
    class FrontierAdapter:
        def __init__(self):
            self.drift = SchemaDriftDetector("acme")
            self.hydrated = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            yield RawJob(
                company="acme",
                req_id="existing",
                title="Director of Software Engineering",
                url="https://example.test/existing",
                locations=["Mountain View, CA, USA"],
            )

        async def hydrate(self, raw):
            self.hydrated = True

    adapter = FrontierAdapter()
    scope = ScopeFilter(
        enabled_bands=frozenset({"staff", "principal", "director_plus"}),
        enabled_roles=frozenset({"engineering_management", "software_engineering"}),
        enabled_tracks=frozenset({"management", "technical"}),
        enabled_locations=frozenset({"silicon_valley", "united_states"}),
        enabled_domains=frozenset(),
    )

    result = await collect_source(
        "acme",
        {"adapter": "fake"},
        scope,
        object(),
        max_list=None,
        hydrate=True,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *args, **kwargs: adapter,
        scan_mode=ScanMode.DISCOVERY,
        lookups=SourceLookups(existing_open_keys=frozenset({"acme:existing"})),
    )

    assert result.stats["scanned"] == 1
    assert result.stats["kept"] == 1
    assert result.enriched == []
    assert adapter.hydrated is False


@pytest.mark.asyncio
async def test_a_wait_on_our_own_comp_lookup_is_not_the_sources_silence():
    """Every lane queues on the comp provider's one cache-miss lock, so with
    many lanes a lookup can outlast the stall window. That wait is ours: the
    board answered every item at once and must not be recorded stalled
    ."""

    class Board:
        def __init__(self):
            self.drift = SchemaDriftDetector("acme")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            for index in range(3):
                yield RawJob(
                    company="acme",
                    req_id=f"staff-{index}",
                    title="Staff Software Engineer",
                    url=f"https://example.test/staff-{index}",
                    locations=["London, UK"],
                )

    class QueuedComp:
        async def resolve(self, _context):
            await asyncio.sleep(0.3)  # longer than the stall window below
            return None, []

    scope = ScopeFilter(
        enabled_bands=frozenset({"staff"}),
        enabled_roles=frozenset({"software_engineering"}),
        enabled_tracks=frozenset({"management", "product_program", "technical"}),
        enabled_locations=frozenset({"uk"}),
        enabled_domains=frozenset(),
    )
    collections = await collect_sources(
        {"acme": {"adapter": _PACED_BACKEND}},
        scope,
        QueuedComp(),
        max_list=None,
        hydrate=False,
        max_concurrent_sources=1,
        source_budget_seconds=30,
        source_stall_seconds=0.2,
        adapter_factory=lambda *args, **kwargs: Board(),
    )

    result = collections["acme"]
    assert result.stats["errors"] == [], result.stats["errors"]
    assert result.stats["kept"] == 3 and len(result.enriched) == 3
    assert classify_source_outcome({**result.stats, "list_complete": result.list_complete}) is (
        SourceOutcome.OK
    )


# --------------------------------------------------------------------------- #
# Per-source time budget. The defect: a source that fails *slowly* is
# invisible to every guard until it has consumed the entire run — a source
# 429ing every page eats all 3600s and takes every healthy source with it.
#
# The bounds below need a provider name only to keep sibling sources on distinct
# backends (`collect_sources` queues per adapter name). It must be one the
# collection policy PERMITS: a denied provider is refused before the injected
# factory ever runs, so a denied one would turn every bound here into a skip
# measuring nothing. `test_the_paced_backend_is_a_provider_policy_permits`
# fails by name if that stops being true.
# --------------------------------------------------------------------------- #

_PACED_BACKEND = "ashby"


def test_the_paced_backend_is_a_provider_policy_permits() -> None:
    assert collection_access(_PACED_BACKEND).reason is None


class _TricklingAdapter:
    """Yields `fast_items` immediately, then one item every `delay` seconds.

    Models the realistic slow-source shape — a board that keeps answering, just
    far too slowly — which is what the *cooperative* deadline is built for: the
    check runs before each item, so the source exits between pages and keeps
    everything it already fetched.
    """

    def __init__(self, company: str, *, fast_items: int = 2, delay: float = 0.6) -> None:
        self.company = company
        self.drift = SchemaDriftDetector(company)
        self._fast_items = fast_items
        self._delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def _job(self, index: int) -> RawJob:
        return RawJob(
            company=self.company,
            req_id=f"{self.company}-{index}",
            title="Staff Software Engineer",
            url=f"https://example.test/{self.company}/{index}",
            locations=["London, UK"],
        )

    async def fetch(self):
        for index in range(self._fast_items):
            yield self._job(index)
        for index in range(self._fast_items, self._fast_items + 50):
            await asyncio.sleep(self._delay)
            yield self._job(index)


class _StalledAdapter:
    """Hangs inside a single await, never yielding again.

    The cooperative check cannot fire here — there is no next item — so this is
    the case the hard `wait_for` backstop exists for, and the case where that
    company's partial data is genuinely lost.
    """

    def __init__(self, company: str) -> None:
        self.company = company
        self.drift = SchemaDriftDetector(company)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        yield RawJob(
            company=self.company,
            req_id=f"{self.company}-0",
            title="Staff Software Engineer",
            url=f"https://example.test/{self.company}/0",
        )
        await asyncio.sleep(30)


class _FastAdapter:
    def __init__(self, company: str) -> None:
        self.company = company
        self.drift = SchemaDriftDetector(company)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        yield RawJob(
            company=self.company,
            req_id=f"{self.company}-1",
            title="Staff Software Engineer",
            url=f"https://example.test/{self.company}/1",
        )


async def _collect(
    targets, *, budget, factory, max_list=None, stall=None
):
    return await collect_sources(
        targets,
        EMPTY_SCOPE,
        object(),
        max_list=max_list,
        hydrate=False,
        max_concurrent_sources=len(targets),
        source_budget_seconds=budget,
        source_stall_seconds=stall,
        adapter_factory=factory,
    )


@pytest.mark.asyncio
async def test_a_slow_source_is_cut_at_its_budget_and_its_sibling_still_returns():
    """The bulkhead property: a degraded source degrades itself only."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company) if company == "slow" else _FastAdapter(company)

    loop = asyncio.get_running_loop()
    started = loop.time()
    collections = await _collect(
        {"slow": {"adapter": _PACED_BACKEND}, "fast": {"adapter": "greenhouse"}},
        budget=0.5,
        factory=factory,
    )
    elapsed = loop.time() - started

    # Bounded by the budget (+ its unwind grace), nowhere near the source's own
    # 30s of stalling.
    assert elapsed < 5

    fast = collections["fast"]
    assert fast.stats["errors"] == []
    assert fast.seen_keys == {"fast:fast-1"}  # the healthy sibling still delivered
    assert fast.list_complete is True

    slow = collections["slow"]
    # Cut by our own ceiling while it was still producing: `bounded`, not an
    # error. The cut is our threshold talking, so it must not read as a source
    # pathology — mislabelled, it would quarantine healthy bindings.
    assert slow.stats["bounded"] is True
    assert slow.stats["errors"] == []
    assert slow.list_complete is False
    # Closure safety is unchanged: an incomplete listing never closes jobs,
    # whether it was cut by us or broke on its own.
    assert should_close_missing(slow, max_list=None) is False


@pytest.mark.asyncio
async def test_budget_exhaustion_keeps_the_pages_already_fetched():
    """Cooperative exit, not a cancel.

    `asyncio.wait_for` discards the coroutine's return value even when the inner
    code suppresses the cancel — so enforcing the budget by cancelling would
    throw away every page the source had already collected. The deadline is
    passed *in* precisely so it does not.
    """

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company, fast_items=3)

    collections = await _collect(
        {"slow": {"adapter": _PACED_BACKEND}}, budget=0.5, factory=factory
    )

    slow = collections["slow"]
    assert slow.stats["scanned"] == 3
    assert slow.seen_keys == {"slow:slow-0", "slow:slow-1", "slow:slow-2"}


@pytest.mark.asyncio
async def test_a_source_stalled_inside_one_await_is_cut_by_the_hard_backstop():
    """The accepted trade, asserted explicitly.

    A source that never yields again cannot exit cooperatively, so `wait_for`
    cancels it and its in-flight data is lost. What must survive is the bound
    itself and the recorded reason — the run may not hang on it.
    """

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _StalledAdapter(company)

    loop = asyncio.get_running_loop()
    started = loop.time()
    collections = await _collect(
        {"stalled": {"adapter": _PACED_BACKEND}}, budget=0.5, factory=factory
    )
    elapsed = loop.time() - started

    assert elapsed < 5  # not the adapter's 30s
    stalled = collections["stalled"]
    # Ignoring the cooperative bound entirely IS a pathology, unlike hitting our
    # ceiling while producing — so this one stays an error and does reach health.
    assert any("SourceUnresponsive" in error for error in stalled.stats["errors"])
    assert stalled.stats["bounded"] is False
    assert stalled.stats["scanned"] == 0  # partial data discarded, as documented
    assert should_close_missing(stalled, max_list=None) is False


class _SlowToCloseAdapter:
    """Hangs mid-listing, then takes seconds to close once cancelled.

    Its backstop fires on time, but the cancelled scan takes far longer than
    its grace to unwind: the one way a company could hold its lane past every
    bound it has.
    """

    def __init__(self, company: str) -> None:
        self.company = company
        self.drift = SchemaDriftDetector(company)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        await asyncio.sleep(10)

    async def fetch(self):
        yield RawJob(
            company=self.company,
            req_id=f"{self.company}-0",
            title="Staff Software Engineer",
            url=f"https://example.test/{self.company}/0",
        )
        await asyncio.sleep(30)


@pytest.mark.asyncio
async def test_a_source_that_will_not_close_does_not_hold_its_lane():
    """No run bound stands behind a lane, so a source that ignores its
    cancellation is left behind once its grace is over: it is recorded
    unresponsive, and the company queued behind it on the same host is read."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _SlowToCloseAdapter(company) if company == "stuck" else _FastAdapter(company)

    targets = {name: {"adapter": "greenhouse"} for name in ("finished", "stuck", "queued")}
    loop = asyncio.get_running_loop()
    started = loop.time()
    collections = await collect_sources(
        targets, EMPTY_SCOPE, object(), max_list=None, hydrate=False,
        max_concurrent_sources=1, source_budget_seconds=0.2, adapter_factory=factory,
    )
    elapsed = loop.time() - started

    outcome = {
        company: classify_source_outcome({**c.stats, "list_complete": c.list_complete})
        for company, c in collections.items()
    }
    assert outcome == {
        "finished": SourceOutcome.OK, "stuck": SourceOutcome.FAILED, "queued": SourceOutcome.OK,
    }
    assert any("SourceUnresponsive" in error for error in collections["stuck"].stats["errors"])
    assert elapsed < 5, elapsed


@pytest.mark.asyncio
async def test_every_company_of_a_lane_is_read_however_long_the_lane_takes():
    """A company bounded by its own ceiling and the company behind it on the
    same host: the second is read, never deferred for the time the first took."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company) if company == "long" else _FastAdapter(company)

    collections = await collect_sources(
        {name: {"adapter": _PACED_BACKEND} for name in ("long", "next")},
        EMPTY_SCOPE, object(), max_list=None, hydrate=False,
        max_concurrent_sources=1, source_budget_seconds=0.5, adapter_factory=factory,
    )

    long_, next_ = collections["long"], collections["next"]
    assert classify_source_outcome({**long_.stats, "list_complete": long_.list_complete}) is (
        SourceOutcome.BOUNDED
    ), "the long company is bounded by our ceiling and keeps what it read"
    assert long_.stats["scanned"] >= 2
    assert classify_source_outcome({**next_.stats, "list_complete": next_.list_complete}) is (
        SourceOutcome.OK
    )
    assert "deferred_reason" not in next_.stats


@pytest.mark.asyncio
async def test_a_ceiling_exhausted_source_is_bounded_not_capped_and_not_degraded():
    """Three-way distinction, not two.

    `capped` = the operator chose it. `bounded` = we chose it. `degraded` = the
    source broke. Collapsing the middle case into `degraded` would score an
    anomaly on every healthy long-running source and quarantine its binding;
    collapsing it into `capped` would make it retry-ineligible and silently
    clean. It has to be its own thing."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company)

    collections = await _collect(
        {"slow": {"adapter": _PACED_BACKEND}}, budget=0.5, factory=factory
    )

    stats = collections["slow"].stats
    stats["list_complete"] = collections["slow"].list_complete

    assert stats["capped"] is False
    assert classify_source_outcome(stats) is SourceOutcome.BOUNDED


@pytest.mark.asyncio
async def test_an_operator_cap_is_capped_not_degraded():
    """The mirror case: `--max-list` is a choice, not a pathology, so it must
    not advance binding health."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company, fast_items=10)

    collections = await _collect(
        {"acme": {"adapter": "greenhouse"}}, budget=30, factory=factory, max_list=2
    )

    stats = collections["acme"].stats
    stats["list_complete"] = collections["acme"].list_complete

    assert stats["errors"] == []
    assert stats["capped"] is True
    assert classify_source_outcome(stats) is SourceOutcome.CAPPED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_list", "capped", "outcome"),
    [(10, True, SourceOutcome.CAPPED), (None, False, SourceOutcome.OK)],
    ids=["cap_set_never_fired", "uncapped_control"],
)
async def test_an_operator_cap_governs_a_board_that_finishes_under_it(max_list, capped, outcome):
    """`capped` records that an operator cap governed the scan, not
    that it fired. A one-row board under a cap of 10 enumerates completely and
    stays `list_complete` — that part is true — but a test run is still not
    evidence about the source, so it classifies `capped` and never `ok`."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _FastAdapter(company)

    collections = await _collect(
        {"acme": {"adapter": "greenhouse"}}, budget=30, factory=factory, max_list=max_list
    )

    collection = collections["acme"]
    assert collection.stats["errors"] == []
    assert collection.stats["scanned"] == 1
    assert collection.list_complete is True
    assert collection.stats["capped"] is capped
    assert classify_source_outcome(
        {**collection.stats, "list_complete": collection.list_complete}
    ) is outcome


def test_companies_on_one_backend_share_a_single_pacer():
    pool = RateLimiterPool()

    first = GreenhouseAdapter("first", limiter_pool=pool)
    second = GreenhouseAdapter("second", limiter_pool=pool)

    assert first._limiter is second._limiter


def test_build_adapter_wires_both_bulkheads_onto_the_adapter():
    """The seam BOTH workflows depend on.

    `collect_sources` and `discover_roles` each hand these bounds to
    `build_adapter`; if they stop reaching the adapter, both silently fall back
    to an unbounded retry path with no test failing anywhere else.
    """
    breakers = BreakerPool()
    adapter = build_adapter(
        "acme", "greenhouse", None, limiter_pool=RateLimiterPool(),
        breaker_pool=breakers, deadline=1234.5,
    )

    assert adapter._breaker is not None
    assert adapter._deadline == 1234.5
    # Keyed on the same scope as the pacer, so companies sharing a backend
    # share the breaker that protects it.
    scope = adapter.rate_limit_scope or adapter.name
    assert adapter._breaker is breakers.get(scope, 5)


def test_an_adapter_built_without_a_pool_has_no_breaker():
    """Standalone/CLI construction must not get a private per-adapter breaker —
    one that could never observe a streak is worse than none."""
    adapter = build_adapter("acme", "greenhouse")

    assert adapter._breaker is None
    assert adapter._deadline is None


@pytest.mark.asyncio
async def test_apple_stops_detail_hydration_after_repeat_auth_block(monkeypatch):
    adapter = AppleAdapter("apple")
    responses = iter([SimpleNamespace(status_code=401), SimpleNamespace(status_code=401)])
    requests: list[str] = []

    async def fake_get(url: str, **kwargs):
        requests.append(url)
        return next(responses)

    async def refreshed() -> bool:
        return True

    monkeypatch.setattr(adapter, "get", fake_get)
    monkeypatch.setattr(adapter, "_ensure_csrf", refreshed)
    job = RawJob(
        company="apple",
        req_id="123",
        title="Engineering Manager",
        url="https://jobs.apple.com/en-us/details/123/engineering-manager",
    )

    await adapter.hydrate(job)
    await adapter.hydrate(job)

    assert len(requests) == 2  # one retry after refresh; later jobs are skipped
    assert adapter._detail_access_blocked is True
    assert adapter.drift.alerts == [
        {
            "source": "apple:apple",
            "message": "detail access blocked after CSRF refresh; hydration disabled for run",
            "status": 401,
            "req": "123",
        }
    ]


# --------------------------------------------------------------------------- #
# Heartbeat / persist-loop lock ordering.
#
# The detached heartbeat and the persist loop are the only two writers of both
# `scrape_runs` and `notifications`, in separate sessions, concurrently. If they
# disagree on the order they touch those two tables, they deadlock: Postgres
# kills the loop's `scrape_runs` UPDATE, the session goes PendingRollbackError,
# and the run sticks in `running`.
#
# This pins the heartbeat's half. The loop's half is the `session.flush()` before
# `update_sync_progress`; it lives inside `run_pipeline`, which needs a live DB
# and two concurrent sessions to exercise, so it is covered by the live run
# rather than here.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_heartbeat_writes_scrape_runs_before_notifications(monkeypatch):
    order: list[str] = []

    class RecordingSession:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "scrape_runs" in sql:
                order.append("scrape_runs")
            elif "notifications" in sql:
                order.append("notifications")
            return None

        @asynccontextmanager
        async def begin_nested(self):
            yield

    @asynccontextmanager
    async def fake_scope():
        yield RecordingSession()

    monkeypatch.setattr(pipeline_module, "session_scope", fake_scope)

    progress = pipeline_module.RunProgress(companies_total=1)
    task = pipeline_module._heartbeat_task(run_id=7, interval_seconds=0, progress=progress)
    # Let the loop complete at least one full beat, then stop it.
    for _ in range(50):
        await asyncio.sleep(0)
        if len(order) >= 2:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert order[:2] == ["scrape_runs", "notifications"], order


# --------------------------------------------------------------------------- #
# Progress-based liveness: stall (the source's fault) vs ceiling (ours).
#
# One fixed budget cannot tell "slow but working" from "hung": set low, it cuts
# healthy sources every run and quarantines their bindings. These pin the
# discrimination a fixed bound cannot make.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_steadily_producing_source_outlives_a_budget_that_would_have_cut_it():
    """The headline rule. The source keeps yielding every 0.05s for well past the
    0.3s that a fixed budget would have allowed; progress must keep it alive."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company, fast_items=0, delay=0.05)

    collections = await _collect(
        {"steady": {"adapter": _PACED_BACKEND}},
        budget=30,  # ceiling far away
        stall=0.3,  # where a fixed budget would cut
        factory=factory,
    )

    steady = collections["steady"]
    # All 50 items, despite running ~2.5s against a 0.3s window.
    assert steady.stats["scanned"] == 50
    assert steady.stats["errors"] == []
    assert steady.stats["bounded"] is False
    assert classify_source_outcome(
        {**steady.stats, "list_complete": steady.list_complete}
    ) is not SourceOutcome.DEGRADED


@pytest.mark.asyncio
async def test_a_source_that_goes_silent_is_stalled_and_stays_a_health_signal():
    """The other half: silence for longer than the window is the source's own
    pathology, so it keeps its error and still reaches binding health."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        # Two quick items, then a gap far longer than the stall window.
        return _TricklingAdapter(company, fast_items=2, delay=0.5)

    collections = await _collect(
        {"quiet": {"adapter": _PACED_BACKEND}},
        budget=30,  # ceiling nowhere near — only the stall bound can fire
        stall=0.1,
        factory=factory,
    )

    quiet = collections["quiet"]
    assert any("SourceStalled" in error for error in quiet.stats["errors"])
    assert quiet.stats["bounded"] is False
    # The pages fetched before it went quiet survive: cooperative exit, not a cancel.
    assert quiet.stats["scanned"] == 2
    stats = {**quiet.stats, "list_complete": quiet.list_complete}
    assert classify_source_outcome(stats) is SourceOutcome.DEGRADED
    assert SourceOutcome.DEGRADED in RESETS_ABSENCE


@pytest.mark.asyncio
async def test_a_still_producing_source_that_hits_the_ceiling_is_bounded_not_stalled():
    """A slow trickle is what the ceiling exists for — but it is our bound, so
    it must not be recorded as the source going silent."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company, fast_items=0, delay=0.05)

    collections = await _collect(
        {"trickle": {"adapter": _PACED_BACKEND}},
        budget=0.3,  # ceiling bites first
        stall=30,  # generous window: the source is never silent
        factory=factory,
    )

    trickle = collections["trickle"]
    assert trickle.stats["bounded"] is True
    assert trickle.stats["errors"] == []
    assert 0 < trickle.stats["scanned"] < 50  # cut mid-listing, kept its pages
    assert trickle.list_complete is False
    assert should_close_missing(trickle, max_list=None) is False


@pytest.mark.asyncio
async def test_a_stalled_source_does_not_take_its_healthy_sibling_down():
    """Bulkheading still holds with these bounds."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company, fast_items=1, delay=0.5) if company == "quiet" else _FastAdapter(company)

    collections = await _collect(
        {"quiet": {"adapter": _PACED_BACKEND}, "fast": {"adapter": "greenhouse"}},
        budget=30,
        stall=0.1,
        factory=factory,
    )

    assert any("SourceStalled" in e for e in collections["quiet"].stats["errors"])
    fast = collections["fast"]
    assert fast.stats["errors"] == []
    assert fast.list_complete is True


@pytest.mark.asyncio
async def test_an_operator_cap_still_wins_over_our_ceiling():
    """`--max-list` is an instruction; a bounded source is retry-eligible and a
    capped one is not, so letting the ceiling win would override the operator."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _TricklingAdapter(company, fast_items=5, delay=0.01)

    collections = await _collect(
        {"slow": {"adapter": _PACED_BACKEND}},
        budget=30,
        stall=30,
        max_list=3,
        factory=factory,
    )

    stats = collections["slow"].stats
    assert stats["capped"] is True
    assert stats["bounded"] is False
    assert classify_source_outcome(
        {**stats, "list_complete": collections["slow"].list_complete}
    ) is SourceOutcome.CAPPED


class _DeadlineRaisingAdapter:
    """Yields a few items, then raises `RetryDeadlineExceeded` from its transport.

    Meta's shape: paced items run straight into the ceiling, and the
    *transport* notices first — so the exception surfaces before the pipeline's
    per-item check can label the stop.
    """

    def __init__(self, company: str, *, items: int = 3, delay: float = 1.2) -> None:
        self.company = company
        self.drift = SchemaDriftDetector(company)
        self._items = items
        self._delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for index in range(self._items):
            yield RawJob(
                company=self.company,
                req_id=f"{self.company}-{index}",
                title="Staff Software Engineer",
                url=f"https://example.test/{self.company}/{index}",
            )
        await asyncio.sleep(self._delay)  # let the bound expire
        raise RetryDeadlineExceeded(f"{self.company}: no time left to retry")


@pytest.mark.asyncio
async def test_a_deadline_exception_at_the_ceiling_is_bounded_not_an_error():
    """The transport raising `RetryDeadlineExceeded` means a bound stopped us — not
    that the source misbehaved. Recorded as an error, it would make the source
    `degraded` and score a health anomaly for being slow, which is precisely the
    misattribution `bounded` exists to prevent.
    """

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _DeadlineRaisingAdapter(company)

    collections = await _collect(
        {"slow": {"adapter": _PACED_BACKEND}},
        budget=1.0,  # ceiling expires during the adapter's sleep, backstop at 2.0s
        stall=30,  # generous: the source was never silent, only slow
        factory=factory,
    )

    slow = collections["slow"]
    assert slow.stats["errors"] == []
    assert slow.stats["bounded"] is True
    assert slow.stats["scanned"] == 3  # the pages it did fetch survive
    stats = {**slow.stats, "list_complete": slow.list_complete}
    assert classify_source_outcome(stats) is SourceOutcome.BOUNDED
    assert SourceOutcome.BOUNDED not in RESETS_ABSENCE
    assert should_close_missing(slow, max_list=None) is False


@pytest.mark.asyncio
async def test_a_deadline_exception_after_going_silent_is_still_a_stall():
    """The other attribution: if the *stall* bound is what expired, the source
    did go quiet, and that stays a health signal even via the same exception."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _DeadlineRaisingAdapter(company)

    collections = await _collect(
        {"quiet": {"adapter": _PACED_BACKEND}},
        budget=30,  # ceiling far away, so only the stall bound can fire
        stall=0.3,
        factory=factory,
    )

    quiet = collections["quiet"]
    assert any("SourceStalled" in e for e in quiet.stats["errors"])
    assert quiet.stats["bounded"] is False


class _BlockedAdapter:
    """A source whose scope circuit opened as blocked (WAF-style refusal)."""

    def __init__(self, company: str, *, scanned_first: int = 0) -> None:
        self.company = company
        self.drift = SchemaDriftDetector(company)
        self._scanned_first = scanned_first

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for index in range(self._scanned_first):
            yield RawJob(
                company=self.company,
                req_id=f"{self.company}-{index}",
                title="Staff Software Engineer",
                url=f"https://example.test/{self.company}/{index}",
            )
        raise CircuitOpenError(self.company, 10, blocked=True)


@pytest.mark.asyncio
async def test_a_blocked_source_classifies_blocked_and_its_sibling_still_lands():
    """The breaker's block verdict must reach the outcome vocabulary.

    Folded into `degraded`/`failed`, "the source is refusing us" is
    indistinguishable from "the source errored" — and only the former means
    retries and probes are pure cost."""

    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _BlockedAdapter(company) if company == "blocked" else _FastAdapter(company)

    collections = await _collect(
        {"blocked": {"adapter": _PACED_BACKEND}, "fast": {"adapter": "greenhouse"}},
        budget=30,
        factory=factory,
    )

    blocked_stats = collections["blocked"].stats
    assert blocked_stats["blocked"] is True
    assert any("blocked" in error for error in blocked_stats["errors"])
    assert classify_source_outcome(blocked_stats) is SourceOutcome.BLOCKED
    assert collections["blocked"].list_complete is False
    # Bulkhead holds: the sibling is untouched.
    assert collections["fast"].stats["errors"] == []


@pytest.mark.asyncio
async def test_pages_collected_before_the_block_survive_but_never_authorize_closure():
    def factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
        return _BlockedAdapter(company, scanned_first=3)

    collections = await _collect({"blocked": {"adapter": _PACED_BACKEND}}, budget=30, factory=factory)

    stats = collections["blocked"].stats
    assert stats["scanned"] == 3  # partial data kept, not discarded
    assert classify_source_outcome(stats) is SourceOutcome.BLOCKED
    assert should_close_missing(collections["blocked"], max_list=None) is False
