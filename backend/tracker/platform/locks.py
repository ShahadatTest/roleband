"""Cross-process mutual exclusion: ``fcntl.flock`` file lock + Postgres
advisory-lock helpers.

The flock is the primary guard against two pipeline runs overlapping (a
scheduled run racing a watchdog catch-up, or a manual CLI). The OS releases an
``flock`` automatically when the holding process dies, so a crashed or hung run
never leaves a stale lock behind — no timestamp/pid cleanup needed.

The advisory helpers provide session-scoped run exclusion and
transaction-scoped read-modify-write serialization across processes sharing
one database.
"""

from __future__ import annotations

import asyncio
import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class AlreadyRunning(RuntimeError):
    """Raised when the lock is already held by another live process."""


@contextmanager
def run_lock(path: str | Path) -> Iterator[None]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")  # noqa: SIM115 - held open for the lock's lifetime
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AlreadyRunning(f"run lock held: {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


async def try_advisory_lock(
    session,
    key: int,
    *,
    wait_seconds: float = 0.0,
    retry_seconds: float = 0.5,
) -> bool:
    """Try to take a Postgres advisory lock, wait-retrying up to
    ``wait_seconds``. Returns True if acquired, False on timeout.

    The lock is tied to the session's connection; release with
    :func:`advisory_unlock` on the same session before returning the
    connection to the pool.
    """
    waited = 0.0
    while True:
        locked = await session.scalar(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
        )
        if locked or waited >= wait_seconds:
            return bool(locked)
        await asyncio.sleep(retry_seconds)
        waited += retry_seconds


async def advisory_unlock(session, key: int) -> None:
    await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})


async def take_dedicated_advisory_lock(
    engine: AsyncEngine,
    key: int,
    *,
    wait_seconds: float = 0.0,
    retry_seconds: float = 0.5,
) -> AsyncConnection | None:
    """Take a session-level advisory lock on a connection of its own, and
    return that connection (None when the lock stayed taken by someone else).

    A session-level lock belongs to one connection, and a pooled connection is
    reset with a rollback, which does not release it. Held on a session that
    also does the work, the lock is lost to the pool two ways: a commit hands
    the session a different connection, so the final unlock runs where nothing
    is held; and a cancellation can catch the connection mid-query, so the
    unlock fails. Either way the next run cannot take the lock. A connection
    that runs nothing else has neither problem. Release it with
    :func:`release_dedicated_advisory_lock`."""
    connection = await engine.connect()
    try:
        if await try_advisory_lock(
            connection, key, wait_seconds=wait_seconds, retry_seconds=retry_seconds
        ):
            return connection
    except BaseException:
        await connection.invalidate()
        raise
    await connection.close()
    return None


async def release_dedicated_advisory_lock(connection: AsyncConnection, key: int) -> None:
    """Release a lock from :func:`take_dedicated_advisory_lock` and give its
    connection back. If the unlock fails, the connection is invalidated, not
    pooled: closing it is what frees the lock then."""
    try:
        await advisory_unlock(connection, key)
    except BaseException:
        await connection.invalidate()
        raise
    await connection.close()


async def advisory_lock_held(session, key: int) -> bool:
    """Whether anyone in this database holds the single-int advisory lock `key`.

    Read from `pg_locks`, never by taking the lock: a probe that acquired it,
    even for an instant, could make the real holder's own attempt fail. A
    bigint key is split across `classid` (high 32 bits) and `objid` (low), and
    `objsubid` 1 marks the single-int form."""
    held = await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
            " AND objsubid = 1 AND ((classid::bigint << 32) | objid::bigint) = :k"
            " AND database = (SELECT oid FROM pg_database WHERE datname = current_database()))"
        ),
        {"k": key},
    )
    return bool(held)


async def advisory_xact_lock(session, key: int) -> None:
    """Serialize a short DB mutation until its transaction ends.

    Unlike the session-scoped run lock, this releases automatically on commit
    or rollback. Use it for read-modify-write state packed into one JSON row,
    where row locking cannot safely cover the row-not-created-yet case.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


async def advisory_xact_lock_shared(session, key: int) -> None:
    """`advisory_xact_lock` in shared mode: shared holders run together, and
    the exclusive lock waits until every one of them has ended its transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": key})


async def advisory_xact_lock_pair(session, namespace: int, key: int) -> None:
    """`advisory_xact_lock` keyed by (namespace, key): PostgreSQL's two-int
    form, a key space apart from the single-int one, so a row id used as `key`
    can never meet the run or relationship locks (91237..91243) that a bare
    id equal to one of them would."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": namespace, "k": key}
    )
