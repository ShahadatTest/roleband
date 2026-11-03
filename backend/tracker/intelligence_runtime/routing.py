"""Assembling the routing ladder — and the only door to off-device inference.

The ladder is the model bench's harness (`scripts.bench_relevance_review`):
no product task routes through it today, so Settings shows its tiers and
nothing sends them job text.

Kept out of `intelligence/registry.py`: the registry is the model
SEAM and sits below the service tier; this needs the saved local and cloud
profiles, the egress switch and the measurement substrate, all of which live in
the store. So the choice of WHICH backend runs is service work, while the
construction of a backend stays down in the seam.

Two properties worth stating plainly, because they are why routing is centralized:

  - There is exactly ONE line in the codebase that can put a cloud tier into a
    provider chain, and it is guarded by `get_ai_egress_enabled`. A cloud
    profile that exists, is enabled, and has a key is still not reachable
    without that switch. The one other path to a cloud model, search query
    parsing (`search/llm.py`), takes the same switch. Auditing the privacy
    promise means reading this file and that one.
  - Routing policy is fed by `measure_tiers`, so which backend runs is decided
    by recorded outcomes rather than by a constant someone guessed.

Apple FM is deliberately absent from the ladder: it is available on one OS, on
recent hardware, behind a user setting, so nothing the app does automatically may
depend on it. `registry.build_provider` is its only door, and only the
Settings > Experimental self-test opens it.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.intelligence.policy import RouteReason
from tracker.intelligence.provider import AvailabilityState, IntelligenceProvider, NullProvider
from tracker.intelligence.providers.cloud import CloudLLMProvider
from tracker.intelligence.providers.local import LocalLLMProvider
from tracker.intelligence.router import RouterProvider, Tier
from tracker.intelligence_runtime.cloud_profiles import get_state as get_cloud_state
from tracker.intelligence_runtime.local_profiles import (
    get_active_profile as get_active_local_profile,
)
from tracker.intelligence_runtime.local_profiles import get_enabled as get_local_enabled
from tracker.intelligence_runtime.telemetry import measure_tiers
from tracker.settings_store import get_ai_egress_enabled


async def build_tiers(session: AsyncSession, *, task_type: str | None) -> list[Tier]:
    """Assemble the routing ladder from saved state + the measurement substrate.

    Local, then cloud. Apple FM is absent by design (see the module docstring).
    `task_type` names the task whose recorded outcomes feed the routing policy;
    None builds the ladder unmeasured, as Settings shows it, and reads no log.
    """
    measurements = await measure_tiers(session, task_type=task_type) if task_type is not None else {}
    tiers: list[Tier] = []

    # The local tier is offered only when the user has it switched on. Omitted
    # rather than added with a `blocked_reason` on purpose: a blocked tier makes
    # `resolve_provider` report the CLOUD egress message, which would be a lie
    # about why nothing ran. Absent, it falls through to "turned off".
    local_profile = (
        await get_active_local_profile(session) if await get_local_enabled(session) else None
    )
    if local_profile is not None:
        local = LocalLLMProvider(local_profile)
        tiers.append(Tier(provider=local, measurement=measurements.get(local.name)))

    # --- the only door to off-device inference ------------------------------
    egress_allowed = await get_ai_egress_enabled(session)
    cloud_state = await get_cloud_state(session)
    for profile in cloud_state.profiles:
        if not profile.enabled:
            continue
        cloud = CloudLLMProvider(profile)
        tiers.append(
            Tier(
                provider=cloud,
                measurement=measurements.get(cloud.name),
                blocked_reason=None if egress_allowed else RouteReason.EGRESS_BLOCKED,
            )
        )
    return tiers


async def resolve_provider(
    session: AsyncSession, *, task_type: str = "relevance_review"
) -> IntelligenceProvider:
    """Provider for a routed task, reflecting the user's persisted configuration.

    Falls back to a `NullProvider` carrying the reason when nothing usable is
    configured — the callers' `availability()` check then reports something the
    user can act on.
    """
    if not get_settings().intelligence_routing_enabled:
        return NullProvider(AvailabilityState.DISABLED_BY_FLAG, "model routing is turned off")

    tiers = await build_tiers(session, task_type=task_type)
    usable = [tier for tier in tiers if tier.blocked_reason is None]
    if not usable:
        if tiers:
            return NullProvider(
                AvailabilityState.EGRESS_NOT_PERMITTED,
                "only cloud models are configured, and sending text off this computer is off",
            )
        return NullProvider(AvailabilityState.NOT_CONFIGURED, "no model backend is configured")
    if len(tiers) == 1:
        # No ladder to speak of — hand back the leaf so single-backend telemetry
        # records the provider that actually ran rather than "router".
        return tiers[0].provider
    return RouterProvider(tiers)


async def routing_state(session: AsyncSession) -> dict:
    """The routed-task ladder (local -> cloud) as configured, WITHOUT probing.

    The read side of this module: `build_tiers` assembles the ladder, this says
    what it looks like to Settings. It lives here, not in the router: it is a
    projection of the ladder, and the ladder lives here.

    Apple FM is never in it: see `intelligence.registry`.

    Availability checks reach the network (loopback for oMLX), and a settings
    read should not depend on a model server being up — nor make a request the
    user did not ask for. The Test buttons are where liveness is established.
    Unmeasured too: no product task routes, so the log holds no outcome of a
    routed task to show, and Settings polls this read while a model downloads.
    """
    egress_enabled = await get_ai_egress_enabled(session)
    tiers = await build_tiers(session, task_type=None)
    return {
        "egress_enabled": egress_enabled,
        "tiers": [
            {
                "provider": getattr(tier.provider, "name", "unknown"),
                "origin": tier.provider.origin.value,
                "model_id": getattr(tier.provider, "model_id", None),
                "blocked_reason": tier.blocked_reason,
            }
            for tier in tiers
        ],
    }
