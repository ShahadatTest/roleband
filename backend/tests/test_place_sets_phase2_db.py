"""Place sets over real Postgres: one Board row per set,
every count a set once, demand that does not book a set's later members, and a
saved posting whose role stays listed elsewhere.

The fixture is the AECOM shape: one role, its text and title
identical, one posting per UK city, each first seen a minute after the last.
Every test names the broken rule it catches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from tracker.analytics.demand import compute_demand_metrics, demand_day
from tracker.db.models import (
    DemandMetric,
    Favorite,
    Job,
    JobFeedback,
    JobLifecycleEvent,
    Notification,
    ScrapeRun,
    TrackedCompany,
)
from tracker.db.queries import jobs as job_queries
from tracker.db.queries.jobs import board_count_stmt
from tracker.db.repo import refresh_search_vectors
from tracker.lineage.counts import event_bucket
from tracker.lineage.place_sets import (
    rebuild_place_sets,
    review_place_set_member,
    still_listed_elsewhere,
)
from tracker.notifications import generate_notifications
from tracker.notifications.render import _company_label
from tracker.platform.util import local_day_start_utc

NOW = datetime.now(UTC)
TITLE = "Project Director - Controls Analytics"
BODY = (
    "AECOM is seeking a Project Director to lead controls analytics across our "
    "infrastructure portfolio. You will own schedule and cost performance, build "
    "the reporting the programme board reads, and grow a team of analysts. "
) * 6


async def _job(
    session,
    n: int,
    city: str,
    *,
    title: str = TITLE,
    status: str = "open",
    in_scope: bool = True,
    seen_days_ago: float = 2,
    now: datetime = NOW,
) -> Job:
    job = Job(
        company="aecom",
        title=title,
        url=f"https://jobs.example.test/aecom/{n}",
        req_id=f"7440001274{n:05d}",
        dedupe_key=f"aecom:{n}",
        level_band="director_plus",
        family="data_science",
        locations=[f"{city}, United Kingdom"],
        location_cities=[f"{city}, UK"],
        location_groups=["uk", f"city_{city.lower().replace(' ', '_')}"],
        description_text=BODY,
        status=status,
        first_seen=now - timedelta(days=seen_days_ago, minutes=-n),
        last_seen=now,
        closed_at=now if status == "closed" else None,
        total_days_open=2,
        repost_count=0,
        in_scope=in_scope,
    )
    session.add(job)
    await session.flush()
    return job


async def _aecom(session) -> tuple[Job, Job, Job, Job]:
    """One role in London, Bristol and Leeds (London first), and another role."""
    london = await _job(session, 1, "London")
    bristol = await _job(session, 2, "Bristol")
    leeds = await _job(session, 3, "Leeds")
    other = await _job(session, 4, "Leeds", title="Project Director - Rail")
    await session.commit()
    await rebuild_place_sets(session)
    return london, bristol, leeds, other


async def _board(client, **params) -> tuple[int, list[int]]:
    response = await client.get("/api/jobs", params={"limit": 50, **params})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["total"], [item["id"] for item in body["items"]]


# --------------------------------------------------------------------------
# The Board: one row per set
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_board_lists_a_set_once_through_its_earliest_member(api_client, db_session):
    """Broken rule caught: no collapse (4 rows), or the latest member as the row."""
    london, bristol, leeds, other = await _aecom(db_session)

    total, ids = await _board(api_client)

    assert total == 2
    assert sorted(ids) == sorted([london.id, other.id])
    row = next(
        item
        for item in (await api_client.get("/api/jobs")).json()["items"]
        if item["id"] == london.id
    )
    assert row["place_count"] == 3


@pytest.mark.asyncio
async def test_a_place_filter_shows_the_member_at_that_place(api_client, db_session):
    """Broken rule caught: the representative ignores the filter, so the
    Bristol filter shows London's posting or (filtered out) nothing at all."""
    london, bristol, leeds, other = await _aecom(db_session)

    assert await _board(api_client, location_group="city_bristol") == (1, [bristol.id])
    # A place two members share-by-group still lists the role once.
    total, ids = await _board(api_client, location_group="uk")
    assert total == 2 and sorted(ids) == sorted([london.id, other.id])
    # Leeds holds the set's Leeds member AND the other role.
    total, ids = await _board(api_client, location_group="city_leeds")
    assert total == 2 and sorted(ids) == sorted([leeds.id, other.id])


@pytest.mark.asyncio
async def test_a_posting_named_by_id_or_saved_is_never_collapsed(api_client, db_session):
    """Broken rule caught: Compare and Saved lose a posting the person chose
    because a sibling represents its set."""
    london, bristol, leeds, other = await _aecom(db_session)
    db_session.add(Favorite(job_id=bristol.id))
    await db_session.commit()

    assert await _board(api_client, ids=[bristol.id]) == (1, [bristol.id])
    assert await _board(api_client, favorites_only=True) == (1, [bristol.id])


@pytest.mark.asyncio
async def test_not_for_me_on_the_row_hides_the_role_not_just_one_posting(api_client, db_session):
    """Broken rule caught: the representative is picked AFTER the dismissed
    filter, so dismissing London promotes Bristol and the role comes back."""
    london, bristol, leeds, other = await _aecom(db_session)
    db_session.add(JobFeedback(job_id=london.id, verdict="dismissed"))
    await db_session.commit()

    assert await _board(api_client) == (1, [other.id])
    total, ids = await _board(api_client, dismissed_only=True)
    assert ids == [london.id]


@pytest.mark.asyncio
async def test_a_member_out_of_scope_or_closed_never_hides_the_open_one(api_client, db_session):
    """Broken rule caught: the earliest member wins regardless of scope or
    status, so a London posting the person does not track (or one that closed
    before the rebuild) hides the Bristol row they can see."""
    london, bristol, leeds, other = await _aecom(db_session)
    london.in_scope = False
    await db_session.commit()
    total, ids = await _board(api_client)
    assert total == 2 and sorted(ids) == sorted([bristol.id, other.id])

    london.in_scope = True
    london.status = "closed"
    await db_session.commit()
    total, ids = await _board(api_client)
    assert total == 2 and sorted(ids) == sorted([bristol.id, other.id])
    # The Closed board lists London, and Bristol does not hide it there.
    assert await _board(api_client, status="closed") == (1, [london.id])


@pytest.mark.asyncio
async def test_a_split_posting_is_its_own_row_again(api_client, db_session):
    """Broken rule caught: the collapse reads `rejected` memberships."""
    london, bristol, leeds, other = await _aecom(db_session)
    await review_place_set_member(db_session, bristol.id, "different")

    total, ids = await _board(api_client)
    assert total == 3 and sorted(ids) == sorted([london.id, bristol.id, other.id])


# --------------------------------------------------------------------------
# Counts: the top bar, /api/stats, facets
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_count_counts_a_set_once(api_client, db_session):
    """Broken rule caught: a count that reads `jobs` without the collapse, so
    the number beside an option disagrees with the rows it lists."""
    london, bristol, leeds, other = await _aecom(db_session)

    stats = (await api_client.get("/api/stats")).json()
    assert stats["open_total"] == 2
    assert stats["by_company"] == {"aecom": 2}

    facets = (await api_client.get("/api/facets")).json()
    assert facets["total"] == 2
    counts = facets["counts"]
    assert counts["company"] == {"aecom": 2}
    assert counts["family"] == {"data_science": 2}
    # Each place counts the rows its filter lists (see the place-filter test).
    assert counts["location_group"]["uk"] == 2
    assert counts["location_group"]["city_bristol"] == 1
    assert counts["location_group"]["city_leeds"] == 2

    overview = (await api_client.get("/api/statistics/overview")).json()
    assert overview["kpis"]["open_total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("now", [
    datetime(2026, 10, 11, 21, 59, 59, tzinfo=UTC),
    datetime(2026, 10, 11, 22, 0, 1, tzinfo=UTC),
], ids=["before-local-midnight", "after-local-midnight"])
async def test_a_new_place_for_a_listed_role_is_not_new_today(api_client, db_session, monkeypatch, now):
    """Broken rule caught: `is_new_job_clause` ignores sets, so a city added
    today to a role listed for weeks is counted, and listed, as a new role."""
    # The API's clock and the seeded rows share an explicit one: module-import
    # NOW can precede midnight while the request executes after it.
    monkeypatch.setattr(job_queries, "local_day_start_utc", lambda: local_day_start_utc(
        now, ZoneInfo("Europe/Stockholm")
    ))
    monkeypatch.setattr(job_queries, "datetime", type("Clock", (datetime,), {
        "now": classmethod(lambda cls, tz=None: now),
    }))
    london = await _job(db_session, 1, "London", seen_days_ago=20, now=now)
    bristol = await _job(db_session, 2, "Bristol", seen_days_ago=0.01, now=now)
    lone = await _job(db_session, 3, "Leeds", title="Project Director - Rail", seen_days_ago=0.01, now=now)
    # London came from an earlier scan, so today's finds were stored while the
    # company was already read.
    for job in (london, bristol, lone):
        job.arrival = "new"
    earlier = ScrapeRun(status="ok", started_at=now - timedelta(days=20), per_source={}, drift_alerts=[])
    run = ScrapeRun(status="ok", started_at=now, per_source={}, drift_alerts=[])
    db_session.add_all([earlier, run])
    await db_session.flush()
    db_session.add(JobLifecycleEvent(job_id=london.id, run_id=earlier.id, event_type="opened",
                                     created_at=now - timedelta(days=20)))
    for job in (bristol, lone):
        db_session.add(
            JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="opened", created_at=now)
        )
    await db_session.commit()
    await rebuild_place_sets(db_session)

    assert (await api_client.get("/api/stats")).json()["new_today"] == 1
    assert await _board(api_client, new_today_only=True) == (1, [lone.id])
    # London is not new today either, and the Board still lists the role once.
    total, ids = await _board(api_client)
    assert total == 2 and london.id in ids and bristol.id not in ids


# --------------------------------------------------------------------------
# A filter picks the member: a posting fact is the posting's own
# --------------------------------------------------------------------------


async def _london_bristol(session, **bristol_facts) -> tuple[Job, Job, Job]:
    """The role in London (first) and Bristol, Bristol carrying `bristol_facts`;
    plus another role, so a total never reads zero by accident."""
    london = await _job(session, 1, "London")
    bristol = await _job(session, 2, "Bristol")
    other = await _job(session, 4, "Leeds", title="Project Director - Rail")
    for job in (london, other):
        job.workplace_type = "hybrid"
        job.comp_median = 200_000
    bristol.workplace_type = "hybrid"
    bristol.comp_median = 200_000
    for name, value in bristol_facts.items():
        setattr(bristol, name, value)
    await session.commit()
    await refresh_search_vectors(session, [london.id, bristol.id, other.id])
    await session.commit()
    await rebuild_place_sets(session)
    return london, bristol, other


async def _count(session, **params) -> int:
    return await session.scalar(board_count_stmt({"status": "open", **params}))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("facts", "params"),
    [
        ({"workplace_type": "remote"}, {"workplace_type": ["remote"]}),
        ({"comp_base_median": 300_000}, {"base_min": 250_000}),
        (
            {
                "structured_at": NOW, "disclosed_base_min": 180_000,
                "disclosed_base_max": 220_000,
            },
            {"discloses_pay": True},
        ),
        ({"team": "Infrastructure Tunnelling"}, {"q": "tunnelling"}),
        ({"first_seen": NOW - timedelta(days=5)}, {"posted_within_days": 30}),
    ],
    ids=["workplace", "pay", "discloses_pay", "search_text", "posted_within"],
)
async def test_a_filter_lists_the_member_that_passes_it(api_client, db_session, facts, params):
    """Broken rule caught: the earliest member represents the set before
    any posting filter, so London failing the filter hides Bristol, which
    passes it, and the role disappears from the page and every total."""
    london, bristol, other = await _london_bristol(db_session, **facts)
    if "posted_within_days" in params:
        # London listed 90 days ago, Bristol (seen later) 5 days ago.
        for job in (london, other):
            job.first_seen = NOW - timedelta(days=90, minutes=-job.id)
        await db_session.commit()

    assert await _board(api_client, **params) == (1, [bristol.id])
    assert await _count(db_session, **params) == 1
    # No filter: the earliest member.
    assert await _board(api_client) == (2, [other.id, london.id])


@pytest.mark.asyncio
async def test_a_filter_no_member_passes_lists_nothing(api_client, db_session):
    await _london_bristol(db_session, workplace_type="hybrid")
    assert await _board(api_client, workplace_type=["remote"]) == (0, [])


@pytest.mark.asyncio
async def test_the_read_lens_is_per_posting(api_client, db_session):
    """Read/Unread reads the posting. London read, Bristol
    not: Unread lists the role through Bristol, Read through London."""
    london, bristol, other = await _london_bristol(db_session)
    london.viewed_at = NOW
    other.viewed_at = NOW
    await db_session.commit()

    assert await _board(api_client, viewed="unread") == (1, [bristol.id])
    assert await _board(api_client, viewed="read") == (2, [other.id, london.id])


@pytest.mark.asyncio
async def test_a_facet_counts_a_set_under_every_value_a_member_has(api_client, db_session):
    """Broken rule caught: the facet counts the set under its representative's
    value only, so "Remote (0)" sits beside a filter that lists a role."""
    await _london_bristol(db_session, workplace_type="remote")
    counts = (await api_client.get("/api/facets")).json()["counts"]
    assert counts["workplace_type"] == {"hybrid": 2, "remote": 1}


@pytest.mark.asyncio
async def test_not_for_me_on_any_member_hides_the_role(api_client, db_session):
    """Broken rules caught (two holes in a role-level Not for me): a place
    filter bringing a dismissed role back through a sibling, and Not for me on
    a sibling leaving the role on the unfiltered Board."""
    london, bristol, other = await _london_bristol(db_session)
    db_session.add(JobFeedback(job_id=london.id, verdict="dismissed"))
    await db_session.commit()
    assert await _board(api_client, location_group=["city_bristol"]) == (0, [])

    await db_session.delete(await db_session.get(JobFeedback, london.id))
    db_session.add(JobFeedback(job_id=bristol.id, verdict="dismissed"))
    await db_session.commit()
    assert await _board(api_client) == (1, [other.id])
    # The Not-for-me lens lists the posting the person marked.
    assert (await _board(api_client, dismissed_only=True))[1] == [bristol.id]


@pytest.mark.asyncio
async def test_best_match_lists_the_member_its_text_admits(api_client, db_session, monkeypatch):
    """Broken rule caught: Best match collapses before its text admission, so
    a search only Bristol's team matches finds no role."""
    from tracker.api.routers import jobs as jobs_router

    async def no_query_vector(_text):
        return None

    monkeypatch.setattr(jobs_router, "embed_query", no_query_vector)
    london, bristol, other = await _london_bristol(db_session, team="Infrastructure Tunnelling")

    body = (
        await api_client.get(
            "/api/jobs", params={"sort": "relevance", "q": "tunnelling", "limit": 50}
        )
    ).json()
    assert [item["id"] for item in body["items"]] == [bristol.id]
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_mcp_search_lists_the_member_its_window_admits(db_session, scratch_scope):
    """Broken rule caught: the MCP tool applied its own window (and phrase)
    after the collapse, so an agent asking for roles first seen this month
    found none when London, the first member, was seen in July."""
    import tracker.mcp.server as server
    from tracker.agents.config import AgentAccessConfig, set_agent_access

    await set_agent_access(db_session, AgentAccessConfig(enabled=True, allow_writes=False))
    db_session.add(
        TrackedCompany(
            slug="aecom", display="AECOM", adapter="greenhouse", status="active",
            enabled=True, visible=True, source="catalog",
        )
    )
    london, bristol, other = await _london_bristol(db_session, first_seen=NOW - timedelta(days=5))
    for job in (london, other):
        job.first_seen = NOW - timedelta(days=90, minutes=-job.id)
    await db_session.commit()

    found = await server.search_opportunities(first_seen_within_days=30, query="controls")
    assert [item["id"] for item in found["items"]] == [bristol.id]
    # Without the window, the role is listed once, through London.
    found = await server.search_opportunities(query="controls")
    assert sorted(item["id"] for item in found["items"]) == sorted([london.id, other.id])


# --------------------------------------------------------------------------
# Demand
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demand_books_a_set_opening_once(db_session):
    """Broken rule caught: every member's `opened` is new demand (3), or the
    later ones move to reposted."""
    london, bristol, leeds, other = await _aecom(db_session)
    run = ScrapeRun(status="ok", started_at=NOW, per_source={}, drift_alerts=[])
    db_session.add(run)
    await db_session.flush()
    for job in (london, bristol, leeds, other):
        db_session.add(
            JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="opened", created_at=NOW)
        )
    db_session.add(
        JobLifecycleEvent(job_id=bristol.id, run_id=run.id, event_type="reopened", created_at=NOW)
    )
    await db_session.commit()

    # The events' own day: the wall clock can pass UTC midnight after NOW was taken.
    await compute_demand_metrics(db_session, today=demand_day(NOW))

    uk = (
        await db_session.scalars(
            select(DemandMetric).where(
                DemandMetric.company == "aecom", DemandMetric.location_group == "uk"
            )
        )
    ).one()
    assert uk.new_count == 2  # the set once, and the other role
    assert uk.reposted_count == 0


@pytest.mark.parametrize("event, role, later, bucket", [
    ("opened", None, True, None),
    ("reopened", None, True, None),
    ("opened", "repost", True, None),
    ("closed", None, True, "closed_count"),
    ("opened", None, False, "new_count"),
    ("opened", "repost", False, "reposted_count"),
])
def test_event_bucket_drops_a_later_members_opening_and_relisting_only(event, role, later, bucket):
    assert event_bucket(event, role, later_in_place_set=later, new_listing=True) == bucket


# --------------------------------------------------------------------------
# A saved posting closes while its role stays listed
# --------------------------------------------------------------------------


async def _close_saved(session, job: Job) -> ScrapeRun:
    session.add(Favorite(job_id=job.id))
    job.status = "closed"
    job.closed_at = NOW
    run = ScrapeRun(status="ok", started_at=NOW, finished_at=NOW, per_source={}, drift_alerts=[])
    session.add(run)
    await session.flush()
    session.add(JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="closed", created_at=NOW))
    await session.commit()
    # The pass runs before notifications and drops the closed member.
    await rebuild_place_sets(session)
    return run


@pytest.mark.asyncio
async def test_a_saved_posting_closing_while_its_role_is_listed_elsewhere(db_session):
    """Broken rule caught: the notification reads the stored set (which the
    rebuild already left), so the person is told the role closed."""
    london, bristol, leeds, other = await _aecom(db_session)
    run = await _close_saved(db_session, bristol)

    await generate_notifications(db_session, run, include_run=False)

    row = (await db_session.scalars(select(Notification))).one()
    assert row.category == "saved_update"
    assert row.title == f"{_company_label('aecom')} still lists a role you saved in 2 other places"
    assert "London, UK, Leeds, UK" in row.body
    # The row opens the earliest open posting; the saved one stays saved.
    assert row.job_id == london.id
    assert [e["job_id"] for e in row.meta["listed_elsewhere"]] == [london.id, leeds.id]
    assert (await db_session.scalars(select(Favorite.job_id))).all() == [bristol.id]


@pytest.mark.asyncio
async def test_a_saved_posting_of_a_two_place_role_still_finds_the_other(db_session):
    """Broken rule caught: a set of two dissolves when one closes, so a
    stored-set read finds nothing; the rule still pairs them."""
    london = await _job(db_session, 1, "London")
    bristol = await _job(db_session, 2, "Bristol")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    run = await _close_saved(db_session, bristol)

    await generate_notifications(db_session, run, include_run=False)

    row = (await db_session.scalars(select(Notification))).one()
    assert row.title.endswith("still lists a role you saved in another place")
    assert row.job_id == london.id


@pytest.mark.asyncio
async def test_closed_still_means_closed_when_nothing_else_is_listed(db_session):
    """Negative controls: a lone role, and a posting the person split out."""
    london, bristol, leeds, other = await _aecom(db_session)
    await review_place_set_member(db_session, leeds.id, "different")
    run = await _close_saved(db_session, other)
    leeds_run = await _close_saved(db_session, leeds)

    assert await still_listed_elsewhere(db_session, [other.id, leeds.id]) == {}
    await generate_notifications(db_session, run, include_run=False)
    await generate_notifications(db_session, leeds_run, include_run=False)

    rows = (await db_session.scalars(select(Notification))).all()
    assert sorted((r.category, r.job_id) for r in rows) == sorted(
        [("closed", other.id), ("closed", leeds.id)]
    )
