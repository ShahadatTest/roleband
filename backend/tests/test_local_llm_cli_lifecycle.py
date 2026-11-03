"""The oMLX CLI a control call starts does not outlive the call.

`control()` kills and reaps its CLI on a timeout and on cancellation (the task
awaiting it cancelled); without the second the CLI keeps running. These tests run a
real, harmless child (a Python one-liner standing in for the CLI: the binary is
`sys.executable` and the spawn swaps the arguments), never oMLX, and kill
anything left over themselves.

Under `no_escape`, lifted for exactly two things: starting `sys.executable -c
<the test's script>`, and signalling the children this test started. Any
other spawn or signal is still refused.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from tests.conftest import EscapeRefused
from tracker.local_llm import server

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

#: The real primitives, taken at import, before `no_escape` refuses them.
_REAL_EXEC = asyncio.create_subprocess_exec
_REAL_POPEN = subprocess.Popen
_REAL_KILL = os.kill


@pytest.fixture
def harmless(monkeypatch, no_escape):
    """`(spawn_with(script), children, spawned)`: point `control()` at a Python
    one-liner and allow only it, and signals to it."""
    children: list = []
    spawned = asyncio.Event()

    def popen(args, *rest, **kwargs):
        if list(args[:2]) != [sys.executable, "-c"]:
            raise EscapeRefused("subprocess")
        return _REAL_POPEN(args, *rest, **kwargs)

    def kill(pid, sig):
        if sig == 0 or pid in {child.pid for child in children}:
            return _REAL_KILL(pid, sig)
        raise EscapeRefused(f"signal {sig} to pid {pid}")

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(server, "binary_path", lambda: sys.executable)

    def spawn_with(script: str) -> None:
        async def spawn(*_args, **kwargs):
            child = await _REAL_EXEC(sys.executable, "-c", script, **kwargs)
            children.append(child)
            spawned.set()
            return child

        monkeypatch.setattr(server.asyncio, "create_subprocess_exec", spawn)

    yield spawn_with, children, spawned
    for child in children:
        if child.returncode is None:
            _REAL_KILL(child.pid, 9)


async def test_a_cancelled_control_kills_and_reaps_its_cli(harmless):
    spawn_with, children, spawned = harmless
    spawn_with("import time; time.sleep(60)")
    task = asyncio.create_task(server.control("start"))
    await asyncio.wait_for(spawned.wait(), timeout=10)
    await asyncio.sleep(0.05)  # inside `communicate`
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task  # cancellation stays cancellation
    assert children[0].returncode is not None


async def test_a_control_that_times_out_kills_and_reaps_its_cli(harmless, monkeypatch):
    spawn_with, children, _ = harmless
    spawn_with("import time; time.sleep(60)")
    monkeypatch.setitem(server._TIMEOUTS, "stop", 0.3)
    result = await server.control("stop")
    assert result.ok is False and "did not finish" in result.detail
    assert children[0].returncode is not None


async def test_a_cli_that_already_exited_is_cleaned_up_without_error(harmless, monkeypatch):
    """The process can end between the decision to kill it and the signal."""
    spawn_with, children, _ = harmless
    spawn_with("pass")

    async def exits_then_cancelled(self, input=None):
        await self.wait()
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio.subprocess.Process, "communicate", exits_then_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await server.control("start")
    assert children[0].returncode == 0


async def test_an_ordinary_exit_still_reports_its_output(harmless):
    """The control: a CLI that finishes keeps its reported outcome."""
    spawn_with, _children, _ = harmless
    spawn_with("print('oMLX server running'); raise SystemExit(3)")
    result = await server.control("start")
    assert (result.ok, result.detail) == (False, "oMLX server running")


async def test_the_lifted_guard_still_refuses_anything_else(harmless):
    """The lift is exactly the test's own child: any other spawn is refused."""
    with pytest.raises(EscapeRefused):
        subprocess.Popen(["/bin/echo", "escaped"])
