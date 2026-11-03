"""No read sends the database a list of ids that grows with the data.

A list fetched into Python and bound back (`= ANY(:ids)`) crosses the wire
twice, and once Postgres plans a prepared statement generically it searches
the array row by row, so the cost grows with ids times rows. The rules these
reads need (a place set's later members, the new-listing rule) run inside the
statement instead. The seed holds more ids of each kind than a bound
list may carry, so a read that binds one fails here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from tests.factories import make_company, make_job
from tracker.analytics.demand import compute_demand_metrics
from tracker.db.models import JobLifecycleEvent, JobPlaceSet, JobPlaceSetMember, ScrapeRun

#: More ids of each kind than a bound list may carry.
MANY = 600
#: The longest list one statement may bind.
LONGEST_BOUND_LIST = 500

READS = (
    "/api/stats",
    "/api/statistics/overview",
    "/api/statistics/velocity?days=30",
    "/api/statistics/velocity?days=0",
    "/api/demand",
    "/api/jobs?status=open&new_today_only=true&limit=20",
    "/api/facets",
)


async def _seed(db_session) -> None:
    """acme's first scan finds MANY roles its board was already listing; a later
    run finds one role listed at MANY + 1 places, a place set with MANY later
    members."""
    now = datetime.now(UTC)
    first = ScrapeRun(started_at=now - timedelta(hours=4), status="ok")
    later = ScrapeRun(started_at=now - timedelta(hours=2), status="ok")
    db_session.add_all([make_company("acme", "Acme"), first, later])
    await db_session.flush()
    finds = [
        make_job(f"find-{i}", company="acme", first_seen=first.started_at, arrival="first_read")
        for i in range(MANY)
    ]
    places = [
        make_job(f"place-{i}", company="acme", first_seen=later.started_at + timedelta(seconds=i), arrival="new")
        for i in range(MANY + 1)
    ]
    place_set = JobPlaceSet(company="acme", title="staff product manager", text_hash="0" * 32,
                            size=len(places), places=[], rule_version="t1")
    db_session.add_all([*finds, *places, place_set])
    await db_session.flush()
    for run, jobs in ((first, finds), (later, places)):
        db_session.add_all(
            JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="opened", detail={},
                              created_at=run.started_at)
            for job in jobs
        )
    db_session.add_all(JobPlaceSetMember(job_id=job.id, set_id=place_set.id, status="auto") for job in places)
    await db_session.commit()


@pytest.mark.asyncio
async def test_no_read_binds_a_list_of_ids_that_grows_with_the_data(api_client, db_session):
    await _seed(db_session)
    longest: dict[str, int] = {}
    reading = [""]

    def record(conn, cursor, statement, parameters, context, executemany):
        longest.setdefault(reading[0], 0)
        for row in parameters if executemany else [parameters]:
            values = row.values() if isinstance(row, dict) else row or ()
            for value in values:
                if isinstance(value, list | tuple):
                    longest[reading[0]] = max(longest[reading[0]], len(value))

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        for path in READS:
            reading[0] = path
            response = await api_client.get(path)
            assert response.status_code == 200, (path, response.text)
        reading[0] = "demand post-pass"
        await compute_demand_metrics(db_session)
        await db_session.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert set(longest) == {*READS, "demand post-pass"}, "every read must reach the listener, or this proves nothing"
    assert {read: n for read, n in longest.items() if n > LONGEST_BOUND_LIST} == {}


@pytest.mark.asyncio
async def test_pace_and_overview_keep_their_rules_at_volume(api_client, db_session):
    """The same seed through the rules themselves: the first scan's finds are
    never openings, and the place set opens once and is open once."""
    await _seed(db_session)
    velocity = (await api_client.get("/api/statistics/velocity?days=30")).json()
    kpis = velocity["kpis"]
    assert (kpis["opened"], kpis["first_scan"], kpis["open_total"]) == (1, MANY, MANY + 1)
    assert sum(band["count"] for band in velocity["aging"]) == kpis["open_total"]
    overview = (await api_client.get("/api/statistics/overview?days=30")).json()["kpis"]
    assert (overview["new_count"], overview["first_scan_count"]) == (1, MANY)
