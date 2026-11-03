"""Semantic clustering of roles (KMeans over embeddings).

Groups open roles by embedding similarity into interpretable clusters that complement
the curated `family` taxonomy (a single family often splits into several skill
clusters). Each cluster is labeled from its members' most characteristic skill
requirements (`characteristic_terms`) and tagged with the modal family. Runs as the `clusters`
post-pass every scrape (whole-corpus, so capped runs included); the
CLI entry point serves manual rebuilds.

k is chosen by silhouette score over a small candidate range unless pinned. A
corpus the last fit already clustered (the same rows, vectors and embedding
model) is not fitted again: its stored assignment is relabelled, since labels
also read families and requirements, which move without a vector moving.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import math
from collections import Counter
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import Cluster, Job, JobSkill, SkillConcept
from tracker.db.queries.skills import ELIGIBLE_REQUIREMENT
from tracker.db.session import session_scope
from tracker.settings_store import delete_setting, get_setting_dict, set_setting_dict
from tracker.taxonomy.roles import role_display

logger = logging.getLogger(__name__)


#: A new k must beat the standing one's silhouette by this much to replace it:
#: re-choosing k from scratch on every rebuild makes the group count flicker
#: between runs on a corpus that barely moved, and labels flicker with it.
K_CHANGE_MARGIN = 0.02


def stable_k(scores: dict[int, float], previous_k: int | None, margin: float = K_CHANGE_MARGIN) -> int:
    """The best-scoring k, unless the standing `previous_k` scores within
    `margin` of it: then the groups stay as many as they were. Pure."""
    best = max(scores, key=lambda k: (scores[k], -k))
    if previous_k in scores and scores[best] - scores[previous_k] < margin:
        return previous_k  # type: ignore[return-value]
    return best


def _kmeans(X, k: int):
    from sklearn.cluster import KMeans

    return KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)


def _silhouettes(X, k_min: int, k_max: int) -> tuple[dict[int, float], dict[int, Any]]:
    """Silhouette (cosine) for each k in [k_min, k_max], and the fit scored
    for each, so the chosen k is not fitted twice."""
    from sklearn.metrics import silhouette_score

    scores: dict[int, float] = {}
    fits: dict[int, Any] = {}
    for k in range(k_min, k_max + 1):
        fits[k] = km = _kmeans(X, k)
        scores[k] = float(silhouette_score(X, km.labels_, metric="cosine"))
        logger.info("k=%d silhouette=%.4f", k, scores[k])
    return scores, fits


#: The app setting holding the digest of the corpus the standing clusters
#: were fitted on (`_corpus_digest`).
CLUSTERS_FITTED_KEY = "clusters_fitted_on"


def _model_version(k: int) -> str:
    model = get_settings().embedding_model.rsplit("/", 1)[-1].lower()
    return f"kmeans-k{k}-{model}"[:48]


def _corpus_digest(rows, *, k: int | None, k_min: int, k_max: int) -> str:
    """What a fit reads: each row and when its vector was written, the
    embedding model, and the k asked for. Equal digests fit the same
    clustering, since the fit is seeded and reads rows in id order."""
    digest = hashlib.sha256(
        f"{get_settings().embedding_model}|k={k}|{k_min}-{k_max}".encode()
    )
    for row in rows:
        stamp = row.embedded_at.isoformat() if row.embedded_at else "-"
        digest.update(f"{row.id}@{stamp};".encode())
    return digest.hexdigest()


#: Concepts a group is never labelled by: what every role is expected to do
#: (`skills.analytics.COMPETENCY_CATEGORIES`, kept in step by a test). Labels
#: built from them would name every group the same way.
LABEL_EXCLUDED_CATEGORIES = frozenset({"process", "leadership", "collaboration"})

#: A skill names a group only when at least one in ten of its roles asks for
#: it. Without this, a group whose roles share no skill is named after
#: whichever skill a handful of them mention, and the label describes almost
#: none of its members; such a group is named by its discipline instead.
LABEL_MIN_SHARE = 0.1

#: The weight a label skill needs: at a one-in-ten share the group must name
#: it about 1.65 times as often as grouped roles overall (0.1 * ln 1.65 = 0.05),
#: a smaller lift as its share grows. A skill as common everywhere as here
#: says nothing about this group, however many of its roles name it.
LABEL_MIN_WEIGHT = 0.05


def characteristic_terms(
    members: dict[int, list[set[str]]],
    meta: dict[str, tuple[str, str]],
    *,
    limit: int = 6,
    min_roles: int = 2,
    min_share: float = LABEL_MIN_SHARE,
    min_weight: float = LABEL_MIN_WEIGHT,
) -> dict[int, list[dict]]:
    """Each group's most characteristic skills, against all grouped roles. Pure.

    `members`: group label -> one set of concept slugs per member role. A
    concept's weight in a group is `share_in_group * ln(share_in_group /
    share_overall)` (its contribution to the group's divergence from the whole,
    a class-based TF-IDF): frequent here AND rarer elsewhere. Ranking by summed
    importance instead would let a frequent concept lead every group and give
    two groups the same three in a different order. Competencies are
    never a label; a concept named by fewer than `min_roles` members is noise,
    and so is one under `min_share` of the group or `min_weight`.
    """
    total_roles = sum(len(roles) for roles in members.values())
    overall: Counter[str] = Counter()
    for roles in members.values():
        for skills in roles:
            overall.update(skills)
    out: dict[int, list[dict]] = {}
    for label, roles in members.items():
        size = len(roles)
        counts: Counter[str] = Counter()
        for skills in roles:
            counts.update(skills)
        scored = []
        for term, n in counts.items():
            display, category = meta.get(term, (term, ""))
            if n < min_roles or category in LABEL_EXCLUDED_CATEGORIES or not total_roles:
                continue
            here, everywhere = n / size, overall[term] / total_roles
            weight = here * math.log(here / everywhere)
            if here >= min_share and weight >= min_weight:
                scored.append({"term": term, "display": display, "weight": round(weight, 4)})
        scored.sort(key=lambda t: (-t["weight"], t["term"]))
        out[label] = scored[:limit]
    return out


async def _member_skills(session: AsyncSession, job_ids: list[int]) -> tuple[dict[int, set[str]], dict[str, tuple[str, str]]]:
    """Each job's eligible requirement concepts (`ELIGIBLE_REQUIREMENT`)."""
    rows = (
        await session.execute(
            select(JobSkill.job_id, SkillConcept.slug, SkillConcept.display, SkillConcept.category)
            .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
            .where(JobSkill.job_id.in_(job_ids), *ELIGIBLE_REQUIREMENT)
        )
    ).all()
    by_job: dict[int, set[str]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for job_id, slug, display, category in rows:
        by_job.setdefault(job_id, set()).add(slug)
        meta[slug] = (display, category or "")
    return by_job, meta


def _label(top_terms: list[dict], family_hint: str | None) -> str:
    if top_terms:
        return " · ".join(t["display"] for t in top_terms[:3])
    return role_display(family_hint) if family_hint else "Unlabeled cluster"


#: Distances are stored to this precision: they only order a cluster's members
#: ("most central first"), and a refit that moves a centroid by a hair must
#: not rewrite every row it touches.
DISTANCE_DECIMALS = 3


def _match_clusters(
    new_members: dict[int, set[int]], old_members: dict[int, set[int]]
) -> dict[int, int]:
    """New cluster label -> the existing cluster id it continues, by member
    overlap (Jaccard), greedily from the closest pair, one to one. A new
    cluster sharing no more than half its union with any old one is new.
    Keeps `/api/clusters/{id}` links, and every member's `cluster_id`, stable
    while the corpus barely moves."""
    pairs = []
    for label, members in new_members.items():
        for cluster_id, old in old_members.items():
            union = len(members | old)
            if union:
                pairs.append((len(members & old) / union, label, cluster_id))
    matched: dict[int, int] = {}
    taken: set[int] = set()
    for score, label, cluster_id in sorted(pairs, reverse=True):
        if score <= 0.5 or label in matched or cluster_id in taken:
            continue
        matched[label] = cluster_id
        taken.add(cluster_id)
    return matched


async def _write_clusters(
    session: AsyncSession,
    *,
    ids: list[int],
    families: list[str | None],
    labels: list[int],
    distances: list[float],
    k: int,
) -> None:
    """Write the clustering, touching only rows whose assignment changed.

    Clusters keep their ids where their members do; a job is written only
    when its cluster or its stored distance changed; a job that left the set
    is cleared; one set-based UPDATE. Rewriting every row each run would push
    non-HOT rewrites through every `jobs` index and re-mint the id behind every
    cluster link.
    """
    current = {
        r.id: (r.cluster_id, r.cluster_distance)
        for r in (
            await session.execute(
                select(Job.id, Job.cluster_id, Job.cluster_distance).where(
                    Job.cluster_id.isnot(None)
                )
            )
        ).all()
    }
    old_members: dict[int, set[int]] = {}
    for job_id, (cluster_id, _) in current.items():
        old_members.setdefault(cluster_id, set()).add(job_id)
    new_members: dict[int, set[int]] = {}
    for job_id, label in zip(ids, labels, strict=True):
        new_members.setdefault(label, set()).add(job_id)

    matched = _match_clusters(new_members, old_members)
    existing = {c.id: c for c in (await session.scalars(select(Cluster))).all()}
    model_version = _model_version(k)
    skills_of, meta = await _member_skills(session, list(ids))
    grouped: dict[int, list[set[str]]] = {}
    for job_id, label in zip(ids, labels, strict=True):
        grouped.setdefault(label, []).append(skills_of.get(job_id, set()))
    terms_of = characteristic_terms(grouped, meta)
    cluster_of: dict[int, int] = {}
    for label in range(k):
        member_idx = [i for i, lab in enumerate(labels) if lab == label]
        member_ids = [ids[i] for i in member_idx]
        member_families = [families[i] for i in member_idx if families[i]]
        family_hint = Counter(member_families).most_common(1)[0][0] if member_families else None
        top_terms = terms_of.get(label, [])
        values = {
            "model_version": model_version,
            "label": _label(top_terms, family_hint),
            "top_terms": top_terms,
            "family_hint": family_hint,
            "size": len(member_ids),
        }
        cluster = existing.get(matched[label]) if label in matched else None
        if cluster is None:
            cluster = Cluster(**values)
            session.add(cluster)
            await session.flush()  # assign id
        else:
            for column, value in values.items():
                if getattr(cluster, column) != value:
                    setattr(cluster, column, value)
        cluster_of[label] = cluster.id

    changed = [
        {"job_id": job_id, "cluster_id": cluster_of[label], "distance": distance}
        for job_id, label, distance in zip(ids, labels, distances, strict=True)
        if current.get(job_id) != (cluster_of[label], distance)
    ]
    if changed:
        await session.execute(
            text(
                "UPDATE jobs SET cluster_id = :cluster_id, cluster_distance = :distance "
                "WHERE id = :job_id"
            ),
            changed,
        )
    left = sorted(set(current) - set(ids))
    if left:
        await session.execute(
            update(Job)
            .where(Job.id.in_(left))
            .values(cluster_id=None, cluster_distance=None)
        )
    unused = set(existing) - set(cluster_of.values())
    if unused:
        await session.execute(delete(Cluster).where(Cluster.id.in_(unused)))
    logger.info(
        "clusters: %d kept, %d new, %d gone; %d jobs written, %d cleared",
        len(matched), k - len(matched), len(unused), len(changed), len(left),
    )


async def _withdraw_clusters(session: AsyncSession) -> None:
    """No clustering stands: clear the assignments that exist, delete every
    cluster. Writes nothing when there is nothing to withdraw."""
    await session.execute(
        update(Job)
        .where(Job.cluster_id.isnot(None))
        .values(cluster_id=None, cluster_distance=None)
    )
    await session.execute(delete(Cluster))
    await delete_setting(session, CLUSTERS_FITTED_KEY)


async def _corpus(session: AsyncSession, *columns):
    """The open, in-scope, embedded rows with `columns`, in id order: input
    order feeds KMeans' initialisation, so an unchanged corpus clusters the
    same way every run."""
    return (
        await session.execute(
            select(Job.id, Job.embedded_at, Job.family, *columns)
            .where(Job.status == "open", Job.in_scope.is_(True), Job.embedding.isnot(None))
            .order_by(Job.id)
        )
    ).all()


def _standing_assignment(rows) -> tuple[int, list[int], list[float]] | None:
    """The stored clustering as (k, labels, distances) in row order, or None
    when a row holds no assignment to keep."""
    if any(r.cluster_id is None or r.cluster_distance is None for r in rows):
        return None
    label_of = {cid: i for i, cid in enumerate(sorted({r.cluster_id for r in rows}))}
    return (
        len(label_of),
        [label_of[r.cluster_id] for r in rows],
        [float(r.cluster_distance) for r in rows],
    )


async def rebuild_clusters(
    session: AsyncSession, *, k: int | None = None, k_min: int = 6, k_max: int = 16
) -> int:
    """Recompute clusters over open, embedded jobs. Returns the number of clusters.

    Too few to cluster (below `k_min`) withdraws the projection: every
    assignment is cleared and every cluster deleted. Returning before touching
    anything would leave clusters and assignments describing postings that
    have since closed or left scope standing as the current answer. A corpus that recovers is clustered afresh.

    The corpus the standing clusters were fitted on is not fitted again; it is
    relabelled from its stored assignment."""
    import numpy as np

    rows = await _corpus(session, Job.cluster_id, Job.cluster_distance)
    if len(rows) >= k_min:
        fitted_on = (await get_setting_dict(session, CLUSTERS_FITTED_KEY) or {}).get("digest")
        standing_fit = (
            _standing_assignment(rows)
            if fitted_on == _corpus_digest(rows, k=k, k_min=k_min, k_max=k_max)
            else None
        )
        if standing_fit is not None:
            chosen, labels, distances = standing_fit
            logger.info("corpus unchanged since the last fit; relabelling %d clusters", chosen)
            await _write_clusters(
                session, ids=[r.id for r in rows], families=[r.family for r in rows],
                labels=labels, distances=distances, k=chosen,
            )
            return chosen
        rows = await _corpus(session, Job.embedding)
    if len(rows) < k_min:
        logger.warning("too few embedded jobs (%d) to cluster; clusters withdrawn", len(rows))
        await _withdraw_clusters(session)
        return 0

    ids = [r.id for r in rows]
    families = [r.family for r in rows]
    vectors = [r.embedding for r in rows]
    digest = _corpus_digest(rows, k=k, k_min=k_min, k_max=k_max)
    k_max = min(k_max, len(rows) - 1)
    standing = (
        await session.scalar(select(func.count()).select_from(Cluster)) if k is None else None
    )

    def _fit() -> tuple[int, list[int], list[float]]:
        X = np.asarray(vectors, dtype=float)
        if k is None:
            scores, fits = _silhouettes(X, k_min, k_max)
            chosen = stable_k(scores, standing or None)
            km = fits[chosen]
        else:
            chosen, km = k, _kmeans(X, k)
        labels = km.labels_
        distances = np.linalg.norm(X - km.cluster_centers_[labels], axis=1)
        return (
            chosen,
            [int(label) for label in labels],
            [round(float(d), DISTANCE_DECIMALS) for d in distances],
        )

    # Off the event loop: silhouette scoring is quadratic in rows and the fits
    # that choose k run one per candidate, which on a whole corpus is long
    # enough to starve the pipeline's liveness heartbeat and have the run
    # declared dead under it.
    fitted_k, labels, distances = await asyncio.to_thread(_fit)
    logger.info("clustering %d jobs into k=%d", len(ids), fitted_k)

    await _write_clusters(session, ids=ids, families=families, labels=labels, distances=distances, k=fitted_k)
    await set_setting_dict(session, CLUSTERS_FITTED_KEY, {"digest": digest})
    logger.info("built %d clusters over %d jobs", fitted_k, len(ids))
    return fitted_k


async def _run(k: int | None) -> dict:
    async with session_scope() as session:
        n = await rebuild_clusters(session, k=k)
        return {"clusters": n}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild semantic role clusters.")
    parser.add_argument("-k", type=int, default=None, help="fix k (default: silhouette-chosen)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    print(asyncio.run(_run(args.k)))


if __name__ == "__main__":
    main()
