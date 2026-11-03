"""Persistence half of the relevance review advisory.

`semantic/anchors.py` owns the classifier: nearest world anchor in the shared
embedding space, ~ms per row, offline, deterministic. This module is the only
writer of `job_relevance_reviews`, and it runs as a `POST_PASSES` entry so a
scrape maintains its own advisory coverage, never a CLI-only producer. No
language model runs on this path; `intelligence/relevance_review.py` keeps the
prompt machinery for the bench's model-comparison mode and the verdict schema
both engines share.

Selection is a standing-debt drain, not a touched-ids scope: any in-scope,
domain-unclassified posting in a review family that has no CURRENT verdict
(none yet, text changed since, or the prompt version moved — the disclosed-comp
staleness shape). Rows without an embedding are not yet reviewable and stay
pending. Capped per run — the cap exists to bound a single transaction, not to
ration a model.

The verdict is stored, never applied: no write to `jobs.domains`, no touch of
`in_scope`. `model_id` records the embedding model that judged.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import Job, JobRelevanceReview
from tracker.intelligence.prefilter import needs_relevance_review
from tracker.intelligence.relevance_review import TASK
from tracker.semantic import anchors
from tracker.semantic.provision import ModelNotReady
from tracker.settings_store import get_active_prompt_version, get_enabled_domains
from tracker.taxonomy.domains import DOMAIN_GROUPS

logger = logging.getLogger(__name__)


def candidate_stmt(review_families: tuple[str, ...], active_version: str, cap: int):
    """The standing-debt query: in-scope, unclassified, review-family rows whose
    verdict is absent or stale, and which HAVE a vector to judge. Mirrors
    `needs_relevance_review` — the SQL and the pure rule must agree, and the
    tests hold them to it."""
    stmt = (
        select(Job)
        .outerjoin(JobRelevanceReview, JobRelevanceReview.job_id == Job.id)
        .where(
            Job.status == "open",
            Job.in_scope.is_(True),
            Job.embedding.isnot(None),
            or_(Job.domains.is_(None), func.cardinality(Job.domains) == 0),
            or_(
                JobRelevanceReview.id.is_(None),
                Job.content_changed_at > JobRelevanceReview.reviewed_at,
                JobRelevanceReview.prompt_version != active_version,
            ),
        )
        .order_by(Job.id.desc())
        .limit(cap)
    )
    if review_families:
        stmt = stmt.where(Job.family.in_(review_families))
    return stmt


async def run_relevance_review(
    session: AsyncSession,
    *,
    cap: int | None = None,
    classifier=None,
) -> dict:
    """Drain the review debt through the anchor classifier.

    `classifier(embedding, tracked) -> RelevanceAssessment` is injectable for
    tests; production resolves the anchor matrix once per call (cached across
    calls by model name).
    """
    settings = get_settings()
    cap = cap or settings.relevance_review_max_per_run
    active = await get_active_prompt_version(session, TASK, anchors.ANCHOR_PROMPT_VERSION)
    tracked = await get_enabled_domains(session)
    tracked_ordered = [g.slug for g in DOMAIN_GROUPS if g.slug in tracked]
    summary = {"processed": 0, "failed": 0, "skipped_unavailable": False}

    if classifier is None:
        try:
            anchors.anchor_matrix()  # provisioning check + one-time anchor embed
        except ModelNotReady:
            # Weights not landed yet: skip cleanly, retry next run.
            logger.info("relevance review skipped: embedding model not provisioned")
            summary["skipped_unavailable"] = True
            return summary
        classifier = anchors.classify_embedding

    jobs = (
        await session.scalars(
            candidate_stmt(settings.relevance_review_families, active, cap)
        )
    ).all()

    for job in jobs:
        # The SQL already selected on this; the pure rule re-checks so the two
        # gates can never silently diverge on a row mid-flight.
        if not needs_relevance_review(
            in_scope=bool(job.in_scope),
            domains=job.domains,
            family=job.family,
            review_families=settings.relevance_review_families,
        ):
            continue
        if job.embedding is None:
            continue

        try:
            assessment = classifier(list(job.embedding), tracked)
        except ValueError:
            # Fail closed: a malformed verdict is never stored or coerced.
            logger.warning("relevance review failed closed on job %s", job.id, exc_info=True)
            summary["failed"] += 1
            continue

        values = {
            "job_id": job.id,
            "domain": assessment.domain,
            "relevance": assessment.relevance,
            "confidence": assessment.confidence,
            "rationale": assessment.rationale,
            "tracked_worlds": tracked_ordered,
            "prompt_version": active,
            "provider": anchors.BUILTIN_PROVIDER,
            # The concrete model that judged — the embedding model, since the
            # verdict is a property of its vector space.
            "model_id": settings.embedding_model,
            "reviewed_at": func.now(),
        }
        stmt = insert(JobRelevanceReview).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[JobRelevanceReview.job_id],
            set_={k: v for k, v in values.items() if k != "job_id"},
        )
        await session.execute(stmt)
        summary["processed"] += 1

    await session.commit()
    logger.info("relevance review: %s", summary)
    return summary
