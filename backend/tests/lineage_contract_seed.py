"""Realistic rows for the lineage and twin contract.

The handlers read the clock themselves, and the analyze routes call a local
model, so `pin_lineage_environment` freezes both: `datetime.now` in
`routers/jobs.py` and `routers/lineage.py` answers `NOW`, the model client's
timer advances a fixed step per read, and the local model is an in-process
OpenAI-compatible server answering `ASSESSMENT`. Two runs of the same request
therefore return the same bytes.

Rows are built by the code that builds them in production wherever that code
exists: the lineage projection by `rebuild_lineage_projection`, a twin's stored
description evidence by `compare_descriptions`, the local model profile by the
local-model store.

| key | what it exercises |
|---|---|
| `original`, `repost`, `duplicate` | a google stack: an auto repost link whose diff moves every field, then a human-confirmed duplicate whose diff is empty and whose decision changed once |
| `rejected` | a duplicate proposal a human rejected, so the posting stands alone with a stored decision |
| `solo` | a posting with no relationship at all |
| `pending_prior`, `pending_newer` | a suspected duplicate awaiting review |
| `twin_left`, `twin_right` | a suspected twin awaiting review, with stored description evidence |
| `twin_hub`, `twin_spoke` | twins confirmed by review (no stored description evidence) and by hand: from `twin_left`, one direct member and one reached through `twin_hub` |
| `other_company` | an acme posting no google posting may be twinned with |
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, JobLineageLink, JobTwinLink
from tracker.intelligence_runtime.local_profiles import create_profile, set_enabled
from tracker.lineage.content_diff import compare_descriptions
from tracker.lineage.detect import DETECTOR_VERSION, rebuild_lineage_projection
from tracker.lineage.twins import DETECTOR_VERSION as TWIN_DETECTOR_VERSION
from tracker.local_llm.models import LocalLLMProfileInput

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
MODEL_ID = "qwen3-8b-mlx"

ASSESSMENT = {
    "recommendation": "confirmed",
    "confidence": 0.86,
    "summary": "Same team, level and responsibilities; the newer posting only adds a location.",
    "matching_evidence": ["identical minimum qualifications", "same department and level"],
    "differences": ["London added as a location"],
}

#: What the in-process model server reports about one completion.
USAGE = {
    "prompt_tokens": 1830,
    "completion_tokens": 212,
    "total_tokens": 2042,
    "total_time": 9.4,
    "time_to_first_token": 0.61,
    "prompt_eval_duration": 1.2,
    "generation_duration": 8.2,
    "prompt_tokens_details": {"cached_tokens": 512},
    "prompt_tokens_per_second": 1525.0,
    "generation_tokens_per_second": 25.9,
}

_SECTIONS = [
    {"key": "responsibilities", "title": "Responsibilities", "content": "Own the inference platform roadmap."},
    {"key": "minimum_qualifications", "title": "Minimum qualifications", "content": "8 years of product management."},
]


def model_server(
    content: str | None = None, usage: dict | None = None, *, finish_reason: str = "stop"
) -> httpx.MockTransport:
    """An OpenAI-compatible local server: one model listed, one completion."""
    body = json.dumps(ASSESSMENT) if content is None else content
    reported = USAGE if usage is None else usage

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL_ID, "max_model_len": 32768}]})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "model": MODEL_ID,
                    "choices": [
                        {"message": {"role": "assistant", "content": body}, "finish_reason": finish_reason}
                    ],
                    "usage": reported,
                },
            )
        return httpx.Response(404, json={"error": {"message": "not found"}})

    return httpx.MockTransport(handle)


class _Ticker:
    """`time.monotonic` for the model client: every read is 9.412 s after the last."""

    def __init__(self) -> None:
        self.value = 1_000.0

    def monotonic(self) -> float:
        self.value += 9.412
        return self.value


def pin_lineage_environment(monkeypatch, *, model_reply: str | None = None, usage: dict | None = None) -> None:
    """Freeze the handlers' clock and put the local model in-process."""
    import tracker.api.routers.jobs as jobs
    import tracker.api.routers.lineage as lineage
    import tracker.lineage.review as review
    import tracker.local_llm.client as client_module

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(jobs, "datetime", _Clock)
    monkeypatch.setattr(lineage, "datetime", _Clock)
    monkeypatch.setattr(review, "datetime", _Clock)  # a verdict's time
    monkeypatch.setattr(client_module, "time", _Ticker())
    transport = model_server(model_reply, usage)
    monkeypatch.setattr(
        lineage,
        "LocalLLMClient",
        lambda profile: client_module.LocalLLMClient(profile, client=httpx.AsyncClient(transport=transport)),
    )


@dataclass(frozen=True)
class SeededLineage:
    original: int
    repost: int
    duplicate: int
    rejected: int
    solo: int
    pending_prior: int
    pending_newer: int
    twin_left: int
    twin_right: int
    twin_hub: int
    twin_spoke: int
    other_company: int
    repost_link: int
    duplicate_link: int
    rejected_link: int
    pending_link: int
    twin_pending: int
    twin_reviewed: int
    twin_manual: int
    profile_id: str | None


def _job(key: str, *, company: str = "google", days_ago: int, **over) -> Job:
    first_seen = NOW - timedelta(days=days_ago)
    row = {
        "company": company,
        "req_id": key,
        "dedupe_key": f"{company}:{key}",
        "title": "Staff Product Manager, Inference",
        "url": f"https://careers.example.test/{company}/{key}",
        "department": "Cloud AI",
        "team": "Inference",
        "locations": ["Mountain View, CA, USA"],
        "location_groups": ["silicon_valley"],
        "domains": ["ai_ml"],
        "workplace_type": "hybrid",
        "level_band": "staff",
        "level_confidence": "confirmed",
        "family": "product_management",
        "track": "product_program",
        "comp_low": 520_000,
        "comp_high": 760_000,
        "comp_median": 640_000,
        "comp_currency": "USD",
        "comp_provenance": "Google L6 estimated median (product_management)",
        "status": "open",
        "in_scope": True,
        "first_seen": first_seen,
        "last_seen": NOW - timedelta(days=1),
        "description_text": "Own the inference platform roadmap. 8 years of product management.",
        "description_html": "<p>Own the inference platform roadmap.</p>",
        "description_sections": _SECTIONS,
    }
    row.update(over)
    return Job(**row)


def _stated_band(low: int, high: int) -> dict:
    return {
        "structured_at": NOW - timedelta(days=2),
        "disclosed_base_min": low,
        "disclosed_base_max": high,
        "disclosed_currency": "USD",
        "disclosed_pay_basis": "base",
        "disclosed_pay_period": "year",
        "disclosed_snippet": f"The US base salary range for this role is ${low:,}-${high:,}.",
        "disclosed_confidence": "high",
    }


async def seed_lineage_contract(session: AsyncSession, *, local_model: bool = True) -> SeededLineage:
    jobs = {
        "original": _job(
            "original", days_ago=90, title="Senior Product Manager, Inference", level_band="senior",
            locations=["Mountain View, CA, USA", "Seattle, WA, USA"], comp_median=410_000, status="closed",
            closed_at=NOW - timedelta(days=62),
        ),
        "repost": _job(
            "repost", days_ago=60, locations=["Mountain View, CA, USA", "London, UK"],
            **_stated_band(250_000, 360_000),
        ),
        "duplicate": _job(
            "duplicate", days_ago=58, locations=["Mountain View, CA, USA", "London, UK"],
            **_stated_band(250_000, 360_000),
        ),
        "rejected": _job("rejected", days_ago=40, title="Staff Product Manager, Serving"),
        "solo": _job("solo", days_ago=30, title="Group Product Manager, Search", family=None, domains=None),
        "pending_prior": _job("pending_prior", days_ago=50, title="Staff Product Manager, Payments"),
        "pending_newer": _job("pending_newer", days_ago=12, title="Staff Product Manager, Payments Platform"),
        "twin_left": _job("twin_left", days_ago=20, title="Staff Product Manager, Gemini API"),
        "twin_right": _job(
            "twin_right", days_ago=19, title="Staff Product Manager, Gemini API (Enterprise)",
            description_sections=[
                _SECTIONS[1],
                {"key": "responsibilities", "title": "Responsibilities", "content": "Own enterprise adoption of the API."},
            ],
        ),
        "twin_hub": _job("twin_hub", days_ago=18, title="Staff Product Manager, Gemini API Platform"),
        "twin_spoke": _job("twin_spoke", days_ago=17, title="Staff Product Manager, Gemini API Growth"),
        "other_company": _job("other_company", company="acme", days_ago=15),
    }
    session.add_all(jobs.values())
    await session.flush()
    ids = {key: job.id for key, job in jobs.items()}

    def lineage_link(newer: str, prior: str, **over) -> JobLineageLink:
        row = {
            "job_id": ids[newer], "prior_job_id": ids[prior], "relation": "duplicate",
            "method": "title+embedding", "score": 0.93, "title_similarity": 0.81,
            "gap_days": (jobs[newer].first_seen - jobs[prior].first_seen).days,
            "confidence": "suspected", "status": "pending", "reviewed_at": None,
            "detector_version": DETECTOR_VERSION,
            "evidence": {"reasons": ["same department and team", "description cosine 0.93"]},
        }
        row.update(over)
        return JobLineageLink(**row)

    links = {
        "repost_link": lineage_link(
            "repost", "original", relation="repost", method="embedding", confidence="auto", score=0.97,
            evidence={"reasons": ["reposted 30 days after closing", "description cosine 0.97"]},
        ),
        "duplicate_link": lineage_link(
            "duplicate", "repost", status="confirmed", reviewed_at=NOW - timedelta(days=3), score=0.99,
            evidence={
                "reasons": ["identical description", "same requisition title"],
                "review_outcome": "duplicate",
                "decision_history": [{"decision": "twin", "changed_at": (NOW - timedelta(days=4)).isoformat()}],
            },
        ),
        "rejected_link": lineage_link(
            "rejected", "duplicate", status="rejected", reviewed_at=NOW - timedelta(days=2), score=0.88,
            evidence={"reasons": ["same department"], "review_outcome": "different"},
        ),
        "pending_link": lineage_link("pending_newer", "pending_prior", score=0.91),
    }

    def twin_link(left: str, right: str, **over) -> JobTwinLink:
        a, b = sorted((ids[left], ids[right]))
        row = {
            "job_a_id": a, "job_b_id": b, "method": "section_diff", "score": 0.87, "title_similarity": 0.9,
            "confidence": "suspected", "status": "pending", "reviewed_at": None,
            "detector_version": TWIN_DETECTOR_VERSION,
        }
        row.update(over)
        return JobTwinLink(**row)

    left, right = jobs["twin_left"], jobs["twin_right"]
    described = compare_descriptions(
        left.description_sections, left.description_text, right.description_sections, right.description_text,
    ).evidence()
    twins = {
        "twin_pending": twin_link(
            "twin_left", "twin_right",
            evidence={"reasons": ["same team, different responsibilities"], "description_diff": described},
        ),
        "twin_reviewed": twin_link(
            "twin_left", "twin_hub", method="duplicate_review", status="confirmed", score=None,
            reviewed_at=NOW - timedelta(days=1),
            evidence={"reasons": ["human marked a duplicate proposal as separate twin openings"], "review_outcome": "twin"},
        ),
        "twin_manual": twin_link(
            "twin_hub", "twin_spoke", method="manual", status="confirmed", score=None, title_similarity=None,
            reviewed_at=NOW - timedelta(days=1),
            evidence={"reasons": ["human-created twin relationship"], "review_outcome": "twin"},
        ),
    }
    session.add_all([*links.values(), *twins.values()])
    await session.commit()
    await rebuild_lineage_projection(session)

    profile_id = None
    if local_model:
        profile = await create_profile(session, LocalLLMProfileInput(name="Workstation", model=MODEL_ID))
        await set_enabled(session, True)
        profile_id = profile.id
    await session.commit()

    return SeededLineage(
        **ids,
        **{key: link.id for key, link in links.items()},
        **{key: link.id for key, link in twins.items()},
        profile_id=profile_id,
    )
