"""`requirements` detail block: state machine, launch-policy filters, and the
no-evidence-no-skill contract of `_job_requirements`."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from tracker.api.routers.jobs import _job_requirements
from tracker.db.models import Job, JobQualification, JobSkill, JobSkillEvidence, SkillConcept

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _job(**over) -> Job:
    j = Job()
    j.id = 1
    j.company = "acme"
    j.title = "Senior Engineer"
    j.description_sections = [
        {"key": "minimum_qualifications", "title": "Minimum Qualifications", "content": "Python."}
    ]
    j.requirements_extracted_at = NOW
    j.requirements_extractor_version = "2.0.0"
    for k, v in over.items():
        setattr(j, k, v)
    return j


def _concept(concept_id=10, slug="python", facet="technology") -> SkillConcept:
    c = SkillConcept()
    c.id = concept_id
    c.slug = slug
    c.display = slug.title()
    c.facet = facet
    c.category = "language"
    c.status = "active"
    return c


def _skill(concept_id=10, band="core", score=85, confidence="high", evidence_scores=(80,)) -> JobSkill:
    s = JobSkill()
    s.job_id = 1
    s.concept_id = concept_id
    s.importance_band = band
    s.importance_score = score
    s.confidence = confidence
    s.modality = "required"
    s.proficiency = "unspecified"
    s.evidence_count = len(evidence_scores)
    s.evidence = []
    for i, ev_score in enumerate(evidence_scores):
        e = JobSkillEvidence()
        e.section_key = "minimum_qualifications"
        e.section_title = "Minimum Qualifications"
        e.unit_index = i
        e.quote = "Python."
        e.start_offset = 0
        e.end_offset = 7
        e.aspect = "minimum"
        e.modality = "required"
        e.actor = "candidate"
        e.confidence = "high"
        e.score = ev_score
        s.evidence.append(e)
    return s


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Scalars(_Result):
    pass


class FakeSession:
    """Returns canned (JobSkill, SkillConcept) pairs then JobQualification rows."""

    def __init__(self, skill_pairs, quals=()):
        self.skill_pairs = skill_pairs
        self.quals = quals

    async def execute(self, stmt):
        return _Result(self.skill_pairs)

    async def scalars(self, stmt):
        return _Scalars(self.quals)


def _run(coro):
    return asyncio.run(coro)


def test_not_extracted_with_text_is_pending():
    job = _job(requirements_extracted_at=None, requirements_extractor_version=None)
    out = _run(_job_requirements(FakeSession([]), job))
    assert out["state"] == "pending"
    assert out["skills"] == [] and out["qualifications"] == []


def test_not_extracted_without_text_is_unavailable():
    job = _job(
        requirements_extracted_at=None,
        requirements_extractor_version=None,
        description_sections=[],
        description_text=None,
    )
    out = _run(_job_requirements(FakeSession([]), job))
    assert out["state"] == "unavailable"


def test_ready_serializes_skill_with_evidence():
    out = _run(_job_requirements(FakeSession([(_skill(), _concept())]), _job()))
    assert out["state"] == "ready"
    assert out["extractor_version"] == "2.0.0"
    (skill,) = out["skills"]
    assert skill["slug"] == "python"
    assert skill["importance_band"] == "core"
    assert skill["evidence"][0]["quote"] == "Python."
    assert skill["evidence"][0]["section_key"] == "minimum_qualifications"


def test_skill_without_displayable_evidence_is_dropped():
    # All evidence units scored 0 (team/company context): association must not
    # surface even if a band slipped through — no evidence, no displayed skill.
    out = _run(
        _job_requirements(
            FakeSession([(_skill(evidence_scores=(0,)), _concept())]), _job()
        )
    )
    assert out["skills"] == []


def test_qualifications_serialize_with_grounding():
    q = JobQualification()
    q.id = 5
    q.job_id = 1
    q.kind = "experience"
    q.display = "8+ years of software engineering experience."
    q.modality = "required"
    q.confidence = "high"
    q.section_key = "minimum_qualifications"
    q.section_title = "Minimum Qualifications"
    q.quote = "8+ years of software engineering experience."
    q.start_offset = 0
    q.end_offset = 45
    out = _run(_job_requirements(FakeSession([], quals=[q]), _job()))
    (qual,) = out["qualifications"]
    assert qual["kind"] == "experience"
    assert qual["evidence"][0]["quote"].startswith("8+ years")


def _qual(qid: int, display: str, modality: str, value: dict | None, kind: str = "experience") -> JobQualification:
    q = JobQualification()
    q.id, q.job_id, q.kind, q.display, q.modality, q.confidence = qid, 1, kind, display, modality, "high"
    q.value = value
    q.section_key, q.section_title, q.quote = "minimum_qualifications", "Minimum Qualifications", display
    q.start_offset, q.end_offset = 0, len(display)
    return q


def test_the_years_a_posting_requires_are_served_with_each_row_and_as_a_headline():
    """`job_qualifications` is served with each row. The headline is the largest a REQUIRED row states:
    "12+ years" under Preferred is not what the employer requires."""
    from tracker.api.schemas.jobs import JobRequirements

    quals = [
        _qual(1, "8+ years of engineering, or 6 with a PhD.", "required", {"years": 8.0, "years_stated": [8.0, 6.0]}),
        _qual(2, "12+ years leading teams.", "preferred", {"years": 12.0, "years_stated": [12.0]}),
        _qual(3, "BS in Computer Science.", "required", None, kind="degree"),
    ]
    out = _run(_job_requirements(FakeSession([], quals=quals), _job()))

    by_id = {q["id"]: q for q in out["qualifications"]}
    assert (by_id[1]["years"], by_id[1]["years_stated"]) == (8.0, [8.0, 6.0])
    assert (by_id[3]["years"], by_id[3]["years_stated"]) == (None, [])
    assert out["required_years"] == 8.0
    # The response model carries every key the route builds (`extra="forbid"`).
    assert JobRequirements.model_validate(out).required_years == 8.0


def test_a_posting_not_yet_read_requires_no_years():
    from tracker.api.schemas.jobs import JobRequirements

    out = _run(_job_requirements(FakeSession([]), _job(requirements_extracted_at=None)))
    assert out["required_years"] is None
    JobRequirements.model_validate(out)
