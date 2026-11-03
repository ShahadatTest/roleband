"""Equal scores rank by a stable key, over real Postgres.

Ordered by score alone, each ranking window (lexical, fuzzy, semantic) and each
candidate cap would give rows with equal scores their rank, and their RRF
share, from PHYSICAL row order. `ts_rank_cd` takes a few dozen values over
thousands of matches, and every pipeline run rewrites every job row (the
cluster pass), so pages would reshuffle between runs with no change to any row
a search reads. A `jobs_pkey` index feed happens to be stable, so each test
pins a plan that reads rows in physical order.
"""

from __future__ import annotations

import random

import pytest
from sqlalchemy import text

from tests.factories import make_job
from tracker.config import get_settings
from tracker.db.repo import refresh_search_vectors
from tracker.search.best_match import relevance_search

pytestmark = pytest.mark.asyncio

BROWSE = {"status": "open", "hidden": []}
DESC = "You will own the roadmap for our payments platform and partner with engineering."
QUERY = "manager product"  # not an exact title: the exploratory, paged path
PHYSICAL_PLANS = {
    "seq": "SET enable_seqscan = on; SET enable_indexscan = off",
    "bitmap": "SET enable_seqscan = off; SET enable_indexscan = off",
}


def _vector() -> list[float]:
    dim = get_settings().embedding_dim
    return [0.0] * (dim - 1) + [1.0]


async def _no_vector(_text):
    return None


async def _a_vector(_text):
    return _vector()


async def _seed(session, ids, *, title="Product Manager", desc=DESC, embedded=False) -> None:
    """Identical postings, one INSERT each, so physical order is `ids` order."""
    for i in ids:
        session.add(
            make_job(
                f"k{i}", id=i, company="acme", dedupe_key=f"acme:k{i}", title=title,
                description_text=desc, url=f"https://careers.example.test/k{i}",
                embedding=_vector() if embedded else None,
            )
        )
        await session.flush()
    await refresh_search_vectors(session, list(ids))
    await session.commit()


async def _plan(session, name: str) -> None:
    for stmt in PHYSICAL_PLANS[name].split(";"):
        await session.execute(text(stmt))


async def _ranking(session, query=QUERY, *, limit=100, offset=0, embed=_no_vector):
    result = await relevance_search(session, BROWSE, query, limit, offset, embed=embed)
    return result, [row.job.id for row in result.rows]


async def _rewrite_without_changing_a_score(session, ids) -> None:
    """What the cluster pass does to every row each run: an UPDATE of an
    indexed column search never reads, so each row gets a new physical slot."""
    await session.execute(
        text("UPDATE jobs SET lineage_role = 'original' WHERE id = ANY(:ids)"), {"ids": list(ids)}
    )
    await session.commit()


@pytest.mark.parametrize("plan", list(PHYSICAL_PLANS))
@pytest.mark.parametrize("embed", [_no_vector, _a_vector], ids=["vector_off", "vector_on"])
async def test_a_rewrite_that_changes_no_score_moves_no_row(db_session, plan, embed):
    """Broken rule caught: ties rank by physical order, so rewriting page 1's
    rows (no score changes) pushes them onto later pages and pulls others up."""
    await _seed(db_session, range(1, 46), embedded=embed is _a_vector)
    await _plan(db_session, plan)
    _, before = await _ranking(db_session, embed=embed)
    page_one = before[:20]

    await _rewrite_without_changing_a_score(db_session, page_one[:10])
    await _plan(db_session, plan)
    _, after = await _ranking(db_session, embed=embed)
    assert after == before

    # And offset paging over the unchanged corpus neither repeats nor drops a row.
    pages = []
    for offset in (0, 20, 40):
        pages += (await _ranking(db_session, limit=20, offset=offset, embed=embed))[1]
    assert sorted(pages) == list(range(1, 46))
    assert len(pages) == len(set(pages))


async def test_equal_scores_rank_newest_id_first_whatever_the_insert_order(db_session):
    """Broken rule caught: the same rows inserted in another order rank in
    another order. The tiebreak is the id, newest first, as every sort."""
    order = list(range(1, 31))
    random.Random(37).shuffle(order)
    await _seed(db_session, order)
    await _plan(db_session, "seq")
    _, ranking = await _ranking(db_session)
    assert ranking == list(range(30, 0, -1))


async def test_a_capped_source_admits_the_same_tied_rows_every_time(db_session, monkeypatch):
    """Broken rule caught: a source's LIMIT had no ORDER BY of its own, so when
    the cap binds, WHICH tied rows are admitted followed physical order."""
    settings = get_settings()
    monkeypatch.setattr(settings, "search_candidate_pool", 10)
    monkeypatch.setattr(settings, "search_candidate_pool_max", 10)
    # A lexical-only match: the word is in the body, nowhere near the title.
    await _seed(
        db_session, range(1, 31), title="Director of Widgets",
        desc="Our zebra platform team ships quarterly.",
    )
    await _plan(db_session, "seq")
    result, before = await _ranking(db_session, "zebra")
    assert result.matched == 30 and result.ranking_truncated
    assert sorted(before) == list(range(21, 31))  # the ten newest of the tie

    await _rewrite_without_changing_a_score(db_session, before)
    await _plan(db_session, "seq")
    _, after = await _ranking(db_session, "zebra")
    assert after == before
