"""AI task stats leave as daily figures, never as text (docs/architecture.md).

`ai_task_log` holds no prompt or output by design; the rollup adds a second
rule: a model is named only when a cloud vendor named it. A local model's name
is the user's own choice and can say anything, so it is left out.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.usage_fixtures import NOW, share
from tracker.db.models import AiTaskLog, UsageEvent
from tracker.usage_stats import rollup
from tracker.usage_stats.consent import get_sharing
from tracker.usage_stats.registry import Group

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

YESTERDAY = NOW - timedelta(days=1)


def _call(**fields) -> AiTaskLog:
    base = dict(task_type="disclosed_comp", provider="cloud_openai", availability_state="available",
                validation_result="ok", model_id="gpt-4o-mini", latency_ms=200,
                input_tokens=100, output_tokens=20, created_at=YESTERDAY)
    return AiTaskLog(**(base | fields))


async def _rows(db_session) -> list[UsageEvent]:
    stmt = select(UsageEvent).where(UsageEvent.name == "daily_ai_task").order_by(UsageEvent.id)
    return list((await db_session.execute(stmt)).scalars())


async def test_calls_become_daily_figures_and_local_model_names_stay_home(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, now=NOW - timedelta(days=3))
    db_session.add_all([
        _call(latency_ms=100), _call(latency_ms=300), _call(latency_ms=200, input_tokens=None),
        _call(provider="ollama", model_id="ada-job-search-finetune", validation_result="invalid",
              failure_class="validation"),
        _call(provider="weird provider name!", model_id="x"),
        _call(created_at=NOW - timedelta(days=5)),  # before the user shared
    ])
    await db_session.commit()
    sharing = await get_sharing(db_session)
    assert await rollup.ai_tasks(db_session, sharing=sharing, now=NOW) == 2

    by_provider = {row.props["provider"]: row for row in await _rows(db_session)}
    assert set(by_provider) == {"cloud_openai", "ollama"}
    cloud = by_provider["cloud_openai"]
    assert cloud.count == 3
    assert cloud.props == {
        "task": "disclosed_comp", "provider": "cloud_openai", "outcome": "ok", "model": "gpt-4o-mini",
        "latency_p50_ms": 200, "input_tokens": 200, "output_tokens": 60,
    }
    local = by_provider["ollama"]
    assert "model" not in local.props
    assert local.props["failure"] == "validation"
    assert "ada-job-search-finetune" not in str([row.props for row in await _rows(db_session)])


async def test_a_rollup_run_again_replaces_its_figures(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, now=NOW - timedelta(days=3))
    db_session.add(_call(latency_ms=100))
    await db_session.commit()
    sharing = await get_sharing(db_session)
    await rollup.ai_tasks(db_session, sharing=sharing, now=NOW)
    db_session.add(_call(latency_ms=500))
    await db_session.commit()
    await rollup.ai_tasks(db_session, sharing=sharing, now=NOW)
    [row] = await _rows(db_session)
    assert row.count == 2
    assert row.props["latency_p50_ms"] == 300


async def test_nothing_without_usage_shared(db_session, sharing_allowed) -> None:
    await share(db_session, Group.CRASHES, now=NOW - timedelta(days=3))
    db_session.add(_call())
    await db_session.commit()
    assert await rollup.ai_tasks(db_session, sharing=await get_sharing(db_session), now=NOW) == 0
    assert await _rows(db_session) == []
