"""When plugin jobs start, and how their processes are kept honest.

Contracts: a weekly job is due when it has never gone through or the pass its
last clean or partial run ended began a week ago; a failed attempt
waits `RETRY_AFTER`; nothing starts while
the plugin is running, disabled, unapproved or removed; re-enabling a plugin
with a clean snapshot fetches nothing; a `running` row whose process is gone
is closed `error`; disable signals only a live runner; and the scheduler never
starts plugin work in a maintenance wake, waits for mains on battery, while
Sync goes on battery. No test spawns a process: the spawner is a fake.
"""

from __future__ import annotations

import signal
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tracker.db.models import PluginInstall, PluginRun
from tracker.platform.paths import DATA_DIR
from tracker.platform.power import Power
from tracker.plugins import runtime
from tracker.plugins.registry import InstallRecord
from tracker.plugins.runtime import (
    RETRY_AFTER,
    WEEKLY,
    RunRecord,
    due_jobs,
    reconcile_dead_runs,
    start_due,
    stop_runs,
)
from tracker.plugins.schedule import CONTINUE_AFTER, reading_left
from tracker.supervisor import registry
from tracker.supervisor import runner as supervisor_runner

#: The module under test starts and signals processes: every test refuses to.
pytestmark = pytest.mark.usefixtures("no_escape")

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
JOBS = [{"name": "refresh", "schedule": "weekly", "budget_seconds": 60}, {"name": "import", "schedule": "manual",
                                                                          "budget_seconds": 60}]


def _record(pid="tpl", *, enabled=True, approved=True, removed=None, schedule=None, paused=False):
    return InstallRecord(pid, enabled, "fp1", "fp1" if approved else None, removed,
                         {"provides": [{"slot": "pay.levels"}], "jobs": JOBS}, schedule=schedule, paused=paused)


def _run(outcome, ago, job="refresh", pid="tpl", *, continues=False, took=timedelta(0)):
    return RunRecord(pid, job, outcome, NOW - ago, NOW - ago + took, continues)


# --------------------------------------------------------------------------- #
# Due, pure
# --------------------------------------------------------------------------- #


def test_a_plugin_that_never_ended_clean_is_due_now_and_only_its_weekly_job():
    assert [(d.plugin_id, d.job, d.reason) for d in due_jobs([_record()], [], NOW)] == [
        ("tpl", "refresh", "never_clean")]


def test_a_clean_run_inside_a_week_is_not_due_and_a_week_old_one_is():
    assert due_jobs([_record()], [_run("clean", WEEKLY - timedelta(minutes=1))], NOW) == []
    assert [d.reason for d in due_jobs([_record()], [_run("clean", WEEKLY)], NOW)] == ["weekly"]


def test_a_failed_attempt_waits_before_it_is_tried_again():
    assert due_jobs([_record()], [_run("error", RETRY_AFTER - timedelta(minutes=1))], NOW) == []
    assert [d.reason for d in due_jobs([_record()], [_run("error", RETRY_AFTER)], NOW)] == ["never_clean"]
    # A fresh clean snapshot plus a later failure: the snapshot still stands.
    runs = [_run("clean", timedelta(days=2)), _run("error", RETRY_AFTER + timedelta(hours=1))]
    assert due_jobs([_record()], runs, NOW) == []


def test_a_pass_in_progress_continues_soon_after_its_last_run_not_a_week_later():
    """A clean run that said `more` stopped at a unit boundary with its pass
    unfinished: the next run continues it `CONTINUE_AFTER` that run ENDED (a
    four-hour run that started long ago is not due the moment it ends)."""
    from tracker.plugins.runtime import CONTINUE_AFTER

    chunk = _run("clean", timedelta(hours=5), continues=True, took=timedelta(hours=4, minutes=40))
    assert due_jobs([_record()], [chunk], NOW) == []  # ended 20 minutes ago
    later = _run("clean", timedelta(hours=5), continues=True, took=timedelta(hours=5) - CONTINUE_AFTER)
    assert [d.reason for d in due_jobs([_record()], [later], NOW)] == ["continues"]


def test_a_failed_chunk_of_a_pass_is_retried_as_the_pass_not_held_for_the_schedule():
    runs = [_run("clean", timedelta(days=20)), _run("clean", timedelta(hours=10), continues=True),
            _run("error", RETRY_AFTER)]
    assert [d.reason for d in due_jobs([_record()], runs, NOW)] == ["continues"]


def test_a_partial_run_ends_a_pass_and_the_plugin_waits_for_its_schedule():
    """One failed request among thousands makes a run `partial`; it read what
    it set out to, so it ends the pass. Read as a failed attempt, it would be
    retried 6 hours after it started, forever, never weekly."""
    assert due_jobs([_record()], [_run("partial", RETRY_AFTER + timedelta(hours=1))], NOW) == []
    assert due_jobs([_record()], [_run("partial", WEEKLY - timedelta(minutes=1))], NOW) == []
    assert [d.reason for d in due_jobs([_record()], [_run("partial", WEEKLY)], NOW)] == ["weekly"]


def test_a_partial_chunk_that_said_more_continues_soon():
    from tracker.plugins.runtime import CONTINUE_AFTER

    chunk = _run("partial", timedelta(hours=5), continues=True, took=timedelta(hours=5) - CONTINUE_AFTER)
    assert [d.reason for d in due_jobs([_record()], [chunk], NOW)] == ["continues"]
    # A pass of clean and partial chunks counts from its first chunk.
    runs = [_run("clean", timedelta(days=7), continues=True), _run("partial", timedelta(days=6), continues=True),
            _run("partial", timedelta(days=5))]
    assert [d.reason for d in due_jobs([_record()], runs, NOW)] == ["weekly"]


def test_a_run_that_did_not_go_through_is_still_retried():
    """Only `clean` and `partial` go through a job; the rest wait `RETRY_AFTER`."""
    for outcome in ("error", "bounded", "stopped"):
        assert [d.reason for d in due_jobs([_record()], [_run(outcome, RETRY_AFTER)], NOW)] == ["never_clean"], outcome


def test_the_schedule_counts_from_the_start_of_the_last_whole_pass():
    """A weekly pass that took three runs over two days repeats a week after it
    began, not a week after its last chunk."""
    runs = [_run("clean", timedelta(days=7), continues=True), _run("clean", timedelta(days=6), continues=True),
            _run("clean", timedelta(days=5))]
    assert [d.reason for d in due_jobs([_record()], runs, NOW)] == ["weekly"]
    assert due_jobs([_record()], [_run("clean", timedelta(days=5))], NOW) == [], "a one-run pass: as before"


# --------------------------------------------------------------------------- #
# The user's schedule and pause
# --------------------------------------------------------------------------- #


def test_the_user_s_schedule_replaces_every_job_s_own():
    """Daily: due a day after the last clean run, the manual job too (the user
    chose it for the plugin); monthly: not due after a week."""
    daily = _record(schedule="daily")
    runs = [_run("clean", timedelta(days=1)), _run("clean", timedelta(days=1), job="import")]
    assert sorted((d.job, d.reason) for d in due_jobs([daily], runs, NOW)) == [
        ("import", "daily"), ("refresh", "daily")]
    assert due_jobs([daily], [_run("clean", timedelta(hours=23))], NOW) == [
        runtime.DueJob("tpl", "import", "never_clean")]
    monthly = _record(schedule="monthly")
    week_old = [_run("clean", WEEKLY), _run("clean", WEEKLY, job="import")]
    assert due_jobs([monthly], week_old, NOW) == []
    assert len(due_jobs([monthly], [_run("clean", timedelta(days=30)), _run("clean", timedelta(days=30),
                                                                             job="import")], NOW)) == 2


def test_manual_never_starts_itself_even_if_the_plugin_says_weekly():
    assert due_jobs([_record(schedule="manual")], [], NOW) == []


def test_an_unknown_stored_schedule_falls_back_to_the_manifest_s():
    assert [d.job for d in due_jobs([_record(schedule="hourly")], [], NOW)] == ["refresh"]


def test_a_paused_plugin_starts_nothing_on_its_own():
    assert due_jobs([_record(paused=True)], [], NOW) == []
    assert due_jobs([_record(paused=True, schedule="daily")], [_run("clean", WEEKLY)], NOW) == []


@pytest.mark.parametrize("record", [
    _record(enabled=False), _record(approved=False), _record(removed=NOW),
], ids=["disabled", "unapproved", "removed"])
def test_a_plugin_that_may_not_run_is_never_due(record):
    assert due_jobs([record], [], NOW) == []


def test_nothing_starts_while_the_plugin_is_running():
    assert due_jobs([_record()], [_run("running", timedelta(days=30))], NOW) == []


def test_re_enabling_a_plugin_with_a_clean_snapshot_fetches_nothing():
    """The rows answer again at once; enabling is not a refresh."""
    assert due_jobs([_record(enabled=True)], [_run("clean", timedelta(days=1))], NOW) == []


# --------------------------------------------------------------------------- #
# How far a pass has to go, pure
# --------------------------------------------------------------------------- #

REFRESH = {"name": "refresh", "schedule": "weekly", "budget_seconds": 14_400}


def _paced(outcome, ago, done, total, took, *, continues=False):
    return RunRecord("tpl", "refresh", outcome, NOW - ago, None if outcome == "running" else NOW - ago + took,
                     continues, done, total)


def test_a_pass_under_way_says_what_is_left_at_the_pace_each_run_moved_it():
    """`done` is the pass's position, so a run's own work is what it moved since
    the run before. Dividing the position by the time would say 40s, not 60s."""
    runs = [_paced("stopped", timedelta(hours=5), 10, 1_180, timedelta(minutes=10)),
            _paced("stopped", timedelta(hours=3), 20, 1_180, timedelta(minutes=10))]
    left = reading_left(REFRESH, runs)
    assert left is not None
    assert left.units == 1_160
    assert left.seconds_per_unit == pytest.approx(60.0)


def test_the_time_left_counts_the_wait_between_the_runs_a_budget_splits_it_into():
    runs = [_paced("stopped", timedelta(hours=3), 880, 1_180, timedelta(hours=14, minutes=40))]
    left = reading_left(REFRESH, runs)
    assert left is not None
    # 300 units at 60s = 18,000s of reading: two 4-hour runs, one wait between them.
    assert left.seconds == pytest.approx(18_000 + CONTINUE_AFTER.total_seconds())


def test_a_new_pass_starts_from_none_read_after_a_finished_one():
    runs = [_paced("clean", timedelta(days=8), 100, 100, timedelta(seconds=6_000)),
            _paced("stopped", timedelta(hours=1), 5, 100, timedelta(seconds=300))]
    left = reading_left(REFRESH, runs)
    assert left is not None
    assert left.units == 95
    assert left.seconds_per_unit == pytest.approx(60.0)


def test_a_running_update_s_position_counts_but_not_its_unfinished_time():
    runs = [_paced("clean", timedelta(hours=6), 30, 100, timedelta(minutes=30),
                   continues=True),
            _paced("running", timedelta(minutes=5), 40, 100, timedelta(0))]
    left = reading_left(REFRESH, runs)
    assert left is not None
    assert left.units == 60
    assert left.seconds_per_unit == pytest.approx(60.0)


@pytest.mark.parametrize("runs", [
    [],
    [_paced("clean", timedelta(days=1), 100, 100, timedelta(minutes=100))],
    [_paced("stopped", timedelta(hours=1), None, None, timedelta(minutes=10))],
    [RunRecord("tpl", "import", "stopped", NOW, NOW + timedelta(minutes=1), False, 1, 9)],
], ids=["never-ran", "pass-through", "never-counted", "another-job"])
def test_nothing_is_left_to_say_without_a_pass_under_way_that_counted_its_units(runs):
    assert reading_left(REFRESH, runs) is None


# --------------------------------------------------------------------------- #
# Processes, against the database
# --------------------------------------------------------------------------- #


async def _install(db, *, enabled=True) -> None:
    db.add(PluginInstall(
        plugin_id="tpl", name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": [{"slot": "pay.levels"}], "jobs": JOBS}, fingerprint="fp1",
        approved_fingerprint="fp1", enabled=enabled,
    ))
    await db.commit()


class _Spawned(list):
    def __call__(self, argv, log):
        self.append((list(argv), log))
        return object()


@pytest.mark.asyncio
async def test_start_due_spawns_the_runner_once_with_its_trigger(db_session):
    await _install(db_session)
    spawned = _Spawned()
    due = await start_due(db_session, trigger="schedule", now=NOW, spawner=spawned)
    assert [(d.plugin_id, d.job) for d in due] == [("tpl", "refresh")]
    (argv, log), = spawned
    assert argv[1:] == ["-m", "tracker.plugins.cli", "run", "tpl", "refresh", "--trigger", "schedule"]
    # The file the supervisor's plugin job writes, not a per-plugin one beside it.
    assert log == supervisor_runner.log_path(DATA_DIR, registry.job("plugin_run"))


@pytest.mark.asyncio
async def test_a_reestimate_logs_where_the_supervisors_reestimate_job_does(db_session):
    spawned = _Spawned()
    await runtime.spawn_reestimate(db_session, spawner=spawned)
    (argv, log), = spawned
    assert argv[1:] == list(registry.job("reestimate").command[1:]), "the supervisor's own command"
    assert log == supervisor_runner.log_path(DATA_DIR, registry.job("reestimate"))


@pytest.mark.asyncio
async def test_a_running_row_whose_process_is_gone_is_closed_error_and_unblocks_the_next(db_session):
    await _install(db_session)
    db_session.add_all([
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp1", outcome="running", pid=111),
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp1", outcome="running", pid=222),
    ])
    await db_session.commit()
    alive = {222: "python -m scripts.plugin run tpl refresh"}
    closed = await reconcile_dead_runs(db_session, command=lambda pid: alive.get(pid, ""))
    await db_session.commit()
    outcomes = dict((await db_session.execute(select(PluginRun.pid, PluginRun.outcome))).all())
    assert len(closed) == 1 and outcomes == {111: "error", 222: "running"}


@pytest.mark.asyncio
async def test_a_recycled_pid_is_not_a_runner(db_session):
    await _install(db_session)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="cli", fingerprint="fp1", outcome="running",
                             pid=333))
    await db_session.commit()
    await reconcile_dead_runs(db_session, command=lambda pid: "/usr/bin/vim notes.txt")
    await db_session.commit()
    assert (await db_session.execute(select(PluginRun.outcome))).scalar_one() == "error"


@pytest.mark.asyncio
async def test_disable_signals_only_a_live_runner(db_session):
    await _install(db_session)
    db_session.add_all([
        PluginRun(plugin_id="tpl", job="refresh", trigger="cli", fingerprint="fp1", outcome="running", pid=444),
        PluginRun(plugin_id="tpl", job="refresh", trigger="cli", fingerprint="fp1", outcome="running", pid=555),
    ])
    await db_session.commit()
    sent = []
    stopped = await stop_runs(
        db_session, "tpl",
        command=lambda pid: "scripts.plugin run tpl refresh" if pid == 444 else "bash",
        kill=lambda pid, sig: sent.append((pid, sig)),
    )
    assert stopped == [444] and sent == [(444, signal.SIGTERM)]
    # The dead one is closed there and then, not left `running`.
    outcomes = dict((await db_session.execute(select(PluginRun.pid, PluginRun.outcome))).all())
    assert outcomes == {444: "running", 555: "error"}


@pytest.mark.parametrize(
    ("line", "runner"),
    [
        ("/repo/backend/.venv/bin/python -m tracker.plugins.cli run tpl refresh --trigger schedule", True),
        # Typed by hand, or started before a landing moved the supervisor's command.
        ("/repo/backend/.venv/bin/python -m scripts.plugin run tpl refresh --trigger manual", True),
        ("/repo/backend/.venv/bin/python -m tracker.plugins.reestimate_cli --wait 600", False),
        ("/repo/backend/.venv/bin/python -m scripts.reestimate --wait 600", False),
        ("/usr/bin/vim notes.txt", False),
        ("", False),
    ],
    ids=["supervised host", "operator host", "re-estimate", "operator re-estimate", "recycled pid", "ps failed"],
)
def test_a_runner_is_recognised_by_either_spelling_of_its_command(line, runner):
    assert runtime.runner_alive(4242, command=lambda _pid: line) is runner
    assert runtime.runner_alive(None, command=lambda _pid: line) is False


@pytest.mark.asyncio
async def test_disable_stops_a_host_started_under_either_spelling(db_session):
    """A supervisor restart on landed code leaves its runs running, so a host
    started under either command is one disable must stop."""
    await _install(db_session)
    db_session.add_all([
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp1", outcome="running", pid=601),
        PluginRun(plugin_id="tpl", job="refresh", trigger="manual", fingerprint="fp1", outcome="running", pid=602),
    ])
    await db_session.commit()
    lines = {
        601: "python -m tracker.plugins.cli run tpl refresh --trigger schedule",
        602: "python -m scripts.plugin run tpl refresh --trigger manual",
    }
    sent: list[tuple[int, int]] = []
    stopped = await stop_runs(db_session, "tpl", command=lambda pid: lines.get(pid, ""),
                              kill=lambda pid, sig: sent.append((pid, sig)))
    assert sorted(stopped) == [601, 602]
    assert sorted(sent) == [(601, signal.SIGTERM), (602, signal.SIGTERM)]


@pytest.mark.asyncio
async def test_a_requested_run_is_the_registry_s_command_with_the_request_s_arguments(db_session):
    """The runtime builds the argv a run gets, the registry holds the command the
    supervisor starts: the request's tail must make one into the other."""
    from tracker.db.models import JobRequest

    await runtime.spawn_run(db_session, "tpl", "refresh", trigger="manual")
    await db_session.commit()
    request = (await db_session.execute(select(JobRequest))).scalar_one()
    started = supervisor_runner.command(registry.job("plugin_run"), request.args["argv"], python="/venv/python")
    assert started == ["/venv/python", "-m", "tracker.plugins.cli", "run", "tpl", "refresh", "--trigger", "manual"]
    built = runtime.spawn_run(db_session, "tpl", "refresh", trigger="manual", spawner=lambda argv, _log: argv)
    assert (await built)[1:] == started[1:]


def test_the_supervised_modules_are_the_ones_the_operator_commands_run(capsys):
    """`scripts.plugin` and `scripts.reestimate` stay the documented commands and
    run the same code the supervisor starts."""
    import runpy
    import sys

    from tracker.plugins import cli, reestimate_cli
    from tracker.supervisor import results

    assert registry.job("plugin_run").command[1:3] == ("-m", runtime.RUN_MODULE)
    assert registry.job("reestimate").command[1:3] == ("-m", runtime.REESTIMATE_MODULE)
    assert reestimate_cli.LOCKED == results.REESTIMATE_LOCKED, "the supervisor reads that exit as busy"
    for module, expected in (("scripts.plugin", ("run", "install", "approve")),
                             ("scripts.reestimate", ("--status", "--wait"))):
        argv = sys.argv
        sys.argv = [module, "--help"]
        try:
            with pytest.raises(SystemExit) as done:
                runpy.run_module(module, run_name="__main__")
        finally:
            sys.argv = argv
        assert done.value.code == 0
        shown = capsys.readouterr().out
        assert shown.startswith(f"usage: {module}")
        assert all(word in shown for word in expected), shown
    assert cli.main.__module__ == runtime.RUN_MODULE
    assert reestimate_cli.main.__module__ == runtime.REESTIMATE_MODULE


# --------------------------------------------------------------------------- #
# The gates, as the scheduler and Sync apply them
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(("power", "trigger", "starts"), [
    (Power(dark_wake=True, on_battery=False), "schedule", False),
    (Power(dark_wake=True, on_battery=False), "sync", False),
    (Power(dark_wake=False, on_battery=True), "schedule", False),
    (Power(dark_wake=False, on_battery=True), "sync", True),
    (Power(dark_wake=False, on_battery=False), "schedule", True),
], ids=["dark-wake-schedule", "dark-wake-sync", "battery-schedule", "battery-sync", "mains-schedule"])
async def test_plugin_work_obeys_the_wake_and_mains_gates(db_session, monkeypatch, power, trigger, starts):
    await _install(db_session)
    spawned = _Spawned()
    result = await runtime.plugins_when_due(db_session, trigger=trigger, power=lambda: power, spawner=spawned,
                                            now=NOW)
    assert bool(spawned) is starts
    if not starts:
        assert result["waiting"]


@pytest.mark.asyncio
async def test_with_nothing_due_the_machine_is_not_read(db_session):
    """No plugin installed: one query, no `pmset`, no spawn."""
    def never():
        raise AssertionError("power read with nothing due")

    spawned = _Spawned()
    result = await runtime.plugins_when_due(db_session, trigger="schedule", power=never, spawner=spawned, now=NOW)
    assert result == {"started": [], "waiting": None} and spawned == []


def test_the_scheduler_entrypoint_hands_the_tick_the_plugin_start():
    """`python -m tracker.scheduler` passes the plugin start as an after-lock
    step; `tracker.workflows.scheduler` itself never imports a spawner."""
    import ast
    from pathlib import Path

    import tracker.scheduler as entry
    from tracker.workflows import scheduler

    source = Path(scheduler.__file__).read_text()
    imported = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
    assert "tracker.plugins.runtime" not in imported
    main_block = Path(entry.__file__).read_text().split('if __name__ == "__main__":')[1]
    assert 'after_lock=[("plugins", start_due_plugins)]' in main_block


@pytest.mark.asyncio
async def test_the_manual_tick_starts_plugins_through_the_supervisor_step_and_logs_a_failure(monkeypatch):
    """One rule for when a scheduled plugin is due: the manual tick calls the
    supervisor's own step, so a change to its gating reaches both, and a
    failure there is logged into the tick's result, never raised."""
    import tracker.scheduler as entry
    from tracker.supervisor import entries

    asked: list[str] = []

    async def plugins_due():
        asked.append("plugins_due")
        raise RuntimeError("the runtime is gone")

    monkeypatch.setattr(entries, "plugins_due", plugins_due)
    result = await entry.start_due_plugins()
    assert asked == ["plugins_due"]
    assert "the runtime is gone" in result["error"]


@pytest.mark.asyncio
async def test_a_dead_run_is_closed_on_a_tick_even_when_no_plugin_may_run(db_session, monkeypatch):
    """A host killed mid-run (a crash, a power loss) and its plugin then
    turned off must not leave its row `running` for good: the tick reconciles
    before it returns, even when nothing is runnable."""
    await _install(db_session, enabled=False)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp1",
                             outcome="running", pid=555))
    await db_session.commit()
    monkeypatch.setattr(runtime, "_command", lambda pid: "")
    spawned = _Spawned()
    assert await start_due(db_session, trigger="schedule", spawner=spawned) == []
    assert spawned == []
    assert (await db_session.execute(select(PluginRun.outcome))).scalar_one() == "error"


# --------------------------------------------------------------------------- #
# Asking the supervisor, against the database
# --------------------------------------------------------------------------- #


async def _plugin_requests(db) -> list:
    from tracker.db.models import JobRequest

    db.expire_all()
    return list(await db.scalars(select(JobRequest).where(JobRequest.job.in_(("plugin_run", "reestimate")))))


@pytest.mark.asyncio
async def test_a_run_is_asked_for_per_plugin_with_the_trigger_its_power_rule_needs(db_session):
    await runtime.spawn_run(db_session, "tpl", "refresh", trigger="schedule")
    await runtime.spawn_run(db_session, "tpl", "import", trigger="manual")
    await db_session.commit()

    requests = sorted(await _plugin_requests(db_session), key=lambda r: r.id)
    assert [(r.key, r.args["trigger"], r.args["argv"]) for r in requests] == [
        ("plugin_run:tpl", "schedule", ["tpl", "refresh", "--trigger", "schedule"]),
        ("plugin_run:tpl", "manual", ["tpl", "import", "--trigger", "manual"]),
    ], "two jobs of one plugin queue under one key: they run one after the other"


@pytest.mark.asyncio
async def test_a_burst_of_decisions_asks_for_one_re_estimate(db_session):
    for _ in range(3):
        await runtime.spawn_reestimate(db_session)
    await db_session.commit()
    assert [r.job for r in await _plugin_requests(db_session)] == ["reestimate"]


@pytest.mark.asyncio
async def test_due_work_is_asked_for_and_committed_so_the_supervisor_sees_it(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    await _install(db_session)
    result = await runtime.plugins_when_due(
        db_session, trigger="schedule", power=lambda: Power(dark_wake=False, on_battery=False), now=NOW
    )
    assert result == {"started": ["tpl:refresh"], "waiting": None}
    async with async_sessionmaker(db_session.bind)() as elsewhere:
        assert [r.key for r in await _plugin_requests(elsewhere)] == ["plugin_run:tpl"]


@pytest.mark.asyncio
async def test_stopping_a_plugin_cancels_its_queued_runs_and_asks_the_supervisor_to_stop_its_live_one(db_session):
    from tracker.db import job_store
    from tracker.db.models import JobRun

    await _install(db_session)
    await runtime.spawn_run(db_session, "tpl", "refresh", trigger="schedule")
    await db_session.commit()
    _request, live = await job_store.claim(db_session, "plugin_run:tpl")
    live_id = live.id
    await runtime.spawn_run(db_session, "tpl", "import", trigger="manual")
    await runtime.spawn_run(db_session, "other", "refresh", trigger="schedule")
    await db_session.commit()

    await stop_runs(db_session, "tpl", command=lambda pid: "", kill=lambda pid, sig: None)

    states = {(r.key, r.args["argv"][1]): r.state for r in await _plugin_requests(db_session)}
    assert states == {
        ("plugin_run:tpl", "refresh"): job_store.CLAIMED,
        ("plugin_run:tpl", "import"): job_store.CANCELLED,
        ("plugin_run:other", "refresh"): job_store.QUEUED,
    }, "another plugin's work is not this stop's"
    run = await db_session.get(JobRun, live_id)
    await db_session.refresh(run)
    assert run.cancel_reason == "plugin_stop"
