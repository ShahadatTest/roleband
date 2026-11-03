"""Start and stop the locally-installed oMLX managed server.

Only oMLX is controllable, and only when its CLI is actually on this Mac: the
binary is resolved with `shutil.which`, never assumed. A profile pointing at
some other OpenAI-compatible server is reported `managed=False` — we did not
start it and must not claim we can stop it.

Safety shape, deliberately narrow: a FIXED argv (`<resolved omlx> start|stop`)
with no shell, no user-supplied arguments, and no environment inheritance
games. Nothing a profile contains reaches the command line, so a malicious
profile value cannot become an argument.

`omlx start` daemonizes its own managed server and returns; we therefore wait
for the CLI to exit (bounded) rather than tracking a PID. Whether the server is
actually ANSWERING is a separate question with a separate answer — the HTTP
probe in `reachable()` — because a CLI that exited 0 is not proof that a model
loaded.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

BINARY = "omlx"
Action = Literal["start", "stop", "restart"]
# `start` may load a multi-GB model from disk; `stop` should be prompt.
_TIMEOUTS: dict[str, float] = {"start": 120.0, "stop": 30.0, "restart": 150.0}
_MAX_DETAIL_CHARS = 400
#: How long a killed CLI may take to be reaped before we stop waiting for it.
_REAP_SECONDS = 5.0


@dataclass
class ControlResult:
    ok: bool
    action: str
    detail: str


def binary_path() -> str | None:
    """Absolute path to the oMLX CLI, or None when it is not installed."""
    return shutil.which(BINARY)


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text[:_MAX_DETAIL_CHARS]


async def control(action: Action) -> ControlResult:
    """Run one oMLX lifecycle command. Never raises for an ordinary failure —
    a missing binary, a non-zero exit, and a timeout are all reported states,
    because the caller renders them and must not 500 on any of them."""
    if action not in _TIMEOUTS:
        return ControlResult(False, str(action), "unsupported action")
    binary = binary_path()
    if binary is None:
        return ControlResult(
            False, action, "oMLX is not installed on this Mac."
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            action,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:  # binary vanished between which() and exec
        return ControlResult(False, action, f"could not run oMLX: {exc}")

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUTS[action])
    except TimeoutError:
        await _reap(proc)
        return ControlResult(
            False, action, f"oMLX {action} did not finish within {_TIMEOUTS[action]:.0f}s."
        )
    except BaseException:
        # Cancelled (the task awaiting this call went away) or failed: the CLI
        # is ours, so it does not outlive the call.
        # Only the CLI: a server it already daemonized is not ours
        # to stop. Re-raised, so cancellation stays cancellation.
        await _reap(proc)
        raise

    output = _clip(stdout.decode("utf-8", errors="replace"))
    ok = proc.returncode == 0
    logger.info("omlx %s -> rc=%s %s", action, proc.returncode, output)
    return ControlResult(ok, action, output or (f"oMLX {action} finished." if ok else
                                                f"oMLX {action} failed (exit {proc.returncode})."))


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Kill the CLI this call started and wait for it, bounded. One that exited
    on its own between the decision and the signal needs only the wait."""
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=_REAP_SECONDS)
    except TimeoutError:
        logger.warning("omlx CLI pid %s still running after kill", proc.pid)
