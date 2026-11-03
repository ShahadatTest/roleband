"""Daily pipeline: scrape -> enrich -> filter -> persist -> demand rollup.

For each enabled company we pull the (cheap) job list, annotate and filter to
level-6+ target-family target-location roles, hydrate descriptions only for
keepers, resolve comp, and upsert with full longitudinal bookkeeping. Then we
recompute demand metrics and finalize the run log.

This module is the run's assembly: scope and targets, the run
lock, the heartbeat, the stages in order, and guaranteed finalization. The stages
own their work: `collection` (network, no DB session), `run_persistence`
(per-source writes and the terminal record), `post_passes` (derived data), with
the shared shapes in `collection_types`.

Transaction map. One `session_scope` session owns every write below. Collection
holds no session; the heartbeat writes through its own short-lived sessions.

1. Advisory run lock on a connection of its own, wait-retrying briefly. Not
   acquired: return `skipped`, no run row.
2. COMMIT the stale-run reconciliation and the `running` marker. `run_pk` is read
   here, while loaded, so no later rollback can turn reading it into
   MissingGreenlet. The heartbeat starts once the row has an id.
3. COMMIT builtins, source bindings, company profiles, the run scope corrected
   from coverage, the sync-started notification and zero-state progress. The
   budget, frontier and fresh-description reads follow.
4. Collection streams into `_RunWriter`, the one task that writes:
   a. COMMIT kept rows (`persist_rows`: upserts + observations) whenever the
      writer's queue runs dry, while their company is still being read;
   b. COMMIT each company when its scan ends, in completion order:
      `finalize_source` (scope flags, closure, catalog, health, source-run row),
      then the run row's running totals flushed BEFORE the progress notification
      (the lock order the heartbeat shares). Companies a crashed lane
      synthesised are finished after collection, in target order.
   Each writer transaction takes the scope lock (`repo.hold_scope_projection`)
   before its first row write and, just before its commit, re-projects the
   rows it wrote or flagged onto the scope saved now, so a save made during
   the run is never undone by it. `upsert_job` re-reads a held
   row's `source_facts` under a row lock before merging into it.
   A writer failure cancels the collection and propagates to step 7; whatever
   it committed before stays committed.
5. COMMIT per post-pass in `run_post_passes`, plus one per derivation-state
   record. A non-fatal failure rolls that pass back and continues; a fatal one
   rolls back, records itself, and raises into step 7.
6. Success: `record_run_finished` flushes the terminal status and notifies; the
   heartbeat stops, the lock is released, and the session scope's exit commits.
7. `Exception`: `record_run_failure` rolls back first (the session may be
   pending-rollback), reloads the run by `run_pk`, records `error`, notifies and
   commits; the original exception is re-raised.
8. Always: cancel and await the heartbeat, then release the lock (a failed
   unlock invalidates the lock's connection, which frees it). Cancellation
   is not an `Exception`: no terminal status is written here, and the `running`
   row goes silent for the stale-run reconciler, or is ended by the cancel route
   as the projection of the sources already committed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.comp_providers.static import StaticCompProvider
from tracker.company_store import (
    ScanTarget,
    ensure_builtins,
    ensure_catalog_connectors,
    ensure_source_bindings,
    get_active_targets,
    record_route,
)
from tracker.config import Settings, get_settings
from tracker.connectors.recipes.outcome import SourceOutcome, classify_source_outcome
from tracker.db.binding import get_active_binding
from tracker.db.models import ScrapeRun, SourceBinding, SyncScheduleState
from tracker.db.recipe_store import attach_recipe_plans
from tracker.db.repo import (
    hold_scope_projection,
    load_company_jobs,
    load_fresh_description_keys,
    load_held_dates,
    load_known_places,
    load_open_keys,
    reconcile_stale_runs,
)
from tracker.db.session import session_scope
from tracker.enrich.comp import CompResolver, EstimateSet
from tracker.health import RunScope
from tracker.notifications import generate_sync_started_notification, update_sync_progress
from tracker.platform.heartbeat import heartbeat_loop
from tracker.platform.locks import release_dedicated_advisory_lock, take_dedicated_advisory_lock
from tracker.platform.version import code_version
from tracker.plugins.reestimate import reestimate, reference_inputs
from tracker.profiles.seed import ensure_company_profiles
from tracker.scope.projection import recompute_saved_scope
from tracker.workflows.collection import collect_sources
from tracker.workflows.collection_types import (
    AskedCompany,
    RunLookups,
    ScanMode,
    SourceCollection,
)
from tracker.workflows.post_passes import PostPassContext, run_post_passes, run_refresh_passes
from tracker.workflows.progress import RunProgress
from tracker.workflows.run_persistence import (
    finalize_source,
    persist_rows,
    record_run_failure,
    record_run_finished,
    scan_emits_run_notifications,
)
from tracker.workflows.scope_filter import load_scope_filter
from tracker.workflows.tuning_pass import load_page_budgets, load_source_budgets, load_source_costs

logger = logging.getLogger(__name__)

# A scrape wait-retries for the run lock (scrape priority): discovery releases it
# between companies within ~1 company scan, so this only needs to cover one gap;
# another scrape holds it for its whole run, so we time out and skip.
_RUN_LOCK_WAIT_SECONDS = 45.0
_RUN_LOCK_RETRY_SECONDS = 0.5


def resolve_run_scope(requested: RunScope, *, roster: int, targeted: int) -> RunScope:
    """Downgrade a `full` request to `targeted` when the run covered less.

    Scope is a property of what a run *covered*, never of what invoked it.
    Asking the caller is the wrong question: a `--company` run that touches a
    few companies, recorded `full`, would advance `last_success_at`, report the
    whole roster fresh, and switch off the catch-up for the companies it never
    contacted.

    Only ever downgrades. A `targeted` retry that happens to cover the whole
    roster is still a retry: it ran because those sources failed, not as a
    fresh statement about the roster.
    """
    return RunScope.TARGETED if targeted < roster else requested


def _heartbeat_task(
    run_id: int, interval_seconds: int, progress: RunProgress | None = None
) -> asyncio.Task:
    """Bump ``ScrapeRun.heartbeat_at`` every ``interval_seconds`` while live.

    Runs as a detached task in its own short-lived sessions so the beat is
    independent of the pipeline's long collect/persist phases. When the process
    is killed the beats simply stop, and the liveness guard + reconciler see the
    run go silent within ``stale_run_heartbeat_seconds`` — no waiting out the
    ``stale_run_minutes`` backstop. A single failed beat is non-fatal
    (loop policy lives in tracker.platform.heartbeat).

    The beat also carries live progress. The collect phase holds no DB session
    by design, so this detached beat is the only writer able to publish progress
    while sources are still being fetched — without it the UI shows zeros for
    the whole (longest) phase. The persist loop publishes inline instead, so its
    counters advance per company rather than per beat.
    """

    async def _bump() -> None:
        # LOCK ORDER, load-bearing: `scrape_runs` then `notifications`, matching
        # the persist loop (which flushes the run row before calling
        # `update_sync_progress`). These are the only two writers of both tables
        # and they must agree, or they deadlock — see the persist loop's note.
        # Progress is display; the beat is liveness. Progress goes in a
        # savepoint, so its failure is raised to the loop (which logs it) only
        # after the beat has committed, and never costs the run its liveness.
        progress_failed: Exception | None = None
        async with session_scope() as hb:
            await hb.execute(
                text(
                    "UPDATE scrape_runs SET heartbeat_at = now() "
                    "WHERE id = :id AND status = 'running'"
                ),
                {"id": run_id},
            )
            if progress is not None:
                try:
                    async with hb.begin_nested():
                        await update_sync_progress(hb, run_id, progress.snapshot())
                except Exception as error:  # noqa: BLE001 - raised below, after the beat commits
                    progress_failed = error
        if progress_failed is not None:
            raise progress_failed

    return asyncio.create_task(
        heartbeat_loop(_bump, interval_seconds, log_name=f"scrape-run-{run_id} heartbeat")
    )


@asynccontextmanager
async def _comp_resolver_scope():
    """Own resolver cleanup across DB/session and pipeline failures.

    The estimate reads the stored per-level rows, loaded once for the run: no
    network call inside enrichment, and the same rows give the same estimate
    on every run. The run points it at the reference set it
    collects under once it holds the lock (`resolver.reset`); until then it
    answers from the static seed alone and is never asked. It holds ours and the
    selected plugin's resolvers side by side."""
    resolver = EstimateSet(CompResolver([StaticCompProvider()]))
    try:
        yield resolver
    finally:
        await resolver.aclose()


#: `(session, company, stats)`: bookkeeping written in the company's own commit.
SourceRecordedHook = Callable[[AsyncSession, str, dict], Awaitable[None]]


async def _load_lookups(
    session, targets: dict[str, ScanTarget], *, scan_mode: ScanMode, settings: Settings
) -> RunLookups:
    """What a run reads before collecting `targets`, so the hot path never
    queries per job or per query; also read for a company that joins the run."""
    return RunLookups(
        # Rows whose description is recent enough not to re-fetch. A row
        # with NO text is never in here, so it is always fetched.
        fresh_description_keys=await load_fresh_description_keys(
            session, targets, settings.description_refresh_days
        ),
        known_places=await load_known_places(
            session, targets, settings.description_refresh_days
        ),
        held_dates=await load_held_dates(session, targets),
        # Learned bounds. Absent rows mean the adapter's own constant
        # stands, so a company with no history behaves exactly as an
        # untuned one.
        page_budgets=await load_page_budgets(session, targets),
        source_budgets=await load_source_budgets(session, targets),
        # The discovery frontier: the keys of the postings already held
        # open.
        existing_open_keys=(
            await load_open_keys(session, targets)
            if scan_mode is ScanMode.DISCOVERY
            else {}
        ),
        # What each company cost and found last time: the order lanes
        # start in, so most of a user's jobs land first.
        costs=await load_source_costs(session, targets),
    )


#: How often the run's writer looks for companies asked for during the run.
_ASKED_EVERY_SECONDS = 5.0


class _RunWriter:
    """The run's one writer while collection streams into it.

    Collection holds no session; it hands this writer each kept row as it is
    read and each company as it finishes, through an in-memory queue. One task
    drains the queue in order on the run's session, so there is still exactly
    one writer. Rows are committed whenever the queue runs dry, which puts a
    posting on the Board seconds after its page is read; a company is finished
    (scope flags, closure, catalog, health, source-run row, run totals) in its
    own commit when its scan ends, with the same decisions `persist_source`
    makes over a whole collection.

    Closure still needs the whole listing, and nothing here changes that: a row
    written early is a presence observation, which is what it was at the end of
    the scan too.
    """

    def __init__(
        self,
        session,
        run: ScrapeRun,
        targets: dict[str, ScanTarget],
        *,
        scan_mode: ScanMode,
        max_list: int | None,
        progress: RunProgress,
        touched_ids: list[int],
        per_source: dict[str, dict],
        outcomes: dict[str, SourceOutcome],
        drift_all: list[dict],
        totals: dict[str, int],
        settings: Settings,
        on_recorded: SourceRecordedHook | None = None,
        asked: asyncio.Queue[AskedCompany] | None = None,
    ) -> None:
        self._on_recorded = on_recorded
        self._settings = settings
        self._asked = asked
        #: Companies asked for during the run that joined it, with their targets.
        self._joined: dict[str, ScanTarget] = {}
        self._asked_seen: set[str] = set()
        self._asked_at = 0.0
        # Rows before this index in `touched_ids` have had a refresh.
        self._refreshed = 0
        self._refreshed_at = time.monotonic()
        self._session = session
        self._run = run
        self._targets = targets
        self._scan_mode = scan_mode
        self._max_list = max_list
        self._progress = progress
        self._touched_ids = touched_ids
        self._per_source = per_source
        self._outcomes = outcomes
        self._drift_all = drift_all
        self._totals = totals
        self._events: asyncio.Queue = asyncio.Queue()
        self._existing: dict[str, dict] = {}
        self._bindings: dict[str, int | None] = {}
        self._written: dict[str, set[str]] = {}
        self._new: dict[str, int] = {}
        self.finished: set[str] = set()
        # The scope lock is held from this transaction's first row write to
        # its commit, and these rows are re-projected just before it.
        self._scope_held = False
        self._projected: set[int] = set()

    # Hooks for `collect_sources`: synchronous, in-memory, never failing.
    def row(self, company: str, enriched) -> None:
        self._events.put_nowait((company, enriched, None))

    def collected(self, company: str, collection: SourceCollection) -> None:
        self._events.put_nowait((company, None, collection))

    def close(self) -> None:
        self._events.put_nowait(None)

    async def drain(self) -> None:
        """Write events until `close`; commits when the queue runs dry."""
        dirty = False
        while True:
            try:
                # With requests to take, a quiet stretch (one long company) is
                # no reason to leave a person's Scan now waiting.
                event = await asyncio.wait_for(
                    self._events.get(), timeout=_ASKED_EVERY_SECONDS if self._asked is not None else None
                )
            except TimeoutError:
                await self._take_asked()
                continue
            if event is None:
                if dirty:
                    await self._commit()
                return
            company, enriched, collection = event
            if collection is not None:
                await self.finish(company, collection)  # commits
                dirty = False
                await self._take_asked()
                await self._refresh_when_due()
            elif company not in self.finished:
                await self._write(company, [enriched])
                dirty = True
            if dirty and self._events.empty():
                await self._commit()
                dirty = False

    async def _take_asked(self) -> None:
        """Between companies, at most every `_ASKED_EVERY_SECONDS`: the
        companies a person asked for (Scan now) since the run began join it
        at the front of their lanes (`collect_sources`' ``asked``). Only a
        company with a schedule row has the binding a finish needs. One the
        run already holds is still passed on: the collection moves it to the
        front if it has not started it."""
        if self._asked is None or time.monotonic() - self._asked_at < _ASKED_EVERY_SECONDS:
            return
        self._asked_at = time.monotonic()
        asked = set(
            (
                await self._session.scalars(
                    select(SourceBinding.company_slug)
                    .join(SyncScheduleState, SyncScheduleState.binding_id == SourceBinding.id)
                    .where(
                        SyncScheduleState.manual_requested_at >= self._run.started_at,
                        SourceBinding.status != "retired",
                    )
                )
            ).all()
        ) - self._asked_seen - self.finished
        if not asked:
            return
        self._asked_seen |= asked
        roster = await get_active_targets(self._session)
        joining = {company: roster[company] for company in sorted(asked) if company in roster}
        await attach_recipe_plans(self._session, joining)
        lookups = await _load_lookups(self._session, joining, scan_mode=self._scan_mode, settings=self._settings)
        for company, cfg in joining.items():
            target = self._targets.get(company)
            if target is None:
                self._joined[company] = cfg
                self._progress.join(company)
            self._asked.put_nowait(AskedCompany(company, target or cfg, lookups.for_company(company)))

    async def _refresh_when_due(self) -> None:
        """Between companies, at most every `scan_refresh_minutes`: the
        incremental post-passes over the rows written since the last refresh.
        Here, on the writer's own task and after a commit, they never race a
        row write and never run inside a scope hold. Collection goes on
        reading meanwhile; its rows wait in the queue."""
        if time.monotonic() - self._refreshed_at < self._settings.scan_refresh_minutes * 60:
            return
        ids = self._touched_ids[self._refreshed:]
        self._refreshed = len(self._touched_ids)
        self._refreshed_at = time.monotonic()
        if not ids:
            return
        await run_refresh_passes(PostPassContext(
            session=self._session,
            run=self._run,
            touched_ids=ids,
            per_source=dict(self._per_source),
            settings=self._settings,
            max_list=self._max_list,
            scan_mode=self._scan_mode,
        ))

    async def _existing_for(self, company: str) -> dict:
        if company not in self._existing:
            self._existing[company] = await load_company_jobs(self._session, company)
        return self._existing[company]

    async def _binding_for(self, company: str) -> int | None:
        """The binding this run reads the company under, resolved once.

        Each posting records the alias it was seen by, and this is asked per
        page of rows; the binding cannot change inside a run, so it is read
        once per company like the rows above it.
        """
        if company not in self._bindings:
            binding = await get_active_binding(self._session, company)
            self._bindings[company] = binding.id if binding is not None else None
        return self._bindings[company]

    async def _hold_scope(self) -> None:
        """The run decides scope with what it loaded at its start; a save during
        the run re-projects the stored rows at once. Held from before this
        transaction's first row write, so a save waits for this commit and its
        re-projection sees these rows, or this transaction waits for the save
        and re-projects them under it."""
        if not self._scope_held:
            await hold_scope_projection(self._session)
            self._scope_held = True

    async def _commit(self) -> None:
        """Re-project the rows this transaction wrote onto the scope saved now,
        then commit, which ends the hold."""
        if self._projected:
            await recompute_saved_scope(self._session, job_ids=sorted(self._projected))
        await self._session.commit()
        self._scope_held = False
        self._projected.clear()

    async def _write(self, company: str, rows: list) -> None:
        written = self._written.setdefault(company, set())
        fresh = [row for row in rows if row.raw.dedupe_key() not in written]
        if not fresh:
            return
        await self._hold_scope()
        before = len(self._touched_ids)
        new = await persist_rows(
            self._session, self._run, fresh, await self._existing_for(company),
            scan_mode=self._scan_mode, touched_ids=self._touched_ids,
            binding_id=await self._binding_for(company),
        )
        self._projected.update(self._touched_ids[before:])
        written.update(row.raw.dedupe_key() for row in fresh)
        self._new[company] = self._new.get(company, 0) + new

    async def finish(self, company: str, collection: SourceCollection) -> None:
        """Finish one company in its own commit; a second call is a no-op."""
        if company in self.finished:
            return
        self._progress.source_persist_started(company)
        await self._hold_scope()
        # Rows the stream did not carry (a hand-off that failed) are written
        # here, so the collection stays the complete record either way.
        await self._write(company, collection.enriched)
        stats = collection.stats
        stats["new"] += self._new.pop(company, 0)
        # A company cut by a bound outside its collection (the backstop)
        # arrives with nothing kept, yet the rows it streamed
        # before the cut are written: the record counts them, and the cut stays
        # the failure its errors say.
        stats["kept"] = max(stats["kept"], len(self._written.get(company, ())))
        run = self._run
        existing = await self._existing_for(company)
        self._outcomes[company] = await finalize_source(
            self._session,
            run,
            company,
            collection,
            existing,
            provider_key=(self._targets.get(company) or self._joined[company])["adapter"],
            scan_mode=self._scan_mode,
            max_list=self._max_list,
            touched_ids=self._touched_ids,
        )
        # `finalize_source` set every observed row's scope flag from the run's
        # own scope decisions, and gave held rows it judged out what it read of
        # them; those rows are re-projected with the rest.
        self._projected.update(
            existing[key].id for key in collection.scope_by_key if key in existing and existing[key].id
        )
        self._existing.pop(company, None)
        self._written.pop(company, None)
        self.finished.add(company)
        if collection.route is not None:
            # The board moved to another route of its family; the
            # next run collects it there.
            await record_route(self._session, company, collection.route)
        self._drift_all.extend(collection.drift)
        self._per_source[company] = stats
        if self._on_recorded is not None:
            await self._on_recorded(self._session, company, stats)
        self._totals["seen"] += stats["kept"]
        self._totals["new"] += stats["new"]
        self._totals["closed"] += stats["closed"]
        logger.info("%s: %s", company, stats)

        run.jobs_seen = self._totals["seen"]
        run.jobs_new = self._totals["new"]
        run.jobs_closed = self._totals["closed"]
        # Belt-and-suspenders beat on the run's own session, so a run is
        # provably live while it writes even if the ticker lags.
        run.heartbeat_at = datetime.now(UTC)
        self._progress.source_recorded(company, stats["kept"])
        # LOCK ORDER, load-bearing: emit the `scrape_runs` UPDATE before
        # touching `notifications`. The detached heartbeat writes the same
        # two tables in that order (`_heartbeat_task._bump`), and
        # `update_sync_progress` is raw `text()` SQL, which does NOT
        # autoflush the dirty `run`, so without this flush the loop would
        # take notifications->scrape_runs against the beat's
        # scrape_runs->notifications and the two would deadlock: Postgres
        # kills the loop's UPDATE, the session goes PendingRollbackError,
        # and the run is stuck in `running`. Keep these two statements in
        # this order.
        await self._session.flush()
        await update_sync_progress(self._session, run.id, self._progress.snapshot())
        await self._commit()


async def _collect_into(writer: _RunWriter, collect) -> dict[str, SourceCollection]:
    """Run collection with its writer beside it; a writer failure stops both.

    The writer is the run's session owner, so its failure is the run's: the
    collection is cancelled (its adapters close) and the error propagates to
    the recovery block. A cancelled run cancels both, and what the writer
    already committed stays committed (the cancel route projects it).
    """
    collect_task = asyncio.create_task(collect, name="run-collect")
    write_task = asyncio.create_task(writer.drain(), name="run-write")
    try:
        await asyncio.wait({collect_task, write_task}, return_when=asyncio.FIRST_COMPLETED)
        if write_task.done():
            # The writer ends only on `close` or on a failure; nothing closed it.
            collect_task.cancel()
            await asyncio.gather(collect_task, return_exceptions=True)
            write_task.result()
            raise RuntimeError("run writer stopped before collection finished")
        collections = collect_task.result()
        writer.close()
        await write_task
        return collections
    except BaseException:
        for task in (collect_task, write_task):
            task.cancel()
        await asyncio.gather(collect_task, write_task, return_exceptions=True)
        raise


async def run_pipeline(
    companies: list[str] | None = None,
    *,
    max_list: int | None = None,
    hydrate: bool = True,
    run_scope: RunScope = RunScope.FULL,
    scan_mode: ScanMode = ScanMode.RECONCILE,
    on_source_recorded: SourceRecordedHook | None = None,
    join_requests: bool = False,
) -> dict:
    """Execute one pipeline run.

    Args:
        companies: subset of company slugs to run (default: all enabled).
        max_list: cap on raw jobs scanned per company (for fast test runs).
        hydrate: fetch full descriptions for kept jobs (detail calls).
        run_scope: the *most* this run may claim. `full` is a request, not an
            assertion — it is downgraded to `targeted` below if the run turns
            out not to have attempted the whole roster. `targeted` is never
            upgraded, so an automated retry stays targeted even when its subset
            happens to be everything.
        scan_mode: `discovery` is non-authoritative by construction. It may add
            or update jobs but never closes missing jobs or advances source
            health. `reconcile` retains the existing authoritative behavior.
        join_requests: a reconcile run takes the companies a person asks for
            while it reads (`_RunWriter._take_asked`); its caller records them
            through ``on_source_recorded`` like its own.
        on_source_recorded: ``(session, company, stats)``, awaited inside the
            commit that finishes each company, so a caller's bookkeeping (the
            scheduler's next deadlines) lands with the source it describes.
            Writes on the run's session and commits nothing; a failure fails
            the run.
    """
    scan_mode = ScanMode(scan_mode)
    settings = get_settings()
    per_source: dict[str, dict] = {}
    outcomes: dict[str, SourceOutcome] = {}
    drift_all: list[dict] = []
    touched_ids: list[int] = []
    totals = {"seen": 0, "new": 0, "closed": 0}
    demand_slices = 0

    async with _comp_resolver_scope() as resolver, session_scope() as session:
        # DB-level overlap guard (backstop to the process fcntl lock), held on
        # a connection of its own: this session commits mid-run, and a lock on
        # its connection would go back to the pool with it.
        # A scrape takes PRIORITY over the role-discovery scan: wait-retry briefly
        # rather than skip instantly, because discovery releases the lock between
        # companies so a waiting scrape can slip in (see tracker.discover_roles).
        # Another *scrape* holds it for its whole run, so we still time out and
        # skip in that case (no concurrent runs).
        lock_connection = await take_dedicated_advisory_lock(
            session.bind,
            settings.advisory_lock_key,
            wait_seconds=_RUN_LOCK_WAIT_SECONDS,
            retry_seconds=_RUN_LOCK_RETRY_SECONDS,
        )
        if lock_connection is None:
            logger.warning("advisory lock held by another run; skipping")
            return {"skipped": "run already in progress", "status": "skipped"}

        heartbeat_task: asyncio.Task | None = None
        run_pk: int | None = None
        try:
            # Sweep orphaned rows before opening a new run so the log stays honest.
            await reconcile_stale_runs(
                session,
                settings.stale_run_minutes,
                settings.stale_run_heartbeat_seconds,
            )

            run = ScrapeRun(
                started_at=datetime.now(UTC),
                heartbeat_at=datetime.now(UTC),
                status="running",
                # The requested scope; corrected from actual coverage once the
                # roster is known (the column is NOT NULL, so it needs a value
                # at open).
                scope=run_scope,
                code_version=code_version(),
                # What a cancel signals; it ends only a run in that group.
                process_group=os.getpgrp(),
            )
            session.add(run)
            # Commit the marker immediately: if this process later crashes or
            # hangs, the row persists as "running" for the reconciler/watchdog to
            # flip to "error".
            await session.commit()
            # Read the id now, while it is loaded. Anything that rolls this
            # session back later expires `run`, and reading an expired attribute
            # is a lazy load, which under async SQLAlchemy raises MissingGreenlet
            # — in the recovery block below, in place of the real error.
            run_pk = run.id

            # Start beating now that the row has an id. A killed process stops
            # beating; the liveness guard then unblocks manual sync in minutes.
            # The progress object is created here (targets are still unknown, so
            # the total is filled in below) purely so the heartbeat can hold one
            # stable reference for the whole run.
            progress = RunProgress(companies_total=0)
            heartbeat_task = _heartbeat_task(run.id, settings.run_heartbeat_seconds, progress)

            scope = await load_scope_filter(session)

            # Every company (built-in + user-added) is a tracked_company row, so the
            # targets are simply the active, enabled, adapter-backed rows. Seed the
            # built-ins first so a fresh DB / newly-added config company is included,
            # then their /company profiles (prices targeting needs profile rows).
            await ensure_builtins(session)
            # Then read the catalog back into any row still waiting for one: a
            # company added before its connector existed keeps `adapter=None`
            # and is dropped by `get_active_targets` with no error.
            await ensure_catalog_connectors(session)
            # Must follow ensure_builtins (it can create the company row this
            # binds) and precede collection: the persist loop's closure
            # resolution and per-source health both need the binding to exist.
            # Without it a newly-seeded company silently falls back
            # to company-scoped closure with no health gate.
            await ensure_source_bindings(session)
            await ensure_company_profiles(session)
            roster = await get_active_targets(session)
            targets = (
                {k: v for k, v in roster.items() if k in companies} if companies else roster
            )
            # Recipe-bound companies carry their pinned, compiled plan.
            await attach_recipe_plans(session, targets)
            # Derived from coverage, never from the caller — see
            # `resolve_run_scope`. Set here rather than at run open because the
            # roster is not known until now.
            run.scope = resolve_run_scope(
                run_scope, roster=len(roster), targeted=len(targets)
            )
            if scan_emits_run_notifications(scan_mode):
                await generate_sync_started_notification(session, run, sorted(targets))
            # Publish the zero-state immediately so the notification shows the
            # company roster the moment it appears, not one heartbeat later.
            progress.set_targets(
                targets, concurrency_limit=settings.scraper_max_concurrent_sources
            )
            await update_sync_progress(session, run.id, progress.snapshot())
            await session.commit()

            # Collect under the current reference set: when it
            # is not the applied one, re-estimate every stored job first, on this
            # session (the run holds the lock), so this run's estimates and the
            # stored ones share one fingerprint and a `comp_median` move recorded
            # below is a fact about the job, not about the switch. Each posting is
            # estimated by ours and the selected plugin's, each from its own data.
            # Estimate under the set the re-estimate read under its lock: one read
            # before it could predate a decision committed in between.
            moved = await reestimate(session)
            reference = moved.inputs or await reference_inputs(session)
            resolver.reset(reference.estimate_set())

            # Read once before collection, so the hot path never queries per job
            # or per query.
            lookups = await _load_lookups(session, targets, scan_mode=scan_mode, settings=settings)
            # Filled by the writer between companies, read by the collection.
            asked: asyncio.Queue[AskedCompany] | None = (
                asyncio.Queue() if join_requests and scan_mode is ScanMode.RECONCILE else None
            )
            writer = _RunWriter(
                session,
                run,
                targets,
                scan_mode=scan_mode,
                max_list=max_list,
                progress=progress,
                touched_ids=touched_ids,
                per_source=per_source,
                outcomes=outcomes,
                drift_all=drift_all,
                totals=totals,
                settings=settings,
                on_recorded=on_source_recorded,
                asked=asked,
            )
            collections = await _collect_into(
                writer,
                collect_sources(
                    targets,
                    scope,
                    resolver,
                    max_list=max_list,
                    hydrate=hydrate,
                    max_concurrent_sources=settings.scraper_max_concurrent_sources,
                    source_budget_seconds=settings.scraper_source_budget_seconds,
                    source_stall_seconds=settings.scraper_source_stall_seconds,
                    on_source_start=progress.source_started,
                    on_source_done=progress.source_collected,
                    scan_mode=scan_mode,
                    lookups=lookups,
                    on_row=writer.row,
                    on_collected=writer.collected,
                    asked=asked,
                ),
            )
            # Close the reporting gap before the UI can observe it. The fill-in
            # above synthesises a failed collection for every company a cancelled
            # or crashed backend never produced, and those paths never reach
            # `_report` — so without this pass a lost company stays "scraping"
            # for the rest of the run, with a clock still ticking on it.
            progress.reconcile_collected(
                {
                    company: (
                        len(collection.enriched),
                        classify_source_outcome(
                            {**collection.stats, "list_complete": collection.list_complete}
                        ).value,
                        int(collection.stats.get("scanned") or 0),
                    )
                    for company, collection in collections.items()
                }
            )
            progress.set_phase("persisting")

            # Companies the stream never announced: the ones a crashed lane
            # synthesised. Finished in target order, one commit each.
            for company in targets:
                await writer.finish(company, collections[company])

            progress.set_phase("finishing")

            # Post-passes run over whatever succeeded, even when a source
            # failed: gating them on every source would throw away the
            # demand rollup for every healthy source to punish one bad
            # neighbour, the coupling bulkheads remove. The passes are
            # individually scoped (`clean_companies`) and individually
            # failure-tolerant.
            post_ctx = PostPassContext(
                session=session,
                run=run,
                touched_ids=touched_ids,
                per_source=per_source,
                settings=settings,
                max_list=max_list,
                scan_mode=scan_mode,
            )
            await run_post_passes(post_ctx)
            demand_slices = post_ctx.results.get("demand_slices", 0)

            await record_run_finished(
                session,
                run,
                outcomes=outcomes,
                totals=totals,
                per_source=per_source,
                drift_all=drift_all,
                demand_slices=demand_slices,
                scan_mode=scan_mode,
            )
            run_id = run.id
            run_status = run.status
        except Exception as exc:  # noqa: BLE001 - persist failed run state before surfacing.
            # `run_pk` was read when the marker was committed, never here: the
            # recorder rolls back before it reloads the run.
            await record_run_failure(
                session,
                run_pk,
                exc,
                per_source=per_source,
                drift_all=drift_all,
                totals=totals,
                scan_mode=scan_mode,
                outcomes=outcomes,
            )
            raise
        finally:
            # Stop the heartbeat before releasing the lock so no beat lands after
            # this run's terminal status is written.
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001 - teardown must not mask the run result
                    logger.debug("heartbeat task teardown error", exc_info=True)
            # A failed unlock has already invalidated the lock's connection,
            # which frees the lock; it must not mask the run's own result.
            try:
                await release_dedicated_advisory_lock(lock_connection, settings.advisory_lock_key)
            except Exception:  # noqa: BLE001
                logger.debug("advisory unlock failed; its connection was invalidated")

    summary = {
        "run_id": run_id,
        "status": run_status,
        **totals,
        "demand_slices": demand_slices,
        "per_source": per_source,
        "scan_mode": scan_mode.value,
    }
    return summary
