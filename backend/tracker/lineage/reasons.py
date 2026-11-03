"""Why the detectors paired two postings, as codes the dashboard words.

The detectors record their reasons as English for diagnostics
(`evidence.reasons`). A reader is told them from the numbers the evidence
also keeps, as a code and its figures, which the dashboard says from its
catalog in the reader's language. Derived when read, so rows stored before
codes existed say them too.

Codes, with the parameters each takes:

- `same_title`: the two postings carry the same title.
- `titles_alike` {pct}: their titles share that share of their words.
- `descriptions_alike` {pct}: their descriptions read that alike.
- `listed_at_once`: both were open at the same time.
- `same_department` / `department_unknown`: a twin's department matches, or
  one of the two states none.
- `passages_differ` {earlier, later}: passages only the earlier, and only the
  newer, posting has.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Said = dict[str, Any]


def _pct(value: Any) -> int | None:
    return round(float(value) * 100) if isinstance(value, int | float) else None


def _say(code: str, **params: int | None) -> Said | None:
    if any(value is None for value in params.values()):
        return None
    return {"code": code, "params": params}


def duplicate_reasons(method: str, relation: str, evidence: Mapping[str, Any]) -> list[Said]:
    """A `job_lineage_link`'s reasons, from its method and evidence."""
    out = []
    if method == "title+embedding":
        out.append(_say("same_title"))
    if method == "title_jaccard":
        out.append(_say("titles_alike", pct=_pct(evidence.get("title_jaccard"))))
    if method in {"title+embedding", "embedding", "title_jaccard"}:
        out.append(_say("descriptions_alike", pct=_pct(evidence.get("cosine"))))
    if relation == "duplicate":
        out.append(_say("listed_at_once"))
    return [said for said in out if said is not None]


def twin_reasons(evidence: Mapping[str, Any]) -> list[Said]:
    """A `job_twin_link`'s reasons, from its anchors and description diff."""
    anchors = evidence.get("anchors") or {}
    diff = evidence.get("description_diff") or {}
    out = [
        _say("same_title") if anchors.get("display_title_equal")
        else _say("titles_alike", pct=_pct(anchors.get("title_similarity"))),
        _say("same_department") if anchors.get("department_relation") == "same"
        else _say("department_unknown") if anchors.get("department_relation") == "missing" else None,
        _say("passages_differ", earlier=diff.get("left_only_count"), later=diff.get("right_only_count"))
        if diff else None,
    ]
    return [said for said in out if said is not None]
