"""Provider abstraction: the seam a router splits work across, local and cloud.

`IntelligenceProvider` is the single interface every backend implements. Callers
only ever see this Protocol and the DB-free `GenerationResult`, so a router, a
local backend and a cloud backend are interchangeable to them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class AvailabilityState(str, Enum):
    AVAILABLE = "available"
    DISABLED_BY_FLAG = "disabled_by_flag"  # apple_fm_enabled is false
    SDK_ABSENT = "sdk_absent"  # import failed (Linux / CI / SDK not installed)
    APPLE_INTELLIGENCE_DISABLED = "apple_intelligence_disabled"
    DEVICE_INELIGIBLE = "device_ineligible"
    MODEL_NOT_READY = "model_not_ready"  # downloading / warming
    # --- states the non-Apple backends need ----------------------
    NOT_CONFIGURED = "not_configured"  # no profile saved / none selected
    SERVER_UNREACHABLE = "server_unreachable"  # loopback or HTTPS endpoint refused
    EGRESS_NOT_PERMITTED = "egress_not_permitted"  # cloud tier without opt-in


class ProviderOrigin(str, Enum):
    """WHERE a response was produced. Shipped privacy copy depends on this being
    accurate per response, not per configuration, so it travels with the result
    rather than being inferred by the UI from the provider name."""

    NONE = "none"  # nothing ran
    ON_DEVICE = "on_device"  # Apple FM — the Mac's own neural engine
    THIS_MAC = "this_mac"  # loopback server (oMLX) — local, but a separate process
    CLOUD = "cloud"  # left the device


# Plain-language reason per state, so Settings can tell the user what to DO about
# it instead of showing an enum.
AVAILABILITY_MESSAGES: dict[AvailabilityState, str] = {
    AvailabilityState.AVAILABLE: "On-device model is ready.",
    AvailabilityState.DISABLED_BY_FLAG: "Integration is turned off.",
    AvailabilityState.SDK_ABSENT: (
        "The Apple Foundation Models SDK isn't installed on this machine "
        "(requires macOS 26+ on Apple silicon)."
    ),
    AvailabilityState.APPLE_INTELLIGENCE_DISABLED: (
        "Apple Intelligence is turned off. Enable it in System Settings."
    ),
    AvailabilityState.DEVICE_INELIGIBLE: "This Mac doesn't support Apple Intelligence.",
    AvailabilityState.MODEL_NOT_READY: (
        "The on-device model isn't ready yet — it may still be downloading."
    ),
    AvailabilityState.NOT_CONFIGURED: (
        "No model is set up. Add one in Settings › AI."
    ),
    AvailabilityState.SERVER_UNREACHABLE: (
        "The model server did not respond. Check that it is running at the "
        "configured address."
    ),
    AvailabilityState.EGRESS_NOT_PERMITTED: (
        "Sending postings to online model services is off. Turn it on in "
        "Settings › AI."
    ),
}


@dataclass(frozen=True)
class Availability:
    state: AvailabilityState
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.state is AvailabilityState.AVAILABLE

    @property
    def message(self) -> str:
        return AVAILABILITY_MESSAGES.get(self.state, "On-device model is unavailable.")


@dataclass(frozen=True)
class RouteAttempt:
    """One tier the router tried. Redacted by construction — names and outcome
    classes only, never prompt or output text, so it is safe to persist."""

    provider: str
    origin: ProviderOrigin
    outcome: str  # ok | failed | skipped
    reason: str  # a `policy.RouteReason` value
    latency_ms: int | None = None
    failure_class: str | None = None

    def redacted(self) -> dict:
        return {
            "provider": self.provider,
            "origin": self.origin.value,
            "outcome": self.outcome,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "failure_class": self.failure_class,
        }


@dataclass
class GenerationResult:
    """DB-free result carrying the output plus provider-agnostic telemetry.

    `provider_name`/`origin`/`route_reason` describe WHICH backend actually
    answered. A single-backend provider fills them with its own identity, so a
    caller never has to know whether it was handed a router or a leaf.
    """

    fields: dict | None  # raw (unvalidated) model output, or None on failure
    availability_state: AvailabilityState
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    failure_class: str | None = None  # timeout | sdk_error | unavailable | None
    provider_name: str | None = None
    # The concrete model that answered (profile's model string / FM model id).
    # None when no tier produced an answer.
    model_id: str | None = None
    origin: ProviderOrigin = ProviderOrigin.NONE
    route_reason: str | None = None
    attempts: list[RouteAttempt] = field(default_factory=list)


@runtime_checkable
class IntelligenceProvider(Protocol):
    name: str
    origin: ProviderOrigin

    async def availability(self) -> Availability: ...

    # Async because Apple's SDK exposes token counting as a coroutine.
    async def count_tokens(self, text: str) -> int: ...

    async def generate(
        self,
        *,
        instructions: str,
        prompt: str,
        schema: type,
        budget_tokens: int,
        validate: Callable[[dict], bool] | None = None,
    ) -> GenerationResult:
        """`validate` decides whether output is ACCEPTABLE, not whether it parsed.

        Only a router can act on it, because acting means trying the next tier.
        A leaf provider takes the argument — so a caller never has to know which
        it holds — and ignores it: with nothing below it, rejecting output would
        throw away the only answer available, and the caller's own validation
        still catches it exactly as before.
        """
        ...


@dataclass
class NullProvider:
    """Stand-in when the feature is disabled or the SDK is absent.

    `availability()` reports the disabling reason; `generate()` never runs a model
    and always returns an unavailable result. `count_tokens` is a rough heuristic so
    deterministic helpers (truncation) still work without a model present.
    """

    state: AvailabilityState = AvailabilityState.DISABLED_BY_FLAG
    detail: str | None = None
    name: str = field(default="null")
    origin: ProviderOrigin = field(default=ProviderOrigin.NONE)

    async def availability(self) -> Availability:
        return Availability(self.state, self.detail)

    async def count_tokens(self, text: str) -> int:
        return max(1, len(text or "") // 4)

    async def generate(
        self,
        *,
        instructions: str,
        prompt: str,
        schema: type,
        budget_tokens: int,
        # Accepted and ignored: a leaf has no tier to escalate to.
        validate: Callable[[dict], bool] | None = None,
    ) -> GenerationResult:
        return GenerationResult(
            fields=None,
            availability_state=self.state,
            failure_class="unavailable",
            provider_name=self.name,
            origin=ProviderOrigin.NONE,
        )
