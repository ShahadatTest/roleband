"""A new schedule row follows the binding's last full read.

`scheduler._ensure_state` seeds a binding's first `SyncScheduleState` from the
binding's own runs: the newest reconcile that read
the whole board (`ok` or `empty`). Each plausible wrong reading fails a case:
the newest run of any kind (a later failure), a discovery probe, another
binding's run, or no read at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tracker.config import get_settings
from tracker.db.models import (
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.workflows import scheduler

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


async def _company(session, slug: str, binding_id: int) -> None:
    session.add(TrackedCompany(slug=slug, display=slug.title(), adapter="greenhouse",
                               board_token=slug, status="active", enabled=True, visible=True,
                               source="catalog"))
    await session.flush()
    session.add(SourceBinding(id=binding_id, company_slug=slug, connector_kind="adapter",
                              connector_id="greenhouse", status="stable",
                              closure_capability="authoritative"))
    await session.flush()


async def _run(session, run_id: int, binding_id: int, slug: str, outcome: str, ago: timedelta,
               *, mode: str = "reconcile") -> None:
    session.add(ScrapeRun(id=run_id, started_at=NOW - ago, status="ok"))
    await session.flush()
    session.add(ScrapeSourceRun(
        run_id=run_id, binding_id=binding_id, company_slug=slug, provider_key="greenhouse",
        scan_mode=mode, outcome=outcome, started_at=NOW - ago, finished_at=NOW - ago,
        scanned=10, errors=[], drift=[],
    ))
    await session.flush()


async def test_a_first_schedule_row_follows_the_last_full_read(db_session):
    await _company(db_session, "readco", 901)
    await _company(db_session, "emptyco", 902)
    await _company(db_session, "newco", 903)
    # readco: read in full 30 h ago; a newer failure and a newer discovery
    # probe are not full reads of the board.
    await _run(db_session, 9001, 901, "readco", "ok", timedelta(hours=30))
    await _run(db_session, 9002, 901, "readco", "failed", timedelta(hours=2))
    await _run(db_session, 9003, 901, "readco", "ok", timedelta(hours=1), mode="discovery")
    # emptyco: a board proven empty was read in full too.
    await _run(db_session, 9004, 902, "emptyco", "empty", timedelta(hours=10))
    await db_session.commit()

    settings = get_settings()
    await scheduler._ensure_state(db_session, NOW, settings)
    await db_session.flush()
    states = {
        row.binding_id: row
        for row in (await db_session.scalars(
            select(SyncScheduleState).where(SyncScheduleState.binding_id.in_((901, 902, 903)))
        )).all()
    }
    cadence = timedelta(seconds=settings.sync_reconcile_cadence_seconds)

    assert states[901].last_reconcile_at == NOW - timedelta(hours=30)
    assert states[901].next_reconcile_at == NOW - timedelta(hours=30) + cadence
    assert states[902].last_reconcile_at == NOW - timedelta(hours=10)
    # Never read: due now, the first scan of a company just followed.
    assert (states[903].last_reconcile_at, states[903].next_reconcile_at) == (None, NOW)


async def test_an_existing_schedule_row_is_never_reseeded(db_session):
    await _company(db_session, "readco", 901)
    await _run(db_session, 9001, 901, "readco", "ok", timedelta(hours=30))
    db_session.add(SyncScheduleState(
        binding_id=901, provider_key="greenhouse", last_reconcile_at=NOW - timedelta(hours=5),
        next_discovery_at=NOW + timedelta(hours=1), next_reconcile_at=NOW + timedelta(hours=19),
    ))
    await db_session.commit()

    await scheduler._ensure_state(db_session, NOW, get_settings())
    await db_session.flush()
    state = (await db_session.scalars(
        select(SyncScheduleState).where(SyncScheduleState.binding_id == 901)
    )).one()
    assert (state.last_reconcile_at, state.next_reconcile_at) == (
        NOW - timedelta(hours=5), NOW + timedelta(hours=19),
    )
