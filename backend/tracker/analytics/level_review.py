"""Independent source review and explicit adjudication over frozen job evidence."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from tracker.schema import LEVEL_BAND_ORDER

STRATA = {"high_confidence": 250, "representative": 250, "edge": 100}
PROTOCOL_VERSION = "1.0.0"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _index(rows: Sequence[Mapping[str, Any]], groups: Mapping[int, str]) -> dict[int, Mapping[str, Any]]:
    index = {}
    for row in rows:
        job_id = row.get("id")
        if type(job_id) is not int or job_id in index:
            raise ValueError("unique integer job identities required")
        if not isinstance(groups.get(job_id), str) or not groups[job_id]:
            raise ValueError("every case requires a frozen group")
        if not isinstance(row.get("company"), str) or not row["company"]:
            raise ValueError("every case requires a company")
        index[job_id] = row
    return index


def _stratum(row: Mapping[str, Any], employers: Counter[str]) -> str:
    low, high = row.get("disclosed_base_min"), row.get("disclosed_base_max")
    if type(low) is not int or type(high) is not int or not 0 < low <= high:
        raise ValueError("ordered positive frozen range required")
    width = (high - low) / low
    employer_size = "small" if employers[row["company"]] < 10 else "medium" if employers[row["company"]] < 100 else "large"
    return json.dumps([employer_size, row.get("family"), row.get("track"), sorted(row.get("location_groups") or []),
                       "narrow" if width <= .25 else "medium" if width <= .5 else "wide", row.get("level_confidence")])


def draw_representative(rows: Sequence[Mapping[str, Any]], groups: Mapping[int, str], *, seed: int,
                        count: int = 250) -> list[int]:
    """Allocate proportionally across frozen strata, with group and employer caps.

    Employer size means representation in the frozen cohort, not headcount.
    Group exclusions and the Apple ceiling can change inclusion probabilities;
    consumers retain the selected strata rather than assume a self-weighting draw.
    """
    if type(count) is not int or count <= 0:
        raise ValueError("positive sample count required")
    index = _index(rows, groups)
    employers = Counter(row["company"] for row in rows)
    buckets: dict[str, list[int]] = defaultdict(list)
    for job_id, row in sorted(index.items()):
        buckets[_stratum(row, employers)].append(job_id)
    rng = random.Random(seed)
    for key in sorted(buckets):
        rng.shuffle(buckets[key])
    quotas = {key: count * len(ids) / len(rows) for key, ids in buckets.items()}
    selected: list[int] = []
    seen: set[str] = set()
    actual: Counter[str] = Counter()
    apple = 0
    cap = math.floor(count * .4)
    while len(selected) < count:
        available = {}
        for key, ids in buckets.items():
            while ids and (groups[ids[-1]] in seen or index[ids[-1]]["company"].casefold() == "apple" and apple >= cap):
                ids.pop()
            if ids:
                available[key] = quotas[key] - actual[key]
        if not available:
            raise ValueError("insufficient group-disjoint cases within employer ceiling")
        key = min(available, key=lambda k: (-available[k], k))
        job_id = buckets[key].pop()
        selected.append(job_id)
        seen.add(groups[job_id])
        actual[key] += 1
        apple += index[job_id]["company"].casefold() == "apple"
    return selected


def prepare_review(rows: Sequence[Mapping[str, Any]], groups: Mapping[int, str],
                   selections: Mapping[str, list[int]], *, high_confidence_ids: set[int],
                   seed: int, reviewers: tuple[str, str]) -> dict[str, Any]:
    """Produce separate blinded packets and a private assignment key."""
    index = _index(rows, groups)
    if (len(reviewers) != 2 or any(not isinstance(r, str) or not r.strip() for r in reviewers)
            or len({r.strip().casefold() for r in reviewers}) != 2):
        raise ValueError("two distinct reviewers required")
    if set(selections) != set(STRATA) or any(len(selections[s]) != n for s, n in STRATA.items()):
        raise ValueError("exact review stratum sizes required")
    selected = [job_id for ids in selections.values() for job_id in ids]
    if any(type(i) is not int or i not in index for i in selected) or len(set(selected)) != 600:
        raise ValueError("600 distinct frozen case identities required")
    if len({groups[i] for i in selected}) != 600:
        raise ValueError("review cases must be group-disjoint")
    if not set(selections["high_confidence"]) <= high_confidence_ids:
        raise ValueError("high-confidence stratum requires the frozen candidate pool")
    if any(sum(index[i]["company"].casefold() == "apple" for i in ids) > math.floor(len(ids) * .4)
           for ids in selections.values()):
        raise ValueError("Apple exceeds 40% of a review stratum")
    rng = random.Random(seed)
    repeated = set(rng.sample(sorted(selected), 150))
    packets: dict[str, list[dict[str, Any]]] = {r: [] for r in reviewers}
    cases = []
    assignments = []
    for stratum in STRATA:
        for job_id in selections[stratum]:
            row = index[job_id]
            source = {key: row.get(key) for key in ("company", "title", "description_text")}
            if any(not isinstance(value, str) or not value.strip() for value in source.values()):
                raise ValueError("complete source title and description required")
            cases.append({"job_id": job_id, "group": groups[job_id], "stratum": stratum,
                          "source": source, "source_sha256": _digest(source)})
            for reviewer in reviewers[:2 if job_id in repeated else 1]:
                case_id = _digest([PROTOCOL_VERSION, seed, job_id, reviewer])[:24]
                packets[reviewer].append({"case_id": case_id, **source})
                assignments.append({"case_id": case_id, "job_id": job_id, "reviewer": reviewer})
    for reviewer in reviewers:
        rng.shuffle(packets[reviewer])
    sealed = {"protocol_version": PROTOCOL_VERSION, "cases": cases, "assignments": assignments}
    return {"packets": packets, "sealed": sealed, "sealed_sha256": _digest(sealed)}


def _cases(sealed: Mapping[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    if sealed.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported review protocol")
    cases = {case["job_id"]: case for case in sealed["cases"]}
    assignments = {a["case_id"]: a for a in sealed["assignments"]}
    if len(cases) != 600 or len(sealed["cases"]) != 600 or len(assignments) != 750 or len(sealed["assignments"]) != 750:
        raise ValueError("incomplete or duplicate case/assignment key")
    if len({case["group"] for case in cases.values()}) != 600:
        raise ValueError("review key reuses a group")
    reviewers: dict[int, set[str]] = defaultdict(set)
    reviewer_counts: Counter[str] = Counter()
    for assignment in assignments.values():
        if assignment["job_id"] not in cases or not isinstance(assignment["reviewer"], str) or not assignment["reviewer"].strip():
            raise ValueError("invalid assignment key")
        reviewers[assignment["job_id"]].add(assignment["reviewer"].strip().casefold())
        reviewer_counts[assignment["reviewer"].strip().casefold()] += 1
    if (Counter(map(len, reviewers.values())) != {1: 450, 2: 150}
            or sorted(reviewer_counts.values()) != [150, 600]):
        raise ValueError("150 independent double assignments required")
    if Counter(case["stratum"] for case in cases.values()) != STRATA:
        raise ValueError("invalid review stratum counts")
    for stratum, size in STRATA.items():
        if sum(c["source"]["company"].casefold() == "apple" for c in cases.values() if c["stratum"] == stratum) > size * .4:
            raise ValueError("Apple exceeds 40% of a review stratum")
    if any(set(c["source"]) != {"company", "title", "description_text"}
           or _digest(c["source"]) != c["source_sha256"] for c in cases.values()):
        raise ValueError("source fingerprint changed")
    return cases, assignments


def _label(label: Mapping[str, Any], source: Mapping[str, str]) -> tuple[str, ...]:
    if label.get("method") != "human":
        raise ValueError("explicit human review required; model prelabels are not truth")
    bands = label.get("bands")
    if (not isinstance(bands, list) or any(not isinstance(b, str) or b not in LEVEL_BAND_ORDER for b in bands)
            or len(set(bands)) != len(bands) or type(label.get("not_identifiable")) is not bool
            or label["not_identifiable"] != (not bands)):
        raise ValueError("permissible bands or not-identifiable label required")
    if label.get("confidence") not in {"low", "medium", "high"} or not isinstance(label.get("reason"), str) or not label["reason"].strip():
        raise ValueError("review confidence and reason required")
    evidence = label.get("evidence")
    if not isinstance(evidence, list) or bands and not evidence:
        raise ValueError("a band requires grounded quote evidence")
    for span in evidence:
        if not isinstance(span, dict):
            raise ValueError("invalid quote evidence")
        field, start, end, quote = (span.get(k) for k in ("field", "start", "end", "quote"))
        content = source.get(field) if isinstance(field, str) and field in {"title", "description_text"} else None
        if (content is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(content) or content[start:end] != quote):
            raise ValueError("review quote does not ground in the shown source")
    return tuple(sorted(bands, key=LEVEL_BAND_ORDER.__getitem__))


def validate_reviews(sealed: Mapping[str, Any], responses: Sequence[Mapping[str, Any]], *, complete: bool = True) -> dict[str, Any]:
    """Collect all blind readings without turning agreement into adjudication."""
    cases, assignments = _cases(sealed)
    seen = set()
    labels: dict[int, dict[str, tuple[str, ...]]] = defaultdict(dict)
    for response in responses:
        case_id = response.get("case_id")
        if not isinstance(case_id, str) or case_id not in assignments or case_id in seen:
            raise ValueError("unknown or duplicate review assignment")
        assignment = assignments[case_id]
        if response.get("reviewer") != assignment["reviewer"]:
            raise ValueError("response reviewer differs from blind assignment")
        labels[assignment["job_id"]][assignment["reviewer"]] = _label(response, cases[assignment["job_id"]]["source"])
        seen.add(case_id)
    if complete and seen != assignments.keys():
        raise ValueError("missing review assignments")
    # Set-valued judgments are categories; no arbitrary band resolves an ambiguous reading.
    pairs = [tuple(readings[r] for r in sorted(readings)) for readings in labels.values() if len(readings) == 2]
    observed = sum(a == b for a, b in pairs) / len(pairs) if pairs else None
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    chance = sum(left[k] * right[k] for k in left) / len(pairs) ** 2 if pairs else None
    kappa = (observed - chance) / (1 - chance) if observed is not None and chance is not None and chance < 1 else None
    return {"reviewed_cases": len(labels), "double_reviewed": len(pairs), "adjudicated": False,
            "complete": len(seen) == len(assignments), "readings": len(seen), "expected_readings": len(assignments),
            "sealed_sha256": _digest(sealed), "reviews_sha256": _digest(responses),
            "agreement": {"exact_set_agreement": observed, "kappa": kappa,
                          "categories": "permissible label sets, including not identifiable",
                          "undefined_reason": ("no paired readings" if not pairs else "only one observed category") if kappa is None else None}}


def adjudicate(sealed: Mapping[str, Any], responses: Sequence[Mapping[str, Any]],
               decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Seal explicit source-backed decisions; neither votes nor model outputs decide."""
    review = validate_reviews(sealed, responses)
    cases, _ = _cases(sealed)
    labels = []
    seen = set()
    for decision in decisions:
        job_id = decision.get("job_id")
        if type(job_id) is not int or job_id not in cases or job_id in seen:
            raise ValueError("unknown or duplicate adjudication")
        if not isinstance(decision.get("adjudicator"), str) or not decision["adjudicator"].strip():
            raise ValueError("explicit adjudicator required")
        _label(decision, cases[job_id]["source"])
        labels.append(dict(decision) | {"group": cases[job_id]["group"], "stratum": cases[job_id]["stratum"],
                                        "source_sha256": cases[job_id]["source_sha256"]})
        seen.add(job_id)
    if seen != cases.keys():
        raise ValueError("missing explicit adjudication")
    counts = Counter("not_identifiable" if row["not_identifiable"] else "single_band" if len(row["bands"]) == 1 else "ambiguous"
                     for row in labels)
    return {"adjudicated": True, "cases": len(labels), "labels": labels, "review": review,
            "label_counts": {key: counts[key] for key in ("single_band", "ambiguous", "not_identifiable")},
            "decisions_sha256": _digest(decisions), "authority": "adjudicated scope benchmark; not employer intent"}
