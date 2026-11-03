"""Role discovery is asked of the supervisor, one at a time, outside the request.

Every trigger (the Settings "refresh scope" button and adding a company) asks
for a discovery, or repeated clicks pile up concurrent full-source scans. The DB
advisory lock does NOT contain them: discovery releases it between companies so a
waiting scrape can slip in, and a second discovery can take it in exactly that
window, then sit on the lock and skip every scrape behind it. So a request is
refused while one is queued or running.
"""

import pytest
from sqlalchemy import select

from tracker.api import job_requests
from tracker.db import job_store
from tracker.db.models import JobRequest
from tracker.supervisor.registry import job

pytestmark = pytest.mark.asyncio


async def _requests(session) -> list[JobRequest]:
    session.expire_all()
    return list(await session.scalars(select(JobRequest).where(JobRequest.job == "role_discovery")))


async def test_a_company_s_discovery_is_scoped_to_it_and_capped(db_session):
    assert await job_requests.ring_role_discovery(db_session, "acme", requested_by="add_company")
    await db_session.commit()

    [request] = await _requests(db_session)
    command = [*job("role_discovery").command, *request.args["argv"]]
    assert command[1:5] == ["-m", "tracker.supervisor.entries", "role_discovery", "--company"]
    assert "acme" in command
    assert command[command.index("--max-list") + 1] == "150"


async def test_a_second_discovery_is_refused_while_one_is_queued(db_session):
    assert await job_requests.ring_role_discovery(db_session, max_list=600, requested_by="scope_refresh")
    await db_session.commit()
    assert not await job_requests.ring_role_discovery(db_session, max_list=600, requested_by="scope_refresh")
    assert len(await _requests(db_session)) == 1


async def test_a_second_discovery_is_refused_while_one_is_running(db_session):
    await job_requests.ring_role_discovery(db_session, max_list=600, requested_by="scope_refresh")
    await job_store.claim(db_session, "role_discovery")
    await db_session.commit()
    assert not await job_requests.ring_role_discovery(db_session, ["acme"], requested_by="add_company")


async def test_a_finished_discovery_never_blocks_the_next(db_session):
    await job_requests.ring_role_discovery(db_session, max_list=600, requested_by="scope_refresh")
    _request, run = await job_store.claim(db_session, "role_discovery")
    await job_store.finish_run(db_session, run.id, state=job_store.EXITED, exit_code=0)
    await db_session.commit()
    assert await job_requests.ring_role_discovery(db_session, max_list=600, requested_by="scope_refresh")


async def test_a_running_scan_or_re_embed_is_not_mistaken_for_a_running_discovery(db_session):
    await job_store.open_run(db_session, "scan", "scan", trigger="schedule")
    await job_store.ring(db_session, "reembed", requested_by="settings")
    await db_session.commit()
    assert await job_requests.ring_role_discovery(db_session, max_list=600, requested_by="scope_refresh")


async def test_the_scope_refresh_passes_the_answered_places_to_discovery(db_session):
    await job_requests.ring_role_discovery(
        db_session, max_list=600, locations=["uk", "city_2643743"], requested_by="scope_refresh"
    )
    await db_session.commit()
    [request] = await _requests(db_session)
    argv = request.args["argv"]
    assert argv[argv.index("--location") + 1 :] == ["uk", "city_2643743"]
