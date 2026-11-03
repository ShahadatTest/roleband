"""Price-provider contracts: every implementation exposes the PriceProvider surface.

Structural checks only — fixture/Tiingo behavior is covered by
tests/test_price_provider.py; this suite pins the pluggable surface so a new
provider (or a refactor) cannot drift from the Protocol.
"""

from __future__ import annotations

import inspect

import pytest

from tracker.prices.provider import (
    FixturePriceProvider,
    TiingoPriceProvider,
    get_price_provider,
)

# The registry of price-provider implementations selectable via
# get_price_provider(); a new implementation must be added here by name.
IMPLEMENTATIONS = {
    "fixture": FixturePriceProvider(),
    "tiingo": TiingoPriceProvider("contract-test-key"),  # constructed, never called live
}


@pytest.mark.parametrize("name", sorted(IMPLEMENTATIONS))
def test_implementation_satisfies_price_provider_surface(name):
    provider = IMPLEMENTATIONS[name]

    assert isinstance(provider.source, str) and provider.source.strip()
    assert isinstance(provider.attribution, str) and provider.attribution.strip()

    assert isinstance(provider.metered, bool)

    assert inspect.iscoroutinefunction(provider.fetch)
    assert list(inspect.signature(provider.fetch).parameters) == ["ticker", "since"]


def test_factory_returns_a_known_implementation_surface():
    provider = get_price_provider()
    assert provider.source in {impl.source for impl in IMPLEMENTATIONS.values()}
    assert inspect.iscoroutinefunction(provider.fetch)
