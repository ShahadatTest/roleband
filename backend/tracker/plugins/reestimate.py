"""Re-estimate every stored job when the reference set changes.

A job's estimate is a function of its stored fields (company, band, family,
location group, title) and the reference data the resolver reads. When that
data changes, every stored estimate moves at once: a plugin enabled, disabled
or refreshed clean, a core levels refresh, a new atlas edition, a change to
the estimate code. Recorded per job as `changed` events, such a move would flood
the history, so the moves happen together, in batches, and are recorded once,
as one `reference_change` with a moved report.

**The reference fingerprint** is sha256 over:
- `builtin_fingerprint()`: the estimate's own code and the atlas files it reads,
  as shipped, hashed by content, never by a version string;
- the provider set of every slot (readers take every slot from the
  applied set, so a benefits or company-size switch is applied by the same
  flip), with how far each active plugin's coverage reached (the companies read
  whole);
- the exact rows the estimate reads (`pay_level_rows`), so a core-written
  refresh, a retirement or a re-banding moves it too.
The benefits dataset never enters it: benefits never enter an estimate, so a
new benefits edition never re-estimates a job.

**`reestimate`** follows `retention.apply_retention`: each batch commits, with
`take_lock` it takes the run lock per batch and yields to a run that holds it,
and a cursor keyed by the target fingerprint survives a stop (a different
target restarts it). Open and closed jobs alike: lineage diffs compare
reposts. A batch writes only each source's own row (`job_comp_estimate`);
the copy every list, sort and filter reads (`jobs.comp_*`) does not move.
The last batch copies the selected source's rows onto every job, flips
`reference_state.applied_fp`, recomputes today's `comp_metrics` /
`comp_snapshot` and writes the `reference_change`, all in one transaction.
So every reader, a list or a detail, sees the old set or the new
one, never half: a list read mid-switch is all the old source. While a switch
moves, the dashboard says estimates are updating, and
`/api/status.reference.pending_jobs` counts the jobs the batches have not
reached yet.

Four callers, one function: the pipeline before collection and its
`reference` post pass (the run holds the lock: `take_lock=False`), the
scheduler's idle branch (`reestimate_when_idle`), and `reestimate_cli` (the
supervisor's `reestimate` job, and `scripts.reestimate` by hand).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.comp_package import pay_level_index
from tracker.analytics.comp_trends import compute_comp_metrics
from tracker.comp_providers.base import CompContext, CompEstimate
from tracker.comp_providers.static import StaticCompProvider
from tracker.comp_providers.table import ReferenceTableProvider
from tracker.config import get_settings
from tracker.db.models import Job, JobCompEstimate, ReferenceChange, ReferenceState
from tracker.db.queries.reference_pay import pay_level_rows
from tracker.db.session import session_scope
from tracker.enrich.builtin_pay import (
    BuiltinPayProvider,
    build_fingerprint,
    cached_rows,
    index_rows,
)
from tracker.enrich.builtin_pay import Index as BuiltinIndex
from tracker.enrich.comp import OURS, CompResolver, EstimateSet
from tracker.enrich.enricher import ESTIMATE_FIELDS, estimate_values
from tracker.plugins.registry import ESTIMATE_SLOTS, PAY_LEVELS, Providers, load_providers
from tracker.schema import LevelBand
from tracker.taxonomy.locations import pay_country

logger = logging.getLogger(__name__)

#: Jobs one batch recomputes; each batch is its own transaction.
BATCH = 1_000
#: How many times one run follows a target that moved under it before it leaves
#: the rest to the next caller.
MAX_RESTARTS = 3

_TRACKER = Path(__file__).resolve().parents[1]
#: What the estimate reads besides the reference rows and the job: the resolver
#: and its two providers, the rung choice and US-row rule, the family map, the
#: rung pay and labels, and the atlas files behind them. A path that does not
#: exist would silently drop out of the hash, so a test checks each one.
ESTIMATE_SOURCES = (
    "enrich/comp.py",
    "comp_providers/base.py",
    "comp_providers/table.py",
    "comp_providers/static.py",
    "analytics/comp_package.py",
    "analytics/comp_market.py",
    "taxonomy/comp_families.py",
    # Which country a posting's pay is for.
    "taxonomy/locations.py",
    "taxonomy/countries.py",
    "levels/pay.py",
    # The seed rule's ladder and the atlas that loads it, and the read-time banding
    # of a plugin's rows: an edit to any of them moves estimates
    # (`test_reestimate.py` follows the imports).
    "levels/atlas.py",
    # The cell rules the atlas reads its files by.
    "platform/tables.py",
    "levels/ladder.py",
    "levels/model.py",
    "levels/companies.py",
    "levels/words.py",
    "levels/vocabulary.py",
    "db/queries/reference_pay.py",
    "levels/atlas/companies.csv",
    "levels/atlas/ladders.csv",
    "levels/atlas/rungs.csv",
    "levels/atlas/printed.csv",
    "levels/atlas/company_facts.csv",
)

@cache
def builtin_fingerprint() -> str:
    """sha256 over the estimate's code and atlas files (`ESTIMATE_SOURCES`)."""
    digest = hashlib.sha256()
    for entry in ESTIMATE_SOURCES:
        path = _TRACKER / entry
        digest.update(entry.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceInputs:
    """One source's estimate inputs: ours, or the selected plugin's."""

    #: `OURS`, or the plugin's id.
    source: str
    #: sha256 over everything this source's estimate reads: never the other's.
    fingerprint: str
    rows: Sequence[Any]
    #: Our dataset's pay rows, ours only, while `builtin_pay_enabled` is on.
    builtin_pay: BuiltinIndex | None = None

    def resolver(self) -> CompResolver:
        """Ours: our stored rows, then the seed, then (switched on) our dataset's
        base. A plugin's: its rows alone, so a company it has not read has no
        estimate rather than ours."""
        providers: list[Any] = [ReferenceTableProvider(pay_level_index(self.rows))]
        if self.source == OURS:
            providers.append(StaticCompProvider())
            if self.builtin_pay is not None:
                providers.append(BuiltinPayProvider(self.builtin_pay))
        return CompResolver(providers, fingerprint=self.fingerprint)


@dataclass(frozen=True)
class ReferenceInputs:
    """What one reference set is: ours, the selected plugin's, which one a job
    shows, and the projection's fingerprint over all three."""

    fingerprint: str
    #: `Providers.record` for the estimate slots (who answers, how far it read).
    providers: dict[str, Any]
    ours: SourceInputs
    plugin: SourceInputs | None = None

    @property
    def selected(self) -> str:
        return self.plugin.source if self.plugin is not None else OURS

    @property
    def rows(self) -> Sequence[Any]:
        """The rows of the source a job shows."""
        return (self.plugin or self.ours).rows

    def fingerprints(self) -> dict[str, str]:
        out = {OURS: self.ours.fingerprint}
        if self.plugin is not None:
            out[self.plugin.source] = self.plugin.fingerprint
        return out

    def estimate_set(self) -> EstimateSet:
        plugin = (self.plugin.source, self.plugin.resolver()) if self.plugin is not None else None
        return EstimateSet(self.ours.resolver(), plugin, fingerprints=self.fingerprints(),
                           fingerprint=self.fingerprint)

    def resolver(self) -> CompResolver:
        """The resolver of the source a job shows, stamped with the projection's
        fingerprint (bench and script callers that read one figure)."""
        resolver = (self.plugin or self.ours).resolver()
        resolver.fingerprint = self.fingerprint
        return resolver


def _row_key(row: Any) -> tuple:
    return (
        row.company_slug, row.family, row.band, row.level_label,
        row.base_amount, row.currency, row.tc_median, row.provider,
        row.as_of.isoformat() if row.as_of else None, row.country,
    )


def _digest(*parts: Any, rows: Sequence[Any] = ()) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(json.dumps(part, sort_keys=True, default=str).encode())
    for key in sorted(_row_key(r) for r in rows):
        digest.update(json.dumps(key, default=str).encode())
    return digest.hexdigest()


async def reference_inputs(session: AsyncSession, providers: Providers | None = None) -> ReferenceInputs:
    """The CURRENT reference set: where a re-estimate is going.

    Ours reads our stored rows (`CORE_SOURCES`; the seed and our dataset's base
    need no rows) whether or not a plugin is selected; the selected plugin's
    reads its rows for the companies it has read whole. A plugin selected before
    it has read anything moves the projection at once: every job shows its
    (empty) estimate, never ours."""
    providers = providers or await load_providers(session)
    # Every slot: readers take them all from the applied record.
    record = providers.record()
    ours_rows = await pay_level_rows(session, Providers(plugins=providers.plugins))
    builtin_pay = index_rows(cached_rows()) if get_settings().builtin_pay_enabled else None
    if builtin_pay is not None:
        record["builtin_pay"] = build_fingerprint()
    ours = SourceInputs(OURS, _digest(builtin_fingerprint(), record.get("builtin_pay"), rows=ours_rows),
                        ours_rows, builtin_pay)
    plugin = None
    if (pid := providers.source_for(PAY_LEVELS)) is not None:
        plugin_rows = await pay_level_rows(session, providers)
        # How far its coverage reached: each company it reads whole moves it.
        through = record["covered_through"].get(PAY_LEVELS, {}).get(pid)
        plugin = SourceInputs(pid, _digest(pid, through, builtin_fingerprint(), rows=plugin_rows), plugin_rows)
    # Who answers the other slots, and how far it has read, moves the set too: a
    # benefits or company-size switch is applied by the same flip as a pay switch.
    # Left out while ours answers them, so that set's fingerprint is
    # the one it always was.
    others = {slot: [pids, record["covered_through"].get(slot)]
              for slot, pids in record["active"].items() if slot not in ESTIMATE_SLOTS}
    fingerprint = _digest(plugin.source if plugin else OURS, ours.fingerprint, plugin.fingerprint if plugin else None,
                          *((others,) if others else ()))
    return ReferenceInputs(fingerprint=fingerprint, providers=record, ours=ours, plugin=plugin)


async def _state(session: AsyncSession) -> ReferenceState:
    """The one reference-state row, LOCKED until the caller's transaction ends.
    `begin` (a decision, a plugin run closing, a re-estimate) and every
    batch read it and write it back; without the lock a decision landing between a
    batch's read and its commit would be overwritten: its cursor would go onto the
    new target, or the last batch's flip would erase it."""
    await session.execute(insert(ReferenceState).values(id=1).on_conflict_do_nothing(index_elements=["id"]))
    state = await session.get(ReferenceState, 1, populate_existing=True, with_for_update=True)
    assert state is not None
    return state


def _empty_report() -> dict[str, Any]:
    return {"jobs": 0, "moved": 0, "same": 0, "gained": 0, "lost": 0, "companies": {}}


def _shown(pair: tuple) -> tuple | None:
    """The figure a posting shows: its total, else its base; None = none."""
    total, base = pair
    if total is not None:
        return ("total", total)
    if base is not None:
        return ("base", base)
    return None


def _tally(report: dict[str, Any], company: str, before: tuple, after: tuple) -> None:
    """Count one job by the figure it SHOWS, (total, base) -> total else base.
    A base filled in under an unchanged total is no move; a posting that gains
    only a base estimate gained one."""
    report["jobs"] += 1
    shown_before, shown_after = _shown(before), _shown(after)
    if shown_before == shown_after:
        kind = "same"
    elif shown_before is None:
        kind = "gained"
    elif shown_after is None:
        kind = "lost"
    else:
        kind = "moved"
    report[kind] += 1
    if kind != "same":
        companies = report["companies"]
        companies[company] = companies.get(company, 0) + 1


@dataclass
class ReestimateResult:
    target_fp: str
    #: Nothing was due: the applied set is the current one.
    current: bool = False
    #: The last batch ran: `applied_fp` is now `target_fp`.
    applied: bool = False
    #: Jobs whose shown estimate (`jobs.comp_*`) changed or was stamped in this
    #: call: only the last batch writes them.
    written: int = 0
    #: Jobs this call estimated, each source's row written.
    reached: int = 0
    batches: int = 0
    #: The idle caller found a run holding the lock and stopped.
    skipped: bool = False
    change_id: int | None = None
    report: dict[str, Any] = field(default_factory=dict)
    #: The set this call moved to (or found current): read under the lock
    #: unless the caller's own still named it.
    inputs: ReferenceInputs | None = None


async def _estimates(estimates: EstimateSet, job: Any) -> dict[str, dict[str, Any]]:
    """Each source's estimate fields, providers' answers and fingerprint for one
    stored job."""
    try:
        band = LevelBand(job.level_band)
    except ValueError:
        band = None
    answers: dict[str, tuple[CompEstimate | None, list[dict]]]
    if band is None:
        answers = {source: (None, []) for source in estimates.resolvers()}
    else:
        ctx = CompContext(
            company=job.company,
            band=band,
            family=job.family,
            location_group=(job.location_groups or [None])[0],
            country=pay_country(job.location_groups),
            title=job.title,
        )
        answers = await estimates.resolve(ctx)
    return {
        source: {**estimate_values(est), "sources": answered, "ref_fp": estimates.fingerprints.get(source)}
        for source, (est, answered) in answers.items()
    }


async def _show(session: AsyncSession, selected: str, target: str, ids: Sequence[int] | None = None) -> int:
    """Copy the selected source's row onto every job whose copy differs from it
    or is not stamped `target`: the one move a list sees. A job with
    no row for that source shows nothing, never another source's figure.
    `ids`: only these jobs (`refresh_jobs`). Returns the jobs written."""
    only = (Job.id.in_(ids),) if ids is not None else ()
    stale = Job.comp_ref_fp.is_distinct_from(target)
    copied = await session.execute(
        update(Job)
        .where(JobCompEstimate.job_id == Job.id, JobCompEstimate.source == selected, *only,
               or_(stale, *[getattr(Job, k).is_distinct_from(getattr(JobCompEstimate, k)) for k in ESTIMATE_FIELDS]))
        .values(comp_ref_fp=target, **{k: getattr(JobCompEstimate, k) for k in ESTIMATE_FIELDS})
        .execution_options(synchronize_session=False)
    )
    empty = estimate_values(None)
    cleared = await session.execute(
        update(Job)
        .where(~exists().where(JobCompEstimate.job_id == Job.id, JobCompEstimate.source == selected), *only,
               or_(stale, *[getattr(Job, k).is_distinct_from(v) for k, v in empty.items()]))
        .values(comp_ref_fp=target, **empty)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(copied, "rowcount", 0) or 0) + int(getattr(cleared, "rowcount", 0) or 0)


async def refresh_jobs(session: AsyncSession, job_ids: Iterable[int]) -> int:
    """Re-estimate jobs whose OWN inputs moved outside a scan: the level
    backfill, the role reclassify, a held row's fresh read. The fingerprint names
    what every estimate reads, never a job's own fields, so nothing else moved
    them. Commits nothing: the pass that moved them owns the transaction; the
    reference row stays locked until it commits.

    Under the set that applies to the job now: settled, its rows and the list's
    copy; moving, the target's rows of the jobs the move has passed (the flip
    copies them; the move reaches the rest); the current set past both, nothing
    (the re-estimate that follows recomputes every job). Returns the jobs
    estimated."""
    ids = sorted(set(job_ids))
    if not ids:
        return 0
    state = await _state(session)
    inputs = await reference_inputs(session)
    moving = state.target_fp is not None
    if inputs.fingerprint != (state.target_fp if moving else state.applied_fp):
        return 0
    if moving:
        ids = [i for i in ids if i <= (state.cursor_job_id or 0)]
        if not ids:
            return 0
    estimates = inputs.estimate_set()
    jobs = (await session.execute(
        select(Job.id, Job.company, Job.level_band, Job.family, Job.location_groups, Job.title)
        .where(Job.id.in_(ids))
    )).all()
    rows: list[dict[str, Any]] = []
    for job in jobs:
        by_source = await _estimates(estimates, job)
        rows.extend({"job_id": job.id, "source": source, **fields} for source, fields in by_source.items())
    await _store(session, rows)
    if not moving:
        await _show(session, estimates.selected, inputs.fingerprint, ids=[job.id for job in jobs])
    return len(jobs)


async def _store(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Upsert each source's estimate per job (`job_comp_estimate`)."""
    if not rows:
        return
    stmt = pg_insert(JobCompEstimate).values(rows)
    columns = [*ESTIMATE_FIELDS, "sources", "ref_fp"]
    await session.execute(stmt.on_conflict_do_update(
        index_elements=["job_id", "source"],
        set_={**{c: stmt.excluded[c] for c in columns}, "estimated_at": func.now()},
    ))


async def begin(session: AsyncSession, inputs: ReferenceInputs | None = None) -> bool:
    """Record where the stored estimates are going and say whether they must move;
    commits. A switch is due while the current set is not the applied one, or a
    move is still under way (the target is kept, with its cursor, unless the
    current set moved again, which restarts it).

    The re-estimate calls it first; a user's decision (`lifecycle`) calls it at
    once, so `/api/status.reference` says estimates are updating from that moment,
    not only once the detached re-estimate it spawns has started; and
    a plugin run that published calls it as it closes (`host`), so its rows read
    as pending until the idle re-estimate applies them."""
    moving, _ = await _begin(session, inputs)
    return moving


async def _begin(session: AsyncSession, inputs: ReferenceInputs | None) -> tuple[bool, ReferenceInputs]:
    """`begin`, also returning the inputs the stored estimates go to.

    A new target is recorded only from inputs read under the row's lock.
    Inputs read before it may predate a decision that committed
    meanwhile, and would replace that decision's target with the older set, then
    apply it. They are trusted only where they write nothing: they name the
    target already recorded (a resumed move) or, with none recorded, the applied
    set. Any other case reads the set again, inside the lock, where every
    decision before it has committed and every one after it waits."""
    state = await _state(session)
    trusted = inputs is not None and (
        inputs.fingerprint == state.target_fp
        or (state.target_fp is None and inputs.fingerprint == state.applied_fp)
    )
    if not trusted:
        inputs = await reference_inputs(session)
    assert inputs is not None
    target = inputs.fingerprint
    if state.applied_fp == target and state.target_fp is None:
        await session.commit()
        return False, inputs
    if state.target_fp != target:
        state.target_fp = target
        state.target_providers = inputs.providers
        state.target_report = _empty_report()
        state.cursor_job_id = 0
    await session.commit()
    return True, inputs


#: How often a waiting caller asks for the run lock again.
_LOCK_POLL_SECONDS = 1.0


async def _try_lock(session: AsyncSession, wait: float = 0.0) -> bool:
    """The run lock for this transaction. `wait` > 0: ask again until it is free
    or `wait` seconds have passed (each failed ask ends its transaction, so the
    caller holds nothing while it waits)."""
    deadline = time.monotonic() + wait
    while True:
        if await session.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"),
                                {"k": get_settings().advisory_lock_key}):
            return True
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        await session.rollback()
        await asyncio.sleep(min(_LOCK_POLL_SECONDS, left))


async def reestimate(
    session: AsyncSession,
    *,
    take_lock: bool = False,
    lock_wait: float = 0.0,
    batch: int = BATCH,
    max_batches: int | None = None,
    inputs: ReferenceInputs | None = None,
) -> ReestimateResult:
    """Bring every stored estimate to the current reference set; commits each batch.

    `take_lock`: take the run lock for each batch's transaction and stop when a
    run holds it. A caller inside a run passes False: the run holds it.
    `lock_wait`: with `take_lock`, wait up to this many seconds for each batch's
    lock before stopping (the follower a decision spawns); 0 asks once.
    `inputs`: a set the caller read; used only where it is still the recorded
    one, else read again under the lock (`_begin`). `result.inputs` is the set
    this call moved to: a caller that estimates beside it uses that one.
    `max_batches`: stop after this many and leave the rest, resumable, to the
    next caller."""
    moving, inputs = await _begin(session, inputs)
    target = inputs.fingerprint
    result = ReestimateResult(target_fp=target, inputs=inputs)
    if not moving:
        result.current = True
        return result

    estimates = inputs.estimate_set()
    restarts = 0
    while max_batches is None or result.batches < max_batches:
        if take_lock and not await _try_lock(session, lock_wait):
            await session.rollback()
            result.skipped = True
            return result
        state = await _state(session)
        if state.target_fp != target:
            # The set moved since this run read it (a decision, a plugin run): the
            # newer target wins, and this run carries on to it rather than stop
            # with the switch half done. Bounded, so a set that keeps
            # moving is left to the next caller.
            await session.rollback()
            restarts += 1
            if restarts > MAX_RESTARTS:
                result.skipped = True
                return result
            moving, inputs = await _begin(session, None)
            target = inputs.fingerprint
            result.target_fp, result.inputs = target, inputs
            if not moving:
                result.current = True
                return result
            estimates = inputs.estimate_set()
            continue
        cursor = state.cursor_job_id or 0
        jobs = (
            await session.execute(
                select(
                    Job.id, Job.company, Job.level_band, Job.family, Job.location_groups, Job.title,
                    Job.comp_median, Job.comp_base_median,
                )
                .where(Job.id > cursor)
                .order_by(Job.id)
                .limit(batch)
            )
        ).all()
        report = dict(state.target_report or _empty_report())
        report["companies"] = dict(report.get("companies") or {})
        rows: list[dict[str, Any]] = []
        for job in jobs:
            by_source = await _estimates(estimates, job)
            rows.extend({"job_id": job.id, "source": source, **fields} for source, fields in by_source.items())
            # Counted against what the job shows now, which no batch moves: the
            # copy moves for every job at once, in the last batch.
            shown = by_source[estimates.selected]
            _tally(report, job.company, (job.comp_median, job.comp_base_median),
                   (shown["comp_median"], shown["comp_base_median"]))
        await _store(session, rows)
        result.reached += len(jobs)
        result.batches += 1
        last = len(jobs) < batch
        if jobs:
            state.cursor_job_id = jobs[-1].id
        state.target_report = report
        if last:
            # Every job takes the selected source's row in the transaction that
            # flips the applied set: a reader sees one source or the other.
            result.written += await _show(session, estimates.selected, target)
            change = ReferenceChange(
                at=datetime.now(UTC),
                from_fp=state.applied_fp,
                to_fp=target,
                providers=state.target_providers or inputs.providers,
                moved_report=report,
            )
            session.add(change)
            await session.flush()
            state.applied_fp = target
            state.applied_providers = state.target_providers or inputs.providers
            state.target_fp = None
            state.target_providers = {}
            state.target_report = {}
            state.cursor_job_id = None
            state.last_change_id = change.id
            await compute_comp_metrics(session)
            await session.commit()
            result.applied = True
            result.change_id = change.id
            result.report = report
            logger.info(
                "reestimate: applied %s (%d jobs, %d moved, %d gained, %d lost)",
                target[:12], report["jobs"], report["moved"], report["gained"], report["lost"],
            )
            return result
        await session.commit()
    return result


async def pending_jobs(session: AsyncSession) -> int:
    """Jobs a re-estimate still has to reach: past its cursor while one is
    moving (no job's shown copy moves before the last batch), else not under
    the applied fingerprint."""
    state = await session.get(ReferenceState, 1)
    query = select(func.count()).select_from(Job)
    if state is not None and state.target_fp is not None:
        query = query.where(Job.id > (state.cursor_job_id or 0))
    elif state is not None and state.applied_fp:
        query = query.where(Job.comp_ref_fp.is_distinct_from(state.applied_fp))
    return int(await session.scalar(query) or 0)


async def reestimate_when_idle() -> ReestimateResult:
    """The scheduler tick's call when no work is due: its own session, the run
    lock taken per batch."""
    async with session_scope() as session:
        return await reestimate(session, take_lock=True)
