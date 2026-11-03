"""The curated list: which companies a user starts with.

Two contracts. `is_curated` is one rule over every kind of company row, and
the discovery payload carries it. `ensure_builtins` starts a fresh install on
the whole curated list, built-ins and catalog companies alike, and never
re-decides an existing row or adds to an install that has started.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tracker import company_discovery, company_store
from tracker.company_catalog import CATALOG
from tracker.company_discovery import COMPANY_DISCOVERY, build_company_discovery, is_curated
from tracker.config import COMPANIES
from tracker.db.models import TrackedCompany


def test_the_built_in_half_of_the_list_and_why_three_are_off_it():
    """A built-in is on the list only when the membership rule puts it there.

    Google (robots) and NVIDIA are walled: followed only when a user says so. Spotify is neither walled
    nor broken: it is simply not in its sectors' top three.
    """
    assert {slug for slug in COMPANIES if is_curated(slug)} == set(COMPANIES) - {
        "google", "nvidia", "spotify",
    }
    # Catalog rows carry the same flag.
    curated_catalog = [slug for slug in CATALOG if slug not in COMPANIES and is_curated(slug)]
    assert len(curated_catalog) == 29


def test_a_catalog_row_is_curated_only_by_its_own_key(monkeypatch):
    monkeypatch.setitem(CATALOG, "example-co", {"display": "Example", "adapter": "greenhouse",
                                                "board_token": "example", "curated": True})
    monkeypatch.setitem(CATALOG, "other-co", {"display": "Other", "adapter": "greenhouse",
                                              "board_token": "other"})
    assert is_curated("example-co") is True
    assert is_curated("other-co") is False


def test_a_parked_or_unknown_company_is_never_curated(monkeypatch):
    monkeypatch.setitem(CATALOG, "meta", {"display": "Meta", "adapter": "greenhouse",
                                          "board_token": "meta", "curated": True})
    assert is_curated("meta") is False, "parked beats any curated key: the list promises scannable companies"
    assert is_curated("some-url-added-co") is False


def test_discovery_carries_the_flag_for_catalog_and_url_added_rows():
    url_added = TrackedCompany(slug="acme", display="Acme", adapter="greenhouse", status="active",
                               enabled=True, visible=True, source="url")
    state = build_company_discovery(tracked={"acme": url_added})
    by_slug = {company["slug"]: company for company in state["companies"]}
    assert by_slug["apple"]["curated"] is True
    assert by_slug["google"]["curated"] is False, "walled is never curated"
    assert by_slug["stripe"]["curated"] is True, "top 3 in fintech (Q3)"
    assert by_slug["coinbase"]["curated"] is False, "8th in fintech"
    assert by_slug["acme"]["curated"] is False


class _CaptureSession:
    def __init__(self):
        self.executed = []

    async def execute(self, stmt):
        if stmt.is_select:
            # A fresh install: no row, and no stored adapter.
            return SimpleNamespace(all=list, first=lambda: None)
        self.executed.append(stmt)


def test_a_fresh_install_follows_curated_built_ins_and_no_other(monkeypatch):
    monkeypatch.setitem(COMPANIES, "uncurated-co", {"display": "Uncurated", "adapter": "greenhouse",
                                                    "enabled": True, "curated": False})
    session = _CaptureSession()
    asyncio.run(company_store.ensure_builtins(session))

    inserted = {}
    for stmt in session.executed:
        params = stmt.compile().params
        if params["slug"] not in COMPANIES:
            continue
        inserted[params["slug"]] = params["enabled"]
        # Insert-only: the conflict branch must never re-decide what a user follows,
        # which is what keeps an existing install's follows across a membership change.
        conflict = str(stmt.compile()).split("ON CONFLICT", 1)[1]
        assert "enabled" not in conflict
    assert inserted["uncurated-co"] is False
    assert inserted["apple"] is True
    # Walled: a fresh install never follows a wall nobody consented to.
    assert inserted["google"] is False


async def _followed(session) -> set[str]:
    rows = await session.execute(select(TrackedCompany.slug).where(TrackedCompany.enabled.is_(True)))
    return {slug for (slug,) in rows}


@pytest.mark.asyncio
async def test_a_fresh_install_starts_on_the_whole_curated_list(db_session):
    """The list is what a new install follows, catalog companies included: the
    built-ins alone are six of its thirty-five."""
    await company_store.ensure_builtins(db_session)
    await db_session.commit()

    curated = {slug for slug in COMPANY_DISCOVERY if is_curated(slug)}
    assert await _followed(db_session) == curated
    assert "stripe" in curated and "stripe" not in COMPANIES
    # Off the list: no row at all, so the company stays a choice, not a pause.
    assert await db_session.get(TrackedCompany, "coinbase") is None
    stripe = await db_session.get(TrackedCompany, "stripe")
    assert (stripe.status, stripe.adapter, stripe.source) == ("active", "greenhouse", "catalog")


@pytest.mark.asyncio
async def test_an_install_that_has_started_never_gains_a_follow(db_session):
    """Once any row exists, a curated company with no row is one the person has
    not chosen. Neither a second call nor a later start adds it, and an
    unfollow made after the first start stays."""
    await company_store.ensure_builtins(db_session)
    await db_session.commit()
    stripe = await db_session.get(TrackedCompany, "stripe")
    stripe.enabled = False
    await db_session.delete(await db_session.get(TrackedCompany, "datadog"))
    await db_session.commit()

    await company_store.ensure_builtins(db_session)
    await db_session.commit()

    assert (await db_session.get(TrackedCompany, "stripe", populate_existing=True)).enabled is False
    assert await db_session.get(TrackedCompany, "datadog") is None


@pytest.mark.asyncio
async def test_an_existing_install_without_catalog_rows_is_left_as_it_is(db_session):
    """An install from before the catalog joined the list holds its built-ins
    only. It has started, so it keeps exactly those."""
    db_session.add(TrackedCompany(slug="apple", display="Apple", adapter="apple", status="active",
                                  enabled=True, visible=True, source="builtin"))
    await db_session.commit()

    await company_store.ensure_builtins(db_session)
    await db_session.commit()

    assert not (await _followed(db_session) - set(COMPANIES))
    assert await db_session.get(TrackedCompany, "stripe") is None


def test_is_curated_is_the_one_rule_discovery_uses(monkeypatch):
    # A second reading of membership (say, the blueprint read directly) would let
    # the payload and the seeding disagree; flipping the rule must move both.
    monkeypatch.setattr(company_discovery, "is_curated", lambda slug, tracked=None: slug == "stripe")
    state = build_company_discovery(tracked={})
    curated = {company["slug"] for company in state["companies"] if company["curated"]}
    assert curated == {"stripe"}


# --------------------------------------------------------------------------- #
# The membership rule itself: top 3 per sector, plus
# FAANG without Google.
# --------------------------------------------------------------------------- #


def _eligible(slug: str) -> bool:
    """Curatable at all: a curated company is followed without anyone being
    asked, so it must be collectable now, ask nothing of the user (no wall),
    and not be one left to the user's choice."""
    from tracker.company_discovery import (
        _PARKED,
        collecting_provider,
        company_wall,
        connector_state,
    )
    from tracker.source_review import user_directed_source

    provider = collecting_provider(slug)
    return (
        slug not in _PARKED
        and company_wall(slug) is None
        and not (provider and user_directed_source(provider, company=slug))
        and connector_state(slug) in {"live", "ready", "family"}
    )


def test_the_curated_list_is_the_owners_rule_applied_to_todays_catalog():
    """The first three ELIGIBLE companies of each sector, in the order the
    sector itself recommends, plus every FAANG company except Google.

    Derived here rather than copied, so a catalog change that moves a sector's
    order — or walls one of its three — fails until the flags are re-decided.
    An ineligible company is skipped and the next one takes the slot: a list
    that promised a company RoleBand cannot scan without asking would be a list
    the user did not get.
    """
    from tracker.company_discovery import _SECTOR_COMPANIES, SECTORS

    expected: set[str] = set()
    for sector in SECTORS:
        eligible = [c.slug for c in _SECTOR_COMPANIES[sector.slug] if _eligible(c.slug)]
        if sector.slug == "faang":
            expected.update(slug for slug in eligible if slug != "google")
        else:
            expected.update(eligible[:3])

    assert {slug for slug in COMPANY_DISCOVERY if is_curated(slug)} == expected
    assert len(expected) == 35, "35 companies, Microsoft counted once for two sectors"


def test_the_rule_excludes_what_the_user_must_be_asked_about():
    """The three exclusions, each for its own reason and each load-bearing."""
    # Walled by robots and by choice: both are followed only when the user
    # says so.
    assert not is_curated("google") and not is_curated("nvidia")
    # Parked: the list promises companies RoleBand can scan.
    assert not is_curated("tesla")
    # Planned: no connector, so following it would seed a row that never scans.
    assert not is_curated("uber")
    # And a live connector outside the rule is simply not on the list.
    assert not is_curated("spotify"), "Spotify is 8th in consumer, not top 3"
