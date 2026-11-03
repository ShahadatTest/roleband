"""Freshness math + catch-up decision — the guards the watchdog relies on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracker.connectors.recipes.outcome import SourceOutcome, run_status_for
from tracker.health import REFRESHED_STATUSES, RunScope, freshness, should_catch_up

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def test_no_prior_success_is_stale():
    age, stale = freshness(None, NOW, 26)
    assert age is None
    assert stale is True


def test_recent_success_is_fresh():
    age, stale = freshness(NOW - timedelta(hours=2), NOW, 26)
    assert 1.99 < age < 2.01
    assert stale is False


def test_old_success_is_stale():
    age, stale = freshness(NOW - timedelta(hours=30), NOW, 26)
    assert age > 26
    assert stale is True


def test_boundary_is_not_stale_at_threshold():
    _, stale = freshness(NOW - timedelta(hours=26), NOW, 26)
    assert stale is False  # strictly greater-than is stale


def test_catch_up_when_stale_and_idle():
    assert should_catch_up({"stale": True, "last_run_status": "ok", "stuck_running": 0}) is True


def test_no_catch_up_when_fresh():
    assert should_catch_up({"stale": False, "last_run_status": "ok", "stuck_running": 0}) is False


def test_no_catch_up_while_running():
    assert should_catch_up({"stale": True, "last_run_status": "running", "stuck_running": 0}) is False


def test_no_catch_up_when_stuck_runs_present():
    assert should_catch_up({"stale": True, "last_run_status": "ok", "stuck_running": 2}) is False


# --------------------------------------------------------------------------- #
# One failing source among healthy ones must not mark every
# run `error` and trigger a catch-up run every hour. These two tests walk the
# whole chain that would sustain such a loop (per-source outcomes -> run status
# -> refresh eligibility -> freshness -> catch-up decision) and are the
# assertions that prove it cannot recur.
# --------------------------------------------------------------------------- #


def _catch_up_after(status: str, *, last_refresh_age_hours: float) -> bool:
    """Replay `/api/status`'s decision for a tree whose last run had `status`."""
    # `/api/status` derives `last_success_at` from the most recent run whose
    # status is in REFRESHED_STATUSES; a status outside it leaves it None.
    last_success_at = (
        NOW - timedelta(hours=last_refresh_age_hours)
        if status in REFRESHED_STATUSES
        else None
    )
    _, stale = freshness(last_success_at, NOW, 26)
    return should_catch_up(
        {"stale": stale, "last_run_status": status, "stuck_running": 0}
    )


def test_a_mostly_good_run_stops_the_hourly_catch_up_loop():
    # Eight healthy sources, one throttled into failure.
    status = run_status_for([SourceOutcome.OK] * 8 + [SourceOutcome.FAILED])

    assert status == "partial"
    assert status in REFRESHED_STATUSES
    # Were this run `error`, `last_success_at` would never advance and the
    # watchdog would re-fire an hour later, forever.
    assert _catch_up_after(status, last_refresh_age_hours=0.5) is False


def test_a_total_failure_still_keeps_retrying():
    """The deliberate non-goal: watchdog failure memory is out of scope.

    A run where *every* source failed stays `error`, stays stale, and keeps
    being retried — network down or DB unreachable *should* keep retrying, and
    per-source pressure is contained by the breaker instead.
    """
    status = run_status_for([SourceOutcome.FAILED] * 9)

    assert status == "error"
    assert status not in REFRESHED_STATUSES
    assert _catch_up_after(status, last_refresh_age_hours=0.5) is True


# --- run scope: what a run covered, vs how it went -------------------------- #
# Freshness is a claim about the whole roster. A targeted retry re-attempts only
# the sources a previous run failed on, so it can legitimately be `ok` while most
# companies were never contacted — and counting that as a refresh would mark them
# fresh and switch off the very catch-up meant to reach them.


def test_scope_is_a_closed_vocabulary():
    assert {s.value for s in RunScope} == {"full", "targeted"}


def test_scope_is_orthogonal_to_status():
    """A targeted run can be `ok`; that is exactly why the two are separate.

    Were success alone enough to advance freshness, the retry mechanism would
    silence staleness for every company it deliberately skipped.
    """
    status = run_status_for([SourceOutcome.OK] * 3)  # the 3 sources it retried
    assert status == "ok"
    assert status in REFRESHED_STATUSES  # the status says nothing about coverage
    assert RunScope.TARGETED != RunScope.FULL  # the scope is what withholds it


def test_str_enum_compares_to_the_stored_column_value():
    """The column is a plain String(16), so the enum must equal the raw text or
    the freshness filter would silently match nothing."""
    assert RunScope.FULL == "full"
    assert RunScope.TARGETED == "targeted"
