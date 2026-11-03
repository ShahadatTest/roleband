"""Twin-opportunity detection and symmetric graph helpers.

Twins are separate openings. They never enter lineage projection or alter demand.
Human decisions are detector-immutable.

A proposal whose titles read the same, in one department, is matched
automatically: `confidence = 'auto'`, `status = 'pending'`, shown as
a related role at once (`TWIN_EFFECTIVE_SQL`) and listed under "Matched
automatically" for a person to check, as auto duplicate links are. Such
proposals are reliably right, and a wrong one costs a card in a deck, undone
with "Different roles". A near-title, a missing department or a title-grade
question stays a proposal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Text, case, cast, delete, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from tracker.config import get_settings
from tracker.db.models import Job, JobLineageLink, JobTwinLink
from tracker.lineage.content_diff import DescriptionDiff, compare_descriptions, normalize_department
from tracker.lineage.decision_history import merge_history, without_history
from tracker.lineage.lock import LINEAGE_LOCK_KEY
from tracker.lineage.normalize import normalize_title, title_grade, title_jaccard, title_key
from tracker.platform.locks import advisory_xact_lock

DETECTOR_VERSION = "twin/v2"

#: A twin the product shows: confirmed by a person, or matched automatically
#: and not yet decided. A person's "Different roles" on an auto twin sets
#: `rejected`, which ends it. Mirrors `detect.EFFECTIVE_LINK_SQL`.
TWIN_EFFECTIVE_SQL = "(status = 'confirmed' OR (confidence = 'auto' AND status = 'pending'))"


@dataclass(frozen=True)
class TwinCandidate:
    job_a_id: int
    job_b_id: int
    cosine: float
    title_similarity: float
    display_title_equal: bool
    title_grade_compatible: bool
    same_family: bool
    same_level_band: bool
    department_relation: str  # same | missing | mismatch
    same_lineage: bool
    description_diff: DescriptionDiff


@dataclass(frozen=True)
class TwinVerdict:
    decision: str  # auto | suspected | reject
    reasons: tuple[str, ...]


def canonical_pair(left: int, right: int) -> tuple[int, int]:
    if left == right:
        raise ValueError("cannot link a job to itself")
    return (left, right) if left < right else (right, left)


def department_relation(left: str | None, right: str | None) -> str:
    a, b = normalize_department(left), normalize_department(right)
    if a is None or b is None:
        return "missing"
    return "same" if a == b else "mismatch"


def score_twin_candidate(candidate: TwinCandidate) -> TwinVerdict:
    settings = get_settings()
    if not candidate.same_family:
        return TwinVerdict("reject", ("family mismatch",))
    if not candidate.same_level_band:
        return TwinVerdict("reject", ("seniority mismatch",))
    if candidate.same_lineage:
        return TwinVerdict("reject", ("already the same opening lineage",))
    if not candidate.title_grade_compatible:
        return TwinVerdict("reject", ("explicit title grade mismatch",))
    if candidate.department_relation == "mismatch":
        return TwinVerdict("reject", ("known department mismatch",))
    if candidate.title_similarity < settings.twin_title_jaccard_min:
        return TwinVerdict("reject", ("title overlap below twin threshold",))
    if candidate.cosine < settings.twin_cos_floor:
        return TwinVerdict("reject", ("semantic similarity below twin threshold",))
    if not candidate.description_diff.comparable:
        return TwinVerdict("reject", ("full descriptions unavailable",))
    if candidate.description_diff.equivalent:
        return TwinVerdict("reject", ("no non-cosmetic description difference",))
    if candidate.description_diff.token_similarity < settings.twin_text_jaccard_min:
        return TwinVerdict("reject", ("whole-description overlap below twin threshold",))

    reasons = [
        "strong same-company role identity with changed description passages",
        (
            f"{candidate.description_diff.left_only_count} earlier-only and "
            f"{candidate.description_diff.right_only_count} later-only passages"
        ),
        f"whole-description token overlap {candidate.description_diff.token_similarity:.2f}",
    ]
    if candidate.department_relation == "missing":
        reasons.append("department missing on one or both postings — human review")
    if not candidate.display_title_equal:
        reasons.append(f"near-title match ({candidate.title_similarity:.2f}) — human review")
    if candidate.display_title_equal and candidate.department_relation == "same":
        reasons.append("identical titles in one department: a related role, matched automatically")
        return TwinVerdict("auto", tuple(reasons))
    return TwinVerdict("suspected", tuple(reasons))


@dataclass
class ScoredTwin:
    candidate: TwinCandidate
    verdict: TwinVerdict
    left_title: str
    right_title: str


async def _neighbor_rows(session: AsyncSession, job: Job, *, k: int):
    """Top unordered same-company/family/band neighbors by cosine.

    Extracted so threshold calibration (`twin_backfill --calibrate`) measures
    the EXACT population detection scores — a calibration that queries its own
    approximation of the candidate set calibrates the wrong thing.
    """
    return (
        await session.execute(
            text(
                """
                SELECT n.id AS nid, n.title, n.department, n.locations,
                       n.description_text, n.description_sections, n.lineage_id,
                       1 - (n.embedding <=> j.embedding) AS cosine
                  FROM jobs j
                  JOIN jobs n ON n.id < j.id AND n.company = j.company
                 WHERE j.id = :job_id
                   AND j.embedding IS NOT NULL AND n.embedding IS NOT NULL
                   AND n.family IS NOT DISTINCT FROM j.family
                   AND n.level_band = j.level_band
                 ORDER BY n.embedding <=> j.embedding
                 LIMIT :k
                """
            ),
            {"job_id": job.id, "k": k},
        )
    ).all()


async def fetch_twin_candidates(session: AsyncSession, job: Job, *, k: int) -> list[ScoredTwin]:
    """Top unordered same-company/family/band neighbors; no temporal gate."""
    rows = await _neighbor_rows(session, job, k=k)

    reviewed = {
        (row.job_a_id, row.job_b_id): row.status
        for row in (
            await session.scalars(
                select(JobTwinLink).where(
                    or_(JobTwinLink.job_a_id == job.id, JobTwinLink.job_b_id == job.id)
                )
            )
        ).all()
        if row.status != "pending"
    }
    # A pending duplicate proposal already offers "Mark as twin" in the same
    # review screen; emitting a second proposal for that pair duplicates work.
    # Confirmed duplicates are ineligible. Rejected duplicate proposals remain
    # eligible because "not duplicate" does not mean "not twin."
    active_duplicate_pairs = {
        canonical_pair(row.job_id, row.prior_job_id)
        for row in (
            await session.scalars(
                select(JobLineageLink).where(
                    or_(JobLineageLink.job_id == job.id, JobLineageLink.prior_job_id == job.id),
                    JobLineageLink.status.in_(("pending", "confirmed")),
                )
            )
        ).all()
    }
    job_key = title_key(job.title, job.locations or [])
    job_display = normalize_title(job.title, job.locations or [])
    job_grade = title_grade(job.title, job.locations or [])
    out: list[ScoredTwin] = []
    for row in rows:
        pair = canonical_pair(job.id, row.nid)
        if pair in reviewed or pair in active_duplicate_pairs:
            continue
        other_key = title_key(row.title, row.locations or [])
        other_grade = title_grade(row.title, row.locations or [])
        candidate = TwinCandidate(
            job_a_id=pair[0],
            job_b_id=pair[1],
            cosine=float(row.cosine),
            title_similarity=title_jaccard(job_key, other_key),
            display_title_equal=(
                bool(job_display)
                and job_display == normalize_title(row.title, row.locations or [])
            ),
            title_grade_compatible=(
                job_grade is None or other_grade is None or job_grade == other_grade
            ),
            same_family=True,
            same_level_band=True,
            department_relation=department_relation(job.department, row.department),
            same_lineage=(
                job.lineage_id is not None
                and row.lineage_id is not None
                and job.lineage_id == row.lineage_id
            ),
            description_diff=compare_descriptions(
                job.description_sections,
                job.description_text,
                row.description_sections,
                row.description_text,
            ),
        )
        out.append(
            ScoredTwin(candidate, score_twin_candidate(candidate), row.title, job.title)
        )
    return out


async def _persist_twin(session: AsyncSession, scored: ScoredTwin) -> None:
    candidate, verdict = scored.candidate, scored.verdict
    evidence = {
        "reasons": list(verdict.reasons),
        "anchors": {
            "display_title_equal": candidate.display_title_equal,
            "department_relation": candidate.department_relation,
            "title_similarity": round(candidate.title_similarity, 4),
            "cosine": round(candidate.cosine, 4),
        },
        "description_diff": candidate.description_diff.evidence(),
        "left_title": scored.left_title,
        "right_title": scored.right_title,
    }
    await session.execute(
        text(
            f"""
            INSERT INTO job_twin_link
                (job_a_id, job_b_id, method, score, title_similarity, confidence,
                 status, detector_version, evidence, created_at)
            VALUES
                (:a, :b, 'section_diff', :score, :title_similarity, :confidence,
                 'pending', :version, cast(:evidence AS jsonb), now())
            ON CONFLICT (job_a_id, job_b_id) DO UPDATE
               SET method = EXCLUDED.method, score = EXCLUDED.score,
                   title_similarity = EXCLUDED.title_similarity,
                   confidence = EXCLUDED.confidence,
                   detector_version = EXCLUDED.detector_version,
                   evidence = {merge_history("job_twin_link.evidence")}
             WHERE job_twin_link.status = 'pending'
            """
        ),
        {
            "a": candidate.job_a_id,
            "b": candidate.job_b_id,
            "score": candidate.cosine,
            "title_similarity": candidate.title_similarity,
            "confidence": verdict.decision,
            "version": DETECTOR_VERSION,
            "evidence": json.dumps(evidence),
        },
    )


def _partners(link, left, right, *conds):
    """The postings linked to this one by `link`, as one ordered string; NULL
    for none."""
    partner = case((left == Job.id, right), else_=left)
    return (
        select(func.string_agg(cast(partner, Text), aggregate_order_by(literal_column("','"), partner)))
        .select_from(link)
        .where(or_(left == Job.id, right == Job.id), *conds)
        .scalar_subquery()
    )


def twin_input_key():
    """What the detector reads of a posting besides its vector, as one md5: the
    candidate gates (company, family, band), the scoring inputs (title, raw
    places, department, its lineage), the duplicate links that keep a pair out
    and the twin verdicts a person gave. A change to any of them re-checks the
    posting; a text change re-embeds it, which `embedded_at` catches.

    The lineage is named by its earliest member, not its id, which the lineage
    projection re-mints each run."""
    mate = aliased(Job, name="lineage_mate")
    lineage = select(func.min(mate.id)).where(mate.lineage_id == Job.lineage_id).scalar_subquery()
    dup = aliased(JobLineageLink, name="dup")
    decided = aliased(JobTwinLink, name="decided")
    parts = [
        Job.company, Job.title, Job.family, Job.level_band, Job.department,
        func.array_to_string(Job.locations, "\x1e"),
        cast(lineage, Text),
        _partners(dup, dup.job_id, dup.prior_job_id, dup.status.in_(("pending", "confirmed"))),
        _partners(decided, decided.job_a_id, decided.job_b_id, decided.status != "pending"),
    ]
    return func.md5(func.concat_ws("\x1f", *[func.coalesce(part, "") for part in parts]))


def _stale_clause():
    return or_(
        Job.twin_checked_at.is_(None),
        Job.embedded_at > Job.twin_checked_at,
        Job.twin_detector_version.is_distinct_from(DETECTOR_VERSION),
        Job.twin_input_key.is_distinct_from(twin_input_key()),
    )


async def _recheck_newer(session: AsyncSession, job: Job, *, k: int) -> None:
    """A posting whose inputs moved reads differently to the newer postings
    that are scored against it: re-check those that proposed it and its
    nearest newer neighbours. Marked, not decided here: the pass's catch-up
    reads them, a capped number per run."""
    await session.execute(
        text(
            """
            UPDATE jobs SET twin_checked_at = NULL
            WHERE id IN (
                SELECT job_b_id FROM job_twin_link WHERE job_a_id = :job_id AND status = 'pending'
              UNION
                (SELECT n.id FROM jobs j JOIN jobs n ON n.id > j.id AND n.company = j.company
                  WHERE j.id = :job_id
                    AND j.embedding IS NOT NULL AND n.embedding IS NOT NULL
                    AND n.family IS NOT DISTINCT FROM j.family
                    AND n.level_band = j.level_band
                  ORDER BY n.embedding <=> j.embedding
                  LIMIT :k)
            )
            """
        ),
        {"job_id": job.id, "k": k},
    )


async def detect_twins(
    session: AsyncSession,
    job_ids: list[int] | None,
    *,
    companies: set[str] | None = None,
    cap: int | None = None,
    dry_run: bool = False,
    stale_only: bool = True,
) -> dict:
    """Propose twins for the given jobs (or the whole corpus), oldest first.

    `stale_only` reads only postings never checked, re-embedded since, read by
    another detector version, or whose `twin_input_key` moved, so a cap drains
    a backlog instead of re-scoring its head. A processed posting is stamped;
    a dry run stamps nothing.
    """
    key = twin_input_key().label("input_key")
    query = select(Job, key).where(Job.embedding.isnot(None))
    if stale_only:
        query = query.where(_stale_clause())
    if job_ids is not None:
        query = query.where(Job.id.in_(job_ids))
    if companies is not None:
        query = query.where(Job.company.in_(companies))
    query = query.order_by(Job.id.asc())
    if cap:
        query = query.limit(cap)
    selected = list((await session.execute(query)).all())
    jobs = [row.Job for row in selected]
    input_keys = {row.Job.id: row.input_key for row in selected}

    summary = {
        "processed": 0, "suspected": 0, "auto": 0, "links_written": 0,
        "proposals": [] if dry_run else None,
    }
    k = get_settings().lineage_candidates_k
    for job in jobs:
        scored = await fetch_twin_candidates(session, job, k=k)
        candidates = [item for item in scored if item.verdict.decision in ("auto", "suspected")]
        candidates.sort(key=lambda item: item.candidate.cosine, reverse=True)
        chosen = candidates[:1]
        summary["processed"] += 1
        for item in chosen:
            summary[item.verdict.decision] += 1
        if dry_run:
            summary["proposals"].extend(
                {
                    "job_a_id": item.candidate.job_a_id,
                    "job_b_id": item.candidate.job_b_id,
                    "left_title": item.left_title,
                    "right_title": item.right_title,
                    "cosine": round(item.candidate.cosine, 4),
                    "title_similarity": round(item.candidate.title_similarity, 4),
                    "reasons": list(item.verdict.reasons),
                    "decision": item.verdict.decision,
                }
                for item in chosen
            )
            continue
        # The relationship lock first, like every writer of these rows: one
        # lock order with the verdicts and the place-set pass.
        await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
        await session.execute(
            delete(JobTwinLink).where(
                # Candidate enumeration is canonical (older/lower id -> current
                # job). Only replace the current job's proposal; deleting every
                # touching proposal would make a later scan erase another job's
                # otherwise valid pending suggestion.
                JobTwinLink.job_b_id == job.id,
                JobTwinLink.status == "pending",
                # Except a row holding a verdict somebody took back.
                without_history(JobTwinLink.evidence),
            )
        )
        for item in chosen:
            await _persist_twin(session, item)
            summary["links_written"] += 1
        moved = job.twin_checked_at is not None and (
            job.twin_input_key != input_keys[job.id]
            or (job.embedded_at is not None and job.embedded_at > job.twin_checked_at)
        )
        if moved:
            await _recheck_newer(session, job, k=k)
        job.twin_checked_at = func.now()
        job.twin_detector_version = DETECTOR_VERSION
        job.twin_input_key = input_keys[job.id]
        await session.commit()
    return summary


async def twin_component_links(session: AsyncSession, start: int) -> dict[int, tuple[int, int]]:
    """The effective twin links of `start`'s component, {link id: (a, b)}.

    Read a frontier at a time, ids only: each round reads the links touching
    the postings the last round reached, so the cost follows the component,
    not the size of the twin table."""
    reached = {start}
    frontier = [start]
    links: dict[int, tuple[int, int]] = {}
    while frontier:
        rows = (
            await session.execute(
                select(JobTwinLink.id, JobTwinLink.job_a_id, JobTwinLink.job_b_id).where(
                    text(TWIN_EFFECTIVE_SQL),
                    or_(JobTwinLink.job_a_id.in_(frontier), JobTwinLink.job_b_id.in_(frontier)),
                )
            )
        ).all()
        frontier = []
        for link_id, a, b in rows:
            links[link_id] = (a, b)
            for job_id in (a, b):
                if job_id not in reached:
                    reached.add(job_id)
                    frontier.append(job_id)
    return links


def connected_twin_ids(start: int, pairs: list[tuple[int, int]]) -> tuple[set[int], set[int]]:
    """Return connected component + direct partners; no transitive assertion."""
    direct = {b if a == start else a for a, b in pairs if a == start or b == start}
    component = {start}
    frontier = [start]
    while frontier:
        current = frontier.pop()
        for a, b in pairs:
            if current not in (a, b):
                continue
            other = b if a == current else a
            if other not in component:
                component.add(other)
                frontier.append(other)
    component.discard(start)
    return component, direct
