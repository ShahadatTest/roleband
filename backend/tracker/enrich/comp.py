"""Compensation resolver: aggregates providers into one range with provenance.

The pipeline passes its providers: the stored per-level rows first
(`comp_providers.table`), then the static seed, then (when switched on) the
built-in dataset's base (`enrich.builtin_pay`). With none given
the resolver uses the seed alone, which needs no database and no network. The
resolver never fails a posting: if nothing resolves, comp fields stay None and
the job is still tracked.

`EstimateSet` holds two resolvers side by side: OURS, built from our
data only, and the selected plugin's, built from its rows only. Every posting
is estimated by both; neither reads the other's providers, so a plugin never
fills a gap in ours and ours never fills one in a plugin's.
"""

from __future__ import annotations

from tracker.comp_providers.base import CompContext, CompEstimate, CompProvider
from tracker.comp_providers.static import StaticCompProvider
from tracker.schema import LEVEL_BAND_ORDER, OUR_ESTIMATE_SOURCE, LevelBand


class CompResolver:
    def __init__(self, providers: list[CompProvider] | None = None, *, fingerprint: str | None = None) -> None:
        # Priority order: first successful primary result wins the headline range;
        # every provider's result is retained in `sources` for transparency.
        self.providers: list[CompProvider] = providers or [StaticCompProvider()]
        #: The reference fingerprint these providers stand for,
        #: stamped on every estimate as `comp_ref_fp`. None outside the pipeline.
        self.fingerprint = fingerprint

    def reset(self, providers: list[CompProvider], *, fingerprint: str | None) -> None:
        """Answer from a new provider set: the run re-estimated before collecting."""
        self.providers = providers
        self.fingerprint = fingerprint

    async def resolve(self, ctx: CompContext) -> tuple[CompEstimate | None, list[dict]]:
        # Comp reference data starts at Senior; earlier stages get no estimate
        # rather than a fabricated one.
        if LEVEL_BAND_ORDER[ctx.band.value] < LEVEL_BAND_ORDER[LevelBand.SENIOR.value]:
            return None, []
        primary: CompEstimate | None = None
        sources: list[dict] = []
        for provider in self.providers:
            try:
                est = await provider.lookup(ctx)
            except Exception:  # noqa: BLE001 - a provider must never break enrichment
                est = None
            if est is None:
                continue
            sources.append(
                {
                    "provider": provider.name,
                    "median": est.median,
                    "low": est.low,
                    "high": est.high,
                    "currency": est.currency,
                    "source": est.source,
                }
            )
            # The widest answer leads: a base-only answer stands only when no
            # provider of this source answers the total.
            if primary is None or (primary.median is None and est.median is not None):
                primary = est
        return primary, sources

    async def aclose(self) -> None:
        for provider in self.providers:
            await provider.aclose()


#: The source key our own estimate is stored under (`job_comp_estimate.source`).
OURS = OUR_ESTIMATE_SOURCE


class EstimateSet:
    """Our resolver and, while a plugin is selected for `pay.levels`, its own,
    with the source a job shows (`selected`). A plain `CompResolver` reads as
    ours alone."""

    def __init__(
        self,
        ours: CompResolver | None = None,
        plugin: tuple[str, CompResolver] | None = None,
        *,
        fingerprints: dict[str, str] | None = None,
        fingerprint: str | None = None,
    ) -> None:
        self.ours = ours or CompResolver()
        self.plugin = plugin
        #: source -> the fingerprint of that source's inputs (`job_comp_estimate.ref_fp`).
        self.fingerprints = dict(fingerprints or {})
        #: The projection's fingerprint (`jobs.comp_ref_fp`).
        self.fingerprint = fingerprint

    @classmethod
    def of(cls, resolver: CompResolver | EstimateSet | None) -> EstimateSet | None:
        if resolver is None or isinstance(resolver, EstimateSet):
            return resolver
        # None = not stamped: a resolver outside a run has no reference set.
        fingerprint = getattr(resolver, "fingerprint", None)
        return cls(resolver, fingerprint=fingerprint, fingerprints={OURS: fingerprint} if fingerprint else {})

    @property
    def selected(self) -> str:
        return self.plugin[0] if self.plugin is not None else OURS

    def resolvers(self) -> dict[str, CompResolver]:
        out = {OURS: self.ours}
        if self.plugin is not None:
            out[self.plugin[0]] = self.plugin[1]
        return out

    def reset(self, other: EstimateSet) -> None:
        """Answer from another set's resolvers: the run re-estimated before
        collecting. Our resolver keeps its identity (the run that made it closes
        it) and takes the other's providers; the plugin's is the other's."""
        self.ours.reset(other.ours.providers, fingerprint=other.fingerprint)
        self.plugin = other.plugin
        self.fingerprints, self.fingerprint = dict(other.fingerprints), other.fingerprint

    async def resolve(self, ctx: CompContext) -> dict[str, tuple[CompEstimate | None, list[dict]]]:
        """Each source's (primary, sources) for one posting."""
        return {source: await resolver.resolve(ctx) for source, resolver in self.resolvers().items()}

    async def aclose(self) -> None:
        for resolver in self.resolvers().values():
            await resolver.aclose()
