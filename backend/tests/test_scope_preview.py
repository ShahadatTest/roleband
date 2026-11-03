"""The save review says what a save will do to the Board before it happens.

`POST /api/scope/preview` runs the save's own scope writes in a SAVEPOINT and
rolls them back, so what it answers is held to what the save then does:

- a widening save adds exactly the postings the preview said, and the Board it
  reports is the Board the preview predicted, hidden companies included;
- a narrowing save's preview says the Board shrinks;
- a posting only "Count now" read (no run) is added by neither;
- with a scan holding the run lock, the preview adds nothing now and says so;
- the preview writes nothing, and refuses what the save refuses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.config import get_settings
from tracker.db.inventory_store import write_inventory
from tracker.db.models import (
    AppSetting,
    Job,
    JobPlaceSet,
    JobPlaceSetMember,
    PostingInventory,
    ScrapeRun,
    TrackedCompany,
)
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import inventory_row
from tracker.platform.locks import advisory_unlock, try_advisory_lock
from tracker.schema import RawJob

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

#: Promotion admits only postings read within `inventory_promotion_fresh_hours`
#:, so the rows here are recent.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
COMPANY = "anthropic"

SAVE = {
    "enabled_role_groups": [], "enabled_seniority_bands": ["staff"],
    "enabled_location_groups": ["uk"], "role_answers": [{"track": "technical", "roles": "any"}],
}
WIDER = {**SAVE, "role_answers": [
    {"track": "technical", "roles": "any"}, {"track": "product_program", "roles": "any"},
]}


def _raw(req: str, title: str = "Staff Software Engineer", places=("London, UK",), company=COMPANY) -> RawJob:
    return RawJob(company=company, req_id=req, title=title, url=f"https://jobs.example.test/{req}",
                  locations=list(places))


def _company(slug: str = COMPANY, *, visible: bool = True) -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=slug.title(), adapter="greenhouse", status="active", enabled=True,
        visible=visible, source="catalog",
    )


async def _store(db_session, raws: list[RawJob], *, company=COMPANY) -> None:
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    rows = {raw.dedupe_key(): inventory_row(raw, annotate(raw)) for raw in raws}
    await write_inventory(
        db_session, run_id=run.id, company=company, binding_id=None, rows=rows,
        seen_keys=set(rows), authoritative=False, now=T0, touch_hours=12,
    )
    await db_session.commit()


async def _preview(api_client, body: dict) -> dict:
    answer = await api_client.post("/api/scope/preview", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()


async def _save(api_client, body: dict) -> dict:
    answer = await api_client.put("/api/settings", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()


async def _snapshot(db_session) -> tuple:
    """Everything a save writes: the settings rows and the jobs."""
    db_session.expire_all()
    settings = sorted((row.key, repr(row.value)) for row in (await db_session.scalars(select(AppSetting))).all())
    jobs = sorted((job.req_id, job.in_scope) for job in (await db_session.scalars(select(Job))).all())
    return settings, jobs


@pytest.mark.asyncio
async def test_a_widening_preview_is_what_the_save_then_does(api_client, db_session):
    db_session.add_all([_company(), _company("hushed", visible=False)])
    await db_session.commit()
    await _store(db_session, [
        _raw("keep"),
        _raw("pm", title="Staff Product Manager"),
        _raw("nyc", title="Staff Product Manager", places=("New York, NY",)),  # another place
    ])
    await _store(db_session, [_raw("hpm", title="Staff Product Manager", company="hushed")], company="hushed")
    await _save(api_client, SAVE)

    before = await _snapshot(db_session)
    preview = await _preview(api_client, WIDER)
    assert await _snapshot(db_session) == before, "a preview writes nothing"
    # Two postings join (one at a hidden company, which the Board never shows).
    assert preview == {
        "on_board_now": 1, "on_board_after": 2, "adds_now": 2, "adds_on_board": 1, "adds_later": 0,
        "scan_running": False,
        "examples": [{"title": "Staff Product Manager", "company": COMPANY, "company_display": "Anthropic"}],
    }

    saved = await _save(api_client, WIDER)
    assert (saved["promoted"], saved["on_board"]) == (preview["adds_now"], preview["on_board_after"])


@pytest.mark.asyncio
async def test_a_role_listed_at_two_places_is_one_row_in_the_preview_as_on_the_board(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("london"), _raw("manchester", places=("Manchester, UK",))])
    assert (await _save(api_client, SAVE))["on_board"] == 2
    jobs = (await db_session.scalars(select(Job).where(Job.company == COMPANY).order_by(Job.id))).all()
    place_set = JobPlaceSet(company=COMPANY, title="staff software engineer", text_hash="0" * 32, size=2,
                            places=["London, UK", "Manchester, UK"], rule_version="t1")
    db_session.add(place_set)
    await db_session.flush()
    db_session.add_all([JobPlaceSetMember(job_id=job.id, set_id=place_set.id, status="auto") for job in jobs])
    await db_session.commit()

    preview = await _preview(api_client, SAVE)
    assert (preview["on_board_now"], preview["on_board_after"]) == (1, 1)
    assert (await _save(api_client, SAVE))["on_board"] == preview["on_board_after"]


@pytest.mark.asyncio
async def test_a_narrowing_preview_says_the_board_shrinks(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep"), _raw("also")])
    await _save(api_client, SAVE)

    narrower = {**SAVE, "enabled_location_groups": ["united_states"]}
    preview = await _preview(api_client, narrower)
    assert (preview["on_board_now"], preview["on_board_after"], preview["adds_now"]) == (2, 0, 0)
    assert preview["examples"] == []
    assert (await _save(api_client, narrower))["on_board"] == preview["on_board_after"]


@pytest.mark.asyncio
async def test_a_posting_no_sync_named_is_added_by_neither(api_client, db_session):
    """Read only by "Count now": it has no run for its observation,
    so the save leaves it for the next sync, and the preview must not promise it."""
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("counted")])
    await db_session.execute(update(PostingInventory).values(last_seen_run_id=None))
    await db_session.commit()

    preview = await _preview(api_client, SAVE)
    assert (preview["adds_now"], preview["adds_later"], preview["on_board_after"]) == (0, 0, 0)
    saved = await _save(api_client, SAVE)
    assert (saved["promoted"], saved["on_board"]) == (0, 0)


@pytest.mark.asyncio
async def test_with_promotion_switched_off_the_preview_promises_nothing(api_client, db_session, monkeypatch):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep")])
    monkeypatch.setattr(get_settings(), "inventory_promotion_enabled", False)

    preview = await _preview(api_client, SAVE)
    assert (preview["adds_now"], preview["adds_later"], preview["on_board_after"], preview["examples"]) == (0, 0, 0, [])
    saved = await _save(api_client, SAVE)
    assert (saved["promoted"], saved["on_board"]) == (0, 0)


@pytest.mark.asyncio
async def test_with_a_scan_running_the_preview_adds_nothing_now_and_says_why(api_client, db_session):
    db_session.add(_company())
    await db_session.commit()
    await _store(db_session, [_raw("keep")])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    key = get_settings().advisory_lock_key
    async with factory() as run_session:
        assert await try_advisory_lock(run_session, key)
        try:
            preview = await _preview(api_client, SAVE)
            assert (preview["scan_running"], preview["adds_now"], preview["adds_later"]) == (True, 0, 1)
            assert preview["on_board_after"] == 0
            saved = await _save(api_client, SAVE)
            assert (saved["promoted"], saved["promotion_pending"], saved["on_board"]) == (0, True, 0)
        finally:
            await advisory_unlock(run_session, key)
    assert (await _preview(api_client, SAVE))["scan_running"] is False, "the probe never holds the lock"


@pytest.mark.asyncio
async def test_the_preview_refuses_what_the_save_refuses_and_keeps_the_persona(api_client, db_session):
    half = await api_client.post("/api/scope/preview", json={**SAVE, "experience_stage": "staff"})
    assert half.status_code == 422
    before = await _snapshot(db_session)
    await _preview(api_client, {**SAVE, "experience_stage": "senior", "target_stage": "principal"})
    assert await _snapshot(db_session) == before
    assert (await api_client.get("/api/profile")).json().get("profile") is None
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0
