"""Diagnostics payload attached to problem notifications.

The notification center expands this block, so it is a UI contract: it must carry
*where* a run hurt (per-source counters), *what* the adapter saw (drift message plus
its context - status codes, req ids), and *what broke* (source errors).
A healthy search with a refused detail request must retain its diagnostics.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tracker.db.models import ScrapeRun
from tracker.notifications import (
    classify_sync_result,
    run_diagnostics,
)

_APPLE_DRIFT = {
    "source": "apple:apple",
    "message": "detail access blocked after CSRF refresh; hydration disabled for run",
    "status": 401,
    "req": "200672287-0836",
}


def _run(**overrides) -> ScrapeRun:
    defaults = dict(
        id=20,
        status="ok",
        started_at=datetime(2026, 7, 14, 14, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 14, 14, 8, tzinfo=UTC),
        jobs_seen=749,
        jobs_new=10,
        jobs_closed=5,
        per_source={
            "apple": {"scanned": 2442, "kept": 389, "new": 4, "closed": 1, "errors": [], "drift": [_APPLE_DRIFT], "duration_seconds": 244.0},
            "google": {"scanned": 553, "kept": 191, "new": 6, "closed": 4, "errors": [], "drift": [], "duration_seconds": 61.2},
        },
        drift_alerts=[_APPLE_DRIFT],
    )
    defaults.update(overrides)
    return ScrapeRun(**defaults)


def test_drift_context_is_preserved_not_flattened_away():
    diag = run_diagnostics(_run())

    assert len(diag["drift"]) == 1
    row = diag["drift"][0]
    assert row["source"] == "apple:apple"
    assert "hydration disabled" in row["message"]
    # The status code and req id are the whole point - they are what makes the
    # alert debuggable rather than just alarming.
    assert row["context"] == {"status": 401, "req": "200672287-0836"}


def test_per_source_rows_sort_problems_first():
    run = _run(
        per_source={
            "anthropic": {"scanned": 408, "kept": 63, "errors": [], "drift": []},
            "apple": {"scanned": 2442, "kept": 389, "errors": [], "drift": [_APPLE_DRIFT]},
            "google": {"scanned": 553, "kept": 191, "errors": ["HTTPError: 503"], "drift": []},
        }
    )
    diag = run_diagnostics(run)

    assert [s["source"] for s in diag["sources"]] == ["google", "apple", "anthropic"]
    assert diag["sources"][0]["errors"] == ["HTTPError: 503"]
    assert diag["sources"][1]["drift_count"] == 1
    assert diag["totals"]["sources_ok"] == 1
    assert diag["totals"]["sources_total"] == 3


def test_sync_warning_names_the_failing_source_instead_of_counting_alerts():
    notif = classify_sync_result(_run())

    assert notif.category == "sync_warning"
    # "Affected source: 1 drift alerts" tells the user nothing about which
    # source to look at.
    assert "1 drift alerts" not in (notif.body or "")
    assert "Apple" in (notif.body or "")
    assert notif.meta["diagnostics"]["drift"][0]["context"]["status"] == 401


def test_drift_diagnostics_ride_on_the_sync_notification():
    """The diagnostics travel on the sync notification itself, not in a second
    row written from the same run."""
    notif = classify_sync_result(_run())

    assert notif is not None
    assert notif.meta["diagnostics"]["run_id"] == 20
    drift = notif.meta["diagnostics"]["drift"][0]
    assert "hydration disabled" in drift["message"]
    assert drift["source"] == "apple:apple"


def test_healthy_run_produces_nothing_at_all():
    clean = _run(per_source={"google": {"scanned": 10, "kept": 2, "errors": [], "drift": []}}, drift_alerts=[])
    assert classify_sync_result(clean) is None


def test_source_errors_surface_as_flat_rows():
    run = _run(
        status="error",
        per_source={"google": {"scanned": 0, "kept": 0, "errors": ["HTTPError: 503", "timeout"], "drift": []}},
        drift_alerts=[],
    )
    diag = run_diagnostics(run)

    assert diag["errors"] == [
        {"source": "google", "error": "HTTPError: 503"},
        {"source": "google", "error": "timeout"},
    ]
