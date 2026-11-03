"""Live scrape progress: counter semantics + notification publication.

Contract under test (docs/architecture.md "Scheduling"): a run publishes
incremental per-company progress into its ``sync_started`` notification so the
collect phase — which writes nothing to the DB — is observable while it happens.

Two invariants carry most of the weight here:

* **in flight != not finished.** The collector semaphore admits a bounded number
  of backends, so most unfinished companies are queued, not working.
* **every company reaches a terminal state.** A company the collector never
  reported must be reconciled, or the UI shows it working forever.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from tracker.connectors.listing.base import SchemaDriftDetector
from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.enrich.enricher import ScopeFilter
from tracker.workflows.collection import collect_sources
from tracker.workflows.progress import RunProgress

#: Frozen so `since_ms` assertions are exact rather than "roughly now".
FIXED_MS = 1_700_000_000_000


def _progress(*slugs: str, limit: int = 5, clock=lambda: FIXED_MS) -> RunProgress:
    p = RunProgress(companies_total=0, clock=clock)
    p.set_targets(slugs, concurrency_limit=limit)
    return p


class TestRunProgressCounters:
    def test_seeded_run_reports_every_company_queued_not_scraping(self):
        """Fails "`total - collected` are in flight", which calls all 5 'scraping'.

        Nothing has started, so nothing is in flight. A run that has resolved its
        targets and not yet acquired a collector slot is 5 queued, 0 working.
        """
        p = _progress("a", "b", "c", "d", "e")
        snap = p.snapshot()
        assert snap["phase"] == "collecting"
        assert snap["percent"] == 0
        assert snap["companies_total"] == 5
        assert snap["companies_scraping"] == 0
        assert snap["companies_queued"] == 5
        assert snap["opportunities_detected"] == 0
        assert snap["opportunities_recorded"] == 0

    def test_unknown_total_reports_zero_not_complete(self):
        """Run open sets total=0 before targets resolve; that is not 100%."""
        assert RunProgress(companies_total=0).snapshot()["percent"] == 0

    def test_scraping_counts_only_started_sources(self):
        p = _progress("a", "b", "c", "d", "e")
        p.source_started("a")
        p.source_started("b")
        snap = p.snapshot()
        assert snap["companies_scraping"] == 2
        assert snap["companies_queued"] == 3
        assert snap["companies_collected"] == 0

    def test_collection_advances_detected_and_shrinks_scraping(self):
        p = _progress("apple", "google", "meta")
        p.source_started("apple")
        p.source_started("google")
        p.source_collected("apple", 40, "ok", 400)
        p.source_collected("google", 60, "ok", 600)
        snap = p.snapshot()
        assert snap["companies_collected"] == 2
        assert snap["companies_scraping"] == 0
        assert snap["companies_queued"] == 1
        assert snap["opportunities_detected"] == 100
        # Nothing written yet — detected must lead recorded.
        assert snap["opportunities_recorded"] == 0
        assert snap["opportunities_pending"] == 100

    def test_persist_advances_recorded_and_drains_pending(self):
        p = _progress("apple", "google")
        p.source_collected("apple", 40, "ok")
        p.source_collected("google", 60, "ok")
        p.set_phase("persisting")
        p.source_persist_started("apple")
        p.source_recorded("apple", 40)
        snap = p.snapshot()
        assert snap["companies_recorded"] == 1
        assert snap["opportunities_recorded"] == 40
        assert snap["opportunities_pending"] == 60

    def test_persist_started_marks_exactly_one_company(self):
        """Persist is serial: two companies must never be writing at once."""
        p = _progress("a", "b")
        p.source_collected("a", 1, "ok")
        p.source_collected("b", 1, "ok")
        p.source_persist_started("a")
        p.source_recorded("a", 1)
        p.source_persist_started("b")
        states = {c["slug"]: c["state"] for c in p.snapshot()["companies"]}
        assert states == {"a": "recorded", "b": "persisting"}

    def test_failed_source_counts_as_collected_but_adds_no_opportunities(self):
        """A dead source must not stall the bar at 'still scraping' forever."""
        p = _progress("apple", "broken")
        p.source_collected("apple", 10, "ok", 100)
        p.source_collected("broken", 0, "failed", 0)
        snap = p.snapshot()
        assert snap["companies_collected"] == 2
        assert snap["companies_scraping"] == 0
        assert snap["companies_failed"] == 1
        assert snap["opportunities_detected"] == 10

    def test_capped_source_is_not_a_failure(self):
        """`--max-list` is an operator choice, never a source pathology."""
        p = _progress("a")
        p.source_collected("a", 12, "capped", 150)
        snap = p.snapshot()
        assert snap["companies_failed"] == 0
        assert snap["companies_collected"] == 1

    def test_degraded_source_is_reported_separately_from_failed(self):
        """Errors plus usable data is a partial refresh, not a dead source."""
        p = _progress("a")
        p.source_collected("a", 5, "degraded", 80)
        snap = p.snapshot()
        assert snap["companies_failed"] == 0
        assert snap["companies_degraded"] == 1

    def test_scanned_a_full_board_and_kept_nothing_is_a_success(self):
        """The distinction `detected` alone cannot draw, and must not read as
        failure: a source can legitimately scan everything and keep none of it."""
        p = _progress("a")
        p.source_collected("a", 0, "ok", 812)
        snap = p.snapshot()
        assert snap["companies_failed"] == 0
        entry = snap["companies"][0]
        assert entry["detected"] == 0
        assert entry["scanned"] == 812
        assert entry["outcome"] == "ok"

    def test_percent_spans_both_phases(self):
        p = _progress("a", "b")
        assert p.snapshot()["percent"] == 0
        p.source_collected("a", 1, "ok")
        p.source_collected("b", 1, "ok")
        # Collection done == half the work.
        assert p.snapshot()["percent"] == 50
        p.source_recorded("a", 1)
        p.source_recorded("b", 1)
        assert p.snapshot()["percent"] == 100

    def test_percent_never_exceeds_100_when_reports_repeat(self):
        p = _progress("a")
        for _ in range(4):
            p.source_collected("a", 1, "ok")
            p.source_recorded("a", 1)
        assert p.snapshot()["percent"] == 100

    def test_pending_never_negative_when_recorded_exceeds_detected(self):
        """Closed/re-seen rows can push kept above what this run detected."""
        p = _progress("a")
        p.source_collected("a", 2, "ok")
        p.source_recorded("a", 9)
        assert p.snapshot()["opportunities_pending"] == 0

    def test_negative_counts_are_clamped(self):
        p = _progress("a")
        p.source_collected("a", -5, "ok", -1)
        p.source_recorded("a", -3)
        snap = p.snapshot()
        assert snap["opportunities_detected"] == 0
        assert snap["opportunities_recorded"] == 0
        assert snap["companies"][0]["scanned"] == 0

    def test_repeat_report_does_not_double_count(self):
        """The collector hook and the reconcile pass both report a company."""
        p = _progress("a")
        p.source_collected("a", 40, "ok")
        p.source_collected("a", 40, "ok")
        assert p.snapshot()["opportunities_detected"] == 40
        assert p.snapshot()["companies_collected"] == 1

    def test_unknown_outcome_is_rejected(self):
        """The guard against a second outcome vocabulary reaching the UI."""
        with pytest.raises(ValueError):
            _progress("a").source_collected("a", 1, "banana", 1)

    def test_recording_an_unknown_company_is_ignored(self):
        """Runs inside the pipeline's transaction: it must never raise there."""
        p = _progress("a")
        p.source_recorded("never-heard-of-it", 5)
        assert p.snapshot()["companies_recorded"] == 0

    def test_unknown_phase_rejected(self):
        with pytest.raises(ValueError):
            RunProgress(companies_total=1).set_phase("bogus")

    def test_phase_transitions(self):
        p = _progress("a")
        for phase in ("collecting", "persisting", "finishing"):
            p.set_phase(phase)
            assert p.snapshot()["phase"] == phase


class TestSnapshotWireFormat:
    """`update_sync_progress` json.dumps() this inside the run's transaction."""

    def test_snapshot_is_json_serializable_in_every_state(self):
        p = _progress("queued-one", "working", "landed", "written")
        p.source_started("working")
        p.source_collected("landed", 7, "capped", 150)
        p.source_collected("written", 3, "ok", 30)
        p.source_persist_started("written")
        p.source_recorded("written", 3)
        assert json.loads(json.dumps(p.snapshot())) == p.snapshot()

    def test_snapshot_keeps_every_legacy_key(self):
        """Old rows and old readers must not break on the added block."""
        snap = _progress("a").snapshot()
        for key in (
            "phase",
            "percent",
            "companies_total",
            "companies_collected",
            "companies_recorded",
            "companies_scraping",
            "companies_failed",
            "opportunities_detected",
            "opportunities_recorded",
            "opportunities_pending",
        ):
            assert key in snap

    def test_company_order_follows_target_order(self):
        p = _progress("zebra", "apple", "mango")
        assert [c["slug"] for c in p.snapshot()["companies"]] == ["zebra", "apple", "mango"]

    def test_queued_company_has_no_start_timestamp(self):
        """A clock must not start on work that has not begun."""
        entry = _progress("a").snapshot()["companies"][0]
        assert entry["since_ms"] is None
        assert entry["outcome"] is None

    def test_since_ms_restamps_on_each_transition(self):
        ticks = iter([10, 20, 30, 40])
        p = _progress("a", clock=lambda: next(ticks))
        p.source_started("a")
        assert p.companies["a"].since_ms == 10
        p.source_collected("a", 1, "ok")
        assert p.companies["a"].since_ms == 20

    def test_concurrency_limit_is_published(self):
        assert _progress("a", limit=3).snapshot()["concurrency_limit"] == 3

    def test_snapshot_anchor_advances_with_the_clock(self):
        ticks = iter([111, 222])
        p = RunProgress(companies_total=0, clock=lambda: next(ticks))
        assert p.snapshot()["snapshot_at_ms"] == 111
        assert p.snapshot()["snapshot_at_ms"] == 222


class TestReconcile:
    """A company the collector never reported must not stay 'in flight'."""

    def test_forces_stuck_scraping_to_its_real_outcome(self):
        p = _progress("reported", "lost")
        p.source_started("reported")
        p.source_started("lost")
        p.source_collected("reported", 10, "ok", 100)
        assert p.snapshot()["companies_scraping"] == 1

        p.reconcile_collected(
            {"reported": (10, "ok", 100), "lost": (0, "failed", 0)}
        )
        snap = p.snapshot()
        assert snap["companies_scraping"] == 0
        assert snap["companies_queued"] == 0
        assert snap["companies_collected"] == 2
        assert snap["companies_failed"] == 1
        # The reported company must not be counted twice.
        assert snap["opportunities_detected"] == 10

    def test_is_idempotent(self):
        p = _progress("a", "b")
        results = {"a": (5, "ok", 50), "b": (0, "failed", 0)}
        p.reconcile_collected(results)
        p.reconcile_collected(results)
        p.reconcile_collected(results)
        snap = p.snapshot()
        assert snap["opportunities_detected"] == 5
        assert snap["companies_collected"] == 2

    def test_never_downgrades_an_already_recorded_company(self):
        p = _progress("a")
        p.source_collected("a", 5, "ok", 50)
        p.source_recorded("a", 5)
        p.reconcile_collected({"a": (0, "failed", 0)})
        snap = p.snapshot()
        assert snap["companies_recorded"] == 1
        assert snap["companies_failed"] == 0
        assert snap["opportunities_recorded"] == 5


EMPTY_SCOPE = ScopeFilter(
    enabled_bands=frozenset(),
    enabled_roles=frozenset(),
    enabled_tracks=frozenset(),
    enabled_locations=frozenset(),
    enabled_domains=frozenset(),
)


def _stub_factory(company: str, adapter: str, board_token: str | None = None, **kwargs):
    """Adapter whose board proves it lists nothing; never touches the network."""

    class _Stub:
        def __init__(self, name: str) -> None:
            self.company = name
            self.drift = SchemaDriftDetector(name)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def fetch(self):
            # Yield to the loop so sibling backends genuinely interleave; a
            # synchronous stub would serialize the test by accident and hide a
            # concurrency regression.
            await asyncio.sleep(0)
            # A board that answered in full and proved it lists nothing;
            # a zero it did not explain would be a failure.
            self.drift.board_empty("stub board lists nothing")
            if False:  # async generator that yields no jobs
                yield None

        async def hydrate(self, job):
            return None

    return _Stub(company)


def _reconcile_payload(collections) -> dict[str, tuple[int, str, int]]:
    """Exactly what the pipeline builds after `collect_sources` returns."""
    return {
        company: (
            len(collection.enriched),
            classify_source_outcome(
                {**collection.stats, "list_complete": collection.list_complete}
            ).value,
            int(collection.stats.get("scanned") or 0),
        )
        for company, collection in collections.items()
    }


async def _collect(targets, *, limit, progress=None, **kwargs):
    if progress is not None:
        kwargs.setdefault("on_source_start", progress.source_started)
        kwargs.setdefault("on_source_done", progress.source_collected)
    return await collect_sources(
        targets,
        EMPTY_SCOPE,
        object(),
        max_list=None,
        hydrate=False,
        max_concurrent_sources=limit,
        adapter_factory=_stub_factory,
        **kwargs,
    )


class TestCollectorProgressHook:
    """``collect_sources`` must report starts and completions without breaking."""

    @pytest.mark.asyncio
    async def test_hook_fires_once_per_source_with_its_outcome(self):
        seen: list[tuple[str, int, str, int]] = []
        await _collect(
            {"first": {"adapter": "greenhouse"}, "second": {"adapter": "ashby"}},
            limit=2,
            on_source_done=lambda c, d, o, s: seen.append((c, d, o, s)),
        )
        assert sorted(c for c, _, _, _ in seen) == ["first", "second"]
        assert all(detected == 0 for _, detected, _, _ in seen)
        # A board proven empty is a scan with no postings, not a failure.
        assert {outcome for _, _, outcome, _ in seen} == {"empty"}

    @pytest.mark.asyncio
    async def test_start_precedes_done_for_every_source(self):
        events: list[tuple[str, str]] = []
        await _collect(
            {"first": {"adapter": "greenhouse"}, "second": {"adapter": "ashby"}},
            limit=2,
            on_source_start=lambda c: events.append(("start", c)),
            on_source_done=lambda c, d, o, s: events.append(("done", c)),
        )
        for company in ("first", "second"):
            own = [kind for kind, name in events if name == company]
            assert own == ["start", "done"]

    @pytest.mark.asyncio
    async def test_two_companies_on_one_backend_never_run_at_once(self):
        """A backend holds its slot and drains its companies serially, so its
        second company is queued — not in flight — while the first works."""
        events: list[tuple[str, str]] = []
        await _collect(
            {"first": {"adapter": "greenhouse"}, "second": {"adapter": "greenhouse"}},
            limit=5,
            on_source_start=lambda c: events.append(("start", c)),
            on_source_done=lambda c, d, o, s: events.append(("done", c)),
        )
        assert events == [
            ("start", "first"),
            ("done", "first"),
            ("start", "second"),
            ("done", "second"),
        ]

    @pytest.mark.asyncio
    async def test_in_flight_never_exceeds_the_concurrency_limit(self):
        targets = {
            "a": {"adapter": "greenhouse"},
            "b": {"adapter": "ashby"},
            "c": {"adapter": "workday"},
            "d": {"adapter": "eightfold"},
        }
        p = _progress(*targets, limit=2)
        peak = 0

        def watch(company: str) -> None:
            nonlocal peak
            p.source_started(company)
            peak = max(peak, p.companies_scraping)

        await collect_sources(
            targets,
            EMPTY_SCOPE,
            object(),
            max_list=None,
            hydrate=False,
            max_concurrent_sources=2,
            adapter_factory=_stub_factory,
            on_source_start=watch,
            on_source_done=p.source_collected,
        )
        assert peak <= 2
        assert p.snapshot()["companies_scraping"] == 0

    @pytest.mark.asyncio
    async def test_broken_hooks_do_not_fail_collection(self):
        """Progress hooks are display-only; raising must not cost the scrape."""
        calls: list[str] = []

        def exploding_start(company: str) -> None:
            calls.append(f"start:{company}")
            raise RuntimeError("progress backend down")

        def exploding_done(company: str, detected: int, outcome: str, scanned: int) -> None:
            calls.append(f"done:{company}")
            raise RuntimeError("progress backend down")

        collections = await _collect(
            {"first": {"adapter": "greenhouse"}},
            limit=1,
            on_source_start=exploding_start,
            on_source_done=exploding_done,
        )
        assert calls == ["start:first", "done:first"]
        assert not collections["first"].stats["errors"]

    @pytest.mark.asyncio
    async def test_reconcile_clears_a_company_the_hook_never_recorded(self):
        """The regression guard for the reporting gap.

        A swallowed hook failure leaves a company stuck at `scraping` — the same
        end state as the cancelled-backend fill-in, which also never reaches the
        completion hook. Reconciling against the returned collections is what
        clears both.
        """
        targets = {"good": {"adapter": "greenhouse"}, "silent": {"adapter": "ashby"}}
        p = _progress(*targets, limit=2)

        def done(company: str, detected: int, outcome: str, scanned: int) -> None:
            if company == "silent":
                raise RuntimeError("dropped on the floor")
            p.source_collected(company, detected, outcome, scanned)

        collections = await _collect(
            targets, limit=2, on_source_start=p.source_started, on_source_done=done
        )
        assert p.snapshot()["companies_scraping"] == 1

        p.reconcile_collected(_reconcile_payload(collections))
        snap = p.snapshot()
        assert snap["companies_scraping"] == 0
        assert snap["companies_queued"] == 0
        assert all(c["outcome"] is not None for c in snap["companies"])

    @pytest.mark.asyncio
    async def test_progress_object_wires_directly_as_both_hooks(self):
        p = _progress("first", "second")
        await _collect(
            {"first": {"adapter": "greenhouse"}, "second": {"adapter": "ashby"}},
            limit=2,
            progress=p,
        )
        snap = p.snapshot()
        assert snap["companies_collected"] == 2
        assert snap["companies_scraping"] == 0
        assert snap["companies_queued"] == 0

    @pytest.mark.asyncio
    async def test_no_hook_is_supported(self):
        collections = await _collect({"first": {"adapter": "greenhouse"}}, limit=1)
        assert "first" in collections
