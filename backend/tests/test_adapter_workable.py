"""Workable listing adapter.

The three behaviors here that would fail silently in production:

* **One request is the whole board.** There is no total to latch and no page to
  advance, so a second request would mean the adapter invented paging the source
  does not have — and a board that answered the same payload forever would never
  terminate.
* **"Not stated" has two spellings.** Workable serves `""` and `null`
  interchangeably for `code`, `city` and `region`. A parser that treated the
  empty string as a value would file `requisition_label=""` and build the
  location label `", , France"`.
* **One boolean cannot answer three questions.** `telecommuting` says remote or
  not-flagged; reading `false` as ONSITE would assert a placement the board
  never made, and Workable has no field that distinguishes onsite from hybrid.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.workable import WorkableAdapter
from tracker.schema import EmploymentType, WorkplaceType

_JOB = {
    "title": "Low-level Senior Software Engineer, Xet Storage - EMEA Remote",
    "shortcode": "F4C096B22E",
    "code": "",
    "employment_type": "Full-time",
    "telecommuting": True,
    "department": "Product",
    "function": "Engineering",
    "url": "https://apply.workable.com/j/F4C096B22E",
    "shortlink": "https://apply.workable.com/j/F4C096B22E",
    "published_on": "2026-07-30",
    "created_at": "2026-07-30",
    "city": "Paris",
    "state": "Île-de-France",
    "country": "France",
    "locations": [
        {"city": "Paris", "country": "France", "countryCode": "FR",
         "region": "Île-de-France", "hidden": True}
    ],
    "description": "<p>At Hugging Face, we're on a journey to democratize good AI.</p>",
}


def _board(*jobs: dict, name: str = "Hugging Face") -> dict:
    return {"name": name, "description": "<p>The AI community.</p>", "jobs": list(jobs)}


def _adapter(handler, company: str = "hugging-face", **kwargs) -> WorkableAdapter:
    adapter = WorkableAdapter(company, **kwargs)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


async def _fetch(adapter: WorkableAdapter) -> list:
    return [job async for job in adapter.fetch()]


@pytest.mark.asyncio
async def test_the_whole_board_arrives_in_one_request():
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=_board(_JOB, {**_JOB, "shortcode": "002470F128"}))

    adapter = _adapter(handler, board_token="huggingface")
    jobs = await _fetch(adapter)

    assert len(jobs) == 2
    assert len(calls) == 1, "a second request means paging the source does not have"
    assert calls[0].path == "/api/v1/widget/accounts/huggingface"
    assert calls[0].params["details"] == "true"
    assert adapter.drift.listing_complete is True


@pytest.mark.asyncio
async def test_descriptions_arrive_inline_so_hydrate_asks_for_nothing():
    """`description_complete=True` is what keeps the run off a detail route. If
    it regressed, the pipeline would issue one request per keeper against an
    endpoint this adapter does not implement."""
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board(_JOB)))
    job = (await _fetch(adapter))[0]

    assert job.description_complete is True
    assert job.description_html == _JOB["description"]

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("hydrate must not reach the network")

    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    await adapter.hydrate(job)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "   ", None])
async def test_a_posting_with_no_body_does_not_claim_a_complete_description(body):
    """Completeness is observed, not assumed. `?details=true` is what puts the
    body in the listing, so a payload without it carries none — and there is no
    detail route to recover from, because `hydrate()` is a no-op here. A blanket
    `description_complete=True` would tell the pipeline it holds a body it does
    not have, and nothing downstream would ever correct it."""
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board({**_JOB, "description": body})))
    job = (await _fetch(adapter))[0]

    assert job.description_complete is False


@pytest.mark.asyncio
async def test_a_posting_is_keyed_by_shortcode_and_labelled_by_its_own_code():
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board({**_JOB, "code": "HF-118"})))
    job = (await _fetch(adapter))[0]

    assert job.req_id == "F4C096B22E"
    assert job.url == "https://apply.workable.com/j/F4C096B22E"
    assert job.source_facts.posting_id == "F4C096B22E"
    assert job.source_facts.requisition_label == "HF-118"
    # Workable names no underlying job id, so the field stays absent rather
    # than repeating the posting id under a second name.
    assert job.source_facts.source_job_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("not_stated", ["", None])
async def test_both_spellings_of_not_stated_leave_the_label_absent(not_stated):
    """Live boards serve `""` and `null` for the same absence, on the same
    field, on the same board. Either read as a value files an empty string as
    the employer's requisition label."""
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board({**_JOB, "code": not_stated})))
    job = (await _fetch(adapter))[0]

    assert job.source_facts.requisition_label is None


@pytest.mark.asyncio
async def test_a_country_only_posting_does_not_build_a_label_out_of_punctuation():
    """The live shape for a country-wide role: `city` empty, `region` null,
    `country` stated. Joining the triple blindly yields ", , France"."""
    country_only = {
        **_JOB,
        "city": "", "state": "", "country": "United States",
        "locations": [{"city": "", "country": "United States",
                       "countryCode": "US", "region": None, "hidden": False}],
    }
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board(country_only)))
    job = (await _fetch(adapter))[0]

    assert job.locations == ["United States"]
    place = job.source_facts.locations[0]
    assert (place.country, place.region, place.locality) == ("United States", None, None)


@pytest.mark.asyncio
async def test_structured_location_fields_are_kept_as_the_tenant_typed_them():
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board(_JOB)))
    job = (await _fetch(adapter))[0]

    assert job.locations == ["Paris, Île-de-France, France"]
    place = job.source_facts.locations[0]
    assert (place.country, place.region, place.locality) == ("France", "Île-de-France", "Paris")
    assert place.is_primary is True


@pytest.mark.asyncio
async def test_every_stated_location_survives_a_multi_location_posting():
    """`locations[]` is the only form that can express more than one place, and
    a `hidden` flag is the employer's styling of their own advertisement — the
    top-level `city` publishes the same place regardless, so dropping it would
    narrow location scope over a display preference."""
    multi = {
        **_JOB,
        "locations": [
            {"city": "Paris", "region": "Île-de-France", "country": "France", "hidden": True},
            {"city": "New York", "region": "New York", "country": "United States",
             "hidden": False},
            # A duplicate of the first: one place, stated twice, is one place.
            {"city": "Paris", "region": "Île-de-France", "country": "France", "hidden": False},
        ],
    }
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board(multi)))
    job = (await _fetch(adapter))[0]

    assert job.locations == ["Paris, Île-de-France, France", "New York, New York, United States"]
    assert [p.is_primary for p in job.source_facts.locations] == [True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("telecommuting", "expected"),
    [
        (True, WorkplaceType.REMOTE),
        # NOT onsite. Workable has no field separating onsite from hybrid, so
        # the unset flag is an absence of evidence, not evidence of placement.
        (False, WorkplaceType.UNKNOWN),
        (None, WorkplaceType.UNKNOWN),
    ],
)
async def test_one_boolean_answers_only_the_question_it_asks(telecommuting, expected):
    adapter = _adapter(
        lambda _r: httpx.Response(200, json=_board({**_JOB, "telecommuting": telecommuting}))
    )
    job = (await _fetch(adapter))[0]

    assert job.workplace_type is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Full-time", EmploymentType.FULL_TIME),
        ("Part-time", EmploymentType.PART_TIME),
        ("Contract", EmploymentType.CONTRACT),
        ("Internship", EmploymentType.INTERN),
        ("Temporary", EmploymentType.TEMPORARY),
        # Workable's vocabulary is hyphenated where Lever's is spaced, which is
        # why this table is its own rather than borrowed.
        ("Full time", EmploymentType.FULL_TIME),
        ("Seasonal Elf", EmploymentType.UNKNOWN),
    ],
)
async def test_employment_type_is_normalized_alongside_the_source_word(raw, normalized):
    adapter = _adapter(
        lambda _r: httpx.Response(200, json=_board({**_JOB, "employment_type": raw}))
    )
    facts = (await _fetch(adapter))[0].source_facts

    assert facts.employment_type_raw == raw
    assert facts.employment_type_normalized is normalized


@pytest.mark.asyncio
async def test_function_is_not_promoted_into_team():
    """It is Workable's fixed job-function taxonomy ("Engineering"), broader
    than `department` ("Product") rather than a unit inside it. It stays in
    the payload, not in a field that means something else."""
    adapter = _adapter(lambda _r: httpx.Response(200, json=_board(_JOB)))
    job = (await _fetch(adapter))[0]

    assert job.department == "Product"
    assert job.team is None
    assert job.detail_payload["function"] == "Engineering"


@pytest.mark.asyncio
async def test_an_unusable_row_is_counted_without_accusing_the_source():
    """A row naming nothing is `drop_record`: its absence proves nothing, so
    closure is suppressed (`listing_complete` goes False) — but the SOURCE is
    not accused. `listing_invalidated` is the channel that says "this board is
    pathological", and one unreadable row is not that claim."""
    adapter = _adapter(
        lambda _r: httpx.Response(200, json=_board(_JOB, {"title": "No shortcode"}))
    )
    jobs = await _fetch(adapter)

    assert [job.req_id for job in jobs] == ["F4C096B22E"], "the rest of the page parsed"
    assert adapter.drift.records_dropped == 1, "the loss is countable, so it is proportionable"
    assert adapter.drift.listing_invalidated is False, "one row is not a lost page"
    assert adapter.drift.listing_complete is False, "we cannot claim that req is gone"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{"name": "Hugging Face"}, {"name": "HF", "jobs": "not-an-array"}, []]
)
async def test_a_payload_without_a_jobs_array_invalidates_the_listing(payload):
    """The opposite call: no array means we did not read the board, so closure
    must not proceed on it."""
    adapter = _adapter(lambda _r: httpx.Response(200, json=payload))

    assert await _fetch(adapter) == []
    assert adapter.drift.listing_invalidated is True
    assert adapter.drift.records_dropped == 0, "a missing array is a lost page, not a lost row"


@pytest.mark.asyncio
async def test_a_non_200_invalidates_the_listing_rather_than_emptying_the_board():
    """404 is the shape a wrong account token takes, and an empty board is the
    shape a real account with no openings takes. Reading the first as the second
    would close every one of that company's postings."""
    adapter = _adapter(lambda _r: httpx.Response(404, json={"error": "not found"}))

    assert await _fetch(adapter) == []
    assert adapter.drift.listing_invalidated is True


@pytest.mark.asyncio
async def test_the_account_token_resolves_from_the_company_when_none_is_stored():
    """`TenantMap` falls through to the slug, so a company added by URL with no
    stored token still reaches a board — and that effective token can rot
    exactly like a stored one, which is why the probe covers it."""
    calls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=_board(_JOB))

    await _fetch(_adapter(handler, company="acmeco"))

    assert calls[0].path == "/api/v1/widget/accounts/acmeco"
