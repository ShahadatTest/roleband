"""oMLX / OpenAI-compatible loopback model as an `IntelligenceProvider`.

Wraps `LocalLLMClient` without changing it: profiles, the loopback
address gate, and the oMLX metric vocabulary stay in `tracker.local_llm`. What
this adds is the seam — availability as a state rather than an exception, and a
`GenerationResult` whose failure classes line up with Apple FM's so the router
can compare tiers on one scale.

The local model takes one request at a time: no batching, no worker fan-out.
Nothing here starts a task group, and `generate` is a single awaited call.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    ProviderOrigin,
)
from tracker.intelligence.structured import json_instruction, parse_json_object
from tracker.local_llm.client import LocalLLMClient, LocalLLMError
from tracker.local_llm.models import LocalLLMProfile

logger = logging.getLogger(__name__)

# `LocalLLMError.failure_class` -> the availability state it implies. Anything
# not listed is a per-request failure, not an unavailable backend.
_UNAVAILABLE_BY_FAILURE = {
    "connection": AvailabilityState.SERVER_UNREACHABLE,
    "timeout": AvailabilityState.SERVER_UNREACHABLE,
    "http_error": AvailabilityState.SERVER_UNREACHABLE,
    "model_not_found": AvailabilityState.MODEL_NOT_READY,
}


class LocalLLMProvider:
    """One saved local profile, presented on the seam."""

    origin = ProviderOrigin.THIS_MAC

    def __init__(self, profile: LocalLLMProfile, client: LocalLLMClient | None = None):
        self.profile = profile
        # Telemetry records the concrete server kind (`omlx` / `openai_compatible`)
        # as the provider, so ai_task_log rows stay comparable per server kind.
        self.name = profile.provider
        self.model_id = profile.model
        self._client = client or LocalLLMClient(profile)

    async def availability(self) -> Availability:
        """Reachability + the configured model actually being served.

        A server that is up but not serving the saved model is NOT
        available for our purposes: routing to it would fail every request.
        """
        try:
            models = await self._client.list_models()
        except LocalLLMError as exc:
            state = _UNAVAILABLE_BY_FAILURE.get(exc.failure_class, AvailabilityState.SERVER_UNREACHABLE)
            return Availability(state, detail=str(exc))
        if not any(item.get("id") == self.profile.model for item in models):
            return Availability(
                AvailabilityState.MODEL_NOT_READY,
                detail=f'the server is not serving "{self.profile.model}"',
            )
        return Availability(AvailabilityState.AVAILABLE)

    async def count_tokens(self, text: str) -> int:
        """Heuristic: the OpenAI-compatible surface exposes no tokenizer, and
        asking the model to count would cost a generation."""
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
                system=f"{instructions}\n\n{json_instruction(schema)}",
                prompt=prompt,
                json_mode=True,
                # Every call through this seam is structured output, and a
                # reasoning preamble lands in the visible channel ahead of the
                # JSON. Off regardless of the profile's free-form setting.
                thinking=False,
            )
        except LocalLLMError as exc:
            state = _UNAVAILABLE_BY_FAILURE.get(exc.failure_class)
            logger.info("local_llm generation failed (%s): %s", exc.failure_class, exc)
            return GenerationResult(
                fields=None,
                availability_state=state or AvailabilityState.AVAILABLE,
                latency_ms=int((time.monotonic() - started) * 1000),
                failure_class=exc.failure_class,
                provider_name=self.name,
                origin=self.origin,
            )

        metrics = result.metrics
        latency_ms = metrics.get("wall_time_ms") or int((time.monotonic() - started) * 1000)
        base = {
            "availability_state": AvailabilityState.AVAILABLE,
            "latency_ms": latency_ms,
            "input_tokens": metrics.get("prompt_tokens"),
            "output_tokens": metrics.get("completion_tokens"),
            "provider_name": self.name,
            "origin": self.origin,
            "model_id": self.profile.model,
        }
        # A truncated turn is never parsed: a JSON object cut mid-string can still
        # decode into something plausible-looking, and that is exactly the class
        # of silent corruption to fail closed on.
        if result.finish_reason == "length":
            return GenerationResult(fields=None, failure_class="truncated", **base)

        fields = parse_json_object(result.content)
        if fields is None:
            return GenerationResult(fields=None, failure_class="validation", **base)
        return GenerationResult(fields=fields, **base)
