"""Paging and window inputs are bounded at the request boundary.

Unbounded, a negative `limit` or `offset` reaches PostgreSQL's LIMIT/OFFSET and
comes back as a 500 (after the route has run its count queries); a negative
`limit` slices a Python list silently; a window of a million days overflows a
date into a 500. Each is a 422 before any database work, and the values
the dashboard really sends (Statistics' All-time is `days=0`, the Board's
count-only baseline is `limit=1`) still answer 200.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

REFUSED = [
    ("/api/notifications", {"offset": -1}),
    ("/api/notifications", {"limit": -1}),
    ("/api/notifications", {"limit": 0}),
    ("/api/notifications", {"limit": 201}),
    ("/api/jobs", {"offset": -1}),
    ("/api/jobs", {"limit": -1}),
    ("/api/jobs", {"posted_within_days": -1}),
    ("/api/jobs", {"posted_within_days": 1_000_000}),
    ("/api/jobs/1/similar", {"limit": -1}),
    ("/api/lineage/review", {"offset": -1}),
    ("/api/lineage/review", {"limit": -1}),
    ("/api/twins/review", {"offset": -1}),
    ("/api/runs", {"limit": -1}),
    ("/api/pursuits", {"limit": -1}),
    ("/api/skills/top", {"limit": -1}),
    ("/api/skills/trends", {"limit": -1}),
    ("/api/skills/trends", {"days": 1_000_000}),
    ("/api/skills/overlap", {"limit_companies": -1}),
    ("/api/statistics/overview", {"days": -1}),
    ("/api/statistics/overview", {"days": 1_000_000}),
    ("/api/statistics/velocity", {"days": 1_000_000}),
    ("/api/statistics/comp-trends", {"days": 1_000_000}),
    ("/api/statistics/disclosure-trends", {"days": 1_000_000}),
]

ACCEPTED = [
    ("/api/notifications", {"limit": 1, "offset": 0}),
    ("/api/notifications", {"limit": 200}),
    ("/api/jobs", {"limit": 1}),
    ("/api/jobs", {"posted_within_days": 30}),
    ("/api/statistics/overview", {"days": 0}),  # All-time
    ("/api/statistics/velocity", {"days": 0}),
    ("/api/skills/trends", {"days": 0}),
    ("/api/skills/overlap", {"min_jobs": 2, "limit_companies": 10}),
]


@pytest.mark.parametrize(("path", "params"), REFUSED, ids=lambda v: str(v))
async def test_an_out_of_range_input_is_refused_before_any_query(api_client, path, params):
    response = await api_client.get(path, params=params)
    assert response.status_code == 422, (path, params, response.status_code, response.text[:200])


@pytest.mark.parametrize(("path", "params"), ACCEPTED, ids=lambda v: str(v))
async def test_what_the_dashboard_sends_still_answers(api_client, path, params):
    response = await api_client.get(path, params=params)
    assert response.status_code == 200, (path, params, response.text[:200])
