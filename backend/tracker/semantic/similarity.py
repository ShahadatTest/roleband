"""Semantic "similar positions" — precomputed neighbors + on-demand fallback.

`rebuild_similarity` fills `job_similarity` with each job's top-K nearest neighbors by
embedding cosine distance (pgvector `<=>`), split into `within` (same company) and
`cross` (other companies) scopes. Runs as the `similarity` post-pass every scrape
(whole-corpus, so capped runs included); the CLI serves manual
rebuilds.

`similar_for_job` serves the API: it reads the precomputed table, falling back to a
live ANN query when the cache cannot answer (so the Drawer never shows a stale "no
matches").

One contract for both paths, applied before the
limit: a neighbour is open, in scope, embedded, and not at a company the reader
hid (`_ELIGIBLE`). A cached row is valid only while its stored score is still the
cosine of the two CURRENT vectors, so re-embedding either side retires it without
a stamp on the row. The cache answers only when it holds `limit` valid eligible
rows; otherwise the live query does, so a vacancy (a neighbour that closed, left
scope or is hidden) is filled by a current neighbour, never by a stale score.

`refresh_similarity` keeps the table current at the cost of what changed, not
of the corpus: it recomputes a source only when its answer can have moved (see
`refresh_similarity`), and the result is the table a full rebuild would write. A full rebuild still runs every `FULL_EVERY`, for the one change no
row records: a closed posting that reopens is a valid neighbour again.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, JobSimilarity
from tracker.db.session import session_scope
from tracker.settings_store import get_similarity_marks, record_similarity_refresh

logger = logging.getLogger(__name__)

_SCOPE_OP = {"within": "=", "cross": "<>"}

#: Which neighbour may be offered, for the live query and the cache alike: `n`
#: is the neighbour, `:hidden` the companies the reader hid.
_ELIGIBLE = """
    n.status = 'open'
    AND n.in_scope IS true
    AND n.embedding IS NOT NULL
    AND NOT (n.company = ANY(CAST(:hidden AS text[])))
"""

#: How far a cached score may sit from the current cosine and still be the
#: same pair of vectors (float rounding only).
_SCORE_TOLERANCE = 1e-6

#: A source: a posting that gets neighbours of its own, open or not.
_SOURCE = "j.in_scope IS true AND j.embedding IS NOT NULL"

#: How long the incremental refresh may run without a full rebuild.
FULL_EVERY = timedelta(days=7)


async def _live_neighbors(
    session: AsyncSession,
    job_id: int,
    scopes: list[str],
    limit: int,
    hidden: Sequence[str] = (),
) -> list[tuple[int, float]]:
    """Run the ANN query directly for the given scopes and merge by score."""
    merged: list[tuple[int, float]] = []
    for scope in scopes:
        op = _SCOPE_OP[scope]
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT n.id AS nid, 1 - (n.embedding <=> j.embedding) AS score
                    FROM jobs j JOIN jobs n ON n.id <> j.id
                    WHERE j.id = :job_id
                      AND j.embedding IS NOT NULL
                      AND {_ELIGIBLE}
                      AND n.company {op} j.company
                    ORDER BY n.embedding <=> j.embedding
                    LIMIT :k
                    """
                ),
                {"job_id": job_id, "k": limit, "hidden": list(hidden)},
            )
        ).all()
        merged.extend((r.nid, float(r.score)) for r in rows)
    merged.sort(key=lambda t: t[1], reverse=True)
    return merged[:limit]


async def _cached_neighbors(
    session: AsyncSession, job_id: int, scopes: list[str], limit: int, hidden: Sequence[str]
) -> list[tuple[int, float]] | None:
    """The cache's answer, or None when it cannot give one: fewer than `limit`
    valid eligible rows, or any row whose vectors have moved since."""
    rows = (
        await session.execute(
            text(
                f"""
                SELECT s.neighbor_job_id AS nid, s.score,
                       1 - (n.embedding <=> j.embedding) AS current
                FROM job_similarity s
                JOIN jobs j ON j.id = s.job_id
                JOIN jobs n ON n.id = s.neighbor_job_id
                WHERE s.job_id = :job_id
                  AND s.scope = ANY(CAST(:scopes AS text[]))
                  AND j.embedding IS NOT NULL
                  AND {_ELIGIBLE}
                ORDER BY s.score DESC
                LIMIT :k
                """
            ),
            {"job_id": job_id, "scopes": scopes, "k": limit, "hidden": list(hidden)},
        )
    ).all()
    if len(rows) < limit or any(abs(r.score - r.current) > _SCORE_TOLERANCE for r in rows):
        return None
    return [(r.nid, float(r.score)) for r in rows]


async def _recompute(session: AsyncSession, ids: Iterable[int], k: int) -> int:
    """Replace each source's rows with its current neighbours. Returns rows written."""
    written = 0
    for job_id in ids:
        await session.execute(delete(JobSimilarity).where(JobSimilarity.job_id == job_id))
        for scope in ("within", "cross"):
            neighbors = await _live_neighbors(session, job_id, [scope], k)
            for rank, (nid, score) in enumerate(neighbors):
                session.add(
                    JobSimilarity(job_id=job_id, neighbor_job_id=nid, scope=scope, rank=rank, score=score)
                )
                written += 1
    await session.flush()
    return written


async def _new_sources(session: AsyncSession) -> set[int]:
    """Sources with no rows at all: just embedded, just in scope, just seen."""
    rows = await session.execute(
        text(
            f"""
            SELECT j.id FROM jobs j
            WHERE {_SOURCE}
              AND NOT EXISTS (SELECT 1 FROM job_similarity s WHERE s.job_id = j.id)
            """
        )
    )
    return {r[0] for r in rows}


async def _invalid_sources(session: AsyncSession) -> set[int]:
    """Sources holding a row that is no longer a valid neighbour: it closed,
    left scope or lost its vector, or either side was re-embedded so the stored
    score is not the cosine any more."""
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT s.job_id FROM job_similarity s
            JOIN jobs j ON j.id = s.job_id
            JOIN jobs n ON n.id = s.neighbor_job_id
            WHERE NOT (n.status = 'open' AND n.in_scope IS true AND n.embedding IS NOT NULL)
               OR abs(s.score - (1 - (n.embedding <=> j.embedding))) > :tol
            """
        ),
        {"tol": _SCORE_TOLERANCE},
    )
    return {r[0] for r in rows}


async def _moved(session: AsyncSession, since: datetime) -> set[int]:
    """Sources whose vector was written after `since`."""
    rows = await session.scalars(
        select(Job.id).where(Job.in_scope.is_(True), Job.embedding.isnot(None), Job.embedded_at > since)
    )
    return set(rows.all())


async def _displaced(session: AsyncSession, arrivals: set[int], k: int) -> set[int]:
    """Sources an arrival now belongs among: a valid neighbour that is new or
    moved, nearer to the source than its farthest kept neighbour in that scope,
    or in a scope where the source keeps fewer than `k`. The nearest-neighbour
    relation is not symmetric, so this is read from every source, not from the
    arrival's own list."""
    if not arrivals:
        return set()
    rows = await session.execute(
        text(
            f"""
            WITH kept AS (
                SELECT job_id, scope, count(*) AS n, min(score) AS floor
                FROM job_similarity GROUP BY job_id, scope
            )
            SELECT DISTINCT j.id
            FROM jobs j
            JOIN jobs n ON n.id = ANY(CAST(:arrivals AS bigint[])) AND n.id <> j.id
            LEFT JOIN kept ON kept.job_id = j.id
                AND kept.scope = CASE WHEN n.company = j.company THEN 'within' ELSE 'cross' END
            WHERE {_SOURCE}
              AND n.status = 'open' AND n.in_scope IS true AND n.embedding IS NOT NULL
              AND (coalesce(kept.n, 0) < :k OR 1 - (n.embedding <=> j.embedding) > kept.floor)
            """
        ),
        {"arrivals": sorted(arrivals), "k": k},
    )
    return {r[0] for r in rows}


async def refresh_similarity(
    session: AsyncSession, *, k: int = 10, full: bool = False, now: datetime | None = None
) -> int:
    """Bring the neighbour table up to date. Returns rows written.

    Commit-free: the post-pass chain owns the transaction. A source that left
    (out of scope, no vector) loses its rows first; then the sources whose own
    rows no longer hold are recomputed, and after them every source one of
    those arrivals (a source new to the table, or re-embedded since the last
    refresh) now outranks a kept neighbour of. With `full`, an empty table, or
    no full rebuild within `FULL_EVERY`, every source is recomputed."""
    now = now or datetime.now(UTC)
    await session.execute(
        text(f"DELETE FROM job_similarity s USING jobs j WHERE j.id = s.job_id AND NOT ({_SOURCE})")
    )
    last_full, last_refresh = await get_similarity_marks(session)
    empty = (await session.scalar(select(JobSimilarity.id).limit(1))) is None
    if full or empty or last_full is None or last_refresh is None or now - last_full >= FULL_EVERY:
        ids = list(
            (await session.scalars(select(Job.id).where(Job.in_scope.is_(True), Job.embedding.isnot(None)))).all()
        )
        await session.execute(delete(JobSimilarity))
        written = await _recompute(session, ids, k)
        await record_similarity_refresh(session, now, full=True)
        logger.info("similarity rebuilt: %d rows over %d jobs", written, len(ids))
        return written

    arrivals = await _new_sources(session) | await _moved(session, last_refresh)
    stale = arrivals | await _invalid_sources(session)
    written = await _recompute(session, sorted(stale), k)
    displaced = await _displaced(session, arrivals, k) - stale
    written += await _recompute(session, sorted(displaced), k)
    await record_similarity_refresh(session, now, full=False)
    logger.info(
        "similarity refreshed: %d rows over %d changed and %d displaced jobs", written, len(stale), len(displaced)
    )
    return written


async def similar_for_job(
    session: AsyncSession,
    job_id: int,
    scope: str = "cross",
    limit: int = 8,
    hidden: Sequence[str] = (),
) -> list[tuple[int, float]]:
    """Return [(neighbor_job_id, score), ...] for a job: the cache when it can
    answer in full, the live query otherwise. `hidden` companies never take a
    slot."""
    scopes = ["within", "cross"] if scope == "all" else [scope]
    cached = await _cached_neighbors(session, job_id, scopes, limit, hidden)
    if cached is not None:
        return cached
    return await _live_neighbors(session, job_id, scopes, limit, hidden)


async def _run(k: int, full: bool) -> int:
    async with session_scope() as session:
        return await refresh_similarity(session, k=k, full=full)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the job similarity neighbor table.")
    parser.add_argument("-k", type=int, default=10, help="neighbors per scope per job")
    parser.add_argument("--full", action="store_true", help="recompute every source, not only what changed")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    written = asyncio.run(_run(args.k, args.full))
    print({"similarity_rows": written})


if __name__ == "__main__":
    main()
