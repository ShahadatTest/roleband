"""Deterministic token-budget truncation (fake provider counts words).

`truncate_to_tokens` is async because Apple's SDK exposes token counting as a
coroutine, so the fake provider mirrors that.
"""

from __future__ import annotations

import asyncio

from tracker.intelligence.schema import snippet_grounded
from tracker.intelligence.truncate import truncate_to_tokens


class WordCountProvider:
    """count_tokens = number of whitespace-separated words (deterministic)."""

    name = "wordcount"

    async def count_tokens(self, text: str) -> int:
        return len((text or "").split())


P = WordCountProvider()


def _run(text, max_tokens):
    return asyncio.run(truncate_to_tokens(P, text, max_tokens))


def test_under_budget_passes_through():
    text = "one two three four five"
    out, truncated, n = _run(text, 100)
    assert out == text
    assert truncated is False
    assert n == 5


def test_over_budget_truncates_with_marker_and_fits():
    text = " ".join(f"w{i}" for i in range(200))
    out, truncated, n = _run(text, 20)
    assert truncated is True
    assert out.endswith("[truncated]")
    assert n <= 20


def test_truncation_is_deterministic():
    text = " ".join(f"w{i}" for i in range(200))
    assert _run(text, 20) == _run(text, 20)


def test_head_snippet_survives_truncation_and_still_grounds():
    # A band near the top is retained and still grounds against the ORIGINAL text.
    head = "Annual Salary: $210,000—$260,000 USD."
    tail = " ".join(f"filler{i}" for i in range(500))
    full = head + " " + tail
    out, truncated, _ = _run(full, 12)
    assert truncated is True
    assert "$210,000" in out
    assert snippet_grounded("$210,000-$260,000 USD", full) is True


def test_empty_text():
    assert _run("", 10) == ("", False, 0)
