"""The `levels_backfill` post pass.

A level is written at scrape time, so a ladder, title-rule or pay-grade change
reaches only rows observed again. The pass re-derives every stored row from its
stored columns: a stale row moves once, its scope follows, and a second run
writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tracker.db.inventory_store import write_inventory
from tracker.db.models import Job, JobSourceIdentity, ScrapeRun, SourceBinding, TrackedCompany
from tracker.db.repo import refresh_listed_rungs
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import inventory_row
from tracker.schema import RawJob
from tracker.settings_store import (
    set_enabled_bands,
    set_enabled_domains,
    set_enabled_locations,
    set_enabled_roles,
    set_enabled_tracks,
)
from tracker.workflows.relevel import pending_relevels, relevel_jobs

_T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _job(key: str, title: str, *, company: str = "google", family: str, track: str,
         band: str, basis: str | None, pay: tuple[int, int] | None = None,
         raw_level: str | None = None, description: str | None = None,
         status: str = "closed", in_scope: bool = False, last_seen: datetime = _T0) -> Job:
    return Job(
        company=company, req_id=key, dedupe_key=f"{company}:{key}", title=title,
        url=f"https://example.test/{key}", locations=["London, UK"], location_groups=["uk"],
        domains=[], workplace_type="onsite", level_band=band, level_confidence="confirmed",
        level_basis=basis, family=family, track=track, comp_currency="USD", status=status,
        in_scope=in_scope, first_seen=_T0, last_seen=last_seen, first_posted_at=_T0,
        description_sections=[], raw_level=raw_level, description_text=description,
        disclosed_base_min=pay[0] if pay else None, disclosed_base_max=pay[1] if pay else None,
        disclosed_currency="USD" if pay else None, disclosed_pay_basis="base" if pay else None,
        disclosed_pay_period="year" if pay else None,
    )


@pytest.mark.asyncio
async def test_a_stale_row_is_relevelled_once_and_its_scope_follows(db_session):
    db_session.add_all([
        # Stored by an older rule: a Senior Software Engineering Manager read as staff.
        _job("sem", "Senior Software Engineering Manager, Search", family="engineering_management",
             track="management", band="staff", basis=None),
        # A bare title whose stored range is Product Manager I's (L4).
        _job("pm", "Product Manager, Google Analytics", family="product_management",
             track="product_program", band="senior", basis="generic", pay=(138_000, 197_000)),
        # Control: already what the model says, so never written.
        _job("staff", "Staff Software Engineer, Ads", family="software_engineering",
             track="technical", band="staff", basis="company"),
    ])
    await set_enabled_roles(db_session, ["engineering_management", "product_management"])
    await set_enabled_bands(db_session, ["principal"])
    await set_enabled_tracks(db_session, ["management", "product_program"])
    await set_enabled_locations(db_session, ["uk"])
    await set_enabled_domains(db_session, [])
    await db_session.commit()

    result = await relevel_jobs(db_session)
    await db_session.commit()

    rows = {
        r.req_id: (r.level_band, r.level_basis, r.in_scope)
        for r in (await db_session.execute(
            select(Job.req_id, Job.level_band, Job.level_basis, Job.in_scope)
        )).all()
    }
    assert rows == {
        "sem": ("principal", "company", True),
        "pm": ("mid", "pay_grade", False),
        "staff": ("staff", "company", False),
    }
    assert result == {"rungs_refreshed": 0, "relevelled": 2, "band_moved": 2, "in_scope_changed": 1}
    # Caught up: the next run is a scan that writes nothing.
    assert await relevel_jobs(db_session) == {
        "rungs_refreshed": 0, "relevelled": 0, "band_moved": 0, "in_scope_changed": 0}


async def _listed(db_session, company: str, postings: list[tuple[str, str, str | None]], *, at: datetime,
                  binding_id: int | None = None) -> None:
    """What a sync read of the board at `at`: (req_id, title, printed rung)."""
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    raws = [RawJob(company=company, req_id=req, title=title, url=f"https://example.test/{req}",
                   locations=["London, UK"], raw_level=rung) for req, title, rung in postings]
    rows = {raw.dedupe_key(): inventory_row(raw, annotate(raw)) for raw in raws}
    await write_inventory(db_session, run_id=run.id, company=company, binding_id=binding_id, rows=rows,
                          seen_keys=set(rows), authoritative=False, now=at, touch_hours=12)


@pytest.mark.asyncio
async def test_a_held_row_takes_the_rung_its_board_now_prints(db_session):
    """Promotion can admit rows from inventory read before the board's
    printed rung was (Waymo): held with no rung, each reads as an unstated
    level the radar admits, and every run would re-project it back in
    although the sync, reading "6", judged it out and never wrote it again."""
    later = _T0 + timedelta(days=1)
    tlm = "Technical Lead Manager, Multiverse"
    db_session.add_all([
        # Held with no rung: a guess the radar admits.
        _job("tlm", tlm, company="waymo", family="engineering_management", track="management",
             band="staff", basis="unmapped", status="open", in_scope=True),
        # A rung read from the posting's text: a listing that prints none never erases it.
        _job("ic5", "Product Manager", company="microsoft", family="product_management",
             track="product_program", band="senior", basis="stated", raw_level="IC5", status="open"),
        # Written by a sync after the read below: the row is the newer evidence.
        _job("fresh", "Technical Lead Manager, Pullover Maneuvers", company="waymo",
             family="engineering_management", track="management", band="staff", basis="unmapped",
             status="open", last_seen=later + timedelta(hours=1)),
        # Closed: history, never rewritten.
        _job("gone", "Technical Lead Manager, Query & Storage SWE", company="waymo",
             family="engineering_management", track="management", band="staff", basis="unmapped"),
    ])
    await _listed(db_session, "waymo", [("tlm", tlm, "6"), ("fresh", "Technical Lead Manager, Pullover Maneuvers", "6"),
                                        ("gone", "Technical Lead Manager, Query & Storage SWE", "6")], at=later)
    await _listed(db_session, "microsoft", [("ic5", "Product Manager", None)], at=later)
    await set_enabled_roles(db_session, ["engineering_management", "product_management"])
    await set_enabled_bands(db_session, ["principal", "director_plus"])
    await set_enabled_tracks(db_session, ["management", "product_program"])
    await set_enabled_locations(db_session, ["uk"])
    await set_enabled_domains(db_session, [])
    await db_session.commit()

    result = await relevel_jobs(db_session)
    await db_session.commit()

    rows = {
        r.req_id: (r.raw_level, r.level_band, r.level_basis, r.in_scope)
        for r in (await db_session.execute(
            select(Job.req_id, Job.raw_level, Job.level_band, Job.level_basis, Job.in_scope)
        )).all()
    }
    # Waymo's 6 is its staff rung: stated, and outside a principal-and-up radar.
    assert rows["tlm"] == ("6", "staff", "stated", False)
    assert rows["ic5"][0] == "IC5"
    assert rows["fresh"][:3] == (None, "staff", "unmapped")
    assert rows["gone"][0] is None
    assert result["rungs_refreshed"] == 1
    # Caught up: nothing left to carry, nothing to re-read.
    again = await relevel_jobs(db_session)
    assert (again["rungs_refreshed"], again["relevelled"]) == (0, 0)


@pytest.mark.asyncio
async def test_the_newest_listed_read_decides_under_either_key(db_session):
    """A held row is read under its own key and under each key a binding
    lists it by. Either path carries the rung, a read found both ways counts
    once, and when reads disagree the newest decides, whichever path found
    it, even when it agrees with the row and an older read does not."""
    later, latest = _T0 + timedelta(days=1), _T0 + timedelta(days=2)
    db_session.add(TrackedCompany(slug="acme", display="Acme", adapter="greenhouse", board_token="acme"))
    await db_session.flush()
    first = SourceBinding(company_slug="acme", connector_kind="adapter", connector_id="greenhouse",
                          status="retired")
    stable = SourceBinding(company_slug="acme", connector_kind="recipe", connector_id="acme-careers",
                           status="stable", closure_capability="authoritative")
    keys = ("direct", "alias", "both", "alias-newer", "own-newer", "agrees", "stray", "closed")
    jobs = {key: _job(key, f"Software Engineer, {key}", company="acme", family="software_engineering",
                      track="technical", band="senior", basis="none", status="open")
            for key in keys}
    jobs["agrees"].raw_level = "L6"
    jobs["closed"].status = "closed"
    db_session.add_all([first, stable, *jobs.values()])
    await db_session.flush()
    db_session.add_all([
        JobSourceIdentity(binding_id=binding.id, job_id=jobs[key].id, source_key=f"acme:{source}")
        for key, binding, source in [
            ("alias", stable, "alias-r"),
            # The posting's own key, recorded for the binding that lists it: one read, two paths.
            ("both", stable, "both"),
            ("alias-newer", stable, "alias-newer-r"),
            ("own-newer", stable, "own-newer-r"),
            ("agrees", stable, "agrees-r"),
            # The key is the stable binding's read, not this binding's.
            ("stray", first, "stray-r"),
            ("closed", stable, "closed-r"),
        ]
    ])
    await _listed(db_session, "acme", [("direct", "SWE", "L5"), ("alias-newer", "SWE", "L4"),
                                       ("agrees", "SWE", "L4")], at=later)
    await _listed(db_session, "acme", [("own-newer", "SWE", "L7")], at=latest)
    await _listed(db_session, "acme", [("both", "SWE", "L5"), ("alias-r", "SWE", "L6"),
                                       ("own-newer-r", "SWE", "L4"), ("stray-r", "SWE", "L9"),
                                       ("closed-r", "SWE", "L9")], at=later, binding_id=stable.id)
    await _listed(db_session, "acme", [("alias-newer-r", "SWE", "L6"), ("agrees-r", "SWE", "L6")],
                  at=latest, binding_id=stable.id)

    changed = await refresh_listed_rungs(db_session)

    rungs = dict((await db_session.execute(select(Job.req_id, Job.raw_level))).all())
    assert rungs == {
        "direct": "L5", "alias": "L6", "both": "L5", "alias-newer": "L6", "own-newer": "L7",
        "agrees": "L6", "stray": None, "closed": None,
    }
    assert sorted(changed) == sorted(jobs[key].id for key in ("direct", "alias", "both", "alias-newer", "own-newer"))
    assert await refresh_listed_rungs(db_session) == []


@pytest.mark.asyncio
async def test_a_printed_rung_is_read_from_the_stored_description(db_session):
    # `raw_level` is empty on rows fetched before the scrape-time reader; the
    # pass reads Microsoft's compensation sentence, and only for an employer
    # that prints a rung.
    sentence = (
        "Product Management IC3 - The typical base pay range for this role across the U.S. "
        "is USD $98,300 - $193,200 per year."
    )
    db_session.add_all([
        _job("ms", "Product Manager II", company="microsoft", family="product_management",
             track="product_program", band="senior", basis="generic", description=sentence),
        # Google prints nothing: the same sentence is prose there.
        _job("g", "Product Manager II, Maps", family="product_management",
             track="product_program", band="senior", basis="company", description=sentence),
    ])
    await db_session.commit()

    _, pending = await pending_relevels(db_session)
    moved = {item.row.req_id: (item.reading.band.value, item.reading.basis.value) for item in pending}
    assert moved == {"ms": ("mid", "stated")}


@pytest.mark.asyncio
async def test_descriptions_are_read_only_where_a_printed_rung_could_band(db_session, monkeypatch):
    """Nvidia prints a family-relative "Level 4" that no ladder bands, so its
    descriptions change no reading and loading them every run is for nothing.
    Only Microsoft prints a code the atlas bands in its text."""
    from tracker.workflows import relevel

    read: list[str] = []
    real = relevel.stated_level

    def spy(company, description):
        if description is not None:
            read.append(company)
        return real(company, description)

    monkeypatch.setattr(relevel, "stated_level", spy)
    db_session.add_all([
        _job("ms", "Product Manager II", company="microsoft", family="product_management",
             track="product_program", band="senior", basis="generic", description="Product Management IC3"),
        _job("nv", "Senior Software Engineer", company="nvidia", family="software_engineering",
             track="technical", band="senior", basis="generic", description="This is a Level 4 role."),
        # Control: a stored rung is never re-read from the text.
        _job("ms-held", "Product Manager", company="microsoft", family="product_management",
             track="product_program", band="mid", basis="stated", raw_level="IC3",
             description="Product Management IC4"),
    ])
    await db_session.commit()

    await pending_relevels(db_session)

    assert read == ["microsoft"]
