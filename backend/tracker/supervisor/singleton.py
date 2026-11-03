"""One supervisor per database.

Worktrees and second checkouts share the database but not their `data/`
directories, so a file lock cannot keep two supervisors apart. A session advisory
lock can: it lives as long as the connection that took it, and the OS closes that
connection when the process dies, so a crashed supervisor never leaves it behind.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: Next to the run and relationship locks (91237 to 91246).
SUPERVISOR_LOCK_KEY = 91247


async def hold(engine: AsyncEngine) -> AsyncConnection | None:
    """A connection holding the supervisor lock, or None when another process
    holds it. Keep the connection open for as long as the supervisor runs."""
    connection = await engine.connect()
    try:
        held = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": SUPERVISOR_LOCK_KEY}
        )
        # The lock is the session's; ending the implicit transaction keeps it.
        await connection.commit()
    except BaseException:
        await connection.close()
        raise
    if not held:
        await connection.close()
        return None
    return connection


async def release(connection: AsyncConnection) -> None:
    """Give the lock up. Closing alone would not: a pooled connection returns to
    the pool with its session, and the session keeps the lock."""
    try:
        await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SUPERVISOR_LOCK_KEY})
        await connection.commit()
    finally:
        await connection.close()


async def holder(engine: AsyncEngine) -> int | None:
    """The backend PID of the session holding the lock, for "who is dispatching".

    Advisory locks belong to a database: a supervisor of another database on the
    same server holds its own, and is not this database's."""
    async with engine.connect() as connection:
        return await connection.scalar(
            text(
                "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted"
                " AND classid = 0 AND objid = :key AND objsubid = 1"
                " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            ),
            {"key": SUPERVISOR_LOCK_KEY},
        )
