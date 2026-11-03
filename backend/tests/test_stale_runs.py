"""One rule for "this `running` row is an orphan", checked two ways.

The rule has two implementations and always will: `stale_run_where` filters a
table, `health.is_run_active` judges a row already in hand. Written separately,
in SQL and in Python, either could move to `<=`, or drop the
`heartbeat_at`-or-`started_at` fallback, and only its own surface would change. The badge would then say
a run is live while the status count called it stuck.

So the gate is not "each one works": it is that they answer identically over the
same rows, boundary rows included, given the same clock. The reconciler is held
to the same predicate by construction (it selects with it) and to real Postgres
behaviour below — a check that the SQL string contains a cast cannot fail for a
reconciler that stopped flipping anything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tracker.db.models import ScrapeRun
from tracker.db.queries.runs import stale_run_where
from tracker.db.repo import reconcile_stale_runs
from tracker.health import is_run_active

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
STALE_MINUTES = 90
HEARTBEAT_SECONDS = 180

#: `(name, started_at offset, heartbeat_at offset or None)`, in seconds before
#: `NOW`. The four boundary rows are the point: one second either side of each
#: bound, and exactly on it.
CASES = [
    ("beating_now", 60, 0),
    ("never_beat_but_young", 30, None),
    ("heartbeat_exactly_at_the_bound", 600, HEARTBEAT_SECONDS),
    ("heartbeat_one_second_past", 600, HEARTBEAT_SECONDS + 1),
    ("start_exactly_at_the_bound", STALE_MINUTES * 60, 0),
    ("start_one_second_past", STALE_MINUTES * 60 + 1, 0),
    # A full collection outlasts any fixed budget. Beating is what makes a run
    # live, so neither of these is an orphan, and the silent one below is.
    ("long_and_beating", STALE_MINUTES * 60 * 4, 0),
    ("long_and_silent", STALE_MINUTES * 60 * 4, HEARTBEAT_SECONDS + 1),
    ("never_beat_and_silent", HEARTBEAT_SECONDS + 1, None),
    ("never_beat_exactly_at_the_bound", HEARTBEAT_SECONDS, None),
]


async def _seed(session, *, status: str = "running") -> dict[str, int]:
    ids: dict[str, int] = {}
    for name, started, beat in CASES:
        run = ScrapeRun(
            started_at=NOW - timedelta(seconds=started),
            heartbeat_at=None if beat is None else NOW - timedelta(seconds=beat),
            status=status,
            scope="full",
            jobs_seen=0,
            jobs_new=0,
            jobs_closed=0,
            per_source={},
            drift_alerts=[],
            notes=None,
        )
        session.add(run)
        await session.flush()
        ids[name] = run.id
    await session.commit()
    return ids


async def _selected(session, now) -> set[int]:
    rows = await session.scalars(
        select(ScrapeRun.id).where(
            stale_run_where(
                now,
                stale_minutes=STALE_MINUTES,
                heartbeat_stale_seconds=HEARTBEAT_SECONDS,
            )
        )
    )
    return set(rows.all())


def _live(name: str) -> bool:
    started, beat = next((s, b) for n, s, b in CASES if n == name)
    return is_run_active(
        "running",
        NOW - timedelta(seconds=started),
        NOW,
        STALE_MINUTES,
        heartbeat_at=None if beat is None else NOW - timedelta(seconds=beat),
        heartbeat_stale_seconds=HEARTBEAT_SECONDS,
    )


async def test_the_sql_predicate_and_the_python_judgement_never_disagree(db_session):
    ids = await _seed(db_session)
    orphaned = await _selected(db_session, NOW)

    verdicts = {name: (ids[name] in orphaned, not _live(name)) for name in ids}
    disagree = {name: pair for name, pair in verdicts.items() if pair[0] != pair[1]}
    assert not disagree, f"SQL and Python judged these rows differently: {disagree}"


@pytest.mark.parametrize(
    ("name", "orphaned"),
    [
        ("beating_now", False),
        ("never_beat_but_young", False),
        ("heartbeat_exactly_at_the_bound", False),
        ("heartbeat_one_second_past", True),
        ("start_exactly_at_the_bound", False),
        # Beating, so not an orphan: age alone never was the evidence.
        ("start_one_second_past", False),
        ("long_and_beating", False),
        ("long_and_silent", True),
        ("never_beat_and_silent", True),
        ("never_beat_exactly_at_the_bound", False),
    ],
)
async def test_each_boundary_row_classifies_the_way_the_rule_says(db_session, name, orphaned):
    """The bound is strict `<`, and a run that has never beaten falls back to
    `started_at`, so its silence is measured from its start rather than
    treated as an absent beat no window can catch.

    Age is not evidence of death. A run reconciled while it is still beating
    goes to `error` with its process still writing, and the terminal status it
    records later overwrites the reconciliation, so the run log reports
    whichever write landed last."""
    ids = await _seed(db_session)
    assert (ids[name] in await _selected(db_session, NOW)) is orphaned
    assert _live(name) is not orphaned


async def test_only_a_running_row_is_ever_an_orphan(db_session):
    ids = await _seed(db_session, status="error")
    assert await _selected(db_session, NOW) == set()
    assert ids, "the seed must have written rows, or nothing was measured"


# --------------------------------------------------------------------------- #
# The reconciler, against real Postgres rather than its own SQL string
# --------------------------------------------------------------------------- #


async def _reconcilable(session) -> dict[str, int]:
    """The same cases, placed relative to the DATABASE clock.

    The reconciler answers with `now()`, so rows are offset from the server's
    instant; the two boundary rows are moved a second clear of their bound
    because a server clock that advanced between the INSERT and the UPDATE would
    otherwise decide them, and that is skew, not semantics.
    """
    server_now = await session.scalar(select(func.now()))
    ids: dict[str, int] = {}
    for name, started, beat in CASES:
        clear = 1 if "exactly" in name else 0
        run = ScrapeRun(
            started_at=server_now - timedelta(seconds=started - clear),
            heartbeat_at=None if beat is None else server_now - timedelta(seconds=beat - clear),
            status="running",
            scope="full",
            jobs_seen=0, jobs_new=0, jobs_closed=0,
            per_source={}, drift_alerts=[], notes=None,
        )
        session.add(run)
        await session.flush()
        ids[name] = run.id
    await session.commit()
    return ids


async def test_the_reconciler_flips_exactly_the_orphans_and_says_why(db_session):
    ids = await _reconcilable(db_session)

    reconciled = await reconcile_stale_runs(
        db_session,
        older_than_minutes=STALE_MINUTES,
        heartbeat_stale_seconds=HEARTBEAT_SECONDS,
    )
    await db_session.commit()

    expected = {name for name, _s, _b in CASES if not _live(name)}
    assert reconciled == len(expected)
    for name, run_id in ids.items():
        row = await db_session.get(ScrapeRun, run_id)
        await db_session.refresh(row)
        if name in expected:
            assert row.status == "error", name
            assert row.finished_at is not None, name
            assert row.notes == " [reconciled: stale/orphaned run]", name
        else:
            assert (row.status, row.finished_at, row.notes) == ("running", None, None), name


async def test_the_reconciler_keeps_a_note_that_was_already_there(db_session):
    run = ScrapeRun(
        started_at=datetime.now(UTC) - timedelta(minutes=STALE_MINUTES + 5),
        heartbeat_at=None, status="running", scope="full",
        jobs_seen=0, jobs_new=0, jobs_closed=0,
        per_source={}, drift_alerts=[], notes="partial: 2 sources bounded",
    )
    db_session.add(run)
    await db_session.commit()

    await reconcile_stale_runs(db_session, older_than_minutes=STALE_MINUTES)
    await db_session.commit()
    await db_session.refresh(run)

    assert run.notes == "partial: 2 sources bounded [reconciled: stale/orphaned run]"


async def test_a_caller_with_no_heartbeat_bound_reconciles_on_start_time_alone(db_session):
    """The pre-heartbeat caller. A run silent for an hour but young by
    `started_at` must survive, or arming the bound would mean nothing."""
    silent = ScrapeRun(
        started_at=datetime.now(UTC) - timedelta(minutes=30),
        heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
        status="running", scope="full",
        jobs_seen=0, jobs_new=0, jobs_closed=0,
        per_source={}, drift_alerts=[], notes=None,
    )
    db_session.add(silent)
    await db_session.commit()

    assert await reconcile_stale_runs(db_session, older_than_minutes=STALE_MINUTES) == 0
    await db_session.refresh(silent)
    assert silent.status == "running"

    assert (
        await reconcile_stale_runs(
            db_session, older_than_minutes=STALE_MINUTES, heartbeat_stale_seconds=HEARTBEAT_SECONDS
        )
        == 1
    )


async def test_a_reconciled_run_reports_the_sources_it_committed(db_session):
    """A run writes `per_source` at its terminal record, which an orphan never
    reached: the reconciler fills it from the source rows it committed. Its
    status is theirs capped at `partial`, as a stopped run's is: `error` would
    deny the rows they wrote. It covered less than it set out to, so it claims
    no full refresh."""
    from tracker.db.models import ScrapeSourceRun, SourceBinding, TrackedCompany

    run = ScrapeRun(
        started_at=datetime.now(UTC) - timedelta(minutes=STALE_MINUTES + 5),
        heartbeat_at=None, status="running", scope="full",
        jobs_seen=0, jobs_new=0, jobs_closed=0, per_source={}, drift_alerts=[], notes=None,
    )
    db_session.add_all([run, TrackedCompany(
        slug="acme", display="Acme", adapter="greenhouse", board_token="acme", careers_url="https://example.test/acme",
        status="active", enabled=True, visible=True, source="catalog",
    )])
    await db_session.flush()
    binding = SourceBinding(company_slug="acme", connector_kind="adapter", connector_id="greenhouse", status="stable",
                            closure_capability="authoritative", created_at=run.started_at, activated_at=run.started_at)
    db_session.add(binding)
    await db_session.flush()
    stats = {"outcome": "ok", "scanned": 4, "kept": 2, "errors": []}
    db_session.add(ScrapeSourceRun(
        run_id=run.id, binding_id=binding.id, company_slug="acme", provider_key="greenhouse", scan_mode="reconcile",
        outcome="ok", started_at=run.started_at, finished_at=run.started_at, stats=stats, errors=[], drift=[],
    ))
    await db_session.commit()

    await reconcile_stale_runs(db_session, older_than_minutes=STALE_MINUTES)
    await db_session.commit()
    await db_session.refresh(run)
    assert (run.status, run.scope, run.per_source) == ("partial", "targeted", {"acme": stats})
