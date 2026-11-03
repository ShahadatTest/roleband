"""The catalog fact sheet, the input to the curated-membership call.

The contracts, each on a way the sheet could mislead the decision:

* **Never measured is never zero.** A company nobody scanned has no duration,
  and the sheet must say so rather than print a number that reads as instant.
* **A duration is a whole scan's.** The median of recent whole scans; a scan
  cut short or refused is not a scan's length.
* **The radar count is what we HOLD** — open and in scope, per company, from
  the store's own query.
* **A walled company is named as walled**, because a walled company is never
  curated.
* **Every discovery company appears**, tracked or not: an untracked one reading
  0 IS the question the curator is answering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from scripts.company_fact_sheet import collect, render
from tests.company_contract_seed import company_job
from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.db.models import Job, ScrapeRun, ScrapeSourceRun, SourceBinding, TrackedCompany
from tracker.db.queries.companies import open_counts_by_company, scan_seconds_by_company


def _job(**over) -> Job:
    """A stored posting, using the shape the company contract seed pins."""
    company, req = over.pop("company", "anthropic"), over.pop("req_id", "R1")
    return company_job(company, req, **over)


@pytest.mark.asyncio
async def test_the_radar_count_is_open_and_in_scope(db_session):
    db_session.add_all([
        _job(req_id="R1"),
        _job(req_id="R2", in_scope=False),
        _job(req_id="R3", status="closed"),
        _job(req_id="R4", company="openai"),
    ])
    await db_session.flush()

    counts = await open_counts_by_company(db_session)
    assert counts.get("anthropic") == 1, "the closed and the out-of-scope rows are not radar"
    assert counts.get("openai") == 1


@pytest.mark.asyncio
async def test_a_company_never_scanned_has_no_duration(db_session):
    """Absence is the answer. Reading it as 0 would report an unscanned company
    as instant, which is the one number a cost decision must not invent."""
    db_session.add(_job())
    await db_session.flush()

    seconds = await scan_seconds_by_company(db_session)
    assert "anthropic" not in seconds

    rows = await collect(db_session)
    row = next(r for r in rows if r["slug"] == "anthropic")
    assert row["scan_seconds"] is None
    assert " -" in render([row]), "an unmeasured scan prints as '-', never as 0s"


@pytest.mark.asyncio
async def test_a_duration_is_the_median_of_whole_recent_scans_only(db_session):
    now = datetime.now(UTC)
    db_session.add_all([
        TrackedCompany(slug=slug, display=slug.title(), adapter=slug, status="active",
                       enabled=True, visible=True, source="builtin")
        for slug in ("stripe", "apple")
    ])
    await db_session.flush()
    db_session.add_all([
        SourceBinding(id=1, company_slug="stripe", connector_kind="adapter",
                      connector_id="greenhouse", status="stable",
                      closure_capability="authoritative"),
        SourceBinding(id=2, company_slug="apple", connector_kind="adapter",
                      connector_id="apple", status="stable",
                      closure_capability="authoritative"),
    ])
    await db_session.flush()

    def run(run_id, binding, slug, outcome, seconds, age_days=1):
        started = now - timedelta(days=age_days)
        return ScrapeSourceRun(
            run_id=run_id, binding_id=binding, company_slug=slug, provider_key=slug,
            scan_mode="reconcile", outcome=outcome, started_at=started,
            finished_at=started + timedelta(seconds=seconds),
        )

    runs = []
    for run_id in range(2, 7):
        db_session.add(ScrapeRun(id=run_id, started_at=now - timedelta(days=1), status="ok"))
    await db_session.flush()
    runs += [run(2, 1, "stripe", "ok", 10), run(3, 1, "stripe", "lossy", 20), run(4, 1, "stripe", "degraded", 30)]
    # Our own bounds cut these short, and a refusal returns fast: none is a scan's length.
    runs += [run(5, 1, "stripe", "bounded", 1), run(6, 1, "stripe", "failed", 1)]
    # Only history older than the window: not measured.
    runs += [run(2, 2, "apple", "ok", 400, age_days=45)]
    db_session.add_all(runs)
    await db_session.commit()

    assert await scan_seconds_by_company(db_session) == {"stripe": 20.0}


@pytest.mark.asyncio
async def test_every_discovery_company_is_listed_with_its_state(db_session):
    rows = await collect(db_session)
    assert {r["slug"] for r in rows} == set(COMPANY_DISCOVERY)

    by_slug = {r["slug"]: r for r in rows}
    assert by_slug["anthropic"]["state"] == "live"
    assert by_slug["tesla"]["state"] == "parked"
    # Arm and Klarna are catalog rows.
    assert by_slug["arm"]["state"] == "ready" and by_slug["arm"]["provider"] == "radancy"
    assert by_slug["klarna"]["provider"] == "deel"


@pytest.mark.asyncio
async def test_a_walled_company_is_named_as_walled(db_session):
    """A walled company is collected only after the user follows it, so it can
    never be curated — the sheet has to show which ones those are."""
    rows = {r["slug"]: r for r in await collect(db_session)}
    assert rows["google"]["walled"] == "google", rows["google"]
    assert not rows["google"]["curated"]
    assert rows["anthropic"]["walled"] is None

    printed = render([rows["google"]])
    assert "walled:google" in printed


@pytest.mark.asyncio
async def test_a_sector_filter_narrows_to_that_sector(db_session):
    rows = await collect(db_session, "faang")
    assert rows and all("faang" in r["sectors"] for r in rows)
    assert {"amazon", "apple", "google"} <= {r["slug"] for r in rows}


@pytest.mark.asyncio
async def test_the_sheet_reads_and_writes_nothing(db_session):
    """It informs a decision; it never makes one. No roster row moves."""
    before = (await db_session.execute(select(TrackedCompany.slug, TrackedCompany.enabled))).all()
    await collect(db_session)
    after = (await db_session.execute(select(TrackedCompany.slug, TrackedCompany.enabled))).all()
    assert before == after
