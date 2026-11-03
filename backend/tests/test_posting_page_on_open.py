"""Opening a posting reads its page once, after the page is shown.

Only the network is mocked (an httpx MockTransport inside the real Greenhouse
adapter, caught where the adapter builds its client). The company register,
the source policy, the route, the read, the storage and the detail flag are the
real code over the scratch database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.factories import make_job
from tracker.config import get_settings
from tracker.connectors import build_adapter as real_build_adapter
from tracker.connectors.listing.greenhouse import application_form, pay_tiers
from tracker.db.models import Job, JobLifecycleEvent, TrackedCompany
from tracker.schema import AccessSurface, SourceJobFacts
from tracker.source_review import source_wall
from tracker.workflows import posting_pages

FIGMA = json.loads((Path(__file__).parent / "fixtures" / "greenhouse_posting" / "figma.json").read_text())


def _facts(provider: str = "greenhouse", posting_id: str = "6150563004") -> dict:
    return {
        **SourceJobFacts(
            provider="greenhouse", access_surface=AccessSurface.PUBLIC_API,
            tenant_identity="figma", posting_id=posting_id,
        ).as_dict(),
        "provider": provider,
    }


@pytest.fixture
def board(monkeypatch):
    """The Greenhouse board, answering with `board.status` and counting requests.

    `board.during` runs inside the request, while the source "answers": the
    moment a concurrent scan could commit, or a held transaction would show.
    """
    state = type("Board", (), {"status": 200, "requests": [], "during": None, "built": []})()

    async def handler(request):
        state.requests.append(request)
        if state.during is not None:
            await state.during()
        return httpx.Response(state.status, json=FIGMA if state.status == 200 else {})

    def build(*args, **kwargs):
        state.built.append(kwargs)
        return real_build_adapter(*args, **kwargs)

    # Opening an adapter (`async with`) builds its client here, so this is the
    # one place a request can be caught before it leaves: patching the
    # adapter's `_client` instead lets a request reach the live board.
    monkeypatch.setattr(
        "tracker.connectors.listing.base.make_tier_client",
        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    # Records what each read was built with; the adapter is the real one.
    monkeypatch.setattr(posting_pages, "build_adapter", build)
    # No pacing wait between the test's requests. The pacer itself is real.
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    # Each test starts with the state a fresh API process has: the app builds
    # its page reads at the first open (`api.deps.get_page_reads`).
    from tracker.api.app import app

    monkeypatch.delattr(app.state, "page_reads", raising=False)
    return state


def _figma(key: str, **over):
    return make_job(key, company="figma", dedupe_key=f"figma:{key}", **over)


async def _company(db_session, slug: str = "figma", **over) -> None:
    row = {"slug": slug, "display": slug.title(), "adapter": "greenhouse", "board_token": slug,
           "status": "active", "enabled": True}
    row.update(over)
    db_session.add(TrackedCompany(**row))
    await db_session.commit()


async def _seed(db_session, key: str = "open-me", *, company: bool = True, **over) -> int:
    if company:
        await _company(db_session)
    over.setdefault("source_facts", _facts())
    job = _figma(key, **over)
    db_session.add(job)
    await db_session.commit()
    return job.id


async def _readable(api_client, job_id: int) -> bool:
    return (await api_client.get(f"/api/jobs/{job_id}")).json()["application_form_readable"]


async def _open(api_client, job_id: int) -> dict:
    return (await api_client.post(f"/api/jobs/{job_id}/posting-page")).json()


@pytest.mark.asyncio
async def test_opening_an_unread_posting_reads_its_form_once(api_client, db_session, board):
    job_id = await _seed(db_session)

    detail = (await api_client.get(f"/api/jobs/{job_id}")).json()
    assert detail["application_form"] is None
    assert detail["application_form_readable"] is True
    assert board.requests == []  # the detail read never waits on the source

    first = await _open(api_client, job_id)
    assert first["outcome"] == "read"
    assert first["application_form"]["required"] == 5
    assert first["application_form"]["written"] == 3

    again = await _open(api_client, job_id)
    assert again["outcome"] == "already_read"
    assert again["application_form"] == first["application_form"]
    assert len(board.requests) == 1  # a repeat answers from storage

    detail = (await api_client.get(f"/api/jobs/{job_id}")).json()
    assert detail["application_form"]["required"] == 5
    assert detail["application_form_readable"] is False


def _read_at(at: datetime, low: int, high: int) -> dict:
    """What a page read at `at` left: the form, and one yearly tier."""
    facts = SourceJobFacts.from_dict(_facts())
    facts.application_form = application_form(FIGMA["questions"], at)
    facts.compensation = pay_tiers([{"title": "Annual Base Salary Range:", "min_cents": low * 100,
                                     "max_cents": high * 100, "currency_type": "USD"}], at)
    return facts.as_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize(("stored", "moves"), [
    ((200_000, 280_000), 1),  # the employer moved the figures on its page
    ((235_000, 317_000), 0),  # the page states the same figures again
    (None, 0),  # a first reading is not a move
])
async def test_a_page_read_on_open_that_moves_its_band_is_in_the_postings_history(
    api_client, db_session, board, stored, moves
):
    """The queue never reads a posting that has a band, so a page band moves
    only when its posting is opened after its text changed. That move is the
    employer's, and it is recorded as the connector and the text pass record
    theirs; the read belongs to no run, so it is history, not a feed row."""
    if stored is None:
        job_id = await _seed(db_session)
    else:
        read_at = datetime.now(UTC) - timedelta(days=3)
        job_id = await _seed(
            db_session, source_facts=_read_at(read_at, *stored), content_changed_at=read_at + timedelta(days=1),
            disclosed_base_min=stored[0], disclosed_base_max=stored[1], disclosed_currency="USD",
            disclosed_pay_period="year", disclosed_pay_basis="base", disclosed_source="page",
        )

    assert (await _open(api_client, job_id))["outcome"] == "read"

    row = await db_session.get(Job, job_id, populate_existing=True)
    assert (row.disclosed_base_min, row.disclosed_base_max, row.disclosed_source) == (235_000, 317_000, "page")
    history = (await api_client.get(f"/api/jobs/{job_id}/history")).json()
    edits = [e["count"] for e in history["events"] if e["kind"] == "edited" and e["field"] == "disclosed_base"]
    assert edits == ([moves] if moves else [])
    events = (await db_session.scalars(select(JobLifecycleEvent).where(JobLifecycleEvent.job_id == job_id))).all()
    assert [(e.event_type, e.run_id, e.detail) for e in events] == [("changed", None, {"disclosed_base": {
        "from": {"min": 200_000, "max": 280_000, "currency": "USD", "period": "year"},
        "to": {"min": 235_000, "max": 317_000, "currency": "USD", "period": "year"},
    }})] * moves


@pytest.mark.asyncio
async def test_a_failed_read_shows_nothing_and_is_not_asked_again_until_the_cool_down(
    api_client, db_session, board
):
    board.status = 503
    job_id = await _seed(db_session)

    result = await _open(api_client, job_id)
    assert result == {"outcome": "failed", "application_form": None}
    # One retry for a read someone is waiting on, not the run's four.
    assert len(board.requests) == 2

    # The next open answers from storage: nothing is advertised, nothing sent.
    assert await _readable(api_client, job_id) is False
    assert await _open(api_client, job_id) == {"outcome": "failed", "application_form": None}
    assert len(board.requests) == 2

    # Once the cool-down has passed, an open may ask again.
    await db_session.execute(
        update(Job).where(Job.id == job_id).values(source_facts=_failed_at(
            datetime.now(UTC) - timedelta(hours=get_settings().posting_page_retry_hours + 1)
        ))
    )
    await db_session.commit()
    assert await _readable(api_client, job_id) is True


def _failed_at(at: datetime) -> dict:
    return {**_facts(), "application_form": {
        "state": "retrieval_failed", "required": 0, "written": 0, "choices": 0,
        "asks_expected_pay": False, "observed_at": at.isoformat(),
    }}


@pytest.mark.asyncio
async def test_a_posting_gone_since_the_scan_costs_one_request(api_client, db_session, board):
    board.status = 404  # closed on the board, still open in our records
    job_id = await _seed(db_session)

    assert await _open(api_client, job_id) == {"outcome": "failed", "application_form": None}
    assert len(board.requests) == 1  # a 404 is an answer, never retried
    assert await _open(api_client, job_id) == {"outcome": "failed", "application_form": None}
    assert len(board.requests) == 1


@pytest.mark.asyncio
async def test_two_opens_at_once_send_one_request(api_client, db_session, board):
    job_id = await _seed(db_session)

    async def slow_source():
        await asyncio.sleep(0.2)

    board.during = slow_source
    first, second = await asyncio.gather(_open(api_client, job_id), _open(api_client, job_id))

    assert len(board.requests) == 1
    assert {first["outcome"], second["outcome"]} == {"read", "already_read"}
    assert first["application_form"] == second["application_form"]


@pytest.mark.asyncio
async def test_opens_share_one_pacer_and_one_breaker(api_client, db_session, board):
    await _company(db_session)
    ids = [await _seed(db_session, f"p{n}", company=False, source_facts=_facts(posting_id=f"61{n}"))
           for n in range(2)]

    for job_id in ids:
        assert (await _open(api_client, job_id))["outcome"] == "read"

    first, second = board.built
    assert first["limiter_pool"] is second["limiter_pool"]
    assert first["breaker_pool"] is not None
    assert first["breaker_pool"] is second["breaker_pool"]


@pytest.mark.asyncio
async def test_a_refusing_host_stops_being_asked(api_client, db_session, board):
    """Two opens meet the same 503 with no Retry-After: the breaker reads a
    block, and the third open sends nothing, whatever posting."""
    board.status = 503
    await _company(db_session)
    ids = [await _seed(db_session, f"p{n}", company=False, source_facts=_facts(posting_id=f"62{n}"))
           for n in range(3)]

    outcomes = [(await _open(api_client, job_id))["outcome"] for job_id in ids]

    assert outcomes == ["failed", "failed", "failed"]
    assert len(board.requests) == 4  # two opens, one retry each, then none


@pytest.mark.asyncio
async def test_the_reads_are_the_apps_so_a_new_process_asks_again(api_client, db_session, board):
    """The pacer, breakers and readers belong to the app serving the opens,
    not to the workflows module: an app that starts over has a
    closed breaker and asks a host the previous one stopped asking."""
    from tracker.api.app import app

    board.status = 503
    await _company(db_session)
    ids = [await _seed(db_session, f"p{n}", company=False, source_facts=_facts(posting_id=f"63{n}"))
           for n in range(3)]
    for job_id in ids[:2]:
        await _open(api_client, job_id)
    first_pool = app.state.page_reads.limiter_pool
    assert len(board.requests) == 4  # the breaker is open now

    del app.state.page_reads  # the state a restarted API process has
    assert (await _open(api_client, ids[2]))["outcome"] == "failed"

    assert len(board.requests) == 6  # asked again: one request and its retry
    assert app.state.page_reads.limiter_pool is not first_pool


@pytest.mark.asyncio
async def test_a_walled_company_is_read_only_with_the_users_consent(api_client, db_session, board):
    # google is walled by its own robots file (the register's `google` row);
    # a company's declared provider keeps its wall whatever connector reads it.
    await _company(db_session, "google", adapter="greenhouse")
    job = make_job("walled", source_facts=_facts())
    db_session.add(job)
    await db_session.commit()

    assert await _readable(api_client, job.id) is False
    assert await _open(api_client, job.id) == {"outcome": "not_available", "application_form": None}
    assert board.requests == []

    fingerprint = source_wall("greenhouse", company="google").wall_fingerprint
    await db_session.execute(
        update(TrackedCompany).where(TrackedCompany.slug == "google").values(consent_fingerprint=fingerprint)
    )
    await db_session.commit()

    assert await _readable(api_client, job.id) is True
    assert (await _open(api_client, job.id))["outcome"] == "read"
    assert len(board.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("company", [
    {"enabled": False},  # followed once, switched off: no scan reads it either
    {"status": "pending"},
    {"adapter": "ashby"},  # the company moved to a source with no page
])
async def test_a_company_we_do_not_collect_is_never_asked(api_client, db_session, board, company):
    await _company(db_session, **company)
    job_id = await _seed(db_session, company=False)

    assert await _readable(api_client, job_id) is False
    assert await _open(api_client, job_id) == {"outcome": "not_available", "application_form": None}
    assert board.requests == []


@pytest.mark.asyncio
async def test_no_transaction_is_held_while_the_source_answers(api_client, db_session, board):
    """A scan that commits while the page is read keeps its facts, and no
    connection sits idle in a transaction for the length of the request."""
    job_id = await _seed(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    idle: list[int] = []

    async def a_scan_commits():
        async with factory() as other:
            idle.append(await other.scalar(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle in transaction'"
            )))
            scanned = {**_facts(), "source_updated_at": "2026-09-29T08:00:00+00:00"}
            await other.execute(update(Job).where(Job.id == job_id).values(source_facts=scanned))
            await other.commit()

    board.during = a_scan_commits
    assert (await _open(api_client, job_id))["outcome"] == "read"

    assert idle == [0]
    stored = (await db_session.get(Job, job_id, populate_existing=True)).source_facts
    assert stored["source_updated_at"] == "2026-09-29T08:00:00+00:00"  # the scan's
    assert stored["application_form"]["required"] == 5  # and the page's


@pytest.mark.asyncio
async def test_a_source_with_no_posting_page_is_never_asked(api_client, db_session, board):
    job_id = await _seed(db_session, "ashby-role", source_facts=_facts(provider="ashby"))

    assert await _readable(api_client, job_id) is False
    assert await _open(api_client, job_id) == {"outcome": "not_available", "application_form": None}
    assert board.requests == []


@pytest.mark.asyncio
async def test_a_closed_posting_is_not_read(api_client, db_session, board):
    job_id = await _seed(db_session, status="closed")
    result = await _open(api_client, job_id)
    assert result["outcome"] == "not_available"
    assert board.requests == []


@pytest.mark.asyncio
async def test_an_unknown_posting_is_a_404(api_client, board):
    assert (await api_client.post("/api/jobs/999999/posting-page")).status_code == 404
