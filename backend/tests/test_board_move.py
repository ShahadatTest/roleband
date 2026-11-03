"""A company whose careers page moved: the move itself.

A company can leave one ATS for another or rename its board; the stored
address then answers 404 on every scan. `record_board_move` points
the company at the new board without handing the new board closure authority it
has not earned.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from tracker import board_relocate
from tracker.api.routers import companies as companies_router
from tracker.company_store import CompanyError, record_board_move
from tracker.db.models import Notification, PostingInventory, SourceBinding, TrackedCompany

#: The move route starts a first scan; `no_escape` refuses any real process.
pytestmark = pytest.mark.usefixtures("no_escape")


def _company(slug: str = "hex-technologies", **over) -> TrackedCompany:
    fields = {
        "slug": slug, "display": "Hex Technologies", "adapter": "greenhouse",
        "board_token": "hextechnologies", "careers_url": None, "status": "active",
        "enabled": True, "visible": True, "source": "directory-set", "role_catalog_status": "done",
    }
    return TrackedCompany(**{**fields, **over})


async def _seed(db_session, **over) -> None:
    db_session.add(_company(**over))
    await db_session.flush()
    db_session.add(SourceBinding(
        company_slug=over.get("slug", "hex-technologies"), connector_kind="adapter",
        connector_id=over.get("adapter", "greenhouse"), status="stable",
        closure_capability="authoritative",
    ))
    await db_session.flush()


async def _bindings(db_session, slug: str) -> list[SourceBinding]:
    return list((await db_session.scalars(
        select(SourceBinding).where(SourceBinding.company_slug == slug).order_by(SourceBinding.id)
    )).all())


@pytest.mark.asyncio
async def test_a_move_across_families_rebinds_with_closure_withheld(db_session):
    await _seed(db_session)

    assert await record_board_move(
        db_session, "hex-technologies", adapter="ashby", board_token="hex"
    ) is True

    row = await db_session.get(TrackedCompany, "hex-technologies")
    assert (row.adapter, row.board_token, row.board_region) == ("ashby", "hex", None)
    assert row.role_catalog_status == "pending", "the catalog described the old board"
    old, new = await _bindings(db_session, "hex-technologies")
    assert old.status == "retired" and old.retired_at is not None
    assert "greenhouse:hextechnologies -> ashby:hex" in old.notes
    assert (new.connector_id, new.status) == ("ashby", "stable")
    assert new.closure_capability == "none", "the new board closes nothing until validated"


@pytest.mark.asyncio
async def test_a_renamed_board_on_the_same_family_still_rebinds(db_session):
    # Amigo: ashby `amigo` -> ashby `concurrence`. Same connector, but a
    # different board, so the authority the old token earned does not carry.
    await _seed(db_session, slug="amigo", display="Amigo", adapter="ashby", board_token="amigo")

    assert await record_board_move(db_session, "amigo", adapter="ashby", board_token="concurrence")

    old, new = await _bindings(db_session, "amigo")
    assert old.status == "retired"
    assert new.connector_id == "ashby" and new.closure_capability == "none"
    assert (await db_session.get(TrackedCompany, "amigo")).board_token == "concurrence"


@pytest.mark.asyncio
async def test_moving_to_the_board_it_already_reads_changes_nothing(db_session):
    await _seed(db_session, adapter="ashby", board_token="hex")

    assert await record_board_move(
        db_session, "hex-technologies", adapter="ashby", board_token="hex"
    ) is False
    (only,) = await _bindings(db_session, "hex-technologies")
    assert only.status == "stable" and only.closure_capability == "authoritative"


@pytest.mark.asyncio
async def test_an_unknown_adapter_or_company_is_refused(db_session):
    await _seed(db_session)
    with pytest.raises(CompanyError, match="unknown adapter"):
        await record_board_move(db_session, "hex-technologies", adapter="nope", board_token="hex")
    with pytest.raises(CompanyError, match="not a tracked company"):
        await record_board_move(db_session, "nobody", adapter="ashby", board_token="hex")
    row = await db_session.get(TrackedCompany, "hex-technologies")
    assert row.adapter == "greenhouse" and row.board_token == "hextechnologies"


@pytest.mark.asyncio
async def test_a_built_in_moves_only_in_config(db_session):
    # `ensure_builtins` re-seeds a built-in's board from config.COMPANIES, so
    # a move written here would be silently undone.
    with pytest.raises(CompanyError, match="built in"):
        await record_board_move(db_session, "anthropic", adapter="ashby", board_token="anthropic")


@pytest.mark.asyncio
async def test_a_built_in_the_code_moves_is_rebound_with_closure_withheld(db_session, monkeypatch):
    """The old binding stops speaking for the company, so it can no longer close
    the postings the new adapter lists under other ids."""
    from tracker.company_store import ensure_builtins
    from tracker.config import COMPANIES

    await ensure_builtins(db_session)
    db_session.add(SourceBinding(
        company_slug="anthropic", connector_kind="adapter", connector_id="greenhouse",
        status="stable", closure_capability="authoritative",
    ))
    await db_session.commit()

    await ensure_builtins(db_session)
    assert [(b.connector_id, b.status) for b in await _bindings(db_session, "anthropic")] == [
        ("greenhouse", "stable")
    ], "an unchanged built-in is left alone"

    monkeypatch.setitem(COMPANIES, "anthropic", {**COMPANIES["anthropic"], "adapter": "ashby"})
    await ensure_builtins(db_session)
    await db_session.commit()
    db_session.expire_all()
    old, new = await _bindings(db_session, "anthropic")
    assert (old.connector_id, old.status, old.notes) == (
        "greenhouse", "retired", "retired: built-in moved greenhouse -> ashby"
    )
    assert (new.connector_id, new.status, new.closure_capability) == ("ashby", "stable", "none")
    assert (await db_session.get(TrackedCompany, "anthropic")).adapter == "ashby"

    await ensure_builtins(db_session)
    assert len(await _bindings(db_session, "anthropic")) == 2, "a settled move is not rebound again"


# --------------------------------------------------------------------------- #
# Over HTTP: find the new careers page, move to it, or stop following
# --------------------------------------------------------------------------- #

ASHBY = "https://api.ashbyhq.com/posting-api/job-board/"
SEEN = ["Staff Software Engineer", "Head of Data", "Product Designer"]


@pytest_asyncio.fixture
async def gone(db_session, monkeypatch):
    """Hex on its dead Greenhouse board, a Coverage row ringing for it, and a
    stand-in for the internet: Ashby serves `hex`, everything else 404s."""
    await _seed(db_session)
    binding = (await _bindings(db_session, "hex-technologies"))[0]
    for i, title in enumerate(SEEN):
        db_session.add(PostingInventory(
            dedupe_key=f"hex-technologies:{i}", company="hex-technologies", req_id=str(i),
            title=title, url=f"https://example.test/{i}", level_band="senior", level_confidence="high",
            track="ic", content_hash=f"h{i}", first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        ))
    db_session.add(Notification(
        created_at=datetime.now(UTC), priority="normal", category="coverage", title="Hex Technologies's careers page is gone",
        body="...", source_type="binding", source_id=binding.id, meta={"cause": "board_missing"},
    ))
    await db_session.commit()

    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        asked.append(url)
        if url == f"{ASHBY}hex":
            return httpx.Response(200, json={"jobs": [{"id": t, "title": t} for t in [*SEEN, "Recruiter"]]})
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        companies_router, "public_client",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    # The finder's per-family pace has its own case in test_board_relocate.
    monkeypatch.setattr(board_relocate, "_probe_delay", lambda family: 0.0)
    dispatched: list[None] = []
    real_ring = companies_router.scan_requests.ring

    async def ring(session, *, requested_by):
        dispatched.append(None)
        await real_ring(session, requested_by=requested_by)

    monkeypatch.setattr(companies_router.scan_requests, "ring", ring)
    return asked, dispatched


async def _coverage_rows(db_session) -> list[Notification]:
    db_session.expire_all()
    return list((await db_session.scalars(
        select(Notification).where(Notification.category == "coverage")
    )).all())


@pytest.mark.asyncio
async def test_find_answers_the_board_the_roles_moved_to(api_client, db_session, gone):
    response = await api_client.post("/api/companies/hex-technologies/board/find", json={})
    assert response.status_code == 200
    assert response.json() == {"candidate": {
        "adapter": "ashby", "board_token": "hex", "board_region": None,
        "roles": 4, "shared": 3, "found_by": "name",
    }}
    # Reading only: nothing moved.
    row = await db_session.get(TrackedCompany, "hex-technologies")
    assert (row.adapter, row.board_token) == ("greenhouse", "hextechnologies")


@pytest.mark.asyncio
async def test_find_with_an_address_checks_that_address(api_client, gone):
    found = await api_client.post(
        "/api/companies/hex-technologies/board/find", json={"careers_url": "https://jobs.ashbyhq.com/hex"},
    )
    assert found.json()["candidate"]["found_by"] == "address"
    nothing = await api_client.post(
        "/api/companies/hex-technologies/board/find", json={"careers_url": "https://jobs.ashbyhq.com/nope"},
    )
    assert nothing.json() == {"candidate": None}


@pytest.mark.asyncio
async def test_moving_to_the_found_board_rebinds_retracts_the_notice_and_scans(api_client, db_session, gone):
    _asked, dispatched = gone
    response = await api_client.put(
        "/api/companies/hex-technologies/board", json={"adapter": "ashby", "board_token": "hex"},
    )
    assert response.status_code == 200, response.text
    assert (response.json()["adapter"], response.json()["board_token"]) == ("ashby", "hex")

    old, new = await _bindings(db_session, "hex-technologies")
    assert old.status == "retired" and new.closure_capability == "none"
    assert await _coverage_rows(db_session) == [], "the notice goes with the move"
    assert dispatched, "its first scan starts now"


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "status"), [
    # Never trusted from the request: a board that does not answer is refused.
    ({"adapter": "ashby", "board_token": "not-there"}, 409),
    ({"adapter": "no-such-family", "board_token": "hex"}, 400),
])
async def test_a_move_to_a_board_that_does_not_answer_changes_nothing(api_client, db_session, gone, body, status):
    response = await api_client.put("/api/companies/hex-technologies/board", json=body)
    assert response.status_code == status
    row = await db_session.get(TrackedCompany, "hex-technologies")
    assert (row.adapter, row.board_token) == ("greenhouse", "hextechnologies")
    assert len(await _coverage_rows(db_session)) == 1


@pytest.mark.asyncio
async def test_a_move_onto_a_denied_provider_is_refused(api_client, db_session, gone, monkeypatch):
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"ashby"}))
    response = await api_client.put(
        "/api/companies/hex-technologies/board", json={"adapter": "ashby", "board_token": "hex"},
    )
    assert response.status_code == 409
    assert (await db_session.get(TrackedCompany, "hex-technologies")).adapter == "greenhouse"


@pytest.mark.asyncio
async def test_stopping_following_retracts_the_notice(api_client, db_session, gone):
    response = await api_client.patch("/api/companies/hex-technologies", json={"enabled": False})
    assert response.status_code == 200
    assert await _coverage_rows(db_session) == []
