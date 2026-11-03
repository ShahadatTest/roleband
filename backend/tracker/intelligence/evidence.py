"""Posting text as an advisory prompt carries it, bounded.

Shared by the duplicate and relevance reviews so both read a posting the same
way: the description and its sections, each cut at a fixed length and marked
when cut, so one long posting cannot crowd the rest of a prompt out.
"""

from __future__ import annotations

from typing import Any

MAX_DESCRIPTION_CHARS = 12_000
MAX_SECTION_CHARS = 3_000


def truncate(value: str | None, limit: int) -> tuple[str, bool]:
    """`value` cut to `limit` characters, and whether it was cut."""
    text = value or ""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def description_sections(job: Any) -> list[dict]:
    """The posting's stored sections, each bounded by `MAX_SECTION_CHARS`."""
    sections = job.description_sections or []
    if not isinstance(sections, list):
        return []
    evidence = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        content, truncated = truncate(str(section.get("content") or ""), MAX_SECTION_CHARS)
        evidence.append({
            "key": section.get("key"),
            "title": section.get("title"),
            "content": content,
            "truncated": truncated,
        })
    return evidence
