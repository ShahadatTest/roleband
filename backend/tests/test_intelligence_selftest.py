"""Settings "Test" button service — run_self_test (fake provider, no DB/model).

The self-test must exercise the REAL path (prefilter -> generate -> grounding), be
a dry run (never touch `jobs`), and tell the user plainly what happened in each
outcome: unavailable, model failure, grounded success, ungrounded rejection.
"""

from __future__ import annotations

import asyncio

from tracker.db.models import AiTaskLog
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    NullProvider,
)
from tracker.intelligence_runtime.selftest import SAMPLE_POSTING, TEST_TASK, run_self_test


class FakeProvider:
    def __init__(self, *, state=AvailabilityState.AVAILABLE, result=None):
        self.name = "fake"
        self._state = state
        self._result = result

    async def availability(self):
        return Availability(self._state)

    async def count_tokens(self, text):
        return max(1, len((text or "").split()))

    async def generate(self, *, instructions, prompt, schema, budget_tokens, validate=None):
        self.last_prompt = prompt
        return self._result


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _good_result():
    return GenerationResult(
        fields={
            "disclosed": True,
            "base_min": 180000,
            "base_max": 240000,
            "currency": "USD",
            "pay_basis": "base",
            "pay_period": "year",
            "source_snippet": "$180,000—$240,000 USD",
            "confidence": "high",
        },
        availability_state=AvailabilityState.AVAILABLE,
        latency_ms=1100,
    )


def test_sample_posting_states_a_band_the_model_should_find():
    # Guard the fixture itself: the built-in sample must actually contain a band,
    # else a "no band found" test result would be meaningless.
    assert "$180,000" in SAMPLE_POSTING and "$240,000" in SAMPLE_POSTING


def test_unavailable_reports_actionable_reason_and_logs_skip():
    session = FakeSession()
    provider = NullProvider(AvailabilityState.SDK_ABSENT)
    out = asyncio.run(run_self_test(session, provider))

    assert out["ok"] is False
    assert out["availability"]["state"] == "sdk_absent"
    # The dashboard says why from `availability.state`; no English here.
    assert "reason" not in out
    rows = [o for o in session.added if isinstance(o, AiTaskLog)]
    assert len(rows) == 1
    assert rows[0].task_type == TEST_TASK  # separable from real extraction telemetry
    assert rows[0].validation_result == "skipped"


def test_grounded_success_reports_raw_and_extracted():
    session = FakeSession()
    out = asyncio.run(run_self_test(session, FakeProvider(result=_good_result())))

    assert out["ok"] is True
    assert out["grounded"] is True
    assert out["rejected_ungrounded"] is False
    assert out["used_sample"] is True
    # The user sees BOTH what the model said and what survived validation.
    assert out["raw"]["base_min"] == 180000
    assert out["extracted"]["base_min"] == 180000
    assert out["extracted"]["base_max"] == 240000
    assert out["extracted"]["currency"] == "USD"
    assert out["latency_ms"] == 1100
    assert out["expected"]["base_min"] == 180000  # so the UI can show expected vs actual
    rows = [o for o in session.added if isinstance(o, AiTaskLog)]
    assert rows[0].validation_result == "ok"


def test_ungrounded_band_is_rejected_and_explained():
    session = FakeSession()
    bad = GenerationResult(
        fields={
            "disclosed": True,
            "base_min": 900000,
            "base_max": 950000,
            "currency": "USD",
            "source_snippet": "$900,000-$950,000 USD",  # not in the sample text
        },
        availability_state=AvailabilityState.AVAILABLE,
    )
    out = asyncio.run(run_self_test(session, FakeProvider(result=bad)))

    assert out["ok"] is True  # the call worked...
    assert out["rejected_ungrounded"] is True  # ...but the band was not in the text
    assert out["grounded"] is False
    assert out["extracted"]["disclosed"] is False
    assert "reason" not in out  # `rejected_ungrounded` says it
    rows = [o for o in session.added if isinstance(o, AiTaskLog)]
    assert rows[0].validation_result == "invalid"
    assert rows[0].failure_class == "validation"


def test_model_failure_reports_failure_class():
    session = FakeSession()
    provider = FakeProvider(
        result=GenerationResult(
            fields=None, availability_state=AvailabilityState.AVAILABLE, failure_class="timeout"
        )
    )
    out = asyncio.run(run_self_test(session, provider))

    assert out["ok"] is False
    assert out["failure_class"] == "timeout"
    rows = [o for o in session.added if isinstance(o, AiTaskLog)]
    assert rows[0].failure_class == "timeout"


def test_custom_text_without_pay_is_prefiltered_without_model_call():
    session = FakeSession()
    # generate() would return None and blow the assertions if it were called.
    provider = FakeProvider(result=None)
    out = asyncio.run(run_self_test(session, provider, text="No compensation mentioned at all."))

    assert out["ok"] is True
    assert out["prefiltered"] is True
    assert out["used_sample"] is False
    assert out["raw"] is None


def test_custom_text_is_used_over_sample():
    session = FakeSession()
    provider = FakeProvider(
        result=GenerationResult(
            fields={
                "disclosed": True,
                "base_min": 100000,
                "base_max": 120000,
                "currency": "USD",
                "source_snippet": "$100,000-$120,000",
            },
            availability_state=AvailabilityState.AVAILABLE,
        )
    )
    out = asyncio.run(
        run_self_test(session, provider, text="Base salary: $100,000-$120,000 per year.")
    )
    assert out["used_sample"] is False
    assert out["grounded"] is True
    assert out["extracted"]["base_max"] == 120000
