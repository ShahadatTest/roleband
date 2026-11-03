"""What a pipeline run leaves behind, however it ends.

Characterization of the pipeline along its seams: real scratch
Postgres, offline adapters, and a post-pass table cut down to the passes a case
needs. Nothing here replaces the pipeline itself. Four claims:

1. **A finished run releases what it took.** Whether it succeeds, loses its only
   source, or fails in a fatal post-pass: the advisory lock is free, the
   heartbeat task is finished, every adapter it opened is closed, the comp
   resolver is closed, and the run row carries a terminal status.
2. **A cancelled run releases its lock, heartbeat and collection, and writes no
   terminal status.** Every adapter it opened is closed and no `collect:` task
   outlives it. `CancelledError` is not an `Exception`, so the
   recovery block does not run; the committed marker stays `running` with its
   heartbeat stopped, which is exactly what the stale-run reconciler reads.
3. **Per-source commits survive a later failure.** A fatal post-pass after two
   sources persisted leaves both sources' jobs and source-run rows committed and
   records both on the failed run.
4. **The audit dicts keep their shape.** `scrape_runs.per_source[company]`,
   `scrape_source_runs.stats` and the summary `run_pipeline` returns carry exactly
   these keys and value types, per outcome, so a typed rewrite cannot rename,
   drop or retype a field that stored rows and readers already depend on.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.barriers import until_waiting
from tracker.config import COMPANIES, get_settings
from tracker.connectors import ADAPTER_REGISTRY, BaseAdapter
from tracker.connectors.recipes.outcome import SourceOutcome, run_status_for
from tracker.db.models import Job, PostingInventory, ScrapeRun, ScrapeSourceRun
from tracker.health import REFRESHED_STATUSES
from tracker.platform.locks import advisory_lock_held
from tracker.schema import RawJob
from tracker.workflows import pipeline, post_passes, run_persistence

pytestmark = pytest.mark.asyncio


def posting(company: str, req_id: str) -> RawJob:
    return RawJob(
        company=company, req_id=req_id,
        title="Staff Product Manager" if company == "apple" else "Principal Product Manager",
        url=f"https://careers.example.test/{company}/{req_id}",
        locations=["San Francisco, CA, USA"],
        description_html="<p>Build distributed systems and mentor senior engineers.</p>",
    )


class Board:
    """This run's listings, and what the run did with the things it opened."""

    def __init__(self) -> None:
        self.plans: dict[str, tuple[list[str], str]] = {}
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.hanging = asyncio.Event()
        # "gated" plans wait here before listing anything (`waiting` says so).
        self.waiting = asyncio.Event()
        self.gate = asyncio.Event()
        self.heartbeats: list[asyncio.Task] = []
        self.resolvers: list = []
        # Per req_id: `RawJob` fields this run's listing states instead.
        self.facts: dict[str, dict] = {}


@pytest.fixture
def board(scratch_scope, monkeypatch):
    state = Board()

    class Listing(BaseAdapter):
        async def __aenter__(self):
            state.opened.append(self.company)
            return await super().__aenter__()

        async def __aexit__(self, *exc):
            state.closed.append(self.company)
            await super().__aexit__(*exc)

        async def fetch(self):
            keys, behaviour = state.plans[self.company]
            if behaviour.startswith("gated"):
                state.waiting.set()
                await state.gate.wait()
                behaviour = behaviour.removeprefix("gated-")
            for key in keys:
                raw = posting(self.company, key)
                for name, value in state.facts.get(key, {}).items():
                    setattr(raw, name, value)
                yield raw
            if behaviour == "incomplete":
                self.drift.invalidate_listing("next page omitted its jobs array")
            elif behaviour == "error":
                raise RuntimeError("source disconnected after its first page")
            elif behaviour == "hang":
                state.hanging.set()
                await asyncio.Event().wait()
            elif behaviour == "slow":
                await asyncio.sleep(1.5)

    class Compensation:
        def __init__(self, *_providers) -> None:
            self.closed = False
            state.resolvers.append(self)

        async def resolve(self, _context):
            return None, []

        def reset(self, _providers, *, fingerprint):
            """The run points its resolver at the reference set it collects under."""
            self.fingerprint = fingerprint

        async def aclose(self):
            self.closed = True

    real_heartbeat = pipeline._heartbeat_task

    def heartbeat(*args, **kwargs):
        task = real_heartbeat(*args, **kwargs)
        state.heartbeats.append(task)
        return task

    monkeypatch.setattr(pipeline, "CompResolver", Compensation)
    monkeypatch.setattr(pipeline, "_heartbeat_task", heartbeat)
    monkeypatch.setattr(post_passes, "POST_PASSES", tuple(
        p for p in post_passes.POST_PASSES if p.name == "search_vectors"
    ))
    for adapter in ADAPTER_REGISTRY:
        monkeypatch.setitem(ADAPTER_REGISTRY, adapter, Listing)
    network = AsyncMock(side_effect=AssertionError("pipeline test attempted external HTTP"))
    monkeypatch.setattr(httpx.AsyncClient, "send", network)
    yield state
    network.assert_not_awaited()


async def _run_lock_is_free(db_session) -> bool:
    """Read from `pg_locks`, never by taking the lock: the lock is re-entrant,
    so a probe that drew the pooled connection still holding it would get it
    and call a leaked lock free."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as probe:
        return not await advisory_lock_held(probe, get_settings().advisory_lock_key)


def _pending_collectors() -> list[str]:
    return sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name().startswith("collect:") and not task.done()
    )


async def _exploding_rollup(ctx) -> None:
    # A statement first, so the loop's rollback has a transaction to discard —
    # without one the failure path is not the one production takes.
    await ctx.session.execute(text("SELECT 1"))
    raise RuntimeError("demand rollup exploded")


# --------------------------------------------------------------------------- #
# 1-2. Cleanup
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ending", ["ok", "source_error", "fatal_post_pass"])
async def test_a_finished_run_releases_everything_it_took(db_session, board, monkeypatch, ending):
    board.plans["apple"] = (["one"], "error" if ending == "source_error" else "complete")
    if ending == "fatal_post_pass":
        monkeypatch.setattr(
            post_passes, "POST_PASSES",
            (post_passes.PostPass("demand_metrics", _exploding_rollup, fatal=True),),
        )
        with pytest.raises(RuntimeError, match="demand rollup exploded"):
            await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    else:
        await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    assert await _run_lock_is_free(db_session), "the run lock outlived its run"
    assert len(board.heartbeats) == 1 and board.heartbeats[0].done()
    assert board.opened == board.closed == ["apple"]
    assert board.resolvers and all(resolver.closed for resolver in board.resolvers)
    assert _pending_collectors() == []

    run = (await db_session.scalars(select(ScrapeRun))).one()
    assert run.finished_at is not None
    # The status is a projection of the recorded outcome, never a second verdict
    # — and that holds for EVERY ending, including a fatal post-pass.
    outcome = SourceOutcome(run.per_source["apple"]["outcome"])
    assert run.status == run_status_for([outcome])
    if ending == "fatal_post_pass":
        assert "demand rollup exploded" in run.notes
    else:
        assert (outcome is SourceOutcome.OK) is (ending == "ok")


async def test_a_cancelled_run_releases_its_lock_and_heartbeat_and_writes_no_terminal_status(
    db_session, board
):
    """Cancellation reaches the collection the run was awaiting.

    Cancelling only the run's `asyncio.wait` leaves the `collect:<backend>`
    task running with its adapter open, so a hung source stays open for as
    long as a long-lived caller lives. Asserted the moment the cancellation
    surfaces, with nothing cancelled on the run's behalf, because a collector
    still unwinding after that point is the defect.
    """
    board.plans["apple"] = (["one"], "hang")
    run_task = asyncio.create_task(pipeline.run_pipeline(companies=["apple"], hydrate=False))
    await asyncio.wait_for(board.hanging.wait(), timeout=20)

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert _pending_collectors() == [], "a cancelled run left its collection running"
    assert board.opened == board.closed == ["apple"], "a cancelled run left its adapter open"
    assert await _run_lock_is_free(db_session), "a cancelled run kept the run lock"
    assert len(board.heartbeats) == 1 and board.heartbeats[0].done()
    assert board.resolvers and all(resolver.closed for resolver in board.resolvers)
    row = (await db_session.scalars(select(ScrapeRun))).one()
    assert row.status == "running" and row.finished_at is None
    # The marker left behind is what `POST /api/sync/cancel` reads: it ends a
    # running run only when the run names the process group it signalled.
    assert row.process_group == os.getpgrp(), "the running marker does not name its process group"


# --------------------------------------------------------------------------- #
# 3. Per-source commits
# --------------------------------------------------------------------------- #


async def test_a_fatal_post_pass_keeps_every_persisted_source_and_records_it(
    db_session, board, monkeypatch
):
    board.plans["apple"] = (["one"], "complete")
    board.plans["amazon"] = (["one"], "complete")
    monkeypatch.setattr(
        post_passes, "POST_PASSES",
        (post_passes.PostPass("demand_metrics", _exploding_rollup, fatal=True),),
    )

    with pytest.raises(RuntimeError, match="demand rollup exploded"):
        await pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False)

    jobs = (await db_session.scalars(select(Job))).all()
    assert {(job.company, job.req_id) for job in jobs} == {("apple", "one"), ("amazon", "one")}
    source_runs = (await db_session.scalars(select(ScrapeSourceRun))).all()
    assert sorted(row.company_slug for row in source_runs) == ["amazon", "apple"]

    run = (await db_session.scalars(select(ScrapeRun))).one()
    assert set(run.per_source) == {"apple", "amazon"}
    assert {stats["outcome"] for stats in run.per_source.values()} == {"ok"}
    # The status is the projection of THOSE outcomes, not a verdict on the pass.
    # Both sources delivered, so the run refreshed the data and says
    # so. `error` here would mean two things at once: `run_status_for` defines
    # it as "no source produced usable data" and `health.REFRESHED_STATUSES`
    # excludes it on that reading, so this run would freeze `last_success_at`
    # and have the watchdog retry it hourly.
    assert run.status == "ok"
    assert run.status in REFRESHED_STATUSES, "a run that collected cleanly must count as a refresh"
    # The exception is not lost by that — it is recorded where it happened.
    assert "demand rollup exploded" in run.notes
    assert run.jobs_new == 2


# --------------------------------------------------------------------------- #
# 4. Audit dict shapes
# --------------------------------------------------------------------------- #

#: Every key a recorded source carries, with the JSON types it is stored as.
SOURCE_STATS_TYPES: dict[str, tuple[type, ...]] = {
    # set before the scan
    "scanned": (int,), "kept": (int,), "new": (int,), "closed": (int,),
    "errors": (list,), "capped": (bool,), "bounded": (bool,), "truncated": (bool,),
    "blocked": (bool,), "suspended": (bool,), "suspended_seconds": (int, float),
    "unattempted": (bool,), "uncovered_locations": (list,), "detail_deferred": (int,),
    # set when the scan ends
    "duration_seconds": (int, float), "records_dropped": (int,),
    "listing_invalidated": (bool,), "empty_proven": (bool,), "board_missing": (bool,),
    "queries": (list,),
    # what the reads cost; None where no read reached a shared transport
    "requests": (int, type(None)), "retries": (int, type(None)), "bytes_received": (int, type(None)),
    "retry_after_until": (str, type(None)),
    # set while persisting
    "closure_scope": (str,), "closure_eligible": (bool,), "drift": (list,),
    "list_complete": (bool,), "outcome": (str,),
    # absence evidence, zero where the listing is not evidence
    "absence_open": (int,), "absence_missed": (int,), "absence_missing_share": (float,),
    "absence_second_miss": (int,), "closure_one_miss": (int,),
    # every posting read, kept in the inventory
    "inventory_rows": (int,), "inventory_gone": (int,),
    # a fresh binding withholds closure, so its first reconcile records why,
    # and whether it granted it: the scheduler reads the flag
    "binding_activation": (str,), "binding_activated": (bool,),
}
POLICY_KEYS: dict[str, tuple[type, ...]] = {"policy_reason": (str,), "policy_provider": (str,)}
SUMMARY_KEYS = {"run_id", "status", "seen", "new", "closed", "demand_slices", "per_source", "scan_mode"}


@pytest.mark.parametrize(
    ("company", "plan", "max_list", "outcome", "extra", "denied"),
    [
        ("apple", (["one", "two"], "complete"), None, "ok", {}, False),
        ("apple", (["one", "two"], "complete"), 1, "capped", {}, False),
        # A board that finishes under its cap is recorded `capped` too:
        # the outcome differs; the stored keys and their types do not.
        ("apple", (["one", "two"], "complete"), 10, "capped", {}, False),
        ("apple", (["one"], "incomplete"), None, "degraded", {}, False),
        ("apple", (["one"], "error"), None, "degraded", {}, False),
        # A denied provider is never attempted. The denial is applied here rather
        # than borrowed from the shipped policy, which denies no company, and
        # this audit shape has to hold for whichever provider is denied next.
        ("apple", ([], "complete"), None, "unattempted", POLICY_KEYS, True),
    ],
    ids=["ok", "capped", "capped_below_cap", "incomplete", "error", "policy_denied"],
)
async def test_a_recorded_source_keeps_its_audit_shape(
    db_session, board, monkeypatch, company, plan, max_list, outcome, extra, denied
):
    if denied:
        monkeypatch.setattr(
            get_settings(),
            "sync_policy_denied_providers",
            frozenset({COMPANIES[company]["adapter"]}),
        )
    board.plans[company] = plan

    summary = await pipeline.run_pipeline(companies=[company], hydrate=False, max_list=max_list)

    assert set(summary) == SUMMARY_KEYS
    run = (await db_session.scalars(select(ScrapeRun))).one()
    stored = run.per_source[company]
    expected = SOURCE_STATS_TYPES | extra
    assert set(stored) == set(expected), (sorted(set(stored) - set(expected)), sorted(set(expected) - set(stored)))
    wrong = {key: type(value).__name__ for key, value in stored.items() if type(value) not in expected[key]}
    assert wrong == {}, wrong
    assert stored["outcome"] == outcome
    assert set(summary["per_source"][company]) == set(stored)

    source_run = (await db_session.scalars(select(ScrapeSourceRun))).one()
    assert source_run.stats == stored
    assert run.drift_alerts == stored["drift"] == source_run.drift


# --------------------------------------------------------------------------- #
# 5. Streaming persistence
# --------------------------------------------------------------------------- #


async def _poll(db_session, query, *, until, timeout: float = 10.0):
    """Read through a fresh session until `until(result)` holds: what another
    reader (the Board) would see, committed or not at all."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        async with factory() as reader:
            result = (await reader.scalars(query)).all()
        if until(result) or asyncio.get_running_loop().time() > deadline:
            return result
        await asyncio.sleep(0.05)


async def test_a_posting_is_committed_while_its_board_is_still_being_read(db_session, board):
    """The Board shows a posting seconds after its page is read, not when the
    company or the run ends; closure still waits for the whole listing."""
    board.plans["apple"] = (["one", "two"], "hang")
    run_task = asyncio.create_task(pipeline.run_pipeline(companies=["apple"], hydrate=False))
    try:
        await asyncio.wait_for(board.hanging.wait(), timeout=20)
        jobs = await _poll(
            db_session, select(Job).where(Job.company == "apple"), until=lambda rows: len(rows) == 2
        )
        assert sorted(job.req_id for job in jobs) == ["one", "two"], "rows wait for the run to end"
        assert all(job.status == "open" for job in jobs)
        recorded = await _poll(db_session, select(ScrapeSourceRun), until=lambda rows: bool(rows), timeout=0.5)
        assert recorded == [], "a company still being read has no outcome yet"
    finally:
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
    assert board.opened == board.closed == ["apple"]
    assert await _run_lock_is_free(db_session)


async def test_a_finished_company_is_recorded_while_another_is_still_read(db_session, board):
    board.plans["amazon"] = (["a1"], "complete")
    board.plans["apple"] = (["one"], "hang")
    run_task = asyncio.create_task(
        pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False)
    )
    try:
        await asyncio.wait_for(board.hanging.wait(), timeout=20)
        recorded = await _poll(
            db_session, select(ScrapeSourceRun), until=lambda rows: len(rows) == 1
        )
        assert [row.company_slug for row in recorded] == ["amazon"]
        assert recorded[0].outcome == "ok"
        from tracker.db.queries.runs import committed_per_source

        (run,) = await _poll(db_session, select(ScrapeRun), until=lambda rows: bool(rows))
        assert (run.status, run.per_source) == ("running", {}), "per_source is written once, at the end"
        assert set(await committed_per_source(db_session, run.id)) == {"amazon"}
    finally:
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task


async def test_a_writer_failure_stops_the_collection_and_fails_the_run(db_session, board, monkeypatch):
    board.plans["apple"] = (["one"], "hang")

    async def broken(*_args, **_kwargs):
        raise RuntimeError("jobs table unwritable")

    monkeypatch.setattr(pipeline, "persist_rows", broken)
    with pytest.raises(RuntimeError, match="jobs table unwritable"):
        await asyncio.wait_for(
            pipeline.run_pipeline(companies=["apple"], hydrate=False), timeout=20
        )

    assert board.opened == board.closed == ["apple"], "the collection outlived its writer"
    assert _pending_collectors() == []
    assert await _run_lock_is_free(db_session)
    run = (await db_session.scalars(select(ScrapeRun))).one()
    assert run.status == "error" and "jobs table unwritable" in run.notes


async def test_a_company_queued_behind_a_hung_one_is_read_in_the_same_run(
    db_session, board, monkeypatch
):
    """One lane at a time, and its first company hangs: the hung company is
    bounded by its own budget and the one behind it is read. Nothing waits for
    a later run, and nothing is deferred for a bound we chose."""
    settings = get_settings()
    monkeypatch.setattr(settings, "scraper_max_concurrent_sources", 1)
    monkeypatch.setattr(settings, "scraper_source_budget_seconds", 1)
    board.plans["apple"] = (["one"], "hang")
    board.plans["amazon"] = (["a1"], "complete")

    await asyncio.wait_for(
        pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False), timeout=30
    )

    run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert run.per_source["amazon"]["outcome"] == "ok"
    assert run.per_source["apple"]["outcome"] == "failed", "the hung site is its own failure"
    assert not any(entry.get("deferred_reason") for entry in run.per_source.values())


async def test_a_lane_longer_than_any_one_company_bound_is_read_to_its_end(
    db_session, board, monkeypatch
):
    """A lane's companies drain one after another, so a lane can take far longer
    than any one company may. Two companies of 1.5 s each on one lane with a
    2 s company budget: the lane takes 3 s and both are read."""
    settings = get_settings()
    monkeypatch.setattr(settings, "scraper_max_concurrent_sources", 1)
    monkeypatch.setattr(settings, "scraper_source_budget_seconds", 2)
    board.plans["apple"] = (["one"], "slow")
    board.plans["amazon"] = (["a1"], "slow")

    await asyncio.wait_for(
        pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False), timeout=30
    )

    run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert {company: entry["outcome"] for company, entry in run.per_source.items()} == {
        "apple": "ok", "amazon": "ok",
    }
    assert "timeout" not in (run.notes or "")


async def test_a_long_run_makes_what_it_has_read_searchable_before_it_ends(db_session, board, monkeypatch):
    """Search comes from a post-pass. A long run refreshes it between
    companies, so a company read early is searchable while a later one is
    still being read, not only once the whole run ends."""
    settings = get_settings()
    monkeypatch.setattr(settings, "scraper_max_concurrent_sources", 1)
    monkeypatch.setattr(settings, "scan_refresh_minutes", 0)
    board.plans["apple"] = (["one", "two"], "complete")
    board.plans["amazon"] = (["a1"], "hang")
    run_task = asyncio.create_task(pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False))
    try:
        await asyncio.wait_for(board.hanging.wait(), timeout=20)
        vectors = await _poll(
            db_session, select(Job.search_vector).where(Job.company == "apple"),
            until=lambda rows: len(rows) == 2 and all(vector is not None for vector in rows),
        )
        assert len(vectors) == 2 and all(vector is not None for vector in vectors)
        assert not board.closed.count("amazon"), "the run is still reading amazon"
    finally:
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task


async def test_a_company_asked_for_during_a_run_is_read_next(db_session, board, monkeypatch):
    """Scan now while a scan reads: the asked company is read next, before the
    company the run planned and has not started, and not after the run."""
    from tracker.workflows import scheduler

    settings = get_settings()
    monkeypatch.setattr(settings, "scraper_max_concurrent_sources", 1)
    monkeypatch.setattr(pipeline, "_ASKED_EVERY_SECONDS", 0.05)
    asked = "anthropic"
    board.plans["apple"] = (["one"], "complete")
    board.plans["amazon"] = (["a1"], "complete")
    board.plans[asked] = (["s1"], "complete")
    await pipeline.run_pipeline(companies=["apple", "amazon", asked], hydrate=False)  # seeds bindings
    async with pipeline.session_scope() as session:
        await scheduler.queue_manual_reconciliation(session, [])  # seeds schedule rows
    board.opened.clear()
    board.plans["apple"] = (["one"], "gated-complete")

    run_task = asyncio.create_task(
        pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False, join_requests=True)
    )
    try:
        await asyncio.wait_for(board.waiting.wait(), timeout=20)
        async with pipeline.session_scope() as session:
            assert await scheduler.queue_manual_reconciliation(session, [asked]) == [asked]
        deadline = asyncio.get_running_loop().time() + 10
        while "collect:greenhouse" not in {task.get_name() for task in asyncio.all_tasks()}:
            assert asyncio.get_running_loop().time() < deadline, "the run never took the request"
            await asyncio.sleep(0.02)
        board.gate.set()
        await asyncio.wait_for(run_task, timeout=30)
    finally:
        board.gate.set()
        if not run_task.done():
            run_task.cancel()

    assert board.opened == ["apple", asked, "amazon"]
    run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert run.per_source[asked]["outcome"] == "ok"


async def test_a_stopped_manual_sync_keeps_the_schedule_of_every_company_it_finished(
    db_session, board, monkeypatch
):
    """A manual sync is one drain; each company's next deadlines are
    written in the commit that finishes it, so stopping the drain keeps what it
    finished. Written after the whole run, a stopped drain would redo everything."""
    from tracker.db.models import SourceBinding, SyncScheduleState
    from tracker.workflows import scheduler

    board.plans["amazon"] = (["a1"], "complete")
    board.plans["apple"] = (["one"], "hang")
    async with pipeline.session_scope() as session:
        queued = await scheduler.queue_manual_reconciliation(session, ["apple", "amazon"])
    assert queued == ["amazon", "apple"]

    task = asyncio.create_task(scheduler.run_once())
    try:
        await asyncio.wait_for(board.hanging.wait(), timeout=20)
        query = (
            select(SyncScheduleState)
            .join(SourceBinding, SourceBinding.id == SyncScheduleState.binding_id)
            .where(SourceBinding.company_slug == "amazon")
        )
        rows = await _poll(db_session, query, until=lambda rs: rs and rs[0].last_outcome == "ok")
        assert rows[0].last_outcome == "ok" and rows[0].manual_requested_at is None
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    apple = (
        await db_session.scalars(
            select(SyncScheduleState)
            .join(SourceBinding, SourceBinding.id == SyncScheduleState.binding_id)
            .where(SourceBinding.company_slug == "apple")
        )
    ).one()
    await db_session.refresh(apple)
    assert apple.manual_requested_at is not None, "the company it never finished stays queued"


async def test_the_tick_after_a_stopped_scan_closes_what_it_left_open(db_session, board):
    """A scan whose process ends before it does leaves its run `running` and
    its plan run without a finish (claim 2: a cancel leaves exactly that). The
    run reads as live until its heartbeat goes silent, and the plan waits for
    it as one in progress. The next tick holds the run lock, so no scan
    is live: it closes the run as a stopped one, keeping the companies it
    committed, and finishes the plan run as interrupted, which a full read
    continues and any other run retries after `FAILED_RETRY`."""
    from tracker.db.models import SchedulePlanRun
    from tracker.workflows import scheduler

    board.plans["amazon"] = (["a1"], "complete")
    board.plans["apple"] = (["one"], "hang")
    async with pipeline.session_scope() as session:
        await scheduler.queue_manual_reconciliation(session, ["apple", "amazon"])
    stopped = asyncio.create_task(scheduler.run_once())
    try:
        await asyncio.wait_for(board.hanging.wait(), timeout=20)
        await _poll(db_session, select(ScrapeSourceRun.company_slug), until=lambda slugs: "amazon" in slugs)
    finally:
        stopped.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopped
    left = (await db_session.scalars(select(ScrapeRun))).one()
    plan = (await db_session.scalars(select(SchedulePlanRun))).one()
    assert (left.status, plan.finished_at) == ("running", None), "the control: nothing closed them"

    board.plans["apple"] = (["one"], "complete")
    await scheduler.run_once()

    await db_session.refresh(left)
    await db_session.refresh(plan)
    assert (left.status, left.scope) == ("partial", "targeted"), left.notes
    assert left.finished_at is not None and "amazon" in left.per_source and "apple" not in left.per_source
    assert (plan.outcome, plan.finished_at is not None) == ("interrupted", True)


async def test_a_tick_beside_a_live_scan_closes_nothing(db_session, board):
    """The negative control: a run holds the run lock for its whole life, so a
    tick that cannot take it leaves that run's row as it is."""
    from tracker.workflows import scheduler

    board.plans["apple"] = (["one"], "hang")
    live = asyncio.create_task(pipeline.run_pipeline(companies=["apple"], hydrate=False))
    try:
        await asyncio.wait_for(board.hanging.wait(), timeout=20)
        await scheduler.close_runs_left_open(datetime.now(UTC))
        run = (await db_session.scalars(select(ScrapeRun))).one()
        await db_session.refresh(run)
        assert (run.status, run.finished_at) == ("running", None)
    finally:
        live.cancel()
        with pytest.raises(asyncio.CancelledError):
            await live


async def test_a_run_that_crashes_holds_no_job_site_back(db_session, board, monkeypatch):
    """An exception out of the run is the run's own: a job site's answer is
    each company's outcome, recorded inside the run. The companies it never
    finished are due again after the usual retry delay, and no provider takes
    a pressure event or a cooldown from the crash."""
    from datetime import timedelta

    from tracker.db.models import ProviderPressureState, SourceBinding, SyncScheduleState
    from tracker.workflows import scheduler

    async def crashed(*_args, **_kwargs):
        raise RuntimeError("the writer lost its session")

    board.plans["amazon"] = (["a1"], "complete")
    board.plans["apple"] = (["one"], "complete")
    monkeypatch.setattr(pipeline, "finalize_source", crashed)
    async with pipeline.session_scope() as session:
        await scheduler.queue_manual_reconciliation(session, ["apple", "amazon"])
    started = datetime.now(UTC)
    with pytest.raises(RuntimeError, match="lost its session"):
        await scheduler.run_once()
    finished = datetime.now(UTC)

    providers = (
        await db_session.scalars(
            select(ProviderPressureState).where(ProviderPressureState.pressure_key.in_(["apple", "amazon"]))
        )
    ).all()
    for provider in providers:
        await db_session.refresh(provider)
    assert {p.pressure_key: (p.state, p.cooldown_until, p.consecutive_pressure_events) for p in providers} == {
        "apple": (scheduler.READY, None, 0), "amazon": (scheduler.READY, None, 0),
    }
    schedules = (
        await db_session.scalars(
            select(SyncScheduleState)
            .join(SourceBinding, SourceBinding.id == SyncScheduleState.binding_id)
            .where(SourceBinding.company_slug.in_(["apple", "amazon"]))
        )
    ).all()
    retry = timedelta(seconds=get_settings().sync_provider_backoff_seconds)
    assert len(schedules) == 2
    for schedule in schedules:
        await db_session.refresh(schedule)
        assert started + retry <= schedule.next_reconcile_at <= finished + retry


# --------------------------------------------------------------------------- #
# 6. The posting inventory
# --------------------------------------------------------------------------- #


async def test_a_sync_keeps_every_posting_it_read_and_a_complete_listing_marks_the_rest_gone(db_session, board):
    board.plans["apple"] = (["one", "two"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    board.plans["apple"] = (["one"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    rows = {r.req_id: r for r in (await db_session.scalars(select(PostingInventory))).all()}
    assert set(rows) == {"one", "two"}
    assert rows["one"].gone_at is None and rows["two"].gone_at is not None
    last = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert last.per_source["apple"]["inventory_gone"] == 1


async def test_a_failed_inventory_write_costs_the_source_nothing_else(db_session, board, monkeypatch):
    """I6: the write runs in a savepoint; the source's jobs, closure, health and
    source-run row commit, and the stored record says what failed."""

    async def failing(session, **kwargs):
        await session.execute(text("SELECT 1/0"))

    monkeypatch.setattr(run_persistence, "write_inventory", failing)
    board.plans["apple"] = (["one", "two"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    run = (await db_session.scalars(select(ScrapeRun))).one()
    stored = run.per_source["apple"]
    assert stored["outcome"] == "ok"
    assert "DivisionByZero" in stored["inventory_error"] or "division by zero" in stored["inventory_error"]
    assert "inventory_rows" not in stored
    assert sorted(j.req_id for j in (await db_session.scalars(select(Job))).all()) == ["one", "two"]
    assert (await db_session.scalars(select(ScrapeSourceRun))).one().stats == stored
    assert (await db_session.scalars(select(PostingInventory))).all() == []


# --------------------------------------------------------------------------- #
# A scope saved while a scan runs
# --------------------------------------------------------------------------- #


async def _scope_bands(db_session, bands: list[str]) -> None:
    """Save the seniority axis as `PUT /api/settings` does: write it, then
    re-project every stored row, in one transaction."""
    from tracker.scope.projection import recompute_saved_scope
    from tracker.settings_store import set_enabled_bands

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as save:
        await set_enabled_bands(save, bands)
        await recompute_saved_scope(save)
        await save.commit()


async def _in_scope(db_session) -> dict[str, bool]:
    rows = await _poll(db_session, select(Job).where(Job.company == "apple"), until=lambda rows: True)
    return {job.req_id: job.in_scope for job in rows}


@pytest.mark.parametrize("ending", ["complete", "streamed"])
async def test_a_scope_saved_during_a_scan_is_the_scope_its_rows_are_stored_under(db_session, board, ending):
    """The run loads the scope once. A narrower save during it re-projects the
    stored rows; a scan that then writes the rows it read as in scope under the
    scope it started with puts a new row on the Board, and flips a held row
    loaded after the save back to in scope. Nothing later repairs either."""
    await _scope_bands(db_session, ["staff"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert await _in_scope(db_session) == {"held": True}, "the control: Staff is in scope"

    board.plans["apple"] = (["held", "new"], "gated-hang" if ending == "streamed" else "gated-complete")
    run_task = asyncio.create_task(pipeline.run_pipeline(companies=["apple"], hydrate=False))
    try:
        await asyncio.wait_for(board.waiting.wait(), timeout=20)
        await _scope_bands(db_session, ["principal"])
        assert await _in_scope(db_session) == {"held": False}, "the save re-projects at once"
        board.gate.set()
        if ending == "streamed":
            await asyncio.wait_for(board.hanging.wait(), timeout=20)
            await _poll(db_session, select(Job).where(Job.company == "apple"), until=lambda rows: len(rows) == 2)
        else:
            await asyncio.wait_for(run_task, timeout=60)
        assert await _in_scope(db_session) == {"held": False, "new": False}
    finally:
        if not run_task.done():
            run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run_task


async def test_a_company_whose_rows_were_reprojected_before_it_finished_still_finishes(db_session, board):
    """The writer commits whenever the stream pauses, and each commit
    re-projects the rows it wrote onto the scope saved now. The run keeps
    those rows to finish the company with; a re-projection that changed them
    must leave them readable without a database round trip, which an async
    session cannot make from a plain attribute read."""
    await _scope_bands(db_session, ["staff"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    board.plans["apple"] = (["held", "new"], "gated-slow")
    run_task = asyncio.create_task(pipeline.run_pipeline(companies=["apple"], hydrate=False))
    try:
        await asyncio.wait_for(board.waiting.wait(), timeout=20)
        await _scope_bands(db_session, ["principal"])
        board.gate.set()
        await asyncio.wait_for(run_task, timeout=60)
    finally:
        if not run_task.done():
            run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run_task

    run = (await db_session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()))).first()
    assert run.per_source["apple"]["outcome"] == "ok", run.notes
    assert await _in_scope(db_session) == {"held": False, "new": False}


async def test_a_reprojected_row_the_session_holds_reads_its_new_flag_in_place(db_session, board):
    """The contract the case above rests on, without a run around it: neither
    expired (a read would need a load) nor left on the flag it had before."""
    from tracker.scope.projection import recompute_saved_scope
    from tracker.settings_store import set_enabled_bands

    await _scope_bands(db_session, ["staff"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as writer:
        held = (await writer.scalars(select(Job).where(Job.req_id == "held"))).one()
        assert held.in_scope is True, "the control: Staff is in scope"
        await set_enabled_bands(writer, ["principal"])
        assert await recompute_saved_scope(writer, job_ids=[held.id]) == 1
        assert held.in_scope is False
        await writer.commit()
    assert await _in_scope(db_session) == {"held": False}


async def test_a_long_lived_session_reads_the_scope_saved_since_it_last_looked(db_session):
    """`settings_store` reads through `session.get`, which answers from the
    session's identity map. The run's session keeps what it loaded across its
    commits; while anything holds the setting row, it would re-project with the
    scope it started with. `saved_scope` asks the database each time."""
    from tracker.db.models import AppSetting
    from tracker.scope.projection import saved_scope
    from tracker.settings_store import ENABLED_BANDS_KEY, set_enabled_bands

    await _scope_bands(db_session, ["staff"])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as run_session:
        held = await run_session.get(AppSetting, ENABLED_BANDS_KEY)  # a reference the run keeps
        await run_session.commit()
        async with factory() as save:
            await set_enabled_bands(save, ["principal"])
            await save.commit()
        (_roles, bands, *_rest), _keywords = await saved_scope(run_session)
        assert set(bands) == {"principal"} and held is not None


async def test_a_save_waits_for_the_writer_transaction_that_holds_the_scope(db_session):
    """The order the race above depends on, made deterministic: from its first
    row write to its commit the run's writer holds the scope lock, so a save's
    re-projection runs after that commit and sees the rows it wrote."""
    from tracker.db.repo import hold_scope_projection

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as writer:
        await hold_scope_projection(writer)
        save = asyncio.create_task(_scope_bands(db_session, ["principal"]))
        await until_waiting(db_session.bind, save)
        assert not save.done(), "the save re-projected under a writer's open transaction"
        await writer.commit()
        await asyncio.wait_for(save, timeout=10)


# --------------------------------------------------------------------------- #
# A held posting the scan rejects keeps what the scan read
# --------------------------------------------------------------------------- #


async def _scope(db_session, *, locations: list[str]) -> None:
    """Save the place axis as a settings save does: write, then re-project."""
    from tracker.scope.projection import recompute_saved_scope
    from tracker.settings_store import set_enabled_bands, set_enabled_locations

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as save:
        await set_enabled_bands(save, ["staff"])
        await set_enabled_locations(save, locations)
        await recompute_saved_scope(save)
        await save.commit()


async def _held(db_session) -> Job:
    rows = await _poll(db_session, select(Job).where(Job.company == "apple"), until=lambda rows: True)
    return {job.req_id: job for job in rows}["held"]


@pytest.mark.parametrize("inventory", [True, False])
async def test_a_held_posting_moved_out_of_scope_stays_out(db_session, board, monkeypatch, inventory):
    """The scan reads the posting at a place the scope excludes and does not
    write it. A writer that re-projects the row from the place it was stored
    with would bring the posting back in at a city it has left."""
    monkeypatch.setattr(get_settings(), "inventory_enabled", inventory)
    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert (await _held(db_session)).in_scope is True, "the control: San Francisco is in scope"

    board.facts["held"] = {"locations": ["London, United Kingdom"]}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    held = await _held(db_session)
    assert held.in_scope is False
    assert held.locations == ["London, United Kingdom"]
    assert "uk" in held.location_groups and "united_states" not in held.location_groups

    # Any later re-projection (a save, a backfill pass) reads the stored row.
    await _scope(db_session, locations=["united_states"])
    assert (await _held(db_session)).in_scope is False
    await _scope(db_session, locations=["united_states", "uk"])
    assert (await _held(db_session)).in_scope is True, "the row now carries the place the board names"


async def test_a_scope_widened_during_the_scan_admits_the_moved_posting(db_session, board):
    """The scan decides with the scope it loaded; the writer re-projects with
    the one saved now. Widened mid-scan to the posting's new place, the
    posting is in, judged by that place."""
    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    board.facts["held"] = {"locations": ["London, United Kingdom"]}
    board.plans["apple"] = (["held"], "gated-complete")
    run_task = asyncio.create_task(pipeline.run_pipeline(companies=["apple"], hydrate=False))
    await asyncio.wait_for(board.waiting.wait(), timeout=20)
    await _scope(db_session, locations=["uk"])
    board.gate.set()
    await asyncio.wait_for(run_task, timeout=60)
    held = await _held(db_session)
    assert (held.in_scope, held.locations) == (True, ["London, United Kingdom"])


async def test_a_retitled_held_posting_is_judged_by_its_new_title(db_session, board):
    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    board.facts["held"] = {"title": "Staff Software Engineer"}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    held = await _held(db_session)
    assert (held.in_scope, held.title, held.family) == (False, "Staff Software Engineer", "software_engineering")
    # A touched row: the run's post-passes re-read the new title.
    vector = await db_session.scalar(select(text("search_vector::text")).select_from(Job).where(Job.id == held.id))
    assert "softwar" in vector
    await _scope(db_session, locations=["united_states"])
    assert (await _held(db_session)).in_scope is False


@pytest.mark.parametrize("kind", ["team", "department"])
async def test_a_held_posting_moved_to_an_excluded_team_stays_out(db_session, board, kind):
    """A learned rule excludes one team. The board moves the posting into it,
    so the scan rejects it and does not write it; a row still carrying its
    old team would be admitted again by the next re-projection."""
    from tracker.db.models import CompanyScopeRule

    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held"], "complete")
    board.facts["held"] = {kind: "Design"}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert (await _held(db_session)).in_scope is True, "the control: Design is not excluded"

    db_session.add(CompanyScopeRule(company="apple", kind=kind, value="Retail Operations"))
    await db_session.commit()
    board.facts["held"] = {kind: "Retail Operations"}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    held = await _held(db_session)
    assert (held.in_scope, getattr(held, kind)) == (False, "Retail Operations")
    await _scope(db_session, locations=["united_states"])
    assert (await _held(db_session)).in_scope is False


async def test_a_listing_that_names_no_team_withdraws_none(db_session, board):
    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held"], "complete")
    board.facts["held"] = {"team": "Design"}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    board.facts["held"] = {"team": None, "locations": ["London, United Kingdom"]}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    assert (await _held(db_session)).team == "Design"


@pytest.mark.parametrize("listed", [[], ["Multiple Locations"], ["62 Locations"]])
async def test_a_listing_that_names_no_place_withdraws_none(db_session, board, listed):
    """Not read is not withdrawn: a listing row with no place, or a card that
    only counts its places (Deloitte's "Multiple Locations", PwC's "62
    Locations"), says nothing about where the
    posting is, so the cities read from its page stand."""
    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held"], "complete")
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    board.facts["held"] = {"locations": listed}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    held = await _held(db_session)
    assert held.locations == ["San Francisco, CA, USA"]
    assert held.in_scope is True


async def test_a_rejected_posting_never_held_is_not_written(db_session, board):
    await _scope(db_session, locations=["united_states"])
    board.plans["apple"] = (["held", "elsewhere"], "complete")
    board.facts["elsewhere"] = {"locations": ["London, United Kingdom"]}
    await pipeline.run_pipeline(companies=["apple"], hydrate=False)
    rows = await _poll(db_session, select(Job).where(Job.company == "apple"), until=lambda rows: True)
    assert sorted(job.req_id for job in rows) == ["held"]


async def test_a_run_re_estimates_stored_jobs_before_it_collects(db_session, board):
    """A stored estimate under another reference set is moved before collection:
    the run's postings and the stored ones then share one
    fingerprint, and the move is one `reference_change`, not per-job events."""
    from tracker.db.models import Job, ReferenceChange, ReferenceState

    db_session.add(Job(company="google", req_id="old", dedupe_key="google:old", title="Staff Software Engineer",
                       url="https://example.com/old", level_band="staff", family=None, status="closed",
                       location_groups=["silicon_valley"], comp_median=1, comp_ref_fp="stale"))
    await db_session.commit()
    board.plans["apple"] = (["one"], "complete")

    await pipeline.run_pipeline(companies=["apple"], hydrate=False)

    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    old = (await db_session.scalars(select(Job).where(Job.dedupe_key == "google:old"))).one()
    await db_session.refresh(old)
    assert state is not None and state.applied_fp is not None
    assert old.comp_ref_fp == state.applied_fp and old.comp_median == 644_000  # the atlas seed, Staff
    assert board.resolvers[-1].fingerprint == state.applied_fp
    assert len((await db_session.scalars(select(ReferenceChange))).all()) == 1


async def test_a_run_writes_its_per_source_once(db_session, board):
    """`per_source` is written once, at the run's terminal record, never again
    for each source that finishes: a run over N companies would otherwise
    write N growing copies of the map."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    writes: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        # The run's own writes; the stale-run reconciler's projection is another run's.
        if (statement.lstrip().upper().startswith("UPDATE SCRAPE_RUNS") and "per_source" in statement
                and "jsonb_object_agg" not in statement):
            writes.append(statement)

    for company in ("apple", "amazon"):
        board.plans[company] = (["one"], "complete")
    event.listen(Engine, "before_cursor_execute", count)
    try:
        await pipeline.run_pipeline(companies=["apple", "amazon"], hydrate=False)
    finally:
        event.remove(Engine, "before_cursor_execute", count)
    (run,) = (await db_session.scalars(select(ScrapeRun))).all()
    assert set(run.per_source) == {"apple", "amazon"}
    assert len(writes) == 1, writes
    # This board's listing never reaches a shared transport: its cost is unknown, never zero.
    rows = (await db_session.scalars(select(ScrapeSourceRun))).all()
    assert {(r.request_count, r.retry_count, r.bytes_received) for r in rows} == {(None, None, None)}
    assert run.per_source["apple"]["requests"] is None
