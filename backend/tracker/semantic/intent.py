"""Standing intent vector — the user's stated aim plus their revealed taste.

    intent = embed(statement) + centroid(favorited/pursued) - centroid(dismissed)

Each term is L2-normalized before combining so no single term dominates by
magnitude, and the sum is re-normalized (cosine against `jobs.embedding` is
then a dot product, same convention as `embed_texts`). Any term may be absent —
a fresh install has no favorites, a statement is optional — and the vector is
whatever signal exists; with no signal at all there is no vector and callers
fall back to their non-intent behavior.

Ranking-only by design: the deterministic scope tiers own
the hard in/out decision, and this vector only reorders what they admit. The
statement embedding is computed once at profile save and passed IN by the
caller (settings_store owns its storage; the layer contract keeps this module
from importing it) — only the centroids are read here, live, because favorites
and dismissals change at interaction time, not scrape time.
"""

from __future__ import annotations

import math

from sqlalchemy import Select, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Favorite, Job, JobFeedback, Pursuit


def normalized(vector: list[float]) -> list[float] | None:
    """L2-normalize; a zero (or empty) vector has no direction and returns None."""
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm:
        return None
    return [x / norm for x in vector]


def centroid(vectors: list[list[float]]) -> list[float] | None:
    """Component-wise mean. pgvector rows arrive as numpy arrays; coerce to float."""
    if not vectors:
        return None
    dim = len(vectors[0])
    total = [0.0] * dim
    for vec in vectors:
        for i, x in enumerate(vec):
            total[i] += float(x)
    return [x / len(vectors) for x in total]


def combine_intent_vector(
    statement: list[float] | None,
    positive: list[list[float]],
    negative: list[list[float]],
) -> list[float] | None:
    """statement + centroid(positive) - centroid(negative), normalized.

    Missing terms are simply absent from the sum; None means no signal at all
    (or the terms cancelled exactly, which is equally unrankable).
    """
    terms: list[list[float]] = []
    for vec in (statement, centroid(positive)):
        unit = normalized(vec) if vec else None
        if unit is not None:
            terms.append(unit)
    negative_centroid = centroid(negative)
    if negative_centroid is not None:
        unit = normalized(negative_centroid)
        if unit is not None:
            terms.append([-x for x in unit])
    if not terms:
        return None
    dim = len(terms[0])
    summed = [sum(term[i] for term in terms) for i in range(dim)]
    return normalized(summed)


def positive_embeddings_stmt() -> Select:
    """Embeddings of jobs the user pulled toward: favorited or pursued.

    Union (not sum) — a favorited job that became a pursuit counts once.
    """
    ids = union(select(Favorite.job_id), select(Pursuit.job_id)).subquery()
    return select(Job.embedding).where(
        Job.id.in_(select(ids.c.job_id)), Job.embedding.isnot(None)
    )


def negative_embeddings_stmt() -> Select:
    """Embeddings of jobs the user pushed away: dismissed ("not for me")."""
    dismissed = select(JobFeedback.job_id).where(JobFeedback.verdict == "dismissed")
    return select(Job.embedding).where(
        Job.id.in_(dismissed), Job.embedding.isnot(None)
    )


async def build_intent_vector(
    session: AsyncSession, statement: list[float] | None
) -> list[float] | None:
    """Compose the standing intent vector from live feedback centroids.

    `statement` is the stored statement embedding (or None) — the caller reads
    it from settings_store and passes it in.
    """
    positive = [list(v) for v in (await session.scalars(positive_embeddings_stmt())).all()]
    negative = [list(v) for v in (await session.scalars(negative_embeddings_stmt())).all()]
    return combine_intent_vector(statement, positive, negative)
