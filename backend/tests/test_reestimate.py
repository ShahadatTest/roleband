"""Stored estimates move together, once, when the reference set changes.

The contract: after `reestimate`, every stored job (open and closed) carries
exactly the estimate the pipeline would compute for it now, stamped with the
current reference fingerprint; the move is recorded as ONE `reference_change`
with a moved report; batches are resumable and restart on a new target; the
run lock is respected; readers keep the applied set until the last batch; and
`upsert_job` records a `comp_median` move as a per-job event only when the
stored and new estimates share a fingerprint.

Side by side: every job keeps OUR estimate, from our data only, and
while a plugin is selected that plugin's, from its rows only; `jobs.comp_*` is
the selected one's copy. A company the plugin has not read shows no estimate,
never ours, and our stored estimate is value-identical through on, off and on.

Figures are distinct per provider (core 300k, plugin 999k), so a reader or a
re-estimate that takes the wrong set shows it in the number.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from tests.plugin_seed import cover
from tracker.comp_providers.base import BUILTIN
from tracker.config import get_settings
from tracker.db.models import (
    CompanyCompLevel,
    CompanyProfile,
    CompMetric,
    Job,
    JobCompEstimate,
    JobLifecycleEvent,
    PluginInstall,
    ReferenceChange,
    ReferenceState,
)
from tracker.db.queries.reference_pay import pay_level_rows
from tracker.db.repo import upsert_job
from tracker.enrich.enricher import Annotation, build_enriched
from tracker.plugins import reestimate as reestimate_module
from tracker.plugins.reestimate import (
    ESTIMATE_SOURCES,
    builtin_fingerprint,
    pending_jobs,
    reestimate,
    reference_inputs,
)
from tracker.plugins.registry import PAY_LEVELS, reader_providers
from tracker.schema import LevelBand, LevelConfidence, RawJob, RoleTrack
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

AT = datetime(2026, 10, 1, tzinfo=UTC)
CORE = dict(family=REFERENCE_FAMILY, provider="manual", fetched_at=AT)


async def _seed(db, *, jobs: int = 3, closed: int = 1) -> list[int]:
    db.add_all([CompanyProfile(slug="acme", display_name="Acme"), CompanyProfile(slug="globex", display_name="Globex")])
    await db.flush()
    db.add_all([
        CompanyCompLevel(company_slug="acme", level_label="L5", band="senior", tc_median=300_000, base_amount=200_000, **CORE),
        CompanyCompLevel(company_slug="globex", level_label="G5", band="senior", tc_median=250_000, base_amount=180_000,
                         **CORE),
    ])
    ids = []
    for i in range(jobs + closed):
        company = "acme" if i % 2 == 0 else "globex"
        job = Job(company=company, req_id=str(i), dedupe_key=f"{company}:{i}", title="Senior Software Engineer",
                  url=f"https://example.com/{i}", level_band="senior", family=None, location_groups=["silicon_valley"],
                  status="closed" if i >= jobs else "open", comp_median=None)
        db.add(job)
        await db.flush()
        ids.append(job.id)
    # One posting below the comp floor: no estimate, still stamped.
    db.add(Job(company="acme", req_id="mid", dedupe_key="acme:mid", title="Software Engineer",
               url="https://example.com/mid", level_band="mid", family=None, location_groups=["silicon_valley"]))
    await db.commit()
    return ids


async def _install_plugin(db, *, clean: bool = True) -> None:
    db.add(PluginInstall(
        plugin_id="tpl", name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": [{"slot": PAY_LEVELS}]}, fingerprint="fp1", approved_fingerprint="fp1", enabled=True,
    ))
    await db.flush()
    # As a plugin sends it: no band; our reading places "Senior Engineer" at senior when read.
    db.add(CompanyCompLevel(company_slug="acme", family=REFERENCE_FAMILY, level_label="Senior Engineer",
                            band=None, tc_median=999_000, base_amount=600_000, provider="tpl",
                            country="US", fetched_at=AT))
    if clean:
        cover(db, "tpl", (PAY_LEVELS,), ("acme",))
    await db.commit()


async def _medians(db) -> dict[str, int | None]:
    rows = (await db.execute(select(Job.dedupe_key, Job.comp_median).order_by(Job.id))).all()
    return dict(rows)


async def _estimates(db, source: str) -> dict[int, tuple]:
    rows = (await db.execute(select(JobCompEstimate).where(JobCompEstimate.source == source))).scalars().all()
    return {r.job_id: (r.comp_low, r.comp_median, r.comp_high, r.comp_base_median, r.comp_provider) for r in rows}


async def _changes(db) -> list[ReferenceChange]:
    return list((await db.execute(select(ReferenceChange).order_by(ReferenceChange.id))).scalars())


def _annotation(job: Job) -> Annotation:
    return Annotation(band=LevelBand(job.level_band), confidence=LevelConfidence.CONFIRMED, family=job.family,
                      location_groups=list(job.location_groups), track=RoleTrack.TECHNICAL, domains=[], basis=None)


# --------------------------------------------------------------------------- #
# The move
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_every_job_takes_the_estimate_the_pipeline_would_compute(db_session):
    await _seed(db_session)
    result = await reestimate(db_session)
    assert result.applied and not result.current

    inputs = await reference_inputs(db_session)
    resolver = inputs.resolver()
    jobs = (await db_session.execute(select(Job).order_by(Job.id))).scalars().all()
    for job in jobs:
        raw = RawJob(company=job.company, req_id=job.req_id, title=job.title, url=job.url, locations=[])
        expected = await build_enriched(raw, _annotation(job), resolver)
        assert (job.comp_low, job.comp_median, job.comp_high) == (
            expected.comp_low, expected.comp_median, expected.comp_high), job.dedupe_key
        assert job.comp_ref_fp == inputs.fingerprint == expected.comp_ref_fp
    by_key = {j.dedupe_key: j for j in jobs}
    # Open and closed alike; the core figure, its base, its provider.
    assert by_key["acme:0"].comp_median == 300_000 and by_key["acme:2"].comp_median == 300_000
    assert by_key["globex:3"].status == "closed" and by_key["globex:3"].comp_median == 250_000
    assert by_key["acme:0"].comp_base_median == 200_000
    assert by_key["acme:0"].comp_component == "total"
    assert by_key["acme:0"].comp_provider == "manual"
    # Below Senior: no estimate, never a fabricated one, but stamped.
    mid = by_key["acme:mid"]
    assert mid.comp_median is None and mid.comp_component is None and mid.comp_ref_fp == inputs.fingerprint


@pytest.mark.asyncio
async def test_one_reference_change_records_the_move_and_a_second_call_is_a_no_op(db_session):
    await _seed(db_session)
    first = await reestimate(db_session)
    changes = await _changes(db_session)
    assert len(changes) == 1 and changes[0].from_fp is None and changes[0].to_fp == first.target_fp
    report = changes[0].moved_report
    assert report["jobs"] == 5 and report["gained"] == 4 and report["same"] == 1
    assert report["companies"] == {"acme": 2, "globex": 2}
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    assert state.applied_fp == first.target_fp and state.last_change_id == changes[0].id
    assert state.target_fp is None and state.cursor_job_id is None

    second = await reestimate(db_session)
    assert second.current and second.written == 0
    assert len(await _changes(db_session)) == 1
    assert await pending_jobs(db_session) == 0


@pytest.mark.asyncio
async def test_a_changed_reference_row_moves_exactly_its_jobs_in_one_change(db_session):
    await _seed(db_session)
    first = await reestimate(db_session)
    await db_session.execute(update(CompanyCompLevel).where(CompanyCompLevel.company_slug == "acme")
                             .values(tc_median=330_000))
    await db_session.commit()
    second = await reestimate(db_session)
    assert second.target_fp != first.target_fp and second.applied
    medians = await _medians(db_session)
    assert medians["acme:0"] == 330_000 and medians["acme:2"] == 330_000 and medians["globex:1"] == 250_000
    changes = await _changes(db_session)
    assert len(changes) == 2 and changes[1].from_fp == first.target_fp
    assert changes[1].moved_report["moved"] == 2 and changes[1].moved_report["companies"] == {"acme": 2}
    # Only the moved jobs and none other were rewritten beyond the stamp.
    assert second.written == 5  # every job takes the new fingerprint


@pytest.mark.asyncio
async def test_enable_and_disable_a_plugin_switch_and_restore_the_same_figures(db_session):
    await _seed(db_session)
    await reestimate(db_session)
    before = await _medians(db_session)
    ours = await _estimates(db_session, "roleband")
    assert len(ours) == 5 and await _estimates(db_session, "tpl") == {}

    await _install_plugin(db_session)
    enabled = await reestimate(db_session)
    on = await _medians(db_session)
    # The plugin's figure where it read the company; nothing, never ours, where it did not.
    assert on["acme:0"] == 999_000 and on["globex:1"] is None
    acme = (await db_session.execute(select(Job).where(Job.dedupe_key == "acme:0"))).scalar_one()
    await db_session.refresh(acme)
    assert acme.comp_provider == "tpl" and acme.comp_base_median == 600_000
    assert (await _changes(db_session))[-1].providers["active"] == {PAY_LEVELS: ["tpl"]}
    # Ours is still stored beside it, untouched by the plugin's rows.
    assert await _estimates(db_session, "roleband") == ours
    assert {median for _, median, *_ in (await _estimates(db_session, "tpl")).values()} == {999_000, None}

    await db_session.execute(update(PluginInstall).values(enabled=False))
    await db_session.commit()
    disabled = await reestimate(db_session)
    assert disabled.target_fp != enabled.target_fp
    assert await _medians(db_session) == before
    assert await _estimates(db_session, "roleband") == ours

    await db_session.execute(update(PluginInstall).values(enabled=True))
    await db_session.commit()
    again = await reestimate(db_session)
    assert again.target_fp == enabled.target_fp  # same run, same rows: same set
    assert await _medians(db_session) == on
    assert await _estimates(db_session, "roleband") == ours


@pytest.mark.asyncio
async def test_a_plugin_selected_before_it_reads_anything_shows_no_estimate_and_ours_stays_stored(db_session):
    """On means on. Before its first read every job shows the
    plugin's (empty) estimate, never ours, and ours is kept, unchanged."""
    await _seed(db_session)
    first = await reestimate(db_session)
    ours = await _estimates(db_session, "roleband")
    await _install_plugin(db_session, clean=False)
    moved = await reestimate(db_session)
    assert moved.applied and moved.target_fp != first.target_fp
    assert set((await _medians(db_session)).values()) == {None}
    assert await _estimates(db_session, "roleband") == ours


# --------------------------------------------------------------------------- #
# Batches, cursor, lock
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_batches_resume_and_readers_keep_the_applied_set_until_the_last(db_session):
    await _seed(db_session)
    await reestimate(db_session)
    shown = await _medians(db_session)
    await _install_plugin(db_session)

    partial = await reestimate(db_session, batch=2, max_batches=1)
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    assert state.target_fp == partial.target_fp and state.cursor_job_id is not None
    # Mid-switch, every pay reader still reads the applied set: no plugin rows,
    # and no job's shown copy moved, though the first two have the plugin's row
    # stored beside ours.
    rows = await pay_level_rows(db_session, await reader_providers(db_session))
    assert {r.tc_median for r in rows} == {300_000, 250_000}
    assert await _medians(db_session) == shown
    assert 999_000 in {median for _, median, *_ in (await _estimates(db_session, "tpl")).values()}
    assert await pending_jobs(db_session) == 3
    assert not partial.applied and (partial.reached, partial.written) == (2, 0)

    rest = await reestimate(db_session, batch=2)
    assert rest.applied and rest.target_fp == partial.target_fp
    # The last batch moved every job's copy at once: both acme figures and the
    # stamp of the three others.
    assert rest.written == 5 and await pending_jobs(db_session) == 0
    assert (await _medians(db_session))["acme:0"] == 999_000
    report = (await _changes(db_session))[-1].moved_report
    # Counted once across both calls: acme's two move to the plugin's figure,
    # globex's two lose theirs (the plugin has not read globex).
    assert (report["jobs"], report["moved"], report["lost"]) == (5, 2, 2)
    rows = await pay_level_rows(db_session, await reader_providers(db_session))
    assert 999_000 in {r.tc_median for r in rows}


@pytest.mark.asyncio
async def test_a_new_target_restarts_the_cursor(db_session):
    await _seed(db_session)
    await reestimate(db_session)
    await _install_plugin(db_session)
    partial = await reestimate(db_session, batch=2, max_batches=1)
    await db_session.execute(update(CompanyCompLevel).where(CompanyCompLevel.provider == "tpl")
                             .values(tc_median=888_000))
    await db_session.commit()
    final = await reestimate(db_session, batch=2)
    assert final.target_fp != partial.target_fp and final.applied
    medians = await _medians(db_session)
    assert medians["acme:0"] == 888_000 and medians["acme:2"] == 888_000
    stamped = await db_session.scalar(select(func.count()).select_from(Job).where(Job.comp_ref_fp == final.target_fp))
    assert stamped == 5
    assert (await _changes(db_session))[-1].moved_report["jobs"] == 5


@pytest.mark.asyncio
async def test_the_idle_caller_yields_to_a_run_holding_the_lock(db_session):
    await _seed(db_session)
    engine = create_async_engine(db_session.bind.url)
    try:
        async with engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": get_settings().advisory_lock_key})
            result = await reestimate(db_session, take_lock=True)
            assert result.skipped and result.written == 0
            assert await db_session.scalar(select(func.count()).select_from(ReferenceChange)) == 0
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": get_settings().advisory_lock_key})
    finally:
        await engine.dispose()
    assert (await reestimate(db_session, take_lock=True)).applied


@pytest.mark.asyncio
async def test_the_last_batch_recomputes_today_s_pay_statistics(db_session):
    await _seed(db_session)
    assert await db_session.scalar(select(func.count()).select_from(CompMetric)) == 0
    await reestimate(db_session)
    assert await db_session.scalar(select(func.count()).select_from(CompMetric)) > 0


# --------------------------------------------------------------------------- #
# Event gating
# --------------------------------------------------------------------------- #


def _enriched(job: Job, median: int, fp: str | None):
    from tests.factories import make_enriched

    e = make_enriched(company=job.company, req_id=job.req_id, title=job.title, family=job.family,
                      level_band=LevelBand(job.level_band), comp_median=median)
    e.comp_ref_fp = fp
    return e


class _Session:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, *_a, **_k) -> None:
        return None


def _stored(fp: str | None) -> Job:
    return Job(id=1, company="acme", req_id="1", dedupe_key="acme:1", title="Staff Software Engineer",
               url="https://example.com/1", status="open", level_band="staff", family="swe", comp_median=500_000,
               comp_ref_fp=fp, first_seen=AT, last_seen=AT, total_days_open=0, repost_count=0)


def _comp_events(session: _Session) -> list[dict]:
    return [{"comp_median": e.detail["comp_median"]} for e in session.added
            if isinstance(e, JobLifecycleEvent) and e.event_type == "changed" and "comp_median" in e.detail]


@pytest.mark.asyncio
async def test_a_move_under_the_same_fingerprint_is_an_event_about_the_job():
    session, job = _Session(), _stored("fpA")
    await upsert_job(session, SimpleNamespace(id=7), _enriched(job, 520_000, "fpA"), {"acme:1": job})
    assert _comp_events(session) == [{"comp_median": {"from": 500_000, "to": 520_000}}]
    assert job.comp_ref_fp == "fpA"


@pytest.mark.asyncio
async def test_a_move_from_a_reference_switch_is_never_a_per_job_event():
    session, job = _Session(), _stored("fpA")
    await upsert_job(session, SimpleNamespace(id=7), _enriched(job, 999_000, "fpB"), {"acme:1": job})
    assert _comp_events(session) == []
    assert job.comp_median == 999_000 and job.comp_ref_fp == "fpB"


# --------------------------------------------------------------------------- #
# The fingerprint
# --------------------------------------------------------------------------- #


def test_every_estimate_source_exists():
    root = reestimate_module._TRACKER
    missing = [entry for entry in ESTIMATE_SOURCES if not (root / entry).is_file()]
    assert missing == []


def test_the_builtin_fingerprint_moves_with_an_atlas_rung_edit(tmp_path, monkeypatch):
    root = reestimate_module._TRACKER
    for entry in ESTIMATE_SOURCES:
        (tmp_path / entry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / entry, tmp_path / entry)
    monkeypatch.setattr(reestimate_module, "_TRACKER", tmp_path)
    builtin_fingerprint.cache_clear()
    try:
        before = builtin_fingerprint()
        rungs = tmp_path / "levels/atlas/rungs.csv"
        rungs.write_text(rungs.read_text() + "\n")
        builtin_fingerprint.cache_clear()
        assert builtin_fingerprint() != before
    finally:
        builtin_fingerprint.cache_clear()


def test_the_benefits_dataset_never_enters_the_estimate_fingerprint():
    assert not any("benefits" in entry for entry in ESTIMATE_SOURCES)


@pytest.mark.asyncio
async def test_the_static_seed_answers_as_builtin(db_session):
    """No stored row for google: the atlas seed prices its Staff rung (644k)."""
    db_session.add(Job(company="google", req_id="1", dedupe_key="google:1", title="Staff Software Engineer",
                       url="https://example.com/g", level_band="staff", family=None, location_groups=["silicon_valley"]))
    await db_session.commit()
    await reestimate(db_session)
    job = (await db_session.execute(select(Job))).scalar_one()
    assert job.comp_median == 644_000
    assert job.comp_provider == BUILTIN and job.comp_component == "total"



@pytest.mark.asyncio
async def test_a_base_filled_in_under_an_unchanged_total_is_not_a_move(db_session):
    """Fails "every newly filled base is a move"."""
    await _seed(db_session)
    await reestimate(db_session)
    await db_session.execute(update(Job).values(comp_base_median=None, comp_base_low=None, comp_base_high=None,
                                                comp_ref_fp=None))
    await db_session.execute(update(CompanyCompLevel).values(base_amount=210_000))  # the rows change: a new target
    await db_session.commit()
    result = await reestimate(db_session)
    assert result.applied
    assert result.report["moved"] == 0 and result.report["same"] == 5


@pytest.mark.asyncio
async def test_each_company_a_plugin_reads_whole_moves_the_reference_set(db_session):
    """Not a whole pass: one more company read whole is a new
    reference set, so the stored estimates follow it at the next re-estimate."""
    await _seed(db_session)
    await _install_plugin(db_session)
    before = (await reference_inputs(db_session)).fingerprint
    cover(db_session, "tpl", (PAY_LEVELS,), ("globex",), at=AT + timedelta(hours=1))
    await db_session.commit()
    assert (await reference_inputs(db_session)).fingerprint != before


# --------------------------------------------------------------------------- #
# A decision that lands while a batch is moving
# --------------------------------------------------------------------------- #


async def _in_other_session(db_url, decide) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    engine = create_async_engine(db_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as other:
            await decide(other)
    finally:
        await engine.dispose()


def _decide_mid_batch(monkeypatch, db_session, decide) -> list:
    """Start `decide(other_session)` inside the re-estimate's first batch (after
    the batch read the reference state, before it commits) and hold the batch
    open until the decision either waits on a lock the batch's transaction
    holds or has finished. With a lock on that row the decision goes through
    once the batch commits; without one it lands inside the batch. Ordered by
    the database's own lock wait, never by a timer, so a slow decision holds
    the batch instead of missing it. The test awaits the returned task."""
    import asyncio

    bound = 60.0
    real = reestimate_module._estimates
    tasks: list = []
    decider: list[int] = []

    async def deciding(other):
        # Its engine pools this one connection, so the pid outlives the decision's commit.
        decider.append(await other.scalar(text("SELECT pg_backend_pid()")))
        await decide(other)

    async def held(decision, run_pid):
        engine = create_async_engine(db_session.bind.url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as watcher:
                while not decision.done():
                    if decider and await watcher.scalar(text("SELECT :run = ANY(pg_blocking_pids(:decider))"),
                                                        {"run": run_pid, "decider": decider[0]}):
                        return
                    await asyncio.wait({decision}, timeout=0.01)
        finally:
            await engine.dispose()

    async def wrapped(estimates, job):
        if not tasks:
            run_pid = await db_session.scalar(text("SELECT pg_backend_pid()"))
            tasks.append(asyncio.create_task(_in_other_session(db_session.bind.url, deciding)))
            try:
                await asyncio.wait_for(held(tasks[0], run_pid), bound)
            except TimeoutError:
                tasks[0].cancel()
                pytest.fail(f"the decision neither waited on the batch nor finished within {bound:.0f} s")
        return await real(estimates, job)

    monkeypatch.setattr(reestimate_module, "_estimates", wrapped)
    return tasks


def _decide_between_batches(monkeypatch, db_session, decide) -> list:
    """Run `decide(other_session)` to its end after the re-estimate's first batch
    commits and before the next batch reads the reference state: the point a
    decision started during a batch reaches once the row lock lets it through.
    Ordered by the run's own steps, never by a timer, so a slow decision delays
    the run instead of missing it. The returned list is non-empty once it ran."""
    real_state, real_estimates = reestimate_module._state, reestimate_module._estimates
    estimated: list[bool] = []
    decided: list[bool] = []

    async def estimating(estimates, job):
        estimated.append(True)
        return await real_estimates(estimates, job)

    async def reading_state(session):
        # The run's session only: the decision's `begin` reads the row too. The
        # first read after a batch estimated is the next batch's, past the commit.
        if session is db_session and estimated and not decided:
            decided.append(True)
            await _in_other_session(db_session.bind.url, decide)
        return await real_state(session)

    monkeypatch.setattr(reestimate_module, "_estimates", estimating)
    monkeypatch.setattr(reestimate_module, "_state", reading_state)
    return decided


@pytest.mark.asyncio
async def test_a_decision_during_a_batch_never_keeps_the_batch_s_cursor(db_session, monkeypatch):
    """The plugin re-publishes at 888k and a decision records that target while a
    batch of the move to its 999k is computing. A batch cursor that lands on the
    new target would leave the jobs before it at 999k under the new fingerprint:
    one company, two plugin publishes, one applied set."""
    await _seed(db_session)
    await reestimate(db_session)
    await _install_plugin(db_session)

    async def republish(other):
        await other.execute(update(CompanyCompLevel).where(CompanyCompLevel.provider == "tpl")
                            .values(tc_median=888_000))
        await other.commit()
        await reestimate_module.begin(other)

    tasks = _decide_mid_batch(monkeypatch, db_session, republish)
    await reestimate(db_session, batch=2)
    await tasks[0]
    monkeypatch.undo()
    await reestimate(db_session, batch=2)
    medians = await _medians(db_session)
    assert (medians["acme:0"], medians["acme:2"]) == (888_000, 888_000), medians
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    assert state.target_fp is None and state.applied_fp == (await reference_inputs(db_session)).fingerprint


@pytest.mark.asyncio
async def test_turning_a_plugin_off_during_the_last_batch_is_never_erased(db_session, monkeypatch):
    """A last batch's flip that wrote over the target the turn-off recorded
    would leave the plugin answering app-wide, nothing saying updating, and
    Remove data refused, until some later tick."""
    await _seed(db_session)
    await reestimate(db_session)
    await _install_plugin(db_session)

    async def turn_off(other):
        await other.execute(update(PluginInstall).values(enabled=False))
        await other.commit()
        await reestimate_module.begin(other)

    tasks = _decide_mid_batch(monkeypatch, db_session, turn_off)
    await reestimate(db_session)
    await tasks[0]
    monkeypatch.undo()
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    current = (await reference_inputs(db_session)).fingerprint
    assert state.target_fp == current != state.applied_fp, "the turn-off's target stands: estimates read as moving"
    assert (await reestimate(db_session)).applied
    assert (await _medians(db_session))["acme:0"] == 300_000, "ours again"


@pytest.mark.asyncio
async def test_a_run_whose_target_moved_carries_on_to_the_new_one(db_session, monkeypatch):
    """A run that finds a newer target between its batches re-reads the set and
    moves to it, in the same call, instead of stopping with the switch half done
    (the follow-up the decision spawns finds the run lock held and stops too)."""
    await _seed(db_session)
    await reestimate(db_session)
    await _install_plugin(db_session)

    async def republish(other):
        await other.execute(update(CompanyCompLevel).where(CompanyCompLevel.provider == "tpl")
                            .values(tc_median=777_000))
        await other.commit()
        await reestimate_module.begin(other)

    decided = _decide_between_batches(monkeypatch, db_session, republish)
    result = await reestimate(db_session, batch=2)

    assert decided, "the decision landed between two batches of the run"
    assert result.applied and not result.skipped, "one call reaches the newer target"
    medians = await _medians(db_session)
    assert (medians["acme:0"], medians["acme:2"]) == (777_000, 777_000), medians


@pytest.mark.asyncio
async def test_inputs_read_before_a_decision_never_replace_its_target(db_session):
    """A caller that read the reference set before a decision committed (the
    pipeline before collection, any caller between its read and the lock) must
    not record that older set over the decision's target. Applied, it would
    leave the plugin just turned on answering nothing, and the status saying
    settled until some later caller noticed."""
    await _seed(db_session)
    await reestimate(db_session)
    stale = await reference_inputs(db_session)
    await _install_plugin(db_session)
    assert await reestimate_module.begin(db_session), "the decision records its target"

    result = await reestimate(db_session, inputs=stale)
    current = (await reference_inputs(db_session)).fingerprint
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    assert result.applied and (state.applied_fp, state.target_fp) == (current, None)
    assert result.inputs.fingerprint == current, "the caller estimates under the set it applied"
    assert (await _medians(db_session))["acme:0"] == 999_000


@pytest.mark.asyncio
async def test_the_follower_waits_for_the_run_lock_within_its_bound(db_session, monkeypatch):
    """The re-estimate a decision spawns waits for a run holding the lock instead
    of trying once, which with no scheduler would leave the switch unfinished.
    Past its bound it still stops, leaving the move to the next caller.

    The follower asks with `pg_try_advisory_xact_lock`, which never queues, so
    there is no lock wait to see. Its signal is a second refused ask: it was
    turned away and asked again rather than giving up."""
    import asyncio

    await _seed(db_session)
    key = {"k": get_settings().advisory_lock_key}
    monkeypatch.setattr(reestimate_module, "_LOCK_POLL_SECONDS", 0.05)
    refused: list[object] = []
    ask = db_session.scalar

    async def counted(statement, *args, **kwargs):
        answer = await ask(statement, *args, **kwargs)
        if "pg_try_advisory_xact_lock" in str(statement) and not answer:
            refused.append(statement)
        return answer

    monkeypatch.setattr(db_session, "scalar", counted)
    engine = create_async_engine(db_session.bind.url)
    try:
        async with engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_lock(:k)"), key)
            gave_up = await reestimate(db_session, take_lock=True, lock_wait=0.3)
            assert gave_up.skipped and not gave_up.applied

            refused.clear()
            follower = asyncio.create_task(reestimate(db_session, take_lock=True, lock_wait=10))
            async with asyncio.timeout(10):
                while len(refused) < 2 and not follower.done():
                    await asyncio.sleep(0.01)
            assert not follower.done(), "it waits while the run holds the lock"
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), key)
            result = await asyncio.wait_for(follower, 10)
    finally:
        await engine.dispose()
    assert result.applied and not result.skipped


@pytest.mark.asyncio
async def test_a_job_re_read_with_its_estimates_deferred_keeps_what_it_shows(db_session):
    """A row read after its source's time bound is enriched with no resolver
    (`retain(network=False)`), so it carries no estimate. Applied as-is, the
    existing job's list copy would go blank while its stored row (the detail)
    kept the figure, a "changed" event would say its pay fell to nothing, and
    the history would record None. Nothing about the job's pay was learned,
    so nothing moves."""
    from tracker.db.models import JobObservation, ScrapeRun

    await _seed(db_session)
    await reestimate(db_session)
    job = (await db_session.execute(select(Job).where(Job.dedupe_key == "acme:0"))).scalar_one()
    assert job.comp_median == 300_000
    raw = RawJob(company="acme", req_id="0", title=job.title, url=job.url, locations=["San Francisco, CA"])
    deferred = await build_enriched(raw, _annotation(job), None)
    assert deferred.estimates == {}
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()

    await upsert_job(db_session, run, deferred, {job.dedupe_key: job})
    await db_session.commit()

    await db_session.refresh(job)
    row = await db_session.get(JobCompEstimate, (job.id, "roleband"), populate_existing=True)
    assert (job.comp_median, row.comp_median) == (300_000, 300_000)
    events = (await db_session.execute(select(JobLifecycleEvent).where(
        JobLifecycleEvent.job_id == job.id, JobLifecycleEvent.event_type == "changed"))).scalars().all()
    assert not [e for e in events if "comp_median" in (e.detail or {})]
    seen = (await db_session.execute(select(JobObservation).where(JobObservation.run_id == run.id))).scalar_one()
    assert seen.comp_median == 300_000 and seen.payload["comp_median"] == 300_000
    assert (await reestimate(db_session)).current, "nothing left for a re-estimate to repair"


# --------------------------------------------------------------------------- #
# A job's own inputs moving outside a scan
# --------------------------------------------------------------------------- #


def test_every_module_and_atlas_file_the_estimate_reads_is_in_its_fingerprint():
    """The fingerprint is what makes an edit re-estimate, so it covers the
    seed rule's modules (`levels/ladder.py`, `atlas.py`, `model.py`,
    `companies.py`), `printed.csv` the ladder reads, and the read-time banding
    (`db/queries/reference_pay.py`, `levels/words.py`). It follows the estimate's imports into
    `tracker.levels` and `tracker.comp_providers`, transitively, and into the
    shared table statement the atlas validates its files with."""
    import ast

    root = reestimate_module._TRACKER
    listed = set(ESTIMATE_SOURCES)
    seen: set[str] = set()
    todo = [e for e in listed if e.endswith(".py")] + ["db/queries/reference_pay.py"]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for node in ast.walk(ast.parse((root / path).read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                    ("tracker.levels", "tracker.comp_providers", "tracker.platform.tables")):
                rel = node.module.removeprefix("tracker.").replace(".", "/")
                todo.append(f"{rel}.py" if (root / f"{rel}.py").is_file() else f"{rel}/__init__.py")
    missing = sorted(p for p in seen if p not in listed and not p.endswith("__init__.py"))
    assert missing == []
    read = _atlas_files_read(root, seen)
    # The control: the walk does find the tables the seed rule reads.
    assert {f"levels/atlas/{name}.csv" for name in ("companies", "ladders", "rungs", "printed", "company_facts")} <= read
    assert sorted(read - listed) == [], "an atlas file the estimate reads is missing from ESTIMATE_SOURCES"
    # The negative control: a module the estimate does not import, which reads
    # an unlisted table, is one this check would catch.
    assert _atlas_files_read(root, {"levels/identity.py"}) - listed


def _atlas_files_read(root, modules: set[str]) -> set[str]:
    """The atlas data files `modules` read: each table they import from
    `tracker.levels.atlas`, directly or through a loader whose body names it."""
    import ast

    from tracker.levels import atlas

    tables = {name: value for name, value in vars(atlas).items() if isinstance(value, atlas.Table)}
    loaders: dict[str, set[str]] = {}
    for node in ast.parse((root / "levels/atlas.py").read_text()).body:
        if isinstance(node, ast.FunctionDef):
            loaders[node.name] = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id in tables}
    read: set[str] = set()
    for path in modules:
        for node in ast.walk(ast.parse((root / path).read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "tracker.levels.atlas":
                for alias in node.names:
                    for table in {alias.name} & set(tables) | loaders.get(alias.name, set()):
                        read.add(tables[table].path.relative_to(root).as_posix())
    return read


@pytest.mark.asyncio
async def test_a_job_whose_level_moved_takes_its_new_estimate_at_once(db_session):
    """No fingerprint covers a job's own fields, so a level backfill that
    rewrites `level_band` moves no estimate by itself. `refresh_jobs`
    re-estimates the jobs whose inputs moved, under the set that applies, the
    list's copy with them."""
    from tracker.db.repo import set_job_levels

    await _seed(db_session)
    await reestimate(db_session)
    mid = (await db_session.execute(select(Job).where(Job.dedupe_key == "acme:mid"))).scalar_one()
    assert mid.comp_median is None
    await set_job_levels(db_session, [{"id": mid.id, "level_band": "senior", "level_confidence": "confirmed",
                                       "level_basis": "title"}])
    assert await reestimate_module.refresh_jobs(db_session, [mid.id]) == 1
    await db_session.commit()
    assert (await _medians(db_session))["acme:mid"] == 300_000
    assert (await _estimates(db_session, "roleband"))[mid.id][1] == 300_000
    assert (await reestimate(db_session)).current, "nothing left for a full pass"


@pytest.mark.asyncio
async def test_mid_switch_only_jobs_the_switch_passed_are_refreshed(db_session):
    """A job the move has not reached yet is the move's to estimate; one it has
    passed takes the target's figure now, and the list keeps the applied copy
    until the flip."""
    from tracker.db.repo import set_job_levels

    await _seed(db_session)
    await reestimate(db_session)
    await _install_plugin(db_session)
    await reestimate(db_session, batch=2, max_batches=1)
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    passed = state.cursor_job_id
    mid = (await db_session.execute(select(Job).where(Job.dedupe_key == "acme:mid"))).scalar_one()
    assert mid.id > passed
    await set_job_levels(db_session, [{"id": mid.id, "level_band": "senior", "level_confidence": "confirmed",
                                       "level_basis": "title"}])
    assert await reestimate_module.refresh_jobs(db_session, [mid.id, passed]) == 1
    await db_session.commit()
    assert (await _medians(db_session))["acme:mid"] is None, "the list keeps the applied copy"
    assert (await reestimate(db_session)).applied
    assert (await _medians(db_session))["acme:mid"] == 999_000


@pytest.mark.asyncio
async def test_the_level_and_role_passes_refresh_what_they_moved(db_session, monkeypatch):
    """The passes that rewrite a job's level or family outside a scan
    re-estimate those jobs."""
    from tracker.workflows import post_passes, relevel

    await _seed(db_session)
    await reestimate(db_session)
    mid = (await db_session.execute(select(Job).where(Job.dedupe_key == "acme:mid"))).scalar_one()
    seen: list[list[int]] = []

    async def spy(session, ids):
        seen.append(sorted(ids))
        return len(ids)

    monkeypatch.setattr(reestimate_module, "refresh_jobs", spy)
    reading = SimpleNamespace(band=LevelBand.SENIOR, confidence=LevelConfidence.CONFIRMED,
                              basis=SimpleNamespace(value="title"))
    pending = [SimpleNamespace(row=SimpleNamespace(id=mid.id), reading=reading, band_moved=True)]

    async def fake_pending(session, *, company=None):
        return 1, pending

    monkeypatch.setattr(relevel, "pending_relevels", fake_pending)
    await relevel.relevel_jobs(db_session)

    async def fake_roles(session, job_ids=None):
        return [{"id": mid.id, "family": "product_management", "track": "ic"}]

    monkeypatch.setattr(post_passes, "pending_roles", fake_roles)
    await post_passes.reclassify_roles(db_session)
    assert seen == [[mid.id], [mid.id]]
