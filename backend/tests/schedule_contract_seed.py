"""Realistic rows for the schedule contract.

Builds on the ops contract's `unscheduled` roster (`tests/ops_contract_seed.py`),
whose scheduler state already covers four of the six statuses a binding can
report, and adds the two it lacks plus the rows the route must not serve:

| company | binding | schedule row | provider | `status` |
|---|---|---|---|---|
| acme | stable | discovery on | greenhouse ready | `scheduled` |
| globex | stable | manual sync queued | greenhouse ready | `manual` |
| initech | stable | manual sync queued, discovery on | ashby backoff, cooldown ahead | `cooldown` |
| umbrella | stable | yes | lever paused | `paused` |
| hooli | stable | none | greenhouse ready | `unscheduled` |
| meta | stable | anchored in Stockholm | meta, denied by policy | `policy_denied` |
| wayne | candidate | yes | greenhouse | not served: only stable bindings are |
| dormant | stable | yes | greenhouse | not served: the company is disabled |
| piedpiper | none | none | ashby | not served: nothing to schedule |

`pin_schedule_environment` is the ops pin plus the one setting the schedule
reads that the ops contract does not: the provider parallelism, at its default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.ops_contract_seed import (
    NOW,
    PINNED_SETTINGS,
    _binding,
    _company,
    _schedule,
    pin_ops_environment,
    seed_ops_contract,
)
from tracker.config import get_settings

#: Where meta's schedule was last anchored: 08:00 discovery, 20:00 reconcile.
META_TIMEZONE = "Europe/Stockholm"


def pin_schedule_environment(monkeypatch, tmp_path) -> None:
    import tracker.api.routers.ops as ops
    import tracker.workflows.scheduler as scheduler

    pin_ops_environment(monkeypatch, tmp_path)
    settings = get_settings().model_copy(update={**PINNED_SETTINGS, "sync_scheduler_max_providers": 2})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)


@dataclass(frozen=True)
class SeededSchedule:
    bindings: dict[str, int]


async def seed_schedule_contract(session: AsyncSession) -> SeededSchedule:
    seeded = await seed_ops_contract(session, roster="unscheduled")
    session.add_all([_company("meta", "Meta", "meta"), _company("wayne", "Wayne", "greenhouse")])
    await session.flush()

    meta = _binding("meta", "meta")
    wayne = _binding("wayne", "greenhouse")
    wayne.status = "candidate"
    session.add_all([meta, wayne])
    await session.flush()

    anchored = _schedule(meta.id, "meta", last_reconcile=NOW - timedelta(hours=16),
                         next_reconcile=NOW + timedelta(hours=8), discovery=True)
    anchored.discovery_anchor_minute = 8 * 60
    anchored.reconcile_anchor_minute = 20 * 60
    anchored.schedule_timezone = META_TIMEZONE
    session.add_all(
        [
            anchored,
            _schedule(wayne.id, "greenhouse", last_reconcile=None,
                      next_reconcile=NOW + timedelta(hours=3), discovery=False),
        ]
    )
    await session.commit()
    return SeededSchedule(bindings={**seeded.bindings, "meta": meta.id, "wayne": wayne.id})
