"""Detection: fetch pgvector candidates, score them, persist lineage links.

Runs after ``embed_jobs`` in the pipeline (so freshly-inserted jobs already have an
embedding) and as the backfill workhorse. The scoring is pure (``score.py``); this
module is the DB half: the candidate query, the human-safe upsert, and the
projection rebuild.

``detect_lineage(adjudicator=...)`` lets a verifier adjudicate *suspected*
pairs. The deterministic rules remain authoritative.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Text,
    and_,
    case,
    cast,
    delete,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from tracker.config import get_settings
from tracker.db.models import Job, JobLineage, JobLineageLink, JobPlaceSetMember, JobTwinLink
from tracker.lineage.content_diff import signature_jaccard
from tracker.lineage.decision_history import merge_history, without_history
from tracker.lineage.lock import LINEAGE_LOCK_KEY
from tracker.lineage.normalize import (
    normalize_title,
    title_grade,
    title_jaccard,
    title_key,
    titles_equal,
)
from tracker.lineage.pairs import TWIN_SAYS_NOT_ONE_OPENING_SQL
from tracker.lineage.place_sets import PlaceSetReads, still_listed_elsewhere
from tracker.lineage.project import JobFact, LineageProjection, LinkFact, build_projection
from tracker.lineage.score import Candidate, LineageThresholds, Verdict, score_pair
from tracker.pay_period import effective_period
from tracker.platform.locks import advisory_xact_lock

logger = logging.getLogger(__name__)

DETECTOR_VERSION = "lineage/v4"

# The effective-link predicate, in one place. A link counts toward a lineage when
# the machine auto-linked it and a human hasn't rejected it, OR a human confirmed it.
EFFECTIVE_LINK_SQL = "((confidence = 'auto' AND status <> 'rejected') OR status = 'confirmed')"


def effective_link_clause():
    """ORM twin of `EFFECTIVE_LINK_SQL`: a machine link the detector trusts
    and nobody rejected, or a link a person confirmed."""
    return or_(
        and_(JobLineageLink.confidence == "auto", JobLineageLink.status != "rejected"),
        JobLineageLink.status == "confirmed",
    )


def thresholds_from_settings() -> LineageThresholds:
    s = get_settings()
    return LineageThresholds(
        cos_auto=s.lineage_cos_auto,
        cos_title_equal=s.lineage_cos_title_equal,
        cos_suspect=s.lineage_cos_suspect,
        cos_floor=s.lineage_cos_floor,
        jaccard_suspect=s.lineage_title_jaccard_suspect,
        location_jaccard_min=s.lineage_location_jaccard_min,
        duplicate_auto=s.lineage_duplicate_auto,
        max_size=s.lineage_max_size,
        word_overlap_min=s.lineage_word_overlap_min,
    )


def band_relation(
    a_min, a_max, a_cur, a_per, b_min, b_max, b_cur, b_per
) -> str:
    """Compare disclosed bands: contradiction rejects; overlap never boosts.

    Periods are the SERVED ones (`effective_period`): a stored
    "$600,000 / hr" is `unclear`, never evidence. Any two known periods that
    differ are a mismatch, month included: a monthly posting and its yearly
    repost are ~12x apart, and "disjoint" would state the wrong reason.
    """
    if None in (a_min, a_max, b_min, b_max):
        return "unknown"
    known = (a_per not in (None, "unclear"), b_per not in (None, "unclear"))
    if all(known) and a_per != b_per:
        return "period_mismatch"
    if a_cur and b_cur and a_cur != b_cur:
        # Different currencies (locale bands) aren't comparable — treat as neutral,
        # never as counter-evidence.
        return "unknown"
    if a_min <= b_max and b_min <= a_max:
        return "overlap"
    return "disjoint"


@dataclass
class ScoredCandidate:
    candidate: Candidate
    verdict: Verdict
    prior_title: str
    prior_closed_at: datetime | None


def _is_concurrent(job_first_seen, prior_closed_at) -> bool:
    """The prior was still live when this posting appeared (lifetimes overlapped).

    The candidate gate already guarantees prior.first_seen < job.first_seen, so the
    prior was open at posting time iff it had not yet closed by then.
    """
    return prior_closed_at is None or prior_closed_at >= job_first_seen


def _gap_days(job_first_seen, concurrent, prior_closed_at, prior_first_seen) -> int | None:
    # Duplicate: measure from the prior's first_seen (how long after the original it
    # appeared). Repost: measure from the prior's closed_at (how long it was gone).
    reference = prior_first_seen if concurrent else prior_closed_at
    if reference is None:
        return None
    return (job_first_seen - reference).days


def _location_jaccard(left: list[str] | None, right: list[str] | None) -> float:
    """Raw-location overlap; broad dashboard location groups are not identity."""
    a, b = set(left or []), set(right or [])
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def fetch_candidates(
    session: AsyncSession, job: Job, *, k: int, place_sets: PlaceSetReads | None = None
) -> list[ScoredCandidate]:
    """Return scored predecessor candidates for one job, best-cosine first.

    Gates are pushed into SQL (same company, older, same family + level_band,
    location-group overlap or both empty). The vector order is exact within the
    company — HNSW is not used under these filters, and exact beats approximate for
    a decision this consequential. `place_sets` holds the place-set rule's
    reads across the jobs of one pass (`PlaceSetReads`).
    """
    rows = (
        await session.execute(
            text(
                f"""
                SELECT n.id AS nid, n.status, n.title, n.locations, n.location_groups,
                       n.first_seen, n.last_seen, n.closed_at,
                       n.description_text IS NOT NULL AS has_desc,
                       n.description_text AS prior_text,
                       n.disclosed_base_min, n.disclosed_base_max,
                       n.disclosed_currency, n.disclosed_pay_period,
                       1 - (n.embedding <=> j.embedding) AS cosine,
                       (SELECT count(*) FROM job_lineage_link l
                        WHERE l.prior_job_id = n.id OR l.job_id = n.id) AS prior_links,
                       EXISTS (SELECT 1 FROM job_place_set_member a
                                 JOIN job_place_set_member b ON b.set_id = a.set_id
                                WHERE a.job_id = j.id AND b.job_id = n.id
                                  AND a.status = 'auto' AND b.status = 'auto') AS same_place_set,
                       EXISTS (SELECT 1 FROM job_twin_link t
                                WHERE ((t.job_a_id = j.id AND t.job_b_id = n.id)
                                       OR (t.job_a_id = n.id AND t.job_b_id = j.id))
                                  AND {TWIN_SAYS_NOT_ONE_OPENING_SQL}) AS human_not_one
                FROM jobs j
                JOIN jobs n ON n.id <> j.id AND n.company = j.company
                WHERE j.id = :job_id
                  AND j.embedding IS NOT NULL
                  AND n.embedding IS NOT NULL
                  AND n.first_seen < j.first_seen
                  AND n.family IS NOT DISTINCT FROM j.family
                  AND n.level_band = j.level_band
                  AND (n.location_groups && j.location_groups
                       OR (cardinality(n.location_groups) = 0
                           AND cardinality(j.location_groups) = 0))
                ORDER BY n.embedding <=> j.embedding
                LIMIT :k
                """
            ),
            {"job_id": job.id, "k": k},
        )
    ).all()

    cfg = thresholds_from_settings()
    job_key = title_key(job.title, job.locations or [])
    job_display_title = normalize_title(job.title, job.locations or [])
    # A set holds open postings, so a member that closes leaves its stored
    # set, and the pair would come back to the queue as a suspected duplicate.
    # For a pair with a closed side, ask the rule instead, the
    # way a saved posting's closing does (`still_listed_elsewhere`).
    # Only a pair of one title can be one set, so only those are asked.
    one_title = [r for r in rows if normalize_title(r.title, r.locations or []) == job_display_title]
    closed = {r.nid for r in one_title if r.status != "open"}
    if job.status != "open" and one_title:
        closed.add(job.id)
    elsewhere = (
        await still_listed_elsewhere(session, closed, companies={job.company}, reads=place_sets)
        if closed
        else {}
    )

    def rule_says_one_set(other: int) -> bool:
        return any(p.id == other for p in elsewhere.get(job.id, ())) or any(
            p.id == job.id for p in elsewhere.get(other, ())
        )

    job_grade = title_grade(job.title, job.locations or [])
    job_groups = set(job.location_groups or [])
    scored: list[ScoredCandidate] = []
    for r in rows:
        prior_key = title_key(r.title, r.locations or [])
        prior_display_title = normalize_title(r.title, r.locations or [])
        prior_grade = title_grade(r.title, r.locations or [])
        prior_groups = set(r.location_groups or [])
        concurrent = _is_concurrent(job.first_seen, r.closed_at)
        cand = Candidate(
            job_id=job.id,
            prior_job_id=r.nid,
            cosine=float(r.cosine),
            title_display_equal=(
                bool(job_display_title) and job_display_title == prior_display_title
            ),
            title_equal=titles_equal(job_key, prior_key),
            title_jaccard=title_jaccard(job_key, prior_key),
            title_grade_compatible=(
                job_grade is None or prior_grade is None or job_grade == prior_grade
            ),
            concurrent=concurrent,
            gap_days=_gap_days(job.first_seen, concurrent, r.closed_at, r.first_seen),
            location_overlap=bool(job_groups & prior_groups),
            both_locations_empty=not job_groups and not prior_groups,
            location_jaccard=_location_jaccard(job.locations, r.locations),
            same_family=True,   # gated in SQL
            same_level_band=True,
            prior_lineage_size=int(r.prior_links) + 1,
            has_descriptions=bool(r.has_desc) and bool(job.description_text),
            word_overlap=signature_jaccard(job.description_text, r.prior_text),
            same_place_set=bool(r.same_place_set) or rule_says_one_set(r.nid),
            human_said_not_one_opening=bool(r.human_not_one),
            band_relation=band_relation(
                job.disclosed_base_min, job.disclosed_base_max,
                job.disclosed_currency, effective_period(
                    job.disclosed_pay_period, job.disclosed_base_min,
                    job.disclosed_base_max, job.disclosed_currency,
                ),
                r.disclosed_base_min, r.disclosed_base_max,
                r.disclosed_currency, effective_period(
                    r.disclosed_pay_period, r.disclosed_base_min,
                    r.disclosed_base_max, r.disclosed_currency,
                ),
            ),
        )
        scored.append(
            ScoredCandidate(
                candidate=cand,
                verdict=score_pair(cand, cfg),
                prior_title=r.title,
                prior_closed_at=r.closed_at,
            )
        )
    return scored


def _choose(scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """At most one predecessor. Ambiguity is not evidence for three links."""
    autos = [s for s in scored if s.verdict.decision == "auto"]
    if autos:
        return [max(autos, key=lambda s: s.candidate.cosine)]
    suspected = [s for s in scored if s.verdict.decision == "suspected"]
    suspected.sort(key=lambda s: s.candidate.cosine, reverse=True)
    return suspected[:1]


async def _persist_link(session: AsyncSession, sc: ScoredCandidate, job_title: str) -> bool:
    c, v = sc.candidate, sc.verdict
    evidence = {
        "reasons": v.reasons,
        "cosine": round(c.cosine, 4),
        "title_jaccard": round(c.title_jaccard, 4),
        "band_relation": c.band_relation,
        "job_title": job_title,
        "prior_title": sc.prior_title,
    }
    # A reviewed verdict is IMMUTABLE to the detector: only 'pending' rows update.
    # Returns whether a row was written: a decided row blocks the upsert, so
    # the run summary counts only the rows that changed.
    result = await session.execute(
        text(
            f"""
            INSERT INTO job_lineage_link
                (job_id, prior_job_id, relation, method, score, title_similarity,
                 gap_days, confidence, status, detector_version, evidence, created_at)
            VALUES
                (:job_id, :prior_job_id, :relation, :method, :score, :title_sim,
                 :gap_days, :confidence, 'pending', :dv, cast(:evidence AS jsonb), now())
            ON CONFLICT (job_id, prior_job_id) DO UPDATE
               SET relation = EXCLUDED.relation,
                   method = EXCLUDED.method,
                   score = EXCLUDED.score,
                   title_similarity = EXCLUDED.title_similarity,
                   gap_days = EXCLUDED.gap_days,
                   confidence = EXCLUDED.confidence,
                   evidence = {merge_history("job_lineage_link.evidence")},
                   detector_version = EXCLUDED.detector_version
             WHERE job_lineage_link.status = 'pending'
            """
        ),
        {
            "job_id": c.job_id,
            "prior_job_id": c.prior_job_id,
            "relation": v.relation,
            "method": v.method,
            "score": c.cosine,
            "title_sim": c.title_jaccard,
            "gap_days": c.gap_days,
            "confidence": v.decision,  # auto | suspected
            "dv": DETECTOR_VERSION,
            "evidence": json.dumps(evidence),
        },
    )
    return bool(getattr(result, "rowcount", 1))


def link_fact(row) -> LinkFact:
    """A stored effective link as the projection reads it."""
    human = row.status == "confirmed"
    return LinkFact(
        row.job_id,
        row.prior_job_id,
        row.relation,
        human=human,
        decided_at=row.reviewed_at if human else None,
        score=row.score,
    )


def lineage_input_key():
    """What the detector reads of a posting, as one md5: the candidate gates (family, band, places) and the scoring
    inputs (title, raw places, stated pay, its place set, and the postings a
    person said it is not one opening with). A change to any of them re-checks
    the posting without a new vector; the text is not here because a text
    change re-embeds it. Never what a scan moves on every read (last seen,
    status, the estimate): those decide nothing here.

    The place set is named by its earliest member, not its id: the id follows
    the set's stored identity (company, title, text class), which can move
    while the postings it groups stay the same (a text edit can change the
    class key; a set that dissolves and forms again takes a new id). The
    verdicts are NULL for a posting with none, which `concat_ws` skips, so the
    key of every such posting is what it was before verdicts were part of it."""
    member = aliased(JobPlaceSetMember)
    mate = aliased(JobPlaceSetMember)
    place_set = (
        select(func.min(mate.job_id))
        .select_from(member)
        .join(mate, mate.set_id == member.set_id)
        .where(member.job_id == Job.id, member.status == "auto", mate.status == "auto")
        .scalar_subquery()
    )
    parts = [
        Job.title, Job.family, Job.level_band,
        func.array_to_string(Job.locations, "\x1e"),
        func.array_to_string(Job.location_groups, "\x1e"),
        cast(Job.disclosed_base_min, Text), cast(Job.disclosed_base_max, Text),
        Job.disclosed_currency, Job.disclosed_pay_period,
        cast(place_set, Text),
    ]
    twin = aliased(JobTwinLink, name="t")
    partner = case((twin.job_a_id == Job.id, twin.job_b_id), else_=twin.job_a_id)
    not_one_opening = (
        select(func.string_agg(cast(partner, Text), aggregate_order_by(literal_column("','"), partner)))
        .select_from(twin)
        .where(or_(twin.job_a_id == Job.id, twin.job_b_id == Job.id), text(TWIN_SAYS_NOT_ONE_OPENING_SQL))
        .scalar_subquery()
    )
    return func.md5(func.concat_ws("\x1f", *[func.coalesce(part, "") for part in parts], not_one_opening))


def _stale_clause():
    return or_(
        Job.lineage_checked_at.is_(None),
        Job.embedded_at > Job.lineage_checked_at,
        Job.lineage_detector_version != DETECTOR_VERSION,
        Job.lineage_input_key.is_distinct_from(lineage_input_key()),
    )


async def _recheck_successors(session: AsyncSession, job: Job) -> None:
    """A posting whose inputs moved is a different predecessor: re-check the
    postings that proposed it and those it may now precede.
    Marked, not decided here: the pass's catch-up reads them, a capped number
    per run, so an interrupted run resumes from the marks."""
    await session.execute(
        text(
            """
            UPDATE jobs SET lineage_checked_at = NULL
            WHERE id IN (
                SELECT job_id FROM job_lineage_link
                WHERE prior_job_id = :job_id AND status = 'pending'
              UNION
                SELECT n.id FROM jobs p JOIN jobs n ON n.company = p.company AND n.id <> p.id
                WHERE p.id = :job_id
                  AND n.embedding IS NOT NULL
                  AND n.first_seen > p.first_seen
                  AND n.family IS NOT DISTINCT FROM p.family
                  AND n.level_band = p.level_band
                  AND (n.location_groups && p.location_groups
                       OR (cardinality(n.location_groups) = 0
                           AND cardinality(p.location_groups) = 0))
            )
            """
        ),
        {"job_id": job.id},
    )


async def detect_lineage(
    session: AsyncSession,
    job_ids: list[int] | None,
    *,
    companies: set[str] | None = None,
    cap: int | None = None,
    dry_run: bool = False,
    auto_only: bool = False,
    adjudicator=None,
    place_sets: PlaceSetReads | None = None,
) -> dict:
    """Detect predecessor links for the given jobs (or the whole stale corpus).

    Returns a summary. When ``dry_run`` is True nothing is persisted and the
    per-job proposals are returned under ``"proposals"`` for the backfill report.
    Every job's candidates share one `PlaceSetReads`: ``place_sets`` when the
    caller shares one across several calls, else a new one. Sound because
    this writes only links and lineage stamps, none of what it holds.
    """
    k = get_settings().lineage_candidates_k
    place_sets = place_sets if place_sets is not None else PlaceSetReads()

    key = lineage_input_key().label("input_key")
    query = select(Job, key).where(Job.embedding.isnot(None), _stale_clause())
    if job_ids is not None:
        query = query.where(Job.id.in_(job_ids))
    if companies is not None:
        query = query.where(Job.company.in_(companies))
    query = query.order_by(Job.first_seen.asc(), Job.id.asc())
    if cap:
        query = query.limit(cap)

    selected = list((await session.execute(query)).all())
    jobs = [row.Job for row in selected]
    input_keys = {row.Job.id: row.input_key for row in selected}

    summary = {
        "processed": 0,
        "auto": 0,
        "suspected": 0,
        "links_written": 0,
        "proposals": [] if dry_run else None,
    }

    for job in jobs:
        scored = await fetch_candidates(session, job, k=k, place_sets=place_sets)
        if adjudicator is not None:
            for sc in scored:
                if sc.verdict.decision == "suspected":
                    revised = await adjudicator(session, sc.candidate)
                    if revised is not None:
                        sc.verdict = revised
        chosen = _choose(scored)
        if auto_only:
            chosen = [sc for sc in chosen if sc.verdict.decision == "auto"]
        # A job a person already linked has its predecessor: proposing another
        # only invites a second one. Its stale proposals are still
        # withdrawn below.
        linked_by_a_person = set(
            (
                await session.scalars(
                    select(JobLineageLink.prior_job_id).where(
                        JobLineageLink.job_id == job.id, JobLineageLink.status == "confirmed"
                    )
                )
            ).all()
        )
        if linked_by_a_person:
            chosen = [sc for sc in chosen if sc.candidate.prior_job_id in linked_by_a_person]

        for sc in chosen:
            if sc.verdict.decision == "auto":
                summary["auto"] += 1
            elif sc.verdict.decision == "suspected":
                summary["suspected"] += 1

        if dry_run:
            summary["proposals"].append(
                {
                    "job_id": job.id,
                    "company": job.company,
                    "job_title": job.title,
                    "chosen": [
                        {
                            "prior_job_id": sc.candidate.prior_job_id,
                            "prior_title": sc.prior_title,
                            "decision": sc.verdict.decision,
                            "relation": sc.verdict.relation,
                            "cosine": round(sc.candidate.cosine, 4),
                            "gap_days": sc.candidate.gap_days,
                            "method": sc.verdict.method,
                        }
                        for sc in chosen
                    ],
                    "rejected": [
                        {
                            "prior_title": sc.prior_title,
                            "cosine": round(sc.candidate.cosine, 4),
                            "reason": sc.verdict.reasons[0] if sc.verdict.reasons else "",
                        }
                        for sc in scored
                        if sc.verdict.decision == "reject"
                    ],
                }
            )
        else:
            # Re-detection must withdraw prior machine proposals that fail
            # the current rules. Human decisions are historical evidence and
            # therefore never deleted or overwritten. The write takes the
            # relationship lock first, like every other writer, so
            # it never meets a verdict or a place-set rebuild in another order.
            await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
            await session.execute(
                delete(JobLineageLink).where(
                    JobLineageLink.job_id == job.id,
                    JobLineageLink.status == "pending",
                    # A verdict somebody took back is not this detector's to
                    # discard: it is the one part of the evidence nothing can
                    # recompute.
                    without_history(JobLineageLink.evidence),
                )
            )
            for sc in chosen:
                if await _persist_link(session, sc, job.title):
                    summary["links_written"] += 1
            current_key = input_keys[job.id]
            if job.lineage_input_key is not None and job.lineage_input_key != current_key:
                await _recheck_successors(session, job)
            job.lineage_checked_at = func.now()
            job.lineage_detector_version = DETECTOR_VERSION
            job.lineage_input_key = current_key
            await session.commit()

        summary["processed"] += 1

    return summary


async def rebuild_lineage_projection(session: AsyncSession) -> int:
    """Rebuild job_lineage + jobs.lineage_* from the effective links. Idempotent.

    Takes `LINEAGE_LOCK_KEY` before it reads a link and commits nothing: the
    caller's commit publishes the projection with whatever decided it, in one
    transaction. Two rebuilds therefore run one after the other, and the later
    one reads every link the earlier committed, so an older snapshot can never
    publish last. A verdict command holds the same lock from before
    its first read (`lineage.review`); the lock is re-entrant in a transaction.
    """
    await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
    link_rows = (
        await session.execute(
            text(
                f"SELECT job_id, prior_job_id, relation, status, reviewed_at, score "
                f"FROM job_lineage_link WHERE {EFFECTIVE_LINK_SQL}"
            )
        )
    ).all()
    links = [link_fact(r) for r in link_rows]

    referenced: set[int] = set()
    for lk in links:
        referenced.add(lk.job_id)
        referenced.add(lk.prior_job_id)

    jobs: dict[int, JobFact] = {}
    if referenced:
        fact_rows = (
            await session.execute(
                select(Job.id, Job.company, Job.first_seen, Job.last_seen, Job.status).where(
                    Job.id.in_(referenced)
                )
            )
        ).all()
        jobs = {
            r.id: JobFact(r.id, r.company, r.first_seen, r.last_seen, r.status)
            for r in fact_rows
        }

    projections = build_projection(links, jobs, max_size=get_settings().lineage_max_size)
    await _write_projection(session, projections)
    return len(projections)


async def _write_projection(session: AsyncSession, projections: list[LineageProjection]) -> None:
    """Write the projection, touching only rows whose assignment changed.

    A lineage keeps its row, and its id, while its root does (`root_job_id`
    is unique); a job is written only when its lineage, place, role or start
    changed; a job that left every lineage is cleared; one UPDATE carries
    them all. Rewriting every member each run would push non-HOT rewrites
    through every `jobs` index (the lineage columns are indexed) and re-mint
    the id of every lineage.
    """
    current = {
        r.id: (r.lineage_id, r.lineage_seq, r.lineage_role, r.lineage_first_seen)
        for r in (
            await session.execute(
                select(
                    Job.id, Job.lineage_id, Job.lineage_seq, Job.lineage_role, Job.lineage_first_seen
                ).where(or_(Job.lineage_id.isnot(None), Job.lineage_role.isnot(None)))
            )
        ).all()
    }
    # A row this session loaded earlier and still holds keeps the values it
    # read then (`expire_on_commit=False`), which another session's rebuild
    # may have replaced: compare against the table, not the identity map.
    existing = {
        row.root_job_id: row
        for row in (
            await session.scalars(select(JobLineage).execution_options(populate_existing=True))
        ).all()
    }

    lineage_of: dict[int, JobLineage] = {}
    for proj in projections:
        if proj.oversized:
            logger.warning(
                "lineage component root=%s is %d deep (> max_size)", proj.root_job_id, proj.size
            )
        values = {
            "company": proj.company,
            "size": proj.size,
            "open_members": proj.open_members,
            "first_seen": proj.first_seen,
            "last_seen": proj.last_seen,
        }
        row = existing.get(proj.root_job_id)
        if row is None:
            row = JobLineage(root_job_id=proj.root_job_id, **values)
            session.add(row)
        else:
            moved = {column: value for column, value in values.items() if getattr(row, column) != value}
            for column, value in moved.items():
                setattr(row, column, value)
            if moved:
                row.updated_at = func.now()
        lineage_of[proj.root_job_id] = row
    await session.flush()  # assign the new lineages' ids

    left = (None, None, None, None)
    wanted = dict.fromkeys(current, left)
    for proj in projections:
        lineage_id = lineage_of[proj.root_job_id].id
        for m in proj.members:
            wanted[m.job_id] = (lineage_id, m.seq, m.role, proj.first_seen)
    changed = [
        {
            "id": job_id,
            "lineage_id": lineage_id,
            "lineage_seq": seq,
            "lineage_role": role,
            "lineage_first_seen": first_seen,
        }
        for job_id, (lineage_id, seq, role, first_seen) in sorted(wanted.items())
        if current.get(job_id, left) != (lineage_id, seq, role, first_seen)
    ]
    if changed:
        # By primary key, so the session's own `Job` objects take the new
        # values: a later pass in the same session reads `lineage_id` off them.
        await session.execute(update(Job), changed)
    gone = {row.id for root, row in existing.items() if root not in lineage_of}
    if gone:
        await session.execute(delete(JobLineage).where(JobLineage.id.in_(gone)))
    new = sum(root not in existing for root in lineage_of)
    logger.info(
        "lineage projection: %d kept, %d new, %d gone; %d jobs written",
        len(lineage_of) - new, new, len(gone), len(changed),
    )
