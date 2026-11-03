"""BYOK cloud model as an `IntelligenceProvider` — the only tier that leaves the Mac.

This adapter deliberately does NOT decide whether egress is allowed. That
decision belongs to `intelligence.registry`, which is the single place a cloud
tier can enter a provider chain, so there is exactly one line to audit rather
than one per call site.

`availability()` never makes a network request. Reaching a cloud endpoint to ask
whether it is up would itself be egress — performed before any opt-in check the
caller might still be about to fail — so readiness here is a question about
local configuration only.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from tracker.cloud_llm.client import CloudLLMClient, CloudLLMError
from tracker.cloud_llm.models import CloudLLMProfile
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    ProviderOrigin,
)
from tracker.intelligence.structured import json_instruction, parse_json_object

logger = logging.getLogger(__name__)

_UNAVAILABLE_BY_FAILURE = {
    "connection": AvailabilityState.SERVER_UNREACHABLE,
    "no_credentials": AvailabilityState.NOT_CONFIGURED,
}


class CloudLLMProvider:
    origin = ProviderOrigin.CLOUD

    def __init__(self, profile: CloudLLMProfile, client: CloudLLMClient | None = None):
        self.profile = profile
        self.name = f"cloud_{profile.provider}"[:24]
        self.model_id = profile.model
        self._client = client or CloudLLMClient(profile)

    async def availability(self) -> Availability:
        if not self.profile.enabled:
            return Availability(
                AvailabilityState.NOT_CONFIGURED, detail="this cloud profile is disabled"
            )
        if not self.profile.api_key:
            return Availability(
                AvailabilityState.NOT_CONFIGURED, detail="no API key is saved for this profile"
            )
        return Availability(AvailabilityState.AVAILABLE)

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
        started = time.monotonic()
        try:
            result = await self._client.chat(
                system=f"{instructions}\n\n{json_instruction(schema)}", prompt=prompt
            )
        except CloudLLMError as exc:
            logger.info("cloud generation failed (%s): %s", exc.failure_class, exc)
            return GenerationResult(
                fields=None,
                availability_state=_UNAVAILABLE_BY_FAILURE.get(
                    exc.failure_class, AvailabilityState.AVAILABLE
                ),
                latency_ms=int((time.monotonic() - started) * 1000),
                failure_class=exc.failure_class,
                provider_name=self.name,
                origin=self.origin,
            )

        metrics = result.metrics
        base = {
            "availability_state": AvailabilityState.AVAILABLE,
            "latency_ms": metrics.get("wall_time_ms"),
            "input_tokens": metrics.get("prompt_tokens"),
            "output_tokens": metrics.get("completion_tokens"),
            "provider_name": self.name,
            "origin": self.origin,
            "model_id": self.profile.model,
        }
        if result.finish_reason == "length":
            return GenerationResult(fields=None, failure_class="truncated", **base)
        fields = parse_json_object(result.content)
        if fields is None:
            return GenerationResult(fields=None, failure_class="validation", **base)
        return GenerationResult(fields=fields, **base)
