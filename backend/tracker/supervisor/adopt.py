"""What a starting supervisor does with each run its predecessor left live.

Jobs outlive the supervisor that started them, so every start begins here: a run
whose process is still provably that run is adopted; one that ended while nobody
watched is finished from the result file its trampoline wrote; one that left no
trace is lost, and its request is queued again (`job_store.finish_run`).

Pure: the process probes and the result reader are passed in, so the tests play
every case without a process.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from tracker.db import job_store


class LiveRun(Protocol):
    id: int
    state: str
    pid: int | None
    proc_started_at: datetime | None
    cancel_requested_at: datetime | None


@dataclass(frozen=True)
class Verdict:
    #: "adopt": keep watching `pid`; "finish": end the run with `state`.
    action: str
    pid: int | None = None
    state: str | None = None
    exit_code: int | None = None
    result: dict[str, Any] | None = None


def reconcile(
    run: LiveRun,
    *,
    is_run: Callable[[int, int, datetime | None], bool],
    find_run: Callable[[int], int | None],
    read_result: Callable[[int], dict[str, Any] | None],
) -> Verdict:
    pid = run.pid
    if pid is None:
        # The supervisor died between the spawn and recording the PID: the
        # marker in the argv is the only way to find the process.
        pid = find_run(run.id)
    if pid is not None and is_run(pid, run.id, run.proc_started_at):
        return Verdict("adopt", pid=pid)
    result = read_result(run.id)
    if result is not None:
        state = job_store.RUN_CANCELLED if run.cancel_requested_at is not None else job_store.EXITED
        return Verdict("finish", state=state, exit_code=result.get("exit_code"), result=result)
    if run.state == job_store.STARTING and run.pid is None:
        return Verdict("finish", state=job_store.SPAWN_FAILED)
    return Verdict("finish", state=job_store.LOST)
