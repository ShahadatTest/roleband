"""A full-width or styled-Unicode query finds what its plain form finds.

`exact_title_key` folds with NFKC. A trigram prefilter, lexical or fuzzy source
that received the query as typed would score "ｓｅｎｉｏｒ ｐｒｏｄｕｃｔ
ｍａｎａｇｅｒ" 0.000 against "Senior Product Manager", miss the exact title and
return NOTHING. The query is folded once where it
enters (Best match, the Board's lexical filter, the agent's phrase). Real
Postgres, the real search path.
"""

from __future__ import annotations

import pytest

from tests.factories import make_job
from tracker.db.repo import refresh_search_vectors
from tracker.search.best_match import relevance_search

pytestmark = pytest.mark.asyncio

BROWSE = {"status": "open", "hidden": []}


async def _no_vector(_text):
    return None


async def _seed(db_session):
    job = make_job("x1", company="acme", dedupe_key="acme:x1", title="Senior Product Manager",
               description_text="Own the roadmap for payments.")
    decoy = make_job("x2", company="beta", dedupe_key="beta:x2", title="Staff Data Scientist",
                 description_text="Models and experiments.")
    db_session.add_all([job, decoy])
    await db_session.flush()
    await refresh_search_vectors(db_session, [job.id, decoy.id])
    await db_session.commit()
    return job


@pytest.mark.parametrize(
    "query",
    [
        "ｓｅｎｉｏｒ ｐｒｏｄｕｃｔ ｍａｎａｇｅｒ",
        "ＳＥＮＩＯＲ ＰＲＯＤＵＣＴ ＭＡＮＡＧＥＲ",
        "𝐒𝐞𝐧𝐢𝐨𝐫 𝐏𝐫𝐨𝐝𝐮𝐜𝐭 𝐌𝐚𝐧𝐚𝐠𝐞𝐫",
        "𝗦𝗲𝗻𝗶𝗼𝗿 𝗣𝗿𝗼𝗱𝘂𝗰𝘁 𝗠𝗮𝗻𝗮𝗴𝗲𝗿",
    ],
    ids=["fullwidth", "fullwidth_upper", "math_bold", "math_sans_bold"],
)
async def test_a_compatibility_form_finds_the_exact_title(db_session, query):
    job = await _seed(db_session)
    result = await relevance_search(db_session, BROWSE, query, 20, 0, embed=_no_vector)
    assert result.query_kind == "exact_title"
    assert [r.job.id for r in result.rows] == [job.id]


@pytest.mark.parametrize(
    "query", ["Senior PM", "Staff Product Manager"], ids=["abbreviation", "other_level"]
)
async def test_folding_never_makes_a_different_title_exact(db_session, query):
    job = await _seed(db_session)
    result = await relevance_search(db_session, BROWSE, query, 20, 0, embed=_no_vector)
    assert result.query_kind != "exact_title"
    assert job.id not in [r.job.id for r in result.rows if r.match_class == "exact"]


async def test_the_boards_search_filter_folds_the_query(api_client, db_session):
    job = await _seed(db_session)
    body = (
        await api_client.get("/api/jobs", params={"q": "ｐａｙｍｅｎｔｓ", "limit": 20})
    ).json()
    assert [item["id"] for item in body["items"]] == [job.id]
