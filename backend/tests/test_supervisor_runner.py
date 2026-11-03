"""Supervised processes start, end, survive and stop the way the supervisor needs.

Real processes, fake jobs: a job that exits with a code, one that sleeps, one that
ignores SIGTERM, one that starts a grandchild, one that floods its log. The runner
is the subject, so nothing in it is mocked; the processes live under `tmp_path`
and every one is gone when its test ends.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

from tracker.platform.paths import REPO_ROOT
from tracker.supervisor import child, logs, runner
from tracker.supervisor.registry import JobSpec, OnRequest, Power

#: Captured at import, before `no_escape` replaces them. The fixture below hands
#: them back to these tests only: starting and signalling processes is the
#: behaviour under test, and every process is one this file started.
REAL_POPEN = subprocess.Popen
REAL_KILL = os.kill
REAL_KILLPG = os.killpg

pytestmark = pytest.mark.usefixtures("no_escape")


@pytest.fixture(autouse=True)
def real_processes(no_escape, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    monkeypatch.setattr(os, "kill", REAL_KILL)
    monkeypatch.setattr(os, "killpg", REAL_KILLPG)


def _job(code: str, **fields) -> JobSpec:
    return JobSpec(
        "fake",
        ("{python}", "-c", code),
        OnRequest(),
        power=Power.NONE,
        uses_database=False,
        **fields,
    )


def _launch(job: JobSpec, run_id: int, data_dir: Path, **kwargs) -> runner.Launched:
    return runner.launch(job, run_id, repo_root=REPO_ROOT, data_dir=data_dir, **kwargs)


def _wait(launched: runner.Launched, timeout: float = 20) -> int:
    assert launched.process is not None
    return launched.process.wait(timeout=timeout)


def _wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def _gone(pid: int) -> bool:
    try:
        REAL_KILL(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_a_job_s_exit_code_and_output_reach_its_result_file_and_its_log(tmp_path):
    launched = _launch(_job("print('read 3 boards'); raise SystemExit(3)"), 41, tmp_path)
    assert _wait(launched) == 3

    result = child.read_result(runner.result_path(tmp_path, 41))
    assert result is not None and result["exit_code"] == 3
    assert "read 3 boards" in launched.log_path.read_text()


def test_a_job_appends_to_its_log_and_records_where_its_output_begins(tmp_path):
    job = _job("print('second run')")
    first = _launch(_job("print('first run')"), 1, tmp_path)
    _wait(first)
    size = first.log_path.stat().st_size
    second = _launch(job, 2, tmp_path)
    _wait(second)

    assert second.log_offset == size
    text = second.log_path.read_text()
    assert text.index("first run") < text.index("second run"), "a log is appended to, never replaced"
    assert text[second.log_offset :].strip() == "second run"


def test_a_job_runs_as_the_leader_of_its_own_session(tmp_path):
    launched = _launch(_job("import time; time.sleep(30)"), 7, tmp_path)
    try:
        assert launched.pgid == launched.pid
        assert os.getpgid(launched.pid) == launched.pid
        assert os.getpgid(launched.pid) != os.getpgrp(), "a job must not share the supervisor's group"
    finally:
        REAL_KILLPG(launched.pgid, signal.SIGKILL)
        _wait(launched)


def test_a_job_gets_its_run_id_and_loads_this_checkout_s_code(tmp_path):
    code = (
        "import os, tracker; "
        "print(os.environ['ROLEBAND_JOB_RUN']); print(tracker.__file__)"
    )
    # The supervisor's own environment need not name this checkout: under
    # launchd it does not.
    bare = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    launched = _launch(_job(code, cwd="dashboard"), 99, tmp_path, env=bare)
    assert _wait(launched) == 0
    run_id, module = launched.log_path.read_text().split()[-2:]
    assert run_id == "99"
    assert module == str(REPO_ROOT / "backend" / "tracker" / "__init__.py"), (
        "a job started outside backend/ must still import this checkout"
    )


def test_a_job_outlives_the_process_that_started_it_and_still_reports_its_end(tmp_path):
    """A supervisor that dies mid-run must not take the run with it, and its
    successor must be able to prove the orphan is the run and read how it ended."""
    marker = tmp_path / "go"
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "from tracker.platform.paths import REPO_ROOT\n"
        "from tracker.supervisor import runner\n"
        "from tracker.supervisor.registry import JobSpec, OnRequest, Power\n"
        f"job = JobSpec('fake', ('{{python}}', '-c', \"import time, pathlib\\nwhile not pathlib.Path({str(marker)!r}).exists(): time.sleep(0.05)\\nraise SystemExit(5)\"), OnRequest(), power=Power.NONE, uses_database=False)\n"
        f"launched = runner.launch(job, 123, repo_root=REPO_ROOT, data_dir=Path({str(tmp_path)!r}))\n"
        "print(launched.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    env = runner.child_env(None, 0, REPO_ROOT)
    supervisor = REAL_POPEN(
        [sys.executable, str(launcher)], stdout=subprocess.PIPE, text=True, env=env
    )
    pid = int(supervisor.stdout.readline())
    began = runner.started_at(pid)
    REAL_KILL(supervisor.pid, signal.SIGKILL)
    supervisor.wait(timeout=10)

    try:
        assert not _gone(pid), "the job died with the process that started it"
        assert runner.is_run(pid, 123, began)
        assert runner.find_run(123) == pid
        assert not runner.is_run(pid, 12, began), "run 12 must not claim run 123's process"
        assert not runner.is_run(pid, 123, began + timedelta(seconds=30)), "a recycled PID is not the run"
    finally:
        marker.touch()
    _wait_for(lambda: _gone(pid))
    _wait_for(lambda: child.read_result(runner.result_path(tmp_path, 123)) is not None)
    assert child.read_result(runner.result_path(tmp_path, 123))["exit_code"] == 5


def test_stopping_a_job_terminates_it_and_its_result_says_how_it_ended(tmp_path):
    launched = _launch(_job("import time; print('ready', flush=True); time.sleep(60)"), 8, tmp_path)
    _wait_for(lambda: "ready" in launched.log_path.read_text())
    outcome = asyncio.run(runner.stop_group(launched.pgid, 5, reap=launched.process.poll))

    assert outcome == "terminated"
    result = child.read_result(runner.result_path(tmp_path, 8))
    assert result["exit_code"] == -signal.SIGTERM
    assert result["signalled"] == [signal.SIGTERM]


def test_a_stop_during_startup_ends_the_run_and_leaves_nothing_running(tmp_path):
    """A cancel that lands before the job printed a line: the group is gone,
    whether the trampoline got as far as starting the command or not."""
    flag = tmp_path / "started"
    code = f"import pathlib, time; pathlib.Path({str(flag)!r}).touch(); time.sleep(60)"
    launched = _launch(_job(code), 15, tmp_path)
    outcome = asyncio.run(runner.stop_group(launched.pgid, 5, reap=launched.process.poll))

    assert outcome in {"terminated", "killed"}
    assert launched.process.returncode is not None and launched.process.returncode != 0
    assert not runner.group_alive(launched.pgid)
    time.sleep(0.3)
    assert not runner.group_alive(launched.pgid), "nothing the run started may linger"


def test_a_job_that_ignores_sigterm_is_killed_after_its_grace(tmp_path):
    code = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(60)"
    )
    launched = _launch(_job(code), 9, tmp_path)
    _wait_for(lambda: "ready" in launched.log_path.read_text())
    started = time.monotonic()
    outcome = asyncio.run(runner.stop_group(launched.pgid, 0.5, reap=launched.process.poll))

    assert outcome == "killed"
    assert time.monotonic() - started >= 0.5, "SIGKILL must wait out the grace"
    assert launched.process.poll() is not None


def test_stopping_a_job_reaches_the_processes_it_started(tmp_path):
    code = (
        "import subprocess, sys, time; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(p.pid, flush=True); time.sleep(60)"
    )
    launched = _launch(_job(code), 10, tmp_path)
    _wait_for(lambda: launched.log_path.read_text().strip().isdigit())
    grandchild = int(launched.log_path.read_text().split()[-1])
    assert not _gone(grandchild)

    asyncio.run(runner.stop_group(launched.pgid, 5, reap=launched.process.poll))
    _wait_for(lambda: _gone(grandchild) or _zombie(grandchild))
    assert not runner.group_alive(launched.pgid)


def _zombie(pid: int) -> bool:
    found = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return found.stdout.strip().startswith("Z")


def test_stopping_a_group_that_already_ended_reports_it_gone(tmp_path):
    launched = _launch(_job("pass"), 11, tmp_path)
    _wait(launched)
    assert asyncio.run(runner.stop_group(launched.pgid, 1, reap=launched.process.poll)) == "gone"


def test_a_command_that_cannot_start_leaves_a_result_not_a_mystery(tmp_path):
    job = JobSpec("missing", ("/nonexistent/tool",), OnRequest(), power=Power.NONE, uses_database=False)
    launched = _launch(job, 12, tmp_path)
    assert _wait(launched) == 127
    assert child.read_result(runner.result_path(tmp_path, 12))["exit_code"] == 127


def test_a_flood_of_output_on_both_streams_never_blocks_the_job(tmp_path):
    """No pipe to fill: the job writes straight to its file."""
    code = (
        "import sys; chunk = 'x' * 1023 + '\\n'\n"
        "for _ in range(6 * 1024):\n"
        "    sys.stdout.write(chunk); sys.stderr.write(chunk)\n"
    )
    launched = _launch(_job(code), 13, tmp_path)
    assert _wait(launched, timeout=60) == 0
    assert launched.log_path.stat().st_size >= 12 * 1024 * 1024


@pytest.mark.skipif(sys.platform != "darwin", reason="caffeinate is macOS's")
def test_a_caffeinated_job_holds_the_machine_awake_only_while_it_runs(tmp_path):
    launched = _launch(_job("import time; time.sleep(1.5)", caffeinate=True), 14, tmp_path)
    _wait_for(lambda: _caffeinate_for(launched.pid))
    assert _wait(launched) == 0
    _wait_for(lambda: not _caffeinate_for(launched.pid))


def _caffeinate_for(pid: int) -> bool:
    out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    return any(
        line.split() and Path(line.split()[0]).name == "caffeinate" and f"-w {pid}" in line
        for line in out.splitlines()
    )


# --- log rotation ------------------------------------------------------------------


def test_a_log_over_its_limit_is_copied_aside_and_emptied(tmp_path):
    log = tmp_path / "scan.log"
    log.write_bytes(b"a" * 2048)
    assert logs.rotate(log, limit=1024)
    assert log.stat().st_size == 0
    assert logs.rotated(log).read_bytes() == b"a" * 2048
    assert not logs.rotate(log, limit=1024), "an empty log is not rotated again"


def test_rotating_twice_keeps_one_copy_so_a_log_is_bounded_by_twice_its_limit(tmp_path):
    log = tmp_path / "scan.log"
    log.write_bytes(b"1" * 2048)
    logs.rotate(log, limit=1024)
    log.write_bytes(b"2" * 2048)
    logs.rotate(log, limit=1024)
    assert logs.rotated(log).read_bytes() == b"2" * 2048
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scan.log", "scan.log.1"]


def test_a_running_writer_keeps_appending_at_the_new_end_after_rotation(tmp_path):
    """The child's descriptor is append-mode: after the truncate its next write
    lands at offset 0, not past a hole of zero bytes."""
    log = tmp_path / "job.log"
    fd = logs.open_append(log)
    try:
        os.write(fd, b"before\n" * 400)
        assert logs.rotate(log, limit=100)
        os.write(fd, b"after\n")
    finally:
        os.close(fd)
    assert log.read_bytes() == b"after\n"


def test_trimming_the_launchd_stream_keeps_its_tail(tmp_path):
    stream = tmp_path / "launchd.log"
    stream.write_bytes(b"old\n" * 1000 + b"crash before logging started\n")
    assert logs.trim(stream, keep=64)
    kept = stream.read_bytes()
    assert len(kept) == 64
    assert kept.endswith(b"crash before logging started\n")
    assert not logs.trim(stream, keep=64)


def test_a_log_is_readable_by_its_owner_only(tmp_path):
    fd = logs.open_append(tmp_path / "deep" / "job.log")
    os.close(fd)
    assert (tmp_path / "deep" / "job.log").stat().st_mode & 0o777 == 0o600


def test_the_copy_names_only_log_files_the_supervisor_writes(tmp_path):
    """A message that sends the user to a log file nobody writes any more is a
    dead end: every `data/...log` the English copy names is one of the files
    the supervisor's layout has (a job's, its own, the API's, or the alerts)."""
    import re

    from tracker.supervisor import registry

    written = {f"data/logs/{job.name}.log" for job in registry.JOBS}
    written |= {f"data/{p.relative_to(tmp_path)}" for p in logs.shared(tmp_path, tmp_path / "pg")[:2]}
    written |= {"data/logs/api.log", "data/logs/launchd.log"}
    named = {
        path
        for ftl in (REPO_ROOT / "dashboard" / "src" / "copy" / "en").glob("*.ftl")
        for path in re.findall(r"data/[A-Za-z0-9_./-]+\.log", ftl.read_text())
    }
    assert named, "the copy names at least the backup's log"
    assert named <= written, sorted(named - written)
