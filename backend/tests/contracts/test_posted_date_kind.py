"""What each source's posting date is, declared per adapter.

The headline listing age starts at the employer's FIRST published date when it
is earlier than our first sighting. An update time is never a posting date: it
moves on every edit, so a source whose `posted_at` falls back to one re-dates
its postings each time an employer fixes a typo. Greenhouse offers such a field
(`updated_at`) and Eightfold another (`t_update`); neither adapter reads it as a
posting date, and each adapter says what feeds its `posted_at` so the next one
is written down before it lands.

Each check fails for a plausible regression: a new adapter that inherits a
kind it never chose, a kind outside the vocabulary, a `none` source that
starts emitting dates, and either update-time fallback coming back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import httpx
import pytest

from tests.contracts.conftest import MODE_NORMAL, build_harness, load_fixture, run_fetch
from tracker.connectors import ADAPTER_REGISTRY, build_adapter
from tracker.connectors.listing.base import PostedDate, RateLimiter

KINDS = set(get_args(PostedDate))


def test_the_vocabulary_has_no_update_kind():
    assert KINDS == {"published", "created", "none"}


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_every_adapter_declares_its_date_kind_on_its_own_class(name):
    """On the class itself, not inherited: `AvatureTlsAdapter` subclasses
    `AvatureAdapter` and the sitemap boards share a base, and each still has to
    say what its own route serves."""
    cls = ADAPTER_REGISTRY[name]
    assert "posted_date" in vars(cls), f"{name}: {cls.__name__} declares no posted_date"
    assert vars(cls)["posted_date"] in KINDS, f"{name}: {vars(cls)['posted_date']!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", sorted(n for n, cls in ADAPTER_REGISTRY.items() if vars(cls).get("posted_date") == "none")
)
async def test_a_source_declared_dateless_dates_nothing_in_its_fixtures(name):
    jobs = await run_fetch(build_harness(name, MODE_NORMAL))

    assert jobs, f"{name}: fixtures yielded no RawJobs"
    dated = [job.req_id for job in jobs if job.posted_at is not None]
    assert not dated, f"{name} is declared `none` but dates {dated}"


def test_at_least_one_adapter_is_declared_dateless():
    """The control for the check above: with no `none` adapter it would pass
    by parametrizing over nothing."""
    assert any(vars(cls).get("posted_date") == "none" for cls in ADAPTER_REGISTRY.values())


# --------------------------------------------------------------------------- #
# The two update-time fallbacks the sources offer
# --------------------------------------------------------------------------- #


async def _greenhouse(jobs: list[dict]) -> dict:
    adapter = build_adapter("acme", "greenhouse", board_token="acme")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"jobs": jobs, "meta": {"total": len(jobs)}})
    ))
    adapter._limiter = RateLimiter(0.0)
    return {job.req_id: job async for job in adapter.fetch()}


def _greenhouse_job(n: int, **dates: str) -> dict:
    return {
        "id": n, "title": f"Role {n}", "location": {"name": "Austin, TX"},
        "offices": [{"id": 1, "name": "Austin, TX"}],
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{n}",
        "content": "<p>x</p>", **dates,
    }


@pytest.mark.asyncio
async def test_a_greenhouse_job_with_only_an_update_time_has_no_posting_date():
    jobs = await _greenhouse([
        _greenhouse_job(1, updated_at="2026-09-20T10:00:00-04:00"),
        _greenhouse_job(2, updated_at="2026-09-20T10:00:00-04:00",
                        first_published="2026-06-01T09:00:00-04:00"),
    ])

    assert jobs["1"].posted_at is None, "an update time is never a posting date"
    assert jobs["2"].posted_at == datetime(2026, 6, 1, 13, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_eightfold_dates_a_posting_by_its_creation_not_its_last_edit():
    """Netflix's v2 fixture carries both: every row's `t_update` is later than
    its `t_create`, so preferring it re-dates each posting to its last edit."""
    positions = [
        *load_fixture("eightfold", "page1.json")["positions"],
        *load_fixture("eightfold", "page2.json")["positions"],
    ]
    created = {datetime.fromtimestamp(p["t_create"], tz=UTC) for p in positions}
    updated = {datetime.fromtimestamp(p["t_update"], tz=UTC) for p in positions}
    assert not created & updated, "the fixture must tell the two apart"

    jobs = await run_fetch(build_harness("eightfold", MODE_NORMAL))

    assert jobs and {job.posted_at for job in jobs} <= created
