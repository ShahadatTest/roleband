"""Apple detail hydration — endpoint, payload shape, and the block circuit-breaker.

`/api/v1/details/{id}` answers 401 for everyone, authenticated or not; the live
detail endpoint is `/api/v1/jobDetails/{id}`. These tests pin the endpoint and
the `res` payload shape so a silent fall back to summary-only descriptions
cannot go unnoticed.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors.listing.apple import AppleAdapter
from tracker.schema import RawJob

_DETAIL = {
    "res": {
        "jobSummary": "Summary text.",
        "description": "Description body.",
        "minimumQualifications": "5+ years shipping software.",
        "preferredQualifications": "Distributed systems depth.",
        "selectedLocale": "en_US",
        "postingFooters": [
            {
                "localizations": {
                    "en_US": [
                        {
                            "displayOrder": 1,
                            "name": "Pay & Benefits",
                            "content": (
                                "The base pay range for this role is between "
                                "$250,800 and $376,300.<br><br>Apple employees may receive equity."
                            ),
                        }
                    ]
                }
            }
        ],
    }
}


def _job(summary: str | None = "short summary") -> RawJob:
    return RawJob(
        company="apple",
        req_id="200672287-0836",
        title="Engineering Manager",
        url="https://jobs.apple.com/en-us/details/200672287/engineering-manager",
        locations=["Cupertino, CA"],
        description_html=summary,
        description_complete=False,
    )


def _adapter(handler) -> AppleAdapter:
    adapter = AppleAdapter("apple")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._csrf = "token-abc"
    return adapter


@pytest.mark.asyncio
async def test_hydrate_uses_jobdetails_endpoint_and_joins_res_fields():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=_DETAIL)

    adapter = _adapter(handler)
    job = _job()
    await adapter.hydrate(job)

    assert seen == ["/api/v1/jobDetails/200672287"]
    assert [section.title for section in job.description_sections] == [
        "Summary",
        "Description",
        "Minimum Qualifications",
        "Preferred Qualifications",
        "Pay & Benefits",
    ]
    pay = job.description_sections[-1]
    assert pay.key == "pay_and_benefits"
    assert "$250,800 and $376,300" in pay.content
    assert "Pay &amp; Benefits" in (job.description_html or "")
    assert job.description_complete is True
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_hydrate_survives_missing_optional_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"res": {"description": "Only a body.", "postingFooters": []}},
        )

    adapter = _adapter(handler)
    job = _job()
    await adapter.hydrate(job)

    assert [(section.key, section.content) for section in job.description_sections] == [
        ("description", "Only a body.")
    ]
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_missing_footer_container_enters_failover_instead_of_silently_dropping_pay():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"res": {"description": "Recovered body."}})

    adapter = _adapter(handler)
    job = _job()
    await adapter.hydrate(job)

    assert job.description_sections[0].content == "Recovered body."
    assert job.description_complete is False
    assert adapter.drift.alerts[-1]["reason"] == "postingFooters schema changed"


@pytest.mark.asyncio
async def test_changed_envelope_uses_failover_and_records_drift():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "jobSummary": "Recovered summary.",
                    "minimumQualifications": "10+ years leading products.",
                    "footerBlocks": [
                        {
                            "label": "Pay & Benefits",
                            "body": "Base pay range: $250,800 to $376,300 per year.",
                        }
                    ],
                }
            },
        )

    adapter = _adapter(handler)
    job = _job()
    await adapter.hydrate(job)

    assert {section.key for section in job.description_sections} >= {
        "summary",
        "minimum_qualifications",
        "pay_and_benefits",
    }
    alert = adapter.drift.alerts[-1]
    assert alert["message"] == "job detail connector entered failover mode"
    assert alert["connector"] == "apple"
    assert alert["reason"] == "detail envelope missing res object"
    assert alert["recovered_sections"] == 3
    assert alert["complete"] is True
    assert job.description_complete is True


@pytest.mark.asyncio
async def test_persistent_401_blocks_hydration_and_preserves_list_summary():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/csrfToken":
            return httpx.Response(200, headers={"x-apple-csrf-token": "fresh"})
        return httpx.Response(401, text="Unauthorized")

    adapter = _adapter(handler)
    job = _job()
    await adapter.hydrate(job)

    # The short list summary must survive a blocked detail fetch.
    assert job.description_html == "short summary"
    assert job.description_complete is False
    assert adapter._detail_access_blocked is True
    assert any("hydration disabled for run" in a["message"] for a in adapter.drift.alerts)

    # Circuit breaker: a second job makes no further paced requests to Apple.
    before = len(calls)
    await adapter.hydrate(_job())
    assert len(calls) == before
