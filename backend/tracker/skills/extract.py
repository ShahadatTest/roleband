"""Deterministic skills/qualifications extraction.

Pipeline per job: segment stored text -> guarded alias matching per evidence
unit -> grounding validation -> importance/confidence aggregation -> atomic
replacement of job_skills / job_skill_evidence / job_qualifications.

Hard rules encoded here:
- A catalogue match is only a candidate; benefit/legal/application units and
  negated statements never produce requirement evidence.
- Every stored evidence quote is an exact substring of the stored section
  content with round-tripping offsets (grounding validator; failures are
  logged and dropped, never downgraded).
- Importance = employer emphasis (max evidence strength + small independent-
  evidence bonus), never mention counts. Confidence is separate; this
  deterministic pass emits `high` only.
- Years of experience are read by one grammar (`years.stated_years`):
  an experience row keeps every number its line states, and the posting's
  headline requirement (`required_years`) is derived from the rows, never
  parsed a second time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, JobQualification, JobSkill, JobSkillEvidence
from tracker.skills.catalog import AliasSpec, Catalog, get_catalog
from tracker.skills.segment import EvidenceUnit, affirmed_text, segment_job
from tracker.skills.sync import sync_catalog
from tracker.skills.years import stated_years

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "2.1.1"

# Aspects that can never ground a skill/qualification (exclusion contexts).
_EXCLUDED_ASPECTS = frozenset({"benefit", "legal", "application"})

_BAND_THRESHOLDS = (("core", 75), ("important", 55), ("supporting", 35))
_MODALITY_RANK = {"required": 3, "preferred": 2, "used_in_role": 1, "context": 0}
_PROFICIENCY_RANK = {
    "expert": 4, "proficient": 3, "hands_on": 2, "familiarity": 1, "unspecified": 0,
}

_EXPERT_CUE = re.compile(r"deep (?:expertise|experience|understanding)|expert(?:ise)? (?:in|with)|advanced (?:knowledge|experience)", re.IGNORECASE)
_PROFICIENT_CUE = re.compile(r"proficien|strong (?:experience|background|knowledge|skills)|extensive experience", re.IGNORECASE)
_HANDS_ON_CUE = re.compile(r"hands[\s-]on|experience (?:with|in|building|shipping)", re.IGNORECASE)
_FAMILIARITY_CUE = re.compile(r"familiar(?:ity)?|exposure to|awareness of", re.IGNORECASE)

# --- Qualification cues (kind, pattern) — matched in minimum/preferred units only.
# "experience" is not a pattern: a unit is an experience row when it states years.
_QUAL_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("education", re.compile(r"\b(?:bachelor|master|ph\.?d|doctorate|b\.?s\.?|m\.?s\.?|mba)\b|degree in", re.IGNORECASE)),
    ("credential", re.compile(r"\bcertif\w+|cissp|pmp\b|licens\w+", re.IGNORECASE)),
    ("clearance", re.compile(r"security clearance|ts/sci|top secret", re.IGNORECASE)),
    ("eligibility", re.compile(r"authoriz\w+ to work|work authorization|visa sponsorship|eligible to work", re.IGNORECASE)),
    ("travel", re.compile(r"travel\s+(?:up to\s+)?\d{1,3}\s*%|willing(?:ness)? to travel", re.IGNORECASE)),
    ("schedule", re.compile(r"on[\s-]call|weekend|night shift|shift work", re.IGNORECASE)),
)


def requirements_content_hash(title: str | None, sections: list[dict] | None) -> str:
    """Hash of exactly the text extraction reads: title + canonical sections JSON."""
    payload = json.dumps(
        {"title": title or "", "sections": sections or []},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Hit:
    """One validated alias match inside one evidence unit."""

    concept_slug: str
    alias: AliasSpec
    unit: EvidenceUnit
    start: int  # span within unit.text
    end: int


def _spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def match_unit(catalog: Catalog, unit: EvidenceUnit) -> list[Hit]:
    """Run every guarded alias over one unit; apply context guards + dedupe.

    Guard semantics: `required_context` must match somewhere in the unit;
    an `excluded_context` match overlapping the alias hit kills that hit
    (so "medical coverage" kills `medical` but "Java and JavaScript" keeps
    `Java`). Overlapping hits for different concepts keep the longer span
    (child/specific beats parent: "AWS S3" suppresses "AWS"); a parent concept
    hit is also dropped when any child concept matched in the same unit.
    """
    hits: list[Hit] = []
    for alias in catalog.all_aliases():
        if alias.required_re and not alias.required_re.search(unit.text):
            continue
        excluded_spans = (
            [m.span() for m in alias.excluded_re.finditer(unit.text)] if alias.excluded_re else []
        )
        for m in alias.pattern.finditer(unit.text):
            if any(_spans_overlap(m.start(), m.end(), s, e) for s, e in excluded_spans):
                continue
            hits.append(Hit(alias.concept_slug, alias, unit, m.start(), m.end()))

    # Longer span wins between overlapping hits of different concepts;
    # same-concept duplicates collapse to one hit per unit later.
    kept: list[Hit] = []
    for h in hits:
        shadowed = any(
            other is not h
            and other.concept_slug != h.concept_slug
            and _spans_overlap(h.start, h.end, other.start, other.end)
            and (other.end - other.start) > (h.end - h.start)
            for other in hits
        )
        if not shadowed:
            kept.append(h)

    # Parent suppression within a unit: the child conveys the information.
    matched_slugs = {h.concept_slug for h in kept}
    ancestors_present: set[str] = set()
    for slug in matched_slugs:
        concept = catalog.get(slug)
        while concept and concept.parent:
            ancestors_present.add(concept.parent)
            concept = catalog.get(concept.parent)
    return [h for h in kept if h.concept_slug not in (ancestors_present & matched_slugs)]


def _unit_base_score(unit: EvidenceUnit) -> int | None:
    """Spec evidence table. None = reject (never evidence), 0 = context-only."""
    if unit.aspect in _EXCLUDED_ASPECTS:
        return None
    if unit.negated:
        return None  # explicitly not required — reject as requirement evidence
    if unit.actor in ("team", "company"):
        return 0
    if unit.aspect == "minimum":
        return 80
    if unit.aspect == "preferred":
        return 60
    if unit.aspect == "responsibility":
        return 45
    # Role/team description, title, other candidate/role-facing context.
    return 20


def _unit_proficiency(text: str) -> str:
    if _EXPERT_CUE.search(text):
        return "expert"
    if _PROFICIENT_CUE.search(text):
        return "proficient"
    if _HANDS_ON_CUE.search(text):
        return "hands_on"
    if _FAMILIARITY_CUE.search(text):
        return "familiarity"
    return "unspecified"


def _unit_score(unit: EvidenceUnit) -> tuple[int, str] | None:
    """(score, proficiency) for one qualifying unit, or None when rejected."""
    base = _unit_base_score(unit)
    if base is None:
        return None
    proficiency = _unit_proficiency(unit.text)
    bonus = 0
    if proficiency == "expert":
        bonus += 10
    elif proficiency in ("proficient", "hands_on") or _unit_years(unit):
        bonus += 5
    return (max(0, min(100, base + bonus if base > 0 else 0)), proficiency)


def _band(score: int) -> str:
    for band, threshold in _BAND_THRESHOLDS:
        if score >= threshold:
            return band
    return "context"


@dataclass
class ExtractionResult:
    skills: list[dict]
    qualifications: list[dict]


def extract_job(catalog: Catalog, title: str | None, sections: list[dict] | None) -> ExtractionResult:
    """Pure extraction for one posting. No DB. Returns aggregated skill dicts
    (with evidence lists) + qualification dicts, all grounded."""
    units = segment_job(title, sections)

    # Grounding source map: section content by (key, occurrence). Sections can
    # repeat a key, so ground against the exact section list order.
    section_contents: list[tuple[str | None, str]] = [
        (s.get("key"), s.get("content") or "") for s in (sections or [])
    ]

    def grounded(unit: EvidenceUnit) -> bool:
        if unit.section_key is None and unit.section_title is None:
            return (title or "")[unit.start_offset:unit.end_offset] == unit.text
        for key, content in section_contents:
            if key == unit.section_key and content[unit.start_offset:unit.end_offset] == unit.text:
                return True
        return False

    # --- skills -----------------------------------------------------------
    by_concept: dict[str, list[tuple[Hit, int, str]]] = {}
    for unit in units:
        scored = _unit_score(unit)
        for hit in match_unit(catalog, unit):
            if not grounded(unit):
                logger.warning("grounding failure dropped: %s in %r", hit.concept_slug, unit.text[:60])
                continue
            if scored is None:
                continue  # benefit/legal/application/negated: no evidence at all
            score, proficiency = scored
            seen = by_concept.setdefault(hit.concept_slug, [])
            # One evidence row per (concept, unit): collapse multi-alias hits.
            if any(h.unit is unit for h, _, _ in seen):
                continue
            seen.append((hit, score, proficiency))

    skills: list[dict] = []
    for slug, evidence in by_concept.items():
        concept = catalog.get(slug)
        qualifying = [(h, s, p) for h, s, p in evidence if s > 0]
        best = max((s for _, s, _ in qualifying), default=0)
        independent_bonus = min(10, 5 * max(0, len(qualifying) - 1))
        score = max(0, min(100, best + independent_bonus))
        modality = max(
            (h.unit.modality for h, s, _ in qualifying),
            key=lambda m: _MODALITY_RANK.get(m, 0),
            default="context",
        )
        proficiency = max(
            (p for _, s, p in qualifying),
            key=lambda p: _PROFICIENCY_RANK.get(p, 0),
            default="unspecified",
        )
        skills.append(
            {
                "slug": slug,
                "facet": concept.facet,
                "importance_score": score,
                "importance_band": _band(score),
                "confidence": "high",
                "modality": modality,
                "proficiency": proficiency,
                "evidence_count": len(qualifying),
                "evidence": [
                    {
                        "section_key": h.unit.section_key,
                        "section_title": h.unit.section_title,
                        "unit_index": h.unit.unit_index,
                        "quote": h.unit.text,
                        "start_offset": h.unit.start_offset,
                        "end_offset": h.unit.end_offset,
                        "aspect": h.unit.aspect,
                        "modality": h.unit.modality,
                        "proficiency": p if p != "unspecified" else None,
                        "years": _first_years(h.unit),
                        "actor": h.unit.actor,
                        "confidence": "high",
                        "score": s,
                    }
                    for h, s, p in evidence
                ],
            }
        )

    # --- qualifications ----------------------------------------------------
    qualifications: list[dict] = []
    seen_quals: set[tuple[str, str]] = set()
    for unit in units:
        if unit.aspect not in ("minimum", "preferred"):
            continue
        # A negated unit still states what its other sentences require.
        text = affirmed_text(unit.text) if unit.negated else unit.text
        if not text or not grounded(unit):
            continue
        years = stated_years(text, requirement_line=True)
        kinds: list[tuple[str, dict | None]] = (
            # Every number the line states, and its headline (the largest: a
            # degree ladder's base, a clause's main requirement).
            [("experience", {"years": float(max(years)), "years_stated": [float(y) for y in years]})]
            if years else []
        )
        kinds += [(kind, None) for kind, pattern in _QUAL_RULES if pattern.search(text)]
        for kind, value in kinds:
            key = (kind, unit.text)
            if key in seen_quals:
                continue
            seen_quals.add(key)
            qualifications.append(
                {
                    "kind": kind,
                    "display": unit.text if len(unit.text) <= 160 else unit.text[:157] + "…",
                    "value": value,
                    "modality": "required" if unit.aspect == "minimum" else "preferred",
                    "confidence": "high",
                    "section_key": unit.section_key,
                    "section_title": unit.section_title,
                    "quote": unit.text,
                    "start_offset": unit.start_offset,
                    "end_offset": unit.end_offset,
                }
            )

    return ExtractionResult(skills=skills, qualifications=qualifications)


def _unit_years(unit: EvidenceUnit) -> list[int]:
    """Every years statement in a unit; a line of the minimum or preferred list
    states one without saying "experience" ("8 years working on X")."""
    return stated_years(unit.text, requirement_line=unit.aspect in ("minimum", "preferred"))


def _first_years(unit: EvidenceUnit) -> float | None:
    years = _unit_years(unit)
    return float(years[0]) if years else None


def required_years(qualifications: Iterable[Mapping]) -> float | None:
    """The posting's headline years requirement: the largest a REQUIRED experience
    row states, or None. Preferred years never count: "12+ years" under
    Preferred Qualifications is not what the employer requires."""
    found = [
        q["value"]["years"]
        for q in qualifications
        if q["kind"] == "experience" and q["modality"] == "required" and q.get("value")
    ]
    return max(found, default=None)


async def extract_requirements(
    session: AsyncSession,
    job_ids: list[int],
    *,
    force: bool = False,
    catalog: Catalog | None = None,
    id_by_slug: dict[str, int] | None = None,
) -> int:
    """Extract + persist requirements for the given jobs (incremental).

    Skips a job when its content hash, extractor version, and taxonomy version
    all match — unless `force`. Replaces each processed job's rows atomically
    (evidence cascades with its job_skill rows). Returns jobs (re)processed.
    """
    if not job_ids:
        return 0

    cat = catalog or get_catalog()
    if id_by_slug is None:
        id_by_slug = await sync_catalog(session, cat)

    jobs = (await session.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
    processed = 0
    for job in jobs:
        new_hash = requirements_content_hash(job.title, job.description_sections)
        if (
            not force
            and job.requirements_content_hash == new_hash
            and job.requirements_extractor_version == EXTRACTOR_VERSION
            and job.requirements_taxonomy_version == cat.taxonomy_version
        ):
            continue

        result = extract_job(cat, job.title, job.description_sections)

        await session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
        await session.execute(delete(JobQualification).where(JobQualification.job_id == job.id))

        for s in result.skills:
            concept_id = id_by_slug.get(s["slug"])
            if concept_id is None:  # catalogue/DB drift — refuse silently wrong writes
                logger.error("no concept row for slug %s; skipping", s["slug"])
                continue
            job_skill = JobSkill(
                job_id=job.id,
                concept_id=concept_id,
                importance_score=s["importance_score"],
                importance_band=s["importance_band"],
                confidence=s["confidence"],
                modality=s["modality"],
                proficiency=s["proficiency"],
                evidence_count=s["evidence_count"],
                content_hash=new_hash,
                extractor_version=EXTRACTOR_VERSION,
                taxonomy_version=cat.taxonomy_version,
            )
            job_skill.evidence = [
                JobSkillEvidence(job_id=job.id, concept_id=concept_id, extractor="dictionary", **e)
                for e in s["evidence"]
            ]
            session.add(job_skill)

        for q in result.qualifications:
            session.add(
                JobQualification(job_id=job.id, extractor_version=EXTRACTOR_VERSION, **q)
            )

        job.required_years = required_years(result.qualifications)
        job.requirements_content_hash = new_hash
        job.requirements_extractor_version = EXTRACTOR_VERSION
        job.requirements_taxonomy_version = cat.taxonomy_version
        job.requirements_extracted_at = func.now()
        processed += 1

    logger.info("requirements extraction: %d/%d jobs processed", processed, len(jobs))
    return processed
