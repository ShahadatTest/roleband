"""Stored postings no scan reads are removed after the user's window.

Settings > Data retention: the user picks 7 to 365 days (default 60) or Never.
Invariants:

- R1 a `posting_inventory` row is removed iff no scan read it within the
  window: dropped from the listing, at an unfollowed or untracked company, or at a
  followed company whose scans failed for the whole window. Nothing else.
- R2 a posting read again before its window ends is kept.
- R3 Never removes nothing; an unset or malformed setting reads as 60, and a
  value outside the choices is refused.
- R4 `jobs`, observations, lifecycle events, saved roles and pursuits are never
  touched.
- R5 what Settings says is due under a window is exactly what a removal under
  it deletes, for every choice.
- R6 a removal is bounded per call; the rest is reported and removed next.
- R7 it runs where runs happen and where they do not: the full-run post pass,
  and the scheduler tick with nothing due, which waits for a running scan.
- R8 no live row can age out: the shortest choice outlasts the longest a
  followed company's live row goes untouched.
- API: exact keys, round trips, and refusals that leave the setting as it was.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.api.schemas import retention as contract
from tracker.config import get_settings
from tracker.db.inventory_store import remove_unread, retention_counts, write_inventory
from tracker.db.models import (
    Favorite,
    Job,
    JobLifecycleEvent,
    JobObservation,
    PostingInventory,
    Pursuit,
    ScrapeRun,
    TrackedCompany,
)
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import inventory_row
from tracker.platform.locks import advisory_unlock, try_advisory_lock
from tracker.schema import RawJob
from tracker.settings_store import (
    RETENTION_CHOICES,
    RETENTION_DEFAULT_DAYS,
    RETENTION_KEY,
    get_retention_days,
    get_retention_last,
    set_retention_days,
    set_setting_dict,
)
from tracker.workflows import retention, scheduler
from tracker.workflows.post_passes import POST_PASSES, PostPassContext, run_post_passes

NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
FOLLOWED = "anthropic"


def _raw(req: str, company: str) -> RawJob:
    return RawJob(company=company, req_id=req, title="Staff Software Engineer",
                  url=f"https://jobs.example.test/{company}/{req}", locations=["London, UK"])


def _company(slug: str, *, enabled: bool = True) -> TrackedCompany:
    return TrackedCompany(slug=slug, display=slug.title(), adapter="greenhouse", status="active",
                          enabled=enabled, visible=True, source="catalog")


async def _store(db_session, reqs, *, at: datetime, company: str = FOLLOWED) -> None:
    """A scan at `at` that read `reqs`: the pipeline's own write path."""
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    raws = [_raw(req, company) for req in reqs]
    rows = {raw.dedupe_key(): inventory_row(raw, annotate(raw)) for raw in raws}
    await write_inventory(
        db_session, run_id=run.id, company=company, binding_id=None, rows=rows,
        seen_keys=set(rows), authoritative=False, now=at, touch_hours=12,
    )
    await db_session.commit()


async def _kept(db_session) -> set[str]:
    db_session.expire_all()
    return set((await db_session.scalars(select(PostingInventory.req_id))).all())


def _factory(db_session):
    return async_sessionmaker(db_session.bind, expire_on_commit=False)


# --------------------------------------------------------------------------- #
# R1, R2: the rule
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_posting_is_removed_only_when_no_scan_read_it_within_the_window(db_session):
    db_session.add_all([_company(FOLLOWED), _company("paused", enabled=False), _company("failing")])
    await db_session.commit()
    days = timedelta(days=1)
    await _store(db_session, ["live"], at=NOW - days)
    await _store(db_session, ["listed-59"], at=NOW - 59 * days)
    await _store(db_session, ["gone-61", "gone-59"], at=NOW - 61 * days)
    await db_session.execute(
        update(PostingInventory).where(PostingInventory.req_id.in_(["gone-61", "gone-59"]))
        .values(gone_at=NOW - 60 * days)
    )
    await db_session.execute(
        update(PostingInventory).where(PostingInventory.req_id == "gone-59")
        .values(last_seen_at=NOW - 59 * days)
    )
    # Unfollowed: not scanned, so its rows age from their last read.
    await _store(db_session, ["paused-61"], at=NOW - 61 * days, company="paused")
    await _store(db_session, ["paused-59"], at=NOW - 59 * days, company="paused")
    # Removed from tracking: no company row at all.
    await _store(db_session, ["removed-61"], at=NOW - 61 * days, company="removed")
    await _store(db_session, ["removed-59"], at=NOW - 59 * days, company="removed")
    # Followed, never marked gone, but no scan has read it (a source failing
    # for the whole window).
    await _store(db_session, ["failing-61"], at=NOW - 61 * days, company="failing")

    result = await retention.apply_retention(db_session, now=NOW)

    assert (result.days, result.removed, result.more) == (60, 4, False)
    assert await _kept(db_session) == {"live", "listed-59", "gone-59", "paused-59", "removed-59"}


@pytest.mark.asyncio
async def test_a_posting_read_again_before_its_window_ends_is_kept(db_session):
    db_session.add(_company(FOLLOWED))
    await db_session.commit()
    await _store(db_session, ["back", "away"], at=NOW - timedelta(days=59))
    await db_session.execute(update(PostingInventory).values(gone_at=NOW - timedelta(days=58)))
    await db_session.commit()
    # The next scan lists "back" again: its row comes back and its clock restarts.
    await _store(db_session, ["back"], at=NOW)

    await retention.apply_retention(db_session, now=NOW + timedelta(days=2))

    assert await _kept(db_session) == {"back"}
    row = (await db_session.scalars(select(PostingInventory))).one()
    assert row.gone_at is None and row.first_seen_at == NOW - timedelta(days=59)


# --------------------------------------------------------------------------- #
# R3: the setting
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_never_removes_nothing(db_session):
    db_session.add(_company(FOLLOWED))
    await db_session.commit()
    await _store(db_session, ["ancient"], at=NOW - timedelta(days=900))
    await set_retention_days(db_session, None)
    await db_session.commit()

    result = await retention.apply_retention(db_session, now=NOW)

    assert (result.days, result.removed) == (None, 0)
    assert await _kept(db_session) == {"ancient"}
    assert await get_retention_last(db_session) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, {}, {"days": 3}, {"days": 45}, {"days": "7"}, {"days": True}])
async def test_an_unset_or_malformed_setting_reads_as_the_default(db_session, stored):
    if stored is not None:
        await set_setting_dict(db_session, RETENTION_KEY, stored)
        await db_session.commit()
    assert await get_retention_days(db_session) == RETENTION_DEFAULT_DAYS == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 45, 1000, True, "60"])
async def test_a_window_outside_the_choices_is_refused(db_session, bad):
    await set_retention_days(db_session, 30)
    with pytest.raises(ValueError):
        await set_retention_days(db_session, bad)
    assert await get_retention_days(db_session) == 30


@pytest.mark.asyncio
async def test_the_switch_off_removes_nothing(db_session, monkeypatch):
    db_session.add(_company(FOLLOWED))
    await db_session.commit()
    await _store(db_session, ["ancient"], at=NOW - timedelta(days=900))
    monkeypatch.setattr(get_settings(), "inventory_retention_enabled", False)

    assert (await retention.apply_retention(db_session, now=NOW)).removed == 0
    assert await _kept(db_session) == {"ancient"}
    by_name = {p.name: p for p in POST_PASSES}
    assert by_name["inventory_retention"].enabled(get_settings()) is False


# --------------------------------------------------------------------------- #
# R4: the Board, Saved and history are never touched
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_removal_never_touches_the_board_saved_roles_or_history(db_session):
    db_session.add(_company("paused", enabled=False))
    await db_session.commit()
    await _store(db_session, ["saved-role"], at=NOW - timedelta(days=90), company="paused")
    stored = (await db_session.scalars(select(PostingInventory))).one()
    run = ScrapeRun(status="ok")
    job = Job(
        company="paused", req_id="saved-role", dedupe_key=stored.dedupe_key,
        title=stored.title, url=stored.url, locations=["London, UK"], location_groups=["uk"],
        workplace_type="onsite", level_band="staff", level_confidence="confirmed",
        family="software_engineering", track="technical", status="open", in_scope=True,
        first_seen=NOW - timedelta(days=120), last_seen=NOW - timedelta(days=90),
        description_sections=[],
    )
    db_session.add_all([run, job])
    await db_session.flush()
    db_session.add_all([
        JobObservation(job_id=job.id, run_id=run.id, observed_at=job.last_seen, title=job.title,
                       level_band="staff", payload={}),
        JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="opened", detail={},
                          created_at=job.first_seen),
        Favorite(job_id=job.id),
        Pursuit(job_id=job.id, stage="applied"),
    ])
    await db_session.commit()
    job_id = job.id

    async def counts():
        return [
            await db_session.scalar(select(func.count()).select_from(model))
            for model in (Job, JobObservation, JobLifecycleEvent, Favorite, Pursuit)
        ]

    before = await counts()
    assert (await retention.apply_retention(db_session, now=NOW)).removed == 1
    assert await _kept(db_session) == set()
    assert await counts() == before == [1, 1, 1, 1, 1]
    assert await db_session.scalar(select(Job.status).where(Job.id == job_id)) == "open"


# --------------------------------------------------------------------------- #
# R5: one clause for the count and the delete
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_what_settings_says_is_due_is_what_a_removal_deletes_for_every_choice(db_session):
    db_session.add_all([_company(FOLLOWED), _company("paused", enabled=False)])
    await db_session.commit()
    # Twelve hours either side of every window, so a count that draws any
    # boundary even a day off disagrees with the delete.
    ages = [timedelta(hours=1), timedelta(days=800)] + [
        timedelta(days=days) + side for days in RETENTION_CHOICES
        for side in (timedelta(hours=-12), timedelta(hours=12))
    ]
    for i, age in enumerate(ages):
        company = FOLLOWED if i % 2 else "paused"
        await _store(db_session, [f"r{i}"], at=NOW - age, company=company)
        await _store(db_session, [f"x{i}"], at=NOW - age, company="untracked")
    await db_session.execute(
        update(PostingInventory).where(PostingInventory.req_id.in_(["r3", "r9", "r15"]))
        .values(gone_at=NOW - timedelta(days=1))
    )
    await db_session.commit()

    counts = await retention_counts(db_session, now=NOW, windows=RETENTION_CHOICES)
    removed = {}
    for days in RETENTION_CHOICES:
        async with db_session.begin_nested() as savepoint:
            removed[days] = await remove_unread(db_session, cutoff=NOW - timedelta(days=days), limit=10_000)
            await savepoint.rollback()

    assert removed == dict(counts.due_by_days)
    assert len(set(removed.values())) == len(RETENTION_CHOICES), "every choice removes a different set"
    assert counts.stored == 2 * len(ages)
    # r3, r9 and r15 sit at the followed company (odd index).
    assert counts.no_longer_listed == 3
    assert counts.stopped_following == len(ages) + sum(1 for i in range(len(ages)) if i % 2 == 0)


# --------------------------------------------------------------------------- #
# R6: bounded, and the rest reported
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_large_removal_is_bounded_and_the_rest_is_removed_next(db_session):
    db_session.add(_company(FOLLOWED))
    await db_session.commit()
    await _store(db_session, [f"old{i}" for i in range(25)], at=NOW - timedelta(days=100))

    first = await retention.apply_retention(db_session, now=NOW, batch=10, max_batches=2)
    assert (first.removed, first.more) == (20, True)
    assert await get_retention_last(db_session) == {"at": NOW.isoformat(), "removed": 20, "more": True}

    later = NOW + timedelta(hours=1)
    second = await retention.apply_retention(db_session, now=later, batch=10, max_batches=2)
    assert (second.removed, second.more) == (5, False)
    assert await _kept(db_session) == set()

    # A call that removes nothing leaves the last removal as it was.
    third = await retention.apply_retention(db_session, now=later + timedelta(hours=1), batch=10, max_batches=2)
    assert third.removed == 0
    assert await get_retention_last(db_session) == {"at": later.isoformat(), "removed": 5, "more": False}


# --------------------------------------------------------------------------- #
# R7: where it runs
# --------------------------------------------------------------------------- #


def test_the_pass_follows_promotion_and_runs_on_full_runs_only():
    names = [p.name for p in POST_PASSES]
    assert names.index("inventory_retention") == names.index("inventory_promotion") + 1
    by_name = {p.name: p for p in POST_PASSES}
    assert by_name["inventory_retention"].capped_ok is False, "an operator's capped smoke never deletes"
    assert by_name["inventory_retention"].discovery_ok is False


def _ctx(session, *, max_list=None):
    return PostPassContext(session=session, touched_ids=[], per_source={}, settings=get_settings(),
                           max_list=max_list)


@pytest.mark.asyncio
async def test_a_full_run_removes_what_is_due_and_a_capped_run_does_not(db_session, monkeypatch):
    db_session.add(_company(FOLLOWED))
    await db_session.commit()
    await _store(db_session, ["ancient"], at=datetime.now(UTC) - timedelta(days=200))
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES",
                        tuple(p for p in POST_PASSES if p.name == "inventory_retention"))

    async with _factory(db_session)() as session:
        capped = _ctx(session, max_list=150)
        await run_post_passes(capped)
    assert "retention" not in capped.results
    assert await _kept(db_session) == {"ancient"}

    async with _factory(db_session)() as session:
        full = _ctx(session)
        await run_post_passes(full)
    assert full.results["retention"] == {"removed": 1, "more": False}
    assert await _kept(db_session) == set()


@pytest.mark.asyncio
async def test_the_scheduler_removes_when_nothing_is_due(db_session, scratch_scope, monkeypatch):
    """A user who stopped following every company has no run, so no post pass:
    the idle tick is what removes their postings."""
    await _store(db_session, ["left"], at=datetime.now(UTC) - timedelta(days=200), company="unfollowed")

    async def nothing_due(_now, **_):
        return scheduler.TickPlan([])

    monkeypatch.setattr(scheduler, "plan_tick", nothing_due)

    dry = await scheduler.run_once(dry_run=True)
    assert "retention" not in dry and await _kept(db_session) == {"left"}

    result = await scheduler.run_once()
    assert (result["reason"], result["retention"]) == ("nothing due", {"removed": 1, "more": False})
    assert result["reminders"] == {"owed": 0}
    assert await _kept(db_session) == set()
    # The same idle tick brings the stored estimates to the reference set:
    # the first ever applies it.
    assert result["reference"]["applied"] is True


@pytest.mark.asyncio
async def test_a_failed_idle_removal_never_fails_the_tick(monkeypatch):
    async def nothing_due(_now, **_):
        return scheduler.TickPlan([])

    async def broken(_now):
        raise RuntimeError("database went away")

    async def no_reminders():
        return 0

    async def no_reestimate():
        raise RuntimeError("reference store went away")

    # Closing what a stopped scan left open is housekeeping too.
    monkeypatch.setattr(scheduler, "close_runs_left_open", broken)
    monkeypatch.setattr(scheduler, "plan_tick", nothing_due)
    monkeypatch.setattr(scheduler, "retention_when_idle", broken)
    monkeypatch.setattr(scheduler, "reminders_when_idle", no_reminders)
    monkeypatch.setattr(scheduler, "reestimate_when_idle", no_reestimate)

    result = await scheduler.run_once()

    assert (result["ran"], result["reason"]) == (False, "nothing due")
    assert "database went away" in result["retention"]["error"]
    # The idle re-estimate is housekeeping too: its failure never fails the tick.
    assert "reference store went away" in result["reference"]["error"]


@pytest.mark.asyncio
async def test_the_idle_removal_waits_for_a_running_scan(db_session):
    await _store(db_session, ["left"], at=NOW - timedelta(days=200), company="unfollowed")
    factory = _factory(db_session)
    key = get_settings().advisory_lock_key
    async with factory() as run_session:
        assert await try_advisory_lock(run_session, key)
        try:
            async with factory() as idle:
                held = await retention.apply_retention(idle, now=NOW, take_lock=True)
            assert (held.removed, held.skipped) == (0, True)
            assert await _kept(db_session) == {"left"}
        finally:
            await advisory_unlock(run_session, key)

    async with factory() as idle:
        free = await retention.apply_retention(idle, now=NOW, take_lock=True)
    assert (free.removed, free.skipped) == (1, False)


# --------------------------------------------------------------------------- #
# R8: no live row can age out
# --------------------------------------------------------------------------- #


def test_the_shortest_window_outlasts_any_live_row_s_untouched_time():
    s = get_settings()
    # A live row is re-touched once its last touch is older than the touch
    # window, at the next scan; a reconcile is at most one cadence away, plus
    # a blocked provider's cooldown.
    longest_untouched = (
        s.inventory_touch_hours
        + s.sync_reconcile_cadence_seconds / 3600
        + s.sync_provider_blocked_cooldown_seconds / 3600
    )
    assert min(RETENTION_CHOICES) * 24 > 2 * longest_untouched
    # Promotion admits only fresher rows than any retention window removes, and
    # waits no less than a healthy company's live row can go untouched.
    assert s.inventory_touch_hours + s.sync_reconcile_cadence_seconds / 3600 < s.inventory_promotion_fresh_hours
    assert s.inventory_promotion_fresh_hours < min(RETENTION_CHOICES) * 24
    assert RETENTION_DEFAULT_DAYS in RETENTION_CHOICES


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

async def _seed_api(db_session) -> None:
    now = datetime.now(UTC)
    db_session.add_all([_company(FOLLOWED), _company("paused", enabled=False)])
    await db_session.commit()
    await _store(db_session, ["live"], at=now - timedelta(hours=2))
    await _store(db_session, ["closed"], at=now - timedelta(days=20))
    await db_session.execute(
        update(PostingInventory).where(PostingInventory.req_id == "closed")
        .values(gone_at=now - timedelta(days=19))
    )
    await db_session.commit()
    await _store(db_session, ["p10"], at=now - timedelta(days=10), company="paused")
    await _store(db_session, ["p100"], at=now - timedelta(days=100), company="paused")


@pytest.mark.asyncio
async def test_get_answers_the_default_window_and_what_each_choice_removes(api_client, db_session):
    await _seed_api(db_session)
    response = await api_client.get("/api/settings/retention")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(contract.RetentionState.model_fields)
    assert (body["days"], body["default_days"]) == (60, 60)
    assert body["choices"] == [
        {"days": 7, "due": 3}, {"days": 14, "due": 2}, {"days": 30, "due": 1}, {"days": 60, "due": 1},
        {"days": 90, "due": 1}, {"days": 180, "due": 0}, {"days": 365, "due": 0},
    ]
    assert (body["stored"], body["no_longer_listed"], body["stopped_following"], body["due"]) == (4, 1, 2, 1)
    assert body["last_removed"] is None


@pytest.mark.asyncio
async def test_put_saves_a_choice_and_never_and_answers_the_new_state(api_client, db_session):
    await _seed_api(db_session)
    saved = await api_client.put("/api/settings/retention", json={"days": 14})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["days"], saved.json()["due"]) == (14, 2)
    assert (await api_client.get("/api/settings/retention")).json()["days"] == 14

    never = await api_client.put("/api/settings/retention", json={"days": None})
    assert (never.json()["days"], never.json()["due"]) == (None, 0)
    assert (await api_client.get("/api/settings/retention")).json()["days"] is None
    # Saving removes nothing: runs do.
    assert await _kept(db_session) == {"live", "closed", "p10", "p100"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"days": 0}, {"days": 45}, {"days": "60"}, {"days": True}, {}, {"days": 60, "x": 1}])
async def test_put_refuses_anything_but_a_choice_and_keeps_the_saved_window(api_client, db_session, body):
    assert (await api_client.put("/api/settings/retention", json={"days": 30})).status_code == 200
    refused = await api_client.put("/api/settings/retention", json=body)
    assert refused.status_code == 422
    assert (await api_client.get("/api/settings/retention")).json()["days"] == 30


@pytest.mark.asyncio
async def test_get_reports_the_last_removal(api_client, db_session):
    await _seed_api(db_session)
    async with _factory(db_session)() as session:
        result = await retention.apply_retention(session, now=datetime.now(UTC))
    assert result.removed == 1
    body = (await api_client.get("/api/settings/retention")).json()
    assert (body["last_removed"]["removed"], body["last_removed"]["more"]) == (1, False)
    assert body["stored"] == 3


@pytest.mark.asyncio
async def test_capture_off_removes_nothing_either(db_session, monkeypatch):
    """`inventory_enabled=False` freezes every row's `last_seen_at`, so a window
    measured against it would remove rows scans DID read, which the retention
    rule ("rows no scan reads") does not cover."""
    db_session.add(_company(FOLLOWED))
    await db_session.commit()
    await _store(db_session, ["ancient"], at=NOW - timedelta(days=900))
    await set_retention_days(db_session, 30)
    monkeypatch.setattr(get_settings(), "inventory_enabled", False)

    assert (await retention.apply_retention(db_session, now=NOW)).removed == 0
    assert await _kept(db_session) == {"ancient"}
    by_name = {p.name: p for p in POST_PASSES}
    assert by_name["inventory_retention"].enabled(get_settings()) is False

    # The control: with capture on, the same row is due.
    monkeypatch.setattr(get_settings(), "inventory_enabled", True)
    assert (await retention.apply_retention(db_session, now=NOW)).removed == 1
