"""The measurement substrate feeding routing policy (fold + window).

Two failure modes are pinned here:

* **Permanent veto lockout.** A vetoed tier is skipped, a skipped tier logs no
  rows, so an unwindowed record could never change: a tier that was broken
  once (say a schema bug with a 100% failure rate) would stay locked out after
  being fixed. The window is the recovery path: failure rows
  age out, the record empties, and `skip_reason(None)` lets the tier probe.
* **Invisible failures of non-final tiers.** `extract` logs one row per job,
  keyed by the ANSWERING provider; a tier that failed and escalated appears
  only in `meta.route_attempts`. Unless the fold reads those, the veto can
  essentially never engage in ladder mode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tracker.intelligence.policy import (
    MIN_SAMPLE_FOR_VETO,
    RouteReason,
    skip_reason,
)
from tracker.intelligence.telemetry import (
    MEASUREMENT_WINDOW_DAYS,
    fold_measurements,
    measurement_cutoff,
)


def _row(
    provider: str,
    validation_result: str = "ok",
    failure_class: str | None = None,
    latency_ms: int | None = 1000,
    meta: dict | None = None,
):
    return SimpleNamespace(
        provider=provider,
        validation_result=validation_result,
        failure_class=failure_class,
        latency_ms=latency_ms,
        meta=meta or {},
    )


def _routed_row_where_apple_failed(answerer: str = "omlx") -> SimpleNamespace:
    """One job: apple_fm timed out, the local tier caught it and answered."""
    return _row(
        answerer,
        meta={
            "route_attempts": [
                {
                    "provider": "apple_fm",
                    "outcome": "failed",
                    "reason": "primary",
                    "failure_class": "timeout",
                    "latency_ms": 30_000,
                },
                {
                    "provider": answerer,
                    "outcome": "ok",
                    "reason": "escalated_timeout",
                    "latency_ms": 900,
                },
            ]
        },
    )


# --- non-final attempts ----------------------------------------------------- #


def test_earlier_tier_failures_are_counted_from_route_attempts():
    measured = fold_measurements([_routed_row_where_apple_failed() for _ in range(3)])

    apple = measured["apple_fm"]
    assert apple.attempts == 3
    assert apple.ok == 0
    assert apple.failures == {"timeout": 3}
    # The answering tier is judged by the row, not double-counted from its
    # own attempts entry.
    assert measured["omlx"].attempts == 3
    assert measured["omlx"].ok == 3


def test_enough_recorded_escalations_engage_the_veto():
    """Apple fails every job,
    local catches every one, and apple's record must still reach the veto."""
    rows = [_routed_row_where_apple_failed() for _ in range(MIN_SAMPLE_FOR_VETO)]
    measured = fold_measurements(rows)
    assert skip_reason(measured["apple_fm"]) == RouteReason.SKIPPED_MEASURED_FAILURE


def test_answering_tier_is_judged_by_our_validator_not_by_parseability():
    """Router 'ok' means 'returned parseable fields'. A tier whose fields then
    fail validation must not count as a success."""
    rows = [
        _row(
            "omlx",
            validation_result="invalid",
            failure_class="validation",
            meta={"route_attempts": [{"provider": "omlx", "outcome": "ok", "reason": "primary"}]},
        )
        for _ in range(MIN_SAMPLE_FOR_VETO)
    ]
    measured = fold_measurements(rows)
    assert measured["omlx"].ok == 0
    assert measured["omlx"].failures == {"validation": MIN_SAMPLE_FOR_VETO}
    assert skip_reason(measured["omlx"]) == RouteReason.SKIPPED_MEASURED_FAILURE


def test_skipped_attempts_never_count_as_evidence():
    row = _row(
        "omlx",
        meta={
            "route_attempts": [
                {"provider": "apple_fm", "outcome": "skipped", "reason": "skipped_context"},
                {"provider": "omlx", "outcome": "ok", "reason": "escalated_context"},
            ]
        },
    )
    measured = fold_measurements([row])
    # A tier that was never asked to do anything has no record at all.
    assert "apple_fm" not in measured


def test_legacy_rows_without_route_attempts_still_measure():
    rows = [_row("apple_fm"), _row("apple_fm", "invalid", "sdk_error")]
    measured = fold_measurements(rows)
    assert measured["apple_fm"].attempts == 2
    assert measured["apple_fm"].ok == 1
    assert measured["apple_fm"].failures == {"sdk_error": 1}


def test_latency_percentiles_cover_failed_escalations_too():
    measured = fold_measurements([_routed_row_where_apple_failed()])
    # apple's 30s timeout is real latency evidence even though it never answered.
    assert measured["apple_fm"].p50_latency_ms == 30_000
    assert measured["omlx"].p50_latency_ms == 1000  # the row's own latency


# --- the recovery path ------------------------------------------------------ #


def test_cutoff_is_the_measurement_window():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    assert measurement_cutoff(now) == now - timedelta(days=MEASUREMENT_WINDOW_DAYS)


def test_veto_lifts_once_the_failure_record_ages_out():
    """The lockout, end to end at the policy seam.

    Day 0: five straight failures -> vetoed. The vetoed tier logs nothing new,
    so WITHOUT a window this record is frozen forever. WITH the window, the
    fetch stops returning those rows and the fold hands policy no measurement —
    which must read as 'no evidence', not as 'still broken'.
    """
    failing = [
        _row("apple_fm", "invalid", "sdk_error") for _ in range(MIN_SAMPLE_FOR_VETO)
    ]
    vetoed = fold_measurements(failing)["apple_fm"]
    assert skip_reason(vetoed) == RouteReason.SKIPPED_MEASURED_FAILURE

    # 15 days later the windowed fetch returns nothing for this tier.
    aged_out = fold_measurements([]).get("apple_fm")
    assert aged_out is None
    assert skip_reason(aged_out) is None  # the tier earns its probe back
