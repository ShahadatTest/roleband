"""The google URL backfill: listing state off stored Google URLs, nothing else.

Real commits on the scratch database, so the per-batch contract is
measured, not mocked: a run that dies keeps the batches it saved and a rerun
finishes the rest by itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from scripts import backfill_google_urls
from tracker.db.models import Job, PostingInventory
from tracker.search.policy import identity_url_key

pytestmark = pytest.mark.asyncio
T0 = datetime(2026, 10, 9, tzinfo=UTC)
BASE = "https://www.google.com/about/careers/applications/jobs/results/"
SHARED = BASE + "133375036143608518-technical-program-manager"
STORED = SHARED + "?page=81&sort_by=date&location=United+States"
# Greenhouse names the posting in its query: not ours to strip.
GREENHOUSE = "https://boards.greenhouse.io/acme/jobs/4?gh_jid=111"


class Killed(RuntimeError):
    pass


def _job(n: int, url: str, company: str = "google") -> Job:
    return Job(
        company=company, req_id=f"r{n}", dedupe_key=f"{company}:r{n}", title="Technical Program Manager",
        url=url, status="closed", in_scope=True, level_band="senior", level_confidence="confirmed",
        level_basis="stated", family="program_management", track="technical", locations=["United States"],
        location_groups=["us"], domains=[], comp_currency="USD", first_seen=T0, last_seen=T0,
    )


def _posting(n: int, url: str) -> PostingInventory:
    return PostingInventory(
        dedupe_key=f"google:r{n}", company="google", req_id=f"r{n}", title="Technical Program Manager",
        url=url, level_band="senior", level_confidence="confirmed", level_basis="stated",
        family="program_management", track="technical", content_hash=f"hash-{n}",
        first_seen_at=T0, last_seen_at=T0,
    )


@pytest_asyncio.fixture
async def scoped(db_session, scratch_scope):
    """Every `session_scope` the code under test opens lands on the scratch DB."""
    return db_session


async def _urls(db_session, model) -> list[str]:
    db_session.expire_all()
    return list((await db_session.scalars(select(model.url).order_by(model.id))).all())


async def test_dry_run_counts_and_writes_nothing(scoped):
    scoped.add_all([_job(1, STORED), _job(2, SHARED), _posting(1, STORED)])
    await scoped.commit()

    stats = await backfill_google_urls.backfill(apply=False)

    assert stats == {"jobs_pending": 1, "posting_inventory_pending": 1}
    assert await _urls(scoped, Job) == [STORED, SHARED]
    assert await _urls(scoped, PostingInventory) == [STORED]


async def test_apply_strips_only_google_listing_state(scoped):
    scoped.add_all([
        _job(1, STORED),
        _job(2, STORED.replace("page=81", "page=3"), company="google-deepmind"),
        _job(3, SHARED),
        _job(4, GREENHOUSE, company="acme"),
        _posting(1, STORED),
    ])
    await scoped.commit()

    stats = await backfill_google_urls.backfill(apply=True)

    assert stats["jobs_rewritten"] == 2
    assert stats["posting_inventory_rewritten"] == 1
    assert await _urls(scoped, Job) == [SHARED, SHARED, SHARED, GREENHOUSE]
    assert await _urls(scoped, PostingInventory) == [SHARED]
    # The hash is left for the next scan to rewrite, not recomputed here.
    assert (await scoped.scalars(select(PostingInventory.content_hash))).one() == "hash-1"
    # The point of the repair: the link a user shares now names the stored row.
    assert identity_url_key(SHARED) == identity_url_key((await _urls(scoped, Job))[0])
    # Nothing is left, so a second apply is a no-op.
    assert await backfill_google_urls.backfill(apply=True) == {
        "jobs_pending": 0, "posting_inventory_pending": 0,
        "jobs_rewritten": 0, "posting_inventory_rewritten": 0,
    }


async def test_a_killed_apply_keeps_saved_batches_and_a_rerun_finishes(scoped, monkeypatch):
    scoped.add_all([_job(n, STORED) for n in range(1, 6)])
    await scoped.commit()
    real = backfill_google_urls.without_query
    calls = 0

    def dies_in_second_batch(url: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise Killed
        return real(url)

    monkeypatch.setattr(backfill_google_urls, "without_query", dies_in_second_batch)
    with pytest.raises(Killed):
        await backfill_google_urls.backfill(apply=True, batch=2)
    urls = await _urls(scoped, Job)
    assert urls[:2] == [SHARED, SHARED]
    assert all("?" in url for url in urls[2:])

    monkeypatch.setattr(backfill_google_urls, "without_query", real)
    stats = await backfill_google_urls.backfill(apply=True, batch=2)
    assert stats["jobs_pending"] == 3
    assert stats["jobs_rewritten"] == 3
    assert await _urls(scoped, Job) == [SHARED] * 5
