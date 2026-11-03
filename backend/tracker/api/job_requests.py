"""How the API asks the supervisor for background work other than scans.

The directory and discovery requests are rung in the caller's transaction
(`tracker.db.job_store`), which the route commits with its own change. The
re-embed's ring and stop commit themselves: they are the tier switch's process
steps, which `semantic.matching` orders after its own commit. Scans have their
own module (`scan_requests.py`), because Sync's Cancel needs them told apart.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db import job_store
from tracker.db.models import JobRequest, JobRun

DIRECTORY = "directory"
ROLE_DISCOVERY = "role_discovery"


async def ring_directory(session: AsyncSession, *, requested_by: str) -> None:
    """Read the directory now, not at the next ten-minute look. A sweep already
    running takes the change at its next pass; the request then waits for it."""
    await job_store.ring(session, DIRECTORY, requested_by=requested_by)


def pending_clause(job: str) -> ColumnElement[bool]:
    """A request for `job` is queued or one of its runs is live."""
    queued = exists().where(JobRequest.job == job, JobRequest.state == job_store.QUEUED)
    return queued | exists().where(JobRun.job == job, JobRun.state.in_(job_store.LIVE))


async def pending(session: AsyncSession, job: str) -> bool:
    return bool(await session.scalar(select(pending_clause(job))))


def role_discovery_argv(
    companies: str | list[str] | None = None,
    *,
    max_list: int = 600,
    locations: list[str] | None = None,
) -> list[str]:
    """The arguments of a discovery run, as `tracker.discover_roles` takes them."""
    company_args = [companies] if isinstance(companies, str) else companies
    args: list[str] = []
    if company_args:
        args.extend(["--company", *company_args])
    args.extend(["--max-list", str(max_list), "-v"])
    if locations:
        args.extend(["--location", *locations])
    return args


async def ring_role_discovery(
    session: AsyncSession,
    companies: str | list[str] | None = None,
    *,
    max_list: int = 150,
    locations: list[str] | None = None,
    requested_by: str,
) -> bool:
    """Ask for a capped list-only scope inventory refresh. False when one is
    already queued or running, which takes this request's place.

    The guard is the point: every trigger (the Settings "refresh scope" button,
    adding a company) would otherwise queue a scan of every source behind the
    last. The DB advisory lock does not contain them: discovery releases it
    between companies so a waiting scrape can slip in."""
    if await pending(session, ROLE_DISCOVERY):
        return False
    argv = role_discovery_argv(companies, max_list=max_list, locations=locations)
    await job_store.ring(session, ROLE_DISCOVERY, requested_by=requested_by, args={"argv": argv})
    return True


REEMBED = "reembed"

#: "Stop and go back" restores the tier only once the re-embed has stopped; it
#: waits this long for the supervisor to end the run, then says it could not.
REEMBED_STOP_WAIT_SECONDS = 30.0


async def ring_reembed(session: AsyncSession, *, requested_by: str) -> bool:
    """Ask for the corpus re-embed now. Commits: the switch that asks has
    already committed its choice, and the supervisor acts only on what is
    committed. False when one is already queued or running."""
    if await pending(session, REEMBED):
        return False
    await job_store.ring(session, REEMBED, requested_by=requested_by)
    await session.commit()
    return True


async def stop_reembed(
    session: AsyncSession, *, wait_seconds: float | None = None, poll_seconds: float = 0.1
) -> tuple[str, int | None]:
    """Stop the re-embed the supervisor runs, and wait until it has stopped.

    "stopped" once nothing of ours is queued or live; "error" when the run is
    still live at the deadline (the tier must then stay where it is);
    "not_running" when nothing of ours was there to stop. The second value is
    the stopped run's process group, if there was one."""
    cancelled = await job_store.cancel_queued(session, key=REEMBED)
    run = await session.scalar(
        select(JobRun).where(JobRun.key == REEMBED, JobRun.state.in_(job_store.LIVE)).limit(1)
    )
    if run is None:
        await session.commit()
        return ("stopped" if cancelled else "not_running"), None
    await job_store.request_cancel(session, run.id, reason="tier_stop")
    await session.commit()
    deadline = time.monotonic() + (REEMBED_STOP_WAIT_SECONDS if wait_seconds is None else wait_seconds)
    while True:
        await session.refresh(run)
        if run.state not in job_store.LIVE:
            return "stopped", run.pgid
        if time.monotonic() >= deadline:
            return "error", run.pgid
        await asyncio.sleep(poll_seconds)


PRICES = "prices"


async def ring_prices(session: AsyncSession, *, requested_by: str) -> None:
    """Ask for a price refresh, in the caller's transaction."""
    await job_store.ring(session, PRICES, requested_by=requested_by)


async def stop_prices(session: AsyncSession) -> None:
    """Cancel the queued and running price work, and commit: a replaced or
    removed key spends nothing more. The run's own lock lets go when it ends."""
    await job_store.cancel_queued(session, key=PRICES)
    run = await session.scalar(
        select(JobRun).where(JobRun.key == PRICES, JobRun.state.in_(job_store.LIVE)).limit(1)
    )
    if run is not None:
        await job_store.request_cancel(session, run.id, reason="key_changed")
    await session.commit()
