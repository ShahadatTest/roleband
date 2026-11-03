"""Provider availability + graceful degradation.

These tests must give the SAME result on a Mac with the SDK installed and on Linux
CI without it, so SDK presence is CONTROLLED here (never inherited from the host):
`_fm=None` simulates absence, and reason-mapping is checked against a stub enum
mirroring `apple_fm_sdk.SystemLanguageModelUnavailableReason`.
"""

from __future__ import annotations

import asyncio
from enum import Enum

from tracker.intelligence.apple_fm import AppleFMProvider, _failure_class, _map_reason, _to_dict
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    NullProvider,
)
from tracker.intelligence.registry import build_provider
from tracker.pay_disclosure import DisclosedComp


class _Reason(Enum):
    """Mirrors the SDK enum so mapping is testable without the SDK."""

    APPLE_INTELLIGENCE_NOT_ENABLED = 0
    DEVICE_NOT_ELIGIBLE = 1
    MODEL_NOT_READY = 2
    UNKNOWN = 255


class _StubFM:
    SystemLanguageModelUnavailableReason = _Reason


def _sdk_absent_provider() -> AppleFMProvider:
    p = AppleFMProvider()
    p._loaded = True  # skip the import
    p._fm = None  # ...and pretend it failed
    return p


def test_null_provider_reports_reason_and_never_generates():
    p = NullProvider(AvailabilityState.DISABLED_BY_FLAG, "off")
    avail = asyncio.run(p.availability())
    assert avail.state is AvailabilityState.DISABLED_BY_FLAG
    assert avail.ok is False
    res = asyncio.run(
        p.generate(instructions="i", prompt="p", schema=DisclosedComp, budget_tokens=8192)
    )
    assert res.fields is None
    assert res.failure_class == "unavailable"


def test_disabled_toggle_yields_null_provider():
    # Enablement is the REGISTRY's job, not the provider's.
    p = build_provider(enabled=False)
    assert isinstance(p, NullProvider)
    assert asyncio.run(p.availability()).state is AvailabilityState.DISABLED_BY_FLAG


def test_enabled_toggle_yields_apple_provider():
    assert isinstance(build_provider(enabled=True), AppleFMProvider)


def test_sdk_absent_degrades_without_raising():
    p = _sdk_absent_provider()
    assert asyncio.run(p.availability()).state is AvailabilityState.SDK_ABSENT
    res = asyncio.run(
        p.generate(instructions="i", prompt="p", schema=DisclosedComp, budget_tokens=8192)
    )
    assert res.fields is None
    assert res.availability_state is AvailabilityState.SDK_ABSENT
    assert res.failure_class == "unavailable"


def test_apple_refuses_a_schema_its_generable_does_not_mirror():
    # Guided generation is hardwired to DisclosedComp. Answering a different
    # schema would return DisclosedComp-shaped fields that quietly fail the
    # caller's validator; the router needs to see "can't do this task" instead.
    class DuplicateAssessment:  # any other structured task
        pass

    p = AppleFMProvider()
    p._loaded = True
    p._fm = _StubFM()  # would be used only if the guard let it through
    res = asyncio.run(
        p.generate(
            instructions="i", prompt="p", schema=DuplicateAssessment, budget_tokens=8192
        )
    )
    assert res.fields is None
    assert res.failure_class == "unsupported_schema"


def test_count_tokens_falls_back_to_heuristic_without_sdk():
    p = _sdk_absent_provider()
    assert asyncio.run(p.count_tokens("a" * 40)) == 10


def test_map_reason_covers_every_sdk_reason():
    assert _map_reason(_StubFM, _Reason.APPLE_INTELLIGENCE_NOT_ENABLED) is (
        AvailabilityState.APPLE_INTELLIGENCE_DISABLED
    )
    assert _map_reason(_StubFM, _Reason.DEVICE_NOT_ELIGIBLE) is AvailabilityState.DEVICE_INELIGIBLE
    assert _map_reason(_StubFM, _Reason.MODEL_NOT_READY) is AvailabilityState.MODEL_NOT_READY
    # Unknown/unmapped reasons must not crash — they degrade to "not ready".
    assert _map_reason(_StubFM, _Reason.UNKNOWN) is AvailabilityState.MODEL_NOT_READY
    assert _map_reason(_StubFM, None) is AvailabilityState.MODEL_NOT_READY


def test_failure_class_defaults_to_sdk_error():
    assert _failure_class(_StubFM, ValueError("boom")) == "sdk_error"


def test_to_dict_reads_generable_fields():
    class Gen:
        disclosed = True
        base_min = 180000
        base_max = 240000
        currency = "USD"
        pay_basis = "base"
        pay_period = "year"
        source_snippet = "$180,000—$240,000 USD"
        confidence = "high"

    out = _to_dict(Gen())
    assert out["base_min"] == 180000
    assert out["source_snippet"] == "$180,000—$240,000 USD"


def test_availability_messages_are_actionable():
    # The Settings UI shows these verbatim; each state must explain itself.
    for state in AvailabilityState:
        msg = Availability(state).message
        assert msg and msg[0].isupper()
    assert "turned off" in Availability(AvailabilityState.DISABLED_BY_FLAG).message.lower()
    assert "sdk" in Availability(AvailabilityState.SDK_ABSENT).message.lower()
    assert "system settings" in (
        Availability(AvailabilityState.APPLE_INTELLIGENCE_DISABLED).message.lower()
    )
