"""What every job would do now, and why: the supervisor's view of one moment.

Reads the database and the machine, writes nothing. `python -m tracker.supervisor
plan` prints it; the dispatcher acts on the same decisions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db import job_store
from tracker.db.models import JobRun
from tracker.platform.paths import BACKEND_DIR
from tracker.platform.power import read_power
from tracker.supervisor.due import Decision, Facts, Gate, World, decide
from tracker.supervisor.registry import JOBS, JobSpec

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


@dataclass(frozen=True)
class Planned:
    job: JobSpec
    key: str
    facts: Facts
    decision: Decision
    #: The structured result of the key's last finished run, if any.
    last_result: Mapping | None = None


def code_heads(ini: Path = ALEMBIC_INI) -> set[str]:
    """The schema revisions this checkout's code expects."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ini))
    config.set_main_option("script_location", str(ini.parent / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def database_revisions(session: AsyncSession) -> set[str]:
    """The revisions the database is stamped at; none for a database that was
    never migrated."""
    if await session.scalar(text("SELECT to_regclass('alembic_version')")) is None:
        return set()
    rows = await session.execute(text("SELECT version_num FROM alembic_version"))
    return {row[0] for row in rows}


async def schema_ready(session: AsyncSession, heads: set[str] | None = None) -> bool:
    """The database is at exactly the revisions the code expects. Code ahead of
    the database (a landing waiting for its migration) is not ready."""
    return await database_revisions(session) == (heads if heads is not None else code_heads())


async def read_world(session: AsyncSession, *, zone: tzinfo, gate: Gate) -> World:
    power = await asyncio.to_thread(read_power)
    return World(
        dark_wake=power.dark_wake,
        on_battery=power.on_battery,
        gate=gate,
        schema_ready=await schema_ready(session),
        zone=zone,
    )


def facts_for(
    key: str,
    now: datetime,
    latest: dict[str, JobRun],
    queues: dict[str, job_store.Queue],
    oldest_trigger: dict[str, str | None],
) -> Facts:
    last = latest.get(key)
    queue = queues.get(key)
    return Facts(
        now=now,
        live=last is not None and last.state in job_store.LIVE,
        last_started_at=last.started_at if last is not None else None,
        last_ended_at=last.ended_at if last is not None else None,
        queued=queue.count if queue is not None else 0,
        requested_for=oldest_trigger.get(key),
        deadline=deadline_of(last),
    )


#: A job that keeps its own deadline and crashed before naming one looks again after this.
DEADLINE_AFTER_FAILURE = timedelta(hours=1)


def deadline_of(last: JobRun | None) -> datetime | None:
    """When a job that names its own next run (`AtDeadline`) asked for it: the
    `next_at` its last finished run returned. One that failed without naming a
    time is tried again an hour after it ended, not left until somebody asks."""
    if last is None or last.state in job_store.LIVE or not isinstance(last.result, dict):
        return None
    named = last.result.get("next_at")
    if isinstance(named, str):
        try:
            return datetime.fromisoformat(named)
        except ValueError:
            return None
    if last.result.get("kind") == "failed" and last.ended_at is not None:
        return last.ended_at + DEADLINE_AFTER_FAILURE
    return None


def keys_of(job: JobSpec, latest: dict[str, JobRun], queues: dict[str, job_store.Queue]) -> list[str]:
    """A job's instances: its one key, or every argument it has a run or a request for."""
    if not job.per_argument:
        return [job.name]
    found = {key for key, run in latest.items() if run.job == job.name and run.state in job_store.LIVE}
    found |= {key for key, queue in queues.items() if queue.job == job.name}
    return sorted(found)


async def plan(
    session: AsyncSession,
    now: datetime,
    world: World,
    *,
    jobs: Sequence[JobSpec] = JOBS,
    changed_since: Mapping[str, datetime] | None = None,
) -> list[Planned]:
    """`changed_since`: for each key watching a fingerprint, since when it has
    differed from the accepted one."""
    latest = await job_store.latest_runs(session)
    queues = await job_store.queues(session)
    oldest_trigger = await job_store.oldest_triggers(session)
    planned: list[Planned] = []
    for job in jobs:
        for key in keys_of(job, latest, queues):
            facts = facts_for(key, now, latest, queues, oldest_trigger)
            if changed_since and key in changed_since:
                facts = replace(facts, changed_since=changed_since[key])
            last = latest.get(key)
            result = last.result if last is not None and last.state not in job_store.LIVE else None
            planned.append(
                Planned(job, key, facts, decide(job, facts, world), result if isinstance(result, dict) else None)
            )
    return planned
