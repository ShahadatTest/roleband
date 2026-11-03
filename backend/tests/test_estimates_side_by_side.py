"""Each source's pay estimate, side by side, never mixed.

Our data and a plugin's must not affect each other at the data
level. So a collected posting is estimated by BOTH resolvers, each from its own
data, and both estimates are stored (`job_comp_estimate`); `jobs.comp_*` is a
copy of the selected one; the append-only history records OURS, whichever source
the job shows; the job detail lists the shown source's providers; and the daily
pay snapshot keeps one series per source, the statistics reading the shown one.

The two resolvers answer distinct figures (ours 300,000, the plugin's 999,000),
so a writer that stores the wrong one shows it in the number.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.plugin_seed import cover
from tracker.analytics.comp_trends import compute_comp_metrics
from tracker.comp_providers.base import CompContext, CompEstimate, CompProvider
from tracker.db.models import (
    CompanyProfile,
    CompSnapshot,
    Job,
    JobCompEstimate,
    JobObservation,
    PluginInstall,
    ReferenceState,
    ScrapeRun,
)
from tracker.db.repo import upsert_job
from tracker.enrich.comp import OURS, CompResolver, EstimateSet
from tracker.enrich.enricher import Annotation, build_enriched
from tracker.plugins.registry import PAY_LEVELS
from tracker.schema import LevelBand, LevelConfidence, RawJob, RoleTrack

AT = datetime(2026, 10, 1, tzinfo=UTC)


class _Fixed(CompProvider):
    """A provider that answers one figure for every senior posting."""

    def __init__(self, name: str, median: int, provider: str) -> None:
        self.name, self.median, self.provider = name, median, provider

    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        return CompEstimate(median=self.median, low=self.median - 10_000, high=self.median + 10_000,
                            currency="USD", source=f"{self.provider} figure", detail={}, provider=self.provider)


def _estimates(*, plugin: bool) -> EstimateSet:
    ours = CompResolver([_Fixed("table", 300_000, "manual")])
    theirs = ("tpl", CompResolver([_Fixed("table", 999_000, "tpl")])) if plugin else None
    fingerprints = {OURS: "fp-ours", **({"tpl": "fp-tpl"} if plugin else {})}
    return EstimateSet(ours, theirs, fingerprints=fingerprints, fingerprint="fp-shown")


def _raw() -> RawJob:
    return RawJob(company="acme", req_id="1", title="Senior Software Engineer", url="https://example.com/1",
                  locations=["San Francisco, CA"])


def _annotation() -> Annotation:
    return Annotation(band=LevelBand.SENIOR, confidence=LevelConfidence.CONFIRMED, family="software_engineering",
                      location_groups=["silicon_valley"], track=RoleTrack.TECHNICAL, domains=[], basis=None)


async def _collect(db, estimates: EstimateSet) -> Job:
    db.add(CompanyProfile(slug="acme", display_name="Acme"))
    run = ScrapeRun(started_at=AT, status="running")
    db.add(run)
    await db.flush()
    enriched = await build_enriched(_raw(), _annotation(), estimates)
    job, _ = await upsert_job(db, run, enriched, {})
    await db.commit()
    return job


async def _stored(db) -> dict[str, tuple]:
    rows = (await db.execute(select(JobCompEstimate))).scalars().all()
    return {r.source: (r.comp_median, r.comp_provider, r.ref_fp, [s["provider"] for s in r.sources]) for r in rows}


@pytest.mark.asyncio
async def test_a_collected_posting_stores_both_estimates_and_shows_the_selected_one(db_session):
    job = await _collect(db_session, _estimates(plugin=True))
    assert (job.comp_median, job.comp_provider, job.comp_ref_fp) == (999_000, "tpl", "fp-shown")
    assert await _stored(db_session) == {
        "roleband": (300_000, "manual", "fp-ours", ["table"]),
        "tpl": (999_000, "tpl", "fp-tpl", ["table"]),
    }


@pytest.mark.asyncio
async def test_the_history_records_our_estimate_whichever_source_the_job_shows(db_session):
    """The append-only history never depends on which plugin was on."""
    await _collect(db_session, _estimates(plugin=True))
    [observation] = (await db_session.execute(select(JobObservation))).scalars().all()
    assert observation.comp_median == 300_000
    assert observation.payload["comp_median"] == 300_000
    assert observation.payload["comp_provenance"] == "manual figure"
    assert [s["median"] for s in observation.payload["comp_sources"]] == [300_000]


@pytest.mark.asyncio
async def test_with_no_plugin_the_posting_shows_and_records_ours_alone(db_session):
    job = await _collect(db_session, _estimates(plugin=False))
    assert job.comp_median == 300_000
    assert await _stored(db_session) == {"roleband": (300_000, "manual", "fp-ours", ["table"])}


@pytest.mark.asyncio
async def test_the_job_detail_lists_the_providers_of_the_source_it_shows(api_client, db_session):
    job = await _collect(db_session, _estimates(plugin=True))
    db_session.add(PluginInstall(
        plugin_id="tpl", name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": [{"slot": PAY_LEVELS}]}, fingerprint="fp1", approved_fingerprint="fp1", enabled=True,
    ))
    await db_session.flush()
    cover(db_session, "tpl", (PAY_LEVELS,), ("acme",))
    await db_session.commit()
    shown = (await api_client.get(f"/api/jobs/{job.id}")).json()
    assert [s["median"] for s in shown["comp_sources"]] == [999_000]

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    ours = (await api_client.get(f"/api/jobs/{job.id}")).json()
    assert [s["median"] for s in ours["comp_sources"]] == [300_000]


@pytest.mark.asyncio
async def test_the_daily_snapshot_keeps_one_series_per_source_and_never_mixes_them(db_session):
    await _collect(db_session, _estimates(plugin=True))
    db_session.add(ReferenceState(id=1, applied_providers={"active": {PAY_LEVELS: ["tpl"]}}))
    await db_session.commit()
    await compute_comp_metrics(db_session)
    await db_session.commit()
    rows = (await db_session.execute(select(CompSnapshot.source, CompSnapshot.comp_values))).all()
    assert sorted((source, list(values)) for source, values in rows) == [
        ("roleband", [300_000]), ("tpl", [999_000])]

    # Off: today's series is ours alone; the plugin's day is not rewritten into it.
    state = await db_session.get(ReferenceState, 1)
    state.applied_providers = {"active": {}}
    await db_session.commit()
    await compute_comp_metrics(db_session)
    await db_session.commit()
    rows = (await db_session.execute(select(CompSnapshot.source, CompSnapshot.comp_values))).all()
    assert sorted((source, list(values)) for source, values in rows) == [("roleband", [300_000])]
