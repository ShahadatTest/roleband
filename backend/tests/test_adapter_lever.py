"""Lever transport adapter and detail connector.

Two behaviors get the most attention here because they are the ones that would
fail silently in production:

* **Termination without a declared total.** Lever publishes no count, so a page
  shorter than the requested `limit` is the only end-of-board signal. If that
  fails, paging runs to `_MAX_PAGES` and records a truncated listing.
* **Change detection without a trustworthy date.** Lever exposes `createdAt`
  and no `updatedAt`, so an edited posting keeps its original timestamp forever.
  Anything that decided "unchanged" from the source's date would go blind to
  every edit; the content fingerprint is what must notice.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors.detail import structure_job_detail
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.lever import LeverAdapter
from tracker.content import content_fingerprint
from tracker.schema import WorkplaceType

_PAY_BLOCK = (
    "<p>The United States base range for this position is $107,483 - $153,547 "
    "plus equity. The benefits available for this position include health "
    "insurance, six month paid parental leave, 401(k) retirement plan.</p>"
)

_POSTING = {
    "id": "cc5ccf57-1111-4a4b-bb73-3a6af6e0edd5",
    "text": "Android Engineer - Experience",
    "hostedUrl": "https://jobs.lever.co/spotify/cc5ccf57-1111-4a4b-bb73-3a6af6e0edd5",
    "applyUrl": "https://jobs.lever.co/spotify/cc5ccf57-1111-4a4b-bb73-3a6af6e0edd5/apply",
    "createdAt": 1784569799619,  # epoch ms
    "country": "US",
    "workplaceType": "hybrid",
    "categories": {
        "commitment": "Permanent",
        "department": "Engineering",
        "location": "New York, NY",
        "team": "Experience",
        "allLocations": ["New York, NY", "London"],
    },
    "description": "<p>Build the Spotify app for Android.</p>",
    "lists": [
        {"text": "What You'll Do", "content": "\n<li>Ship Android features</li>"},
        {"text": "Who You Are", "content": "\n<li>5+ years of Android</li>"},
    ],
    "additional": _PAY_BLOCK,
}


def _numbered(count: int, *, start: int = 0) -> list[dict]:
    """`count` distinct postings — enough to fill a page at the adapter's limit."""
    return [{**_POSTING, "id": f"posting-{start + i}", "text": f"Engineer {start + i}"} for i in range(count)]


def _adapter(handler, company: str = "spotify", **kwargs) -> LeverAdapter:
    adapter = LeverAdapter(company, **kwargs)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


@pytest.mark.asyncio
async def test_short_page_ends_the_board_without_extra_requests():
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=[_POSTING])

    jobs = [job async for job in _adapter(handler).fetch()]

    assert len(jobs) == 1
    # One page, and crucially NOT a second "is it empty yet?" round trip.
    assert len(calls) == 1
    assert calls[0].params.get("mode") == "json"
    assert calls[0].params.get("skip") == "0"
    assert "api.lever.co/v0/postings/spotify" in str(calls[0])


@pytest.mark.asyncio
async def test_pages_until_a_short_page_and_records_no_truncation():
    """A full page must advance `skip`; the short page ends it cleanly.

    The drift assertion is the point: reaching the end of a board is a natural
    stop, so nothing may mark the listing incomplete.
    """
    pages = {"0": _numbered(50), "50": _numbered(50, start=50), "100": _numbered(7, start=100)}
    seen_skips: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        skip = request.url.params.get("skip")
        seen_skips.append(skip)
        return httpx.Response(200, json=pages.get(skip, []))

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert seen_skips == ["0", "50", "100"]
    assert len(jobs) == 107
    assert adapter.drift.listing_complete is True
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("lost", "gone"), [("0", True), ("50", False)], ids=["root-404", "page-two-404"])
async def test_only_the_first_page_can_say_the_board_is_gone(lost, gone):
    """An unknown site answers 404 at `skip=0`. The same answer on a
    later page is a lost page of a board that exists, never a board gone."""
    pages = {"0": _numbered(50), "50": _numbered(3, start=50)}

    def handler(request: httpx.Request) -> httpx.Response:
        skip = request.url.params.get("skip")
        if skip == lost:
            return httpx.Response(404, json={"ok": False, "error": "Document not found"})
        return httpx.Response(200, json=pages.get(skip, []))

    adapter = _adapter(handler)
    [job async for job in adapter.fetch()]

    assert adapter.drift.listing_invalidated is True
    assert adapter.drift.board_gone is gone
    assert [bool(alert.get("board_missing")) for alert in adapter.drift.alerts] == [gone]


@pytest.mark.asyncio
async def test_duplicate_ids_across_pages_are_collapsed():
    pages = {"0": _numbered(50), "50": [*_numbered(3), *_numbered(2, start=50)]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages.get(request.url.params.get("skip"), []))

    jobs = [job async for job in _adapter(handler).fetch()]

    assert len(jobs) == 52  # 50 + 2 new; the 3 repeats are dropped
    assert len({job.req_id for job in jobs}) == 52


@pytest.mark.asyncio
async def test_maps_fields_locations_and_workplace_type():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_POSTING])

    (job,) = [job async for job in _adapter(handler).fetch()]

    assert job.company == "spotify"
    assert job.req_id == _POSTING["id"]
    assert job.title == "Android Engineer - Experience"
    assert job.url == _POSTING["hostedUrl"]
    assert job.department == "Engineering"
    assert job.team == "Experience"
    assert job.workplace_type is WorkplaceType.HYBRID
    # allLocations first, primary `location` deduped rather than repeated.
    assert job.locations == ["New York, NY", "London"]
    assert job.posted_at is not None and job.posted_at.year == 2026


@pytest.mark.asyncio
async def test_unknown_workplace_type_does_not_guess():
    posting = {**_POSTING, "workplaceType": "hyperspace"}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[posting])

    (job,) = [job async for job in _adapter(handler).fetch()]
    assert job.workplace_type is WorkplaceType.UNKNOWN


@pytest.mark.asyncio
async def test_non_array_payload_invalidates_the_listing():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"postings": []})

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert jobs == []
    assert adapter.drift.listing_complete is False


@pytest.mark.asyncio
async def test_non_200_invalidates_the_listing():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json=[])

    adapter = _adapter(handler)
    assert [job async for job in adapter.fetch()] == []
    assert adapter.drift.listing_complete is False


@pytest.mark.asyncio
async def test_posting_missing_id_or_title_is_drift_not_a_crash():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "x-1"}, _POSTING])

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert [job.req_id for job in jobs] == [_POSTING["id"]]
    assert adapter.drift.listing_complete is False


def test_board_token_overrides_the_builtin_site_map():
    assert LeverAdapter("spotify")._site() == "spotify"
    # A DB-registered Lever company resolves through its token, no code change.
    assert LeverAdapter("acme", board_token="acmeco")._site() == "acmeco"
    # Unknown slug with no token falls back to the slug itself.
    assert LeverAdapter("someco")._site() == "someco"


# --- detail connector ------------------------------------------------------ #


class _Drift:
    def __init__(self) -> None:
        self.alerts: list[dict] = []

    def note(self, message: str, **context) -> None:
        self.alerts.append({"message": message, **context})


async def _structured(posting: dict):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[posting])

    (job,) = [job async for job in _adapter(handler).fetch()]
    structure_job_detail(job, _Drift(), payload=job.detail_payload, source="lever")
    return job


@pytest.mark.asyncio
async def test_detail_builds_sections_from_lists_and_promotes_pay():
    job = await _structured(_POSTING)

    keys = [section.key for section in job.description_sections]
    assert "what_you_ll_do" in keys and "who_you_are" in keys
    assert keys[-1] == "pay_and_benefits"
    body = {section.key: section.content for section in job.description_sections}
    assert "Ship Android features" in body["what_you_ll_do"]
    assert "$107,483" in body["pay_and_benefits"]
    # The isolated block is what licenses a grounded disclosed-comp extraction.
    assert job.source_disclosed_comp is not None
    assert job.source_disclosed_comp.base_min == 107_483
    assert job.source_disclosed_comp.base_max == 153_547


@pytest.mark.asyncio
async def test_closing_block_without_a_range_is_not_a_pay_disclosure():
    """Most non-US postings close with EEO boilerplate. Labelling that as pay
    would inflate the disclosure metrics with postings that disclosed nothing."""
    posting = {
        **_POSTING,
        "additional": "<p>Spotify is an equal opportunity employer.</p>",
    }
    job = await _structured(posting)

    keys = [section.key for section in job.description_sections]
    assert "pay_and_benefits" not in keys
    assert keys[-1] == "additional_information"
    assert job.source_disclosed_comp is None


# --- the dateless contract ------------------------------------------------- #


@pytest.mark.asyncio
async def test_edited_posting_is_detected_although_createdAt_never_moves():
    """Lever has no `updatedAt`: an edit leaves `createdAt` untouched.

    This is the invariant that keeps RoleBand independent of source metadata —
    the content fingerprint must move even when every date the source gives us
    stays identical.
    """
    before = _POSTING
    after = {
        **_POSTING,
        "lists": [{"text": "Who You Are", "content": "\n<li>8+ years of Android</li>"}],
    }
    assert before["createdAt"] == after["createdAt"]

    job_before = await _structured(before)
    job_after = await _structured(after)

    assert job_before.posted_at == job_after.posted_at  # the source learned nothing
    text_before = "\n".join(s.content for s in job_before.description_sections)
    text_after = "\n".join(s.content for s in job_after.description_sections)
    assert content_fingerprint(job_before.title, text_before) != content_fingerprint(
        job_after.title, text_after
    )


# -- regional deployments ------------------------------------------ #
#
# `api.lever.co` and `api.eu.lever.co` are separate deployments with separate
# tenant namespaces. The EU host answers
# `{"ok":false,"error":"Document not found"}` (404) for `spotify`, byte-identical
# to what the global host answers for a site name that exists nowhere. So
# fetching an EU tenant from the global host does not fail with a message naming
# the problem — it looks exactly like a dead board token, which invalidates the
# listing, scans 0, classifies `failed` -> ANOMALY, and quarantines the binding
# after three runs with no exit a user can reach (the dead-token shape).


@pytest.mark.parametrize("region,host", [
    (None, "api.lever.co"),
    ("global", "api.lever.co"),
    ("eu", "api.eu.lever.co"),
])
@pytest.mark.asyncio
async def test_the_listing_is_fetched_from_the_tenants_own_deployment(region, host):
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=[_POSTING])

    adapter = _adapter(handler, company="someco", board_region=region)
    [job async for job in adapter.fetch()]

    assert seen, "the adapter made no request"
    assert {url.host for url in seen} == {host}
    assert all(url.path == "/v0/postings/someco" for url in seen)


def test_each_deployment_paces_and_trips_on_its_own_budget():
    """One bucket per region, not per family. A shared pacer would give each
    deployment half the allowance it is entitled to, and a shared breaker would
    let an outage on one host open the circuit on a host that is answering
    fine. Both pacing and circuit breaking must be scoped per deployment."""
    scopes = {
        region: LeverAdapter("someco", board_region=region).pacing_scope()
        for region in (None, "global", "eu")
    }

    assert scopes["eu"] != scopes["global"]
    # An absent region is the global deployment, so it must share ITS bucket
    # rather than getting a third one.
    assert scopes[None] == scopes["global"]


def test_a_shared_pool_hands_the_two_deployments_different_limiters():
    """The scope only matters if the pool actually separates on it."""
    from tracker.connectors.listing.base import RateLimiterPool

    pool = RateLimiterPool()
    eu = LeverAdapter("someco", board_region="eu", limiter_pool=pool)
    glob = LeverAdapter("someco", board_region="global", limiter_pool=pool)
    twin = LeverAdapter("other", board_region="eu", limiter_pool=pool)

    assert eu._limiter is not glob._limiter
    # Two companies on the SAME deployment still share it: one host is one host.
    assert eu._limiter is twin._limiter
