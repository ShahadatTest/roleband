"""The supervisor as a long-running service: hold the lock, adopt, then loop.

It wakes the moment a request or a cancel is committed (LISTEN on the store's
channel) and otherwise every `idle_seconds`, or every `busy_seconds` while a job
runs, so an end is recorded promptly. The poll never depends on the listener:
a dropped listening connection only delays a start until the next full look,
and is reopened.

A full look (`Dispatcher.tick`) reads the machine, plans, starts and publishes.
A busy turn that only timed out records what ended and begins the stops that
are due (`Dispatcher.settle`), and follows with a full look only when a run
ended or a stop began. A notification, a sleep, a change in what the supervisor
publishes beside the plan, and `idle_seconds` since the last full look each
make the next look a full one.

A stop (SIGTERM from launchd) ends the loop and leaves running jobs running:
they are their own sessions, and the next supervisor adopts them. Maintenance
(`maintenance.py`) is the other way out of the loop: the running jobs are stopped
or waited for, every connection is let go, and the supervisor waits, touching
nothing, until it is lifted.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

import asyncpg
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tracker.db import job_store
from tracker.supervisor import activation, logs, maintenance, singleton
from tracker.supervisor.activation import Watcher
from tracker.supervisor.api import ApiService
from tracker.supervisor.clock import SleepDetector, awake_seconds
from tracker.supervisor.dispatch import Dispatcher

logger = logging.getLogger("tracker.supervisor")


def asyncpg_arguments(url: URL) -> dict:
    """asyncpg connection arguments for a SQLAlchemy URL, including the embedded
    server's socket directory, which travels in the URL's query."""
    arguments: dict = {
        "user": url.username,
        "password": url.password,
        "database": url.database,
        "port": url.port,
    }
    host = url.query.get("host") or url.host
    if isinstance(host, tuple):
        host = host[0]
    if host:
        arguments["host"] = host
    return {key: value for key, value in arguments.items() if value is not None}


class Listener:
    """A LISTEN connection that sets `wake` on every notification."""

    def __init__(self, url: URL, wake: asyncio.Event) -> None:
        self._url = url
        self._wake = wake
        self._connection: asyncpg.Connection | None = None

    async def ensure(self) -> None:
        if self._connection is not None and not self._connection.is_closed():
            return
        try:
            self._connection = await asyncpg.connect(**asyncpg_arguments(self._url))
            await self._connection.add_listener(job_store.CHANNEL, lambda *_args: self._wake.set())
        except (OSError, asyncpg.PostgresError) as error:
            self._connection = None
            logger.warning("not listening for requests (polling instead): %s", error)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed():
            await self._connection.close()
        self._connection = None


async def serve(
    dispatcher: Dispatcher,
    engine: AsyncEngine,
    stop: asyncio.Event,
    *,
    idle_seconds: float = 30.0,
    busy_seconds: float = 1.0,
    lock_retry_seconds: float = 60.0,
    pause_poll_seconds: float = 1.0,
    rotate: Iterable[Path] = (),
    recover: Callable[[], str | None] | None = None,
    recover_every_seconds: float = 60.0,
    api: ApiService | None = None,
    watcher: Watcher | None = None,
    reexec: Callable[[], None] | None = None,
    beat: Callable[[], None] = lambda: None,
) -> None:
    """`recover` brings a database back that cannot be reached; it runs here, in
    the supervisor, because with the database down no job can even be recorded."""
    data_dir = dispatcher.data_dir
    last_recovery: float | None = None
    if api is not None:
        dispatcher.status_sources.append(api.status)
    if watcher is not None:
        dispatcher.held = lambda: watcher.held

    async def recovered(error: BaseException) -> bool:
        nonlocal last_recovery
        if recover is None or not _unreachable(error):
            return False
        now = awake_seconds()
        if last_recovery is not None and now - last_recovery < recover_every_seconds:
            return False
        last_recovery = now
        logger.warning("database unreachable (%s); bringing it back", error)
        failure = await asyncio.to_thread(recover)
        if failure:
            logger.error("database recovery failed: %s", failure)
        return failure is None

    async def take_lock() -> AsyncConnection | None:
        while True:
            beat()
            try:
                held = await singleton.hold(engine)
                break
            except Exception as error:  # noqa: BLE001 - a database that is down is waited out
                await recovered(error)
                if await _wait(stop, idle_seconds):
                    return None
        while held is None:
            beat()
            logger.warning(
                "another supervisor holds this database (backend pid %s); not dispatching",
                await singleton.holder(engine),
            )
            if await _wait(stop, lock_retry_seconds):
                return None
            held = await singleton.hold(engine)
        return held

    while not stop.is_set():
        # Before any contact with the database: a supervisor that starts during a
        # restore must not be the client that recreates an empty one.
        await _pause(data_dir, stop, pause_poll_seconds, beat)
        if stop.is_set():
            return
        held = await take_lock()
        if held is None:
            return
        wake = asyncio.Event()
        listener = Listener(engine.url, wake)
        ended: str | None = None
        try:
            try:
                adopted = await dispatcher.adopt()
            except Exception as error:  # noqa: BLE001 - e.g. a database behind this code
                if not await recovered(error):
                    logger.error("cannot read the job tables (is the database migrated?): %s", error)
            else:
                for run_id, verdict in adopted:
                    logger.info("run %s left by a previous supervisor: %s", run_id, verdict.action)
                ended = await _supervise(
                    dispatcher, stop, wake, listener, recovered, data_dir=data_dir,
                    idle_seconds=idle_seconds, busy_seconds=busy_seconds, rotate=tuple(rotate),
                    api=api, watcher=watcher, beat=beat,
                )
        finally:
            if api is not None:
                # The API serves only while this supervisor dispatches: not in
                # maintenance, not beside another supervisor, not across a re-exec.
                await api.stop(grace_seconds=10.0 if ended in (None, STOPPED) else 30.0)
            await listener.close()
            await singleton.release(held)
        if ended is None:
            # A crash loop under launchd would help nobody: wait, then look again.
            beat()
            if await _wait(stop, idle_seconds):
                return
            continue
        if ended == STOPPED:
            return
        # Let go of every pooled connection: the database may be swapped next,
        # and an exec must not carry a half-used pool.
        await engine.dispose()
        if ended == REEXEC:
            logger.info("restarting on the landed code")
            if reexec is not None:
                reexec()
            return
        logger.info("in maintenance: holding no connection, starting nothing")


#: How `_supervise` ended.
STOPPED = "stopped"
MAINTENANCE = "maintenance"
REEXEC = "reexec"


async def _supervise(
    dispatcher: Dispatcher,
    stop: asyncio.Event,
    wake: asyncio.Event,
    listener: Listener,
    recovered: Callable[[BaseException], Awaitable[bool]],
    *,
    data_dir: Path,
    idle_seconds: float,
    busy_seconds: float,
    rotate: tuple[Path, ...],
    api: ApiService | None,
    watcher: Watcher | None,
    beat: Callable[[], None],
) -> str:
    """Look until stopped, until maintenance has drained every run, or until
    landed code is ready to run (the re-exec happens between looks, never inside
    a claim)."""
    sleeps = SleepDetector()
    full = True
    full_at: float | None = None
    shown: list[object] | None = None
    while not stop.is_set():
        beat()
        await listener.ensure()
        # Read before the clear: a notification that lands during this turn's
        # work sets it again, and ends the wait at once.
        full = full or wake.is_set()
        wake.clear()
        slept = sleeps.slept()
        if slept:
            logger.info("the machine slept %.0f s", slept)
            full = True
        standing = maintenance.requested(data_dir)
        try:
            if standing is None:
                if api is not None:
                    await api.tend(awake_seconds())
                if watcher is not None:
                    step = await watcher.look(awake_seconds())
                    if step.action == activation.RESTART:
                        return REEXEC
                    if step.action == activation.RESTART_API and api is not None:
                        logger.info("a new dashboard is built; restarting the API to serve it")
                        await api.stop()
                beside = _beside(dispatcher)
                began = awake_seconds()
                full = full or beside != shown or full_at is None or began - full_at >= idle_seconds
                if full or await dispatcher.settle():
                    # Stays set if the look fails, so the next turn tries it again.
                    full = True
                    await dispatcher.tick()
                    full, full_at, shown = False, began, beside
            else:
                full = True
                if await _drained(dispatcher, standing, data_dir):
                    return MAINTENANCE
        except Exception as error:  # noqa: BLE001 - one bad look never ends supervision
            if not await recovered(error):
                logger.exception("tick failed")
        for path in rotate:
            logs.rotate(path)
        if api is not None:
            logs.rotate(api.log)
        for watched in dispatcher.watched.values():
            if logs.rotate(watched.launched.log_path):
                await _log_rotated(dispatcher, watched.launched.log_path)
        busy = (
            dispatcher.watched or standing is not None
            or (api is not None and api.state != "running")
            or (watcher is not None and watcher.building)
        )
        if not busy:
            full = True
        await _first(stop, wake, busy_seconds if busy else idle_seconds)
    return STOPPED


def _beside(dispatcher: Dispatcher) -> list[object]:
    """What the dispatcher publishes or plans from beside the jobs' own facts:
    the API's row, why landed code is held, whether its dependencies are in."""
    return [
        *(source() for source in dispatcher.status_sources),
        dispatcher.held() if dispatcher.held is not None else None,
        dispatcher.dependencies_ready,
    ]


async def _log_rotated(dispatcher: Dispatcher, path: Path) -> None:
    try:
        async with dispatcher.factory() as session:
            await job_store.mark_log_rotated(session, str(path))
            await session.commit()
    except Exception as error:  # noqa: BLE001 - a run that keeps a stale offset is no reason to stop
        logger.warning("could not mark the runs logged in %s as rotated: %s", path, error)


async def _drained(dispatcher: Dispatcher, standing: maintenance.Request, data_dir: Path) -> bool:
    """One look of a drain: ask the runs to stop (once), record what ended.
    True once nothing runs, with every job published as paused."""
    answered = maintenance.answered(data_dir, alive=lambda pid: pid == os.getpid())
    if answered is None:
        maintenance.answer(data_dir, maintenance.DRAINING, standing)
        logger.info("maintenance asked by %s: %s the running jobs", standing.by,
                    "waiting for" if standing.drain else "stopping")
        await dispatcher.drain(cancel=not standing.drain)
    await dispatcher.settle()
    if dispatcher.watched:
        return False
    await dispatcher.publish_paused()
    return True


async def _pause(data_dir: Path, stop: asyncio.Event, poll_seconds: float, beat: Callable[[], None]) -> None:
    """While maintenance stands: say so, and wait for it to be lifted."""
    standing = maintenance.requested(data_dir)
    answered: str | None = None
    while standing is not None and not stop.is_set():
        beat()
        if answered != standing.since:
            maintenance.answer(data_dir, maintenance.PAUSED, standing)
            answered = standing.since
        if await _wait(stop, poll_seconds):
            break
        standing = maintenance.requested(data_dir)
    if answered is not None:
        maintenance.withdraw_answer(data_dir)
        logger.info("maintenance lifted: resuming")


def _unreachable(error: BaseException) -> bool:
    """A failure to reach the database, as opposed to a bug in a query."""
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

    if isinstance(error, (OSError, OperationalError, InterfaceError)):
        return True
    return isinstance(error, DBAPIError) and bool(getattr(error, "connection_invalidated", False))


async def _wait(event: asyncio.Event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


async def _first(stop: asyncio.Event, wake: asyncio.Event, seconds: float) -> None:
    waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(wake.wait())]
    try:
        await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
