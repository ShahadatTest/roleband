"""Job browse surface: list/detail/search, favorites, views, similar, facets.

For the list this module is transport and wire shape: filters, ordering and the
page's reader state come from `db/queries/jobs.py`, and both Best-match orders
from `search/best_match.py`. The model calls those orders need — the
query embedder and the intent vector — are chosen here and passed in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracker.agents.pursuits import ensure_favorite, lock_role_writes, public_pursuit
from tracker.analytics.comp_package import build_job_package, country_rows, select_baselines
from tracker.analytics.pay_floor import floor_check
from tracker.api.deps import MAX_WINDOW_DAYS, OffBoardDep, Offset, PageReadsDep, SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.jobs import (
    DismissResponse,
    FacetsResponse,
    FavoriteResponse,
    JobDetailResponse,
    JobListResponse,
    JobViewResponse,
    ListingHistoryResponse,
    PostingPageResponse,
    SimilarJobsResponse,
    UndismissResponse,
)
from tracker.api.schemas.text_class import text
from tracker.api.serializers.jobs import application_form_view, serialize_job
from tracker.comp_providers.base import OUR_PAY_COUNTRY
from tracker.company_store import visible_company_names
from tracker.db.models import (
    FEEDBACK_REASONS,
    CompareSelection,
    Favorite,
    Job,
    JobCompEstimate,
    JobFeedback,
    JobLifecycleEvent,
    JobQualification,
    JobRelevanceReview,
    JobSkill,
    Pursuit,
    SkillConcept,
)
from tracker.db.queries.jobs import (
    DEFAULT_SORT,
    LEVEL_FACET_KEY,
    JobSort,
    RowContext,
    SortOrder,
    browse_jobs,
    domain_facet_count_stmt,
    exclude_hidden,
    facet_count_stmt,
    known_order,
    known_sort,
    list_rows,
    open_in_scope_count_stmt,
    place_facet_count_stmt,
    row_context,
    unclassified_domain_count_stmt,
)
from tracker.db.queries.listing_history import lineage_members, listing_history, role_of
from tracker.db.queries.reference_pay import package_rows
from tracker.enrich.enricher import ESTIMATE_FIELDS
from tracker.plugins.registry import PAY_LEVELS, reader_providers
from tracker.schema import OUR_ESTIMATE_SOURCE
from tracker.search.best_match import (
    IntentRanking,
    RankedRow,
    RelevanceResult,
    intent_ranking,
    relevance_search,
)
from tracker.semantic.embed import embed_query
from tracker.semantic.intent import build_intent_vector
from tracker.semantic.similarity import similar_for_job
from tracker.settings_store import get_enabled_locations, get_intent_embedding, get_pay_floor
from tracker.skills.extract import required_years
from tracker.taxonomy.domains import DOMAIN_GROUPS
from tracker.taxonomy.locations import LOCATION_GROUPS, pay_country, tracked_city_nodes
from tracker.taxonomy.role_catalog import UNCLASSIFIED_KEY
from tracker.taxonomy.roles import ROLE_GROUPS
from tracker.taxonomy.tracks import TRACKS
from tracker.workflows.posting_pages import readable_on_open

router = APIRouter()


# exclude_unset: the envelope's search- and intent-only keys stay absent on the
# responses that do not set them, exactly as the handler's dicts leave them.
@router.get("/api/jobs", response_model=JobListResponse, response_model_exclude_unset=True)
async def list_jobs(
    session: SessionDep,
    hidden: OffBoardDep,
    company: Annotated[list[str] | None, Query()] = None,
    level_band: Annotated[list[str] | None, Query()] = None,
    level_confidence: str | None = None,
    family: Annotated[list[str] | None, Query()] = None,
    track: Annotated[list[str] | None, Query()] = None,
    location_group: Annotated[list[str] | None, Query()] = None,
    domain: Annotated[list[str] | None, Query()] = None,
    workplace_type: Annotated[list[str] | None, Query()] = None,
    status: str | None = "open",
    q: str | None = None,
    base_min: int | None = None,
    base_max: int | None = None,
    posted_within_days: Annotated[int | None, Query(ge=1, le=MAX_WINDOW_DAYS)] = None,
    new_today_only: bool = False,
    repost_today_only: bool = False,
    favorites_only: bool = False,
    dismissed_only: bool = False,
    discloses_pay: bool = False,
    viewed: Literal["read", "unread"] | None = None,
    ids: Annotated[list[int] | None, Query()] = None,
    # The schema publishes only the keys that order something; a key or a
    # direction the list does not know reads as the default, so an old link
    # keeps listing rows.
    sort: Annotated[JobSort, BeforeValidator(known_sort)] = DEFAULT_SORT,
    order: Annotated[SortOrder, BeforeValidator(known_order)] = "desc",
    include_related: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Offset = 0,
) -> dict:
    params = {
        "company": company,
        "level_band": level_band,
        "level_confidence": level_confidence,
        "family": family,
        "track": track,
        "location_group": location_group,
        "domain": domain,
        "workplace_type": workplace_type,
        "status": status,
        "q": q,
        "base_min": base_min,
        "base_max": base_max,
        "posted_within_days": posted_within_days,
        "new_today_only": new_today_only,
        "repost_today_only": repost_today_only,
        "favorites_only": favorites_only,
        "dismissed_only": dismissed_only,
        "discloses_pay": discloses_pay,
        "viewed": viewed,
        "ids": ids,
        "hidden": hidden,
        # Which off-Board companies are unfollowed: read with the list, so the
        # rows that can be at one (Saved, ids) say so for free. A
        # plain list (a dependency override) knows none.
        "unfollowed": getattr(hidden, "unfollowed", frozenset()),
    }

    # The Not-for-me lens is a review list, not a ranking: it reads in the
    # order the reader made the marks, newest first, whatever sort the board
    # carries. Ranking a dismissed set by intent would put the
    # roles the reader liked LEAST at the bottom, which is where a mis-click
    # would hide.
    if dismissed_only:
        sort, order = "dismissed_at", "desc"

    # Smart "Best match" path: natural-language parse + hybrid ranked retrieval.
    # Gated on sort=relevance + a non-empty query so every other caller keeps its
    # ordinary ordering.
    if sort == "relevance" and q and q.strip():
        result = await relevance_search(
            session, params, q, limit, offset,
            include_related=include_related, embed=embed_query,
        )
        return _relevance_response(result, limit=limit, offset=offset)

    # Queryless "Best matches": the SAME filtered set,
    # reordered by cosine to the standing intent vector (statement +
    # favorited/pursued centroid - dismissed centroid). Ranking only, never a
    # gate — total and membership are identical to any other sort, and rows
    # without an embedding still appear, sorted last. No intent signal at all
    # (fresh install, no statement, no feedback) falls back to the default
    # ordering.
    if sort == "relevance":
        stored = await get_intent_embedding(session)
        intent_vec = await build_intent_vector(
            session, stored["vector"] if stored else None
        )
        if intent_vec is not None:
            ranking = await intent_ranking(session, params, intent_vec, limit, offset)
            return _intent_response(ranking, limit=limit, offset=offset)

    page = await browse_jobs(session, params, sort=sort, order=order, limit=limit, offset=offset)
    response = {
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "items": [serialize_job(j, **page.context) for j in page.jobs],
    }
    if page.placed_total is not None:
        # Best fit with no intent signal yet: the placed group still leads.
        response["placed_total"] = page.placed_total
    return response


def _intent_response(ranking: IntentRanking, *, limit: int, offset: int) -> dict:
    """Queryless Best matches in the ordinary list envelope, plus `ranked_by`."""
    items = []
    for row in ranking.rows:
        data = serialize_job(row.job, **ranking.context)
        data["relevance"] = row.relevance
        data["why_world"] = row.why_world
        items.append(data)
    return {
        "total": ranking.total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "ranked_by": "intent",
        "placed_total": ranking.placed_total,
    }


def _relevance_items(rows: list[RankedRow], ctx: RowContext) -> list[dict]:
    """Serialize one Best-match section; the ranking's labels ride on each row."""
    items = []
    for row in rows:
        data = serialize_job(row.job, **ctx)
        data["relevance"] = row.relevance
        data["matched_via"] = row.matched_via
        data["match_class"] = row.match_class
        items.append(data)
    return items


def _relevance_response(result: RelevanceResult, *, limit: int, offset: int) -> dict:
    """The one relevance response envelope — every relevance branch returns through
    here, so a new field cannot be added to two of the three branches."""
    return {
        # Exploratory: the pageable fused set (never exceeds `matched`: the
        # vector reorders admitted rows, it cannot add any). Direct kinds:
        # the exact section only; the related section counts itself.
        "total": result.total,
        # Rows the query matches textually, counted from the predicate rather
        # than the pool — the honest match-set size.
        "matched": result.matched,
        # The pool grows to cover `matched`; past the ceiling it cannot. Then
        # the (related) ranking is a slice and the client must say so.
        "ranking_truncated": result.ranking_truncated,
        "limit": limit,
        "offset": offset,
        "items": _relevance_items(result.rows, result.context),
        "related_items": _relevance_items(result.related_rows, result.context),
        "related_total": result.related_total,
        "query_kind": result.query_kind,
        "parsed": result.parsed.as_echo(),
    }


async def _job_requirements(session: AsyncSession, job: Job) -> dict:
    """The requirements block for the detail payload.

    Only high-confidence, non-context rows are exposed, and evidence rides
    along, so the UI never shows an association without its quote.
    """
    if job.requirements_extracted_at is None:
        has_text = bool(job.description_sections) or bool(job.description_text)
        return {
            "state": "pending" if has_text else "unavailable",
            "extractor_version": None,
            "skills": [],
            "qualifications": [],
            "required_years": None,
        }

    skill_rows = (
        await session.execute(
            select(JobSkill, SkillConcept)
            .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
            .options(selectinload(JobSkill.evidence))
            .where(
                JobSkill.job_id == job.id,
                JobSkill.confidence == "high",
                JobSkill.importance_band != "context",
                SkillConcept.status == "active",
            )
            .order_by(JobSkill.importance_score.desc(), SkillConcept.display.asc())
        )
    ).all()

    def _evidence(rows) -> list[dict]:
        return [
            {
                "section_key": e.section_key,
                "section_title": e.section_title,
                "quote": e.quote,
                "start_offset": e.start_offset,
                "end_offset": e.end_offset,
                "modality": e.modality,
            }
            for e in rows
            if e.score > 0  # context-only units stay audit-internal
        ]

    skills = []
    for job_skill, concept in skill_rows:
        evidence = _evidence(job_skill.evidence)
        if not evidence:  # no displayable grounding -> no displayed skill
            continue
        skills.append(
            {
                "concept_id": concept.id,
                "slug": concept.slug,
                "facet": concept.facet,
                "category": concept.category,
                "importance_band": job_skill.importance_band,
                "importance_score": job_skill.importance_score,
                "confidence": job_skill.confidence,
                "modality": job_skill.modality,
                "proficiency": job_skill.proficiency,
                "evidence": evidence,
            }
        )

    qual_rows = (
        await session.scalars(
            select(JobQualification)
            .where(JobQualification.job_id == job.id, JobQualification.confidence == "high")
            .order_by(JobQualification.modality.desc(), JobQualification.id.asc())
        )
    ).all()
    qualifications = [
        {
            "id": q.id,
            "kind": q.kind,
            "display": q.display,
            "modality": q.modality,
            # What an experience row states, read back as the extractor wrote
            # it (`skills.extract`).
            "years": (q.value or {}).get("years"),
            "years_stated": list((q.value or {}).get("years_stated") or []),
            "evidence": [
                {
                    "section_key": q.section_key,
                    "section_title": q.section_title,
                    "quote": q.quote,
                    "start_offset": q.start_offset,
                    "end_offset": q.end_offset,
                    "modality": q.modality,
                }
            ],
        }
        for q in qual_rows
    ]

    return {
        "state": "ready",
        "extractor_version": job.requirements_extractor_version,
        "skills": skills,
        "qualifications": qualifications,
        "required_years": required_years(
            {"kind": q.kind, "modality": q.modality, "value": q.value} for q in qual_rows
        ),
    }


@router.get("/api/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: int, session: SessionDep) -> dict:
    job = await session.get(Job, job_id)
    if job is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    feedback = await session.scalar(select(JobFeedback).where(JobFeedback.job_id == job_id))
    ctx = await row_context(session, [job])
    lineage_meta = ctx["lineage_meta"]
    # The same reader state, and the same standing-posting sign, as the row a
    # list shows for this posting.
    data = serialize_job(job, detail=True, **ctx)
    data["feedback_reason"] = feedback.reason if feedback is not None else None

    # Advisory relevance verdict, with its rationale.
    # Display material only — the verdict never gates anything server-side.
    review = await session.scalar(
        select(JobRelevanceReview).where(JobRelevanceReview.job_id == job_id)
    )
    # Pursuit state: lets the detail pane offer the stage control without
    # a second request.
    pursuit_row = await session.scalar(select(Pursuit).where(Pursuit.job_id == job_id))
    data["pursuit"] = public_pursuit(pursuit_row) if pursuit_row is not None else None

    data["relevance_review"] = (
        {
            "domain": review.domain,
            "relevance": review.relevance,
            "confidence": review.confidence,
            "rationale": review.rationale,
            "tracked_worlds": review.tracked_worlds or [],
            "prompt_version": review.prompt_version,
            "provider": review.provider,
            "model_id": review.model_id,
            "reviewed_at": review.reviewed_at,
        }
        if review is not None
        else None
    )

    # Every pay figure of the source the job shows: ours, or the
    # plugin's while it answers pay, never a mix. One read says which source
    # (the applied set), and the figures, the per-provider breakdown and the
    # package's baselines all come from it, so a switch that lands while this
    # request runs cannot pair one source's headline with the other's breakdown.
    # A job no re-estimate has reached has no row: it shows its
    # stored copy and no breakdown, never an old observation's, whose list
    # can name both sources.
    providers = await reader_providers(session)
    shown = providers.source_for(PAY_LEVELS) or OUR_ESTIMATE_SOURCE
    # Who answers pay here and whether it has read this company: a
    # company the plugin has not read says "not covered", never a bare dash.
    data["pay_source"] = providers.answering(PAY_LEVELS, job.company)
    estimate = await session.get(JobCompEstimate, (job_id, shown))
    if estimate is not None:
        data.update({name: getattr(estimate, name) for name in ESTIMATE_FIELDS})
    data["comp_sources"] = list(estimate.sources or []) if estimate is not None else []

    # The comp package: what is cash / bonus / equity, and which of those the employer
    # actually stated. Anchored on the disclosed base when there is one, scaled
    # by this company's measured per-level split. Keyed by family too, so the derivation
    # can tell a same-family split from a borrowed one.
    # Only rungs for the posting's own country measure it: none when it names
    # places in several countries.
    country = pay_country(job.location_groups)
    baseline_rows = await package_rows(session, providers, job.company, country)
    # Several ladder rungs collapse into one band, so which row represents the
    # band is a decision, not a detail — see `select_baselines`. A worldwide-mix
    # row is not US pay and never measures a posting.
    baselines = select_baselines(country_rows(baseline_rows, country))
    data["comp_package"] = build_job_package(
        company=job.company,
        band=job.level_band,
        family=job.family,
        comp_low=data["comp_low"],
        comp_median=data["comp_median"],
        comp_high=data["comp_high"],
        comp_provenance=data["comp_provenance"],
        disclosed=data.get("disclosed_comp"),
        baselines=baselines,
        base_estimate=(
            {"low": data["comp_base_low"], "median": data["comp_base_median"], "high": data["comp_base_high"],
             "provider": data["comp_provider"], "as_of": data["comp_as_of"]}
            if data["comp_base_median"] is not None else None
        ),
        heuristic=shown == OUR_ESTIMATE_SOURCE,
        # Our split heuristic is measured on US pay only.
        us_pay=country == OUR_PAY_COUNTRY,
        covered=data["pay_source"]["covered"],
    )

    events = (
        await session.scalars(
            select(JobLifecycleEvent)
            .where(JobLifecycleEvent.job_id == job_id)
            .order_by(JobLifecycleEvent.created_at.asc())
        )
    ).all()
    data["lifecycle"] = [
        {"event_type": e.event_type, "detail": e.detail, "at": e.created_at} for e in events
    ]
    data["requirements"] = await _job_requirements(session, job)
    # Role age: one query for the lineage's postings, and only when
    # there is more than this one. The headline stays the posting's own.
    now = datetime.now(UTC)
    lineage = lineage_meta.get(job.lineage_id) if job.lineage_id is not None else None
    members = (
        await lineage_members(session, job.lineage_id)
        if lineage is not None and lineage.size >= 2
        else []
    )
    role = role_of(members, now)
    data["role_since"] = role["since"] if role else None
    data["role_days"] = role["days"] if role else None
    data["role_postings"] = role["postings"] if role else None
    # Is this a standing posting? The serializer read it off the same row
    # context a list reads; a posting with no first sighting has no verdict.
    data.setdefault("posting_reality", None)
    data["application_form"] = application_form_view(job.source_facts)
    data["application_form_readable"] = await readable_on_open(session, job)
    # Compared on the served block, whose period is already checked.
    data["pay_floor_check"] = floor_check(await get_pay_floor(session), data.get("disclosed_comp"))
    return data


@router.get("/api/jobs/{job_id}/history", response_model=ListingHistoryResponse)
async def get_listing_history(job_id: int, session: SessionDep) -> dict:
    """Every dated fact about a posting and the postings counted as its role.
    Read on demand, so Job detail's payload stays lean; built by
    `db.queries.listing_history`, which the agent tool reads too."""
    history = await listing_history(session, job_id, datetime.now(UTC))
    if history is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    return history


@router.post("/api/jobs/{job_id}/posting-page", response_model=PostingPageResponse)
async def read_posting_page_on_open(job_id: int, session: SessionDep, reads: PageReadsDep) -> dict:
    """Read the posting's own page because someone opened it.

    Called by Job detail AFTER it renders, never inside the detail read, so an
    open never waits on the source. One paced request at most per posting and
    text version; a repeat, or an open while one is in flight, answers from
    storage. `OpenPageReads.read_one` owns the transactions: none
    is held across the request. The reads are the app's.
    """
    result = await reads.read_one(session, job_id)
    if result is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    outcome, source_facts = result
    return {"outcome": outcome, "application_form": application_form_view(source_facts)}


@router.post("/api/jobs/{job_id}/view", response_model=JobViewResponse)
async def mark_job_viewed(job_id: int, session: SessionDep) -> dict:
    """Persist the first user open; repeat opens are idempotent."""
    job = await session.get(Job, job_id)
    if job is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    if job.viewed_at is None:
        job.viewed_at = datetime.now(UTC)
        await session.commit()
    return {"job_id": job.id, "viewed_at": job.viewed_at}


@router.get("/api/jobs/{job_id}/similar", response_model=SimilarJobsResponse)
async def similar_jobs(
    job_id: int,
    session: SessionDep,
    hidden: OffBoardDep,
    scope: str = "cross",
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> dict:
    """Semantically similar open positions. scope: within | cross | all."""
    if scope not in ("within", "cross", "all"):
        raise api_error(400, ErrorCode.INVALID_INPUT, "scope must be within|cross|all")

    # Hidden companies are excluded before the limit, by the one neighbour
    # contract the cache and the live query share.
    pairs = await similar_for_job(session, job_id, scope=scope, limit=limit, hidden=list(hidden))
    if not pairs:
        return {"scope": scope, "items": []}

    score_by_id = {nid: score for nid, score in pairs}
    jobs = (
        await session.scalars(
            list_rows(exclude_hidden(select(Job).where(Job.id.in_(list(score_by_id))), hidden))
        )
    ).all()
    by_id = {j.id: j for j in jobs}
    ctx = await row_context(session, list(jobs), unfollowed=hidden.unfollowed, standing=False)
    items = [
        {**serialize_job(by_id[nid], **ctx), "score": round(score, 4)}
        for nid, score in pairs
        if nid in by_id  # preserve score-desc order from similar_for_job
    ]
    return {"scope": scope, "items": items}


async def _visible_company_options(session: AsyncSession) -> dict[str, dict]:
    """Companies the filter may offer: every visible tracked company (built-in
    and user-added alike are rows). `facets` then drops the off-Board ones:
    an unfollowed company's postings are off the Board, so offering it would
    offer a company with nothing behind it."""
    return {slug: {"display": display} for slug, display in await visible_company_names(session)}


@router.get("/api/facets", response_model=FacetsResponse)
async def facets(session: SessionDep, hidden: OffBoardDep) -> dict:
    """Filter-sidebar options with open-job counts."""

    # Every count is of open roles, a place set once, so the number
    # beside an option is the rows choosing it lists.
    async def grouped(column) -> dict[str, int]:
        rows = (await session.execute(facet_count_stmt(column, hidden))).all()
        return {str(k): v for k, v in rows if k is not None}

    bound_locations = {
        str(k): v for k, v in (await session.execute(place_facet_count_stmt(hidden))).all()
    }

    # Worlds (domains), plus the unclassified bucket: NULL (pre-axis) and `{}`
    # (honestly unknown) rows are the fail-open volume and must stay findable,
    # not invisible.
    domain_counts = {
        str(k): v for k, v in (await session.execute(domain_facet_count_stmt(hidden))).all()
    }
    unclassified = int(await session.scalar(unclassified_domain_count_stmt(hidden)) or 0)
    if unclassified:
        domain_counts[UNCLASSIFIED_KEY] = unclassified

    # Location options follow the saved Settings scope, so the board filter and
    # the tracked-locations axis stay one concept.
    enabled_locations = await get_enabled_locations(session)

    off_board = set(hidden)
    return {
        "companies": {
            slug: option
            for slug, option in (await _visible_company_options(session)).items()
            if slug not in off_board
        },
        # Slugs only: the dashboard names them from its catalog.
        "families": {g.slug: {} for g in ROLE_GROUPS},
        "tracks": {t.slug: {} for t in TRACKS},
        # Tracked AND bound. A filter option that can only ever return nothing
        # is noise here, and across every group it is a wall of it — the scope may
        # cover the planet, but the board offers the slice that actually has
        # roles. Settings deliberately keeps showing every group
        # (`/api/scope/catalog`), because that is where you choose what to
        # track, and a market you cannot select is a market you cannot grow
        # into. Bands and workplace types offer only values with roles too.
        # `parent` travels with the option so the register can render the
        # nesting the taxonomy already has (metro under country under region)
        # instead of a flat list of sibling names. It is the RAW parent —
        # a client that shows only bound groups may find the parent absent, and
        # must render such a group at the top level rather than hiding it.
        # Tracked cities come after the taxonomy, with
        # their display and parent, so the board can nest and name them.
        "location_groups": {
            k: {"display": v["display"], "parent": v.get("parent")}
            for k, v in (*LOCATION_GROUPS.items(), *tracked_city_nodes(enabled_locations))
            if k in enabled_locations and bound_locations.get(k)
        },
        # Worlds with in-scope roles, plus the unclassified bucket. Options
        # follow the data, not the enabled set: a world the user disabled has
        # no in-scope rows, so it drops out on its own.
        "domains": {
            **{
                g.slug: {}
                for g in DOMAIN_GROUPS
                if domain_counts.get(g.slug)
            },
            **(
                {UNCLASSIFIED_KEY: {}}
                if domain_counts.get(UNCLASSIFIED_KEY)
                else {}
            ),
        },
        # Every open in-scope role the board can show, under the same guard the
        # counts use. A facet VALUE whose count equals this narrows nothing
        # (a broad region can match the entire board), and an option that cannot narrow is noise in a column whose whole job
        # is narrowing.
        "total": await session.scalar(open_in_scope_count_stmt(hidden)) or 0,
        "counts": {
            "company": await grouped(Job.company),
            # A posting that names no level counts under `unstated`, never
            # under Mid-level; the filter selects it by that key.
            "level_band": await grouped(LEVEL_FACET_KEY),
            "level_confidence": await grouped(Job.level_confidence),
            "family": await grouped(Job.family),
            "track": await grouped(Job.track),
            "workplace_type": await grouped(Job.workplace_type),
            "location_group": bound_locations,
            "domain": domain_counts,
        },
    }


@router.put("/api/jobs/{job_id}/favorite", response_model=FavoriteResponse)
async def add_favorite(job_id: int, session: SessionDep) -> dict:
    if await session.get(Job, job_id) is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    if await ensure_favorite(session, job_id):
        await session.commit()
    return {"job_id": job_id, "is_favorite": True}


@router.delete("/api/jobs/{job_id}/favorite", response_model=FavoriteResponse)
async def remove_favorite(job_id: int, session: SessionDep) -> dict:
    # Serialized with the star and a pursuit's implicit save.
    # Unsaving keeps the pursuit.
    await lock_role_writes(session, job_id)
    row = await session.scalar(select(Favorite).where(Favorite.job_id == job_id))
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"job_id": job_id, "is_favorite": False}


# The comparison holds three roles (the screen shows one full description
# diff per role past the first, and four roles put six job-description
# columns below the fold). Enforced here and not only in the
# dashboard because the cap is a property of the stored selection, not of one
# client's opinion about it.
COMPARE_CAP = 3


class CompareSelectionOut(BaseModel):
    """What is STORED, which is not always what was asked for.

    The endpoint echoes rather than 404s so the dashboard can reconcile its
    optimistic state against the truth in one round trip: ids past the cap and
    ids whose job is gone come back absent, and the rail count follows
    what is really there.
    """

    job_ids: list[int]


class CompareSelectionPayload(BaseModel):
    """The whole selection, every time.

    Replace-all rather than per-job toggles: the dashboard's verbs are
    whole-set (`setCompare`, `clearCompare`, and an Undo that restores an exact
    set), so a per-job API would turn one user action into four writes with no
    atomic point between them.
    """

    job_ids: list[int]


@router.get("/api/compare-selection", response_model=CompareSelectionOut)
async def get_compare_selection(session: SessionDep) -> CompareSelectionOut:
    rows = await session.scalars(
        select(CompareSelection.job_id).order_by(
            CompareSelection.position, CompareSelection.id
        )
    )
    # Clamped on the way out too, not only on the way in: a stored selection
    # can hold more rows than the cap, and the read is what a reload
    # restores. The extra row is left on disk rather than deleted by a
    # GET; the next write replaces the whole set.
    return CompareSelectionOut(job_ids=list(rows)[:COMPARE_CAP])


@router.put("/api/compare-selection", response_model=CompareSelectionOut)
async def put_compare_selection(
    payload: CompareSelectionPayload, session: SessionDep
) -> CompareSelectionOut:
    """Replace the selection, and answer with what survived.

    Unknown ids are dropped rather than refused. A stale id is not a client bug
    worth failing the whole write over — it is a job that closed while the tab
    was open, and the useful response is the selection minus that role, which
    the dashboard then renders. Deduplication is order-preserving: `position`
    is what the beacon reads to dock level with the role selected last.
    """
    seen: set[int] = set()
    wanted: list[int] = []
    for job_id in payload.job_ids:
        if job_id not in seen:
            seen.add(job_id)
            wanted.append(job_id)
    wanted = wanted[:COMPARE_CAP]

    live: set[int] = set()
    if wanted:
        live = set(await session.scalars(select(Job.id).where(Job.id.in_(wanted))))
    kept = [job_id for job_id in wanted if job_id in live]

    # Replace-all in one transaction: no window in which the selection is
    # partially written, which a toggle-shaped API could not promise.
    await session.execute(delete(CompareSelection))
    for position, job_id in enumerate(kept):
        session.add(CompareSelection(job_id=job_id, position=position))
    await session.commit()
    return CompareSelectionOut(job_ids=kept)


class FeedbackPayload(BaseModel):
    verdict: Literal["dismissed"]
    reason: str | None = Field(None, json_schema_extra=text("code"))


@router.put("/api/jobs/{job_id}/feedback", response_model=DismissResponse)
async def set_feedback(job_id: int, payload: FeedbackPayload, session: SessionDep) -> dict:
    """Record "not for me". Upserts — one verdict per job.

    Deliberately does NOT touch `in_scope`: that column is a projection of the
    saved scope axes and is recomputed wholesale on every scope save, which
    would silently resurrect anything folded into it. Dismissal is a list-time
    filter instead (see `_structured_conds`).
    """
    if payload.reason is not None and payload.reason not in FEEDBACK_REASONS:
        raise api_error(422, ErrorCode.INVALID_INPUT, f"unknown reason: {payload.reason!r}")
    job = await session.get(Job, job_id)
    if job is None:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
    row = await session.scalar(select(JobFeedback).where(JobFeedback.job_id == job_id))
    if row is None:
        session.add(JobFeedback(job_id=job_id, verdict=payload.verdict, reason=payload.reason))
    else:
        # A re-mark after an undo is a NEW mark: the lens orders by it.
        row.verdict = payload.verdict
        row.reason = payload.reason
        row.created_at = datetime.now(UTC)
    await session.commit()
    return {
        "job_id": job_id,
        "is_dismissed": True,
        "reason": payload.reason,
        # Everything the dismiss flow needs to OFFER an employer-vocabulary
        # exclusion without another read. Offer only — a rule is
        # written solely by explicit confirmation via POST /api/scope/rules.
        "company": job.company,
        "department": job.department,
        "team": job.team,
    }


@router.delete("/api/jobs/{job_id}/feedback", response_model=UndismissResponse)
async def clear_feedback(job_id: int, session: SessionDep) -> dict:
    row = await session.scalar(select(JobFeedback).where(JobFeedback.job_id == job_id))
    if row is not None:
        await session.delete(row)
        await session.commit()
    return {"job_id": job_id, "is_dismissed": False}
