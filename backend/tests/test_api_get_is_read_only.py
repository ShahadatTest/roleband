"""A GET never commits.

A GET is what a foreign page can issue with no preflight and no `Origin` — an
`<img src>` is enough — so a GET that writes is a write any web page can make,
and one the loopback boundary (`tracker/api/boundary.py`) cannot tell from a
read. It is also a read that can queue behind a running scrape's row locks
(see `/api/companies/discovery`). So the rule is structural: walk every GET in
the frozen route table against a session that refuses to commit, and fail by
route name. A route added later is walked by default. No route is exempt; the
instrument's own control is a write route walked the same way, which must be
seen to commit.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.company_store import ensure_builtins
from tracker.db.models import Job
from tracker.profiles.seed import ensure_company_profiles

pytestmark = pytest.mark.asyncio

_ROUTES = json.loads((Path(__file__).parent / "fixtures" / "route_table.json").read_text())["routes"]
GET_ROUTES = sorted({r["path"] for r in _ROUTES if r["method"] == "GET"})

class CommitRefused(RuntimeError):
    """Raised inside the handler, so the write never lands in the scratch DB."""


@pytest_asyncio.fixture
async def seeded_job(db_session):
    """What startup and one scrape leave behind, so handlers get past their 404s."""
    await ensure_builtins(db_session)
    await db_session.commit()
    await ensure_company_profiles(db_session)
    await db_session.commit()
    now = datetime.now(UTC)
    job = Job(
        company="google", req_id="4410", dedupe_key="google:4410",
        title="Staff Product Manager, Search", url="https://careers.google.com/jobs/4410",
        level_band="staff", family="product_management", track="product_program",
        locations=["Mountain View, CA, USA"], location_groups=["silicon_valley"],
        status="open", in_scope=True, first_seen=now, last_seen=now,
    )
    db_session.add(job)
    await db_session.commit()
    return job


def _url(path: str, job: Job) -> str:
    samples = {"job_id": str(job.id), "slug": "google", "band": "strong", "full_path": "board"}
    return re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: samples.get(m.group(1), "1"), path)


async def test_no_get_route_commits(db_session, seeded_job, no_escape):
    from tracker.api.app import app
    from tracker.api.deps import get_session

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    commits: list[str] = []

    async def refusing_session(request: Request):
        async with factory() as session:

            def refuse(_session):
                commits.append(request.url.path)
                raise CommitRefused(request.url.path)

            event.listen(session.sync_session, "before_commit", refuse)
            yield session

    committed: dict[str, list[str]] = {}
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = refusing_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://127.0.0.1:8010",
        ) as client:
            for path in GET_ROUTES:
                commits.clear()
                await client.get(_url(path, seeded_job))
                if commits:
                    committed[path] = list(commits)
            # The control: a write commits, so a listener that never fired
            # fails here instead of passing every GET silently.
            commits.clear()
            await client.put("/api/profile/pay-floor", json={"amount": 200_000, "currency": "USD"})
            control = list(commits)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert not committed, f"GET routes that commit: {sorted(committed)}"
    assert control == ["/api/profile/pay-floor"], "the commit listener never fired"
