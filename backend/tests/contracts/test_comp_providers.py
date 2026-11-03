"""Comp-provider contracts: a failing provider can never break the resolver chain."""

from __future__ import annotations

import inspect

import pytest

from tracker.comp_providers.base import CompContext, CompEstimate, CompProvider
from tracker.enrich.comp import CompResolver
from tracker.schema import LevelBand

CTX = CompContext(
    company="google",
    band=LevelBand.STAFF,
    family="software_engineering",
    location_group="silicon_valley",
    country="US",
    title="Staff Software Engineer",
)


class BoomProvider(CompProvider):
    name = "boom"

    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        raise RuntimeError("provider exploded")


class OkProvider(CompProvider):
    name = "ok"

    def __init__(self) -> None:
        self.calls = 0

    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        self.calls += 1
        return CompEstimate(
            median=400_000, low=330_000, high=480_000,
            currency="USD", source="contract fixture", detail={},
        )


@pytest.mark.asyncio
async def test_raising_provider_does_not_break_chain_and_later_providers_run():
    ok = OkProvider()
    resolver = CompResolver([BoomProvider(), ok])

    primary, sources = await resolver.resolve(CTX)

    assert ok.calls == 1, "provider after the failing one was never consulted"
    assert primary is not None and primary.median == 400_000
    assert [s["provider"] for s in sources] == ["ok"]


@pytest.mark.asyncio
async def test_all_providers_failing_resolves_to_none_not_exception():
    resolver = CompResolver([BoomProvider(), BoomProvider()])

    primary, sources = await resolver.resolve(CTX)

    assert primary is None
    assert sources == []


def test_default_resolver_providers_satisfy_the_comp_provider_surface():
    providers = CompResolver().providers
    assert providers, "default resolver has no providers"
    for provider in providers:
        assert isinstance(provider, CompProvider), f"{provider!r} is not a CompProvider"
        assert isinstance(provider.name, str) and provider.name.strip()
        assert inspect.iscoroutinefunction(provider.lookup)
        assert inspect.iscoroutinefunction(provider.aclose)
