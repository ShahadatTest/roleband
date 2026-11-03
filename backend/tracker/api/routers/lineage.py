"""Repost lineage (the "stack deck") + twin relationships and their review flows."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.api.deps import OffBoardDep, Offset, SessionDep, end_read
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.lineage import (
    DuplicateReviewResponse,
    DuplicateVerdictResult,
    JobLineageResponse,
    JobPlaceSetResponse,
    JobTwinsResponse,
    LineageLinkRejected,
    RelationshipAssessment,
    TwinLinkCreated,
    TwinReviewResponse,
    TwinVerdictResult,
)
from tracker.api.serializers.jobs import serialize_job
from tracker.db.models import Job, JobLineage, JobLineageLink, JobTwinLink
from tracker.db.queries.jobs import list_rows, pair_on_board, row_context
from tracker.intelligence.duplicate_review import (
    PROMPT_VERSION as DUPLICATE_REVIEW_PROMPT_VERSION,
)
from tracker.intelligence.duplicate_review import (
    assess_duplicate,
)
from tracker.intelligence_runtime.local_profiles import (
    get_active_profile as get_active_local_llm_profile,
)
from tracker.intelligence_runtime.local_profiles import (
    get_enabled as get_local_llm_enabled,
)
from tracker.intelligence_runtime.telemetry import log_ai_task
from tracker.lineage.content_diff import compare_descriptions
from tracker.lineage.detect import effective_link_clause, link_fact, rebuild_lineage_projection
from tracker.lineage.diff import build_member_diff
from tracker.lineage.pairs import (
    PairRefused,
    human_twin_row,
    require_one_company,
)
from tracker.lineage.place_sets import NotAMember, place_set_of, review_place_set_member
from tracker.lineage.project import choose_predecessors
from tracker.lineage.reasons import duplicate_reasons, twin_reasons
from tracker.lineage.review import (
    LinkNotFound,
    _confirm_twin_pair,
    decide_lineage_link,
    decide_twin_link,
    lock_relationships,
)
from tracker.lineage.twins import connected_twin_ids, twin_component_links
from tracker.local_llm.client import LocalLLMClient, LocalLLMError

router = APIRouter()


def _serialize_link(link: JobLineageLink) -> dict:
    ev = link.evidence or {}
    return {
        "proposal_kind": "duplicate",
        "id": link.id,
        "job_id": link.job_id,
        "prior_job_id": link.prior_job_id,
        "relation": link.relation,
        "method": link.method,
        "confidence": link.confidence,
        "status": link.status,
        "score": link.score,
        "gap_days": link.gap_days,
        "reasons": ev.get("reasons", []),
        "said": duplicate_reasons(link.method, link.relation, ev),
        "decision": ev.get("review_outcome"),
        "decision_changes": len(ev.get("decision_history", [])),
        "reviewed_at": link.reviewed_at,
    }


def _serialize_twin_link(link: JobTwinLink) -> dict:
    ev = link.evidence or {}
    return {
        "proposal_kind": "twin",
        "id": link.id,
        "job_id": link.job_b_id,
        "prior_job_id": link.job_a_id,
        "relation": "twin",
        "method": link.method,
        "confidence": link.confidence,
        "status": link.status,
        "score": link.score,
        "gap_days": None,
        "title_similarity": link.title_similarity,
        "reasons": ev.get("reasons", []),
        "said": twin_reasons(ev),
        "decision": ev.get("review_outcome"),
        "decision_changes": len(ev.get("decision_history", [])),
        "reviewed_at": link.reviewed_at,
        "description_diff": ev.get("description_diff"),
    }


async def _review_postings(session: AsyncSession, job_ids: set[int], detail: bool) -> dict[int, Job]:
    """The postings of a page of review items, by id. The summary form leaves
    the description columns unread (`list_rows`), as a list row does."""
    stmt = select(Job).where(Job.id.in_(job_ids))
    return {job.id: job for job in (await session.scalars(stmt if detail else list_rows(stmt))).all()}


def _review_statuses(status: str) -> tuple[str, ...]:
    """Map the review API lens to stored human-decision states."""
    if status == "reviewed":
        return ("confirmed", "rejected")
    if status in ("pending", "confirmed", "rejected"):
        return (status,)
    raise api_error(400, ErrorCode.INVALID_INPUT, "status must be pending|confirmed|rejected|reviewed")


# exclude_unset: a posting diff names only the fields that moved (`PostingDiff`).
@router.get(
    "/api/jobs/{job_id}/lineage", response_model=JobLineageResponse, response_model_exclude_unset=True
)
async def job_lineage(job_id: int, session: SessionDep) -> dict:
    """The full stack for a job: every posting of the role, in order, with the
    change vs the previous posting. Standalone jobs return size 1 / no members list."""
    job = await session.get(Job, job_id)
    if job is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    if job.lineage_id is None:
        return {"lineage_id": None, "size": 1, "members": []}

    lineage = await session.get(JobLineage, job.lineage_id)
    members = list(
        (
            await session.scalars(
                select(Job).where(Job.lineage_id == job.lineage_id).order_by(Job.lineage_seq.asc())
            )
        ).all()
    )
    # Inbound link per successor member: the one the projection chose
    # (`project.choose_predecessors`), never the last row read, so
    # a pending proposal to a posting outside the lineage cannot stand in
    # for the confirmed link that placed the member.
    links = (
        await session.scalars(
            select(JobLineageLink).where(
                JobLineageLink.job_id.in_([m.id for m in members]),
                effective_link_clause(),
            )
        )
    ).all()
    by_pair = {(lk.job_id, lk.prior_job_id): lk for lk in links}
    link_by_job = {
        job_id: by_pair[(fact.job_id, fact.prior_job_id)]
        for job_id, fact in choose_predecessors([link_fact(lk) for lk in links]).items()
    }

    ctx = await row_context(session, members, standing=False)
    payload_members = []
    prev = None
    for m in members:
        link = link_by_job.get(m.id)
        # Only an EFFECTIVE link ties a member to its predecessor in the stack.
        effective = link is not None and (
            (link.confidence == "auto" and link.status != "rejected") or link.status == "confirmed"
        )
        payload_members.append(
            {
                "seq": m.lineage_seq,
                "role": m.lineage_role,
                "job": serialize_job(m, detail=True, **ctx),
                "link": _serialize_link(link) if link is not None else None,
                "diff_vs_prev": build_member_diff(prev, m) if (prev is not None and effective) else None,
            }
        )
        prev = m

    return {
        "lineage_id": lineage.id,
        "root_job_id": lineage.root_job_id,
        "company": lineage.company,
        "size": lineage.size,
        "open_members": lineage.open_members,
        "first_seen": lineage.first_seen,
        "last_seen": lineage.last_seen,
        "members": payload_members,
    }


@router.get("/api/lineage/review", response_model=DuplicateReviewResponse, response_model_exclude_unset=True)
async def lineage_review(
    session: SessionDep,
    hidden: OffBoardDep,
    status: str = "pending",
    confidence: str | None = "suspected",
    order: Literal["strongest", "weakest"] = "strongest",
    on_board: bool = True,
    detail: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Offset = 0,
) -> dict:
    """Links awaiting a human verdict — the labeling surface. Each item pairs the
    two postings and the detector's evidence so the reviewer can decide fast.

    `order=weakest` puts the lowest score first: the order for checking links
    the detector merged on its own (`confidence=auto`), where the weakest are
    the likeliest mistakes.

    A pending pair is listed only while one of its postings is on the Board
    (`pair_on_board`); `on_board=false` lists every pending pair.
    A decided pair is listed whatever its postings show now, and the
    `reviewed` lens lists the newest verdict first. A verdict keeps the link's
    confidence, so the Decided list asks for every confidence (`confidence=`).

    `detail=false` is the summary form a list of many pairs reads: each
    posting as a list row, its description neither read nor sent."""
    conds = [JobLineageLink.status.in_(_review_statuses(status))]
    if confidence:
        conds.append(JobLineageLink.confidence == confidence)
    if status == "pending" and on_board:
        conds.append(pair_on_board(JobLineageLink.job_id, JobLineageLink.prior_job_id, hidden))
    total = await session.scalar(
        select(func.count()).select_from(JobLineageLink).where(*conds)
    )
    links = (
        await session.scalars(
            select(JobLineageLink)
            .where(*conds)
            .order_by(
                JobLineageLink.reviewed_at.desc().nullslast()
                if status == "reviewed"
                else JobLineageLink.score.asc().nullsfirst()
                if order == "weakest"
                else JobLineageLink.score.desc().nullslast(),
                JobLineageLink.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    job_ids = {lk.job_id for lk in links} | {lk.prior_job_id for lk in links}
    jobs = await _review_postings(session, job_ids, detail)
    ctx = await row_context(session, list(jobs.values()), unfollowed=hidden.unfollowed, standing=False)
    items = []
    for lk in links:
        job, prior = jobs.get(lk.job_id), jobs.get(lk.prior_job_id)
        if job is None or prior is None:
            continue
        items.append(
            {
                "link": _serialize_link(lk),
                "job": serialize_job(job, detail=detail, **ctx),
                "prior": serialize_job(prior, detail=detail, **ctx),
                "diff": build_member_diff(prior, job),
            }
        )
    return {"total": total or 0, "limit": limit, "offset": offset, "items": items}


#: `pending` takes the last verdict back.
LineageVerdict = Literal["confirmed", "rejected", "twin", "pending"]


class LineageReviewPayload(BaseModel):
    verdict: LineageVerdict


@router.post("/api/lineage/links/{link_id}/review", response_model=DuplicateVerdictResult)
async def review_lineage_link(
    link_id: int, payload: LineageReviewPayload, session: SessionDep
) -> dict:
    """Record a human verdict on a link, then rebuild the projection so the counts
    and aging clock reflect it immediately. `pending` withdraws the last verdict:
    the link returns to the queue and what the verdict changed beyond it — the
    twin it confirmed, the counterpart it rejected — goes back as it was."""
    # One transaction: the verdict, the rows it changed and the projection it
    # decides are committed together or not at all.
    try:
        outcome = await decide_lineage_link(session, link_id, payload.verdict)
    except LinkNotFound as exc:
        raise api_error(404, ErrorCode.LINK_NOT_FOUND, str(exc)) from exc
    n = await rebuild_lineage_projection(session)
    await session.commit()
    link = outcome.link
    return {
        "id": link.id,
        "status": link.status,
        "reviewed_at": link.reviewed_at,
        "lineages": n,
        "decision": outcome.decision,
        "twin_link_id": outcome.twin_link_id,
        "kept": outcome.kept,
    }


@router.get("/api/twins/review", response_model=TwinReviewResponse, response_model_exclude_unset=True)
async def twin_review(
    session: SessionDep,
    hidden: OffBoardDep,
    status: str = "pending",
    confidence: str | None = "suspected",
    on_board: bool = True,
    detail: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Offset = 0,
) -> dict:
    """Twin proposals and durable human decisions in the duplicate queue's shape.
    A pending pair is listed only while one of its postings is on the Board,
    and the `reviewed` lens lists the newest verdict first, as in the duplicate
    queue. `detail=false` is the same summary form, and it also leaves out the
    description diff, so no two descriptions are compared."""
    conds = [JobTwinLink.status.in_(_review_statuses(status))]
    if confidence:
        conds.append(JobTwinLink.confidence == confidence)
    if status == "pending" and on_board:
        conds.append(pair_on_board(JobTwinLink.job_a_id, JobTwinLink.job_b_id, hidden))
    total = await session.scalar(select(func.count()).select_from(JobTwinLink).where(*conds))
    links = (
        await session.scalars(
            select(JobTwinLink)
            .where(*conds)
            .order_by(
                JobTwinLink.reviewed_at.desc().nullslast()
                if status == "reviewed"
                else JobTwinLink.score.desc().nullslast(),
                JobTwinLink.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    job_ids = {link.job_a_id for link in links} | {link.job_b_id for link in links}
    jobs = await _review_postings(session, job_ids, detail)
    ctx = await row_context(session, list(jobs.values()), unfollowed=hidden.unfollowed, standing=False)
    items = []
    for link in links:
        prior, job = jobs.get(link.job_a_id), jobs.get(link.job_b_id)
        if prior is None or job is None:
            continue
        item = {
            "link": _serialize_twin_link(link),
            "job": serialize_job(job, detail=detail, **ctx),
            "prior": serialize_job(prior, detail=detail, **ctx),
            "diff": build_member_diff(prior, job),
        }
        if detail:
            item["description_diff"] = compare_descriptions(
                prior.description_sections,
                prior.description_text,
                job.description_sections,
                job.description_text,
            ).evidence()
        items.append(item)
    return {"total": total or 0, "limit": limit, "offset": offset, "items": items}


#: `pending` takes the last verdict back.
TwinVerdict = Literal["confirmed", "rejected", "duplicate", "pending"]


class TwinReviewPayload(BaseModel):
    verdict: TwinVerdict


@router.post("/api/twins/links/{link_id}/review", response_model=TwinVerdictResult)
async def review_twin_link(
    link_id: int, payload: TwinReviewPayload, session: SessionDep
) -> dict:
    """Record a human verdict on a twin proposal. `pending` withdraws the last
    verdict exactly as on a lineage link."""
    try:
        outcome = await decide_twin_link(session, link_id, payload.verdict)
    except LinkNotFound as exc:
        raise api_error(404, ErrorCode.LINK_NOT_FOUND, str(exc)) from exc
    lineages = await rebuild_lineage_projection(session)
    await session.commit()
    link = outcome.link
    return {
        "id": link.id,
        "status": link.status,
        "decision": outcome.decision,
        "reviewed_at": link.reviewed_at,
        "lineages": lineages,
        "kept": outcome.kept,
    }


class TwinLinkPayload(BaseModel):
    job_id: int
    twin_job_id: int


@router.post("/api/twins/links", status_code=201, response_model=TwinLinkCreated)
async def create_twin_link(payload: TwinLinkPayload, session: SessionDep) -> dict:
    if payload.job_id == payload.twin_job_id:
        raise api_error(400, ErrorCode.LINK_TO_ITSELF, "cannot link a job to itself")
    await lock_relationships(session)
    jobs = list(
        (
            await session.scalars(
                select(Job).where(Job.id.in_([payload.job_id, payload.twin_job_id]))
            )
        ).all()
    )
    if len(jobs) != 2:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    try:
        require_one_company(jobs[0], jobs[1], "twin")
    except PairRefused as exc:
        raise api_error(exc.status, ErrorCode.PAIR_REFUSED, exc.detail) from exc
    if (
        jobs[0].lineage_id is not None
        and jobs[1].lineage_id is not None
        and jobs[0].lineage_id == jobs[1].lineage_id
    ):
        raise api_error(409, ErrorCode.ALREADY_LINKED, "the jobs are already the same opening lineage")
    # A person's word stands: a twin decided before is answered as
    # it stands, or refused if it says otherwise; changing it is a verdict.
    decided = await human_twin_row(session, payload.job_id, payload.twin_job_id)
    if decided is not None:
        if decided.status == "confirmed":
            return {"id": decided.id, "status": "confirmed", "decision": "twin"}
        raise api_error(409, ErrorCode.VERDICT_DECIDED, "a person decided these postings already; change that verdict in History")
    twin = await _confirm_twin_pair(
        session,
        payload.job_id,
        payload.twin_job_id,
        method="manual",
        evidence={"review_outcome": "twin", "reasons": ["human-created twin relationship"]},
    )
    await session.commit()
    return {"id": twin["id"], "status": "confirmed", "decision": "twin"}


@router.get("/api/jobs/{job_id}/twins", response_model=JobTwinsResponse)
async def job_twins(job_id: int, session: SessionDep) -> dict:
    if await session.get(Job, job_id) is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    links = await twin_component_links(session, job_id)
    component, direct = connected_twin_ids(job_id, list(links.values()))
    member_ids = {job_id} | component
    jobs = {
        job.id: job
        for job in (
            await session.scalars(select(Job).where(Job.id.in_(member_ids)))
        ).all()
    }
    # Only a direct link is shown with its evidence, so only those rows load whole.
    own = [link_id for link_id, (a, b) in links.items() if job_id in (a, b)]
    direct_links = {
        (link.job_b_id if link.job_a_id == job_id else link.job_a_id): link
        for link in (
            await session.scalars(select(JobTwinLink).where(JobTwinLink.id.in_(own)))
        ).all()
    }
    ordered_ids = [job_id] + sorted(component)
    ctx = await row_context(session, list(jobs.values()), standing=False)
    return {
        "job_id": job_id,
        "size": len(member_ids),
        "direct_count": len(direct),
        "members": [
            {
                "job": serialize_job(jobs[member_id], detail=True, **ctx),
                "direct": member_id in direct,
                "link": (
                    _serialize_twin_link(direct_links[member_id])
                    if member_id in direct_links
                    else None
                ),
            }
            for member_id in ordered_ids
            if member_id in jobs
        ],
    }


def _stated_pay(job: Job) -> dict | None:
    """The base band a posting states, or None when it states none."""
    if job.disclosed_base_min is None and job.disclosed_base_max is None:
        return None
    return {
        "low": job.disclosed_base_min,
        "high": job.disclosed_base_max,
        "currency": job.disclosed_currency,
        "period": job.disclosed_pay_period,
    }


async def _place_set_response(session: AsyncSession, job_id: int) -> dict:
    state = await place_set_of(session, job_id)
    found = state["set"]
    if found is None:
        return {
            "job_id": job_id,
            "place_set": None,
            "rejected": state["rejected"],
            "rejected_at": state["rejected_at"],
        }
    jobs = {
        job.id: job
        for job in (
            await session.scalars(select(Job).where(Job.id.in_(found["member_ids"])))
        ).all()
    }
    ctx = await row_context(session, list(jobs.values()), standing=False)
    return {
        "job_id": job_id,
        "place_set": {
            "id": found["id"],
            "size": found["size"],
            "places": found["places"],
            "employer_label": found["employer_label"],
            "rule_version": found["rule_version"],
            "members": [
                {
                    "job": serialize_job(jobs[member_id], **ctx),
                    "is_this": member_id == job_id,
                    "relation": found["relations"].get(member_id, "place"),
                    "same_place": member_id != job_id
                    and found["place_keys"].get(member_id) is not None
                    and found["place_keys"].get(member_id) == found["place_keys"].get(job_id),
                    "stated_pay": _stated_pay(jobs[member_id]),
                }
                for member_id in found["member_ids"]
                if member_id in jobs
            ],
        },
        "rejected": False,
        "rejected_at": None,
    }


@router.get("/api/jobs/{job_id}/place-set", response_model=JobPlaceSetResponse)
async def job_place_set(job_id: int, session: SessionDep) -> dict:
    """The role's other places: postings with the same title and text, each at
    a different place, decided by rule and never queued."""
    if await session.get(Job, job_id) is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    return await _place_set_response(session, job_id)


class PlaceSetReviewPayload(BaseModel):
    #: `different` splits the posting out of its set; `pending` takes that back.
    decision: Literal["different", "pending"]


@router.post("/api/jobs/{job_id}/place-set/review", response_model=JobPlaceSetResponse)
async def review_job_place_set(
    job_id: int, payload: PlaceSetReviewPayload, session: SessionDep
) -> dict:
    if await session.get(Job, job_id) is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    try:
        await review_place_set_member(session, job_id, payload.decision)
    except NotAMember as exc:
        raise api_error(409, ErrorCode.NOT_A_MEMBER, str(exc)) from exc
    return await _place_set_response(session, job_id)


async def _analyze_relationship_candidate(
    session: AsyncSession,
    *,
    link,
    prior: Job,
    newer: Job,
    proposal_kind: str,
) -> dict:
    """Run one advisory same-opening assessment for either proposal artifact."""
    # The switch is checked here too, not just in the routing registry: this is
    # an explicit user action on a direct client, so "off" must say so rather
    # than quietly running the model the user turned off.
    if not await get_local_llm_enabled(session):
        raise api_error(409, ErrorCode.LOCAL_MODELS_OFF, "Local models are turned off. Turn them on in Settings / Intelligence.")
    profile = await get_active_local_llm_profile(session)
    if profile is None:
        raise api_error(409, ErrorCode.NO_LOCAL_MODEL, "No local model is selected. Add one in Settings / Intelligence.")
    await end_read(session)
    try:
        result = await assess_duplicate(LocalLLMClient(profile), link, prior, newer)
    except LocalLLMError as exc:
        await log_ai_task(
            session,
            task_type="duplicate_review",
            provider=profile.provider,
            availability_state="available",
            validation_result="invalid",
            failure_class=exc.failure_class,
            prompt_version=DUPLICATE_REVIEW_PROMPT_VERSION,
            model_id=profile.model[:64],
            job_id=newer.id,
            meta={"link_id": link.id, "proposal_kind": proposal_kind},
        )
        await session.commit()
        raise api_error(exc.status_code, ErrorCode.MODEL_UNREACHABLE, str(exc)) from exc
    metrics = result["metrics"]
    await log_ai_task(
        session,
        task_type="duplicate_review",
        provider=profile.provider,
        availability_state="available",
        validation_result="ok",
        latency_ms=metrics.get("wall_time_ms"),
        input_tokens=metrics.get("prompt_tokens"),
        output_tokens=metrics.get("completion_tokens"),
        prompt_version=DUPLICATE_REVIEW_PROMPT_VERSION,
        model_id=profile.model[:64],
        job_id=newer.id,
        meta={
            "link_id": link.id,
            "proposal_kind": proposal_kind,
            "recommendation": result["assessment"]["recommendation"],
        },
    )
    await session.commit()
    return result


@router.post("/api/lineage/links/{link_id}/analyze", response_model=RelationshipAssessment)
async def analyze_lineage_link(link_id: int, session: SessionDep) -> dict:
    """Ask the selected local model for advice. Never mutates the human verdict."""
    link = await session.get(JobLineageLink, link_id)
    if link is None:
        raise api_error(404, ErrorCode.LINK_NOT_FOUND, "link not found")
    newer = await session.get(Job, link.job_id)
    prior = await session.get(Job, link.prior_job_id)
    if newer is None or prior is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "linked job not found")
    return await _analyze_relationship_candidate(
        session,
        link=link,
        prior=prior,
        newer=newer,
        proposal_kind="duplicate",
    )


@router.post("/api/twins/links/{link_id}/analyze", response_model=RelationshipAssessment)
async def analyze_twin_link(link_id: int, session: SessionDep) -> dict:
    """Expose the same optional AI judgment for twin-origin review candidates."""
    twin = await session.get(JobTwinLink, link_id)
    if twin is None:
        raise api_error(404, ErrorCode.LINK_NOT_FOUND, "twin link not found")
    prior = await session.get(Job, twin.job_a_id)
    newer = await session.get(Job, twin.job_b_id)
    if newer is None or prior is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "linked job not found")
    prompt_link = SimpleNamespace(
        id=twin.id,
        relation="twin",
        method=twin.method,
        score=twin.score,
        gap_days=None,
        evidence=twin.evidence,
    )
    return await _analyze_relationship_candidate(
        session,
        link=prompt_link,
        prior=prior,
        newer=newer,
        proposal_kind="twin",
    )


@router.delete("/api/lineage/links/{link_id}", response_model=LineageLinkRejected)
async def delete_lineage_link(link_id: int, session: SessionDep) -> dict:
    """Soft-delete: mark the link rejected (a durable negative label), never a hard
    delete — the verdict is kept as a labelled example."""
    await lock_relationships(session)
    link = await session.get(JobLineageLink, link_id, populate_existing=True, with_for_update=True)
    if link is None:
        raise api_error(404, ErrorCode.LINK_NOT_FOUND, "link not found")
    link.status = "rejected"
    link.reviewed_at = datetime.now(UTC)
    await session.flush()
    n = await rebuild_lineage_projection(session)
    await session.commit()
    return {"id": link_id, "status": "rejected", "lineages": n}
