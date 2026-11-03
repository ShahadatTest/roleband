"""The Board shows the companies the user follows.

Unfollowing leaves `visible` true, so if `visible` alone decided what the Board
shows, the open postings of companies the user stopped following would stay on
it, unverified and growing. Nothing scans a company nobody follows, and closure needs a scan, so they would never
leave on their own.

Four companies, one posting each, in every test: followed and visible (on the
Board), unfollowed, hidden but followed, and one with no roster row at all (a
posting the Board keeps). Every count must agree with the Board, and
what the user saved stays theirs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import update

import tracker.mcp.server as server
from tracker.agents.config import AgentAccessConfig, set_agent_access
from tracker.api.routers.settings import _board_count
from tracker.db.models import Favorite, Job, JobLifecycleEvent, TrackedCompany
from tracker.notifications.digest import collect_digest_matches

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

NOW = datetime.now(UTC)


def _company(slug: str, *, enabled: bool = True, visible: bool = True) -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=slug.title(), adapter="greenhouse", status="active",
        enabled=enabled, visible=visible, source="directory-set",
    )


def _job(job_id: int, company: str) -> Job:
    return Job(
        id=job_id, company=company, req_id=f"r{job_id}", dedupe_key=f"{company}:r{job_id}",
        title="Staff Product Manager", url=f"https://careers.example.test/{job_id}",
        locations=["San Francisco, CA"], location_groups=["silicon_valley"], workplace_type="hybrid",
        level_band="staff", family="product_management", track="product_program",
        status="open", in_scope=True, first_seen=NOW - timedelta(days=8), last_seen=NOW - timedelta(days=7),
    )


@pytest_asyncio.fixture
async def board(db_session, scratch_scope) -> dict[str, int]:
    await set_agent_access(db_session, AgentAccessConfig(enabled=True, allow_writes=False))
    db_session.add_all([
        _company("followed"),
        _company("dormant", enabled=False),
        _company("shadow", visible=False),
    ])
    jobs = {"followed": _job(1, "followed"), "dormant": _job(2, "dormant"),
            "shadow": _job(3, "shadow"), "rosterless": _job(4, "rosterless")}
    db_session.add_all(jobs.values())
    await db_session.flush()
    db_session.add(Favorite(job_id=2))
    await db_session.commit()
    return {name: job.id for name, job in jobs.items()}


async def _ids(api_client, query: str = "") -> set[int]:
    response = await api_client.get(f"/api/jobs?limit=500{query}")
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


async def test_every_count_is_the_boards_count(api_client, db_session, board):
    """No surface counts a posting the Board would not show: the
    Board, its facets, the header, the Walk's "on your Board", the agent."""
    on_board = await _ids(api_client)
    assert on_board == {board["followed"], board["rosterless"]}

    stats = (await api_client.get("/api/stats")).json()
    facets = (await api_client.get("/api/facets")).json()
    summary = await server.get_radar_summary()
    agent = {item["id"] for item in (await server.search_opportunities(limit=50))["items"]}
    assert stats["open_total"] == facets["total"] == await _board_count(db_session) == len(on_board) == 2
    assert summary["open_opportunities"] == 2
    assert agent == on_board
    assert "dormant" not in facets["companies"] and "followed" in facets["companies"]


async def test_a_saved_role_at_an_unfollowed_company_stays_the_users(api_client, board):
    dormant = board["dormant"]
    assert await _ids(api_client, "&favorites_only=true") == {dormant}
    assert await _ids(api_client, f"&ids={dormant}") == {dormant}, "Compare reads by id"
    assert (await api_client.get(f"/api/jobs/{dormant}")).status_code == 200
    saved = await server.search_opportunities(saved_only=True)
    assert [item["id"] for item in saved["items"]] == [dormant]
    # And it says nothing checks it: the Saved row and Job detail both
    # carry the flag; a followed company's row never does.
    saved_rows = (await api_client.get("/api/jobs?favorites_only=true")).json()["items"]
    assert [row["company_unfollowed"] for row in saved_rows] == [True]
    assert (await api_client.get(f"/api/jobs/{dormant}")).json()["company_unfollowed"] is True
    followed = (await api_client.get(f"/api/jobs/{board['followed']}")).json()
    assert followed["company_unfollowed"] is False
    board_rows = (await api_client.get("/api/jobs")).json()["items"]
    assert {row["company_unfollowed"] for row in board_rows} == {False}


async def test_the_company_card_and_profile_count_what_the_board_shows(api_client, board):
    """"View N open roles" links to the Board: an unfollowed company's link
    would open on nothing, so it counts nothing and says why."""
    followed = (await api_client.get("/api/companies/followed/card")).json()
    dormant = (await api_client.get("/api/companies/dormant/card")).json()
    shadow = (await api_client.get("/api/companies/shadow/card")).json()
    assert (followed["open_roles"], followed["unfollowed"]) == (1, False)
    assert (dormant["open_roles"], dormant["unfollowed"]) == (0, True)
    # Hidden is the user's own switch over a followed company, not unfollowing.
    assert (shadow["open_roles"], shadow["unfollowed"]) == (0, False)


async def test_the_digest_announces_only_what_the_board_shows(db_session, board):
    """The digest's own rule ("never advertise a role the Board would not
    display") must read the hidden list, or a hidden company's new roles reach
    it as an unfollowed one's would."""
    today = datetime.now().astimezone()
    db_session.add_all([
        JobLifecycleEvent(job_id=job_id, event_type="opened", detail={}, created_at=today)
        for job_id in board.values()
    ])
    # Each opened today: its first sighting, as the writer stores it.
    await db_session.execute(update(Job).where(Job.id.in_(list(board.values()))).values(first_seen=today))
    await db_session.commit()
    day: date = today.date()
    announced = {match.job_id for match in await collect_digest_matches(db_session, day, set())}
    assert announced == {board["followed"], board["rosterless"]}


async def test_unfollowing_deletes_and_closes_nothing(api_client, db_session, board):
    before = {job.id: (job.status, job.last_seen) for job in await _all(db_session)}
    row = await db_session.get(TrackedCompany, "followed")
    row.enabled = False
    await db_session.commit()
    assert board["followed"] not in await _ids(api_client)
    assert {job.id: (job.status, job.last_seen) for job in await _all(db_session)} == before

    row.enabled = True
    await db_session.commit()
    assert board["followed"] in await _ids(api_client), "back at once, before any scan"


async def _all(session) -> list[Job]:
    from sqlalchemy import select

    session.expire_all()
    return list((await session.scalars(select(Job))).all())
