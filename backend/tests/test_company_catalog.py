"""Catalog search + add-request resolution — pure logic, no DB."""

from __future__ import annotations

from collections import Counter

import pytest

from tracker.company_catalog import CATALOG
from tracker.company_discovery import (
    COMPANY_DISCOVERY,
    SECTORS,
    build_company_discovery,
    discovery_company_fields,
)
from tracker.company_store import CompanyError, resolve_company, slugify


def test_slugify():
    assert slugify("Scale AI") == "scale-ai"
    assert slugify("  Acme, Inc.  ") == "acme-inc"


def test_resolve_from_catalog_slug():
    fields = resolve_company(catalog_slug="stripe")
    assert fields["status"] == "active"
    assert fields["adapter"] == CATALOG["stripe"]["adapter"]
    assert fields["board_token"] == CATALOG["stripe"]["board_token"]
    assert fields["source"] == "catalog"


def test_resolve_existing_catalog_company_outside_discovery_sectors():
    # `flexport` is the catalog's only entry with no discovery-sector record.
    # The case matters because the two lookups are independent: a catalog slug
    # must still resolve when `discovery_company_fields` returns None.
    fields = resolve_company(catalog_slug="flexport")
    assert fields["status"] == "active"
    assert fields["adapter"] == CATALOG["flexport"]["adapter"]
    assert fields["source"] == "catalog"


def test_resolve_name_matching_catalog_is_treated_as_catalog_add():
    fields = resolve_company(name="Stripe", careers_url="https://example.com/x")
    assert fields["slug"] == "stripe"
    assert fields["source"] == "catalog"


def test_resolve_greenhouse_url_is_active():
    fields = resolve_company(name="Acme", careers_url="https://boards.greenhouse.io/acmeco")
    assert fields["status"] == "active"
    assert fields["adapter"] == "greenhouse"
    assert fields["board_token"] == "acmeco"
    assert fields["source"] == "url"


def test_resolve_unsupported_url_is_pending():
    """A company on an ATS we cannot reach has to park rather than pretend."""
    fields = resolve_company(name="Widgets", careers_url="https://widgets.example/careers")
    assert fields["status"] == "pending"
    assert fields["adapter"] is None
    assert fields["board_token"] is None
    assert fields["careers_url"] == "https://widgets.example/careers"


@pytest.mark.parametrize("url,region", [
    ("https://jobs.lever.co/widgets", "global"),
    ("https://jobs.eu.lever.co/widgets", "eu"),
])
def test_resolve_lever_url_is_active_and_keeps_its_region(url, region):
    """A Lever URL is recognised. The region has to persist here: it
    cannot be recovered from a failed fetch, because a wrong region answers the
    same 404 as a wrong board token."""
    fields = resolve_company(name="Widgets", careers_url=url)

    assert fields["status"] == "active"
    assert fields["adapter"] == "lever"
    assert fields["board_token"] == "widgets"
    assert fields["board_region"] == region


def test_a_single_host_family_stores_no_region():
    """`None`, not `"global"` — a Greenhouse company has one deployment and no
    region to record."""
    fields = resolve_company(name="Acme", careers_url="https://boards.greenhouse.io/acmeco")

    assert fields["board_region"] is None


def test_resolve_requires_url_when_not_in_catalog():
    with pytest.raises(CompanyError):
        resolve_company(name="Totally Unknown Co")


def test_resolve_requires_some_input():
    with pytest.raises(CompanyError):
        resolve_company()


def test_discovery_catalog_has_job_seeker_sectors_and_canonical_companies():
    assert [sector.slug for sector in SECTORS[:3]] == ["faang", "ai", "technology"]
    assert len(SECTORS) == 12
    assert len(COMPANY_DISCOVERY) == 136
    assert COMPANY_DISCOVERY["microsoft"].sectors == ("technology", "gaming")
    assert COMPANY_DISCOVERY["cloudflare"].sectors == ("cybersecurity", "cloud-data-devtools")


def test_every_catalog_company_can_be_found_in_the_explorer():
    """The explorer is the only place a catalog company is offered by name:
    the directory search leaves catalog slugs out so nothing is listed twice.
    A catalog entry missing here can be added only by pasting its careers URL."""
    assert sorted(set(CATALOG) - set(COMPANY_DISCOVERY)) == []


def test_discovery_keeps_faang_exact_and_parked_company_unavailable():
    state = build_company_discovery(tracked={})
    faang = next(sector for sector in state["sectors"] if sector["slug"] == "faang")
    assert faang["company_count"] == 5
    tesla = next(company for company in state["companies"] if company["slug"] == "tesla")
    assert tesla["connector_state"] == "parked"
    assert tesla["selectable"] is False


def test_discovery_derives_live_ready_and_family_connector_states():
    state = build_company_discovery(tracked={})
    companies = {company["slug"]: company for company in state["companies"]}
    assert companies["google"]["connector_state"] == "live"
    assert companies["stripe"]["connector_state"] == "ready"
    assert companies["google-deepmind"]["connector_state"] == "family"
    # `mckinsey-company` runs a bespoke careers site on no ATS we could add, so
    # it is `planned` until the recipe engine reaches it.
    assert companies["mckinsey-company"]["connector_state"] == "planned"


def test_the_catalog_wave_left_every_state_reachable_and_the_roster_untouched():
    """A catalog wave adds many rows at once, so the shape of the result is worth
    one assertion: an entry is an OFFER. Every one of them reports `ready`, which is
    a state a user acts on — nothing here is tracked, enabled or scraped until
    they do, which is why a wave of this size costs no requests.
    """
    state = build_company_discovery(tracked={})
    by_state = Counter(c["connector_state"] for c in state["companies"])

    # A company moves from `planned` to `ready` when a connector reaches its
    # board; the change that moves one updates these counts. `figure` is on
    # its own Greenhouse board `figureai` (the `figure` token is Figure Lending's).
    assert by_state["ready"] == 116
    assert by_state["planned"] == 7
    assert set(by_state) == {"live", "ready", "family", "planned", "parked"}
    added = [c for c in state["companies"] if c["slug"] in {"wiz", "palantir", "snowflake"}]
    assert [(c["connector_state"], c["tracked"], c["enabled"]) for c in added] == [
        ("ready", False, False)
    ] * 3


@pytest.mark.parametrize("slug,adapter,token", [
    ("pwc", "workday", "pwc.wd3.myworkdayjobs.com|US_Experienced_Careers"),
    ("amd", "jibe", "careers.amd.com"),
    ("susquehanna-international-group", "jibe", "careers.sig.com"),
    ("boston-consulting-group", "eightfold", "experiencedtalent.bcg.com|bcg.com"),
    ("two-sigma", "avature", "careers.twosigma.com|careers|openroles"),
    ("micron", "eightfold", "careers.micron.com|micron.com|pcsx"),
    ("deloitte", "avature", "apply.deloitte.com|en_US/careers|capped"),
    ("bain-company", "avature", "careers.bain.com|jobs|folder"),
])
def test_existing_family_coverage_resolves_a_collectable_unfollowed_company(slug, adapter, token):
    fields = resolve_company(catalog_slug=slug)
    assert (fields["status"], fields["adapter"], fields["board_token"]) == ("active", adapter, token)
    company = next(c for c in build_company_discovery(tracked={})["companies"] if c["slug"] == slug)
    assert company["connector_state"] == "ready"
    assert company["selectable"] is True
    assert (company["tracked"], company["enabled"]) == (False, False)
    # Bain, not Deloitte, holds the consulting slot.
    assert company["curated"] is (slug in {"amd", "boston-consulting-group", "two-sigma", "bain-company"})


def test_ami_labs_is_an_ai_sector_company_with_a_live_ashby_board():
    # The two catalogs are independent: a discovery entry alone would render AMI
    # Labs as "Connector planned" and never scrape. Assert both halves plus the
    # board token, since an Ashby tenant name is the one field a wrong guess
    # turns into a nightly 404 -> quarantined binding.
    assert COMPANY_DISCOVERY["ami-labs"].sectors == ("ai",)
    assert "AMI" in COMPANY_DISCOVERY["ami-labs"].aliases
    assert CATALOG["ami-labs"] == {
        "display": "AMI Labs",
        "adapter": "ashby",
        "board_token": "ami",
    }
    fields = resolve_company(catalog_slug="ami-labs")
    assert fields["status"] == "active"
    assert (fields["adapter"], fields["board_token"]) == ("ashby", "ami")
    assert fields["careers_url"] == "https://jobs.ashbyhq.com/ami"

    state = build_company_discovery(tracked={})
    entry = next(c for c in state["companies"] if c["slug"] == "ami-labs")
    assert entry["connector_state"] == "ready"
    assert entry["selectable"] is True


def test_lovable_spans_two_sectors_and_scrapes_its_own_ashby_board():
    # Same two-catalog rule as AMI Labs: a discovery entry alone renders
    # "Connector planned" and never scrapes. Both halves plus the token, since
    # a wrong Ashby tenant is a nightly 404 -> quarantined binding.
    assert COMPANY_DISCOVERY["lovable"].sectors == ("ai", "cloud-data-devtools")
    assert "GPT Engineer" in COMPANY_DISCOVERY["lovable"].aliases
    assert CATALOG["lovable"] == {
        "display": "Lovable",
        "adapter": "ashby",
        "board_token": "lovable",
    }
    fields = resolve_company(catalog_slug="lovable")
    assert fields["status"] == "active"
    assert (fields["adapter"], fields["board_token"]) == ("ashby", "lovable")
    # Unlike AMI Labs, Lovable publishes a careers page of its own, so the
    # seeker-facing URL is that page and not the raw Ashby board behind it.
    assert fields["careers_url"] == "https://lovable.dev/careers"

    state = build_company_discovery(tracked={})
    entry = next(c for c in state["companies"] if c["slug"] == "lovable")
    assert entry["connector_state"] == "ready"
    assert entry["selectable"] is True


def test_resolve_planned_discovery_company_as_pending():
    fields = resolve_company(catalog_slug="mckinsey-company")
    assert fields == {
        "slug": "mckinsey-company",
        "display": "McKinsey & Company",
        "adapter": None,
        "board_token": None,
        "board_region": None,
        "careers_url": "https://www.mckinsey.com/careers/search-jobs",
        "status": "pending",
        "source": "catalog",
    }


@pytest.mark.parametrize("slug", ["tesla", "valve", "meta"])
def test_resolve_rejects_parked_discovery_company(slug):
    with pytest.raises(CompanyError, match="not currently available"):
        resolve_company(catalog_slug=slug)


def test_a_company_with_no_collectable_source_is_parked_not_planned():
    """`planned` reads "Connector planned", which is a promise. Tesla's board
    refuses every client RoleBand may use (Akamai answers 403 to the identified
    client and to the TLS fingerprint), and Valve's robots.txt
    disallows its jobs page for every agent, so either promise would be false."""
    state = build_company_discovery(tracked={})
    by_slug = {c["slug"]: c for c in state["companies"]}

    assert (by_slug["tesla"]["connector_state"], by_slug["tesla"]["selectable"]) == ("parked", False)
    assert by_slug["tesla"]["parked_reason"] == "bot_protected"
    assert (by_slug["valve"]["connector_state"], by_slug["valve"]["selectable"]) == ("parked", False)
    assert by_slug["valve"]["parked_reason"] == "robots_disallow"


def test_every_recipe_catalog_row_names_a_bundled_recipe_that_compiles():
    from tracker.connectors.recipes import compile_recipe
    from tracker.connectors.recipes.bundled import BUNDLED_RECIPES

    for slug, entry in CATALOG.items():
        if entry["adapter"] != "recipe":
            continue
        assert entry["board_token"] in BUNDLED_RECIPES, slug
        compile_recipe(BUNDLED_RECIPES[entry["board_token"]].document)


def test_a_lever_catalog_row_carries_its_region_and_a_greenhouse_row_carries_none():
    """The region rule reaching the catalog. `None` and `"global"`
    are different records: Lever runs separate tenant namespaces per region and
    a wrong region answers the same 404 as a wrong token, so the region can
    never be recovered from the failure — while a Greenhouse company genuinely
    has one deployment and must not be labelled as if it had chosen a host."""
    lever = resolve_company(catalog_slug="palantir")
    greenhouse = resolve_company(catalog_slug="wiz")

    assert (lever["adapter"], lever["board_token"], lever["board_region"]) == (
        "lever", "palantir", "global",
    )
    assert greenhouse["board_region"] is None
    # The two readings of one row must not disagree — an add takes the first.
    assert discovery_company_fields("palantir")["board_region"] == "global"


def test_every_resolution_path_returns_the_same_field_names():
    """`board_region` on the detected-URL branch only would make the dict's
    shape depend on which branch produced it — a caller reading the key would
    work for a URL add and raise for a catalog add. Every path answers with
    the same keys."""
    paths = [
        resolve_company(catalog_slug="stripe"),                                   # catalog
        resolve_company(name="Acme", careers_url="https://boards.greenhouse.io/acmeco"),  # detected
        resolve_company(name="Widgets", careers_url="https://widgets.example/careers"),   # pending
    ]

    assert {frozenset(fields) for fields in paths} == {frozenset(paths[0])}
    assert all("board_region" in fields for fields in paths)
