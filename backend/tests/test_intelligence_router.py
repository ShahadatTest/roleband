"""Tier routing: escalation, refusal containment, and the egress gate.

Every provider here is a stub, because the point under test is the ROUTING
decision, not any model's output. Stubs record whether they were called, so a
tier that should never run can be asserted as never having run — the only way
to test "this text did not leave the Mac" without watching a socket.
"""

from __future__ import annotations

import asyncio

import pytest

from tracker.intelligence.policy import (
    MIN_SAMPLE_FOR_VETO,
    RouteReason,
    TierMeasurement,
    escalation_reason,
    skip_reason,
)
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    ProviderOrigin,
)
from tracker.intelligence.router import RouterProvider, Tier
from tracker.pay_disclosure import DisclosedComp


class StubProvider:
    """A tier with a scripted outcome that remembers whether it ran."""

    def __init__(
        self,
        name: str,
        origin: ProviderOrigin,
        *,
        fields: dict | None = None,
        failure_class: str | None = None,
        state: AvailabilityState = AvailabilityState.AVAILABLE,
        tokens: int = 10,
    ):
        self.name = name
        self.origin = origin
        self._fields = fields
        self._failure_class = failure_class
        self._state = state
        self._tokens = tokens
        self.calls = 0

    async def availability(self) -> Availability:
        return Availability(self._state)

    async def count_tokens(self, text: str) -> int:
        return self._tokens

    async def generate(self, *, instructions, prompt, schema, budget_tokens, validate=None):
        self.calls += 1
        return GenerationResult(
            fields=self._fields,
            availability_state=self._state,
            latency_ms=5,
            failure_class=self._failure_class,
            provider_name=self.name,
            origin=self.origin,
        )


def _run(router: RouterProvider, validate=None) -> GenerationResult:
    return asyncio.run(
        router.generate(
            instructions="i",
            prompt="p",
            schema=DisclosedComp,
            budget_tokens=8192,
            validate=validate,
        )
    )


def _apple(**kwargs) -> StubProvider:
    return StubProvider("apple_fm", ProviderOrigin.ON_DEVICE, **kwargs)


def _local(**kwargs) -> StubProvider:
    return StubProvider("omlx", ProviderOrigin.THIS_MAC, **kwargs)


def _cloud(**kwargs) -> StubProvider:
    return StubProvider("cloud_openai", ProviderOrigin.CLOUD, **kwargs)


# --------------------------------------------------------------------------- #
# Escalation
# --------------------------------------------------------------------------- #


def test_first_tier_success_never_touches_lower_tiers():
    apple, local, cloud = _apple(fields={"disclosed": True}), _local(), _cloud()
    res = _run(RouterProvider([Tier(apple), Tier(local), Tier(cloud)]))
    assert res.fields == {"disclosed": True}
    assert res.origin is ProviderOrigin.ON_DEVICE
    assert (local.calls, cloud.calls) == (0, 0)


def test_timeout_escalates_to_the_next_tier_and_records_why():
    apple = _apple(failure_class="timeout")
    local = _local(fields={"disclosed": False})
    res = _run(RouterProvider([Tier(apple), Tier(local)]))
    assert res.fields == {"disclosed": False}
    assert res.provider_name == "omlx"
    assert res.route_reason == RouteReason.ESCALATED_TIMEOUT
    assert [a.outcome for a in res.attempts] == ["failed", "ok"]
    # Per-attempt reasons agree with the result they persist beside: the tier
    # that caught the escalation must not be recorded as "primary".
    assert [a.reason for a in res.attempts] == [
        RouteReason.PRIMARY,
        RouteReason.ESCALATED_TIMEOUT,
    ]


def test_no_band_disclosed_is_success_and_does_not_escalate():
    # A posting stating no pay must not trigger escalation:
    # absence of a band is not a model failure.
    apple = _apple(fields={"disclosed": False})
    local = _local(fields={"disclosed": True})
    res = _run(RouterProvider([Tier(apple), Tier(local)]))
    assert res.fields == {"disclosed": False}
    assert local.calls == 0


def test_unsupported_schema_escalates_rather_than_returning_wrong_shape():
    apple = _apple(failure_class="unsupported_schema")
    local = _local(fields={"recommendation": "confirmed"})
    res = _run(RouterProvider([Tier(apple), Tier(local)]))
    assert res.route_reason == RouteReason.ESCALATED_UNSUPPORTED
    assert res.provider_name == "omlx"


def test_unknown_failure_class_still_escalates():
    apple = _apple(failure_class="something_new")
    local = _local(fields={"disclosed": True})
    res = _run(RouterProvider([Tier(apple), Tier(local)]))
    assert local.calls == 1
    assert res.fields == {"disclosed": True}


# --------------------------------------------------------------------------- #
# Privacy containment
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("failure_class", ["guardrail", "refusal"])
def test_refused_content_is_never_forwarded_off_device(failure_class):
    apple = _apple(failure_class=failure_class)
    local, cloud = _local(fields={"disclosed": True}), _cloud(fields={"disclosed": True})
    res = _run(RouterProvider([Tier(apple), Tier(local), Tier(cloud)]))
    assert res.fields is None
    assert res.route_reason == RouteReason.TERMINAL_REFUSAL
    assert (local.calls, cloud.calls) == (0, 0)


def test_blocked_cloud_tier_never_runs_even_when_every_local_tier_failed():
    apple, local = _apple(failure_class="timeout"), _local(failure_class="timeout")
    cloud = _cloud(fields={"disclosed": True})
    res = _run(
        RouterProvider(
            [
                Tier(apple),
                Tier(local),
                Tier(cloud, blocked_reason=RouteReason.EGRESS_BLOCKED),
            ]
        )
    )
    assert cloud.calls == 0
    assert res.fields is None
    assert res.route_reason == RouteReason.EXHAUSTED
    skipped = [a for a in res.attempts if a.outcome == "skipped"]
    assert [a.reason for a in skipped] == [RouteReason.EGRESS_BLOCKED]


def test_router_origin_reports_the_most_private_reachable_tier():
    router = RouterProvider(
        [Tier(_apple()), Tier(_local()), Tier(_cloud(), blocked_reason=RouteReason.EGRESS_BLOCKED)]
    )
    assert router.origin is ProviderOrigin.ON_DEVICE
    cloud_only = RouterProvider([Tier(_cloud())])
    assert cloud_only.origin is ProviderOrigin.CLOUD


def test_route_attempts_carry_no_prompt_or_output_text():
    apple = _apple(failure_class="timeout")
    local = _local(fields={"disclosed": True, "source_snippet": "$180,000 base"})
    res = _run(RouterProvider([Tier(apple), Tier(local)]))
    serialized = str([a.redacted() for a in res.attempts])
    assert "180,000" not in serialized
    assert set(res.attempts[0].redacted()) == {
        "provider",
        "origin",
        "outcome",
        "reason",
        "latency_ms",
        "failure_class",
    }


# --------------------------------------------------------------------------- #
# Availability, context, and measurement-driven skips
# --------------------------------------------------------------------------- #


def test_unavailable_tier_is_skipped_without_being_generated_against():
    apple = _apple(state=AvailabilityState.APPLE_INTELLIGENCE_DISABLED)
    local = _local(fields={"disclosed": True})
    res = _run(RouterProvider([Tier(apple), Tier(local)]))
    assert apple.calls == 0
    assert res.route_reason == RouteReason.TIER_UNAVAILABLE
    assert res.fields == {"disclosed": True}


def test_prompt_over_a_tier_context_skips_straight_to_a_bigger_one():
    apple = _apple(tokens=9000)
    local = _local(fields={"disclosed": True})
    res = _run(RouterProvider([Tier(apple, context_tokens=8192), Tier(local)]))
    assert apple.calls == 0
    assert res.route_reason == RouteReason.ESCALATED_CONTEXT


def test_tier_with_a_total_measured_failure_record_is_vetoed():
    dead = TierMeasurement(provider="apple_fm", attempts=MIN_SAMPLE_FOR_VETO, ok=0)
    apple = _apple(fields={"disclosed": True})
    local = _local(fields={"disclosed": False})
    res = _run(RouterProvider([Tier(apple, measurement=dead), Tier(local)]))
    assert apple.calls == 0
    assert res.route_reason == RouteReason.SKIPPED_MEASURED_FAILURE


def test_a_partially_working_tier_is_still_tried():
    # Cheaper and more private; its failures escalate anyway.
    mixed = TierMeasurement(provider="apple_fm", attempts=50, ok=1)
    apple = _apple(fields={"disclosed": True})
    _run(RouterProvider([Tier(apple, measurement=mixed), Tier(_local())]))
    assert apple.calls == 1


def test_small_failing_sample_does_not_veto():
    thin = TierMeasurement(provider="apple_fm", attempts=MIN_SAMPLE_FOR_VETO - 1, ok=0)
    apple = _apple(fields={"disclosed": True})
    assert skip_reason(thin) is None
    _run(RouterProvider([Tier(apple, measurement=thin)]))
    assert apple.calls == 1


def test_cold_start_is_distinguishable_from_a_measured_primary():
    apple = _apple(fields={"disclosed": True})
    cold = _run(RouterProvider([Tier(apple)]))
    assert cold.route_reason == RouteReason.COLD_START

    measured = TierMeasurement(provider="apple_fm", attempts=10, ok=9)
    warm = _run(RouterProvider([Tier(_apple(fields={"disclosed": True}), measurement=measured)]))
    assert warm.route_reason == RouteReason.PRIMARY


def test_empty_ladder_reports_unconfigured_rather_than_crashing():
    res = _run(RouterProvider([]))
    assert res.fields is None
    assert res.availability_state is AvailabilityState.NOT_CONFIGURED


# --------------------------------------------------------------------------- #
# Policy units
# --------------------------------------------------------------------------- #


def test_escalation_reason_maps_every_documented_failure_class():
    assert escalation_reason("timeout") == RouteReason.ESCALATED_TIMEOUT
    assert escalation_reason("truncated") == RouteReason.ESCALATED_TRUNCATED
    assert escalation_reason("validation") == RouteReason.ESCALATED_VALIDATION
    assert escalation_reason("rate_limited") == RouteReason.ESCALATED_RATE_LIMITED
    assert escalation_reason("guardrail") is None
    assert escalation_reason("refusal") is None
    assert escalation_reason(None) is None


def test_route_reason_values_fit_the_persisted_column():
    # ai_task_log.route_reason is String(32); a longer value would truncate or
    # error on write depending on the driver, so the vocabulary is bounded here.
    values = [
        value
        for name, value in vars(RouteReason).items()
        if not name.startswith("_") and isinstance(value, str)
    ]
    assert values, "RouteReason must expose values"
    assert max(len(value) for value in values) <= 32


# --------------------------------------------------------------------------- #
# Acceptance vs parseability
#
# "Returned parseable fields" is not acceptance. A router that returns the first
# tier that produced JSON leaves the caller to discover an ungrounded answer
# afterwards, by which point `_mark_processed` has made it permanent, and
# `escalation_reason("validation")` never fires for the case `policy.py` names
# it for. The stakes: a faster tier ahead of a more accurate one in the ladder.
# --------------------------------------------------------------------------- #


#: Stands in for the grounding check: a claimed band is accepted only when the
#: posting actually contains it. "No band" is never refuted (the real
#: `_grounds` is one-sided for the same reason).
def _grounded_only(fields: dict) -> bool:
    if not fields.get("disclosed"):
        return True
    return bool(fields.get("grounded"))


def test_an_ungrounded_band_escalates_to_the_tier_that_gets_it_right():
    apple = _apple(fields={"disclosed": True, "grounded": False})
    local = _local(fields={"disclosed": True, "grounded": True})
    router = RouterProvider([Tier(apple), Tier(local)])

    result = _run(router, validate=_grounded_only)

    assert local.calls == 1, "the second tier was actually consulted"
    assert result.fields == {"disclosed": True, "grounded": True}
    assert result.provider_name == "omlx"
    assert result.route_reason == RouteReason.ESCALATED_VALIDATION
    # The rejected tier is recorded as having answered WRONG, not as having
    # broken — accuracy grading reads exactly this.
    rejected = next(a for a in result.attempts if a.provider == "apple_fm")
    assert rejected.outcome == "failed"
    assert rejected.failure_class == "validation"


def test_a_correct_no_band_answer_does_not_walk_the_ladder():
    """The asymmetry that keeps this affordable. Most postings disclose no pay,
    and rejecting "no band" would escalate every one of them to the slowest
    tier only to arrive at the same answer."""
    apple = _apple(fields={"disclosed": False})
    local = _local(fields={"disclosed": True, "grounded": True})
    router = RouterProvider([Tier(apple), Tier(local)])

    result = _run(router, validate=_grounded_only)

    assert local.calls == 0, "the expensive tier was never woken"
    assert result.provider_name == "apple_fm"
    # `cold_start` rather than `primary` only because this stub tier carries no
    # measurement; what matters is that nothing escalated.
    assert result.route_reason in {RouteReason.PRIMARY, RouteReason.COLD_START}


def test_without_a_validator_the_first_parseable_answer_still_wins():
    """With no referee, the caller gets the first parseable answer."""
    apple = _apple(fields={"disclosed": True, "grounded": False})
    local = _local(fields={"disclosed": True, "grounded": True})
    router = RouterProvider([Tier(apple), Tier(local)])

    result = _run(router)

    assert local.calls == 0
    assert result.provider_name == "apple_fm"


def test_when_every_tier_is_rejected_the_last_answer_is_still_returned():
    """No tier could ground the band, so there is no better answer to be had.
    Withholding the output would turn "nothing grounded this" into "the model
    failed" — a different and less true statement — and would lose the
    caller's existing handling of a bad answer."""
    apple = _apple(fields={"disclosed": True, "grounded": False})
    local = _local(fields={"disclosed": True, "grounded": False})
    router = RouterProvider([Tier(apple), Tier(local)])

    result = _run(router, validate=_grounded_only)

    assert apple.calls == 1 and local.calls == 1
    assert result.fields is not None, "the caller still gets something to coerce"
    assert result.failure_class == "validation"
    assert result.route_reason == RouteReason.EXHAUSTED


def test_a_rejected_tier_is_not_confused_with_a_broken_one():
    """Both land in the failure path, and they must stay distinguishable: a
    `sdk_error` says the model never answered, `validation` says it answered
    wrongly. Accuracy grading grades the second and deliberately ignores the first."""
    broken = _apple(fields=None, failure_class="sdk_error")
    rejected = _local(fields={"disclosed": True, "grounded": False})
    router = RouterProvider([Tier(broken), Tier(rejected)])

    result = _run(router, validate=_grounded_only)

    by_provider = {a.provider: a for a in result.attempts}
    assert by_provider["apple_fm"].failure_class == "sdk_error"
    assert by_provider["omlx"].failure_class == "validation"
