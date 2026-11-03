"""Writing and reading `ai_task_log` — the measurement substrate itself.

The table decides what to escalate from a local model to a cloud one, so
writing a row and folding the rows back into per-tier measurements are
the same job and live together. Both need the database, which is why they are
here rather than in `tracker/intelligence/telemetry.py`, where the GRADING of a
row — pure, given the row — stays.

It holds NO raw prompt or model output: `meta` carries only the redacted flags and
counts named in `_ALLOWED_META`, and anything else is dropped, so raw text cannot
leak through this path.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AiTaskLog, JobLineageLink, JobTwinLink
from tracker.intelligence.policy import TierMeasurement
from tracker.intelligence.telemetry import (
    Verdicts,
    fold_measurements,
    measurement_cutoff,
)

# Keys allowed in the redacted `meta` blob. Anything else is dropped so raw text
# can never leak through this path.
_ALLOWED_META = {
    "prefiltered",
    "disclosed",
    "truncated",
    "input_chars",
    "input_scope",
    "deterministic_recovery",
    "link_id",
    "recommendation",
    # relevance_review verdict echo (same role as `recommendation` above).
    "relevance",
    "domain",
    "finish_reason",
    "proposal_kind",
    # Router extras: tier names + outcome classes only (see RouteAttempt.redacted).
    "route_attempts",
    "origin",
}


async def log_ai_task(
    session: AsyncSession,
    *,
    task_type: str,
    provider: str,
    availability_state: str,
    validation_result: str,
    failure_class: str | None = None,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    prompt_version: str | None = None,
    model_id: str | None = None,
    job_id: int | None = None,
    route_reason: str | None = None,
    meta: dict | None = None,
) -> AiTaskLog:
    """Add (not commit) an `AiTaskLog` row; the caller owns the transaction."""
    safe_meta = {k: v for k, v in (meta or {}).items() if k in _ALLOWED_META}
    row = AiTaskLog(
        task_type=task_type,
        provider=provider,
        availability_state=availability_state,
        validation_result=validation_result,
        failure_class=failure_class,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        prompt_version=prompt_version,
        model_id=model_id,
        job_id=job_id,
        route_reason=route_reason,
        meta=safe_meta,
    )
    session.add(row)
    return row


async def measure_tiers(session: AsyncSession, *, task_type: str) -> dict[str, TierMeasurement]:
    """Per-provider record for one task, straight out of `ai_task_log`.

    This is the ONLY reader of the measurement substrate, so routing policy is
    fed by recorded outcomes rather than by anyone's belief about which backend
    is better. `skipped` rows are excluded: they are runs where no model was
    asked to do anything, and counting them would make an idle tier look broken.
    Bounded to `MEASUREMENT_WINDOW_DAYS` — see the constant for why that bound
    is what keeps a vetoed tier recoverable.
    """
    rows = (
        await session.execute(
            select(
                AiTaskLog.provider,
                AiTaskLog.validation_result,
                AiTaskLog.failure_class,
                AiTaskLog.latency_ms,
                AiTaskLog.meta,
            ).where(
                AiTaskLog.task_type == task_type,
                AiTaskLog.validation_result != "skipped",
                AiTaskLog.created_at >= measurement_cutoff(),
            )
        )
    ).all()
    verdicts = await _review_verdicts(session) if task_type.startswith("duplicate_review") else None
    return fold_measurements(rows, task_type=task_type, verdicts=verdicts)


async def _review_verdicts(session: AsyncSession) -> Verdicts:
    """Human verdicts on proposed links, keyed the way `meta` records them.

    Only reviewed links are returned: a `pending` link has no verdict, and an
    absent key is what `grade_row` reads as ungraded. Keyed by
    `(proposal_kind, id)` because lineage and twin ids collide.
    """
    verdicts: Verdicts = {}
    for kind, model in (("duplicate", JobLineageLink), ("twin", JobTwinLink)):
        rows = (
            await session.execute(
                select(model.id, model.status).where(
                    model.status.in_(("confirmed", "rejected"))
                )
            )
        ).all()
        for link_id, status in rows:
            verdicts[(kind, link_id)] = status
    return verdicts
