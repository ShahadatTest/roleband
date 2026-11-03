"""A company added before its connector existed.

The gap a batch of new catalog entries walks into: rows stored `pending`
before their connector existed. Adding a `CATALOG` entry makes
`connector_state` report **ready** (it reads the catalog) while the stored row
keeps `adapter=None, status="pending"`, unless something reads the catalog
back into it.

The cost is silent and points the wrong way. `get_active_targets` filters on
`if r.adapter`, so the company is dropped from every run with no error, no drift
alert and no binding, while its card invites the user to enable it. These tests
pin the upgrade AND its limits: the pass may only ever fill a hole, never
overrule a row that already answered the question.
"""

from __future__ import annotations

import pytest

from tracker.company_store import (
    ensure_catalog_connectors,
    get_active_targets,
)
from tracker.db.models import TrackedCompany


def _pending(slug: str, display: str, **over) -> TrackedCompany:
    fields = {
        "slug": slug,
        "display": display,
        "adapter": None,
        "board_token": None,
        "careers_url": f"https://{slug}.example/careers",
        "status": "pending",
        "enabled": False,
        "visible": True,
        "source": "catalog",
        "role_catalog_status": "pending",
    }
    return TrackedCompany(**{**fields, **over})


@pytest.mark.asyncio
async def test_a_pending_row_gains_the_connector_the_catalog_now_has(db_session):
    """`xai`: added from the discovery screen before a Greenhouse token for it
    existed."""
    db_session.add(_pending("xai", "SpaceXAI"))
    await db_session.flush()

    upgraded = await ensure_catalog_connectors(db_session)

    assert upgraded == ["xai"]
    row = await db_session.get(TrackedCompany, "xai")
    assert (row.adapter, row.board_token, row.status) == ("greenhouse", "xai", "active")


@pytest.mark.asyncio
async def test_the_upgraded_company_actually_reaches_the_roster(db_session):
    """The assertion that matters: a row `get_active_targets` drops would make
    enabling the company do nothing at all."""
    db_session.add(_pending("snowflake", "Snowflake", enabled=True))
    await db_session.flush()

    assert "snowflake" not in await get_active_targets(db_session)

    await ensure_catalog_connectors(db_session)

    targets = await get_active_targets(db_session)
    assert targets["snowflake"]["adapter"] == "ashby"
    assert targets["snowflake"]["board_token"] == "snowflake"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_pending_pwc_gains_its_verified_board_without_changing_follow_choice(db_session, enabled):
    db_session.add(_pending("pwc", "PwC", enabled=enabled))
    await db_session.flush()
    assert "pwc" not in await get_active_targets(db_session)

    assert await ensure_catalog_connectors(db_session) == ["pwc"]

    row = await db_session.get(TrackedCompany, "pwc")
    assert (row.adapter, row.board_token, row.status, row.enabled) == (
        "workday", "pwc.wd3.myworkdayjobs.com|US_Experienced_Careers", "active", enabled,
    )
    targets = await get_active_targets(db_session)
    assert ("pwc" in targets) is enabled


@pytest.mark.asyncio
async def test_a_regional_catalog_row_carries_its_region_through_the_upgrade(db_session):
    """The region rule survives the repair. A Lever tenant recorded without its
    region answers the same 404 as a wrong token, and the upgrade is exactly
    where that would be dropped."""
    db_session.add(_pending("palantir", "Palantir"))
    await db_session.flush()

    await ensure_catalog_connectors(db_session)

    row = await db_session.get(TrackedCompany, "palantir")
    assert (row.adapter, row.board_region) == ("lever", "global")


@pytest.mark.asyncio
async def test_acquiring_a_connector_is_not_consent_to_start_scraping(db_session):
    """`enabled` and `visible` are the operator's, and a table must not flip
    them. A company someone deliberately paused must not resume because its
    connector shipped."""
    db_session.add(_pending("nintendo", "Nintendo", enabled=False, visible=False))
    await db_session.flush()

    await ensure_catalog_connectors(db_session)

    row = await db_session.get(TrackedCompany, "nintendo")
    assert row.status == "active", "the connector exists now"
    assert (row.enabled, row.visible) == (False, False), "the choice was not ours to change"


@pytest.mark.asyncio
async def test_a_row_that_already_answered_is_never_overruled(db_session):
    """The pass fills a hole; it does not arbitrate. A URL-added company
    resolved its own board, and an operator who edited one outranks a table —
    so a row carrying ANY adapter is left exactly as it is, even when the
    catalog has a different token for that slug."""
    db_session.add(
        _pending(
            "snowflake", "Snowflake",
            adapter="greenhouse", board_token="hand-picked",
            status="active", source="url",
        )
    )
    await db_session.flush()

    assert await ensure_catalog_connectors(db_session) == []

    row = await db_session.get(TrackedCompany, "snowflake")
    assert (row.adapter, row.board_token) == ("greenhouse", "hand-picked")


@pytest.mark.asyncio
async def test_a_company_the_catalog_still_cannot_reach_stays_pending(db_session):
    """A planned company with no ATS we run has nothing to upgrade to, and must
    keep waiting rather than acquire a guess."""
    db_session.add(_pending("uber", "Uber"))
    await db_session.flush()

    assert await ensure_catalog_connectors(db_session) == []

    row = await db_session.get(TrackedCompany, "uber")
    assert (row.adapter, row.status) == (None, "pending")


@pytest.mark.asyncio
async def test_the_pass_is_idempotent(db_session):
    """It runs on every pipeline tick, every scheduler tick and every API
    start, so a second call must find nothing left to do."""
    db_session.add(_pending("epic-games", "Epic Games"))
    await db_session.flush()

    assert await ensure_catalog_connectors(db_session) == ["epic-games"]
    assert await ensure_catalog_connectors(db_session) == []


@pytest.mark.asyncio
async def test_the_role_inventory_is_rescanned_rather_than_kept(db_session):
    """Whatever `role_catalog_status` says, it describes a board we had no way
    to read. Carrying it forward would present a stale inventory as current."""
    db_session.add(
        _pending(
            "hugging-face", "Hugging Face",
            role_catalog_status="partial", role_catalog_error="no adapter",
        )
    )
    await db_session.flush()

    await ensure_catalog_connectors(db_session)

    row = await db_session.get(TrackedCompany, "hugging-face")
    assert row.adapter == "workable"
    assert (row.role_catalog_status, row.role_catalog_error) == ("pending", None)
