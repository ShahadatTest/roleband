"""Every other company RoleBand can scan: find one by name, follow it.

Two contracts. Search answers a name with the few companies it could mean —
the prefix before the substring, punctuation and case set aside, never the
whole set for a letter. And a directory company followed by name becomes an
ordinary scannable company, drawn apart from the ones a user added by URL.

The data file is held to what makes a row safe to offer: no slug that is
already one of ours, no board we already collect, and every row reachable by
the adapter it names.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.api_errors import said
from tests.company_contract_seed import seed_company_contract
from tracker import company_directory
from tracker.company_catalog import CATALOG
from tracker.company_directory import (
    DIRECTORY_SOURCES,
    DirectoryCompany,
    directory,
    search_directory,
)
from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.company_store import resolve_company
from tracker.config import COMPANIES
from tracker.connectors import ADAPTER_REGISTRY

pytestmark = pytest.mark.usefixtures("no_escape")


def _company(rank, slug, display, adapter="greenhouse", token=None, named_by="board", region=None):
    return DirectoryCompany(slug=slug, display=display, named_by=named_by, adapter=adapter,
                            board_token=token or slug, board_region=region, rank=rank)


_FIXTURE = {c.slug: c for c in [
    _company(0, "spacex", "SpaceX"),
    _company(1, "crusoe", "Crusoe", adapter="ashby", token="Crusoe", named_by="address"),
    _company(2, "space-ape-games", "Space Ape Games", adapter="workable"),
    _company(3, "outer-space-labs", "Outer Space Labs", adapter="ashby", named_by="address"),
    _company(4, "wypoon", "Wypoon", adapter="lever", region="eu", named_by="address"),
    _company(5, "pantheon", "Pantheon Ventures Careers", token="pantheonpublic"),
]}


@pytest.fixture
def fixture_directory(monkeypatch):
    monkeypatch.setattr(company_directory, "directory", lambda: _FIXTURE)
    return _FIXTURE


# --- search -------------------------------------------------------------------


def test_a_name_that_starts_with_the_query_comes_before_one_that_contains_it(fixture_directory):
    hits, total = search_directory("space")
    assert [h.slug for h in hits] == ["spacex", "space-ape-games", "outer-space-labs"]
    assert total == 3


@pytest.mark.parametrize("query", ["SPACE X", "space-x", "Space.X"])
def test_case_spaces_and_punctuation_are_set_aside(fixture_directory, query):
    assert [h.slug for h in search_directory(query)[0]] == ["spacex"]


def test_the_board_address_is_searched_too(fixture_directory):
    assert [h.slug for h in search_directory("pantheonpub")[0]] == ["pantheon"]


@pytest.mark.parametrize("query", ["", " ", "s", "-"])
def test_under_two_characters_matches_nothing_rather_than_most_of_the_set(fixture_directory, query):
    assert search_directory(query) == ([], 0)


def test_the_count_is_every_match_while_the_list_is_capped(fixture_directory):
    hits, total = search_directory("a", limit=2)  # one letter: nothing
    assert (hits, total) == ([], 0)
    hits, total = search_directory("sp", limit=2)
    assert len(hits) == 2 and total == 3


def test_a_query_matching_nothing_is_an_empty_answer_not_an_error(fixture_directory):
    assert search_directory("zzzz") == ([], 0)


# --- following one ------------------------------------------------------------


def test_a_directory_company_resolves_to_its_own_board(fixture_directory):
    fields = resolve_company(catalog_slug="wypoon")
    assert fields == {
        "slug": "wypoon", "display": "Wypoon", "adapter": "lever", "board_token": "wypoon",
        "board_region": "eu", "careers_url": None, "status": "active", "source": "directory",
    }


def test_a_catalog_slug_still_resolves_from_the_catalog_first(fixture_directory, monkeypatch):
    """Precedence: the catalog is a decision, the directory is not."""
    monkeypatch.setattr(company_directory, "directory", lambda: {
        **_FIXTURE, "stripe": _company(9, "stripe", "Stripe Imposter", token="stripe-imposter")})
    assert resolve_company(catalog_slug="stripe")["source"] == "catalog"


@pytest_asyncio.fixture
async def seeded(db_session, monkeypatch, no_escape, fixture_directory):
    await seed_company_contract(db_session)


@pytest.mark.asyncio
async def test_search_over_http_says_which_matches_are_already_followed(api_client, seeded):
    before = (await api_client.get("/api/companies/directory", params={"q": "space"})).json()
    assert before["size"] == len(_FIXTURE) and before["match_count"] == 3
    assert [(m["slug"], m["tracked"], m["enabled"]) for m in before["matches"]] == [
        ("spacex", False, False), ("space-ape-games", False, False), ("outer-space-labs", False, False)]

    applied = await api_client.put("/api/companies/selection", json={"follow": ["spacex"]})
    assert applied.status_code == 200, applied.text

    after = (await api_client.get("/api/companies/directory", params={"q": "space"})).json()
    assert after["matches"][0] == {"slug": "spacex", "display": "SpaceX", "named_by": "board",
                                   "tracked": True, "enabled": True}


@pytest.mark.asyncio
async def test_a_followed_directory_company_is_drawn_apart_from_url_additions(api_client, seeded):
    body = (await api_client.put("/api/companies/selection",
                                 json={"follow": ["crusoe"]})).json()
    companies = {c["slug"]: c for c in body["companies"]}
    crusoe = companies["crusoe"]
    assert (crusoe["directory"], crusoe["sectors"], crusoe["connector_state"], crusoe["enabled"]) == (
        True, [], "active", True)
    # The URL-added company in the seed stays a URL addition.
    assert companies["acme-labs"]["directory"] is False
    # And nothing from the recommended list is ever marked directory.
    assert not any(c["directory"] for c in body["companies"] if c["slug"] in COMPANY_DISCOVERY)


@pytest.mark.asyncio
async def test_a_slug_in_neither_list_is_still_refused(api_client, seeded):
    response = await api_client.put("/api/companies/selection", json={"follow": ["not-a-company"]})
    assert response.status_code == 400
    assert said(response.json()) == {"detail": "unknown companies: not-a-company"}


# --- the data file ------------------------------------------------------------


def test_the_directory_file_offers_only_new_companies_on_boards_we_can_read():
    rows = directory()
    assert len(rows) > 1000, "the built directory ships with the code"
    reserved = set(COMPANY_DISCOVERY) | set(CATALOG) | set(COMPANIES)
    assert not reserved & set(rows), "a directory slug shadows a company we already have"
    held = {(entry["adapter"], entry["board_token"].casefold()) for entry in CATALOG.values()}
    for row in rows.values():
        assert row.named_by in {"board", "address"}
        assert (row.adapter, row.board_token.casefold()) not in held, row.slug
        cls = ADAPTER_REGISTRY.get(row.adapter)
        assert cls is not None and getattr(cls, "board_probe", None) is not None, row.adapter
    assert len({r.slug for r in rows.values()}) == len(rows)


def test_directory_sources_are_what_the_store_writes():
    assert DIRECTORY_SOURCES == {"directory", "directory-set"}
