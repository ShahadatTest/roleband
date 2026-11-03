"""The one way a supervised job starts.

    python -m tracker.supervisor.child --run <id> --result <path> [--caffeinate] -- <command...>

The argv carries the run id, so a supervisor that restarts can prove a process is
still this run by its PID, its start time and this marker together: the OS
recycles PIDs, so a PID alone proves nothing. The trampoline runs the command in its own process group
(the runner starts it as a session leader), keeps the machine from idle-sleeping
while it runs when asked, and writes how the command ended to the result file
before it exits, so a run's end is known even when the supervisor that started it
has gone. It never touches the database: a backup or a preflight runs while the
database is down.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

MARKER = "tracker.supervisor.child"


def marks_run(command: str, run_id: int) -> bool:
    """Whether a process command line is the trampoline of run `run_id`.

    Compared token by token: `--run 12` must not match run 123."""
    tokens = command.split()
    for index, token in enumerate(tokens):
        if token == MARKER and tokens[index + 1 : index + 3] == ["--run", str(run_id)]:
            return True
    return False


def write_result(path: Path, payload: object) -> None:
    """Replace the result file in one step, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(partial, path)


def read_result(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    signalled: list[int] = []

    def note(signum: int, _frame: FrameType | None) -> None:
        # A signal to the group reaches the command as well; the trampoline stays
        # only to record how the command ended.
        signalled.append(signum)

    # First, before anything that takes time: a stop that arrives earlier ends
    # the trampoline before it has started the command, which is a clean stop
    # with nothing left behind, but leaves no result file.
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, note)

    parser = argparse.ArgumentParser(prog=f"python -m {MARKER}")
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--caffeinate", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command to run")

    helper = None
    caffeinate = shutil.which("caffeinate") if args.caffeinate else None
    if caffeinate is not None:
        # Holds the power assertion until this process exits, then exits itself.
        helper = subprocess.Popen(  # noqa: S603 - fixed system tool, our own PID
            [caffeinate, "-s", "-i", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    if signalled:
        # Stopped before the command started: start nothing.
        write_result(args.result, {"exit_code": 128 + signalled[0], "signalled": signalled[:1], "ended_at": _now()})
        return 128 + signalled[0]
    try:
        child = subprocess.Popen(command)  # noqa: S603 - a registry command, never user input
    except OSError as error:
        write_result(args.result, {"exit_code": 127, "error": str(error), "ended_at": _now()})
        return 127
    if signalled:
        # The group's signal came between the check above and the start, before
        # the command existed to receive it.
        child.send_signal(signalled[0])
    code = child.wait()
    write_result(
        args.result,
        {
            "exit_code": code,
            "signal": -code if code < 0 else None,
            "signalled": signalled[:1] or None,
            "ended_at": _now(),
        },
    )
    if helper is not None:
        helper.terminate()
    return code if code >= 0 else 128 - code


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    sys.exit(main())
