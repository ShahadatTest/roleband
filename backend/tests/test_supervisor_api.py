"""The API as the supervisor's child: started, probed, restarted when it exits or
stops answering, with a backoff, and stopped gracefully.

A small HTTP server stands in for uvicorn, on a free port; its health answer is
read from a file the test writes, so a test can make a running API turn sick.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tracker.platform.paths import REPO_ROOT
from tracker.supervisor import api as api_module
from tracker.supervisor.api import ApiService

REAL_POPEN = subprocess.Popen
REAL_KILL = os.kill
REAL_ASYNC_HTTP = httpx.AsyncHTTPTransport.handle_async_request

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]


@pytest.fixture(autouse=True)
def real_processes(no_escape, monkeypatch):
    """The fake API is a real process this file starts and stops, and the only
    host the health probe reaches is it, on the loopback."""
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    monkeypatch.setattr(os, "kill", REAL_KILL)

    async def loopback_only(self, request):
        assert request.url.host == "127.0.0.1", request.url
        return await REAL_ASYNC_HTTP(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", loopback_only)


SERVER = """
import http.server, pathlib, socketserver, sys
answer = pathlib.Path(sys.argv[2])
class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = int(answer.read_text().strip() or 200) if answer.exists() else 200
        self.send_response(code); self.end_headers()
    def log_message(self, *args):
        pass
class Quick(http.server.HTTPServer):
    def server_bind(self):
        # HTTPServer would look its own name up in DNS first, which can take seconds.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]
Quick(("127.0.0.1", int(sys.argv[1])), Health).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _service(tmp_path: Path, *, command=None, **timing) -> tuple[ApiService, Path]:
    port = _free_port()
    answer = tmp_path / "answer"
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    service = ApiService(
        repo_root=REPO_ROOT, data_dir=tmp_path, host="127.0.0.1", port=port,
        command=command or [sys.executable, str(script), str(port), str(answer)],
        **{"start_grace_seconds": 5, "probe_every_seconds": 0, "failures_to_restart": 2, **timing},
    )
    return service, answer


async def _until(service: ApiService, state: str, *, clock: list[float], timeout: float = 10) -> None:
    for _ in range(int(timeout / 0.05)):
        clock[0] += 0.05
        await service.tend(clock[0])
        if service.state == state:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"api never reached {state} (is {service.state}, {service.reason})")


async def test_the_api_starts_answers_and_stops_gracefully(tmp_path):
    service, _ = _service(tmp_path)
    clock = [0.0]
    try:
        await _until(service, api_module.RUNNING, clock=clock)
        status = service.status()
        assert (status.key, status.state, status.detail["port"]) == ("api", "running", service.port)
        process = service.process
        await service.stop()
        assert process.poll() is not None
        assert service.state == api_module.STOPPED
    finally:
        await service.stop()


async def test_an_api_that_exits_is_restarted_and_the_wait_resets_after_a_healthy_run(tmp_path):
    service, _ = _service(tmp_path)
    clock = [0.0]
    try:
        await _until(service, api_module.RUNNING, clock=clock)
        service.process.kill()
        service.process.wait()
        await service.tend(clock[0])
        assert (service.state, service.reason) == (api_module.WAITING, api_module.EXITED)
        await service.tend(clock[0] + 0.5)
        assert service.process is None, "not before the wait has passed"
        clock[0] += 1.0
        await _until(service, api_module.RUNNING, clock=clock)
        assert service.restarts == 1

        service.process.kill()
        service.process.wait()
        await service.tend(clock[0])
        clock[0] += 1.0
        await service.tend(clock[0])
        assert service.process is not None, "a healthy run reset the wait to a second"
    finally:
        await service.stop()


async def test_an_api_that_cannot_start_waits_longer_each_time(tmp_path):
    service, _ = _service(tmp_path, command=[sys.executable, "-c", "raise SystemExit(3)"])
    try:
        waits = []
        clock = 0.0
        for _ in range(3):
            await service.tend(clock)
            service.process.wait()
            await service.tend(clock)
            assert service.state == api_module.WAITING
            waits.append(service._resume_at - clock)
            clock = service._resume_at
        assert waits == [1.0, 2.0, 4.0]
    finally:
        await service.stop()


async def test_an_api_that_stops_answering_is_restarted(tmp_path):
    service, answer = _service(tmp_path)
    clock = [0.0]
    try:
        await _until(service, api_module.RUNNING, clock=clock)
        first = service.process.pid
        answer.write_text("503")
        clock[0] += 1
        await service.tend(clock[0])
        assert service.state == api_module.RUNNING, "one failed probe is not enough"
        clock[0] += 1
        await service.tend(clock[0])
        assert (service.state, service.reason) == (api_module.WAITING, api_module.UNHEALTHY)
        answer.write_text("200")
        clock[0] += 2
        await _until(service, api_module.RUNNING, clock=clock)
        assert service.process.pid != first
    finally:
        await service.stop()


async def test_an_api_that_never_becomes_healthy_is_restarted_after_its_grace(tmp_path):
    service, _ = _service(tmp_path, command=[sys.executable, "-c", "import time; time.sleep(60)"])
    clock = [0.0]
    try:
        await service.tend(clock[0])
        assert service.state == api_module.STARTING
        await service.tend(clock[0] + 4)
        assert service.state == api_module.STARTING
        await service.tend(clock[0] + 6)
        assert (service.state, service.reason) == (api_module.WAITING, api_module.UNHEALTHY)
        assert service.process is None
    finally:
        await service.stop()


async def test_a_stop_kills_an_api_that_ignores_sigterm(tmp_path):
    stubborn = [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"]
    service, _ = _service(tmp_path, command=stubborn)
    await service.tend(0)
    process = service.process
    await asyncio.sleep(0.3)
    await asyncio.wait_for(service.stop(grace_seconds=0.5), timeout=5)
    assert process.poll() is not None


async def test_uvicorn_runs_the_app_without_access_lines():
    command = api_module.uvicorn_command("/py", "127.0.0.1", 8010)
    assert command[:4] == ["/py", "-m", "uvicorn", "tracker.api.app:app"]
    assert "--no-access-log" in command
