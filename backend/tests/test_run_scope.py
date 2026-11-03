"""`scrape_runs.scope`: a subset run must not claim the whole roster is fresh.

Freshness is computed from the newest run whose status counts as a refresh. That
is safe only for a run that covers every company: a targeted retry over 3 of 20
sources can legitimately return `ok`, and if that advanced `last_success_at` the 17 it never contacted would be reported fresh and
the watchdog catch-up meant to reach them would stop firing.

The regression requests the real status endpoint against seeded Postgres rows.
A copied SQL expression cannot protect the production filter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.config import get_settings
from tracker.db.models import ScrapeRun
from tracker.health import RunScope
from tracker.workflows.pipeline import resolve_run_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("full_status", ["ok", "partial"])
@pytest.mark.parametrize("targeted_status", ["ok", "partial"])
async def test_newer_targeted_run_cannot_refresh_the_full_roster(
    db_session, api_client, full_status, targeted_status
):
    now = datetime.now(UTC)
    full_finished = now - timedelta(hours=get_settings().freshness_max_hours + 2)
    db_session.add(ScrapeRun(
        scope=RunScope.FULL, status=full_status,
        started_at=full_finished - timedelta(minutes=1), finished_at=full_finished,
    ))
    await db_session.flush()
    db_session.add(ScrapeRun(
        scope=RunScope.TARGETED, status=targeted_status,
        started_at=now - timedelta(minutes=2), finished_at=now - timedelta(minutes=1),
    ))
    await db_session.commit()

    response = await api_client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["last_success_at"]) == full_finished
    assert body["stale"] is True


@pytest.mark.asyncio
async def test_targeted_run_alone_cannot_claim_a_successful_full_refresh(db_session, api_client):
    now = datetime.now(UTC)
    db_session.add(ScrapeRun(
        scope=RunScope.TARGETED, status="ok",
        started_at=now - timedelta(minutes=2), finished_at=now - timedelta(minutes=1),
    ))
    await db_session.commit()

    response = await api_client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["last_success_at"] is None
    assert response.json()["stale"] is True


def test_the_column_default_keeps_every_existing_run_full():
    """Pre-existing rows all covered the roster; the default must say so, or the
    migration would retroactively make the whole history non-refreshing."""
    column = ScrapeRun.__table__.c.scope
    assert column.default.arg == RunScope.FULL
    assert column.server_default.arg == "full"
    assert column.nullable is False


def test_the_freshness_lookup_is_indexed():
    """It runs on every `/api/status` poll, which the dashboard badge drives."""
    index_columns = {
        tuple(c.name for c in index.columns) for index in ScrapeRun.__table__.indexes
    }
    assert ("scope", "status") in index_columns


# --- scope is derived from coverage, not from the caller -------------------- #
# A `--company` run while testing a connector touches 1-2 companies. Recorded
# `full`, it would advance `last_success_at`, report the whole roster fresh and
# switch off the catch-up for the companies never contacted. So the scope is
# what the run covered, never what the caller says.


def test_a_subset_run_is_targeted_however_it_was_invoked():
    """The regression. `--company deepmind` on a 12-company roster asserts
    nothing about the other eleven, whatever the operator intended."""
    assert resolve_run_scope(RunScope.FULL, roster=12, targeted=1) is RunScope.TARGETED
    assert resolve_run_scope(RunScope.FULL, roster=12, targeted=11) is RunScope.TARGETED


def test_a_run_covering_the_whole_roster_stays_full():
    assert resolve_run_scope(RunScope.FULL, roster=12, targeted=12) is RunScope.FULL


def test_targeted_is_never_upgraded_to_full():
    """A retry that happens to cover everything is still a retry: it ran because
    those sources failed, not as a fresh statement about the roster."""
    assert resolve_run_scope(RunScope.TARGETED, roster=12, targeted=12) is RunScope.TARGETED


def test_an_empty_roster_is_not_silently_targeted():
    """Nothing enabled is a degenerate config, not a subset — and 0 < 0 is false,
    so the rule must not quietly reclassify it."""
    assert resolve_run_scope(RunScope.FULL, roster=0, targeted=0) is RunScope.FULL


def test_run_pipeline_does_not_shadow_the_role_scope_filter():
    """`run_pipeline` has a local `scope` holding the *ScopeFilter*
    (roles/bands/locations). A run-scope parameter also named `scope` would be
    silently overwritten by it, so `run.scope = scope` would write a ScopeFilter
    into a VARCHAR column; Postgres rejects the UPDATE and the run dies at start.

    Nothing types what reaches `run.scope`, so every other test would pass.
    Pinning the parameter name is the cheap, honest guard.
    """
    import inspect

    from tracker.workflows.pipeline import run_pipeline

    params = inspect.signature(run_pipeline).parameters
    assert "run_scope" in params, "run-scope parameter must not be named `scope`"
    assert "scope" not in params


def test_resolve_run_scope_only_accepts_a_run_scope():
    """The value that reaches the column must be the enum, not whatever the
    caller happened to pass — a str-enum makes a wrong type silently storable."""
    out = resolve_run_scope(RunScope.FULL, roster=3, targeted=3)
    assert isinstance(out, RunScope)
    out = resolve_run_scope(RunScope.FULL, roster=3, targeted=1)
    assert isinstance(out, RunScope)
