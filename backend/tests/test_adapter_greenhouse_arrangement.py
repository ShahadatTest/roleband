"""A Greenhouse location that states HOW is not a place.

A work arrangement in `location.name` belongs in `workplace_type`;
`offices` supplies the places. With no office, the location text is retained
so the posting remains visible.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.greenhouse import work_arrangement
from tracker.schema import WorkplaceType


def _job(n: int, location: str, offices: list[str]) -> dict:
    return {
        "id": n, "title": f"Role {n}", "location": {"name": location},
        "offices": [{"id": i, "name": name} for i, name in enumerate(offices)],
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{n}",
        "first_published": "2026-09-01T00:00:00Z", "content": "<p>x</p>",
    }


async def _fetch(jobs: list[dict]) -> dict[str, object]:
    adapter = build_adapter("acme", "greenhouse", board_token="acme")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"jobs": jobs, "meta": {"total": len(jobs)}})
    ))
    adapter._limiter = RateLimiter(0.0)
    return {job.req_id: job async for job in adapter.fetch()}


@pytest.mark.asyncio
async def test_an_arrangement_with_an_office_is_a_workplace_not_a_place():
    jobs = await _fetch([
        _job(1, "Hybrid", ["Austin, TX", "New York, NY"]),
        _job(2, "Distributed", ["Toronto, ON"]),
        _job(3, "In-Office", ["London, United Kingdom"]),
        _job(4, "Hybrid or Remote", ["Seattle, WA"]),
    ])

    assert (jobs["1"].locations, jobs["1"].workplace_type) == (["Austin, TX", "New York, NY"], WorkplaceType.HYBRID)
    assert (jobs["2"].locations, jobs["2"].workplace_type) == (["Toronto, ON"], WorkplaceType.REMOTE)
    assert (jobs["3"].locations, jobs["3"].workplace_type) == (["London, United Kingdom"], WorkplaceType.ONSITE)
    assert jobs["4"].workplace_type is WorkplaceType.REMOTE  # remote-eligible


@pytest.mark.asyncio
async def test_an_arrangement_is_kept_when_it_is_the_only_location():
    """A posting with no place at all is invisible: with no office
    to name one, the arrangement stays what the board gave us."""
    jobs = await _fetch([_job(1, "Remote", [])])
    assert (jobs["1"].locations, jobs["1"].workplace_type) == (["Remote"], WorkplaceType.REMOTE)


@pytest.mark.asyncio
async def test_a_place_in_the_location_field_is_untouched():
    jobs = await _fetch([_job(1, "San Francisco, CA", ["San Francisco, CA", "Seattle, WA"])])
    assert jobs["1"].locations == ["San Francisco, CA", "Seattle, WA"]
    assert jobs["1"].workplace_type is WorkplaceType.UNKNOWN


@pytest.mark.parametrize("name", ["Remote - US", "San Francisco, CA", "Remote India", "", None])
def test_only_a_pure_arrangement_reads_as_one(name):
    assert work_arrangement(name) is None
