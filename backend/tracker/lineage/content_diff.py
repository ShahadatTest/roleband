"""Full-section, order-insensitive posting text comparison.

Embeddings truncate long postings. Twin evidence therefore compares every stored
description passage. Only cosmetic formatting is normalized; numbers and wording
stay exact. Reordered identical passages are shared, not changes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass

from tracker.platform.util import normalize_text

_BULLET_RE = re.compile(r"^(?:[-*•·‣▪◦]+|\d+[.)])\s*")
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[\w+#.]+", re.UNICODE)


@dataclass(frozen=True)
class Passage:
    section_key: str
    section_title: str
    text: str


@dataclass(frozen=True)
class DescriptionDiff:
    comparable: bool
    equivalent: bool
    shared_count: int
    left_only_count: int
    right_only_count: int
    difference_ratio: float
    token_similarity: float
    left_only: tuple[Passage, ...]
    right_only: tuple[Passage, ...]

    def evidence(self) -> dict:
        return {
            "comparable": self.comparable,
            "equivalent": self.equivalent,
            "shared_count": self.shared_count,
            "left_only_count": self.left_only_count,
            "right_only_count": self.right_only_count,
            "difference_ratio": self.difference_ratio,
            "token_similarity": self.token_similarity,
            "left_only": [asdict(p) for p in self.left_only],
            "right_only": [asdict(p) for p in self.right_only],
        }


def _section_rows(sections: list[dict] | None, fallback: str | None) -> list[dict]:
    rows = [row for row in (sections or []) if isinstance(row, dict) and row.get("content")]
    if rows:
        return rows
    if fallback and fallback.strip():
        return [{"key": "job_description", "title": "Job description", "content": fallback}]
    return []


def _passages(sections: list[dict] | None, fallback: str | None) -> list[Passage]:
    out: list[Passage] = []
    for index, section in enumerate(_section_rows(sections, fallback)):
        key = str(section.get("key") or f"section_{index}")
        title = str(section.get("title") or key.replace("_", " ").title())
        for raw in re.split(r"\n+", str(section.get("content") or "")):
            text = raw.strip()
            if text:
                out.append(Passage(key, title, text))
    return out


def passages(sections: list[dict] | None, fallback: str | None) -> list[Passage]:
    """A description as the passages `compare_descriptions` compares."""
    return _passages(sections, fallback)


def passage_key(passage: Passage) -> tuple[str, str]:
    section = normalize_text(passage.section_key).casefold().replace(" ", "_")
    text = _BULLET_RE.sub("", normalize_text(passage.text).casefold())
    return section, _WS_RE.sub(" ", text).strip()


def compare_descriptions(
    left_sections: list[dict] | None,
    left_text: str | None,
    right_sections: list[dict] | None,
    right_text: str | None,
    *,
    snippet_limit: int = 12,
) -> DescriptionDiff:
    left = _passages(left_sections, left_text)
    right = _passages(right_sections, right_text)
    if not left or not right:
        return DescriptionDiff(False, False, 0, len(left), len(right), 1.0, 0.0, (), ())

    left_counts = Counter(passage_key(p) for p in left)
    right_counts = Counter(passage_key(p) for p in right)
    shared_counts = left_counts & right_counts
    shared = sum(shared_counts.values())

    left_remaining = shared_counts.copy()
    left_only: list[Passage] = []
    for passage in left:
        key = passage_key(passage)
        if left_remaining[key] > 0:
            left_remaining[key] -= 1
        else:
            left_only.append(passage)

    right_remaining = shared_counts.copy()
    right_only: list[Passage] = []
    for passage in right:
        key = passage_key(passage)
        if right_remaining[key] > 0:
            right_remaining[key] -= 1
        else:
            right_only.append(passage)

    unmatched = len(left_only) + len(right_only)
    total = len(left) + len(right)
    left_tokens = Counter(
        token for passage in left for token in _TOKEN_RE.findall(passage_key(passage)[1])
    )
    right_tokens = Counter(
        token for passage in right for token in _TOKEN_RE.findall(passage_key(passage)[1])
    )
    token_union = sum((left_tokens | right_tokens).values())
    token_shared = sum((left_tokens & right_tokens).values())
    return DescriptionDiff(
        comparable=True,
        equivalent=unmatched == 0,
        shared_count=shared,
        left_only_count=len(left_only),
        right_only_count=len(right_only),
        difference_ratio=round(unmatched / total, 4) if total else 0.0,
        token_similarity=round(token_shared / token_union, 4) if token_union else 0.0,
        left_only=tuple(left_only[:snippet_limit]),
        right_only=tuple(right_only[:snippet_limit]),
    )


def normalize_department(value: str | None) -> str | None:
    normalized = _WS_RE.sub(" ", normalize_text(value).casefold()).strip(" ,-|/")
    return normalized or None


#: A description's word signature: distinct
#: lower-cased words of at least four characters. A SET, so repeated
#: boilerplate counts once.
_SIGNATURE_WORD = re.compile(r"[a-z0-9]+")
SIGNATURE_MIN_WORD = 4


def signature(description: str | None) -> frozenset[str]:
    return frozenset(
        w for w in _SIGNATURE_WORD.findall((description or "").lower()) if len(w) >= SIGNATURE_MIN_WORD
    )


def signature_jaccard(left: str | None, right: str | None) -> float | None:
    """Share of distinct words the two descriptions have in common. `None` when
    either side has no description: absence is not dissimilarity."""
    a, b = signature(left), signature(right)
    if not a or not b:
        return None
    return len(a & b) / len(a | b)
