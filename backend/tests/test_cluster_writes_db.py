"""The cluster pass writes only what changed, and a cluster keeps its id.

`rebuild_clusters` runs on every non-discovery run, and `cluster_id` is
indexed. A pass that nulls `cluster_id` on EVERY job row, deletes every
cluster and re-creates them with new ids would rewrite every member row non-HOT
through every `jobs` index, re-mint every `/api/clusters/{id}` link, and
reshuffle the physical row order search ties fall back to. Real Postgres; a
row's `xmin` (the transaction that last wrote it) tells whether it was
rewritten.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from tracker.config import get_settings
from tracker.db.models import Cluster, Job
from tracker.semantic.cluster import rebuild_clusters

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 4, tzinfo=UTC)


def _vector(axis: int, wobble: float) -> list[float]:
    dim = get_settings().embedding_dim
    vec = [0.0] * dim
    vec[axis] = 1.0
    vec[(axis + 7) % dim] = wobble
    return vec


async def _seed(db_session, n_per: int = 8) -> list[Job]:
    jobs = []
    for group, axis in enumerate((0, 100, 200)):
        for i in range(n_per):
            n = group * 100 + i
            jobs.append(
                Job(
                    company="acme", req_id=f"r{n}", dedupe_key=f"acme:{n}", title=f"Role {n}",
                    url=f"https://careers.example.test/{n}", level_band="staff", status="open",
                    in_scope=True, first_seen=NOW, last_seen=NOW,
                    embedding=_vector(axis, 0.01 * i),
                )
            )
    db_session.add_all(jobs)
    await db_session.commit()
    return jobs


async def _xmins(db_session) -> dict[int, str]:
    rows = (await db_session.execute(text("SELECT id, xmin::text FROM jobs"))).all()
    return {r.id: r.xmin for r in rows}


async def _assignments(db_session) -> dict[int, int | None]:
    rows = (await db_session.execute(select(Job.id, Job.cluster_id))).all()
    return {r.id: r.cluster_id for r in rows}


async def test_a_rerun_on_an_unchanged_corpus_writes_no_job_row(db_session):
    await _seed(db_session)
    assert await rebuild_clusters(db_session, k=3) == 3
    await db_session.commit()
    before = await _xmins(db_session)
    clusters = sorted((await db_session.scalars(select(Cluster.id))).all())

    await rebuild_clusters(db_session, k=3)
    await db_session.commit()

    assert await _xmins(db_session) == before
    assert sorted((await db_session.scalars(select(Cluster.id))).all()) == clusters


async def test_a_job_that_leaves_writes_no_row_of_another_cluster(db_session):
    jobs = await _seed(db_session)
    await rebuild_clusters(db_session, k=3)
    await db_session.commit()
    first = await _assignments(db_session)

    gone = jobs[0]
    gone.status = "closed"
    await db_session.commit()
    before = await _xmins(db_session)
    await rebuild_clusters(db_session, k=3)
    await db_session.commit()

    after = await _xmins(db_session)
    rewritten = {job_id for job_id in after if after[job_id] != before[job_id]}
    # The leaver, and at most its cluster-mates (their centroid moved, so a
    # stored distance may too); never a row of another cluster.
    mates = {job_id for job_id, cluster in first.items() if cluster == first[gone.id]}
    assert gone.id in rewritten and rewritten <= mates
    assignments = await _assignments(db_session)
    assert assignments[gone.id] is None
    # Everyone else keeps the cluster (and id) they had.
    assert {k: v for k, v in assignments.items() if k != gone.id} == {
        k: v for k, v in first.items() if k != gone.id
    }


async def test_the_first_build_assigns_every_open_embedded_job(db_session):
    jobs = await _seed(db_session)
    await rebuild_clusters(db_session, k=3)
    await db_session.commit()
    assignments = await _assignments(db_session)
    assert all(assignments[job.id] is not None for job in jobs)
    assert len(set(assignments.values())) == 3


# --------------------------------------------------------------------------- #
# Too little input withdraws the projection
# --------------------------------------------------------------------------- #


async def _routes_agree(api_client, db_session) -> list[tuple[int, int]]:
    """Each listed cluster's size, checked against its detail and its members."""
    listed = (await api_client.get("/api/clusters")).json()["items"]
    sizes = []
    for item in listed:
        detail = (await api_client.get(f"/api/clusters/{item['id']}")).json()
        assert item["size"] == detail["size"] == len(detail["items"]) > 0
        sizes.append((item["id"], item["size"]))
    return sorted(sizes)


async def test_too_little_input_withdraws_every_cluster_and_assignment(db_session, api_client):
    """Below `k_min` the pass must not return before touching anything: the
    clusters, their sizes and every job's assignment would stay, describing
    postings that have since closed or left scope."""
    jobs = await _seed(db_session)
    assert await rebuild_clusters(db_session, k=3) == 3
    await db_session.commit()
    assert [size for _id, size in await _routes_agree(api_client, db_session)] == [8, 8, 8]

    for job in jobs[4:]:  # four left: below k_min (6)
        job.in_scope = False
    await db_session.commit()
    assert await rebuild_clusters(db_session, k=3) == 0
    await db_session.commit()
    assert (await db_session.scalars(select(Cluster.id))).all() == []
    assert set((await _assignments(db_session)).values()) == {None}
    assert await _routes_agree(api_client, db_session) == []

    for job in jobs[:4]:  # none left
        job.in_scope = False
    await db_session.commit()
    assert await rebuild_clusters(db_session, k=3) == 0
    await db_session.commit()
    assert await _routes_agree(api_client, db_session) == []

    for job in jobs:  # recovered
        job.in_scope = True
    await db_session.commit()
    assert await rebuild_clusters(db_session, k=3) == 3
    await db_session.commit()
    assert [size for _id, size in await _routes_agree(api_client, db_session)] == [8, 8, 8]
    assert None not in set((await _assignments(db_session)).values())


async def test_a_cluster_shows_its_current_members_between_rebuilds(db_session, api_client):
    """A posting that leaves scope after the pass (a scope save) is not a
    member the routes show, so the size they state must not count it either."""
    jobs = await _seed(db_session)
    await rebuild_clusters(db_session, k=3)
    await db_session.commit()
    jobs[0].in_scope = False
    await db_session.commit()
    assert sorted(size for _id, size in await _routes_agree(api_client, db_session)) == [7, 8, 8]


async def test_the_fit_runs_off_the_event_loop(db_session, monkeypatch):
    """The pipeline's liveness heartbeat is a task on the loop this pass runs
    on, and a run that stops beating is reconciled away. Silhouette scoring is
    quadratic in rows and runs one fit per candidate k, so on a whole corpus it
    is long enough to do that. Fail-first: fit inline and the ticker below
    never advances.
    """
    import asyncio
    import time

    from tracker.semantic import cluster as cluster_mod

    await _seed(db_session)

    real_silhouettes = cluster_mod._silhouettes

    def slow_silhouettes(X, k_min, k_max):
        time.sleep(0.2)  # blocking on purpose: sklearn does not await
        _scores, fits = real_silhouettes(X, k_min, k_max)
        return {k: 1.0 / k for k in range(k_min, k_max + 1)}, fits

    monkeypatch.setattr(cluster_mod, "_silhouettes", slow_silhouettes)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        k = await rebuild_clusters(db_session)  # no k: the choice runs too
    finally:
        task.cancel()

    assert k == 6, "stable_k takes the best-scoring candidate"
    assert ticks >= 5, "the event loop was blocked while the clusters were fit"


# --------------------------------------------------------------------------- #
# An unchanged corpus is not fitted again
# --------------------------------------------------------------------------- #


def _count_fits(monkeypatch) -> list[int]:
    """Record the k of every KMeans fit the pass makes."""
    from tracker.semantic import cluster as cluster_mod

    fitted: list[int] = []
    real = cluster_mod._kmeans

    def counting(X, k):
        fitted.append(k)
        return real(X, k)

    monkeypatch.setattr(cluster_mod, "_kmeans", counting)
    return fitted


async def test_choosing_k_fits_each_candidate_once_and_keeps_the_chosen_fit(db_session, monkeypatch):
    await _seed(db_session)
    fitted = _count_fits(monkeypatch)

    k = await rebuild_clusters(db_session)

    assert sorted(fitted) == list(range(6, 17)), "one fit per candidate, none again for the chosen k"
    assert k in fitted


async def test_an_unchanged_corpus_is_relabelled_without_a_fit(db_session, monkeypatch):
    jobs = await _seed(db_session)
    k = await rebuild_clusters(db_session)
    await db_session.commit()
    first = await _assignments(db_session)
    before = await _xmins(db_session)
    fitted = _count_fits(monkeypatch)

    for job in jobs:  # a family moves without a vector moving
        job.family = "software_engineering"
    await db_session.commit()
    families_written = await _xmins(db_session)
    assert await rebuild_clusters(db_session) == k
    await db_session.commit()

    assert fitted == []
    assert await _assignments(db_session) == first
    assert await _xmins(db_session) == families_written != before, "no job row written by the pass"
    hints = set((await db_session.scalars(select(Cluster.family_hint))).all())
    assert hints == {"software_engineering"}, "the labels follow what moved"


async def test_a_reembedded_row_is_fitted_again(db_session, monkeypatch):
    """The control for the skip above: it holds only while every vector does."""
    jobs = await _seed(db_session)
    await rebuild_clusters(db_session)
    await db_session.commit()
    fitted = _count_fits(monkeypatch)

    jobs[0].embedding = _vector(300, 0.5)
    jobs[0].embedded_at = NOW
    await db_session.commit()
    await rebuild_clusters(db_session)

    assert fitted, "a new vector was clustered from the stored assignment"


async def test_a_corpus_fitted_at_a_pinned_k_is_fitted_again_when_k_is_chosen(db_session, monkeypatch):
    await _seed(db_session)
    assert await rebuild_clusters(db_session, k=3) == 3
    await db_session.commit()
    fitted = _count_fits(monkeypatch)

    await rebuild_clusters(db_session)

    assert sorted(fitted) == list(range(6, 17))


async def test_the_clusters_name_the_embedding_model_they_were_fitted_on(db_session):
    await _seed(db_session)
    await rebuild_clusters(db_session, k=3)
    model = get_settings().embedding_model.rsplit("/", 1)[-1].lower()
    assert set((await db_session.scalars(select(Cluster.model_version))).all()) == {f"kmeans-k3-{model}"}
