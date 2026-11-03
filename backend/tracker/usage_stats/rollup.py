"""Day rows the flush writes before it sends: scan health and the heartbeat.

Scan health is rolled up from `scrape_source_runs`, the per-source audit the
pipeline already keeps: per completed UTC day, how many sources of each job-site
family ended in each outcome. A provider key becomes its family or
`single_company` (`registry.family_of`), so no employer is named. Days before
the user shared usage are never rolled up: what is sent describes the time
after the answer. The last `ROLLUP_DAYS` completed days are recomputed every
flush, which is idempotent (`outbox.set_count` leaves a sent row as sent), so a
machine that was off for a few days still reports them.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AiTaskLog, ScrapeSourceRun
from tracker.usage_stats import facts, recorder
from tracker.usage_stats.consent import Sharing
from tracker.usage_stats.registry import CATALOGUE, IDENTIFIER, OUTCOMES, Group, family_of

ROLLUP_DAYS = 7


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def scan_health(session: AsyncSession, *, sharing: Sharing, now: datetime) -> int:
    """Roll up completed days since the user shared usage. Returns rows written."""
    decided = sharing.decided_at(Group.USAGE)
    if decided is None or not sharing.shared(Group.USAGE):
        return 0
    today = now.date()
    first = max(today - timedelta(days=ROLLUP_DAYS), decided.astimezone(UTC).date())
    written = 0
    day = first
    while day < today:
        start, end = _day_bounds(day)
        rows = await session.execute(
            select(ScrapeSourceRun.provider_key, ScrapeSourceRun.outcome, func.count())
            .where(ScrapeSourceRun.finished_at >= start, ScrapeSourceRun.finished_at < end)
            .group_by(ScrapeSourceRun.provider_key, ScrapeSourceRun.outcome)
        )
        totals: Counter[tuple[str, str]] = Counter()
        for provider_key, outcome, count in rows:
            if OUTCOMES.accepts(outcome):
                totals[(family_of(provider_key), outcome)] += int(count)
        for (family, outcome), count in sorted(totals.items()):
            if await recorder.record_total(
                session,
                "daily_scan_health",
                {"family": family, "outcome": outcome},
                day=day,
                count=count,
                now=now,
                sharing=sharing,
            ):
                written += 1
        day += timedelta(days=1)
    return written


#: Providers whose model ids are a vendor's (never a name the user gave a local model).
_CLOUD_PREFIX = "cloud_"


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and IDENTIFIER.accepts(value) else None


async def ai_tasks(session: AsyncSession, *, sharing: Sharing, now: datetime) -> int:
    """Roll up `ai_task_log` per completed day since the user shared usage: per
    task, provider, outcome, failure class and (cloud only) model, the number
    of calls, their median latency and their token totals. The log holds no
    prompt or output (`intelligence_runtime/telemetry.py`); a value that is not
    a code identifier is left out rather than sent."""
    decided = sharing.decided_at(Group.USAGE)
    if decided is None or not sharing.shared(Group.USAGE):
        return 0
    today = now.date()
    day = max(today - timedelta(days=ROLLUP_DAYS), decided.astimezone(UTC).date())
    written = 0
    while day < today:
        start, end = _day_bounds(day)
        rows = await session.execute(
            select(
                AiTaskLog.task_type,
                AiTaskLog.provider,
                AiTaskLog.validation_result,
                AiTaskLog.failure_class,
                AiTaskLog.model_id,
                func.count(),
                func.percentile_cont(0.5).within_group(AiTaskLog.latency_ms),
                func.sum(AiTaskLog.input_tokens),
                func.sum(AiTaskLog.output_tokens),
            )
            .where(AiTaskLog.created_at >= start, AiTaskLog.created_at < end)
            .group_by(
                AiTaskLog.task_type,
                AiTaskLog.provider,
                AiTaskLog.validation_result,
                AiTaskLog.failure_class,
                AiTaskLog.model_id,
            )
        )
        for task, provider, outcome, failure, model, count, latency, tokens_in, tokens_out in rows:
            key = {"task": _identifier(task), "provider": _identifier(provider), "outcome": _identifier(outcome)}
            if None in key.values():
                continue
            if _identifier(failure):
                key["failure"] = failure
            if isinstance(provider, str) and provider.startswith(_CLOUD_PREFIX) and isinstance(model, str):
                model_id = model.strip().lower()
                if CATALOGUE["daily_ai_task"].props["model"].accepts(model_id):
                    key["model"] = model_id
            props: dict[str, object] = dict(key)
            if latency is not None:
                props["latency_p50_ms"] = int(round(float(latency)))
            if tokens_in is not None:
                props["input_tokens"] = int(tokens_in)
            if tokens_out is not None:
                props["output_tokens"] = int(tokens_out)
            if await recorder.record_total(
                session, "daily_ai_task", props, day=day, count=int(count), now=now, sharing=sharing, key_props=key
            ):
                written += 1
        day += timedelta(days=1)
    return written


async def first_scan(session: AsyncSession, *, sharing: Sharing, now: datetime) -> bool:
    """The first scan to finish after the user shared usage, once ever."""
    decided = sharing.decided_at(Group.USAGE)
    if decided is None or not sharing.shared(Group.USAGE):
        return False
    first = (
        await session.execute(
            select(ScrapeSourceRun.outcome, ScrapeSourceRun.finished_at)
            .where(ScrapeSourceRun.finished_at >= decided, ScrapeSourceRun.finished_at < now)
            .order_by(ScrapeSourceRun.finished_at)
            .limit(1)
        )
    ).first()
    if first is None or not OUTCOMES.accepts(first.outcome):
        return False
    return await recorder.record_milestone(
        session, "first_scan_finished", {"outcome": first.outcome}, now=first.finished_at, sharing=sharing
    )


async def heartbeat(session: AsyncSession, *, sharing: Sharing, now: datetime) -> bool:
    """Today's heartbeat snapshot; it leaves with the next day's send."""
    return await recorder.record_daily(
        session, "daily_heartbeat", await facts.heartbeat(session), now=now, sharing=sharing
    )
