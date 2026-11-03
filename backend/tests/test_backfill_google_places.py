"""The google place backfill: a searched country the listed places already
name leaves the place list, and nothing else moves.

Real commits on the scratch database, so the per-batch contract is
measured, not mocked: a run that dies keeps the batches it saved and a rerun
finishes the rest by itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from scripts import backfill_google_places
from tracker.db.models import Job, PostingInventory
from tracker.enrich.classify import location_slugs_for

pytestmark = pytest.mark.asyncio
T0 = datetime(2026, 10, 9, tzinfo=UTC)
BASE = "https://www.google.com/about/careers/applications/jobs/results/"
SUNNYVALE = ["Sunnyvale, CA, USA", "United States"]
# The card hid its UK office behind "+1 more": the country is the only trace.
HIDDEN_UK = ["Hamburg, Germany", "Zürich, Switzerland", "United Kingdom"]


class Killed(RuntimeError):
    pass


def _job(n: int, locations: list[str], *, company: str = "google", url: str | None = None) -> Job:
    return Job(
        company=company, req_id=f"r{n}", dedupe_key=f"{company}:r{n}", title="Technical Lead",
        url=url or f"{BASE}{n}-technical-lead", status="closed", in_scope=True, level_band="senior",
        level_confidence="confirmed", level_basis="stated", family="software_engineering",
        track="technical", locations=locations, location_groups=location_slugs_for(locations),
        domains=[], comp_currency="USD", first_seen=T0, last_seen=T0,
    )


def _posting(n: int, locations: list[str]) -> PostingInventory:
    return PostingInventory(
        dedupe_key=f"google:r{n}", company="google", req_id=f"r{n}", title="Technical Lead",
        url=f"{BASE}{n}-technical-lead", level_band="senior", level_confidence="confirmed",
        level_basis="stated", family="software_engineering", track="technical",
        locations=locations, location_groups=location_slugs_for(locations),
        content_hash=f"hash-{n}", first_seen_at=T0, last_seen_at=T0,
    )


@pytest_asyncio.fixture
async def scoped(db_session, scratch_scope):
    """Every `session_scope` the code under test opens lands on the scratch DB."""
    return db_session


async def _places(db_session, model) -> list[list[str]]:
    db_session.expire_all()
    return [list(p) for p in (await db_session.scalars(select(model.locations).order_by(model.id))).all()]


async def test_dry_run_counts_and_writes_nothing(scoped):
    scoped.add_all([_job(1, SUNNYVALE), _job(2, HIDDEN_UK), _posting(1, SUNNYVALE)])
    await scoped.commit()

    stats = await backfill_google_places.backfill(apply=False)

    assert stats == {"jobs_pending": 1, "posting_inventory_pending": 1}
    assert await _places(scoped, Job) == [SUNNYVALE, HIDDEN_UK]
    assert await _places(scoped, PostingInventory) == [SUNNYVALE]


async def test_apply_drops_only_a_country_the_listed_places_already_name(scoped):
    other_board = ["Sunnyvale, CA", "United States"]
    scoped.add_all([
        _job(1, SUNNYVALE),
        _job(2, ["Mountain View, CA, USA", "New York, NY, USA", "United States"], company="google-deepmind"),
        _job(3, HIDDEN_UK),
        # A card with no place of its own keeps the country it was found under.
        _job(4, ["United States"]),
        # Another board's rows are not the adapter's to repair.
        _job(5, other_board, company="acme", url="https://jobs.example.com/5"),
        _posting(1, SUNNYVALE),
    ])
    await scoped.commit()
    groups_before = (await scoped.scalars(select(Job.location_groups).order_by(Job.id))).all()

    stats = await backfill_google_places.backfill(apply=True)

    assert stats["jobs_rewritten"] == 2
    assert stats["posting_inventory_rewritten"] == 1
    assert await _places(scoped, Job) == [
        ["Sunnyvale, CA, USA"],
        ["Mountain View, CA, USA", "New York, NY, USA"],
        HIDDEN_UK,
        ["United States"],
        other_board,
    ]
    assert await _places(scoped, PostingInventory) == [["Sunnyvale, CA, USA"]]
    # Only the place list moves: the stored tags still match it, and the
    # inventory hash is left for the next scan to rewrite.
    groups_after = (await scoped.scalars(select(Job.location_groups).order_by(Job.id))).all()
    assert groups_after == groups_before
    assert [location_slugs_for(p) for p in await _places(scoped, Job)] == [list(g) for g in groups_after]
    assert (await scoped.scalars(select(PostingInventory.content_hash))).one() == "hash-1"
    # Nothing is left, so a second apply is a no-op.
    assert await backfill_google_places.backfill(apply=True) == {
        "jobs_pending": 0, "posting_inventory_pending": 0,
        "jobs_rewritten": 0, "posting_inventory_rewritten": 0,
    }


async def test_a_killed_apply_keeps_saved_batches_and_a_rerun_finishes(scoped, monkeypatch):
    scoped.add_all([_job(n, SUNNYVALE) for n in range(1, 6)])
    await scoped.commit()
    real = backfill_google_places.without_search_term
    calls = 0

    def dies_in_second_batch(places: list[str]) -> list[str] | None:
        nonlocal calls
        calls += 1
        # Five selection reads, then the writes: the eighth is the second batch's first.
        if calls == 8:
            raise Killed
        return real(places)

    monkeypatch.setattr(backfill_google_places, "without_search_term", dies_in_second_batch)
    with pytest.raises(Killed):
        await backfill_google_places.backfill(apply=True, batch=2)
    places = await _places(scoped, Job)
    assert places[:2] == [["Sunnyvale, CA, USA"]] * 2
    assert places[2:] == [SUNNYVALE] * 3

    monkeypatch.setattr(backfill_google_places, "without_search_term", real)
    stats = await backfill_google_places.backfill(apply=True, batch=2)
    assert stats["jobs_pending"] == 3
    assert stats["jobs_rewritten"] == 3
    assert await _places(scoped, Job) == [["Sunnyvale, CA, USA"]] * 5
