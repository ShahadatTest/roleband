"""Apple Foundation Models provider — the ONLY module that touches the SDK.

Verified against `apple-fm-sdk` 0.2.1 on macOS 27 / Apple silicon:
  - import name is `apple_fm_sdk` (NOT `apple_fm`)
  - `SystemLanguageModel().is_available() -> (bool, UnavailableReason | None)`
  - `.context_size` (8192 on this model) and `await .token_count(...)` (a coroutine)
  - `LanguageModelSession(instructions=...)`, `await .respond(prompt, generating=Cls)`
  - guided generation uses an `@fm.generable` dataclass; the `json_schema=` path
    expects Apple's own dialect (an `x-order` key Pydantic doesn't emit), so we use
    the native decorator and mirror it back onto our Pydantic model for validation.

Isolated so the rest of the app never imports the SDK: on Linux/CI the import fails
and availability reports SDK_ABSENT, keeping the whole feature a no-op. Blocking is
avoided by awaiting the SDK's own coroutines under a hard timeout; any failure
degrades to a safe result rather than raising.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from tracker.config import get_settings
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    ProviderOrigin,
)

logger = logging.getLogger(__name__)

# Built lazily on first use, because it needs the SDK's decorator to exist.
_GENERABLE = None


def _build_generable(fm):
    """The guided-generation target. Mirrors `schema.DisclosedComp` field-for-field.

    `fm.guide(anyOf=...)` constrains the enum-ish fields at generation time — without
    it the model happily returns junk like confidence='job posting text'.

    OPTIONAL FIELDS MUST USE `Optional[X]`, NEVER `X | None`. The SDK forwards the
    PEP 604 union to Swift as a literal type name, and `GenerationSchema` rejects it
    (`SchemaError:3 ... undefined references: [int | None, str | None]`) — at
    generation time, not at decoration time, so the class builds cleanly and then
    every single respond() call fails. `from __future__ import annotations` is
    not involved: the same failure occurs without it, and `Optional` fixes it with it.
    """

    @fm.generable
    @dataclass
    class DisclosedCompGen:
        disclosed: bool = fm.guide(
            description="True only if the posting explicitly states a pay band."
        )
        base_min: Optional[int] = fm.guide(  # noqa: UP045 — see docstring
            description="Lower bound, whole currency units, exactly as written."
        )
        base_max: Optional[int] = fm.guide(  # noqa: UP045
            description="Upper bound, whole currency units, exactly as written."
        )
        # Constrained: left free-form, the model can return the literal word "CURRENCY".
        currency: Optional[str] = fm.guide(  # noqa: UP045
            anyOf=["USD", "EUR", "GBP", "CAD", "AUD", "SGD", "INR", "JPY", "CHF"]
        )
        pay_basis: str = fm.guide(anyOf=["base", "total", "unclear"])
        pay_period: str = fm.guide(anyOf=["year", "month", "hour", "unclear"])
        source_snippet: Optional[str] = fm.guide(  # noqa: UP045
            description="The exact sentence from the posting stating the pay, copied verbatim."
        )
        confidence: str = fm.guide(anyOf=["high", "low"])

    return DisclosedCompGen


class AppleFMProvider:
    name = "apple_fm"
    origin = ProviderOrigin.ON_DEVICE

    def __init__(self) -> None:
        self._fm = None
        self._loaded = False
        self._model = None

    def _load(self) -> None:
        """Import the SDK once; leaves `_fm=None` if it is unavailable."""
        self._loaded = True
        try:
            import apple_fm_sdk as fm  # noqa: PLC0415 — optional, macOS-only dependency

            self._fm = fm
        except Exception as exc:  # noqa: BLE001 — any import problem => SDK absent
            logger.info("apple_fm_sdk not importable: %s", exc)
            self._fm = None

    def _system_model(self):
        if self._model is None:
            self._model = self._fm.SystemLanguageModel()
        return self._model

    async def availability(self) -> Availability:
        # Enablement is decided in `registry`; this only reports device readiness.
        if not self._loaded:
            self._load()
        if self._fm is None:
            return Availability(AvailabilityState.SDK_ABSENT)
        try:
            available, reason = self._system_model().is_available()
            if available:
                return Availability(AvailabilityState.AVAILABLE)
            return Availability(_map_reason(self._fm, reason), detail=str(reason) if reason else None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("apple_fm availability check failed: %s", exc)
            return Availability(AvailabilityState.MODEL_NOT_READY, detail=str(exc))

    async def count_tokens(self, text: str) -> int:
        text = text or ""
        if not self._loaded:
            self._load()
        if self._fm is not None:
            try:
                return int(await self._system_model().token_count(text))
            except Exception:  # noqa: BLE001 — fall back to a rough estimate
                pass
        return max(1, len(text) // 4)

    async def context_size(self) -> int | None:
        if not self._loaded:
            self._load()
        if self._fm is None:
            return None
        try:
            return int(self._system_model().context_size)
        except Exception:  # noqa: BLE001
            return None

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
        global _GENERABLE
        settings = get_settings()
        if not self._loaded:
            self._load()
        if self._fm is None:
            return GenerationResult(
                fields=None,
                availability_state=AvailabilityState.SDK_ABSENT,
                failure_class="unavailable",
                provider_name=self.name,
            )

        # `_GENERABLE` mirrors DisclosedComp field-for-field. Guided generation
        # against any OTHER schema would return DisclosedComp-shaped output that
        # silently fails the caller's validator, so refuse it: a router must be
        # able to see "this tier can't do this task" and move on.
        if getattr(schema, "__name__", None) != "DisclosedComp":
            return GenerationResult(
                fields=None,
                availability_state=AvailabilityState.AVAILABLE,
                failure_class="unsupported_schema",
                provider_name=self.name,
                origin=self.origin,
            )

        started = time.monotonic()
        try:
            if _GENERABLE is None:
                _GENERABLE = _build_generable(self._fm)
            session = self._fm.LanguageModelSession(instructions=instructions)
            result = await asyncio.wait_for(
                session.respond(prompt, generating=_GENERABLE),
                timeout=settings.intelligence_timeout_seconds,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            return GenerationResult(
                fields=_to_dict(result),
                availability_state=AvailabilityState.AVAILABLE,
                latency_ms=latency_ms,
                input_tokens=await self.count_tokens(prompt),
                provider_name=self.name,
                origin=self.origin,
                model_id=settings.intelligence_model_id,
            )
        except TimeoutError:
            return GenerationResult(
                fields=None,
                availability_state=AvailabilityState.AVAILABLE,
                latency_ms=int((time.monotonic() - started) * 1000),
                failure_class="timeout",
                provider_name=self.name,
                origin=self.origin,
            )
        except Exception as exc:  # noqa: BLE001 — never break the pass on the SDK
            logger.warning("apple_fm generation failed: %s", exc)
            return GenerationResult(
                fields=None,
                availability_state=AvailabilityState.AVAILABLE,
                latency_ms=int((time.monotonic() - started) * 1000),
                failure_class=_failure_class(self._fm, exc),
                provider_name=self.name,
                origin=self.origin,
            )


def _failure_class(fm, exc: Exception) -> str:
    """Distinguish the SDK's typed errors so telemetry can tell them apart."""
    try:
        if isinstance(exc, fm.ExceededContextWindowSizeError):
            return "context_exceeded"
        if isinstance(exc, fm.GuardrailViolationError):
            return "guardrail"
        if isinstance(exc, fm.RateLimitedError):
            return "rate_limited"
        if isinstance(exc, fm.RefusalError):
            return "refusal"
    except Exception:  # noqa: BLE001 — error classes unavailable
        pass
    return "sdk_error"


def _map_reason(fm, reason) -> AvailabilityState:
    """Map the SDK's `SystemLanguageModelUnavailableReason` onto our states."""
    try:
        R = fm.SystemLanguageModelUnavailableReason
        if reason == R.APPLE_INTELLIGENCE_NOT_ENABLED:
            return AvailabilityState.APPLE_INTELLIGENCE_DISABLED
        if reason == R.DEVICE_NOT_ELIGIBLE:
            return AvailabilityState.DEVICE_INELIGIBLE
        if reason == R.MODEL_NOT_READY:
            return AvailabilityState.MODEL_NOT_READY
    except Exception:  # noqa: BLE001
        pass
    return AvailabilityState.MODEL_NOT_READY


def _to_dict(result) -> dict:
    """Coerce the SDK's generable instance into a plain dict for our validator."""
    if isinstance(result, dict):
        return result
    fields = (
        "disclosed",
        "base_min",
        "base_max",
        "currency",
        "pay_basis",
        "pay_period",
        "source_snippet",
        "confidence",
    )
    out = {f: getattr(result, f, None) for f in fields}
    return out if any(v is not None for v in out.values()) else dict(getattr(result, "__dict__", {}))
