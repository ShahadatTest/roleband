"""Deterministic token-budget truncation of a job description.

Keeps the head of the posting under a token budget so a single JD comfortably fits
the on-device model's context window alongside instructions, schema, and output. Uses
only the provider's `count_tokens` (no model call), so it is deterministic and
unit-testable with a fake provider. Whitespace-collapsing here is consistent with
the grounding normalization, so a snippet the model copies from the truncated
prompt still matches the original posting.
"""

from __future__ import annotations

_MARKER = "\n…[truncated]"
_MARKER_RESERVE = 8  # tokens held back for the marker


async def truncate_to_tokens(provider, text: str | None, max_tokens: int) -> tuple[str, bool, int]:
    """Return (prompt_text, truncated, token_count).

    If the text is within budget it is returned unchanged. Otherwise the largest
    whitespace-bounded prefix that fits (minus a small marker reserve) is returned
    with a truncation marker appended. Async because provider token counting is
    async (Apple's SDK exposes it as a coroutine).
    """
    text = text or ""
    if not text:
        return "", False, 0

    total = await provider.count_tokens(text)
    if total <= max_tokens:
        return text, False, total

    words = text.split()
    lo, hi, best = 0, len(words), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = " ".join(words[:mid])
        if await provider.count_tokens(candidate) <= max_tokens - _MARKER_RESERVE:
            best, lo = candidate, mid + 1
        else:
            hi = mid - 1

    truncated_text = best + _MARKER
    return truncated_text, True, await provider.count_tokens(truncated_text)
