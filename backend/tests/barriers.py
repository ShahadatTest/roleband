"""Barriers for race tests between two database sessions.

A race test holds one transaction open, starts a second writer beside it, and
must know where the second stands before it releases the first: queued on a
lock, or already finished. A fixed sleep only guesses. On a loaded host the
second may not have reached its read when the window ends, so it reads the
first's committed row and the test passes with the lock removed. These wait on
Postgres's own lock queue instead.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

#: A lock some backend on this test process's scratch database is waiting for.
#: `pg_locks` covers the whole cluster and parallel workers share it, so the
#: join to `pg_stat_activity` keeps their waits out. Both views are read once
#: per transaction, so every poll runs in a fresh one.
_WAITING = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
    " WHERE NOT l.granted AND a.datname = current_database()"
    " AND (CAST(:pid AS integer) IS NULL OR l.pid = CAST(:pid AS integer)))"
)


async def until_waiting(
    engine: AsyncEngine, task: asyncio.Future[Any], *, pid: int | None = None, timeout: float = 10.0
) -> None:
    """Return once `task` has finished or a session waits for a lock.

    `pid` narrows the wait to one backend; without it any session on the
    scratch database counts, which is the second writer when the test holds
    every other session idle. A test whose contract is that the second writer
    waits asserts `not task.done()` after this returns. Raises TimeoutError
    when neither happens, so a writer stuck elsewhere fails instead of passing.
    """
    async with asyncio.timeout(timeout), engine.connect() as conn:
        while not task.done():
            waiting = await conn.scalar(_WAITING, {"pid": pid})
            await conn.rollback()
            if waiting:
                return
            await asyncio.sleep(0.01)
