"""Routing policy — pure decisions over measured evidence.

Deliberately DB-free: `telemetry.measure_tiers` reads `ai_task_log` and hands
plain dataclasses in here. That split keeps every routing rule unit-testable
without a database, and keeps `tracker.intelligence` off a new upward import.

The policy answers exactly three questions, and nothing else decides them:

1. Should this tier be tried at all?      -> `skip_reason`
2. Did this attempt earn an escalation?   -> `escalation_reason`
3. Which tier answered, and why?          -> a `RouteReason` on the log row

WHY THESE RULES. The escalation set is not "everything that went
wrong": it is the failure classes where a *different, larger* model is a
plausible fix. Two classes are excluded on purpose.

  - `guardrail` / `refusal` never escalate. The on-device model declining
    content is not evidence a cloud model would do better, and shipping exactly
    the text one model refused to a third party is the worst possible default
    for a product whose shipped promise is about staying on the Mac.
  - A clean "no pay band disclosed" is a SUCCESS, not a failure. Escalating it
    would multiply cost across the majority of postings that legitimately state
    no band, which is the single most expensive mistake this router could make.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A tier must have failed at least this many logged attempts before its measured
# record is allowed to veto it. Below this the sample is noise, and a cold or
# freshly-fixed backend would be locked out by one bad afternoon.
MIN_SAMPLE_FOR_VETO = 5


class RouteReason:
    """Why a given tier produced (or did not produce) the answer.

    Persisted verbatim in `ai_task_log.route_reason`, so these strings are a
    stable vocabulary — add values, never repurpose one.
    """

    PRIMARY = "primary"  # first tier, worked
    COLD_START = "cold_start"  # first tier, worked, and we had no measurements
    TIER_UNAVAILABLE = "tier_unavailable"
    EGRESS_BLOCKED = "egress_blocked"
    SKIPPED_MEASURED_FAILURE = "skipped_measured_failure"
    SKIPPED_CONTEXT = "skipped_context"
    ESCALATED_TIMEOUT = "escalated_timeout"
    ESCALATED_TRUNCATED = "escalated_truncated"
    ESCALATED_VALIDATION = "escalated_validation"
    ESCALATED_CONTEXT = "escalated_context"
    ESCALATED_UNSUPPORTED = "escalated_unsupported"
    ESCALATED_RATE_LIMITED = "escalated_rate_limited"
    ESCALATED_UNREACHABLE = "escalated_unreachable"
    ESCALATED_SDK_ERROR = "escalated_sdk_error"
    TERMINAL_REFUSAL = "terminal_refusal"
    EXHAUSTED = "exhausted"


# failure_class -> the reason recorded when it sends work to the next tier.
ESCALATION_REASONS: dict[str, str] = {
    "timeout": RouteReason.ESCALATED_TIMEOUT,
    "truncated": RouteReason.ESCALATED_TRUNCATED,
    "validation": RouteReason.ESCALATED_VALIDATION,
    "context_exceeded": RouteReason.ESCALATED_CONTEXT,
    "unsupported_schema": RouteReason.ESCALATED_UNSUPPORTED,
    "rate_limited": RouteReason.ESCALATED_RATE_LIMITED,
    "server_unreachable": RouteReason.ESCALATED_UNREACHABLE,
    "connection": RouteReason.ESCALATED_UNREACHABLE,
    "http_error": RouteReason.ESCALATED_UNREACHABLE,
    "api_error": RouteReason.ESCALATED_UNREACHABLE,
    "sdk_error": RouteReason.ESCALATED_SDK_ERROR,
}

# Failure classes that end the run where they happened. See module docstring.
TERMINAL_FAILURES: frozenset[str] = frozenset({"guardrail", "refusal", "no_credentials"})


@dataclass(frozen=True)
class TierMeasurement:
    """What `ai_task_log` actually recorded for one provider on one task."""

    provider: str
    attempts: int = 0
    ok: int = 0
    failures: dict[str, int] = field(default_factory=dict)
    p50_latency_ms: int | None = None
    p90_latency_ms: int | None = None
    #: Rows an independent referee could actually judge. Strictly a
    #: subset of `attempts`: most rows carry no referee evidence either way.
    graded: int = 0
    #: Of those, how many the referee agreed with.
    correct: int = 0

    @property
    def has_sample(self) -> bool:
        return self.attempts > 0

    @property
    def success_rate(self) -> float:
        """How often the response was USABLE — the parseability axis.

        Emphatically not "how often it was right". A model that confidently
        returns a well-formed wrong answer scores 1.0 here.
        """
        return self.ok / self.attempts if self.attempts else 0.0

    @property
    def accuracy(self) -> float | None:
        """How often an independent referee AGREED — the correctness axis.

        `None`, never 0.0, when nothing could be graded. The distinction is the
        whole point: "no referee evidence" and "wrong every time" are opposite
        findings, and collapsing them into a number is how a tier with no
        measurement at all would look like the worst tier available.
        """
        return self.correct / self.graded if self.graded else None


def escalation_reason(failure_class: str | None) -> str | None:
    """The reason to move on, or None when this failure ends the run.

    An unrecognized failure class escalates: a tier we cannot classify is a tier
    we should not trust to be the last word.
    """
    if failure_class is None:
        return None
    if failure_class in TERMINAL_FAILURES:
        return None
    return ESCALATION_REASONS.get(failure_class, RouteReason.ESCALATED_SDK_ERROR)


def terminal_reason(failure_class: str | None) -> str:
    return (
        RouteReason.TERMINAL_REFUSAL
        if failure_class in TERMINAL_FAILURES
        else RouteReason.EXHAUSTED
    )


def skip_reason(measurement: TierMeasurement | None) -> str | None:
    """Veto a tier its own record says cannot do this task.

    Only a total failure record vetoes, and only past `MIN_SAMPLE_FOR_VETO`.
    A partially-working tier is still worth trying: its successes are cheaper
    and more private than the tier above it, and its failures escalate anyway.
    """
    if measurement is None or not measurement.has_sample:
        return None
    if measurement.attempts >= MIN_SAMPLE_FOR_VETO and measurement.ok == 0:
        return RouteReason.SKIPPED_MEASURED_FAILURE
    return None


def success_reason(index: int, measured: bool, escalated_from: str | None) -> str:
    """Reason for the tier that actually answered."""
    if escalated_from:
        return escalated_from
    if index == 0:
        return RouteReason.PRIMARY if measured else RouteReason.COLD_START
    return RouteReason.PRIMARY
