"""Generic Workday adapter — tenant resolution, per-term paging, hydrate, detail.

Workday is multi-tenant: one adapter serves every company by (host, site). These
tests pin (1) host/site/tenant resolution from the module map and an explicit
board_token, (2) one search query per configured location term with req_id dedup,
(3) the list->RawJob mapping, (4) hydrate fetching the detail description + date,
and (5) the shared Workday detail connector grounding a disclosed pay band.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tracker.connectors.detail import structure_job_detail
from tracker.connectors.listing import build_adapter
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.workday import (
    WorkdayAdapter,
)
from tracker.source_review import SOURCE_REVIEWS


def _consented(adapter):
    """Workday is walled, so the adapter refuses before it requests anything. The consent is this fixture's, never a
    user's: the transport is a mock and no request leaves the process."""
    adapter.collection_consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    return adapter

_POSTING = {
    "title": "Senior Backend Platform Engineer",
    "externalPath": "/job/US-CA-Santa-Clara/Senior-Backend-Platform-Engineer_JR2021162",
    "locationsText": "US, CA, Santa Clara",
    "postedOn": "Posted Today",
    "bulletFields": ["JR2021162"],
}
_DETAIL = {
    "jobPostingInfo": {
        "jobDescription": (
            "<p>Build large-scale platform systems at Nvidia.</p>"
            "<h2>Compensation</h2>"
            "<p>The base salary range for this role is $200,000 - $280,000 USD "
            "annually, depending on location and experience.</p>"
        ),
        "location": "US, CA, Santa Clara",
        "startDate": "2026-07-01",
        "jobReqId": "JR2021162",
    }
}

# Default scope selects relevant location terms, not the entire manifest.
_TERM_COUNT = len(
    WorkdayAdapter('acme', board_token='example.wd1.myworkdayjobs.com|External')
    .planned_location_terms()
)


def _adapter(handler, *, board_token=None) -> WorkdayAdapter:
    adapter = _consented(WorkdayAdapter("nvidia", board_token=board_token))
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


def test_resolve_from_module_map():
    host, tenant, site = WorkdayAdapter("nvidia")._resolve()
    assert host == "nvidia.wd5.myworkdayjobs.com"
    assert tenant == "nvidia"  # derived from the host's first label
    assert site == "NVIDIAExternalCareerSite"


def test_resolve_prefers_explicit_board_token():
    # A DB-added Workday company carries "host|site"; tenant derives from the host.
    a = WorkdayAdapter("acme", board_token="acme.wd1.myworkdayjobs.com|AcmeCareers")
    assert a._resolve() == ("acme.wd1.myworkdayjobs.com", "acme", "AcmeCareers")


def test_resolve_rejects_malformed_board_token():
    with pytest.raises(ValueError):
        WorkdayAdapter("acme", board_token="no-site-here")._resolve()


def test_build_adapter_threads_workday():
    a = build_adapter("nvidia", "workday")
    assert isinstance(a, WorkdayAdapter)


@pytest.mark.asyncio
async def test_fetch_queries_each_term_and_dedupes():
    first_page_terms: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # Return the single posting on the first page of every term, else empty.
        if body["offset"] == 0:
            first_page_terms.append(body["searchText"])
            jobs = [_POSTING]
        else:
            jobs = []
        return httpx.Response(200, json={"total": 1, "jobPostings": jobs})

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    # Same req_id across every location term collapses to one RawJob.
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "nvidia"
    assert job.req_id == "JR2021162"
    assert job.url == (
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
        "/job/US-CA-Santa-Clara/Senior-Backend-Platform-Engineer_JR2021162"
    )
    assert "US, CA, Santa Clara" in job.locations
    assert job.description_complete is False  # list omits the description
    # One first-page search query per configured location term.
    assert len(first_page_terms) == _TERM_COUNT


@pytest.mark.asyncio
async def test_hydrate_fetches_detail_and_structures_pay():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            offset_zero = json.loads(request.content)["offset"] == 0
            return httpx.Response(200, json={"total": 1, "jobPostings": [_POSTING] if offset_zero else []})
        # GET detail
        return httpx.Response(200, json=_DETAIL)

    adapter = _adapter(handler)
    job = [j async for j in adapter.fetch()][0]
    await adapter.hydrate(job)

    assert job.description_complete is True
    assert "platform systems" in (job.description_html or "").lower()
    assert job.posted_at is not None and job.posted_at.year == 2026

    structure_job_detail(job, adapter.drift, payload=job.detail_payload, source="workday")
    assert any(s.key == "job_description" for s in job.description_sections)
    assert any(s.key == "pay_and_benefits" for s in job.description_sections)
    assert job.source_disclosed_comp is not None
    assert job.source_disclosed_comp.base_min == 200_000
    assert job.source_disclosed_comp.base_max == 280_000


@pytest.mark.asyncio
async def test_non_200_search_records_drift_and_yields_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert jobs == []
    assert any(a["message"] == "non-200 jobs search" for a in adapter.drift.alerts)


@pytest.mark.asyncio
async def test_maintenance_redirect_to_html_degrades_to_drift():
    # Workday 303s to a maintenance page that httpx follows to 200 HTML; the
    # adapter must record drift instead of crashing on the non-JSON body.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>maintenance</body></html>")

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert jobs == []
    assert any("non-JSON jobs response" in a["message"] for a in adapter.drift.alerts)


# --- A shared host that names no tenant (snap) -------------------- #
# `wd1.myworkdaysite.com` serves several employers, so the host's first label
# ("wd1") is not the tenant. CXS `/wday/cxs/wd1/snap` is not snap's board,
# `/wday/cxs/snapchat/snap/jobs` is, and the posting page is `/recruiting/snapchat/snap/job/...` (`/snap/job/...` is 500).

_SNAP = "wd1.myworkdaysite.com|snap|snapchat"


def test_a_three_part_token_names_the_tenant_the_host_does_not():
    board = WorkdayAdapter("snap", board_token=_SNAP)._resolve()
    assert board == ("wd1.myworkdaysite.com", "snapchat", "snap")
    probe = WorkdayAdapter.board_probe
    assert probe.url_for(_SNAP) == "https://wd1.myworkdaysite.com/wday/cxs/snapchat/snap/jobs"


@pytest.mark.parametrize("token", [
    "wd1.myworkdaysite.com|snap|",           # a tenant slot that names nothing
    "wd1.myworkdaysite.com|snap|snapchat|x",
    "wd1.myworkdaysite.com||snapchat",
])
def test_a_malformed_tenant_token_is_refused(token):
    with pytest.raises(ValueError):
        WorkdayAdapter("snap", board_token=token)._resolve()


@pytest.mark.asyncio
async def test_every_request_and_url_for_a_shared_host_carries_the_named_tenant():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "POST":
            body = json.loads(request.content)
            jobs = [_POSTING] if body["offset"] == 0 else []
            return httpx.Response(200, json={"total": 1, "jobPostings": jobs})
        return httpx.Response(200, json=_DETAIL)

    adapter = _adapter(handler, board_token=_SNAP)
    jobs = [job async for job in adapter.fetch()]
    assert len(jobs) == 1
    await adapter.hydrate(jobs[0])

    assert {p for p in paths if p.endswith("/jobs")} == {"/wday/cxs/snapchat/snap/jobs"}
    assert paths[-1] == "/wday/cxs/snapchat/snap" + _POSTING["externalPath"]
    assert jobs[0].url == (
        "https://wd1.myworkdaysite.com/recruiting/snapchat/snap" + _POSTING["externalPath"]
    )
    assert jobs[0].description_complete


@pytest.mark.asyncio
async def test_a_tenant_host_keeps_its_root_posting_url():
    # Negative control: a myworkdayjobs host still determines its tenant.
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        jobs = [_POSTING] if body["offset"] == 0 else []
        return httpx.Response(200, json={"total": 1, "jobPostings": jobs})

    jobs = [job async for job in _adapter(handler).fetch()]
    assert jobs[0].url == (
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite" + _POSTING["externalPath"]
    )


@pytest.mark.asyncio
async def test_a_detail_payload_from_before_the_tenant_field_still_hydrates():
    # A host+site payload derives its tenant from the host's label,
    # and hydrate must still reach the same route.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=_DETAIL)

    from tracker.schema import RawJob

    job = RawJob(
        company="nvidia", req_id="JR2021162", title="t", url="u", locations=[],
        description_complete=False,
        detail_payload={
            "external_path": _POSTING["externalPath"],
            "host": "nvidia.wd5.myworkdayjobs.com",
            "site": "NVIDIAExternalCareerSite",
        },
    )
    await _adapter(handler).hydrate(job)
    assert seen == ["/wday/cxs/nvidia/NVIDIAExternalCareerSite" + _POSTING["externalPath"]]


# --- A row that counts its places instead of naming them --------- #

_COUNTED = {
    "title": "Senior Verification Engineer -- ARM Fabric Unit Level",
    "externalPath": "/job/India-Bengaluru/Senior-Verification-Engineer----ARM-Fabric-Unit-Level_JR2020600",
    "locationsText": "2 Locations",
    "postedOn": "Posted Today",
    "bulletFields": ["JR2020600"],
}
_COUNTED_DETAIL = {"jobPostingInfo": {
    "jobDescription": "<p>Verify the ARM fabric.</p>",
    "location": "India, Bengaluru",
    "additionalLocations": ["India, Hyderabad"],
    "startDate": "2026-09-23",
}}


def _board_with(postings, detail_status=200):
    gets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            gets.append(request.url.path)
            if detail_status != 200:
                return httpx.Response(detail_status)
            return httpx.Response(200, json=_COUNTED_DETAIL)
        body = json.loads(request.content)
        return httpx.Response(200, json={"total": len(postings), "jobPostings": postings if body["offset"] == 0 else []})

    return _adapter(handler), gets


@pytest.mark.asyncio
async def test_a_counted_row_is_placed_from_its_detail_before_scope_reads_it():
    from tracker.enrich.classify import match_location_groups

    adapter, gets = _board_with([_POSTING, _COUNTED])
    jobs = {job.req_id: job async for job in adapter.fetch()}

    counted = jobs["JR2020600"]
    assert counted.locations == ["India, Bengaluru", "India, Hyderabad"]
    assert match_location_groups(counted), "a placed row must land in a location group"
    # One detail request, for the counted row only; the row that names its
    # place costs nothing extra.
    assert gets == ["/wday/cxs/nvidia/NVIDIAExternalCareerSite" + _COUNTED["externalPath"]]

    # Hydration reuses the answer: in scope, it costs no second request.
    await adapter.hydrate(counted)
    assert len(gets) == 1
    assert counted.description_complete
    assert counted.locations == ["India, Bengaluru", "India, Hyderabad"]


@pytest.mark.asyncio
async def test_a_counted_row_whose_detail_fails_is_left_as_it_was():
    # 404: the posting closed between the listing and its detail (a 5xx would
    # be retried by the transport, which is not what this pins).
    adapter, gets = _board_with([_COUNTED], detail_status=404)
    jobs = [job async for job in adapter.fetch()]

    assert [job.locations for job in jobs] == [["2 Locations"]]
    assert len(gets) == 1
    assert any(a["message"] == "non-200 job detail" for a in adapter.drift.alerts)
    # A detail is not the listing: the board is still complete.
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_counted_row_reuses_places_read_recently_without_a_request():
    # Places read inside the refresh window must avoid another detail request.
    adapter, gets = _board_with([_COUNTED])
    adapter.known_places = {"JR2020600": ("India, Bengaluru", "India, Hyderabad")}
    jobs = [job async for job in adapter.fetch()]

    assert gets == []
    assert jobs[0].locations == ["India, Bengaluru", "India, Hyderabad"]
    # A row placed from memory has no detail on its payload: hydrate reads it
    # if the row is owed one, as for any posting.
    assert "info" not in jobs[0].detail_payload


@pytest.mark.asyncio
async def test_a_counted_row_the_role_gate_drops_costs_no_detail_request():
    # Rejected counted rows need no detail request: their places cannot affect
    # inclusion, so fetching them wastes the listing budget.
    adapter, gets = _board_with([_POSTING, _COUNTED])
    asked: list[str] = []

    def gate(job):
        asked.append(job.req_id)
        return False

    adapter.place_gate = gate
    jobs = {job.req_id: job async for job in adapter.fetch()}

    assert asked == ["JR2020600"]
    assert gets == []
    assert jobs["JR2020600"].locations == ["2 Locations"]
    assert jobs["JR2021162"].locations == ["US, CA, Santa Clara"]


@pytest.mark.asyncio
async def test_a_counted_row_the_role_gate_admits_is_still_placed():
    adapter, gets = _board_with([_COUNTED])
    adapter.place_gate = lambda job: True
    jobs = [job async for job in adapter.fetch()]

    assert jobs[0].locations == ["India, Bengaluru", "India, Hyderabad"]
    assert len(gets) == 1


# --- A row whose first bullet is a badge, not its id ------------- #

def _spotlight(req: str) -> dict:
    """Intel's real row shape: a featured posting's first bullet is
    the badge "Spotlight Job" and its requisition id is the second."""
    return {
        "title": f"Senior CPU Performance Architect {req}",
        "externalPath": f"/job/US-Texas-Austin/Senior-CPU-Performance-Architect_{req}",
        "locationsText": "US, Texas, Austin",
        "postedOn": "Posted 30+ Days Ago",
        "bulletFields": ["Spotlight Job", req],
    }


@pytest.mark.asyncio
async def test_badged_rows_are_keyed_by_their_requisition_and_the_term_is_complete():
    postings = [_spotlight("JR0287131"), _spotlight("JR0282127"), _POSTING]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"total": 3, "jobPostings": postings if body["offset"] == 0 else []})

    adapter = _adapter(handler)
    jobs = [job async for job in adapter.fetch()]

    assert sorted(job.req_id for job in jobs) == ["JR0282127", "JR0287131", "JR2021162"]
    assert not any("fewer unique" in a["message"] for a in adapter.drift.alerts)
    assert adapter.drift.listing_complete


def test_posting_key_skips_a_badge_and_keeps_every_id_first_row_as_it_was():
    from tracker.connectors.listing.workday import posting_key

    assert posting_key(_POSTING) == "JR2021162"
    assert posting_key(_spotlight("JR0287131")) == "JR0287131"
    # The first id-bearing bullet outranks a different path suffix: changing
    # precedence would split a posting's stored identity.
    assert posting_key({"bulletFields": ["JR2020600"], "externalPath": "/job/x_JR2020600-1"}) == "JR2020600"
    # Only a badge, or none: the id embedded in the path.
    assert posting_key({"bulletFields": ["Spotlight Job"], "externalPath": "/job/x_JR1"}) == "JR1"
    assert posting_key({"externalPath": "/job/x_JR2"}) == "JR2"
    assert posting_key({}) == ""


def test_posting_key_never_keys_a_row_by_a_one_word_badge():
    """A one-word badge has no whitespace but is not a requisition id.
    Reading it as the key collapses distinct postings into duplicates."""
    from tracker.connectors.listing.workday import posting_key

    assert posting_key({"bulletFields": ["Remote", "JR0001"], "externalPath": "/job/x_JR0001"}) == "JR0001"
    assert posting_key({"bulletFields": ["Hybrid", "R-12345"], "externalPath": "/job/x_R-12345"}) == "R-12345"
    # The badge alone: the path's id; no path: the digit-bearing bullet, else the badge.
    assert posting_key({"bulletFields": ["Remote"], "externalPath": "/job/x_JR1"}) == "JR1"
    assert posting_key({"bulletFields": ["New", "12345"]}) == "12345"
    assert posting_key({"bulletFields": ["Remote"]}) == "Remote"


# --------------------------------------------------------------------------- #
# A stored posting rebuilds its detail address from its url
# --------------------------------------------------------------------------- #


def _listing_handler(paths: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "POST":
            jobs = [_POSTING] if json.loads(request.content)["offset"] == 0 else []
            return httpx.Response(200, json={"total": 1, "jobPostings": jobs})
        return httpx.Response(200, json=_DETAIL)
    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("board_token", [None, _SNAP], ids=["tenant-host", "shared-host"])
async def test_a_stored_posting_rebuilds_the_address_its_listing_row_carried(board_token):
    """The description backfill must be able to fill a lost description back,
    and a stored posting carries its url and req_id, not the listing's payload. Every
    url we store is `posting_url(external_path)`, so the url gives it back."""
    from tracker.schema import RawJob

    paths: list[str] = []
    adapter = _adapter(_listing_handler(paths), board_token=board_token)
    listed = [job async for job in adapter.fetch()][0]
    # What the backfill rebuilds from a stored row: nothing the listing carried.
    stored = RawJob(company="nvidia", req_id=listed.req_id, title=listed.title, url=listed.url,
                    description_complete=False)

    assert adapter.payload_from_posting(stored) == listed.detail_payload
    stored.detail_payload = adapter.payload_from_posting(stored)
    await adapter.hydrate(stored)

    assert paths[-1].endswith("/" + listed.detail_payload["site"] + _POSTING["externalPath"])
    assert stored.description_complete and "platform systems" in stored.description_html.lower()


def test_a_url_off_the_company_board_rebuilds_nothing():
    """A guessed address is no detail request: another tenant's url, a url that
    names no posting, and a company with no board all rebuild nothing."""
    from tracker.schema import RawJob

    adapter = _adapter(lambda request: httpx.Response(500))

    def stored(url: str) -> RawJob:
        return RawJob(company="nvidia", req_id="JR1", title="t", url=url)

    assert adapter.payload_from_posting(stored(
        "https://snapchat.wd1.myworkdayjobs.com/snap/job/US/Engineer_JR1")) is None
    assert adapter.payload_from_posting(stored(
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite")) is None
    unconfigured = WorkdayAdapter("acme-no-board")
    assert unconfigured.payload_from_posting(stored("https://acme.wd1.myworkdayjobs.com/x/job/y_1")) is None


@pytest.mark.asyncio
async def test_a_rescan_that_reads_no_page_keeps_the_places_one_named():
    """Only a count-only card asked the page, so a row whose card names one
    place never reached that branch and the card's single label replaced what
    the page had said. Locations fail closed, so the posting then drops out of
    a scope its page place matched. Fail-first: one place comes back."""
    adapter, gets = _board_with([_POSTING])
    adapter.known_places = {"JR2021162": ("US, CA, Santa Clara", "US, TX, Austin")}
    jobs = [job async for job in adapter.fetch()]

    assert gets == [], "the page was read again"
    assert jobs[0].locations == ["US, CA, Santa Clara", "US, TX, Austin"]


@pytest.mark.asyncio
async def test_a_card_that_adds_a_place_keeps_it_beside_the_held_ones():
    """Held is a floor, not a replacement: a board that lists a new place for
    a posting must still be heard. Labels are compared case-insensitively
    because boards change their case between runs."""
    adapter, _ = _board_with([{**_POSTING, "locationsText": "us, ca, santa clara"}])
    adapter.known_places = {"JR2021162": ("US, TX, Austin",)}
    [job] = [job async for job in adapter.fetch()]

    assert job.locations == ["US, TX, Austin", "us, ca, santa clara"]

    adapter, _ = _board_with([_POSTING])
    adapter.known_places = {"JR2021162": ("us, ca, santa clara",)}
    [same] = [job async for job in adapter.fetch()]
    assert same.locations == ["us, ca, santa clara"], "the same place was listed twice"
