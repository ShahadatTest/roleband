"""A restarted supervisor adopts what is still running and settles the rest.

The negative controls matter most: a recycled PID must not be adopted, and a run
that ended while nobody watched must be finished from its own result, not
replayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from tracker.db import job_store
from tracker.supervisor.adopt import reconcile

BEGAN = datetime(2026, 10, 19, 5, 1, 18, tzinfo=UTC)


@dataclass
class Run:
    id: int = 7
    state: str = job_store.RUNNING
    pid: int | None = 4242
    proc_started_at: datetime | None = BEGAN
    cancel_requested_at: datetime | None = None


def _verdict(run: Run, *, alive: set[tuple[int, int]] = frozenset(), marker: dict | None = None, results=None):
    return reconcile(
        run,
        is_run=lambda pid, run_id, began: (pid, run_id) in alive and began == run.proc_started_at,
        find_run=lambda run_id: (marker or {}).get(run_id),
        read_result=lambda run_id: (results or {}).get(run_id),
    )


def test_a_run_whose_process_is_still_that_run_is_adopted():
    verdict = _verdict(Run(), alive={(4242, 7)})
    assert (verdict.action, verdict.pid) == ("adopt", 4242)


def test_a_recycled_pid_is_not_adopted_and_the_run_is_lost():
    verdict = _verdict(Run(), alive={(4242, 8)})
    assert (verdict.action, verdict.state) == ("finish", job_store.LOST)


def test_a_run_that_ended_unwatched_is_finished_from_its_result():
    verdict = _verdict(Run(), results={7: {"exit_code": 3}})
    assert (verdict.action, verdict.state, verdict.exit_code) == ("finish", job_store.EXITED, 3)


def test_a_cancelled_run_that_ended_unwatched_is_finished_as_cancelled():
    run = Run(cancel_requested_at=BEGAN)
    verdict = _verdict(run, results={7: {"exit_code": -15}})
    assert (verdict.state, verdict.exit_code) == (job_store.RUN_CANCELLED, -15)


def test_a_run_whose_pid_was_never_recorded_is_found_by_its_marker():
    run = Run(state=job_store.STARTING, pid=None, proc_started_at=None)
    verdict = _verdict(run, alive={(5150, 7)}, marker={7: 5150})
    assert (verdict.action, verdict.pid) == ("adopt", 5150)


def test_a_claim_that_never_became_a_process_is_a_failed_spawn():
    run = Run(state=job_store.STARTING, pid=None, proc_started_at=None)
    assert _verdict(run).state == job_store.SPAWN_FAILED


def test_a_running_run_that_left_no_trace_is_lost():
    assert _verdict(Run()).state == job_store.LOST
