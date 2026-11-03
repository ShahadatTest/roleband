"""`RouterProvider` — one `IntelligenceProvider` that spans several tiers.

It IS a provider, not a thing beside providers: it satisfies the same Protocol,
so a caller cannot tell whether it was handed a router or a leaf. That is what
makes routing an assembly decision (`intelligence_runtime/routing.py`) instead
of a caller decision.

Order is the model on this Mac -> cloud, which is simultaneously the
cheapest-first, most-private-first, and lowest-latency-first order. Those three usually conflict; here they agree, so
the ordering needs no tie-break policy.

The router never runs tiers in parallel or speculatively. Besides the
standing "no local concurrency" rule, a speculative cloud call would send job
text off the Mac for a request the on-device model was about to answer — the
privacy contract makes racing the tiers unavailable as an optimization.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from tracker.intelligence.policy import (
    RouteReason,
    TierMeasurement,
    escalation_reason,
    skip_reason,
    success_reason,
    terminal_reason,
)
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    IntelligenceProvider,
    ProviderOrigin,
    RouteAttempt,
)

logger = logging.getLogger(__name__)


@dataclass
class Tier:
    """One rung of the ladder plus what policy needs to reason about it."""

    provider: IntelligenceProvider
    measurement: TierMeasurement | None = None
    context_tokens: int | None = None
    # Set when the tier is present but forbidden (cloud without egress opt-in).
    blocked_reason: str | None = None


class RouterProvider:
    name = "router"

    def __init__(self, tiers: list[Tier]):
        self.tiers = tiers

    @property
    def origin(self) -> ProviderOrigin:
        """The most private origin still reachable — what the UI can promise
        before a request runs. Per-response origin comes off the result."""
        for tier in self.tiers:
            if tier.blocked_reason is None:
                return tier.provider.origin
        return ProviderOrigin.NONE

    async def availability(self) -> Availability:
        """Available if ANY unblocked tier is. Reports the first tier's reason
        when none are, since that is the one the user configured first."""
        first: Availability | None = None
        for tier in self.tiers:
            if tier.blocked_reason is not None:
                continue
            avail = await tier.provider.availability()
            if avail.ok:
                return avail
            first = first or avail
        return first or Availability(
            AvailabilityState.NOT_CONFIGURED, detail="no model backend is configured"
        )

    async def count_tokens(self, text: str) -> int:
        """Counted by the tier that would run first — token budgets are set for
        the primary tier, and a fallback's tokenizer must not silently rewrite
        how much input the caller decides to send."""
        for tier in self.tiers:
            if tier.blocked_reason is None:
                return await tier.provider.count_tokens(text)
        return max(1, len(text or "") // 4)

    async def generate(
        self,
        *,
        instructions: str,
        prompt: str,
        schema: type,
        budget_tokens: int,
        validate: Callable[[dict], bool] | None = None,
    ) -> GenerationResult:
        """Walk the ladder until a tier produces output this caller will accept.

        `validate` is what makes `escalation_reason("validation")` reachable
        for the case `policy.py` names it for. Without it, "returned parseable
        fields" would be acceptance: the router would return the first tier
        that produced JSON, and the caller would discover an ungrounded answer
        only afterwards, too late to try the tier that would have got it right.

        It matters most exactly when the ladder is deepest, and because the
        caller marks the job processed, a dropped answer is permanent until the
        posting's text changes.
        """
        attempts: list[RouteAttempt] = []
        pending_reason: str | None = None  # why the NEXT tier is being tried
        last_failure: GenerationResult | None = None

        for index, tier in enumerate(self.tiers):
            provider = tier.provider
            name = getattr(provider, "name", "unknown")

            if tier.blocked_reason is not None:
                attempts.append(
                    RouteAttempt(name, provider.origin, "skipped", tier.blocked_reason)
                )
                continue

            veto = skip_reason(tier.measurement)
            if veto is not None:
                attempts.append(RouteAttempt(name, provider.origin, "skipped", veto))
                pending_reason = pending_reason or veto
                continue

            if tier.context_tokens is not None:
                needed = await provider.count_tokens(prompt)
                if needed > tier.context_tokens:
                    attempts.append(
                        RouteAttempt(
                            name, provider.origin, "skipped", RouteReason.SKIPPED_CONTEXT
                        )
                    )
                    pending_reason = pending_reason or RouteReason.ESCALATED_CONTEXT
                    continue

            avail = await provider.availability()
            if not avail.ok:
                attempts.append(
                    RouteAttempt(
                        name,
                        provider.origin,
                        "skipped",
                        RouteReason.TIER_UNAVAILABLE,
                        failure_class=avail.state.value,
                    )
                )
                pending_reason = pending_reason or RouteReason.TIER_UNAVAILABLE
                continue

            result = await provider.generate(
                instructions=instructions,
                prompt=prompt,
                schema=schema,
                budget_tokens=budget_tokens,
            )

            if result.fields is not None and (validate is None or validate(result.fields)):
                attempts.append(
                    RouteAttempt(
                        name,
                        provider.origin,
                        "ok",
                        # The same reason the result carries: an escalated-to
                        # tier's attempt entry must not read "primary" while
                        # the row it sits on says "escalated_*".
                        pending_reason or RouteReason.PRIMARY,
                        result.latency_ms,
                    )
                )
                result.route_reason = success_reason(
                    index, tier.measurement is not None, pending_reason
                )
                result.attempts = attempts
                return result

            if result.fields is not None:
                # It generated fine and the caller rejected the ANSWER. Naming
                # it `validation` is what makes `escalation_reason` route it on;
                # it also means the row is measured as a wrong answer rather
                # than a mechanical fault (grading reads this).
                result.failure_class = "validation"
            attempts.append(
                RouteAttempt(
                    name,
                    provider.origin,
                    "failed",
                    pending_reason or RouteReason.PRIMARY,
                    result.latency_ms,
                    result.failure_class,
                )
            )
            last_failure = result

            escalate = escalation_reason(result.failure_class)
            if escalate is None:
                # Terminal: a bigger model is not the fix, and for a refusal,
                # forwarding the text would be actively wrong.
                result.route_reason = terminal_reason(result.failure_class)
                result.attempts = attempts
                return result
            pending_reason = escalate

        # Every tier skipped or failed. When the failures were `validate`
        # rejections the last result still CARRIES its fields, and returning
        # them is deliberate: every tier disagreed with the caller, so there is
        # no better answer to be had, and the caller handles a bad answer as it
        # would from a single tier. Withholding it
        # would turn "no tier could ground this band" into "the model failed",
        # which is a different and less true statement.
        if last_failure is not None:
            last_failure.route_reason = RouteReason.EXHAUSTED
            last_failure.attempts = attempts
            return last_failure
        return GenerationResult(
            fields=None,
            availability_state=AvailabilityState.NOT_CONFIGURED,
            failure_class="unavailable",
            provider_name=self.name,
            origin=ProviderOrigin.NONE,
            route_reason=pending_reason or RouteReason.EXHAUSTED,
            attempts=attempts,
        )
