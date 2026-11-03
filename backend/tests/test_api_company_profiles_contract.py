"""The company-profile routes' response contract.

`tracker/api/schemas/companies.py` declares what `/api/company-profiles*` and the
company card send. These tests hold it to its sources:

1. **Vocabularies**: data health, freshness and review reasons against the
   resolver; the shown fields against the profile store; price ranges against
   the router's table.
2. **Reads over real HTTP** against profiles built by the real claim store and
   resolver (`tests/company_profiles_contract_seed.py`): the list's visibility,
   ladder counts and quotes; a profile's provenance, conflicts, candidates and
   worklist in each reason; the ladder, benefits and offices; every claim; price
   windows; and the card with and without a profile.
3. **Writes**: a pin and an unpin read back through the profile, the list, the
   claims and the card; each refusal changing nothing.
4. **Drift**: a key a builder adds or drops fails the response; a stored conflict
   keeps a key its model does not name and fails without one the client reads.
5. **One source**: with the plugin on, company size, the ladder and
   benefits are the plugin's alone, a company it has not read shows none of
   ours in their place, identity stays ours, a pin on its field is refused, and
   turning it off brings every profile back exactly as ours was.

`pin_profile_clock` freezes the clock these routes read; `no_escape` guards
every test.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import select

from tests.company_profiles_contract_seed import (
    NOW,
    PLUGIN,
    PLUGIN_ATTRIBUTION,
    PLUGIN_NAME,
    TODAY,
    install_plugin,
    pin_profile_clock,
    seed_company_profiles,
)
from tests.factories import make_company
from tracker.api.routers import companies as router
from tracker.api.schemas import companies as contract
from tracker.db.models import CompanyProfile
from tracker.levels.pay import profile_offer
from tracker.prices.provider import ATTRIBUTION_FIXTURE
from tracker.profiles import resolve
from tracker.profiles import store as profile_store

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

P = "/api/company-profiles"


@pytest_asyncio.fixture
async def profiles(api_client, db_session, monkeypatch, no_escape):
    """Our data, with the plugin's rows and claims stored but no plugin installed:
    every profile reads ours alone (`tests/test_plugin_registry.py`)."""
    pin_profile_clock(monkeypatch)
    await seed_company_profiles(db_session)


@pytest_asyncio.fixture
async def plugin_on(profiles, db_session):
    """The same data with the plugin on, having read google whole."""
    await install_plugin(db_session)


def _fields(model) -> list[str]:
    return list(model.model_fields)


def _stamp(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _zulu(days_ago: int) -> str:
    return _stamp(days_ago).replace("+00:00", "Z")


async def _call(api_client, method: str, path: str, json=None, status: int = 200) -> dict:
    response = await api_client.request(method, path, json=json)
    assert response.status_code == status, response.text
    return response.json()


def _candidate(source: str, rank: int, value, days_ago: int) -> dict:
    """A source's claim: its code, which the dashboard names."""
    return {"source": source, "rank": rank, "value": value, "observed_at": _stamp(days_ago)}


# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def test_each_literal_is_the_vocabulary_it_mirrors():
    assert set(get_args(contract.DataHealth)) == set(resolve._HEALTH_SEVERITY)
    assert set(get_args(contract.Freshness)) == {resolve.FRESH, resolve.AGING, resolve.STALE}
    assert set(get_args(contract.ReviewReason)) == {resolve.CONFLICT, resolve.STALE, resolve.MISSING}
    assert set(get_args(contract.PriceRange)) == set(router._PRICE_RANGES)
    shown = list(get_args(contract.ShownProfileField))
    assert _fields(contract.CompanyProfileFields) == shown
    assert set(shown) <= set(profile_store.PROFILE_FIELDS)
    # A required field the panel did not show could be `missing` with nowhere to fix it.
    assert set(profile_store.REQUIRED_FIELDS) | {"ticker"} <= set(shown)


def test_built_shapes_forbid_unknown_keys_and_a_stored_conflict_keeps_them():
    d1 = [
        contract.CompanyProfileSummary, contract.CompanyProfileListResponse, contract.ProfileFieldCandidate,
        contract.ProfileFieldDetail, contract.CompanyProfileFields, contract.ProfileReviewItem,
        contract.CompanyCompRung, contract.CompanyBenefitItem, contract.CompanyBenefitGroup,
        contract.CompanyLocationRow, contract.CompanyProfileDetailResponse, contract.ProfileHealth,
        contract.CompanyProfileFieldWrite, contract.CompanyClaim, contract.CompanyClaimsResponse,
        contract.PriceQuote, contract.PriceBarRow, contract.CompanyPricesResponse, contract.CompanyCardResponse,
    ]
    assert [m.__name__ for m in d1 if m.model_config.get("extra") != "forbid"] == []
    assert contract.ProfileFieldConflict.model_config.get("extra") == "allow"


# --------------------------------------------------------------------------- #
# 2. Reads
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_list_serves_visible_profiles_with_their_reference_ladder_and_latest_quote(api_client, profiles):
    body = await _call(api_client, "GET", P)
    assert list(body) == _fields(contract.CompanyProfileListResponse)
    assert body["attribution"] is None  # ours needs no credit
    assert all(list(item) == _fields(contract.CompanyProfileSummary) for item in body["items"])
    items = {item["slug"]: item for item in body["items"]}
    assert list(items) == ["anthropic", "google", "reddit"]  # by slug; hidden-co is not visible

    # Our dataset holds no stored ladder: the plugin's google rungs are not read.
    assert {slug: item["mapped_levels"] for slug, item in items.items()} == {"anthropic": 0, "google": 0, "reddit": 0}
    assert {slug: item["headcount"] for slug, item in items.items()} == {
        "anthropic": 1100, "google": 182502, "reddit": 2013}
    assert {k: items["google"][k] for k in ("price", "change_pct", "currency", "price_as_of")} == {
        "price": 213.95, "change_pct": -0.48, "currency": "USD",
        "price_as_of": (TODAY - timedelta(days=1)).isoformat(),
    }
    # Conflicting fields in the order `field_meta` stores its keys (Postgres serves shorter JSONB keys first).
    assert (items["reddit"]["data_health"], items["reddit"]["conflict_fields"]) == ("missing", ["ticker", "is_public"])
    # A pinned field that others dispute is still a conflict field, but not a health problem.
    assert (items["anthropic"]["data_health"], items["anthropic"]["conflict_fields"]) == ("ok", ["headcount"])
    assert items["anthropic"]["price"] is None and items["anthropic"]["price_as_of"] is None
    # Grouping inputs: each company's sectors, and whether the atlas researched it.
    assert {slug: (item["sectors"], item["in_dataset"]) for slug, item in items.items()} == {
        "anthropic": (["ai"], True), "google": (["faang"], True), "reddit": (["consumer"], True),
    }
    assert body["sectors"][:3] == ["faang", "ai", "technology"]  # Settings' order, FAANG first


@pytest.mark.asyncio
async def test_the_list_says_each_company_s_sectors_and_whether_the_dataset_has_it(
    api_client, db_session, profiles
):
    """A company in two sectors carries both, in sector order; one in a single
    sector carries that one; one added by its careers page is in neither."""
    db_session.add_all([
        make_company("microsoft", "Microsoft"),
        make_company("flexport", "Flexport"),
        make_company("plain-co", "Plain Co", source="url"),
        CompanyProfile(slug="microsoft", display_name="Microsoft"),
        CompanyProfile(slug="flexport", display_name="Flexport"),
        CompanyProfile(slug="plain-co", display_name="Plain Co"),
    ])
    await db_session.commit()
    items = {item["slug"]: item for item in (await _call(api_client, "GET", P))["items"]}
    assert {slug: (items[slug]["sectors"], items[slug]["in_dataset"]) for slug in ("microsoft", "flexport", "plain-co")} == {
        "microsoft": (["technology", "gaming"], True),
        "flexport": (["technology"], True),
        "plain-co": ([], False),
    }


@pytest.mark.asyncio
async def test_hiding_a_company_removes_it_from_the_list_but_not_from_its_own_page(api_client, db_session, profiles):
    db_session.add(make_company("google", "Google", visible=False))
    await db_session.commit()
    assert [item["slug"] for item in (await _call(api_client, "GET", P))["items"]] == ["anthropic", "reddit"]
    assert (await _call(api_client, "GET", f"{P}/hidden-co"))["slug"] == "hidden-co"
    assert (await _call(api_client, "GET", f"{P}/google"))["slug"] == "google"


@pytest.mark.asyncio
async def test_a_healthy_profile_carries_provenance_candidates_ladder_benefits_and_offices(api_client, profiles):
    body = await _call(api_client, "GET", f"{P}/google")
    assert list(body) == _fields(contract.CompanyProfileDetailResponse)
    assert list(body["fields"]) == list(get_args(contract.ShownProfileField))
    assert all(list(f) == _fields(contract.ProfileFieldDetail) for f in body["fields"].values())
    assert (body["data_health"], body["needs_review"]) == ("ok", [])
    # RoleBand names its own sources itself; no plugin answers.
    assert body["source_names"] == {}
    ours = {"plugin": None, "plugin_name": None, "covered": True}
    assert body["sources"] == {"pay": ours, "benefits": ours, "company_size": ours}

    # A lower-trust headcount within tolerance is offered as a candidate, never
    # raised as a conflict; the plugin's stored claim is not among them.
    assert body["fields"]["headcount"] == {
        "value": 182502, "source": "reported", "observed_at": _stamp(10),
        "freshness": "fresh", "is_manual": False, "conflicts": [],
        "candidates": [
            _candidate("reported", 55, 182502, 10),
            _candidate("blueprint", 30, 190000, 5),
        ],
        "editable": True,
        "answered_by": None,
    }
    assert (body["fields"]["ticker"]["value"], body["fields"]["ticker"]["source"]) == ("GOOG", "blueprint")
    assert (body["fields"]["hq_city"]["value"], body["fields"]["hq_city"]["source"]) == ("Mountain View", "roleband")

    # Our dataset holds no stored ladder; the plugin's is not read while it is off.
    assert body["comp_levels"] == []
    # Benefits from our dataset alone; never a summed total.
    items = [i for group in body["benefits"] for i in group["items"]]
    assert items, "RoleBand's dataset answers google's benefits"
    assert all(list(i) == _fields(contract.CompanyBenefitItem) for i in items)
    assert all(i["builtin"] and i["provider"] == "builtin" and i["kind"] in ("dataset", "employer") for i in items)
    categories = [g["category"] for g in body["benefits"]]
    assert len(categories) == len(set(categories))
    # Nothing is reviewed yet: the dataset holds no reviewed record.
    assert {i["reviewed"] for i in items} == {False}
    assert "benefits_value_usd" not in body["fields"]
    assert "benefits_total_usd" not in body

    # How offers are built: the atlas's facts, each with who states them.
    assert body["offer_policy"] == profile_offer("google")
    assert body["offer_policy"]["facts"], "the atlas researched google"
    assert all(list(f) == _fields(contract.CompanyOfferFact) for f in body["offer_policy"]["facts"])

    # Offices from open in-scope roles only, busiest first, the HQ marked by its city.
    assert body["open_roles"] == 4
    assert [(loc["city"], loc["open_count"], loc["is_hq"]) for loc in body["locations"]] == [
        ("Mountain View, CA", 2, True), ("London, UK", 1, False), ("New York, NY", 1, False),
        ("Sunnyvale, CA", 1, False),
    ]
    assert all(list(loc) == _fields(contract.CompanyLocationRow) for loc in body["locations"])
    assert all(loc["country"] is None or loc["country"] in loc["groups"] for loc in body["locations"])
    assert body["attribution"] is None


@pytest.mark.asyncio
async def test_a_disputed_profile_lists_its_worklist_conflicts_then_stale_then_missing(api_client, profiles):
    body = await _call(api_client, "GET", f"{P}/reddit")
    assert body["data_health"] == "missing"
    assert [(i["field"], i["reason"], i["current"]) for i in body["needs_review"]] == [
        ("is_public", "conflict", True), ("ticker", "conflict", "RDDT"),
        ("headcount", "stale", 2013), ("equity_vehicle", "missing", None),
    ]
    ticker = body["needs_review"][1]
    assert ticker["suggestion"] == _candidate("sec_edgar", 80, "RDDT", 20)
    assert ticker["candidates"] == [ticker["suggestion"], _candidate("reported", 55, None, 20)]
    assert (body["needs_review"][3]["suggestion"], body["needs_review"][3]["candidates"]) == (None, [])
    # The conflict as the resolver stored it, keys in the order Postgres serves them.
    assert body["fields"]["ticker"]["conflicts"] == [
        {"value": None, "source": "reported", "observed_at": _stamp(20)}
    ]
    assert list(body["fields"]["ticker"]["conflicts"][0]) == ["value", "source", "observed_at"]
    assert body["fields"]["headcount"]["freshness"] == "stale"
    stored = [i for group in body["benefits"] for i in group["items"] if not i["builtin"]]
    assert (body["comp_levels"], stored) == ([], [])


@pytest.mark.asyncio
async def test_a_company_the_atlas_has_not_researched_has_no_offer_policy(api_client, profiles):
    """Not researched is not "searched and found nothing": the one is null, the
    other a list of facts with null values."""
    body = await _call(api_client, "GET", f"{P}/hidden-co")
    assert body["offer_policy"] is None


@pytest.mark.asyncio
async def test_a_pinned_field_keeps_its_dispute_but_leaves_the_worklist(api_client, profiles):
    body = await _call(api_client, "GET", f"{P}/anthropic")
    headcount = body["fields"]["headcount"]
    assert (headcount["value"], headcount["source"], headcount["is_manual"]) == (1100, "manual", True)
    assert headcount["conflicts"] == [
        {"value": 45, "source": "reported", "observed_at": _stamp(70)}
    ]
    assert (body["data_health"], body["needs_review"]) == ("ok", [])
    assert body["fields"]["equity_vehicle"]["freshness"] == "aging"
    # A field no source asserts: every provenance key null, nothing to choose from.
    assert body["fields"]["ticker"] == {
        "value": None, "source": None, "observed_at": None, "freshness": None,
        "is_manual": False, "conflicts": [], "candidates": [], "editable": True, "answered_by": None,
    }
    assert (body["comp_notes"], body["open_roles"], body["locations"]) == (
        "Options with a ten-year exercise window.", 0, [],
    )
    await _call(api_client, "GET", f"{P}/nosuch", status=404)


@pytest.mark.asyncio
async def test_claims_are_every_source_s_word_grouped_by_field_newest_first(api_client, profiles):
    body = await _call(api_client, "GET", f"{P}/google/claims")
    assert list(body) == _fields(contract.CompanyClaimsResponse)
    assert all(list(c) == _fields(contract.CompanyClaim) for c in body["claims"])
    headcount = [c for c in body["claims"] if c["field"] == "headcount"]
    assert headcount == [
        {"field": "headcount", "value": 190000, "source": "blueprint",
         "rank": 30, "observed_at": _zulu(5)},
        {"field": "headcount", "value": 182502, "source": "reported",
         "rank": 55, "observed_at": _zulu(10)},
    ]
    assert [c["field"] for c in body["claims"]] == sorted(c["field"] for c in body["claims"])
    assert len(body["claims"]) == 12, "ours only: the plugin's two claims are not read"
    # An unknown company has no claims, rather than no page.
    assert await _call(api_client, "GET", f"{P}/nosuch/claims") == {"slug": "nosuch", "claims": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "answered", "days"),
    [("", "3m", [60, 2, 1]), ("?range=1m", "1m", [2, 1]), ("?range=6m", "6m", [120, 60, 2, 1]),
     ("?range=1y", "1y", [200, 120, 60, 2, 1]), ("?range=5y", "3m", [60, 2, 1])],
    ids=["default", "1m", "6m", "1y", "unknown_range"],
)
async def test_prices_serve_the_window_asked_for_oldest_first(api_client, profiles, query, answered, days):
    body = await _call(api_client, "GET", f"{P}/google/prices{query}")
    assert list(body) == _fields(contract.CompanyPricesResponse)
    assert (body["slug"], body["range"], body["currency"]) == ("google", answered, "USD")
    assert [b["date"] for b in body["bars"]] == [(TODAY - timedelta(days=d)).isoformat() for d in days]
    assert body["latest"] == {
        "ticker": "GOOG", "price": 213.95, "currency": "USD", "change_abs": -1.03, "change_pct": -0.48,
        "as_of": (TODAY - timedelta(days=1)).isoformat(),
    }
    # The seeded bars are the offline sample, so the credit says so: it names the
    # bars shown, never the configured provider.
    assert body["attribution"] == ATTRIBUTION_FIXTURE
    assert body["feed_configured"] is False


@pytest.mark.asyncio
async def test_a_bar_without_a_range_and_a_quote_without_a_move_keep_their_nulls(api_client, profiles):
    google = await _call(api_client, "GET", f"{P}/google/prices?range=1m")
    assert google["bars"][0] == {
        "date": (TODAY - timedelta(days=2)).isoformat(), "open": None, "high": None, "low": None,
        "close": 214.98, "volume": None,
    }
    reddit = await _call(api_client, "GET", f"{P}/reddit/prices?range=1y")
    assert (reddit["latest"]["change_abs"], reddit["latest"]["change_pct"]) == (None, None)
    # A private company is a valid, price-less profile: empty, not 404.
    anthropic = await _call(api_client, "GET", f"{P}/anthropic/prices")
    assert (anthropic["latest"], anthropic["bars"], anthropic["currency"]) == (None, [], "USD")
    assert anthropic["attribution"] is None, "no prices shown, nobody to credit"
    await _call(api_client, "GET", f"{P}/nosuch/prices", status=404)


@pytest.mark.asyncio
async def test_the_card_answers_with_or_without_a_profile(api_client, profiles):
    google = await _call(api_client, "GET", "/api/companies/google/card")
    assert list(google) == _fields(contract.CompanyCardResponse)
    assert {k: google[k] for k in ("display_name", "has_profile", "is_public", "ticker", "open_roles", "top_cities",
                                   "price", "price_as_of")} == {
        "display_name": "Google", "has_profile": True, "is_public": True, "ticker": "GOOG", "open_roles": 4,
        "top_cities": ["Mountain View, CA", "London, UK", "New York, NY"], "price": 213.95,
        "price_as_of": (TODAY - timedelta(days=1)).isoformat(),
    }
    assert await _call(api_client, "GET", "/api/companies/acme-labs/card") == {
        "slug": "acme-labs", "display_name": "Acme Labs", "logo_url": None, "brand_color": None, "ticker": None,
        "is_public": False, "has_profile": False, "open_roles": 1, "unfollowed": False,
        "top_cities": ["Austin, TX"], "price": None,
        "change_pct": None, "currency": None, "price_as_of": None,
    }
    reddit = await _call(api_client, "GET", "/api/companies/reddit/card")
    assert (reddit["price"], reddit["change_pct"]) == (168.4, None)


# --------------------------------------------------------------------------- #
# 3. Writes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_pin_settles_the_field_everywhere_it_is_read_and_an_unpin_restores_resolution(api_client, profiles):
    pinned = await _call(api_client, "PATCH", f"{P}/reddit", {"field": "equity_vehicle", "value": "rsu"})
    assert list(pinned) == _fields(contract.CompanyProfileFieldWrite)
    assert pinned == {"slug": "reddit", "field": "equity_vehicle", "health": {
        # A stale headcount is no review work: the field is optional.
        "status": "conflict", "missing": [], "conflicts": ["is_public", "ticker"], "stale": [],
        "needs_review": ["is_public", "ticker"],
    }}
    detail = await _call(api_client, "GET", f"{P}/reddit")
    vehicle = detail["fields"]["equity_vehicle"]
    assert (vehicle["value"], vehicle["is_manual"], vehicle["observed_at"]) == ("rsu", True, _stamp(0))
    assert "equity_vehicle" not in [i["field"] for i in detail["needs_review"]]
    listed = {i["slug"]: i for i in (await _call(api_client, "GET", P))["items"]}["reddit"]
    assert (listed["equity_vehicle"], listed["data_health"]) == ("rsu", "conflict")
    claims = (await _call(api_client, "GET", f"{P}/reddit/claims"))["claims"]
    assert {"field": "equity_vehicle", "value": "rsu", "source": "manual",
            "rank": 100, "observed_at": _zulu(0)} in claims

    unpinned = await _call(api_client, "DELETE", f"{P}/reddit/manual/equity_vehicle")
    assert unpinned["health"]["status"] == "missing"
    assert unpinned["health"]["needs_review"] == ["equity_vehicle", "is_public", "ticker"]
    after = await _call(api_client, "GET", f"{P}/reddit")
    assert (after["fields"]["equity_vehicle"]["value"], after["data_health"]) == (None, "missing")
    assert all(c["source"] != "manual" for c in (await _call(api_client, "GET", f"{P}/reddit/claims"))["claims"])


@pytest.mark.asyncio
async def test_unpinning_falls_back_to_the_best_remaining_source(api_client, profiles):
    await _call(api_client, "DELETE", f"{P}/anthropic/manual/headcount")
    headcount = (await _call(api_client, "GET", f"{P}/anthropic"))["fields"]["headcount"]
    assert {k: headcount[k] for k in ("value", "source", "freshness", "is_manual", "conflicts")} == {
        "value": 45, "source": "reported", "freshness": "aging", "is_manual": False, "conflicts": [],
    }


@pytest.mark.asyncio
async def test_a_pinned_identity_field_reaches_the_list_and_the_card(api_client, profiles):
    written = await _call(api_client, "PATCH", f"{P}/google", {"field": "display_name", "value": "Alphabet"})
    assert written["health"]["status"] == "ok"
    assert (await _call(api_client, "GET", f"{P}/google"))["display_name"] == "Alphabet"
    assert {i["slug"]: i for i in (await _call(api_client, "GET", P))["items"]}["google"]["display_name"] == "Alphabet"
    assert (await _call(api_client, "GET", "/api/companies/google/card"))["display_name"] == "Alphabet"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("PATCH", f"{P}/reddit", {"field": "salary", "value": 1}, 400),
        ("PATCH", f"{P}/nosuch", {"field": "ticker", "value": "NOPE"}, 404),
        ("PATCH", f"{P}/reddit", {"value": "rsu"}, 422),
        ("DELETE", f"{P}/nosuch/manual/ticker", None, 404),
        # A nullable column the resolver does not own: unpinning it would
        # blank it with no claim to bring it back.
        ("DELETE", f"{P}/reddit/manual/comp_notes", None, 400),
    ],
    ids=["unknown_field", "unknown_company_pin", "no_field", "unknown_company_unpin", "unknown_field_unpin"],
)
async def test_a_refused_write_changes_nothing(api_client, profiles, method, path, body, status):
    before = [await _call(api_client, "GET", f"{P}/reddit"), await _call(api_client, "GET", f"{P}/reddit/claims")]
    await _call(api_client, method, path, body, status=status)
    assert [await _call(api_client, "GET", f"{P}/reddit"), await _call(api_client, "GET", f"{P}/reddit/claims")] == before


# --------------------------------------------------------------------------- #
# 4. Drift
# --------------------------------------------------------------------------- #


def _adding(real):
    def drifted(*args, **kwargs):
        return {**real(*args, **kwargs), "unmodelled": True}

    return drifted


@pytest.mark.asyncio
async def test_a_field_builder_that_adds_a_key_fails_the_profile(api_client, profiles, monkeypatch):
    monkeypatch.setattr(router, "_profile_field", _adding(router._profile_field))
    with pytest.raises(ResponseValidationError):
        await api_client.get(f"{P}/google")


@pytest.mark.asyncio
async def test_a_worklist_item_without_its_suggestion_fails_the_profile(api_client, profiles, monkeypatch):
    real = router._needs_review
    monkeypatch.setattr(
        router, "_needs_review",
        lambda profile, fields: [{k: v for k, v in item.items() if k != "suggestion"} for item in real(profile, fields)],
    )
    with pytest.raises(ResponseValidationError):
        await api_client.get(f"{P}/reddit")


def _quote_with_an_exchange(quotes: dict) -> dict:
    return {slug: {**q, "exchange": "NASDAQ"} for slug, q in quotes.items()}


def _quote_with_a_word_for_a_move(quotes: dict) -> dict:
    return {slug: {**q, "change_pct": "down"} for slug, q in quotes.items()}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "drift"),
    [
        # Prices serve the whole quote, so a key the model does not name reaches the wire.
        (f"{P}/google/prices", _quote_with_an_exchange),
        # The list and the card copy four values out of it, so only a value of the wrong type can.
        (P, _quote_with_a_word_for_a_move),
        ("/api/companies/google/card", _quote_with_a_word_for_a_move),
    ],
    ids=["prices", "list", "card"],
)
async def test_a_quote_that_drifts_fails_every_read_that_serves_it(api_client, profiles, monkeypatch, path, drift):
    real = router.price_store.latest_price_map

    async def drifted(session, slugs=None):
        return drift(await real(session, slugs))

    monkeypatch.setattr(router.price_store, "latest_price_map", drifted)
    with pytest.raises(ResponseValidationError):
        await api_client.get(path)


@pytest.mark.asyncio
async def test_a_health_verdict_that_drifts_fails_a_pin(api_client, profiles, monkeypatch):
    real = profile_store.set_manual

    async def drifted(session, slug, field, value):
        return {**(await real(session, slug, field, value)), "severity": 2}

    monkeypatch.setattr(router.profile_store, "set_manual", drifted)
    with pytest.raises(ResponseValidationError):
        await api_client.patch(f"{P}/reddit", json={"field": "equity_vehicle", "value": "rsu"})


@pytest.mark.asyncio
async def test_a_stored_conflict_keeps_an_unnamed_key_and_fails_without_its_source(api_client, db_session, profiles):
    profile = (await db_session.execute(select(CompanyProfile).where(CompanyProfile.slug == "reddit"))).scalar_one()
    await db_session.refresh(profile)
    meta = json.loads(json.dumps(profile.field_meta))
    meta["ticker"]["conflicts"][0]["confidence"] = 0.4
    profile.field_meta = meta
    await db_session.commit()
    kept = (await _call(api_client, "GET", f"{P}/reddit"))["fields"]["ticker"]["conflicts"][0]
    assert kept["confidence"] == 0.4

    meta = json.loads(json.dumps(meta))
    del meta["ticker"]["conflicts"][0]["source"]
    profile.field_meta = meta
    await db_session.commit()
    with pytest.raises(ResponseValidationError):
        await api_client.get(f"{P}/reddit")


# --------------------------------------------------------------------------- #
# 5. One source
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_with_the_plugin_on_the_list_credits_it_and_shows_its_company_size_alone(api_client, plugin_on):
    body = await _call(api_client, "GET", P)
    assert body["attribution"] == PLUGIN_ATTRIBUTION
    items = {item["slug"]: item for item in body["items"]}
    # The plugin's size for the company it read; none of ours for the others.
    assert {slug: item["headcount"] for slug, item in items.items()} == {
        "anthropic": None, "google": 180000, "reddit": None}
    # Its reference ladder, banded from our atlas when read: L7, L6, L5, L3.
    assert {slug: item["mapped_levels"] for slug, item in items.items()} == {"anthropic": 0, "google": 4, "reddit": 0}
    # Identity is ours whatever the plugin claims; anthropic's disputed size is
    # not shown, so it is no conflict field.
    assert items["google"]["display_name"] == "Google"
    assert (items["anthropic"]["conflict_fields"], items["reddit"]["conflict_fields"]) == ([], ["ticker", "is_public"])


@pytest.mark.asyncio
async def test_the_plugin_answers_company_size_ladder_and_benefits_and_never_identity(api_client, plugin_on):
    body = await _call(api_client, "GET", f"{P}/google")
    assert body["fields"]["headcount"] == {
        "value": 180000, "source": PLUGIN, "observed_at": _stamp(2),
        "freshness": "fresh", "is_manual": False, "conflicts": [],
        "candidates": [_candidate(PLUGIN, 50, 180000, 2)],
        "editable": False,
        "answered_by": PLUGIN,
    }
    hq = body["fields"]["hq_city"]
    assert (hq["value"], hq["source"], hq["answered_by"], hq["editable"]) == ("Mountain View", "roleband", None, True)
    assert all(c["source"] != PLUGIN for c in hq["candidates"])
    assert body["source_names"] == {PLUGIN: PLUGIN_NAME}
    assert body["attribution"] == PLUGIN_ATTRIBUTION
    read = {"plugin": PLUGIN, "plugin_name": PLUGIN_NAME, "covered": True}
    assert body["sources"] == {"pay": read, "benefits": read, "company_size": read}

    # Highest median first, a rung without one last, only the reference ladder,
    # each banded by our atlas at read time.
    assert [(r["level_label"], r["band"], r["tc_median"]) for r in body["comp_levels"]] == [
        ("L7", "principal", 907556), ("L6", "staff", 594000), ("L5", "senior", 400000), ("L3", "entry", None),
    ]
    assert body["comp_levels"][2]["bonus_pct"] == 0.0
    # Benefits: the plugin's rows alone, never a dataset record beside them.
    items = [i for group in body["benefits"] for i in group["items"]]
    assert sorted((i["name"], i["benefit_type"], i["value_usd"], i["value_text"], i["description"], i["kind"])
                  for i in items) == sorted([
        ("401k", "retirement_plan", 9750, None, "50% match up to the IRS limit", "provider"),
        ("ESPP", None, None, "15% discount", None, "provider"),
        ("Remote work stipend", None, 1000, None, None, "provider"),
    ], key=str)
    assert not [i for i in items if i["builtin"]]
    assert [g["category"] for g in body["benefits"]][-1] == "other"


@pytest.mark.asyncio
async def test_a_company_the_plugin_has_not_read_shows_none_of_ours_in_its_place(api_client, plugin_on):
    body = await _call(api_client, "GET", f"{P}/anthropic")
    assert body["fields"]["headcount"] == {
        "value": None, "source": None, "observed_at": None, "freshness": None,
        "is_manual": False, "conflicts": [], "candidates": [], "editable": False, "answered_by": PLUGIN,
    }, "your pin is ours: hidden while the plugin answers company size"
    assert (body["comp_levels"], body["benefits"]) == ([], [])
    unread = {"plugin": PLUGIN, "plugin_name": PLUGIN_NAME, "covered": False}
    assert body["sources"] == {"pay": unread, "benefits": unread, "company_size": unread}
    assert (body["data_health"], body["needs_review"]) == ("ok", [])
    # Identity and the offer policy are still ours.
    assert body["fields"]["is_public"]["value"] is False
    assert body["fields"]["equity_vehicle"]["value"] == "options"


@pytest.mark.asyncio
async def test_a_pin_on_the_plugin_s_field_is_refused_and_an_identity_pin_is_not(api_client, plugin_on):
    before = [await _call(api_client, "GET", f"{P}/anthropic"), await _call(api_client, "GET", f"{P}/anthropic/claims")]
    refused = await _call(api_client, "PATCH", f"{P}/anthropic", {"field": "headcount", "value": 2000}, status=409)
    assert refused["detail"]["code"] == "field-answered-by-plugin"
    after = [await _call(api_client, "GET", f"{P}/anthropic"), await _call(api_client, "GET", f"{P}/anthropic/claims")]
    assert after == before
    written = await _call(api_client, "PATCH", f"{P}/anthropic", {"field": "hq_city", "value": "San Francisco"})
    assert written["field"] == "hq_city"
    assert (await _call(api_client, "GET", f"{P}/anthropic"))["fields"]["hq_city"]["value"] == "San Francisco"


@pytest.mark.asyncio
async def test_turning_the_plugin_off_brings_every_profile_back_exactly_as_ours_was(api_client, db_session, profiles):
    from tracker.db.models import PluginInstall

    async def read() -> list:
        return [await _call(api_client, "GET", P)] + [
            await _call(api_client, "GET", f"{P}/{slug}") for slug in ("google", "reddit", "anthropic")]

    ours = await read()
    await install_plugin(db_session)
    on = await read()
    assert on != ours
    (await db_session.get(PluginInstall, PLUGIN)).enabled = False
    await db_session.commit()
    assert await read() == ours


@pytest.mark.asyncio
async def test_the_company_s_us_ladder_is_screened_as_the_estimate_screens_it(api_client, profiles, db_session):
    """A rung of ours under the US floor is not US pay to the estimate
    (`comp_market.us_rows`), so the company's page does not show it as US pay
    either: the two never disagree. Fail-first: the page showed it."""
    from tracker.db.models import CompanyCompLevel
    from tracker.taxonomy.comp_families import REFERENCE_FAMILY

    def ours(label: str, band: str, base: int, tc: int) -> CompanyCompLevel:
        return CompanyCompLevel(company_slug="reddit", family=REFERENCE_FAMILY, level_label=label, band=band,
                                base_amount=base, tc_median=tc, provider="manual", fetched_at=NOW)

    db_session.add_all([ours("IC2", "mid", 30_000, 38_000), ours("IC4", "senior", 210_000, 330_000),
                        ours("IC5", "staff", 250_000, 420_000)])
    await db_session.commit()
    body = await _call(api_client, "GET", f"{P}/reddit")
    assert [r["level_label"] for r in body["comp_levels"]] == ["IC5", "IC4"]
