"""Maintenance mode: the supervisor stops its jobs, lets go of the database and
starts nothing until it is told to resume.

    python -m tracker.supervisor maintenance on [--drain]
    python -m tracker.supervisor maintenance off

A restore swaps the database out from under every client, so the request and
the supervisor's answer are files in `data/`, never rows: the database that
would hold them is the one being replaced. The supervisor reads the request at
every look, and every second while it is paused, without touching the database.

The answer names the supervisor's PID and the request it answers, so an answer
left by a supervisor that has since died, or one given to an earlier request,
is never read as the current supervisor being paused.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUEST = "maintenance.json"
ANSWER = "maintenance.answer.json"

#: The supervisor is stopping its running jobs (or waiting for them, with `drain`).
DRAINING = "draining"
#: Nothing runs, nothing starts, and the supervisor holds no database connection.
PAUSED = "paused"


@dataclass(frozen=True)
class Request:
    since: str
    by: str
    #: Wait for running jobs to finish instead of cancelling them.
    drain: bool = False


@dataclass(frozen=True)
class Answer:
    pid: int
    state: str
    #: The `since` of the request this answers.
    request: str


def _write(path: Path, payload: dict[str, Any]) -> None:
    """In one step, so the other side never reads half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(partial, path)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def request(data_dir: Path, *, by: str, drain: bool = False) -> Request:
    """Ask for maintenance. A request already standing is kept as it is, so a
    second `on` does not restart a drain the supervisor has half done."""
    standing = requested(data_dir)
    if standing is not None:
        return standing
    made = Request(since=datetime.now(UTC).isoformat(), by=by, drain=drain)
    _write(data_dir / REQUEST, {"since": made.since, "by": made.by, "drain": made.drain})
    return made


def requested(data_dir: Path) -> Request | None:
    raw = _read(data_dir / REQUEST)
    if not isinstance(raw, dict) or not isinstance(raw.get("since"), str):
        return None
    return Request(since=raw["since"], by=str(raw.get("by") or ""), drain=bool(raw.get("drain")))


def lift(data_dir: Path) -> bool:
    """End maintenance. False when none was requested."""
    try:
        (data_dir / REQUEST).unlink()
    except FileNotFoundError:
        return False
    return True


def answer(data_dir: Path, state: str, standing: Request) -> None:
    _write(data_dir / ANSWER, {"pid": os.getpid(), "state": state, "request": standing.since})


def withdraw_answer(data_dir: Path) -> None:
    (data_dir / ANSWER).unlink(missing_ok=True)


def last_answer(data_dir: Path, *, alive: Callable[[int], bool]) -> Answer | None:
    """The answer on file, if the process that gave it still exists, whatever
    request it answered. `alive(pid)` decides whether a process exists."""
    raw = _read(data_dir / ANSWER)
    if not isinstance(raw, dict):
        return None
    try:
        given = Answer(pid=int(raw["pid"]), state=str(raw["state"]), request=str(raw["request"]))
    except (KeyError, TypeError, ValueError):
        return None
    return given if alive(given.pid) else None


def answered(data_dir: Path, *, alive: Callable[[int], bool]) -> Answer | None:
    """The live supervisor's answer to the standing request, or None."""
    standing = requested(data_dir)
    given = last_answer(data_dir, alive=alive)
    if standing is None or given is None or given.request != standing.since:
        return None
    return given
