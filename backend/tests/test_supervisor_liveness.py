"""A supervisor whose loop stops beating ends itself, so launchd restarts it;
one that keeps beating, or slept, is left alone."""

from __future__ import annotations

import time

from tracker.supervisor.liveness import STALLED, Heartbeat


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _wait_for(check, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return check()


def test_a_loop_that_stops_beating_ends_the_process_with_its_own_code():
    exits: list[int] = []
    tidied: list[bool] = []
    clock = Clock()
    heartbeat = Heartbeat(stall_seconds=5, check_seconds=0.01, exit=exits.append,
                          on_stall=lambda: tidied.append(True), clock=clock)
    heartbeat.start()
    try:
        clock.now = 4
        time.sleep(0.05)
        assert exits == [], "not yet past the stall bound"
        clock.now = 6
        assert _wait_for(lambda: exits == [STALLED])
        assert tidied == [True], "the API child is asked to stop first"
    finally:
        heartbeat.stop()


def test_a_loop_that_keeps_beating_is_left_alone():
    exits: list[int] = []
    clock = Clock()
    heartbeat = Heartbeat(stall_seconds=5, check_seconds=0.01, exit=exits.append, clock=clock)
    heartbeat.start()
    try:
        for step in range(1, 20):
            clock.now = step * 2
            heartbeat.beat()
            time.sleep(0.01)
        assert exits == []
    finally:
        heartbeat.stop()
