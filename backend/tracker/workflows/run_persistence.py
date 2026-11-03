"""What a run writes: each source's persistence and the run's terminal record.

Session ownership is explicit, and no session is ever shared with
collection:

* `persist_rows` writes kept rows as they are read and `finalize_source`
  decides a source once its listing is whole; the run's writer commits both.
  `persist_source` is the two at once, and commits nothing.
* `record_run_finished` flushes the terminal status and writes the run's
  notifications; the run's session scope commits it after the heartbeat stops
  and the run lock is released.
* `record_run_failure` rolls back first, reloads the run by its id, records
  `error`, notifies and commits.

Closure authority is two gates, both applied in `persist_source`: run quality
(`scan_may_close`, over `should_close_missing`) says whether the listing is
evidence at all, and the binding's closure scope says which jobs it may speak for.
Within them a posting closes only on its second miss (`repo.record_absence`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from tracker.config import get_settings
from tracker.connectors.recipes.outcome import (
    RESETS_ABSENCE,
    SourceOutcome,
    classify_source_outcome,
    run_status_for,
)
from tracker.db.arrival import classify_arrivals
from tracker.db.binding import (
    activate_validated_binding,
    get_active_binding,
    resolve_closure_scope,
)
from tracker.db.inventory_store import write_inventory
from tracker.db.models import ScrapeRun, ScrapeSourceRun
from tracker.db.repo import (
    apply_scope_state,
    close_missing,
    load_company_jobs,
    record_absence,
    refresh_held_reads,
    reset_absence,
    upsert_job,
)
from tracker.notifications import generate_notifications
from tracker.platform.util import describe_exception
from tracker.plugins import reestimate
from tracker.scope.catalog_store import persist_company_catalog
from tracker.taxonomy.role_catalog import catalog_collection_error
from tracker.usage_stats.recorder import record_exception
from tracker.workflows.collection_types import ScanMode, SourceCollection

logger = logging.getLogger(__name__)

def should_close_missing(collection: SourceCollection, *, max_list: int | None) -> bool:
    """Whether this listing is trustworthy evidence that unseen jobs closed."""
    return (
        max_list is None
        and collection.list_complete
        and not collection.stats.get("errors")
    )


def scan_may_close(
    scan_mode: ScanMode,
    collection: SourceCollection,
    *,
    max_list: int | None,
) -> bool:
    """Authority gate above listing completeness.

    A discovery probe is evidence of presence only. Even if a tiny board ends
    naturally before the cap and reports `list_complete=True`, the work item
    was not scheduled as lifecycle reconciliation and may not close by absence.
    """
    return scan_mode is ScanMode.RECONCILE and should_close_missing(
        collection, max_list=max_list
    )


def discovery_should_persist(existing_job) -> bool:
    """Discovery owns the frontier, not canonical refresh of already-open rows."""
    return existing_job is None or existing_job.status != "open"


def scan_emits_run_notifications(scan_mode: ScanMode) -> bool:
    """Micro-probes may notify new roles, never one sync banner per probe."""
    return scan_mode is ScanMode.RECONCILE


def _record_absence(
    stats: dict, scope, existing: dict, seen_keys: set[str]
) -> frozenset[int]:
    """Count this listing's misses; returns the postings missed for the second time.

    The keys are recorded on every source, zero where the listing is not
    evidence, so a run's audit shape does not depend on its outcome. Two of
    them are shadow measures for a sudden-drop guard: `absence_missed` of
    `absence_open` is the share of the company's open postings one listing
    missed, read from runs to set its threshold. `closure_one_miss` is what a
    one-miss rule would close here.
    """
    tally = None
    if scope.speaks_for:
        tally = record_absence(
            existing,
            seen_keys,
            speaks_for=scope.speaks_for,
            now=datetime.now(UTC),
            min_gap=timedelta(hours=get_settings().closure_second_miss_min_hours),
        )
    stats["absence_open"] = tally.open if tally else 0
    stats["absence_missed"] = tally.missed if tally else 0
    stats["absence_missing_share"] = tally.missing_share if tally else 0.0
    stats["absence_second_miss"] = len(tally.second_miss) if tally else 0
    stats["closure_one_miss"] = (
        tally.missed if tally is not None and scope.may_close else 0
    )
    return tally.second_miss if tally else frozenset()


async def _activate_source_binding(
    session, company: str, outcome: SourceOutcome, stats: dict, *, now: datetime, run_id: int
) -> None:
    """Let this run's evidence grant a withheld binding closure authority.

    Ordered deliberately: after `resolve_closure_scope`, so the run supplying
    the evidence never closes on it. Binding health plays no part:
    the first complete listing with rows activates, whatever failed before it.

    `binding_activation` is recorded only when something is actually withheld.
    Stamping "nothing withheld" onto every binding every night would
    put a constant string in `per_source` and in every `scrape_source_runs.stats`
    row, and make the one case worth reading harder to find. `binding_activated`
    rides with it: the scheduler reads whether this run granted authority from
    the flag, never from the reason's wording.
    """
    binding = await get_active_binding(session, company)
    if binding is None or binding.closure_capability != "none":
        return
    decision = await activate_validated_binding(
        session,
        binding,
        outcome=outcome,
        scan_mode=ScanMode.RECONCILE.value,
        scanned=int(stats.get("scanned") or 0),
        now=now,
        run_id=run_id,
    )
    stats["binding_activation"] = decision.reason
    stats["binding_activated"] = decision.activate
    logger.info(
        "%s: binding %d %s — %s",
        company,
        binding.id,
        "activated" if decision.activate else "still withheld",
        decision.reason,
    )


async def _write_source_inventory(
    session,
    run: ScrapeRun,
    company: str,
    collection: SourceCollection,
    *,
    scan_mode: ScanMode,
    max_list: int | None,
) -> None:
    """Keep every posting this scan read in `posting_inventory`.

    Only a listing that may close jobs may mark inventory rows gone; anything
    less upserts what it saw. In a SAVEPOINT: an inventory failure is recorded
    as `inventory_error` and costs the source nothing else, since closure,
    activation and the source-run row stay in the company's transaction.
    """
    settings = get_settings()
    if not settings.inventory_enabled:
        # Off means inert: an empty capture must never read as an empty board.
        return
    stats = collection.stats
    # Flushed first, so a failure of the company's own pending writes is not
    # recorded as the inventory's.
    await session.flush()
    binding = await get_active_binding(session, company)
    try:
        async with session.begin_nested():
            result = await write_inventory(
                session,
                run_id=run.id,
                company=company,
                binding_id=binding.id if binding is not None else None,
                rows=collection.inventory,
                seen_keys=collection.seen_keys,
                authoritative=scan_may_close(scan_mode, collection, max_list=max_list),
                now=datetime.now(UTC),
                touch_hours=settings.inventory_touch_hours,
            )
    except Exception as exc:  # noqa: BLE001 - the inventory never fails a source
        logger.warning("inventory write failed for %s", company, exc_info=True)
        stats["inventory_error"] = describe_exception(exc)[:500]
        return
    stats["inventory_rows"] = result.rows
    stats["inventory_gone"] = result.gone


async def persist_rows(
    session,
    run: ScrapeRun,
    rows,
    existing: dict,
    *,
    scan_mode: ScanMode,
    touched_ids: list[int],
    binding_id: int | None = None,
) -> int:
    """Upsert kept postings with their append-only observations; returns how
    many were new. Commits nothing.

    `binding_id` is the binding this scan read the company under; each posting
    records the alias it was seen by, which is what closure scope reads.

    The row half of `persist_source`, callable while the source is still being
    read: the run's writer calls it as each page's kept rows arrive,
    so a posting reaches the Board when it is read, not when its company (or
    the whole run) ends. It decides nothing about closure, activation or the
    catalog; those wait for `finalize_source`, which needs the whole listing.
    `existing` is the company's rows as loaded BEFORE the scan, the set closure
    reads, so it is not extended with the rows written here.
    """
    created: list[int] = []
    for enriched in rows:
        key = enriched.raw.dedupe_key()
        if (
            scan_mode is ScanMode.DISCOVERY
            and not discovery_should_persist(existing.get(key))
        ):
            continue
        job, is_new = await upsert_job(session, run, enriched, existing, binding_id=binding_id)
        touched_ids.append(job.id)
        if is_new:
            created.append(job.id)
    await classify_arrivals(session, created)
    return len(created)


async def persist_source(
    session,
    run: ScrapeRun,
    company: str,
    collection: SourceCollection,
    *,
    provider_key: str,
    scan_mode: ScanMode,
    max_list: int | None,
    touched_ids: list[int],
) -> SourceOutcome:
    """Write one collected source and return its outcome.

    Canonical upserts with their append-only observations (ids appended to
    `touched_ids` for the post-passes), closure by absence where run quality AND
    binding scope both allow it, the role catalog, binding activation,
    and the source's `scrape_source_runs` row. `collection.stats` is completed in
    place: it is the very dict the run records.

    Commits nothing. The run's persist loop commits after each source, so a
    failure here leaves every earlier source committed and this one's writes to
    the run's recovery rollback. The whole-source form of `persist_rows` +
    `finalize_source`, for a caller that holds the collection at once.
    """
    existing = await load_company_jobs(session, company)
    if scan_mode is ScanMode.RECONCILE:
        refreshed = refresh_held_reads(existing, collection.held_reads)
        touched_ids.extend(refreshed)
        # A fresh title, family or place is an estimate input.
        await reestimate.refresh_jobs(session, refreshed)
        apply_scope_state(existing, collection.scope_by_key)
    binding = await get_active_binding(session, company)
    collection.stats["new"] += await persist_rows(
        session, run, collection.enriched, existing,
        scan_mode=scan_mode, touched_ids=touched_ids,
        binding_id=binding.id if binding is not None else None,
    )
    return await _finish_source(
        session, run, company, collection, existing,
        provider_key=provider_key, scan_mode=scan_mode, max_list=max_list,
    )


async def finalize_source(
    session,
    run: ScrapeRun,
    company: str,
    collection: SourceCollection,
    existing: dict,
    *,
    provider_key: str,
    scan_mode: ScanMode,
    max_list: int | None,
    touched_ids: list[int] | None = None,
) -> SourceOutcome:
    """Everything a source decides once its listing is whole.

    For rows already written by `persist_rows` against the same `existing`:
    the scope flags of every observed row, closure by absence, the catalog,
    activation and the `scrape_source_runs` row, exactly as
    `persist_source` decides them. Commits nothing.

    Held rows judged out of scope take what the scan read of them first;
    their ids join `touched_ids`, as written rows do, so the
    post-passes re-read a changed title or place.
    """
    if scan_mode is ScanMode.RECONCILE:
        # After the upserts rather than before, as `persist_source` orders it:
        # an in-scope key is set True by both, and an out-of-scope one is
        # never upserted, so the order changes nothing.
        refreshed = refresh_held_reads(existing, collection.held_reads)
        if touched_ids is not None:
            touched_ids.extend(refreshed)
        # A fresh title, family or place is an estimate input.
        await reestimate.refresh_jobs(session, refreshed)
        apply_scope_state(existing, collection.scope_by_key)
    return await _finish_source(
        session, run, company, collection, existing,
        provider_key=provider_key, scan_mode=scan_mode, max_list=max_list,
    )


async def _finish_source(
    session,
    run: ScrapeRun,
    company: str,
    collection: SourceCollection,
    existing: dict,
    *,
    provider_key: str,
    scan_mode: ScanMode,
    max_list: int | None,
) -> SourceOutcome:
    stats = collection.stats
    # Two independent gates on closure. Run quality (uncapped,
    # complete, error-free) says the listing is trustworthy
    # evidence; binding scope says WHICH jobs this
    # binding is entitled to speak for. A rebind passes the first
    # and must still fail the second.
    scope = await resolve_closure_scope(
        session,
        company,
        open_jobs=list(existing.values()),
        listing_is_authoritative=scan_may_close(
            scan_mode, collection, max_list=max_list
        ),
    )
    stats["closure_scope"] = scope.reason
    stats["closure_eligible"] = scope.may_close
    # Seeing a posting in any scan, complete or not, starts its count again.
    reset_absence(
        job for key, job in existing.items() if key in collection.seen_keys
    )
    second_miss = _record_absence(stats, scope, existing, collection.seen_keys)
    if scope.may_close:
        stats["closed"] = await close_missing(
            session,
            run,
            company,
            collection.seen_keys,
            existing,
            closable_job_ids=scope.closable_job_ids & second_miss,
        )

    # A deferred company was never read, so it has nothing to say about its
    # catalog; an error written here would mark a ready catalog failed.
    if (
        scan_mode is ScanMode.RECONCILE
        and not stats.get("policy_reason")
        and not stats.get("deferred_reason")
    ):
        catalog_error = catalog_collection_error(
            errors=stats["errors"],
            scanned=stats["scanned"],
            drift_alerts=collection.drift,
        )
        await persist_company_catalog(
            session,
            company,
            collection.catalog,
            # A board proven empty is a complete catalog of no roles; its listing
            # is incomplete only so nothing closes on it.
            complete=max_list is None
            and (collection.list_complete or bool(stats.get("empty_proven"))),
            error=catalog_error,
            places=collection.catalog_places,
            unplaced=collection.catalog_unplaced,
            unsorted=collection.catalog_unsorted,
        )

    await _write_source_inventory(
        session, run, company, collection, scan_mode=scan_mode, max_list=max_list
    )

    stats["drift"] = collection.drift
    stats["list_complete"] = collection.list_complete
    # Derived once, from the finished stats dict, and recorded on the
    # run: the run's status is a projection of these values, and
    # "why was this run partial" must be answerable from the row
    # itself rather than re-derived by a reader.
    outcome = classify_source_outcome(stats)
    stats["outcome"] = outcome.value
    # A discovery probe neither counts nor resets a miss: a capped
    # probe that fails at noon is not evidence about last night's reconcile.
    if outcome in RESETS_ABSENCE and scan_mode is ScanMode.RECONCILE:
        reset_absence(existing.values())
    if scan_mode is ScanMode.RECONCILE:
        now = datetime.now(UTC)
        await _activate_source_binding(
            session, company, outcome, stats, now=now, run_id=run.id
        )
    binding = await get_active_binding(session, company)
    if binding is None:
        raise RuntimeError(f"{company}: active source binding disappeared")
    finished_source_at = datetime.now(UTC)
    source_duration = max(0.0, float(stats.get("duration_seconds") or 0.0))
    session.add(
        ScrapeSourceRun(
            run_id=run.id,
            binding_id=binding.id,
            company_slug=company,
            provider_key=provider_key,
            scan_mode=scan_mode.value,
            outcome=outcome.value,
            started_at=finished_source_at
            - timedelta(seconds=source_duration),
            finished_at=finished_source_at,
            scanned=int(stats.get("scanned") or 0),
            kept=int(stats.get("kept") or 0),
            jobs_new=int(stats.get("new") or 0),
            jobs_closed=int(stats.get("closed") or 0),
            # NULL when no read reached a shared transport: unknown, never zero.
            request_count=stats.get("requests"),
            retry_count=stats.get("retries"),
            bytes_received=stats.get("bytes_received"),
            list_complete=bool(collection.list_complete),
            closure_eligible=bool(
                scan_mode is ScanMode.RECONCILE
                and stats["closure_eligible"]
            ),
            errors=list(stats.get("errors") or []),
            drift=list(collection.drift),
            stats=dict(stats),
        )
    )
    return outcome


async def record_run_finished(
    session,
    run: ScrapeRun,
    *,
    outcomes: dict[str, SourceOutcome],
    totals: dict[str, int],
    per_source: dict[str, dict],
    drift_all: list[dict],
    demand_slices: int,
    scan_mode: ScanMode,
) -> None:
    """The terminal record of a run that got through its post-passes.

    Flushes the finished run row, then writes the run's notifications. Commits
    nothing: the run's session scope commits once the heartbeat has stopped and
    the run lock is released.
    """
    run.finished_at = datetime.now(UTC)
    # Status is a projection of the per-source outcomes, never an
    # independent judgement. `partial` (some sources good) counts as a
    # successful refresh; `error` means nothing usable came back at all.
    run.status = run_status_for(outcomes.values())
    run.jobs_seen = totals["seen"]
    run.jobs_new = totals["new"]
    run.jobs_closed = totals["closed"]
    run.per_source = per_source
    run.drift_alerts = drift_all
    note = f"{demand_slices} demand slices"
    # Name the sources that made a run less than ok. "partial" with no
    # explanation is the kind of status nobody can act on.
    unhealthy = sorted(
        f"{company}={outcome.value}"
        for company, outcome in outcomes.items()
        if outcome is not SourceOutcome.OK
    )
    if unhealthy:
        note = f"{', '.join(unhealthy)}; " + note
    run.notes = note
    await session.flush()
    await generate_notifications(
        session,
        run,
        include_run=scan_emits_run_notifications(scan_mode),
    )


async def record_run_failure(
    session,
    run_pk: int | None,
    exc: Exception,
    *,
    per_source: dict[str, dict],
    drift_all: list[dict],
    totals: dict[str, int],
    scan_mode: ScanMode,
    outcomes: dict[str, SourceOutcome] | None = None,
) -> None:
    """Record `exc` as the run's terminal state, surviving what it left behind.

    Rolls back, reloads the run by the id read when its marker was committed,
    records the failure with whatever sources had already been recorded,
    notifies, and commits. The caller re-raises the original exception.

    **The status stays a projection of the per-source outcomes**, never
    `error` outright: `run_status_for` defines `error` as "no source produced
    usable data", and `health.REFRESHED_STATUSES` excludes it on exactly that
    reading, so a FATAL POST-PASS failing over healthy sources recorded as
    `error` would freeze `last_success_at`, leave `stale` true, and have
    `should_catch_up` kick another run into the same wall every hour. A
    collection failure still reads `error` because the projection says so, and
    an exception raised before any source was attempted still reads `error`
    because there is no outcome to project (`all([])` is vacuously true, so the
    empty case is answered here rather than inside the projection).

    The exception is not lost by this: it stays in `notes`, the failing pass
    already recorded itself in `derivation_state` (which `stale_derivations`
    reports), and `failure` below carries it to the notification so the feed
    names the derivation instead of blaming the sources.
    """
    # `run_pk` was read when the marker was committed, never here. Reading it
    # ahead of the rollback below is not enough: a failing FATAL
    # post-pass has already rolled the session back (`run_post_passes`
    # does, to record the failure), so `run` is expired by now and
    # `run.id` would raise MissingGreenlet instead of `exc`, leaving the run
    # at "running".
    # Roll back first, for the reason `post_passes.run_post_passes` states in
    # its loop: if `exc` was itself a DB error the session is
    # in a pending-rollback state, and the flush below would raise
    # PendingRollbackError -- masking the real exception AND leaving the
    # run at "running" forever, which is the one status the reconciler
    # cannot distinguish from a live run until it goes stale.
    await session.rollback()
    # Safe: the run marker is committed at open (see `session.add(run)` in
    # `pipeline.run_pipeline`), so the rollback cannot discard it -- it only discards the
    # work this failed run had not committed.
    run = await session.get(ScrapeRun, run_pk) if run_pk is not None else None
    if run is not None:
        run.finished_at = datetime.now(UTC)
        run.status = run_status_for(outcomes.values()) if outcomes else "error"
        run.notes = f"pipeline exception: {describe_exception(exc)}"
        run.per_source = per_source
        run.drift_alerts = drift_all
        run.jobs_seen = totals["seen"]
        run.jobs_new = totals["new"]
        run.jobs_closed = totals["closed"]
        await session.flush()
        await _failure_notification(
            session,
            run,
            include_run=scan_emits_run_notifications(scan_mode),
            failure=describe_exception(exc),
        )
        await _usage_crash(session, exc)
        await session.commit()


async def _failure_notification(session, run, *, include_run: bool, failure: str) -> None:
    """Tell the feed the run failed, in a savepoint, for the reason
    `_usage_crash` gives beside it.

    The fault that killed a run is often a fault that kills this write too. Out
    in the open it would escape past the commit below, leaving the run at
    `running` for the reconciler to find much later, and mask the exception
    that caused it. The record of a failure has to outlive the telling of it.
    The flush above is what makes the savepoint enough: the terminal status is
    already in the transaction, so rolling back to the savepoint cannot take it.
    """
    try:
        async with session.begin_nested():
            await generate_notifications(session, run, include_run=include_run, failure=failure)
    except Exception:  # noqa: BLE001 - the feed never costs the run its record
        logger.warning("could not write the failed run's notification", exc_info=True)


async def _usage_crash(session, exc: Exception) -> None:
    """The run's crash for crash reports (docs/architecture.md), in a
    savepoint: whatever happens here, the failure record above commits."""
    try:
        async with session.begin_nested():
            await record_exception(session, exc, source="pipeline", now=datetime.now(UTC))
    except Exception:  # noqa: BLE001 - a crash report never costs the run its record
        logger.warning("could not record the run's crash for crash reports", exc_info=True)
