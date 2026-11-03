"""Self-test: run one real extraction and report exactly what the model returned.

Backs the Settings "Test" button. It exercises the FULL production path — prompt
assembly, guided generation, grounding validation — against a built-in sample
posting (or user-supplied text), so a green result proves the integration works
end to end, not merely that a model replied.

It is a dry run: it never touches `jobs`. It does write one `AiTaskLog` row under
its own task type so self-tests stay separable from real extraction telemetry.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.intelligence.prefilter import has_pay_pattern
from tracker.intelligence.prompts import INSTRUCTIONS, PROMPT_VERSION, build_prompt
from tracker.intelligence.provider import IntelligenceProvider, ProviderOrigin
from tracker.intelligence.schema import DISCLOSED_COMP_SCHEMA, coerce_disclosed_comp
from tracker.intelligence.truncate import truncate_to_tokens
from tracker.intelligence_runtime.telemetry import log_ai_task

logger = logging.getLogger(__name__)

TEST_TASK = "disclosed_comp_test"

# A realistic posting that clearly states a band. The expected extraction is
# 180,000-240,000 USD / year, so a correct run is obvious to the user at a glance.
SAMPLE_POSTING = (
    "Staff Software Engineer, Platform\n\n"
    "We're hiring a Staff Software Engineer to lead our platform reliability work. "
    "You'll design distributed systems, mentor senior engineers, and own service "
    "level objectives across the fleet.\n\n"
    "Requirements: 8+ years of backend experience, deep familiarity with "
    "Kubernetes, and a track record of leading cross-team technical projects.\n\n"
    "The annual base salary range for this role is $180,000—$240,000 USD. "
    "Actual compensation depends on experience and location. We also offer equity "
    "and a comprehensive benefits package."
)

EXPECTED_HINT = {"base_min": 180000, "base_max": 240000, "currency": "USD"}


# Which tier answered is shown next to every response, derived from what RAN,
# not from what is configured (a routed call can land on another tier): the
# dashboard names `origin`.


def _availability_payload(avail) -> dict:
    return {
        "state": avail.state.value,
        "ok": avail.ok,
        "detail": avail.detail,
    }


def _origin_payload(res) -> dict:
    return {
        "origin": res.origin.value,
        "left_device": res.origin is ProviderOrigin.CLOUD,
        "answered_by": res.provider_name,
        "route_reason": res.route_reason,
        "route_attempts": [item.redacted() for item in res.attempts],
    }


async def run_self_test(
    session: AsyncSession,
    provider: IntelligenceProvider,
    text: str | None = None,
) -> dict:
    """Run one extraction and return a UI-ready report. Never raises."""
    settings = get_settings()
    used_sample = not (text and text.strip())
    description = SAMPLE_POSTING if used_sample else text.strip()

    avail = await provider.availability()
    base = {
        "availability": _availability_payload(avail),
        "used_sample": used_sample,
        "prompt_version": PROMPT_VERSION,
        "model_id": settings.intelligence_model_id,
        "expected": EXPECTED_HINT if used_sample else None,
    }

    if not avail.ok:
        await log_ai_task(
            session,
            task_type=TEST_TASK,
            provider=provider.name,
            availability_state=avail.state.value,
            validation_result="skipped",
            failure_class="unavailable",
            prompt_version=PROMPT_VERSION,
            model_id=settings.intelligence_model_id,
        )
        return {**base, "ok": False}

    # Mirrors the real pass: the pre-filter decides whether a model call is worth it.
    prefiltered = not has_pay_pattern(description)
    if prefiltered:
        return {
            **base,
            "ok": True,
            "prefiltered": True,
            "raw": None,
            "extracted": None,
        }

    prompt_text, truncated, _ = await truncate_to_tokens(
        provider, description, settings.intelligence_input_token_budget
    )
    res = await provider.generate(
        instructions=INSTRUCTIONS,
        prompt=build_prompt(prompt_text),
        schema=DISCLOSED_COMP_SCHEMA,
        budget_tokens=settings.intelligence_context_tokens,
    )

    if res.fields is None:
        await log_ai_task(
            session,
            task_type=TEST_TASK,
            provider=res.provider_name or provider.name,
            availability_state=res.availability_state.value,
            validation_result="invalid",
            failure_class=res.failure_class or "sdk_error",
            latency_ms=res.latency_ms,
            prompt_version=PROMPT_VERSION,
            model_id=settings.intelligence_model_id,
            route_reason=res.route_reason,
            meta={"truncated": truncated, "origin": res.origin.value},
        )
        return {
            **base,
            "ok": False,
            "failure_class": res.failure_class,
            "latency_ms": res.latency_ms,
            **_origin_payload(res),
        }

    extracted = coerce_disclosed_comp(res.fields, description)
    raw_disclosed = isinstance(res.fields, dict) and bool(res.fields.get("disclosed"))
    rejected = raw_disclosed and not extracted.disclosed

    await log_ai_task(
        session,
        task_type=TEST_TASK,
        provider=res.provider_name or provider.name,
        availability_state=res.availability_state.value,
        validation_result="invalid" if rejected else "ok",
        failure_class="validation" if rejected else None,
        latency_ms=res.latency_ms,
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
        prompt_version=PROMPT_VERSION,
        model_id=settings.intelligence_model_id,
        route_reason=res.route_reason,
        meta={
            "disclosed": extracted.disclosed,
            "truncated": truncated,
            "origin": res.origin.value,
        },
    )

    return {
        **base,
        "ok": True,
        "prefiltered": False,
        "latency_ms": res.latency_ms,
        **_origin_payload(res),
        "input_tokens": res.input_tokens,
        "output_tokens": res.output_tokens,
        "truncated": truncated,
        # What the model literally returned, before validation.
        "raw": res.fields,
        # What survived grounding + bounds validation — what we would store.
        "extracted": extracted.model_dump(mode="json"),
        "grounded": extracted.disclosed,
        # True when the model claimed a band that is NOT in the text (rejected).
        "rejected_ungrounded": rejected,
    }
