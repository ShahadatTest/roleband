"""Best match: the two ranked orders of the job list.

* `relevance_search` — a typed query. Direct identity first (URL/req_id, then
  the conservative exact-title key), then hybrid ranked retrieval over the
  textual sources, reordered by the query vector.
* `intent_ranking` — no query. The SAME filtered set as any other sort,
  reordered by cosine to the standing intent vector: a ranking, never a gate.

Both return rows plus their per-row context and leave the wire shape to the API
boundary (`api/routers/jobs.py`). Model calls belong to the caller: the query
embedder is passed in and the intent vector arrives already built, so this
module loads no model and imports no web framework.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import Select, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_discovery import company_names
from tracker.config import get_settings
from tracker.db.models import Job, JobRelevanceReview, TrackedCompany
from tracker.db.queries.companies import is_followed
from tracker.db.queries.jobs import (
    LEVEL_PLACED_FIRST,
    UNPLACED_BY_YEARS,
    RowContext,
    apply_job_filters,
    count_with_placed,
    list_rows,
    one_per_place_set,
    row_context,
    structured_conds,
)
from tracker.search.llm import resolve_query
from tracker.search.parse import ParsedQuery, companies_mentioned
from tracker.search.policy import (
    CandidateEvidence,
    MatchClass,
    QueryKind,
    classify_candidate,
    fold_query,
    identity_probe,
    posting_signature,
    query_signature,
    resolve_query_kind,
)
from tracker.search.retrieval import (
    candidate_pool,
    exact_title_rows,
    fused_candidates,
    identifier_matches,
    match_total,
    textual_match,
)
from tracker.settings_store import get_ai_egress_enabled
from tracker.taxonomy.domains import DOMAIN_GROUPS

#: Turns a query remainder into its vector. An empty or None answer means no
#: vector: the lexical half ranks alone.
QueryEmbedder = Callable[[str], Awaitable[list[float] | None]]


# The worlds the why-chip may name on intent-ranked rows (never scores).
_WORLDS = frozenset(g.slug for g in DOMAIN_GROUPS)


def why_world(domains: list[str] | None, advisory_domain: str | None) -> str | None:
    """The world a row serves, as its slug: deterministic ladder first, the
    anchor advisory where the ladder could not place it. None when neither knows
    or the slug is no world: an absent chip, never a guess. The dashboard names
    it from its catalog, so the chip speaks the reader's language."""
    world = (domains[0] if domains else None) or advisory_domain
    return world if world in _WORLDS else None


def intent_ranked_stmt(
    params: dict, intent_vec: list[float], limit: int, offset: int
) -> Select:
    """The intent-ranked page query. Ordering ONLY: the WHERE is exactly
    `apply_job_filters` — no embedding predicate joins it, so unembedded rows
    stay in the set and simply sort last (cosine distance is NULL for them).
    A row whose level we place leads one whose level we cannot;
    inside "Level not placed" more required years lead; intent
    orders the rest."""
    dist = Job.embedding.cosine_distance(intent_vec).label("intent_distance")
    stmt = list_rows(apply_job_filters(select(Job, dist), params))
    return stmt.order_by(LEVEL_PLACED_FIRST, UNPLACED_BY_YEARS, nullslast(dist.asc()), Job.id.desc()).limit(limit).offset(offset)


@dataclass(frozen=True)
class IntentRow:
    job: Job
    #: Cosine similarity to the intent vector; None for a row with no embedding,
    #: which sorts last. Never rendered by the UI.
    relevance: float | None
    #: The world the role serves, as a slug, or None; never a score.
    why_world: str | None


@dataclass(frozen=True)
class IntentRanking:
    total: int
    rows: list[IntentRow]
    context: RowContext
    #: Rows whose level we place, which come first.
    placed_total: int = 0


async def intent_ranking(
    session: AsyncSession, params: dict, intent_vec: list[float], limit: int, offset: int
) -> IntentRanking:
    """Queryless Best matches: the normal list, reordered by intent.

    `total` is counted from the same filtered base as every other sort — the
    invariant that makes this a ranking and not a gate."""
    base = apply_job_filters(select(Job), params)
    total, placed_total = await count_with_placed(session, base)

    rows = (await session.execute(intent_ranked_stmt(params, intent_vec, limit, offset))).all()
    jobs = [row[0] for row in rows]
    page_ids = [j.id for j in jobs]
    context = await row_context(session, jobs, unfollowed=params.get("unfollowed", ()))
    # Qualitative per-row "why" for the intent-ranked board: the world the
    # role serves, from the deterministic ladder where it classified and the
    # anchor advisory where it did not. A display name, NEVER the score:
    # `relevance` stays unrendered by the UI.
    advisory_domains: dict[int, str] = {}
    if page_ids:
        advisory_domains = {
            r.job_id: r.domain
            for r in (
                await session.scalars(
                    select(JobRelevanceReview).where(
                        JobRelevanceReview.job_id.in_(page_ids),
                        JobRelevanceReview.domain.isnot(None),
                    )
                )
            ).all()
        }
    return IntentRanking(
        total=total or 0,
        rows=[
            IntentRow(
                job=job,
                # Embeddings are normalized, so 1 - cosine_distance = cosine similarity.
                relevance=(1.0 - float(dist)) if dist is not None else None,
                why_world=why_world(job.domains, advisory_domains.get(job.id)),
            )
            for job, dist in rows
        ],
        context=context,
        placed_total=placed_total,
    )


_PARSED_FIELDS = ("company", "level_band", "family", "workplace_type", "location_group")


def _match_class_for(qsig, job: Job, sources: list[str]) -> str:
    """The decision tree over one admitted row. Qualitative label, never a score."""
    decision = classify_candidate(
        qsig,
        CandidateEvidence(
            signature=posting_signature(
                title=job.title or "",
                family=job.family,
                track=job.track,
                level_band=job.level_band,
                domains=list(job.domains or []),
                company=job.company,
            ),
            sources=frozenset(sources),
        ),
    )
    # Admitted textual rows always classify: rejection needs semantic-only
    # evidence, and this path admits only textual rows.
    return decision.match_class.value if decision.match_class else MatchClass.RELATED.value


@dataclass(frozen=True)
class RankedRow:
    job: Job
    #: The fused RRF score; None for a row the fused set did not rank.
    relevance: float | None
    #: Membership badges. `exact` leads them on an exact row.
    matched_via: list[str]
    #: The qualitative class: a label, never a score.
    match_class: str


@dataclass(frozen=True)
class RelevanceResult:
    """The search answer without its transport envelope."""

    total: int
    matched: int
    ranking_truncated: bool
    rows: list[RankedRow]
    related_rows: list[RankedRow]
    related_total: int
    query_kind: QueryKind
    parsed: ParsedQuery
    #: Built once over BOTH sections.
    context: RowContext


def _ranked_rows(
    rows: list[tuple[Job, float | None, list[str]]],
    qsig,
    *,
    exact: bool,
) -> list[RankedRow]:
    """One response section, with per-row `match_class`."""
    return [
        RankedRow(
            job=job,
            relevance=float(rrf) if rrf is not None else None,
            # `exact` is a matched_via value only on exact rows; textual
            # badges the row also earned ride along.
            matched_via=(["exact", *via] if exact else via),
            match_class=MatchClass.EXACT.value if exact else _match_class_for(qsig, job, via),
        )
        for job, rrf, via in rows
    ]


def ranked_conds(merged: dict, remainder: str) -> list:
    """The structured conditions the textual sources rank under. The sources
    admit by `textual_match` themselves, so the row is not asked it twice; a
    place set's representative is the earliest member that text admits too.
    Public for the retrieval harness, which measures this path."""
    return structured_conds(
        merged,
        matching=lambda entity: [textual_match(remainder, entity=entity)],
        row_matched=True,
    )


async def exact_title_ids(
    session: AsyncSession, title_key: str, params: dict, raw_query: str
) -> list[int]:
    """Rows whose title key equals the query's, a place set once. Equality is
    Python's, so the one-row-per-set rule runs over the equal rows, never
    before them, and costs a query only when two equal rows share a set
    (a search budget counts its round trips)."""
    rows = await exact_title_rows(
        session, title_key, structured_conds(params, collapse=False), raw_query
    )
    ids = [job_id for job_id, _ in rows]
    sets = [set_id for _, set_id in rows if set_id is not None]
    if len(sets) == len(set(sets)):
        return ids
    return await one_per_place_set(session, ids)


async def board_company_names(
    session: AsyncSession, *, named_in: str | None = None
) -> dict[str, tuple[str, ...]]:
    """The companies a query may name: every named company whose postings the
    Board shows (followed and visible), with the names a person types for it.

    A name the Board does not show stays in the remainder. Search reads only
    the Board's companies, so filtering to any other could only empty it, and
    many company names are also the name of a skill ("snowflake", "docker").

    With `named_in`, only the companies the text names as the parser reads a
    name (`companies_mentioned`), so a query that names no company reads
    nothing here."""
    names = company_names()
    if named_in is not None:
        names = companies_mentioned(named_in, names)
        if not names:
            return {}
    shown = set(
        await session.scalars(
            select(TrackedCompany.slug).where(
                TrackedCompany.slug.in_(sorted(names)), TrackedCompany.visible.is_(True), is_followed()
            )
        )
    )
    return {slug: typed for slug, typed in names.items() if slug in shown}


async def relevance_search(
    session: AsyncSession,
    params: dict,
    q: str,
    limit: int,
    offset: int,
    include_related: bool = False,
    *,
    embed: QueryEmbedder,
) -> RelevanceResult:
    """Best-match search: direct identity first, then hybrid ranked retrieval.

    Resolution order: URL/req_id identity, conservative exact-title key,
    exploratory. Direct lookups run under EXPLICIT request filters only
    (parsed filters may narrow related retrieval; they must never hide an
    identity match). Exact rows are an unpaginated equality set that
    sorts above every related page; related rows appear only behind
    `include_related` and page independently.

    `embed` turns the remainder into the query vector. It is called only for a
    non-identifier query, and only while `search_semantic_enabled`.
    """
    settings = get_settings()
    q = fold_query(q)
    # The switch is read only when a model could be asked at all.
    egress_allowed = settings.search_llm_enabled and await get_ai_egress_enabled(session)
    # A model may name a company the text only describes, so it is offered
    # every company the Board shows; the local parser needs only those named.
    parsed = await resolve_query(
        q,
        egress_allowed=egress_allowed,
        companies=await board_company_names(session, named_in=None if egress_allowed else q),
    )

    merged = dict(params)
    structured = parsed.structured()
    for field in _PARSED_FIELDS:
        if not params.get(field) and structured.get(field):
            merged[field] = structured[field]
    # Money a query names bounds the base the Board's pay column shows.
    if params.get("base_min") is None and parsed.comp_min is not None:
        merged["base_min"] = parsed.comp_min
    if params.get("base_max") is None and parsed.comp_max is not None:
        merged["base_max"] = parsed.comp_max

    remainder = parsed.remainder or q

    # --- direct identity resolution: explicit filters only ----------------- #
    # A URL/req_id is a specific-row read, so it bypasses the standing
    # visibility gates (scope, hidden, dismissed) like the `ids` exemption
    # does. A title is a search, so the title probe keeps browse visibility.
    probe = identity_probe(q)
    ident_ids = (
        await identifier_matches(
            session, probe, structured_conds(params, browse_visibility=False)
        )
        if probe.is_identifier()
        else []
    )
    exact_ids = [] if ident_ids else await exact_title_ids(session, probe.title_key, params, q)
    kind = resolve_query_kind(
        has_identifier_match=bool(ident_ids), has_exact_title_match=bool(exact_ids)
    )

    if kind == "identifier":
        # The identity IS the answer: no fused retrieval, no related section,
        # and no textual count — trigram-scoring a pasted URL against every
        # title to fill a compat field is pure waste, so `matched` reports the
        # identity set itself (documented in dashboard/src/api/jobs.ts).
        jobs = (
            await session.scalars(
                list_rows(select(Job).where(Job.id.in_(ident_ids)).order_by(Job.id.desc()))
            )
        ).all()
        ctx = await row_context(session, list(jobs), unfollowed=params.get("unfollowed", ()))
        rows = _ranked_rows([(j, None, []) for j in jobs], None, exact=True)
        return RelevanceResult(
            total=len(rows), matched=len(rows), ranking_truncated=False,
            rows=rows, related_rows=[], related_total=0,
            query_kind=kind, parsed=parsed, context=ctx,
        )

    # Honest textual count: the size of the *textual match set*, not of any
    # response section.
    conds = ranked_conds(merged, remainder)
    matched_total = await match_total(session, conds, remainder)

    qvec: list[float] | None = None
    if settings.search_semantic_enabled:
        qvec = (await embed(remainder)) or None

    # Count first, then size the pool to it: the honest total is also what tells
    # the ranking how deep it needs to go.
    pool = candidate_pool(matched_total)
    fused, via_names = fused_candidates(conds, remainder, qvec, pool)
    ranked_total = int(await session.scalar(select(func.count()).select_from(fused)) or 0)
    via_cols = [fused.c[f"via_{name}"] for name in via_names]

    def _vias(row) -> list[str]:
        # By NAME, never by position: the two select shapes in this function
        # put the via columns at different indexes, and positional reads are
        # booleans: an offset mistake shifts every badge without a type error.
        return [name for name in via_names if row._mapping[f"via_{name}"]]

    qsig = query_signature(q, parsed)

    if kind == "exact_title":
        # Exact rows: the full equality set, stable and unpaginated. A row
        # keeps any textual badges/rank it also earned in the fused set,
        # fetched by id, so a wrong parsed filter cannot hide it.
        fused_rows = (
            await session.execute(
                select(fused.c.id, fused.c.rrf, *via_cols).where(fused.c.id.in_(exact_ids))
            )
        ).all()
        fused_of = {row[0]: (float(row[1]), _vias(row)) for row in fused_rows}
        exact_jobs = list(
            (
                await session.scalars(
                    list_rows(select(Job).where(Job.id.in_(exact_ids)).order_by(Job.id.desc()))
                )
            ).all()
        )
        # The fused rows already in hand ARE the overlap — recounting it would
        # re-execute the whole fusion to produce len() of a fetched list.
        related_total = ranked_total - len(fused_rows)

        related_rows: list[tuple[Job, float | None, list[str]]] = []
        if include_related and related_total:
            # Request offset/limit page the RELATED section only; the exact
            # section stays whole above every related page.
            stmt = list_rows(
                select(Job, fused.c.rrf, *via_cols)
                .join(fused, Job.id == fused.c.id)
                .where(Job.id.notin_(exact_ids))
                .order_by(fused.c.rrf.desc(), Job.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).all()
            related_rows = [(row[0], float(row[1]), _vias(row)) for row in rows]

        # One batched context over BOTH sections.
        ctx = await row_context(session, exact_jobs + [job for job, _, _ in related_rows], unfollowed=params.get("unfollowed", ()))
        rows = _ranked_rows(
            [(j, *(fused_of.get(j.id) or (None, []))) for j in exact_jobs],
            qsig, exact=True,
        )
        return RelevanceResult(
            # Exact-query total = exact primary rows; the related section has
            # its own independent count authority.
            total=len(rows), matched=matched_total,
            ranking_truncated=matched_total > pool,
            rows=rows, related_rows=_ranked_rows(related_rows, qsig, exact=False),
            related_total=related_total,
            query_kind=kind, parsed=parsed, context=ctx,
        )

    # --- exploratory: the hybrid page, plus per-row class labels ----------- #
    stmt = list_rows(
        select(Job, fused.c.rrf, *via_cols)
        .join(fused, Job.id == fused.c.id)
        .order_by(fused.c.rrf.desc(), Job.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    page = [(row[0], float(row[1]), _vias(row)) for row in rows]
    ctx = await row_context(session, [job for job, _, _ in page], unfollowed=params.get("unfollowed", ()))
    return RelevanceResult(
        total=ranked_total, matched=matched_total,
        ranking_truncated=matched_total > pool,
        rows=_ranked_rows(page, qsig, exact=False), related_rows=[], related_total=0,
        query_kind=kind, parsed=parsed, context=ctx,
    )
