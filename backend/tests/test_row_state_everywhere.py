"""A posting's reader state is the same on every surface that lists it.

Saved, Not for me, and how many twins a posting has are read for every job row
an answer carries, not only the Board's: a row that says "not saved" must have
been looked at. The lineage contract seed has a stack, twins and pairs in the
review queues; one posting is saved and one marked not for me, and each
surface that shows them must say so.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio

from tests.lineage_contract_seed import NOW, pin_lineage_environment, seed_lineage_contract
from tracker.db.models import Favorite, JobFeedback

pytestmark = pytest.mark.asyncio


def _rows(body: object) -> list[dict]:
    """Every job row anywhere in an answer."""
    found: list[dict] = []
    if isinstance(body, dict):
        if "is_favorite" in body and "id" in body:
            found.append(body)
        for value in body.values():
            found.extend(_rows(value))
    elif isinstance(body, list):
        for value in body:
            found.extend(_rows(value))
    return found


@pytest_asyncio.fixture
async def marked(api_client, db_session, monkeypatch):
    seeded = await seed_lineage_contract(db_session)
    pin_lineage_environment(monkeypatch)
    db_session.add(Favorite(job_id=seeded.repost, created_at=NOW - timedelta(days=1)))
    db_session.add(JobFeedback(job_id=seeded.twin_left, verdict="dismissed", reason="wrong_domain",
                               created_at=NOW - timedelta(days=1)))
    await db_session.commit()
    return seeded


async def _get(api_client, path: str) -> object:
    response = await api_client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("path", [
    "/api/jobs/{original}/lineage",
    "/api/lineage/review?status=reviewed&confidence=",
    "/api/lineage/review?status=reviewed&confidence=&detail=false",
    "/api/demand",
])
async def test_a_saved_posting_reads_as_saved_wherever_it_is_listed(api_client, marked, path):
    rows = _rows(await _get(api_client, path.format(original=marked.original)))
    saved = [row for row in rows if row["id"] == marked.repost]
    assert saved, f"the saved posting is not in {path}, so nothing was measured"
    assert all(row["is_favorite"] for row in saved)
    assert not any(row["is_favorite"] for row in rows if row["id"] != marked.repost)


@pytest.mark.parametrize("path", [
    "/api/jobs/{twin_left}/twins",
    "/api/twins/review?status=reviewed&confidence=",
])
async def test_a_posting_marked_not_for_me_reads_so_and_counts_its_twins(api_client, marked, path):
    rows = _rows(await _get(api_client, path.format(twin_left=marked.twin_left)))
    dismissed = [row for row in rows if row["id"] == marked.twin_left]
    assert dismissed, f"the dismissed posting is not in {path}, so nothing was measured"
    assert all(row["is_dismissed"] for row in dismissed)
    assert all(row["twin_count"] >= 1 for row in dismissed)
