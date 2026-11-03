"""Facts the source stated, kept beside the identity we assigned.

Three things would fail silently without a test here, and all three are ways of
losing information rather than crashing:

* **Collapsing identifiers.** Greenhouse names the posting, the underlying job
  and the employer's requisition separately. Treating any two as the same thing
  merges live postings and takes their history with them.
* **Flattening compensation.** A posting can state several complete offer tiers
  in several currencies and intervals. A min/max taken across them is a band no
  employer offered, and an equity PERCENTAGE folded in with dollar amounts is
  not a smaller error, it is a different unit.
* **Confusing "we did not ask" with "there is nothing".** Four retrieval states
  exist because a failed optional request must not erase a real disclosure and a
  withdrawn field must not be reported forever from a stale row.

Fixtures are synthetic but schema-faithful, shaped from recorded responses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tracker.connectors.listing.ashby import AshbyAdapter
from tracker.connectors.listing.greenhouse import GreenhouseAdapter
from tracker.connectors.listing.lever import LeverAdapter
from tracker.schema import (
    AccessSurface,
    CompComponent,
    CompensationFacts,
    CompTier,
    EmploymentType,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
    merge_source_facts,
)

# --------------------------------------------------------------------------- #
# The persisted shape
# --------------------------------------------------------------------------- #


def _facts(**overrides) -> SourceJobFacts:
    base = {
        "provider": "ashby",
        "access_surface": AccessSurface.PUBLIC_API,
        "tenant_identity": "OpenAI",
        "posting_id": "9e5b4a2c",
        "source_job_id": "2345678",
        "requisition_label": "REQ-4471",
        "first_published_at": datetime(2026, 7, 1, 17, 30, tzinfo=UTC),
        "source_updated_at": datetime(2026, 8, 2, 9, 0, tzinfo=UTC),
        "employment_type_raw": "FullTime",
        "employment_type_normalized": EmploymentType.FULL_TIME,
        "locations": [
            SourceLocation(
                label="San Francisco", country="US", region="CA",
                locality="San Francisco", is_primary=True,
            ),
            SourceLocation(label="London"),
        ],
        "compensation": CompensationFacts(
            tiers=[
                CompTier(
                    title="US · Senior",
                    additional_information="Plus benefits.",
                    components=[
                        CompComponent("salary", 310000, 460000, "USD", "year", "$310K – $460K"),
                        CompComponent("equity", 0.01, 0.04, None, "percentage"),
                    ],
                ),
                CompTier(
                    title="Contract",
                    components=[CompComponent("salary", 95, 130, "GBP", "hour")],
                ),
            ],
            state=RetrievalState.PRESENT,
            observed_at=datetime(2026, 9, 10, 6, 0, tzinfo=UTC),
        ),
        "observed_at": datetime(2026, 9, 10, 6, 0, tzinfo=UTC),
    }
    return SourceJobFacts(**{**base, **overrides})


def test_the_record_round_trips_through_its_own_serializer():
    """History has exactly one reader, and it must agree with the writer.

    `asdict()` would follow whatever the dataclass happens to hold, so the
    serializer is explicit — which means nothing but a round trip proves the two
    halves still describe the same shape.
    """
    original = _facts()
    restored = SourceJobFacts.from_dict(json.loads(json.dumps(original.as_dict())))

    assert restored == original
    assert restored.as_dict() == original.as_dict()


def test_every_tier_component_keeps_its_own_currency_and_interval():
    """Two tiers, three components, three unit systems — and none of them merge."""
    stored = _facts().as_dict()
    tiers = stored["compensation"]["tiers"]

    assert [tier["title"] for tier in tiers] == ["US · Senior", "Contract"]
    assert [(c["type"], c["currency"], c["interval"]) for c in tiers[0]["components"]] == [
        ("salary", "USD", "year"),
        ("equity", None, "percentage"),  # a share, not an amount: no currency
    ]
    # An hourly GBP contract rate sits in its own tier and is never averaged
    # into the yearly USD band above it.
    assert tiers[1]["components"] == [{
        "type": "salary", "min": 95.0, "max": 130.0,
        "currency": "GBP", "interval": "hour", "source_text": None,
    }]


def test_the_record_is_an_allowlist_and_carries_no_vendor_payload():
    """Application questions and compliance metadata may not ride along.

    The guard is that the serializer names its fields: a source object handed
    in wholesale would show up here as unexpected keys.
    """
    stored = _facts().as_dict()

    assert set(stored) == {
        "schema_version", "provider", "access_surface", "tenant_identity",
        "posting_id", "source_job_id", "requisition_label",
        "first_published_at", "last_published_at", "source_created_at",
        "source_updated_at", "application_deadline",
        "employment_type_raw", "employment_type_normalized",
        "locations", "compensation", "application_form", "observed_at",
    }
    assert set(stored["locations"][0]) == {
        "label", "country", "region", "locality", "is_primary"
    }
    # The form is kept as COUNTS. No key here can hold a question's
    # wording, so the questions themselves still cannot ride along. The last
    # two are the page read's cool-down record, ours, not the source's.
    assert set(stored["application_form"]) == {
        "state", "observed_at", "required", "written", "choices", "asks_expected_pay",
        "failed_at", "permanent",
    }
    assert stored["schema_version"] == 1


# --------------------------------------------------------------------------- #
# Merge: what this run saw vs what we already knew
# --------------------------------------------------------------------------- #

_EARLIER = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize("state", [
    RetrievalState.NOT_REQUESTED,
    RetrievalState.RETRIEVAL_FAILED,
])
def test_a_disclosure_survives_a_run_that_did_not_or_could_not_ask(state):
    """The rule that stops an optional detail request from destroying evidence.

    A timeout on a pay-detail fetch is a fact about US. Letting it clear the
    tiers would mean a flaky night silently erased a band the employer really
    published, with an append-only history recording the erasure as truth.
    """
    stored = _facts(
        compensation=CompensationFacts(
            tiers=_facts().compensation.tiers,
            state=RetrievalState.PRESENT,
            observed_at=_EARLIER,
        )
    ).as_dict()

    merged = merge_source_facts(stored, _facts(compensation=CompensationFacts(state=state)))

    assert merged["compensation"]["state"] == RetrievalState.PRESENT.value
    assert merged["compensation"]["tiers"] == stored["compensation"]["tiers"]
    # Carried, and it says so: the tiers are older than the record holding them.
    assert merged["compensation"]["observed_at"] == _EARLIER.isoformat()
    assert merged["observed_at"] != merged["compensation"]["observed_at"]
    # Everything the run DID see is this run's.
    assert merged["source_updated_at"] == _facts().as_dict()["source_updated_at"]


def test_a_successful_response_that_omits_pay_retires_the_old_disclosure():
    """The other half, and the one a naive "keep the last good value" gets wrong.

    The board answered, and its answer was that this posting states no pay.
    Perpetuating yesterday's band would report a disclosure the employer has
    withdrawn.
    """
    stored = _facts().as_dict()

    merged = merge_source_facts(
        stored,
        _facts(compensation=CompensationFacts(
            state=RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE,
            observed_at=datetime(2026, 9, 10, 6, 0, tzinfo=UTC),
        )),
    )

    assert merged["compensation"]["tiers"] == []
    assert merged["compensation"]["state"] == RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE.value


@pytest.mark.parametrize("state", [
    RetrievalState.NOT_REQUESTED,
    RetrievalState.RETRIEVAL_FAILED,
])
def test_an_answer_of_no_pay_survives_a_run_that_did_not_or_could_not_ask(state):
    """A posting page read that found no pay field is a reading.

    Greenhouse's listing never asks for structured pay, so the next scan
    arrives `not_requested`. Resetting the page's "none" to that would say we
    never asked, and lose when we did; the form beside it was always kept.
    """
    read_at = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    stored = _facts(
        compensation=CompensationFacts(
            state=RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE, observed_at=read_at,
        ),
    ).as_dict()

    merged = merge_source_facts(stored, _facts(compensation=CompensationFacts(state=state)))

    assert merged["compensation"]["state"] == RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE.value
    assert merged["compensation"]["observed_at"] == read_at.isoformat()
    assert merged["compensation"]["tiers"] == []


def test_a_scan_that_skipped_the_detail_page_keeps_the_publish_date():
    """KPMG, SuccessFactors and SmartRecruiters date a posting only on its
    detail page; a rescan inside the refresh window reads the listing alone
    and states no date. That is not the employer withdrawing the date."""
    stored = _facts(source_created_at=_EARLIER).as_dict()

    merged = merge_source_facts(stored, _facts(first_published_at=None, source_created_at=None))

    assert merged["first_published_at"] == stored["first_published_at"]
    assert merged["source_created_at"] == _EARLIER.isoformat()


def test_a_date_the_run_states_replaces_the_stored_one_either_way():
    """A re-date is what the source says now; the earliest is kept on the
    job's own `first_posted_at`, not by freezing the facts."""
    later = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
    stored = _facts().as_dict()

    merged = merge_source_facts(stored, _facts(first_published_at=later))

    assert merged["first_published_at"] == later.isoformat()


def test_nothing_is_carried_when_there_was_never_anything_to_carry():
    for stored in (None, {}, _facts(compensation=CompensationFacts()).as_dict()):
        merged = merge_source_facts(
            stored, _facts(compensation=CompensationFacts(state=RetrievalState.RETRIEVAL_FAILED))
        )
        assert merged["compensation"]["tiers"] == []
        assert merged["compensation"]["state"] == RetrievalState.RETRIEVAL_FAILED.value


# --------------------------------------------------------------------------- #
# Adapter mappings
# --------------------------------------------------------------------------- #

_GH_POSTING = {
    "id": 8172510,
    "internal_job_id": 2785594,
    "requisition_id": "REQ-14832",
    "title": "Staff Software Engineer, Reliability",
    "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/8172510",
    "location": {"name": "San Francisco, CA"},
    "offices": [{"name": "San Francisco, CA"}, {"name": "Seattle, WA"}],
    "departments": [{"name": "Engineering"}],
    "content": "<p>Own reliability.</p>",
    "first_published": "2026-06-20T09:00:00-04:00",
    "updated_at": "2026-07-10T12:00:00-04:00",
    "application_deadline": None,
    # Nothing below this line may reach storage.
    "data_compliance": [{"type": "gdpr", "requires_consent": True}],
    "metadata": [{"name": "Internal notes", "value": "do not publish"}],
}


def test_greenhouse_keeps_three_identifiers_apart():
    """On a real board many postings share one internal job id, up to nine.

    `req_id` must stay the POSTING id — rekeying to `internal_job_id` would
    merge those rows into one and take the other roles' favourites,
    observations and lineage with them.
    """
    adapter = GreenhouseAdapter("anthropic")

    facts = adapter._facts(
        _GH_POSTING, "8172510", "anthropic",
        _GH_POSTING["location"], _GH_POSTING["offices"],
    )

    assert facts.posting_id == "8172510"
    assert facts.source_job_id == "2785594"
    assert facts.requisition_label == "REQ-14832"
    assert len({facts.posting_id, facts.source_job_id, facts.requisition_label}) == 3
    assert facts.tenant_identity == "anthropic"
    assert facts.access_surface is AccessSurface.PUBLIC_API


@pytest.mark.parametrize("field", ["internal_job_id", "requisition_id"])
@pytest.mark.parametrize("value", [0, "", None])
def test_greenhouse_reads_a_zero_or_blank_identifier_as_none(field, value):
    """0 names no job, as it names no posting in `fetch`. Kept as "0", it
    would read as one employer job shared by every posting that carries it.
    The other identifier is read as stated, so a reader that drops both fails."""
    posting = {**_GH_POSTING, field: value}

    facts = GreenhouseAdapter("anthropic")._facts(
        posting, "8172510", "anthropic", posting["location"], posting["offices"],
    )

    read = {"internal_job_id": facts.source_job_id, "requisition_id": facts.requisition_label}
    assert read == {"internal_job_id": "2785594", "requisition_id": "REQ-14832", field: None}


def test_greenhouse_keeps_publication_and_update_dates_apart():
    """`posted_at` coalesces the two; the record may not.

    A board's `updated_at` moves when the body is edited. Reported as a
    publication date it would make an old role look freshly posted.
    """
    facts = GreenhouseAdapter("anthropic")._facts(
        _GH_POSTING, "8172510", "anthropic", _GH_POSTING["location"], _GH_POSTING["offices"]
    )

    assert facts.first_published_at is not None
    assert facts.source_updated_at is not None
    assert facts.first_published_at < facts.source_updated_at
    assert facts.application_deadline is None


def test_greenhouse_does_not_claim_pay_it_never_asked_for():
    """The list route carries no pay: `pay_input_ranges` is a DETAIL field.

    Recording that as "the employer disclosed nothing" would be a claim about
    Anthropic made from a request we chose not to send.
    """
    facts = GreenhouseAdapter("anthropic")._facts(
        _GH_POSTING, "8172510", "anthropic", _GH_POSTING["location"], _GH_POSTING["offices"]
    )

    assert facts.compensation.state is RetrievalState.NOT_REQUESTED
    assert facts.compensation.tiers == []


def test_greenhouse_records_no_vendor_metadata():
    stored = json.dumps(
        GreenhouseAdapter("anthropic")._facts(
            _GH_POSTING, "8172510", "anthropic",
            _GH_POSTING["location"], _GH_POSTING["offices"],
        ).as_dict()
    )

    assert "do not publish" not in stored
    assert "requires_consent" not in stored


_ASHBY_POSTING = {
    "id": "c414f15f-60c4-40b5-a896-d2ad6c7f4415",
    "title": "Member of Technical Staff",
    "employmentType": "FullTime",
    "location": "San Francisco",
    "address": {"postalAddress": {
        "addressCountry": "United States",
        "addressRegion": "California",
        "addressLocality": "San Francisco",
    }},
    "secondaryLocations": [
        {"location": "London", "address": {"postalAddress": {"addressCountry": "United Kingdom"}}},
    ],
    "isListed": True,
    "publishedAt": "2026-07-01T17:30:00.000Z",
    "compensation": {
        "compensationTierSummary": "$310K – $460K • Offers Equity",
        "summaryComponents": [
            {"compensationType": "Salary", "interval": "1 YEAR",
             "currencyCode": "USD", "minValue": 310000, "maxValue": 460000},
        ],
        "compensationTiers": [
            {
                "title": "San Francisco",
                "additionalInformation": "Plus equity and benefits.",
                "components": [
                    {"compensationType": "Salary", "interval": "1 YEAR",
                     "currencyCode": "USD", "minValue": 310000, "maxValue": 460000},
                    {"compensationType": "Equity", "interval": "1 YEAR",
                     "minValue": 0.05, "maxValue": 0.2, "summary": "0.05% – 0.2%"},
                ],
            },
            {
                "title": "London",
                "components": [
                    {"compensationType": "Salary", "interval": "1 YEAR",
                     "currencyCode": "GBP", "minValue": 210000, "maxValue": 290000},
                ],
            },
            {
                "title": "Contract",
                "components": [
                    {"compensationType": "Salary", "interval": "1 HOUR",
                     "currencyCode": "USD", "minValue": 120, "maxValue": 180},
                ],
            },
        ],
    },
}


def test_ashby_retains_every_tier_with_its_own_units():
    """Three tiers is a real shape at openai.

    The three differ in currency AND interval AND kind. Any flattening — one
    band, one currency, one period — loses something a reader would need.
    """
    facts = AshbyAdapter("openai")._facts(_ASHBY_POSTING, _ASHBY_POSTING["id"])
    tiers = facts.compensation.tiers

    assert facts.compensation.state is RetrievalState.PRESENT
    assert [tier.title for tier in tiers] == ["San Francisco", "London", "Contract"]
    assert tiers[0].additional_information == "Plus equity and benefits."
    # An equity percentage keeps no currency and is not a salary.
    salary, equity = tiers[0].components
    assert (salary.type, salary.currency, salary.interval) == ("salary", "USD", "year")
    assert (equity.type, equity.currency, equity.max) == ("equity", None, 0.2)
    # Hourly vs yearly stays distinct, in different currencies.
    assert (tiers[1].components[0].currency, tiers[1].components[0].interval) == ("GBP", "year")
    assert (tiers[2].components[0].currency, tiers[2].components[0].interval) == ("USD", "hour")


def test_ashby_does_not_read_the_summary_as_a_fourth_tier():
    """`summaryComponents` is the same money, flattened. Counting both doubles it."""
    facts = AshbyAdapter("openai")._facts(_ASHBY_POSTING, _ASHBY_POSTING["id"])

    assert len(facts.compensation.tiers) == 3
    assert all("$310K – $460K" != tier.title for tier in facts.compensation.tiers)


def test_ashby_falls_back_to_the_summary_when_no_tiers_are_declared():
    """Most postings carry only the summary: exactly one tier."""
    posting = {**_ASHBY_POSTING, "compensation": {
        "compensationTierSummary": "$310K – $460K",
        "summaryComponents": _ASHBY_POSTING["compensation"]["summaryComponents"],
    }}

    facts = AshbyAdapter("openai")._facts(posting, posting["id"])

    assert facts.compensation.state is RetrievalState.PRESENT
    assert [c.type for tier in facts.compensation.tiers for c in tier.components] == ["salary"]


def test_ashby_reports_a_pay_free_posting_as_the_employers_answer():
    """Some postings state nothing. The board answered, so this is not our gap."""
    posting = {k: v for k, v in _ASHBY_POSTING.items() if k != "compensation"}

    facts = AshbyAdapter("openai")._facts(posting, posting["id"])

    assert facts.compensation.state is RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE
    assert facts.compensation.tiers == []


def test_ashby_keeps_address_strings_exactly_as_the_tenant_typed_them():
    """"United States" is not silently promoted to an ISO code we then assert."""
    facts = AshbyAdapter("openai")._facts(_ASHBY_POSTING, _ASHBY_POSTING["id"])
    primary, secondary = facts.locations

    assert (primary.label, primary.country, primary.region) == (
        "San Francisco", "United States", "California",
    )
    assert primary.is_primary is True
    assert (secondary.label, secondary.country, secondary.is_primary) == (
        "London", "United Kingdom", False,
    )


def test_ashby_keeps_the_source_word_for_employment_type_beside_ours():
    facts = AshbyAdapter("openai")._facts(_ASHBY_POSTING, _ASHBY_POSTING["id"])
    assert (facts.employment_type_raw, facts.employment_type_normalized) == (
        "FullTime", EmploymentType.FULL_TIME,
    )

    odd = AshbyAdapter("openai")._facts({**_ASHBY_POSTING, "employmentType": "Fractional"}, "x")
    # Unmapped degrades to UNKNOWN and keeps the word — never a guess.
    assert (odd.employment_type_raw, odd.employment_type_normalized) == (
        "Fractional", EmploymentType.UNKNOWN,
    )


_LEVER_POSTING = {
    "id": "cc5ccf57-b851-4c25-8840-ed4cd0535c12",
    "text": "Analyst, Licensing Finance",
    "hostedUrl": "https://jobs.lever.co/spotify/cc5ccf57-b851-4c25-8840-ed4cd0535c12",
    "createdAt": 1772482884346,
    "country": "US",
    "workplaceType": "onsite",
    "categories": {
        "commitment": "Permanent",
        "department": "Finance",
        "location": "New York, NY",
        "allLocations": ["New York, NY", "Stockholm"],
    },
    "description": "<div>Model licensing economics.</div>",
    "additional": "<div>The United States base range for this position is "
                  "$67,172 - $95,960 plus equity.</div>",
}


def test_lever_records_absent_salary_fields_without_inventing_a_band():
    """Spotify postings carry no `salaryRange`.

    The pay is in the prose, and the existing text extraction is what reads it.
    This record says the structured fields were empty — it does not re-parse the
    description into a second, independently-derived compensation claim.
    """
    facts = LeverAdapter("spotify")._facts(
        _LEVER_POSTING, _LEVER_POSTING["id"], _LEVER_POSTING["categories"],
        ["New York, NY", "Stockholm"],
    )

    assert facts.compensation.state is RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE
    assert facts.compensation.tiers == []
    assert "67,172" not in json.dumps(facts.as_dict())


def test_lever_maps_a_declared_salary_range_when_the_tenant_publishes_one():
    posting = {**_LEVER_POSTING, "salaryRange": {
        "min": 67172, "max": 95960, "currency": "USD", "interval": "per-year-salary",
    }, "salaryDescription": "Base range plus equity."}

    facts = LeverAdapter("spotify")._facts(
        posting, posting["id"], posting["categories"], ["New York, NY"],
    )

    assert facts.compensation.state is RetrievalState.PRESENT
    component = facts.compensation.tiers[0].components[0]
    assert (component.min, component.max, component.currency) == (67172.0, 95960.0, "USD")
    assert component.source_text == "Base range plus equity."


def test_lever_attaches_its_country_to_the_primary_location_only():
    """`allLocations` crosses borders; `country` is one field about one place."""
    facts = LeverAdapter("spotify")._facts(
        _LEVER_POSTING, _LEVER_POSTING["id"], _LEVER_POSTING["categories"],
        ["New York, NY", "Stockholm"],
    )

    assert [(loc.label, loc.country, loc.is_primary) for loc in facts.locations] == [
        ("New York, NY", "US", True),
        ("Stockholm", None, False),
    ]


def test_lever_calls_a_creation_time_a_creation_time():
    """Lever states when the posting was OPENED and never when it went up."""
    facts = LeverAdapter("spotify")._facts(
        _LEVER_POSTING, _LEVER_POSTING["id"], _LEVER_POSTING["categories"], ["New York, NY"],
    )

    assert facts.source_created_at is not None
    assert facts.first_published_at is None
    assert facts.source_updated_at is None


def test_lever_does_not_read_permanent_as_full_time():
    """A basis is not a schedule. Spotify postings say "Permanent"."""
    facts = LeverAdapter("spotify")._facts(
        _LEVER_POSTING, _LEVER_POSTING["id"], _LEVER_POSTING["categories"], ["New York, NY"],
    )

    assert facts.employment_type_raw == "Permanent"
    assert facts.employment_type_normalized is EmploymentType.UNKNOWN


def test_every_public_adapter_stamps_when_it_observed_the_facts():
    before = datetime.now(UTC) - timedelta(seconds=5)
    records = [
        GreenhouseAdapter("anthropic")._facts(
            _GH_POSTING, "8172510", "anthropic", _GH_POSTING["location"], _GH_POSTING["offices"]
        ),
        AshbyAdapter("openai")._facts(_ASHBY_POSTING, _ASHBY_POSTING["id"]),
        LeverAdapter("spotify")._facts(
            _LEVER_POSTING, _LEVER_POSTING["id"], _LEVER_POSTING["categories"], ["New York, NY"]
        ),
    ]

    for facts in records:
        assert facts.observed_at is not None and facts.observed_at >= before
        assert facts.provider in {"greenhouse", "ashby", "lever"}
        assert facts.tenant_identity  # never blank: the record must name its board


# --------------------------------------------------------------------------- #
# Through the real parser
#
# Every test above builds facts by handing `_facts` a Python dict. That is a
# fine way to assert a mapping rule and a *useless* way to assert a value
# survives, because the literal `0.2` in a dict is already a float and the
# adapter never parses it. `fetch()` parses with `ijson`, which answers
# `Decimal` for anything fractional — so the boundary the fixtures skip is
# precisely where equity percentages can drop while every assertion above
# stays green. These drive the adapter.
# --------------------------------------------------------------------------- #

_ASHBY_BOARD = {
    "apiVersion": "1",
    "jobs": [{
        "id": "job-1",
        "title": "Member of Technical Staff",
        "isListed": True,
        "location": "San Francisco",
        # Ashby's documented PRIMARY shape: fields under `postalAddress`.
        "address": {"postalAddress": {
            "addressCountry": "USA",
            "addressRegion": "California",
            "addressLocality": "San Francisco",
        }},
        # Ashby's documented SECONDARY shape: the same fields, one level up.
        "secondaryLocations": [{
            "location": "London",
            "address": {
                "addressCountry": "United Kingdom",
                "addressRegion": "England",
                "addressLocality": "London",
            },
        }],
        "publishedAt": "2026-07-01T17:30:00.000Z",
        "updatedAt": "2026-09-01T12:00:00.000Z",
        "compensation": {"compensationTiers": [{"title": "SF", "components": [
            {"compensationType": "Salary", "interval": "1 YEAR",
             "currencyCode": "USD", "minValue": 310000, "maxValue": 460000},
            # The documented equity example, verbatim: fractional, no currency.
            {"compensationType": "EquityPercentage", "interval": "NONE",
             "currencyCode": None, "minValue": 0.5, "maxValue": 1.75,
             "summary": "0.5% – 1.75%"},
        ]}]},
    }],
}


async def _ashby_facts(board: dict):
    """One posting's facts, taken through `AshbyAdapter.fetch()` and `ijson`."""
    import httpx

    from tracker.platform.ratelimit import RateLimiter

    adapter = AshbyAdapter("openai")
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=json.dumps(board).encode())
        )
    )
    adapter._limiter = RateLimiter(0.0)
    jobs = [job async for job in adapter.fetch()]
    return jobs[0].source_facts


@pytest.mark.asyncio
async def test_ashby_keeps_a_fractional_equity_percentage_through_the_parser():
    """`ijson` answers `Decimal`, and a `Decimal` filter must not reject it.

    Fails on a `_number` that rejects `Decimal`, with `min=None, max=None`:
    the component and its `present` state survive, so a posting stating
    "0.5% – 1.75%" would be
    stored as an employer offering equity and naming no amount. Whole salaries
    are unaffected — `ijson` answers those as `int` — so the loss hits
    exactly one component type, the only one Ashby states fractionally.
    """
    facts = await _ashby_facts(_ASHBY_BOARD)
    salary, equity = facts.compensation.tiers[0].components

    assert (equity.min, equity.max) == (0.5, 1.75)
    assert equity.currency is None
    assert (salary.min, salary.max) == (310000.0, 460000.0)
    # Whatever the parser produced has to survive persistence too.
    assert "1.75" in json.dumps(facts.as_dict())


@pytest.mark.asyncio
async def test_ashby_reads_the_documented_secondary_address_shape():
    """Primary nests under `postalAddress`; secondary states the fields directly.

    Two shapes, both documented. Reading only the nested one loses country,
    region AND locality on every secondary location while the label survives —
    invisible downstream, so the fixture carries the documented secondary
    shape rather than a nested one.
    """
    facts = await _ashby_facts(_ASHBY_BOARD)
    primary, secondary = facts.locations

    assert (primary.country, primary.region, primary.locality) == (
        "USA", "California", "San Francisco",
    )
    assert (secondary.country, secondary.region, secondary.locality) == (
        "United Kingdom", "England", "London",
    )


@pytest.mark.asyncio
async def test_ashby_calls_a_last_publication_a_last_publication():
    """Ashby documents `publishedAt` as when the job was LAST published.

    Storing it as `first_published_at` makes a claim the board never made: a
    republished posting moves the field, and we would have recorded that as the
    role first appearing. Greenhouse states `first_published` and Ashby does
    not, so first publication stays unknown rather than borrowing the nearest
    field with a date in it.
    """
    facts = await _ashby_facts(_ASHBY_BOARD)

    assert facts.last_published_at == datetime(2026, 7, 1, 17, 30, tzinfo=UTC)
    assert facts.first_published_at is None
    assert facts.source_updated_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_lever_takes_the_primary_from_the_field_that_declares_it():
    """`categories.location` is the primary. `allLocations[0]` is not.

    Lever documents only that the primary "also appears in the allLocations
    array" — no ordering guarantee — and the adapter builds its list
    `allLocations` first. So a posting whose array happens to lead with another
    site would flag the wrong location primary and hang the posting's single
    `country` on it, which is the country invention `_facts` already forbids,
    arriving by the back door. Fixture is the shipped one with the array
    reversed, so the reversal is the whole test.
    """
    posting = {**_LEVER_POSTING, "categories": {
        **_LEVER_POSTING["categories"], "allLocations": ["Stockholm", "New York, NY"],
    }}
    raw = LeverAdapter("spotify")._to_rawjob(posting)

    assert [(loc.label, loc.country, loc.is_primary) for loc in raw.source_facts.locations] == [
        ("Stockholm", None, False),
        ("New York, NY", "US", True),
    ]
    # Display ordering is the source's and is deliberately left alone.
    assert raw.locations == ["Stockholm", "New York, NY"]


def test_lever_marks_no_primary_when_the_posting_declares_none():
    """An `is_primary` nobody asserted is worth less than an absent one."""
    categories = {k: v for k, v in _LEVER_POSTING["categories"].items() if k != "location"}
    raw = LeverAdapter("spotify")._to_rawjob({**_LEVER_POSTING, "categories": categories})
    locations = raw.source_facts.locations

    assert [loc.label for loc in locations] == ["New York, NY", "Stockholm"]
    assert not any(loc.is_primary for loc in locations)
    assert all(loc.country is None for loc in locations)
