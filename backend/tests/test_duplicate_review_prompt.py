"""Duplicate review prompt hygiene, verdict survival, and the thinking override.

These pin prompt evidence, verdict parsing, and thinking controls. All pure/mocked;
live model confidence belongs in `scripts.bench_duplicate_review`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from tracker.intelligence.duplicate_review import (
    MAX_LIST_ITEMS,
    MAX_SUMMARY_CHARS,
    PROMPT_VERSION,
    DuplicateAssessment,
    assess_duplicate,
    build_duplicate_prompt,
)
from tracker.local_llm.client import LocalLLMClient
from tracker.local_llm.models import LocalLLMParameters, LocalLLMProfile


def _job(job_id: int, title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id, company="microsoft", req_id=f"REQ{job_id}",
        url=f"https://example.com/{job_id}", title=title, department="Cloud",
        team="CoreAI", locations=["Redmond, WA"], location_groups=["seattle"],
        workplace_type="onsite", level_band="senior", level_confidence="high",
        family="engineering", track="technical", status="open", in_scope=True,
        posted_at=datetime(2026, 7, 11, tzinfo=UTC),
        first_seen=datetime(2026, 7, 11, tzinfo=UTC),
        last_seen=datetime(2026, 7, 20, tzinfo=UTC), closed_at=None,
        total_days_open=9, repost_count=0, lineage_id=None, lineage_seq=1,
        lineage_role="original", lineage_first_seen=None,
        comp_low=1, comp_high=2, comp_median=1, comp_currency="USD",
        comp_provenance="seed", disclosed_base_min=None, disclosed_base_max=None,
        disclosed_currency=None, disclosed_pay_basis=None, disclosed_pay_period=None,
        disclosed_snippet=None, disclosed_confidence=None, disclosed_bonus_pct=None,
        structured_at=None, description_text=f"Description for {title}.",
        description_sections=[{"key": "about", "title": "About", "content": "Team text"}],
    )


def _link() -> SimpleNamespace:
    return SimpleNamespace(
        id=47, relation="duplicate", method="title+embedding", score=1.0,
        gap_days=0, evidence={"reasons": ["identical_title", "cosine_1.0"]},
    )


# --------------------------------------------------------------------------- #
# The detector's conclusion must not reach the model
# --------------------------------------------------------------------------- #


def test_prompt_withholds_every_detector_signal():
    """Given the detector's verdict as evidence, the model agrees with it and
    gets fewer pairs right than with no hint. An advisory that echoes the detector tells the reviewer nothing they cannot already see.
    """
    prompt = build_duplicate_prompt(_link(), _job(1, "Staff Engineer"), _job(2, "Staff Engineer"))
    for leaked in (
        "detector_relation",
        "detector_method",
        "detector_score",
        "detector_reasons",
        "candidate_link",
        "identical_title",  # a reason string from evidence
        "cosine_1.0",
    ):
        assert leaked not in prompt, f"{leaked} leaked into the prompt"
    assert "title+embedding" not in prompt


def test_prompt_withholds_the_lineage_the_detectors_links_project():
    """A pending auto link already counts toward a lineage, so both postings
    carry its id and the newer one is its `repost`: that is the detector's
    verdict again, in other words."""
    prior = SimpleNamespace(**{**vars(_job(1, "Staff Engineer")), "lineage_id": 9071, "lineage_seq": 1,
                               "lineage_role": "original", "repost_count": 0, "total_days_open": 40})
    newer = SimpleNamespace(**{**vars(_job(2, "Staff Engineer")), "lineage_id": 9071, "lineage_seq": 2,
                               "lineage_role": "repost", "repost_count": 1, "total_days_open": 3})
    prompt = build_duplicate_prompt(_link(), prior, newer)
    payload = json.loads(prompt.split("<job_evidence>\n", 1)[1].split("\n</job_evidence>", 1)[0])
    for posting in payload.values():
        for projected in ("lineage", "repost_count", "total_days_open"):
            assert projected not in posting, projected
    for leaked in ("9071", "repost"):
        assert leaked not in prompt, f"{leaked} leaked into the prompt"


def test_prompt_still_carries_both_postings_in_full():
    prompt = build_duplicate_prompt(_link(), _job(1, "Staff Engineer"), _job(2, "Senior Engineer"))
    assert "earlier_posting" in prompt and "newer_posting" in prompt
    assert "Staff Engineer" in prompt and "Senior Engineer" in prompt
    # gap_days is dropped, but the dates it derives from are still present.
    assert "posted_at" in prompt and "first_seen" in prompt
    assert "<job_evidence>" in prompt and "</job_evidence>" in prompt


def _payload(prompt: str) -> dict:
    return json.loads(prompt.split("<job_evidence>\n", 1)[1].split("\n</job_evidence>", 1)[0])


def test_the_model_sees_the_period_the_reader_sees():
    """A yearly salary stored as hourly would reach the reviewer as a
    $600,000 hourly rate beside its yearly repost: a difference that is not
    there. The served period says "could not tell"."""
    prior, newer = _job(1, "Staff Engineer"), _job(2, "Staff Engineer")
    for job, period in ((prior, "hour"), (newer, "year")):
        job.disclosed_base_min, job.disclosed_base_max = 600_000, 1_066_000
        job.disclosed_currency, job.disclosed_pay_period = "USD", period
    payload = _payload(build_duplicate_prompt(_link(), prior, newer))
    assert payload["earlier_posting"]["disclosed_comp"]["pay_period"] == "unclear"
    assert payload["newer_posting"]["disclosed_comp"]["pay_period"] == "year"
    # No band: nothing to check, so the stored value passes through.
    assert _payload(build_duplicate_prompt(_link(), _job(3, "A"), _job(4, "B")))[
        "earlier_posting"]["disclosed_comp"]["pay_period"] is None


def test_prompt_version_records_the_withholding():
    # Telemetry tells one prompt's assessments from another's by this stamp.
    assert PROMPT_VERSION == "duplicate_review/v3"


# --------------------------------------------------------------------------- #
# A verdict survives a verbose response
# --------------------------------------------------------------------------- #


def test_a_ninth_evidence_item_clips_instead_of_destroying_the_verdict():
    """Verbose is not malformed: a ninth evidence item must not destroy a call
    that carries a correct, confident verdict."""
    assessment = DuplicateAssessment.model_validate({
        "recommendation": "confirmed",
        "confidence": 0.98,
        "summary": "Same requisition reposted.",
        "matching_evidence": [f"evidence {i}" for i in range(12)],
        "differences": [f"difference {i}" for i in range(11)],
    })
    assert assessment.recommendation == "confirmed"
    assert len(assessment.matching_evidence) == MAX_LIST_ITEMS
    assert len(assessment.differences) == MAX_LIST_ITEMS
    assert assessment.matching_evidence[0] == "evidence 0"


def test_an_overlong_summary_clips_instead_of_destroying_the_verdict():
    assessment = DuplicateAssessment.model_validate({
        "recommendation": "rejected",
        "confidence": 0.5,
        "summary": "x" * (MAX_SUMMARY_CHARS + 500),
        "matching_evidence": [],
        "differences": [],
    })
    assert assessment.recommendation == "rejected"
    assert len(assessment.summary) == MAX_SUMMARY_CHARS


def test_non_string_evidence_items_are_dropped_not_fatal():
    assessment = DuplicateAssessment.model_validate({
        "recommendation": "uncertain", "confidence": 0.4, "summary": "Unclear.",
        "matching_evidence": ["real", {"nested": "object"}, 42, "also real"],
        "differences": [],
    })
    assert assessment.matching_evidence == ["real", "also real"]


@pytest.mark.parametrize(
    "payload",
    [
        {"recommendation": "maybe", "confidence": 0.9, "summary": "s"},  # not in the enum
        {"recommendation": "confirmed", "confidence": 1.4, "summary": "s"},  # out of range
        {"recommendation": "confirmed", "confidence": 0.9, "summary": ""},  # no verdict text
        {"confidence": 0.9, "summary": "s"},  # no recommendation at all
    ],
)
def test_a_malformed_verdict_still_fails_closed(payload):
    # Clipping is for DISPLAY bounds only. The verdict itself stays strict.
    with pytest.raises(ValueError):
        DuplicateAssessment.model_validate(payload)


# --------------------------------------------------------------------------- #
# Thinking is off for structured output, without touching the saved profile
# --------------------------------------------------------------------------- #


def _profile() -> LocalLLMProfile:
    return LocalLLMProfile(
        id="profile12345", name="Local", provider="omlx",
        base_url="http://127.0.0.1:8000/v1", model="test-model", api_key=None,
        parameters=LocalLLMParameters(enable_thinking=True, thinking_budget=2048),
    )


def test_chat_payload_honours_a_per_call_thinking_override():
    params = LocalLLMParameters(enable_thinking=True, thinking_budget=2048)
    assert params.chat_payload()["chat_template_kwargs"] == {"enable_thinking": True}
    off = params.chat_payload(thinking=False)
    assert off["chat_template_kwargs"] == {"enable_thinking": False}
    # A budget beside a disabled channel is contradictory; some servers honour it.
    assert "thinking_budget" not in off
    # The profile itself is untouched.
    assert params.enable_thinking is True


def test_duplicate_review_disables_thinking_on_the_wire():
    """The structured-output request disables thinking to avoid a reasoning
    preamble delaying or crowding out the verdict JSON."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "test-model",
            "choices": [{
                "message": {"content": json.dumps({
                    "recommendation": "rejected", "confidence": 0.6,
                    "summary": "Distinct roles.",
                    "matching_evidence": ["same company"],
                    "differences": ["different level"],
                })},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        })

    profile = _profile()
    client = LocalLLMClient(
        profile, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    result = asyncio.run(
        assess_duplicate(client, _link(), _job(1, "Staff Engineer"), _job(2, "Staff Engineer"))
    )
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert "thinking_budget" not in sent
    assert profile.parameters.enable_thinking is True  # saved profile unchanged
    assert result["assessment"]["recommendation"] == "rejected"
    assert result["prompt_version"] == PROMPT_VERSION


def test_the_body_sent_to_the_model_contains_no_detector_fields():
    """End-to-end guard: the hygiene must hold on the actual wire payload, not
    just in the prompt builder."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "test-model",
            "choices": [{
                "message": {"content": json.dumps({
                    "recommendation": "uncertain", "confidence": 0.5,
                    "summary": "Unclear.", "matching_evidence": [], "differences": [],
                })},
                "finish_reason": "stop",
            }],
            "usage": {},
        })

    client = LocalLLMClient(
        _profile(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    asyncio.run(
        assess_duplicate(client, _link(), _job(1, "Staff Engineer"), _job(2, "Staff Engineer"))
    )
    body = json.dumps(sent)
    for leaked in ("detector_relation", "detector_score", "detector_reasons", "cosine_1.0"):
        assert leaked not in body
