"""A finished test session leaves no embedded Postgres server running.

Unguarded, every full run leaves throwaway servers behind, re-parented to
launchd. Upstream, a request for a `cleanup_mode="delete"` handle can return the
one `ensure_server` already cached in the same process, whose mode is `None`
(the app's server must outlive its process), so `.cleanup()` returns before
stopping anything. pytest's retention hides the scale: rotating out the oldest
basetemp deletes its servers' lock files, and Postgres shuts itself down within
a minute of losing one, so the count settles at three runs' worth instead of
growing.

Two layers, and removing either one fails a test here:

- `destroy` stops the server it is given and deletes the cluster, in-process.
- The session stops whatever a test left running under its own basetemp, when
  it finishes and when it is interrupted, serial and under xdist. Those cases
  run a real, separate pytest, as `test_skip_policy.py` does: a teardown that is
  never registered passes every in-process assertion about its helper.

`pg_ctl` starts each postmaster in a session of its own, so the SIGINT sent to
the probe's process group reaches pytest and never Postgres: a server that
stops was stopped by the harness, not by the signal.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pixeltable_pgserver", reason="embedded Postgres wheel not installed")

import psutil  # noqa: E402 - a pgserver dependency, present whenever the wheel is

from tests.embedded_utils import cluster_locale, destroy, running_clusters  # noqa: E402
from tracker.platform.embedded_db import ensure_server, stop_server  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

# Each probe starts a server and never tears it down, then records the
# postmaster's PID outside the basetemp, so the check below cannot pass
# because no server was ever started.
_PROBE = '''
import os
import time
from pathlib import Path

from tests.embedded_utils import cluster_locale
from tracker.platform.embedded_db import ensure_server


def _start(tmp_path, name):
    server = ensure_server(tmp_path / "db", database="probe", locale=cluster_locale())
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    pid = (server.pgdata / "postmaster.pid").read_text().split()[0]
    (Path(os.environ["PROBE_PIDS"]) / f"{worker}-{name}").write_text(pid)


def test_leaves_its_server_running(tmp_path):
    _start(tmp_path, "finished")


def test_is_interrupted_while_its_server_runs(tmp_path):
    _start(tmp_path, "interrupted")
    time.sleep(300)
'''

_TIMEOUT = 180


def _is_postmaster(pid: int) -> bool:
    """A live postgres process. A zombie has stopped: it is only waiting for
    a parent to reap it, which a container whose PID 1 never reaps never does,
    and on Linux it still answers `name()`."""
    try:
        process = psutil.Process(pid)
        return process.status() != psutil.STATUS_ZOMBIE and "postgres" in process.name()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False


def _postmaster_pid(pgdata: Path) -> int:
    return int((pgdata / "postmaster.pid").read_text().split()[0])


class _ProbeSession:
    """A separate pytest over `_PROBE` that loads the real harness from `tests.conftest`."""

    def __init__(self, tmp_path: Path, workers: int) -> None:
        self.root = tmp_path
        self.workers = workers
        self.basetemp = tmp_path / "basetemp"
        self.pids = tmp_path / "pids"
        self.pids.mkdir()
        self.log = tmp_path / "session.log"
        self.proc: subprocess.Popen | None = None
        (tmp_path / "test_probe.py").write_text(_PROBE)
        # An ini of its own keeps the repo's workers out; the harness comes in by `-p`.
        (tmp_path / "pytest.ini").write_text("[pytest]\nasyncio_default_fixture_loop_scope = function\n")

    def _expected(self, name: str) -> set[str]:
        workers = ["main"] if self.workers == 0 else [f"gw{i}" for i in range(self.workers)]
        return {f"{worker}-{name}" for worker in workers}

    def _start(self, test: str) -> subprocess.Popen:
        # The outer run's PYTEST_XDIST_WORKER would otherwise name the probe's worker.
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
        env |= {"PYTHONPATH": str(BACKEND), "PROBE_PIDS": str(self.pids)}
        dist = ["-n", "0"] if self.workers == 0 else ["-n", str(self.workers), "--dist", "each"]
        with self.log.open("w") as log:
            self.proc = subprocess.Popen(
                [
                    sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                    "-p", "tests.conftest", "-c", str(self.root / "pytest.ini"),
                    "--rootdir", str(self.root), "--basetemp", str(self.basetemp),
                    *dist, f"test_probe.py::{test}",
                ],
                cwd=self.root, env=env, stdout=log, stderr=subprocess.STDOUT,
                # Its own process group, so the SIGINT below reaches this run and nothing else.
                start_new_session=True,
            )
        return self.proc

    def finish(self) -> int:
        return self._start("test_leaves_its_server_running").wait(timeout=_TIMEOUT)

    def interrupt(self) -> int:
        proc = self._start("test_is_interrupted_while_its_server_runs")
        expected = self._expected("interrupted")
        deadline = time.monotonic() + _TIMEOUT
        while not expected <= {path.name for path in self.pids.iterdir()}:
            if proc.poll() is not None or time.monotonic() > deadline:
                pytest.fail(f"the probe never started its servers:\n{self.output()}")
            time.sleep(0.2)
        os.killpg(proc.pid, signal.SIGINT)  # what Ctrl-C in a terminal sends
        return proc.wait(timeout=_TIMEOUT)

    def assert_started_and_stopped(self, name: str) -> None:
        recorded = {path.name: int(path.read_text()) for path in self.pids.iterdir()}
        assert set(recorded) == self._expected(name), self.output()
        assert running_clusters(self.basetemp) == {}, self.output()
        assert [pid for pid in recorded.values() if _is_postmaster(pid)] == [], self.output()

    def output(self) -> str:
        return self.log.read_text(errors="replace")[-4000:]

    def cleanup(self) -> None:
        """Leave nothing behind, including when an assertion above failed."""
        if self.proc is not None and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        for pgdata in running_clusters(self.basetemp):
            stop_server(pgdata)


class TestDestroy:
    def test_stops_the_server_and_removes_the_cluster(self, tmp_path):
        server = ensure_server(tmp_path / "db2", database="probe", locale=cluster_locale())
        pgdata = server.pgdata.resolve()
        pid = _postmaster_pid(pgdata)
        try:
            # The finder sees this server, and only from a root that contains it:
            # `db` shares the directory's name prefix without containing it.
            assert running_clusters(tmp_path) == {pgdata: pid}
            assert running_clusters(tmp_path / "db") == {}

            destroy(server.pgdata)

            assert running_clusters(tmp_path) == {}
            assert not _is_postmaster(pid)
            assert not server.pgdata.exists()
        finally:
            for leaked in running_clusters(tmp_path):
                stop_server(leaked)


@pytest.mark.parametrize("workers", [0, 2], ids=["serial", "xdist"])
class TestTheSessionStopsWhatATestLeftRunning:
    def test_when_it_finishes(self, tmp_path, workers):
        session = _ProbeSession(tmp_path, workers)
        try:
            assert session.finish() == 0, session.output()
            session.assert_started_and_stopped("finished")
        finally:
            session.cleanup()

    def test_when_it_is_interrupted(self, tmp_path, workers):
        session = _ProbeSession(tmp_path, workers)
        try:
            assert session.interrupt() == pytest.ExitCode.INTERRUPTED, session.output()
            session.assert_started_and_stopped("interrupted")
        finally:
            session.cleanup()


def test_a_zombie_postmaster_counts_as_stopped(monkeypatch):
    """The negative control is a live postgres, which still counts."""

    class Process:
        def __init__(self, status: str) -> None:
            self._status = status

        def status(self) -> str:
            return self._status

        def name(self) -> str:
            return "postgres"

    monkeypatch.setattr(psutil, "Process", lambda pid: Process(psutil.STATUS_ZOMBIE))
    assert _is_postmaster(1) is False
    monkeypatch.setattr(psutil, "Process", lambda pid: Process(psutil.STATUS_SLEEPING))
    assert _is_postmaster(1) is True

    def zombie(pid):
        raise psutil.ZombieProcess(pid)

    monkeypatch.setattr(psutil, "Process", zombie)
    assert _is_postmaster(1) is False


def test_a_process_that_exits_while_its_arguments_are_read_is_not_a_cluster(monkeypatch, tmp_path):
    """macOS can answer SystemError or AccessDenied for a process that exits mid-read.
    A gone one is skipped; a live postmaster is asked again and still counted, never
    dropped; another user's process stays unreadable and is not a test's."""
    pgdata = tmp_path / "db"
    pgdata.mkdir()

    class Process:
        def __init__(self, pid: int, answers: list, running: bool) -> None:
            self.info = {"pid": pid, "name": "postgres"}
            self._answers, self._running = answers, running

        def cmdline(self) -> list[str]:
            answer = self._answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        def is_running(self) -> bool:
            return self._running

    failed = SystemError("<built-in function proc_cmdline> returned a result with an exception set")
    postmaster = ["postgres", "-D", str(pgdata)]
    refused = psutil.AccessDenied(14, "postgres")
    gone = Process(11, [failed], running=False)
    gone_refused = Process(14, [refused], running=False)
    flaky = Process(12, [failed, refused, postmaster], running=True)
    foreign = Process(15, [refused, refused, refused], running=True)
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: iter([gone, gone_refused, flaky, foreign]))
    assert running_clusters(tmp_path) == {pgdata.resolve(): 12}

    stuck = Process(13, [failed, failed, failed], running=True)
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: iter([stuck]))
    with pytest.raises(SystemError):
        running_clusters(tmp_path)
