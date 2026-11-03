"""Intelligence-provider contracts: implementations satisfy the Protocol surface.

Behavior (gating, telemetry, schema) is covered by tests/test_intelligence_*.py;
this suite pins the IntelligenceProvider seam every implementation must keep.
"""

from __future__ import annotations

import inspect

import pytest

from tracker.intelligence.apple_fm import AppleFMProvider
from tracker.intelligence.provider import (
    AvailabilityState,
    IntelligenceProvider,
    NullProvider,
)
from tracker.intelligence.registry import build_provider

# Every implementation reachable through the registry, by name. AppleFMProvider
# construction is SDK-free (the import happens lazily on first use), so this
# never touches the model.
IMPLEMENTATIONS = {
    "null": NullProvider(),
    "apple_fm": AppleFMProvider(),
}

GENERATE_KWARGS = ["instructions", "prompt", "schema", "budget_tokens"]


@pytest.mark.parametrize("name", sorted(IMPLEMENTATIONS))
def test_implementation_satisfies_intelligence_provider_protocol(name):
    provider = IMPLEMENTATIONS[name]

    assert isinstance(provider, IntelligenceProvider), f"{name}: fails the runtime Protocol"
    assert isinstance(provider.name, str) and provider.name.strip()
    assert inspect.iscoroutinefunction(provider.availability)
    assert inspect.iscoroutinefunction(provider.count_tokens)
    assert inspect.iscoroutinefunction(provider.generate)

    params = inspect.signature(provider.generate).parameters
    for kwarg in GENERATE_KWARGS:
        assert kwarg in params, f"{name}: generate() missing kwarg '{kwarg}'"
        assert params[kwarg].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("enabled", [True, False])
def test_registry_swap_point_returns_protocol_satisfying_provider(enabled):
    provider = build_provider(enabled)
    assert isinstance(provider, IntelligenceProvider)


@pytest.mark.asyncio
async def test_disabled_provider_reports_unavailable_and_never_generates():
    provider = build_provider(False)

    availability = await provider.availability()
    assert availability.ok is False
    assert availability.state is AvailabilityState.DISABLED_BY_FLAG

    result = await provider.generate(
        instructions="x", prompt="y", schema=dict, budget_tokens=10
    )
    assert result.fields is None
    assert result.failure_class == "unavailable"
