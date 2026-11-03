"""Background reads wait for a full wake; the directory scan for mains power.

macOS wakes a Mac that is shut and on battery many times for seconds of
maintenance. A run started in such a wake stretches across hours of sleep, and
a read that crosses a sleep cannot close a posting. The `pmset` answers are
in `tests/power_answers.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.power_answers import DARK_WAKE, DESKTOP, FULL_WAKE, ON_BATTERY, ON_MAINS, machine
from tracker.platform import power
from tracker.platform.power import (
    WAITING_FOR_FULL_WAKE,
    WAITING_FOR_MAINS,
    Power,
    dark_wake_in,
    on_battery_in,
    read_power,
)
from tracker.workflows import scheduler
from tracker.workflows.collection_types import ScanMode

#: The real probe, before the suite's guard replaces it (`conftest`).
_REAL_PMSET = power._pmset


def test_a_maintenance_wake_is_the_cpu_without_graphics():
    assert dark_wake_in(DARK_WAKE)
    assert not dark_wake_in(FULL_WAKE)


def test_only_mains_power_is_mains():
    assert on_battery_in(ON_BATTERY)
    assert on_battery_in("Now drawing from 'UPS Power'\n")
    assert not on_battery_in(ON_MAINS)
    assert not on_battery_in(DESKTOP)


@pytest.mark.parametrize("unreadable", [None, "", "pmset: unknown option\n", "Current Power State: 4\n"])
def test_an_answer_it_cannot_read_never_stops_collection(unreadable):
    assert not dark_wake_in(unreadable)
    assert not on_battery_in(unreadable)


def test_a_machine_without_pmset_counts_as_awake_on_mains(monkeypatch):
    monkeypatch.setattr(power.shutil, "which", lambda _name: None)
    assert _REAL_PMSET("-g", "batt") is None
    monkeypatch.setattr(power, "_pmset", _REAL_PMSET)
    assert read_power() == Power(dark_wake=False, on_battery=False)


def test_battery_holds_only_the_work_that_asks_for_mains():
    shut = Power(dark_wake=True, on_battery=True)
    unplugged = Power(dark_wake=False, on_battery=True)
    assert shut.wait_reason() == WAITING_FOR_FULL_WAKE
    assert shut.wait_reason(mains=True) == WAITING_FOR_FULL_WAKE
    assert unplugged.wait_reason() is None, "the user's own companies are read on battery"
    assert unplugged.wait_reason(mains=True) == WAITING_FOR_MAINS
    assert Power(dark_wake=False, on_battery=False).wait_reason(mains=True) is None


def _one_due(monkeypatch) -> list[str]:
    """One company due; returns the companies the tick handed to a run."""
    item = scheduler.DueWork(1, "acme", "greenhouse", ScanMode.RECONCILE, datetime.now(UTC))
    started: list[str] = []

    async def due(_now, **_):
        return scheduler.TickPlan([item])

    async def mark_started(work, _now):
        started.extend(w.company_slug for w in work)

    async def pipeline(**kw):
        return {"status": "ok", "companies": kw["companies"]}

    async def recorded(*_args, **_kw):
        return None

    async def nothing_left_open(_now):
        return None

    monkeypatch.setattr(scheduler, "close_runs_left_open", nothing_left_open)
    monkeypatch.setattr(scheduler, "plan_tick", due)
    monkeypatch.setattr(scheduler, "_mark_started", mark_started)
    monkeypatch.setattr(scheduler, "run_pipeline", pipeline)
    monkeypatch.setattr(scheduler, "_record_result", recorded)
    return started


@pytest.mark.asyncio
async def test_a_tick_in_a_maintenance_wake_starts_no_run(monkeypatch):
    started = _one_due(monkeypatch)
    machine(monkeypatch, systemstate=DARK_WAKE)

    result = await scheduler.run_once()

    assert (result["ran"], result["reason"]) == (False, WAITING_FOR_FULL_WAKE)
    assert [w["company"] for w in result["work"]] == ["acme"], "still says what is due"
    assert started == []


@pytest.mark.asyncio
async def test_a_tick_on_battery_reads_the_users_companies(monkeypatch):
    started = _one_due(monkeypatch)
    machine(monkeypatch, batt=ON_BATTERY)

    result = await scheduler.run_once()

    assert result["ran"] and started == ["acme"]
