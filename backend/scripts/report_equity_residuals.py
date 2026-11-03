"""One-shot equity-residual report against the local DB (read-only).

    python -m scripts.report_equity_residuals

Runs the same query + pure builder as `GET /api/statistics/equity-validation`
and prints the JSON, for evidence and ad-hoc model checks.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from tracker.analytics.comp_residual import build_equity_residuals
from tracker.comp_providers.base import OUR_PAY_COUNTRY
from tracker.db.models import Job
from tracker.db.queries.reference_pay import split_rows
from tracker.db.session import session_scope
from tracker.intelligence.extract import TASK
from tracker.intelligence.prompts import PROMPT_VERSION
from tracker.plugins.registry import reader_providers
from tracker.settings_store import get_active_prompt_version


async def main() -> None:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    Job.company,
                    Job.level_band,
                    Job.comp_median,
                    Job.disclosed_base_min,
                    Job.disclosed_base_max,
                    Job.disclosed_currency,
                    Job.disclosed_pay_basis,
                    Job.disclosed_pay_period,
                    Job.disclosed_bonus_pct,
                    Job.structured_prompt_version,
                ).where(
                    Job.status == "open",
                    Job.in_scope.is_(True),
                    Job.disclosed_base_min.isnot(None),
                )
            )
        ).all()
        providers = await reader_providers(session)
        splits_read = await split_rows(session, providers, OUR_PAY_COUNTRY)
        observed = {
            (r.company_slug, r.band): {
                "base_pct": r.base_pct,
                "stock_pct": r.stock_pct,
                "bonus_pct": r.bonus_pct,
            }
            for r in splits_read
        }
        active = await get_active_prompt_version(session, TASK, PROMPT_VERSION)

    out = build_equity_residuals(
        [tuple(r) for r in rows], observed=observed, accepted_versions={active}
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
