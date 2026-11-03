"""SQL retrieval for Best-match search.

Membership is **textual evidence only**: full-text search or an explicit-floor
trigram match. The semantic vector may reorder rows those sources admitted; it
can never admit a row: on the shipped representation no cosine bound, absolute
or relative, distinguishes "no match" from "match", so a dense source cannot
define a match set. Ordering within an admitted set is the one claim it can
still make, and it is the same claim the queryless intent ranking already
makes with the same vector.

Ranking is weighted: `search_vector` is built with `setweight` (title=A,
department/team=B, body=C — `db/repo.SEARCH_VECTOR_SQL`), so `ts_rank_cd`
prefers a title hit over fifty body-boilerplate hits. The B tier also ADDS
department/team lexemes to the vector, so `@@` membership, here and on the
lexical filter path, reaches rows via their employer-stated category too.
Deliberate: category fields are search surfaces (see the note on
`SEARCH_VECTOR_SQL`).

Layer: builds SQL against `db.models.Job`; imported by `search/best_match.py`.
Structured filter conditions are built by `db/queries/jobs.py` (it owns
request/param policy) and passed in; this module applies them identically to
every source. Imports no `tracker.api`.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, func, literal, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from tracker.config import get_settings
from tracker.db.models import Job, JobPlaceSetMember
from tracker.search.policy import (
    DEFAULT_THRESHOLDS,
    IdentityProbe,
    SearchThresholds,
    exact_title_key,
    identity_url_key,
)

#: Membership badges, in source order. `semantic` is deliberately absent: a
#: badge is a membership claim ("your words appear here"), and the vector makes
#: none: it contributes rank, which `relevance` already carries.
VIA_NAMES: tuple[str, ...] = ("keyword", "fuzzy")


# --------------------------------------------------------------------------- #
# Direct identity resolution. Explicit request filters ONLY: a parsed filter
# is advisory and may be wrong, and it must never hide an exact URL/req/title
# match. Equality throughout: no `%`, no similarity(), no tsquery. An
# identifier that fuzzy-matched a different req would be the worst lie this
# feature can tell.
# --------------------------------------------------------------------------- #


async def identifier_matches(
    session: AsyncSession, probe: IdentityProbe, explicit_conds: list
) -> list[int]:
    """Row ids whose stored URL or complete req_id IS the query.

    URL identity compares canonical keys on both sides (tracking params and
    fragment removed, nothing else), so the stored side runs through the same
    pure function as the pasted side — a SQL approximation of that
    normalization would be a second implementation that drifts. The URL branch
    only runs when the query *is* a URL, so the (id, url) fetch is cheap.

    A bare req_id ambiguous across companies returns every explicitly-filtered
    equality match, never a guess at the company.
    """
    if probe.url_key is not None:
        rows = (
            await session.execute(
                select(Job.id, Job.url).where(*explicit_conds, Job.url.isnot(None))
            )
        ).all()
        ids = [jid for jid, url in rows if identity_url_key(url) == probe.url_key]
        if ids:
            return sorted(ids, reverse=True)
    if probe.req_id is not None:
        rows = (
            await session.scalars(
                select(Job.id)
                .where(*explicit_conds, Job.req_id == probe.req_id)
                .order_by(Job.id.desc())
            )
        ).all()
        return list(rows)
    return []


async def exact_title_matches(
    session: AsyncSession, title_key: str, explicit_conds: list, raw_query: str
) -> list[int]:
    """Row ids whose conservative title key equals the query's.

    Equality is decided ONLY by the pure `exact_title_key` in Python — the SQL
    side never approximates the normalization, so there is exactly one
    definition of "equal". The trigram `%` probe is a *prefilter*: two strings
    with equal keys differ at most by case/whitespace/dash/NFKC damage, none of
    which survives pg_trgm's own lowercase alphanumeric-trigram extraction, so
    their similarity is ~1.0 and the probe cannot lose a true match under any
    sane `pg_trgm.similarity_threshold` (nothing in this repo sets the GUC).
    That holds for the QUERY only because it arrives folded
    (`policy.fold_query`): pg_trgm applies no NFKC, so an unfolded full-width
    query scores 0.000 here. A STORED title in compatibility forms
    ("ＳＲＥ", "Oﬃcer") can still miss: a documented limit, not a guarantee.
    Without the prefilter, every keystroke pause would fetch and normalize every
    title on the event loop. The eval harness's identity gates are the
    executable proof this stays lossless.
    """
    return [job_id for job_id, _ in await exact_title_rows(session, title_key, explicit_conds, raw_query)]


async def exact_title_rows(
    session: AsyncSession, title_key: str, explicit_conds: list, raw_query: str
) -> list[tuple[int, int | None]]:
    """`exact_title_matches` with each row's place set (None outside one), read
    in the same round trip, so the caller collapses a set only when two equal
    rows share one."""
    if not title_key:
        return []
    member = aliased(JobPlaceSetMember)
    rows = (
        await session.execute(
            select(Job.id, Job.title, member.set_id)
            .outerjoin(member, and_(member.job_id == Job.id, member.status == "auto"))
            .where(*explicit_conds, Job.title.isnot(None), Job.title.op("%")(raw_query))
        )
    ).all()
    return sorted(
        ((jid, set_id) for jid, title, set_id in rows if exact_title_key(title) == title_key),
        reverse=True,
    )


def tsquery(text: str):
    """THE text-search query builder. Public: the lexical `q` filter path
    (`db/queries/jobs.py::apply_job_filters`) uses it too, so the parser/configuration cannot
    fork between the boolean filter and hybrid retrieval."""
    return func.websearch_to_tsquery("english", text)


def _trgm_similarity(remainder: str, entity=Job):
    return func.greatest(
        func.similarity(entity.title, remainder), func.similarity(entity.company, remainder)
    )


def fuzzy_predicate(
    remainder: str, thresholds: SearchThresholds = DEFAULT_THRESHOLDS, entity=Job
):
    """Trigram membership: `%` probes the GIN index, the explicit floor decides.

    A bare `similarity() >= x` plans as a Seq Scan because
    `gin_trgm_ops` answers the operator, not the function — while `%` alone
    hands the match set to the session GUC `pg_trgm.similarity_threshold`.
    Both terms together keep the Bitmap Index Scan AND make the threshold a
    named policy constant. The eval harness asserts the plan shape stays.
    """
    return and_(
        or_(entity.title.op("%")(remainder), entity.company.op("%")(remainder)),
        _trgm_similarity(remainder, entity) >= thresholds.trgm_min,
    )


def textual_match(
    remainder: str, thresholds: SearchThresholds = DEFAULT_THRESHOLDS, entity=Job
):
    """The boolean "this row is a hit" predicate, independent of ranking.

    Lexical OR explicit-floor fuzzy. This predicate is the whole membership
    story: counting it needs no candidate cap, which is what makes
    an honest `total` possible.
    """
    return or_(
        entity.search_vector.op("@@")(tsquery(remainder)),
        fuzzy_predicate(remainder, thresholds, entity),
    )


async def match_total(
    session: AsyncSession,
    conds: list,
    remainder: str,
    thresholds: SearchThresholds = DEFAULT_THRESHOLDS,
) -> int:
    """How many rows the query matches, counted from the predicate, never a pool.

    A pool size reported as `total` would be a capped number presented as a
    fact.
    """
    stmt = select(func.count()).select_from(
        select(Job.id).where(and_(*conds, textual_match(remainder, thresholds))).subquery()
    )
    return int(await session.scalar(stmt) or 0)


def candidate_pool(matched_total: int) -> int:
    """Per-source ranking depth, grown to cover the match set up to a ceiling.

    The pool limits *work*, never membership: a row outside the pool is still
    matched and still counted. When the ceiling binds, the caller must say so
    (`ranking_truncated`) — a silently truncated ranking is the defect this
    bound exists to expose, not to hide.
    """
    settings = get_settings()
    base = settings.search_candidate_pool
    ceiling = max(base, settings.search_candidate_pool_max)
    return int(min(max(base, matched_total), ceiling))


def fused_candidates(
    conds: list,
    remainder: str,
    qvec: list[float] | None,
    pool: int,
    thresholds: SearchThresholds = DEFAULT_THRESHOLDS,
):
    """RRF-fused candidates: textual sources admit, the vector only reorders.

    Lexical (weighted `ts_rank_cd`) and fuzzy (explicit-floor trigram) each
    rank up to `pool` rows under the same structured conditions. Their union
    is the admitted set. When a query vector exists, a third ranking orders
    *that admitted set* by cosine and joins the fusion — it reads ids from the
    textual union, so by construction it cannot add a row. Fused score
    is sum(1/(k+rank)). Returns (subquery, via_names); via columns exist only
    for the membership-bearing sources.
    """
    settings = get_settings()
    k = settings.search_rrf_k
    tsq = tsquery(remainder)

    # Every rank and every cap orders by score, then id newest first, as every
    # Board sort does. Equal scores are ordinary (`ts_rank_cd` takes a
    # few dozen values over thousands of matches): ordered by score alone, a tie
    # would take its rank, its RRF share and its place under the cap from
    # physical row order, which every run's rewrite of the job rows reshuffles.
    lex_order = (func.ts_rank_cd(Job.search_vector, tsq).desc(), Job.id.desc())
    lex = (
        select(Job.id.label("id"), func.row_number().over(order_by=lex_order).label("rnk"))
        .where(and_(*conds, Job.search_vector.op("@@")(tsq)))
        .order_by(*lex_order)
        .limit(pool)
        .cte("lex")
    )
    trgm_order = (_trgm_similarity(remainder).desc(), Job.id.desc())
    trgm = (
        select(Job.id.label("id"), func.row_number().over(order_by=trgm_order).label("rnk"))
        .where(and_(*conds, fuzzy_predicate(remainder, thresholds)))
        .order_by(*trgm_order)
        .limit(pool)
        .cte("trgm")
    )

    # The admitted set. Every downstream id — including the semantic ranking's —
    # comes from here.
    textual = union(select(lex.c.id), select(trgm.c.id)).subquery("textual")

    ranked = [("keyword", lex), ("fuzzy", trgm)]
    reorder = []
    if qvec is not None:
        # Bind through the pgvector type so its processor serializes the list;
        # a bare literal() sends a raw Python list and asyncpg rejects it.
        qv = literal(qvec, Vector(get_settings().embedding_dim))
        vec = (
            select(
                Job.id.label("id"),
                func.row_number()
                .over(order_by=(Job.embedding.cosine_distance(qv), Job.id.desc()))
                .label("rnk"),
            )
            .where(Job.id.in_(select(textual.c.id)), Job.embedding.isnot(None))
            .cte("vec")
        )
        reorder.append(("semantic", vec))

    join_target = textual
    rrf_sum = literal(0.0)
    cols = [textual.c.id.label("id")]
    for name, cte in [*ranked, *reorder]:
        join_target = join_target.outerjoin(cte, cte.c.id == textual.c.id)
        rrf_sum = rrf_sum + func.coalesce(1.0 / (k + cte.c.rnk), 0.0)
        if name in VIA_NAMES:
            cols.append((cte.c.rnk.isnot(None)).label(f"via_{name}"))
    cols.append(rrf_sum.label("rrf"))

    fused = select(*cols).select_from(join_target).subquery("fused")
    return fused, list(VIA_NAMES)
