"""The API counts successful mutations by route template, only while sharing
(docs/architecture.md).

Contracts:

* Every unsafe route is classified: counted under one stable action, or not
  counted with a reason. A new endpoint fails here by name until it is decided.
* A 2xx counts; a 4xx, a request the loopback boundary refuses, and anything
  while usage is not shared do not. The action comes from the route TEMPLATE,
  so no id or slug from the URL reaches the tally.
* An unhandled crash leaves the response the 500 it was and is tallied only as
  a scrubbed shape, only while crash reports are shared.
* The tally drains to the outbox through the recorder, which checks consent
  again; with usage not shared it is discarded unwritten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.middleware.cors import CORSMiddleware

from tests.usage_fixtures import NOW, share
from tracker.api.app import app
from tracker.api.boundary import LoopbackBoundary
from tracker.api.usage_counter import ACTIONS, NOT_COUNTED, UsageCounter
from tracker.db.models import UsageEvent
from tracker.usage_stats import registry
from tracker.usage_stats.consent import NOTHING_SHARED, get_sharing
from tracker.usage_stats.registry import Group
from tracker.usage_stats.tally import TALLY, ApiTally, drain

pytestmark = pytest.mark.usefixtures("no_escape")

ROUTE_TABLE = Path(__file__).parent / "fixtures" / "route_table.json"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def tally(monkeypatch):
    """The API's own tally, emptied, with both flags on for the test."""
    monkeypatch.setattr(TALLY, "usage", True)
    monkeypatch.setattr(TALLY, "crashes", True)
    TALLY.take()
    yield TALLY
    TALLY.take()


def test_every_unsafe_route_is_counted_or_excused() -> None:
    routes = json.loads(ROUTE_TABLE.read_text())["routes"]
    unsafe = {(r["method"], r["path"]) for r in routes if r["method"] in UNSAFE}
    assert set(ACTIONS) | set(NOT_COUNTED) == unsafe
    assert not set(ACTIONS) & set(NOT_COUNTED)
    assert all(reason.strip() for reason in NOT_COUNTED.values())


def test_the_action_names_are_the_catalogue() -> None:
    assert set(ACTIONS.values()) == registry.ACTIONS
    assert len(set(ACTIONS.values())) == len(ACTIONS), "two routes share an action name"


def test_the_boundary_stays_outermost_and_the_counter_inside_it() -> None:
    order = [m.cls for m in app.user_middleware]
    assert order[0] is LoopbackBoundary
    assert order.index(UsageCounter) > order.index(CORSMiddleware)


@pytest.mark.asyncio
async def test_a_successful_mutation_counts_by_template(api_client, tally) -> None:
    response = await api_client.put("/api/settings/locale", json={"language": "en", "region": None})
    assert response.status_code == 200
    assert dict(tally.actions) == {"locale_set": 1}
    # A read is no action, however it answers.
    assert (await api_client.get("/api/settings/locale")).status_code == 200
    assert dict(tally.actions) == {"locale_set": 1}


@pytest.mark.asyncio
async def test_a_failed_or_refused_mutation_does_not_count(api_client, tally) -> None:
    missing = await api_client.put("/api/jobs/987654/favorite")
    assert missing.status_code == 404
    refused = await api_client.put(
        "/api/settings/locale",
        json={"language": "en", "region": None},
        headers={"Origin": "https://evil.example"},
    )
    assert refused.status_code == 403
    invalid = await api_client.put("/api/settings/locale", json={"language": "not a tag!"})
    assert invalid.status_code == 422
    assert dict(tally.actions) == {}


@pytest.mark.asyncio
async def test_nothing_is_tallied_while_usage_is_not_shared(api_client, monkeypatch) -> None:
    TALLY.take()
    monkeypatch.setattr(TALLY, "usage", False)
    response = await api_client.put("/api/settings/locale", json={"language": "en", "region": None})
    assert response.status_code == 200
    assert dict(TALLY.actions) == {}


def _crashing_app(tally: ApiTally) -> FastAPI:
    crashing = FastAPI()

    @crashing.post("/api/boom/{company}")
    async def boom(company: str) -> dict:
        raise RuntimeError(f"board for {company} broke")

    @crashing.get("/api/boom/{company}")
    async def read_boom(company: str) -> dict:
        raise RuntimeError(f"board for {company} broke")

    crashing.add_middleware(UsageCounter, tally=tally)
    return crashing


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "GET"])
async def test_a_crash_stays_a_500_and_is_tallied_scrubbed(method) -> None:
    # A read crashes too, and most requests are reads.
    tally = ApiTally(usage=True, crashes=True)
    transport = ASGITransport(app=_crashing_app(tally), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8010") as client:
        response = await client.request(method, "/api/boom/zyxwv-robotics")
    assert response.status_code == 500
    assert dict(tally.actions) == {}
    [shape] = tally.crashes_pending
    assert shape.type == "RuntimeError"
    assert "zyxwv" not in json.dumps(shape.__dict__, default=str)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "GET"])
async def test_a_crash_is_not_tallied_without_crash_sharing(method) -> None:
    tally = ApiTally(usage=True, crashes=False)
    transport = ASGITransport(app=_crashing_app(tally), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8010") as client:
        assert (await client.request(method, "/api/boom/x")).status_code == 500
    assert tally.crashes_pending == []


@pytest.mark.asyncio
async def test_the_drain_writes_counts_and_refreshes_the_flags(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    tally = ApiTally(usage=True, crashes=True)
    tally.count("save_job")
    tally.count("save_job")
    tally.count("locale_set")
    assert await drain(db_session, tally, now=NOW) == 3
    rows = list((await db_session.execute(select(UsageEvent))).scalars())
    counts = {r.props["action"]: r.count for r in rows if r.name == "daily_action"}
    assert counts == {"save_job": 2, "locale_set": 1}
    # The first save after sharing is also a milestone, once.
    assert [r.name for r in rows if r.kind == "milestone"] == ["first_job_saved"]
    tally.count("save_job")
    await drain(db_session, tally, now=NOW)
    milestones = (await db_session.execute(select(UsageEvent).where(UsageEvent.kind == "milestone"))).scalars().all()
    assert len(milestones) == 1
    # Crash reports were never answered, so the drain turned that flag off.
    assert tally.usage is True and tally.crashes is False


@pytest.mark.asyncio
async def test_the_drain_discards_when_usage_is_not_shared(db_session, sharing_allowed) -> None:
    assert await get_sharing(db_session) == NOTHING_SHARED
    tally = ApiTally(usage=True, crashes=True)
    tally.count("save_job")
    assert await drain(db_session, tally, now=NOW) == 0
    assert (await db_session.execute(select(UsageEvent))).first() is None
    assert tally.usage is False and dict(tally.actions) == {}
