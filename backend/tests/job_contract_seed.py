"""Realistic rows for the job API contract: one posting per serializer branch.

Every timestamp is fixed, so two runs of the same request return the same bytes
(`days_open` still counts from today, which is the serializer's own behaviour).
The postings cover each branch `serialize_job`, `get_job`, `build_job_package`
and `_job_requirements` can take:

| key | what it exercises |
|---|---|
| `plain` | never checked for pay, no description, unknown offer policy, `domains` NULL |
| `band` | stated USD base band, favorite, pursuit, relevance review, requirements, lineage original, comp sources, lifecycle |
| `repost` | the lineage's second member, with its own older lineage clock |
| `none_stated` | checked, no band stated, so the package is our estimate split |
| `hourly` | a stated hourly band, which is never decomposed |
| `total` | a stated total-comp band at netflix: the employee chooses the mix |
| `dismissed` | "not for me" with a reason |
| `closed` | a closed posting, visible only with `status=all` |
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import T0, make_job
from tracker.db.models import (
    Favorite,
    JobCompEstimate,
    JobFeedback,
    JobLifecycleEvent,
    JobLineage,
    JobObservation,
    JobQualification,
    JobRelevanceReview,
    JobSkill,
    JobSkillEvidence,
    Pursuit,
    ScrapeRun,
    SkillConcept,
)

SECTION = "8 years of product management. Python."


@dataclass(frozen=True)
class SeededJobs:
    plain: int
    band: int
    repost: int
    none_stated: int
    hourly: int
    total: int
    dismissed: int
    closed: int

    def items(self) -> list[tuple[str, int]]:
        return [(f.name, getattr(self, f.name)) for f in fields(self)]


def _stated(**over) -> dict:
    band = {
        "structured_at": T0,
        "disclosed_currency": "USD",
        "disclosed_pay_basis": "base",
        "disclosed_pay_period": "year",
        "disclosed_confidence": "high",
    }
    band.update(over)
    return band


async def seed_job_contract(session: AsyncSession) -> SeededJobs:
    run = ScrapeRun(started_at=T0, status="ok")
    estimate = {
        "comp_low": 520_000,
        "comp_high": 760_000,
        "comp_median": 640_000,
        "comp_provenance": "Google L6 estimated median (product_management)",
    }
    jobs = {
        "plain": make_job(
            "plain", company="acme", family=None, domains=None,
            level_confidence="unconfirmed", workplace_type="unknown", department=None,
        ),
        "band": make_job(
            "band", **estimate, team="Platform", posted_at=T0, viewed_at=T0,
            description_text="Lead the platform.", description_html="<p>Lead the platform.</p>",
            description_sections=[
                {"key": "minimum_qualifications", "title": "Minimum qualifications", "content": SECTION}
            ],
            requirements_extracted_at=T0, requirements_extractor_version="2.0.0",
            lineage_role="original", lineage_seq=1,
            **_stated(
                disclosed_base_min=230_000, disclosed_base_max=330_000,
                disclosed_snippet="$230,000-$330,000 base", disclosed_bonus_pct=0.15,
            ),
        ),
        "repost": make_job(
            "repost", **estimate, lineage_role="repost", lineage_seq=2,
            lineage_first_seen=T0 - timedelta(days=30),
        ),
        # Two titles sharing words, so an exact-title search for one has the
        # other as a textual related match.
        "none_stated": make_job(
            "none_stated", **estimate, **_stated(disclosed_confidence="high"),
            title="Platform Strategy Lead, Cloud",
        ),
        "hourly": make_job(
            "hourly", **_stated(disclosed_base_min=60, disclosed_base_max=85, disclosed_pay_period="hour"),
            title="Platform Strategy Lead, Maps",
        ),
        "total": make_job(
            "total", company="netflix",
            **_stated(disclosed_base_min=500_000, disclosed_base_max=900_000, disclosed_pay_basis="total"),
        ),
        "dismissed": make_job("dismissed", level_band="senior"),
        "closed": make_job("closed", status="closed", closed_at=T0 + timedelta(days=3)),
    }
    session.add(run)
    session.add_all(jobs.values())
    await session.flush()
    band = jobs["band"]

    lineage = JobLineage(
        company="google", root_job_id=band.id, size=2, open_members=2,
        first_seen=T0 - timedelta(days=30), last_seen=T0,
    )
    session.add(lineage)
    concept = SkillConcept(
        slug="python", display="Python", facet="technology", category="language",
        description="The Python language.", taxonomy_version="1",
    )
    session.add(concept)
    await session.flush()
    band.lineage_id = lineage.id
    jobs["repost"].lineage_id = lineage.id

    skill = JobSkill(
        job_id=band.id, concept_id=concept.id, importance_score=85, importance_band="core",
        confidence="high", modality="required", proficiency="hands_on",
        content_hash="c0ffee", extractor_version="2.0.0", taxonomy_version="1",
    )
    session.add(skill)
    await session.flush()
    start = SECTION.index("Python")
    session.add_all([
        JobSkillEvidence(
            job_skill_id=skill.id, job_id=band.id, concept_id=concept.id,
            section_key="minimum_qualifications", section_title="Minimum qualifications",
            quote="Python", start_offset=start, end_offset=start + len("Python"),
            aspect="minimum", modality="required", actor="candidate", score=80,
        ),
        JobQualification(
            job_id=band.id, kind="experience", display="8+ years of product management",
            modality="required", section_key="minimum_qualifications",
            section_title="Minimum qualifications", quote="8 years of product management",
            start_offset=0, end_offset=len("8 years of product management"),
            extractor_version="2.0.0",
        ),
        Favorite(job_id=band.id, created_at=T0),
        Pursuit(
            job_id=band.id, stage="applied", priority=2, notes="Referred by a PM there.",
            next_action="Follow up with the recruiter", next_action_due=T0 + timedelta(days=7),
            created_at=T0, updated_at=T0,
        ),
        JobRelevanceReview(
            job_id=band.id, domain="ai_ml", relevance="relevant", confidence=0.82,
            rationale="An AI platform product role.", tracked_worlds=["ai_ml"],
            prompt_version="r3", provider="local", model_id="qwen3", reviewed_at=T0,
        ),
        JobObservation(
            job_id=band.id, run_id=run.id, observed_at=T0, title=band.title, level_band="staff",
            payload={"comp_sources": [{
                "provider": "reference_table", "median": 640_000, "low": 520_000, "high": 760_000,
                "currency": "USD", "source": "Google L6 estimated median (product_management)",
            }]},
        ),
        # Our stored estimate, which the detail's figures and breakdown read;
        # the observation above is history.
        JobCompEstimate(
            job_id=band.id, source="roleband", **estimate, comp_currency="USD",
            sources=[{"provider": "reference_table", "median": 640_000, "low": 520_000, "high": 760_000,
                      "currency": "USD", "source": "Google L6 estimated median (product_management)"}],
        ),
        JobLifecycleEvent(job_id=band.id, run_id=run.id, event_type="opened", detail={}, created_at=T0),
        JobLifecycleEvent(
            job_id=band.id, run_id=run.id, event_type="changed", created_at=T0 + timedelta(days=1),
            detail={"field": "title", "before": "Product Manager", "after": band.title},
        ),
        JobFeedback(job_id=jobs["dismissed"].id, verdict="dismissed", reason="wrong_level", created_at=T0),
    ])
    await session.commit()
    return SeededJobs(**{key: row.id for key, row in jobs.items()})
