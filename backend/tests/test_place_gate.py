"""A place read from a posting's detail page is spent only on a posting the rest
of the scope admits.

Workday "N Locations" rows and Avature "Multiple Locations" cards
name no place in the listing, and locations fail closed, so the
adapter reads each posting's detail to place it before scope runs. Done for
every such row, that read costs hundreds of requests per scan at the pacing
interval and can overrun the time budget before a listing finishes. A posting the role gate drops is dropped wherever it is.

End to end through `collect_source` with the real Workday adapter on a mock
transport: the gate `collect_source` installs is the scope minus location.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.factories import NoComp, scope_filter
from tracker.connectors.listing import base
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.workday import WorkdayAdapter
from tracker.enrich.enricher import annotate, passes_filters
from tracker.platform.ratelimit import RateLimiterPool
from tracker.schema import RawJob
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows.collection import collect_source

_CONSENT = SOURCE_REVIEWS["workday"].wall_fingerprint

# `collect_source` enters the adapter, and entering builds the real tier client:
# every client the adapter makes is the mock below, and `no_escape` refuses any
# network transport that slips past it.
pytestmark = pytest.mark.usefixtures("no_escape")


def _row(req: str, title: str) -> dict:
    return {
        "title": title,
        "externalPath": f"/job/US-CA-Santa-Clara/{title.replace(' ', '-')}_{req}",
        "locationsText": "3 Locations",
        "postedOn": "Posted Today",
        "bulletFields": [req],
    }


_IN_ROLE = _row("JR1", "Senior Manager, Software Engineering")
_OFF_ROLE = _row("JR2", "Senior Verification Engineer")
_DETAIL = {"jobPostingInfo": {
    "jobDescription": "<p>Lead the team.</p>",
    "location": "US, CA, Santa Clara",
    "additionalLocations": ["US, TX, Austin"],
    "startDate": "2026-09-20",
}}


def _placed(row: dict) -> RawJob:
    return RawJob(company="nvidia", req_id=row["bulletFields"][0], title=row["title"],
                  url="https://example.test", locations=["US, CA, Santa Clara"])


# The scope is built from the in-role row's own annotation, so the test holds
# whatever the taxonomy calls it; the off-role row must fail the role gate.
_ANN = annotate(_placed(_IN_ROLE))
_SCOPE = scope_filter(
    bands={_ANN.band.value},
    roles={_ANN.family},
    tracks={_ANN.track.value},
    locations=_ANN.location_groups,
    domains=(),
)


def _adapter(gets: list[str], monkeypatch) -> WorkdayAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            gets.append(request.url.path.rsplit("_", 1)[-1])
            return httpx.Response(200, json=_DETAIL)
        body = json.loads(request.content)
        rows = [_IN_ROLE, _OFF_ROLE] if body["offset"] == 0 else []
        return httpx.Response(200, json={"total": 2, "jobPostings": rows})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(base, "make_tier_client", lambda *a, **kw: httpx.AsyncClient(transport=transport))
    adapter = WorkdayAdapter("nvidia")
    adapter._client = httpx.AsyncClient(transport=transport)
    adapter._limiter = RateLimiter(0.0)
    return adapter


def test_the_fixture_rows_split_on_role_not_place():
    assert _ANN.family and _ANN.location_groups
    assert passes_filters(_ANN, _SCOPE)
    assert not passes_filters(annotate(_placed(_OFF_ROLE)), _SCOPE, read_place=False)


def test_read_place_false_skips_only_the_location_axis():
    abroad = scope_filter(
        bands=_SCOPE.enabled_bands,
        roles=_SCOPE.enabled_roles,
        tracks=_SCOPE.enabled_tracks,
        locations={"no_such_group"},
        domains=(),
    )
    assert not passes_filters(_ANN, abroad)
    assert passes_filters(_ANN, abroad, read_place=False)


@pytest.mark.asyncio
async def test_collection_places_only_the_row_the_role_gate_admits(monkeypatch):
    gets: list[str] = []
    adapter = _adapter(gets, monkeypatch)
    result = await collect_source(
        "nvidia",
        {"adapter": "workday", "consent": _CONSENT},
        _SCOPE,
        NoComp(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, **kw: adapter,
    )

    # One detail read, for the in-role row; the off-role row costs nothing.
    assert gets == ["JR1"]
    kept = {job.raw.req_id: job for job in result.enriched}
    assert list(kept) == ["JR1"], "the placed in-role row is kept"
    assert kept["JR1"].raw.locations == ["US, CA, Santa Clara", "US, TX, Austin"]
    assert result.list_complete, "skipping a place read never costs the listing"


@pytest.mark.asyncio
async def test_an_adapter_outside_collection_still_places_every_row(monkeypatch):
    """Smoke and tests build adapters with no gate: every counted row is read."""
    gets: list[str] = []
    adapter = _adapter(gets, monkeypatch)
    adapter.collection_consent = _CONSENT
    async with adapter:
        [job async for job in adapter.fetch()]
    assert sorted(gets) == ["JR1", "JR2"]
