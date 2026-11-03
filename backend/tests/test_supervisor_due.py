"""When a job starts, and why it waits.

Every rule here has its negative control: the moment just before a start, the
blocker that must hold a job back, the job that must not inherit another's gate.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tracker.supervisor import due
from tracker.supervisor.due import Decision, Facts, Gate, World
from tracker.supervisor.registry import JOBS, Daily, Every, JobSpec, OnChange, Power, job

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
CLEAR = World(dark_wake=False, on_battery=False, gate=Gate.PASSED, schema_ready=True, zone=PARIS)


def _decide(name: str, world: World = CLEAR, **facts) -> Decision:
    return due.decide(job(name), Facts(now=facts.pop("now", NOW), **facts), world)


# --- every N seconds, launchd parity -------------------------------------------


def test_a_periodic_job_that_never_ran_starts_at_once():
    assert _decide("scan").start


def test_a_periodic_job_starts_one_period_after_its_last_start_and_not_a_second_before():
    started = NOW - timedelta(minutes=10)
    ended = started + timedelta(minutes=2)
    assert _decide("scan", last_started_at=started, last_ended_at=ended).start
    early = _decide("scan", now=NOW - timedelta(seconds=1), last_started_at=started, last_ended_at=ended)
    assert not early.start
    assert early.state == due.IDLE
    assert early.next_at == NOW


def test_starts_that_fall_inside_a_long_run_are_missed_not_queued():
    """A sweep that ran 25 minutes on a 10 minute period next starts at the 30
    minute boundary, as launchd's StartInterval would, not the moment it ends."""
    started = NOW - timedelta(minutes=25)
    ended = NOW
    decision = _decide("directory", last_started_at=started, last_ended_at=ended)
    assert not decision.start
    assert decision.next_at == started + timedelta(minutes=30)


def test_a_live_run_is_never_started_again_whatever_is_due_or_queued():
    decision = _decide("scan", live=True, queued=3, last_started_at=NOW - timedelta(hours=5))
    assert not decision.start
    assert decision.state == due.RUNNING


def test_after_a_long_sleep_an_overdue_periodic_job_starts_once_at_the_first_look():
    started = NOW - timedelta(hours=9)
    decision = _decide("scan", last_started_at=started, last_ended_at=started + timedelta(minutes=3))
    assert decision.start
    assert decision.trigger == "schedule"


# --- daily, with catch-up -------------------------------------------------------


def _backup_at(local: datetime, last: datetime | None) -> Decision:
    return due.decide(job("backup"), Facts(now=local.astimezone(UTC), last_started_at=last), CLEAR)


def test_the_daily_backup_waits_for_its_slot():
    yesterday = datetime(2026, 10, 18, 6, 30, tzinfo=PARIS)
    decision = _backup_at(datetime(2026, 10, 19, 6, 29, tzinfo=PARIS), yesterday)
    assert not decision.start
    assert decision.next_at == datetime(2026, 10, 19, 6, 30, tzinfo=PARIS)


def test_the_daily_backup_runs_at_its_slot_in_local_time():
    yesterday = datetime(2026, 10, 18, 6, 30, tzinfo=PARIS)
    assert _backup_at(datetime(2026, 10, 19, 6, 30, tzinfo=PARIS), yesterday).start


def test_a_slot_missed_while_asleep_runs_once_at_the_first_wake_and_not_again():
    yesterday = datetime(2026, 10, 18, 6, 31, tzinfo=PARIS)
    woke = datetime(2026, 10, 19, 9, 40, tzinfo=PARIS)
    assert _backup_at(woke, yesterday).start, "the 06:30 slot slept through runs at the first look"
    caught_up = woke + timedelta(minutes=1)
    later = _backup_at(woke + timedelta(hours=2), caught_up)
    assert not later.start, "one catch-up per missed slot"
    assert later.next_at == datetime(2026, 10, 20, 6, 30, tzinfo=PARIS)


def test_without_catch_up_a_slot_missed_by_more_than_the_grace_is_skipped():
    strict = replace(job("backup"), schedule=Daily(time(6, 30), catch_up=False))
    yesterday = datetime(2026, 10, 18, 6, 30, tzinfo=PARIS)
    late = datetime(2026, 10, 19, 9, 40, tzinfo=PARIS).astimezone(UTC)
    decision = due.decide(strict, Facts(now=late, last_started_at=yesterday), CLEAR)
    assert not decision.start
    within = datetime(2026, 10, 19, 7, 0, tzinfo=PARIS).astimezone(UTC)
    assert due.decide(strict, Facts(now=within, last_started_at=yesterday), CLEAR).start


def test_the_daily_slot_follows_local_time_across_a_clock_change():
    """Paris leaves summer time on the last Sunday of October: the slot stays
    06:30 on the wall, which is an hour later in UTC."""
    before = datetime(2026, 10, 24, 6, 30, tzinfo=PARIS)
    decision = _backup_at(datetime(2026, 10, 24, 12, 0, tzinfo=PARIS), before)
    assert decision.next_at.astimezone(PARIS).time() == time(6, 30)
    after = _backup_at(datetime(2026, 10, 25, 12, 0, tzinfo=PARIS), before)
    assert after.start
    assert after.next_at.astimezone(UTC).hour == 5, "06:30 in winter time is 05:30 UTC"


# --- requests ---------------------------------------------------------------------


def test_a_job_that_runs_only_when_asked_waits_for_a_request():
    assert not _decide("reembed", last_started_at=NOW - timedelta(days=30)).start
    asked = _decide("reembed", queued=1)
    assert asked.start
    assert asked.trigger == "request"


def test_a_request_starts_a_periodic_job_before_its_period():
    started = NOW - timedelta(minutes=1)
    decision = _decide("scan", last_started_at=started, last_ended_at=started, queued=1)
    assert decision.start
    assert decision.trigger == "request"


# --- blockers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate", "reason"),
    [(Gate.RUNNING, due.PREFLIGHT_RUNNING), (Gate.FAILED, due.PREFLIGHT_FAILED), (Gate.UNKNOWN, due.PREFLIGHT_RUNNING)],
)
def test_a_gated_job_waits_for_a_passing_preflight_and_says_why(gate, reason):
    decision = _decide("scan", replace(CLEAR, gate=gate), queued=1)
    assert not decision.start
    assert (decision.state, decision.reason) == (due.WAITING, reason)


@pytest.mark.parametrize("name", ["backup", "preflight", "dashboard_build", "usage_send", "prices"])
def test_a_failing_preflight_holds_no_ungated_job(name):
    """No job is held by another's gate: backups and checks run while collection waits."""
    failed = replace(CLEAR, gate=Gate.FAILED)
    assert _decide(name, failed, queued=1).start


def test_the_jobs_gated_by_preflight_are_the_ones_that_collect_or_derive():
    gated = {entry.name for entry in JOBS if entry.gated}
    assert gated == {"scan", "directory", "plugin_run", "role_discovery", "reembed", "reestimate"}


def test_the_jobs_a_rehearsal_dry_runs_are_the_ones_that_reach_a_third_party():
    network = {entry.name for entry in JOBS if entry.network}
    assert network == {"scan", "directory", "usage_send", "plugin_run", "role_discovery", "reembed", "prices"}


def test_code_ahead_of_the_schema_holds_every_job_that_touches_the_database():
    pending = replace(CLEAR, schema_ready=False)
    assert _decide("backup", pending, queued=1).reason == due.SCHEMA_PENDING
    assert _decide("scan", pending, queued=1).reason == due.SCHEMA_PENDING
    assert _decide("preflight", pending, queued=1).start, "the suite builds its own databases"
    assert _decide("dashboard_build", pending, queued=1).start


def test_dependencies_not_installed_hold_every_job_that_touches_the_database():
    pending = replace(CLEAR, dependencies_ready=False)
    assert _decide("scan", pending, queued=1).reason == due.DEPENDENCIES_PENDING
    assert _decide("usage_send", pending, queued=1).reason == due.DEPENDENCIES_PENDING
    assert _decide("preflight", pending, queued=1).start
    assert _decide("dashboard_build", pending, queued=1).start, "the build is how a new lock gets checked"


def test_a_maintenance_wake_holds_awake_jobs_and_spares_the_rest():
    dark = replace(CLEAR, dark_wake=True)
    assert _decide("scan", dark, queued=1).reason == due.WAITING_FOR_WAKE
    assert _decide("backup", dark, queued=1).start


def test_battery_holds_the_directory_sweep_but_not_the_scan():
    battery = replace(CLEAR, on_battery=True)
    assert _decide("directory", battery, queued=1).reason == due.WAITING_FOR_MAINS
    assert _decide("scan", battery, queued=1).start


def test_on_battery_a_scheduled_plugin_run_waits_and_one_the_user_asked_for_does_not():
    battery = replace(CLEAR, on_battery=True)
    scheduled = _decide("plugin_run", battery, queued=1, requested_for="schedule")
    assert scheduled.reason == due.WAITING_FOR_MAINS
    assert _decide("plugin_run", battery, queued=1, requested_for="manual").start
    assert _decide("plugin_run", battery, queued=1, requested_for="sync").start


def test_a_blocked_job_still_reports_when_its_schedule_falls_due():
    started = NOW - timedelta(minutes=4)
    decision = _decide("scan", replace(CLEAR, gate=Gate.FAILED), queued=1, last_started_at=started)
    assert decision.next_at == started + timedelta(minutes=10)


# --- on change -------------------------------------------------------------------------


def test_a_change_starts_its_job_only_after_it_settles():
    settle = job("preflight").schedule
    assert isinstance(settle, OnChange)
    changed = NOW - timedelta(seconds=settle.settle_seconds - 1)
    assert not _decide("preflight", changed_since=changed).start
    settled = _decide("preflight", changed_since=NOW - timedelta(seconds=settle.settle_seconds))
    assert settled.start
    assert settled.trigger == "change"
    assert not _decide("preflight", changed_since=None).start, "nothing changed, nothing to check"


# --- the registry itself -----------------------------------------------------------------


def test_job_names_are_unique_and_every_command_is_concrete():
    names = [entry.name for entry in JOBS]
    assert len(names) == len(set(names))
    for entry in JOBS:
        assert entry.command, entry.name
        assert all(part for part in entry.command), entry.name


def test_only_the_scan_runs_without_a_hard_timeout():
    """The scan's liveness is its heartbeat; every other job has a bound."""
    unbounded = {entry.name for entry in JOBS if entry.timeout_seconds is None}
    assert unbounded == {"scan"}


def test_a_job_with_no_power_policy_ignores_power_entirely():
    entry = JobSpec("probe", ("true",), OnChange(), power=Power.NONE, uses_database=False)
    world = replace(CLEAR, dark_wake=True, on_battery=True)
    assert due.decide(entry, Facts(now=NOW, queued=1), world).start


def test_the_schedule_screen_states_the_scan_job_s_real_cadence():
    from tracker.workflows.schedule_status import SCHEDULER_TICK_SECONDS

    assert job("scan").schedule == Every(SCHEDULER_TICK_SECONDS)
