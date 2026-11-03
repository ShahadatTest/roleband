"""Detached liveness heartbeat: run an async tick on an interval, forever.

The loop owns the cadence and failure policy; the caller owns what a beat
does. Cancel the task to stop. One missed beat is harmless, but a beat that
fails every time leaves a live run looking dead to every liveness guard, so
the first failure of a streak, and every `WARN_EVERY`th after it, is a warning
with its traceback, and the beat that ends the streak says so.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

#: A streak of failed beats warns on its first and then on every this-many.
WARN_EVERY = 10


async def heartbeat_loop(
    tick: Callable[[], Awaitable[None]],
    interval_seconds: int,
    *,
    log_name: str = "heartbeat",
) -> None:
    """Await ``tick()`` every ``interval_seconds`` until cancelled.

    A failing tick never kills the loop — when the process dies the beats
    simply stop, which is exactly the signal liveness guards watch for.
    """
    failed = 0
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a missed beat is harmless; keep beating
            failed += 1
            if failed % WARN_EVERY == 1:
                logger.warning("%s tick failed (%d in a row)", log_name, failed, exc_info=True)
            else:
                logger.debug("%s tick failed (%d in a row)", log_name, failed, exc_info=True)
        else:
            if failed:
                logger.info("%s beating again after %d failed ticks", log_name, failed)
            failed = 0
