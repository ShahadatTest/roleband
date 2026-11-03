"""The supervisor's own liveness: a loop that stops beating ends the process.

The service loop stamps a heartbeat on every turn, in its waits included. A
thread checks the stamp every `check_seconds` and, once it is older than
`stall_seconds` of awake time, ends the process with exit code 70; launchd then
starts a fresh supervisor, which adopts the jobs still running. Awake time, so
a machine that slept is not a stalled loop. A thread, because a stalled loop
cannot notice itself.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

from tracker.supervisor.clock import awake_seconds

logger = logging.getLogger("tracker.supervisor")

#: What the process exits with when its loop stalls (EX_SOFTWARE).
STALLED = 70


class Heartbeat:
    def __init__(
        self,
        *,
        stall_seconds: float = 120.0,
        check_seconds: float = 10.0,
        on_stall: Callable[[], object] | None = None,
        exit: Callable[[int], object] = os._exit,
        clock: Callable[[], float] = awake_seconds,
    ) -> None:
        self.stall_seconds = stall_seconds
        self.check_seconds = check_seconds
        self.on_stall = on_stall
        self._exit = exit
        self._clock = clock
        self._stamp = clock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self) -> None:
        self._stamp = self._clock()

    def start(self) -> None:
        self.beat()
        self._thread = threading.Thread(target=self._watch, name="supervisor-liveness", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=self.check_seconds + 1)

    def _watch(self) -> None:
        while not self._stopped.wait(self.check_seconds):
            silent = self._clock() - self._stamp
            if silent <= self.stall_seconds:
                continue
            logger.critical("the supervisor's loop has not beaten for %.0f s; exiting so it restarts", silent)
            if self.on_stall is not None:
                try:
                    self.on_stall()
                except Exception:  # noqa: BLE001 - exiting matters more than tidying up
                    logger.exception("could not tidy up before exiting")
            logging.shutdown()
            self._exit(STALLED)
            return
