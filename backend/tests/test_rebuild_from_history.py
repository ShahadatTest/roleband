"""Cleaning what plugin data reached in our derived data, from our own history.

`scripts.rebuild_from_history`: a dry run writes nothing; `--write` rebuilds a
day's `roleband` pay series from what OUR providers answered that night (never
the plugin's answer beside it), leaves the `mixed` day unread and untouched,
and skips a day already rebuilt; and it resolves each profile from our sources
only, so a value only an outside source stated clears and the equity inference
does not read it. Nothing is deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from scripts import rebuild_from_history as script
from tracker.db.models import (
    CompanyFact,
    CompanyProfile,
    CompSnapshot,
    Job,
    JobObservation,
    ScrapeRun,
)
from tracker.profiles.store import record_fact, resolve_and_materialize

pytestmark = pytest.mark.asyncio

DAY = datetime(2026, 9, 20, tzinfo=UTC)
LEGACY = "acme.legacy"


@pytest_asyncio.fixture
async def scoped(db_session, scratch_scope):
    """Every `session_scope` the script opens lands on the scratch DB."""
    return db_session


async def _history(db) -> None:
    run = ScrapeRun(started_at=DAY, status="ok")
    db.add(run)
    db.add_all([
        Job(company="google", req_id="1", dedupe_key="google:1", title="Senior Software Engineer",
            url="https://example.com/1", level_band="senior", family="software_engineering", status="open",
            first_seen=DAY - timedelta(days=3), last_seen=DAY, in_scope=True),
        Job(company="google", req_id="2", dedupe_key="google:2", title="Staff Software Engineer",
            url="https://example.com/2", level_band="staff", family="software_engineering", status="closed",
            first_seen=DAY - timedelta(days=9), closed_at=DAY - timedelta(days=2), last_seen=DAY, in_scope=True),
    ])
    await db.flush()
    open_job, closed_job = (await db.scalars(select(Job).order_by(Job.req_id))).all()

    def observed(job: Job, at: datetime, sources: list[dict]) -> JobObservation:
        return JobObservation(job_id=job.id, run_id=run.id, observed_at=at, title=job.title, level_band=job.level_band,
                              family=job.family, locations=[], comp_median=sources[0]["median"] if sources else None,
                              payload={"level_band": job.level_band, "level_basis": "title",
                                       "family": job.family, "comp_sources": sources})

    db.add_all([
        # That night the plugin answered first; ours answered beside it.
        observed(open_job, DAY + timedelta(hours=6), [
            {"provider": "reference_table", "median": 999_000}, {"provider": "static", "median": 300_000}]),
        # A later observation is not that day's.
        observed(open_job, DAY + timedelta(days=2), [{"provider": "static", "median": 333_000}]),
        # Closed before the day: not counted.
        observed(closed_job, DAY - timedelta(days=4), [{"provider": "static", "median": 500_000}]),
        CompSnapshot(metric_date=DAY, company="google", level_band="senior", family="software_engineering",
                     comp_values=[999_000], source="mixed"),
    ])
    await db.commit()


async def _series(db) -> list[tuple]:
    db.expire_all()
    rows = (await db.execute(select(CompSnapshot.source, CompSnapshot.level_band, CompSnapshot.comp_values)
                             .order_by(CompSnapshot.source))).all()
    return [(source, level, list(values)) for source, level, values in rows]


async def test_a_day_is_rebuilt_from_our_answers_that_night_and_the_mixed_day_stays(scoped, capsys):
    await _history(scoped)
    assert await script._snapshots(write=False) == 0
    assert await _series(scoped) == [("mixed", "senior", [999_000])], "a dry run writes nothing"

    await script._snapshots(write=True)
    assert await _series(scoped) == [("mixed", "senior", [999_000]), ("roleband", "senior", [300_000])]

    await script._snapshots(write=True)
    assert len(await _series(scoped)) == 2, "a rebuilt day is skipped"
    assert '"skipped": 1' in capsys.readouterr().out


async def test_a_profile_resolves_from_ours_and_the_inference_stops_reading_an_outside_listing(scoped):
    """An outside source's claim once made `is_public` true and the heuristic
    inferred RSUs from it. Resolved from ours, the listing is unknown, so the
    inference states nothing and the stale values clear."""
    # As an older resolver left it: each column with the source it came from.
    meta = {field: {"source": source, "observed_at": DAY.isoformat(), "freshness": "fresh", "is_manual": False,
                    "conflicts": []}
            for field, source in (("is_public", LEGACY), ("equity_vehicle", "heuristic"))}
    scoped.add(CompanyProfile(slug="acme-robotics", display_name="Acme Robotics", is_public=True,
                              equity_vehicle="rsu", field_meta=meta))
    await scoped.flush()
    scoped.add_all([
        CompanyFact(company_slug="acme-robotics", field="is_public", value={"v": True}, source=LEGACY,
                    observed_at=DAY),
        CompanyFact(company_slug="acme-robotics", field="equity_vehicle", value={"v": "rsu"}, source="heuristic",
                    observed_at=DAY),
    ])
    await scoped.commit()

    await script._profiles(write=False, after=None)
    profile = await scoped.get(CompanyProfile, "acme-robotics", populate_existing=True)
    assert (profile.is_public, profile.equity_vehicle) == (True, "rsu"), "a dry run writes nothing"

    await script._profiles(write=True, after=None)
    profile = await scoped.get(CompanyProfile, "acme-robotics", populate_existing=True)
    assert (profile.is_public, profile.equity_vehicle) == (None, None)
    claims = (await scoped.execute(select(CompanyFact.source, CompanyFact.value)
                                   .where(CompanyFact.field == "equity_vehicle")
                                   .order_by(CompanyFact.id))).all()
    assert claims == [("heuristic", {"v": "rsu"}), ("heuristic", {"v": None})], "appended, never deleted"


async def test_our_own_listing_still_infers_the_vehicle(scoped):
    scoped.add(CompanyProfile(slug="acme-robotics", display_name="Acme Robotics"))
    await scoped.flush()
    await record_fact(scoped, "acme-robotics", "is_public", True, "roleband")
    await record_fact(scoped, "acme-robotics", "equity_vehicle", "options", "heuristic",
                      observed_at=DAY)
    await resolve_and_materialize(scoped, "acme-robotics")
    await scoped.commit()
    await script._profiles(write=True, after=None)
    profile = await scoped.get(CompanyProfile, "acme-robotics", populate_existing=True)
    assert (profile.is_public, profile.equity_vehicle) == (True, "rsu")


async def test_a_leftover_value_no_provenance_names_still_clears(scoped):
    """Wise's shape: `is_public` true with no `field_meta` entry behind it (a
    NOT NULL column kept it when its source stopped being read). Resolved from
    ours, a value no source of ours states clears all the same."""
    scoped.add(CompanyProfile(slug="acme-robotics", display_name="Acme Robotics", is_public=True, field_meta={}))
    await scoped.commit()
    await script._profiles(write=True, after=None)
    profile = await scoped.get(CompanyProfile, "acme-robotics", populate_existing=True)
    assert profile.is_public is None
