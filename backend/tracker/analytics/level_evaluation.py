"""Independent labels, leakage groups and sealed inputs for level evaluation.

This module reads frozen records only. It never writes canonical job fields or
reads the committed salary maps to manufacture a validation label.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from tracker.enrich.level_mapper import read_level, title_states_band
from tracker.lineage.normalize import normalize_title, title_key
from tracker.pay_period import effective_period
from tracker.schema import LevelBand, LevelBasis, RawJob
from tracker.taxonomy.locations import pay_country
from tracker.taxonomy.stated_level import stated_level


class LabelTier(str, Enum):
    PRINTED = "A"
    COMPANY = "B"
    GENERIC = "C"
    HYPOTHESIS = "D"


@dataclass(frozen=True)
class EvidenceLabel:
    job_id: int
    company: str
    title: str
    family: str
    track: str
    band: LevelBand
    tier: LabelTier
    source: str
    printed: str | None
    base_min: int
    base_max: int

    @property
    def unit(self) -> tuple[str, str, int, int]:
        return self.company, " ".join(self.title.lower().split()), self.base_min, self.base_max


def _text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    return value if isinstance(value, str) and value else None


def _integer(row: Mapping[str, object], key: str) -> int | None:
    value = row.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def usable_base(row: Mapping[str, object]) -> bool:
    locations = row.get("location_groups")
    if not isinstance(locations, list) or not all(isinstance(v, str) for v in locations):
        return False
    low, high = _integer(row, "disclosed_base_min"), _integer(row, "disclosed_base_max")
    currency = _text(row, "disclosed_currency")
    return bool(
        low is not None and high is not None and 0 < low <= high
        and pay_country(locations) == "US"
        and currency == "USD"
        and _text(row, "disclosed_pay_basis") == "base"
        and effective_period(_text(row, "disclosed_pay_period"), low, high, currency) == "year"
        and _text(row, "disclosed_confidence") == "high"
        and _text(row, "disclosed_source") in {"connector", "text", "page"}
    )


def independent_label(row: Mapping[str, object]) -> EvidenceLabel | None:
    """Read without salary or derived level fields, keeping label provenance."""
    if not usable_base(row):
        return None
    company, title, family = (_text(row, k) for k in ("company", "title", "family"))
    job_id = _integer(row, "id")
    if company is None or title is None or family is None or job_id is None:
        return None
    printed = _text(row, "raw_level")
    source = "structured_employer_grade"
    if printed is None:
        printed = stated_level(company, _text(row, "description_text"))
        source = "description_employer_grade"
    if printed is None:
        # A frozen capture can carry the text reader's result with its source.
        printed = _text(row, "independent_raw_level")
        source = "captured_employer_grade"
    raw = RawJob(company=company, req_id="", title=title, url="",
                 department=_text(row, "department"), team=_text(row, "team"), raw_level=printed)
    reading = read_level(raw, family)
    if not title_states_band(title, reading, printed, company):
        return None
    if reading.basis is LevelBasis.STATED:
        tier = LabelTier.PRINTED
    elif reading.basis is LevelBasis.COMPANY:
        tier, source = LabelTier.COMPANY, "company_title_vocabulary"
    elif reading.basis is LevelBasis.GENERIC:
        tier, source = LabelTier.GENERIC, "generic_title_words"
    else:
        return None
    low, high = _integer(row, "disclosed_base_min"), _integer(row, "disclosed_base_max")
    assert low is not None and high is not None
    return EvidenceLabel(job_id, company, title, family, _text(row, "track") or "unknown",
                         reading.band, tier, source, printed, low, high)


@dataclass(frozen=True)
class GroupInput:
    """Identity and text evidence only; no classified band or grade is accepted."""

    job_id: int
    company: str
    req_id: str = ""
    title: str = ""
    description: str = ""
    cluster_id: int | None = None
    place_set_id: int | None = None
    syndication_id: str | None = None


_CODE = re.compile(r"\b(?:IC|ICT|L|E|M|P|T)\d{1,2}\b|\b(?:level|grade|rung)\s*[:#-]?\s*\d+\b", re.I)
_AMOUNT = re.compile(r"\$\s*\d[\d,.]*(?:\s*[km])?|\b\d[\d,.]*(?:\s*[km])?\s*USD\b", re.I)
_WORDS = re.compile(r"\w+", re.UNICODE)


def _experience_years(match: re.Match[str]) -> bool:
    return (bool(re.match(r"level\b", match.group(), re.I))
            and bool(re.search(r"\bexperience\s+$", match.string[:match.start()], re.I))
            and bool(re.match(r"\s*(?:\+|(?:[-–—]|to)\s*\d+)?\s+years?\b",
                              match.string[match.end():], re.I)))


def _redact_codes(text: str, replacement: str) -> str:
    return _CODE.sub(lambda match: match.group() if _experience_years(match) else replacement, text)


def text_fingerprint(text: str) -> str | None:
    """A pay/grade-independent template key, absent on short or missing context."""
    cleaned = _CODE.sub(" ", _AMOUNT.sub(" money ", text.casefold()))
    words = _WORDS.findall(cleaned)
    if len(words) < 12:
        return None
    return hashlib.sha256(" ".join(words).encode()).hexdigest()


def leakage_groups(rows: Sequence[GroupInput]) -> dict[int, str]:
    """Keep linked identities and identical role templates in one evaluation partition.

    Semantic clusters only identify candidates; membership alone is insufficient
    to merge roles. Cross-employer grouping requires an explicit syndication id.
    """
    ids = [row.job_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate job id")
    parent = {job_id: job_id for job_id in ids}

    def root(job_id: int) -> int:
        while parent[job_id] != job_id:
            parent[job_id] = parent[parent[job_id]]
            job_id = parent[job_id]
        return job_id

    def union(a: int, b: int) -> None:
        a, b = root(a), root(b)
        parent[max(a, b)] = min(a, b)

    seen: dict[tuple[str, ...], int] = {}
    for row in sorted(rows, key=lambda r: r.job_id):
        keys: list[tuple[str, ...]] = []
        if row.req_id:
            keys.append(("req", row.company, row.req_id))
        if row.place_set_id is not None:
            keys.append(("places", row.company, str(row.place_set_id)))
        fingerprint = text_fingerprint(row.description)
        title = title_key(row.title)
        if fingerprint and title:
            keys.append(("template", row.company, title, fingerprint))
        if row.syndication_id:
            keys.append(("syndication", row.syndication_id))
        for key in keys:
            if key in seen:
                union(row.job_id, seen[key])
            else:
                seen[key] = row.job_id
    members: dict[int, list[int]] = defaultdict(list)
    for job_id in sorted(ids):
        members[root(job_id)].append(job_id)
    return {job_id: hashlib.sha256(",".join(map(str, group)).encode()).hexdigest()
            for group in members.values() for job_id in group}


class MaskMode(str, Enum):
    OPENING = "M1"
    TITLE = "M2"
    SIGNATURE = "M3"


def signature(row: Mapping[str, object]) -> tuple[object, ...]:
    keys = ("company", "family", "track", "disclosed_base_min", "disclosed_base_max")
    values = tuple(row.get(key) for key in keys)
    if any(value is None for value in values):
        raise ValueError("incomplete salary signature")
    return values


def sealed_ids(rows: Sequence[Mapping[str, object]], target: Mapping[str, object],
               mode: MaskMode) -> frozenset[int]:
    target_signature = signature(target) if mode is MaskMode.SIGNATURE else None
    ids: set[int] = set()
    for row in rows:
        if mode is MaskMode.OPENING:
            match = row.get("id") == target.get("id")
        elif mode is MaskMode.TITLE:
            match = (row.get("company") == target.get("company")
                     and normalize_title(_text(row, "title")) == normalize_title(_text(target, "title")))
        else:
            try:
                match = signature(row) == target_signature
            except ValueError:
                match = False
        if match:
            job_id = _integer(row, "id")
            if job_id is None:
                raise ValueError("missing job id")
            ids.add(job_id)
    if _integer(target, "id") not in ids:
        raise ValueError("target is absent from frozen evidence")
    return frozenset(ids)


_DERIVED = frozenset({
    "raw_level", "level_band", "level_basis", "level_confidence", "independent_raw_level",
    "independent_band", "independent_basis", "independent_confidence", "title_anchor",
    "embedding", "search_vector", "tsvector", "cached_features", "cached_feature_rows",
    "comp_low", "comp_median", "comp_high", "comp_provenance", "comp_sources",
    "comp_base_low", "comp_base_median", "comp_base_high", "comp_ref_fp",
    "grade", "grade_code", "rung", "band", "level", "employer_level",
    "cluster_id", "cluster_distance", "embedded_at", "embedded_tier",
    "comp_component", "comp_provider", "comp_as_of",
})
_SENIORITY = re.compile(r"\b(?:senior staff|senior|sr\.?|staff|principal|director|distinguished|fellow)\b", re.I)


def mask_inputs(row: Mapping[str, object], grades: Sequence[str], *, hard: bool = False) -> dict[str, object]:
    """Invalidate precomputed channels; callers rebuild features from masked facts."""
    patterns = []
    for grade in grades:
        for token in grade.split("/"):
            token = token.strip()
            if token and not token.isdecimal():
                patterns.append(re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)", re.I))
    if hard:
        patterns.append(_SENIORITY)

    numeric = {token.strip() for grade in grades for token in grade.split("/") if token.strip().isdecimal()}

    def title_mask(value: object) -> object:
        if isinstance(value, str):
            for token in numeric:
                value = re.sub(r"\b" + re.escape(token) + r"\s*$", "[withheld]", value)
        return value

    def mask(value: object) -> object:
        if isinstance(value, str):
            value = _redact_codes(value, "[withheld]")
            for pattern in patterns:
                value = pattern.sub("[withheld]", value)
            return value
        if isinstance(value, Mapping):
            return {str(key): mask(title_mask(v) if key == "title" else v)
                    for key, v in value.items() if key not in _DERIVED}
        if isinstance(value, list):
            return [mask(v) for v in value]
        return value

    return {key: mask(title_mask(value) if key == "title" else value)
            for key, value in row.items() if key not in _DERIVED}


def assert_no_grade_leak(inputs: object, grades: Sequence[str]) -> None:
    """Reject sealed codes and stale derived channels before a model reads inputs."""
    patterns = []
    for grade in grades:
        for token in grade.split("/"):
            if token.strip() and not token.strip().isdecimal():
                patterns.append(re.compile(r"(?<!\w)" + re.escape(token.strip()) + r"(?!\w)", re.I))
    if isinstance(inputs, str):
        if (any(not _experience_years(match) for match in _CODE.finditer(inputs))
                or any(pattern.search(inputs) for pattern in patterns)):
            raise ValueError("sealed employer grade in input")
    elif isinstance(inputs, Mapping):
        if _DERIVED.intersection(inputs):
            raise ValueError("stale derived input channel")
        title = inputs.get("title")
        if isinstance(title, str):
            numeric = {token.strip() for grade in grades for token in grade.split("/") if token.strip().isdecimal()}
            if any(re.search(r"\b" + re.escape(token) + r"\s*$", title) for token in numeric):
                raise ValueError("sealed numeric grade in title")
        for value in inputs.values():
            assert_no_grade_leak(value, grades)
    elif isinstance(inputs, (list, tuple)):
        for value in inputs:
            assert_no_grade_leak(value, grades)


def partition_reference(rows: Sequence[Mapping[str, object]], target: Mapping[str, object],
                        excluded: frozenset[int], mode: MaskMode) -> list[dict[str, object]]:
    """Remove held-out evidence, including atlas signatures without track metadata."""
    result: list[dict[str, object]] = []
    for row in rows:
        source_ids = row.get("source_job_ids")
        if isinstance(source_ids, list) and any(job_id in excluded for job_id in source_ids):
            continue
        if _integer(row, "job_id") in excluded:
            continue
        if mode is MaskMode.SIGNATURE and row.get("company") == target.get("company"):
            same = (row.get("family") == target.get("family")
                    and row.get("base_min") == target.get("disclosed_base_min")
                    and row.get("base_max") == target.get("disclosed_base_max")
                    and (row.get("track") is None or row.get("track") == target.get("track")))
            if same:
                continue
        if not isinstance(source_ids, list) and row.get("job_id") is None:
            keyed_range = all(row.get(key) is not None for key in ("company", "family", "base_min", "base_max"))
            if mode is not MaskMode.SIGNATURE or not keyed_range:
                raise ValueError("reference without source identities cannot prove isolation")
        result.append(dict(row))
    return result


#: A range pair within five percent on the average of both endpoints.
NEAR = math.log(1.05)


class MatchRule(str, Enum):
    EXACT = "exact"
    NEAREST_NEAR = "nearest_near"
    NEAREST = "nearest"
    WITHIN_NEAR = "within_near"
    NEAREST_FIVE = "nearest_five"


@dataclass(frozen=True)
class Vote:
    band: LevelBand
    identities: int
    support: int
    share: float
    anchors: tuple[int, ...]


def endpoint_distance(a: EvidenceLabel, b: EvidenceLabel) -> float:
    """Average absolute log gap over both endpoints, so width counts as position does."""
    return (abs(math.log(a.base_min / b.base_min)) + abs(math.log(a.base_max / b.base_max))) / 2


def match_anchors(target: EvidenceLabel, pool: Sequence[EvidenceLabel],
                  rule: MatchRule) -> list[EvidenceLabel]:
    """Anchors a rule admits for one target, before any vote is counted."""
    if rule is MatchRule.EXACT:
        return [a for a in pool if (a.base_min, a.base_max) == (target.base_min, target.base_max)]
    if not pool:
        return []
    distance = {a.job_id: endpoint_distance(target, a) for a in pool}
    if rule is MatchRule.WITHIN_NEAR:
        return [a for a in pool if distance[a.job_id] <= NEAR]
    if rule is MatchRule.NEAREST_FIVE:
        return sorted(pool, key=lambda a: (distance[a.job_id], a.job_id))[:5]
    closest = min(distance.values())
    if rule is MatchRule.NEAREST_NEAR and closest > NEAR:
        return []
    return [a for a in pool if distance[a.job_id] - closest < 1e-10]


def majority_band(candidates: Sequence[EvidenceLabel], *, floor: float = 0.8,
                  minimum: int = 2, per_employer: bool = False) -> Vote | None:
    """One identity is one vote, so repeated requisitions cannot manufacture support.

    `per_employer` divides each employer's weight by how many anchors it brought,
    so a single employer's posting volume cannot carry a cross-employer vote.
    """
    if not candidates:
        return None
    keys: set[object] = ({a.company for a in candidates} if per_employer
                         else {a.unit[:2] for a in candidates})
    if len(keys) < minimum:
        return None
    weights: dict[LevelBand, float] = defaultdict(float)
    brought = Counter(a.company for a in candidates)
    for anchor in candidates:
        weights[anchor.band] += 1 / brought[anchor.company] if per_employer else 1
    total = sum(weights.values())
    band, weight = max(weights.items(), key=lambda item: (item[1], item[0].value))
    if weight / total < floor:
        return None
    return Vote(band, len(keys), len(candidates), weight / total,
                tuple(sorted(a.job_id for a in candidates)))


def observed_before(row: Mapping[str, object], cutoff: datetime) -> bool:
    """Availability comes from capture time, never a backdated publication date."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff requires timezone")
    captured = _text(row, "observed_at")
    if captured is None:
        return False
    observed = datetime.fromisoformat(captured)
    if observed.tzinfo is None:
        raise ValueError("observation requires timezone")
    return observed <= cutoff
