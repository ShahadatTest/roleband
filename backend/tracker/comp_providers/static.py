"""Static fallback comp provider: reads the seed pay on each rung (`levels.pay`).

Always available, never fails, no network. The backstop when the stored rows
cannot resolve a company/band.
"""

from __future__ import annotations

from tracker.comp_providers.base import (
    BUILTIN,
    OUR_PAY_COUNTRY,
    CompContext,
    CompEstimate,
    CompProvider,
    company_name,
)
from tracker.levels.pay import level_label, seed_range


class StaticCompProvider(CompProvider):
    name = "static"

    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        if ctx.country != OUR_PAY_COUNTRY:
            return None
        rng = seed_range(ctx.company, ctx.band)
        if rng is None:
            return None
        low, median, high = rng
        label = level_label(ctx.company, ctx.band)
        return CompEstimate(
            median=median,
            low=low,
            high=high,
            currency="USD",
            source=f"{company_name(ctx.company)} {label} (built-in estimate)",
            detail={"provider": self.name, "level": label},
            provider=BUILTIN,
        )
