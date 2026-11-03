"""A list read leaves each posting's description and search artifacts in the database.

A list row is serialized without its description (`serialize_job` reads it only
for `detail=True`), so the Board under any sort, Best fit, the intent ranking,
Saved, Compare, every search kind and Similar postings fetch none of `HEAVY`. They are most of a
row's bytes, and pgvector parses every fetched embedding into an array.

The probe is what each statement RETURNED (`cursor.description`), not its SQL
text: the intent ranking orders by the embedding inside the query without
returning it. Job detail is the control: it serializes the description, so the
same probe must see those columns fetched there.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import pytest_asyncio
from sqlalchemy import event

from tests.facets_contract_seed import seed_board
from tests.job_contract_seed import seed_job_contract
from tracker.api.routers import jobs as jobs_router
from tracker.config import get_settings

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

HEAVY = frozenset(
    {"description_html", "description_sections", "description_text", "embedding", "search_vector"}
)
#: A result column carrying one of `HEAVY`, under any label SQLAlchemy gives it
#: (`jobs_embedding`, `embedding_1`).
_HEAVY_LABEL = re.compile(rf"(?:\w+_)?({'|'.join(sorted(HEAVY))})(?:_\d+)?")


@contextmanager
def _returned_heavy(engine) -> Iterator[set[str]]:
    """The `HEAVY` columns any statement returned while the block ran."""
    seen: set[str] = set()

    def record(_conn, cursor, _statement, _parameters, _context, _executemany):
        for column in cursor.description or ():
            if match := _HEAVY_LABEL.fullmatch(column[0]):
                seen.add(match.group(1))

    event.listen(engine.sync_engine, "after_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", record)


async def _read(api_client, engine, path: str) -> tuple[set[str], dict]:
    with _returned_heavy(engine) as heavy:
        response = await api_client.get(path)
    assert response.status_code == 200, response.text
    return heavy, response.json()


@pytest_asyncio.fixture
async def seeded(db_session, monkeypatch):
    async def no_query_vector(_text):
        return None  # no model weights in tests: the lexical half ranks alone

    monkeypatch.setattr(jobs_router, "embed_query", no_query_vector)
    return await seed_job_contract(db_session)


LISTS = {
    "board": "/api/jobs",
    "board_by_age": "/api/jobs?sort=days_open&order=asc",
    "saved": "/api/jobs?favorites_only=true",
    "search_exploratory": "/api/jobs?sort=relevance&q=product%20manager",
    "search_exact_title_with_related": (
        "/api/jobs?sort=relevance&q=Platform%20Strategy%20Lead%2C%20Cloud&include_related=true"
    ),
    "search_identifier": "/api/jobs?sort=relevance&q=https%3A%2F%2Fcareers.example.test%2Fband",
}


@pytest.mark.parametrize("shape", sorted(LISTS))
async def test_a_list_read_fetches_no_description_or_search_artifact(
    api_client, db_session, seeded, shape
):
    heavy, body = await _read(api_client, db_session.bind, LISTS[shape])

    assert body["items"], f"{shape} listed nothing, so nothing was measured"
    assert heavy == set()


async def test_compare_reads_its_rows_without_their_descriptions(api_client, db_session, seeded):
    heavy, body = await _read(
        api_client, db_session.bind, f"/api/jobs?ids={seeded.band}&ids={seeded.plain}&status="
    )

    assert {item["id"] for item in body["items"]} == {seeded.band, seeded.plain}
    assert heavy == set()


def _intent(monkeypatch, vector: list[float] | None) -> None:
    """Stand in for the intent build, whose own read of the Saved rows'
    embeddings is the input to a ranking, not a list read."""

    async def no_statement(_session):
        return None

    async def intent_vector(_session, _stored):
        return vector

    monkeypatch.setattr(jobs_router, "get_intent_embedding", no_statement)
    monkeypatch.setattr(jobs_router, "build_intent_vector", intent_vector)


async def test_the_intent_ranking_orders_by_the_embedding_without_fetching_it(
    api_client, db_session, seeded, monkeypatch
):
    _intent(monkeypatch, [0.01] * get_settings().embedding_dim)

    heavy, body = await _read(api_client, db_session.bind, "/api/jobs?sort=relevance")

    assert body["ranked_by"] == "intent" and body["items"]
    assert heavy == set()


async def test_best_fit_without_an_intent_signal_fetches_none_either(
    api_client, db_session, seeded, monkeypatch
):
    _intent(monkeypatch, None)

    heavy, body = await _read(api_client, db_session.bind, "/api/jobs?sort=relevance")

    assert "ranked_by" not in body and "placed_total" in body and body["items"]
    assert heavy == set()


async def test_similar_postings_list_their_rows_without_descriptions(api_client, db_session):
    board = await seed_board(db_session)

    heavy, body = await _read(api_client, db_session.bind, f"/api/jobs/{board.jobs['cloud']}/similar")

    assert body["items"], "the seed's neighbours must be listed, or nothing was measured"
    assert heavy == set()


async def test_job_detail_fetches_the_description_the_list_leaves_behind(
    api_client, db_session, seeded
):
    """The control: the probe sees a description when one is read."""
    heavy, body = await _read(api_client, db_session.bind, f"/api/jobs/{seeded.band}")

    assert body["description_text"] == "Lead the platform."
    assert body["description_sections"]
    assert {"description_html", "description_sections", "description_text"} <= heavy
