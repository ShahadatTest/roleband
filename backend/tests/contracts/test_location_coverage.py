"""Location-coverage contracts, parametrized over ADAPTER_REGISTRY.

A location-narrowed source can only answer questions it is asked. When the user
tracks a region and no adapter query targets it, the response is empty for the
same reason a region with no open roles is empty — there is no error, no drift
alert, and no anomaly to tell them apart. Nothing downstream can recover that
distinction, so it has to be declared up front and checked here.

`BaseAdapter.location_queries` is that declaration. These tests pin the two
properties that make it trustworthy:

1. Every declared key is a real location group, and coverage flows only DOWN the
   tree. Declaring `london` never covers `uk`.
2. A tracked group with no declared ancestor is REPORTED, not silently dropped.
"""

from __future__ import annotations

import pytest

from tracker.connectors import ADAPTER_REGISTRY
from tracker.connectors.listing import build_adapter
from tracker.taxonomy.countries import COUNTRIES
from tracker.taxonomy.locations import (
    LOCATION_GROUPS,
    location_group_covers,
)

#: Adapters needing a board token shaped like something before they construct.
_TOKENS = {"workday": "example.wd1.myworkdayjobs.com|External"}

_DEFAULTS = frozenset(
    slug for slug, group in LOCATION_GROUPS.items() if group.get("enabled")
)


def _adapter(name: str, **kwargs):
    return build_adapter(f"contract-{name}", name, _TOKENS.get(name), **kwargs)


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_manifest_keys_are_real_location_groups(name):
    """A manifest key nobody can enable is a coverage claim about nothing."""
    manifest = _adapter(name).location_queries
    if manifest is None:
        return
    unknown = sorted(set(manifest) - set(LOCATION_GROUPS))
    assert not unknown, f"{name} declares unknown location groups: {unknown}"


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_manifest_entries_have_query_terms(name):
    """An empty term list claims coverage while sending no query at all."""
    manifest = _adapter(name).location_queries
    if manifest is None:
        return
    empty = sorted(group for group, terms in manifest.items() if not terms)
    assert not empty, f"{name} claims {empty} with no query terms"


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_tracked_group_without_a_declared_ancestor_is_reported(name):
    """The core promise: an unaskable region is named, never silently empty."""
    adapter = _adapter(name, location_groups=["canada"])
    manifest = adapter.location_queries
    if manifest is None:
        # Whole-board sources return every region in one response, so there is
        # nothing to narrow and nothing to miss.
        assert adapter.location_gaps() == []
        return
    if any(location_group_covers(declared, "canada") for declared in manifest):
        pytest.skip(f"{name} genuinely covers canada")
    assert adapter.location_gaps() == ["canada"], (
        f"{name} tracks canada, has no query for it, and did not report the gap"
    )


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_declaring_a_metro_does_not_claim_its_country(name):
    """`london` must never satisfy a tracked `uk` — the over-claim that
    serves one city as if it were the whole country."""
    adapter = _adapter(name, location_groups=["uk"])
    manifest = adapter.location_queries
    if manifest is None or "uk" in manifest:
        return
    if any(location_group_covers(declared, "uk") for declared in manifest):
        return  # covered by a genuine ancestor (e.g. europe)
    assert "uk" in adapter.location_gaps(), (
        f"{name} declares {sorted(manifest)} and claimed to cover uk"
    )


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_declaring_a_country_covers_its_metros(name):
    """The other direction must still hold, or every US metro reads as a gap."""
    adapter = _adapter(name, location_groups=["new_york"])
    manifest = adapter.location_queries
    if manifest is None or "united_states" not in manifest:
        return
    assert adapter.location_gaps() == [], (
        f"{name} declares united_states but reported new_york as uncovered"
    )


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_untracked_scope_runs_the_shipped_defaults_not_the_planet(name):
    """Standalone use (CLI, smoke, tests) means the DEFAULT scope, not every
    entry declared.

    Manifests are generated per country, so "run everything declared" is one
    query per country: a `smoke_adapters` run would issue all of them, and a
    contract test paging a repeating source would exceed its request cap. An
    unconfigured run should mean the shipped scope.
    """
    adapter = _adapter(name)
    manifest = adapter.location_queries
    assert adapter.location_gaps() == []
    if manifest is None:
        assert adapter.planned_location_terms() == []
        return
    planned = {group for group, _ in adapter.planned_location_items()}
    assert planned, f"{name} planned nothing for the default scope"
    # Relatedness is the whole assertion. A regression to "no scope means
    # everything" shows up here rather than in a count, because a per-country
    # manifest would plan `india`, which relates to no shipped-enabled group.
    # (A small hand-written manifest legitimately plans all of itself.)
    for group in planned:
        assert any(
            location_group_covers(group, default) or location_group_covers(default, group)
            for default in _DEFAULTS
        ), f"{name} planned {group}, unrelated to any default-enabled group"


def test_no_adapter_silently_drops_a_tracked_region():
    """Whole-registry sweep against the shipped defaults: every gap any adapter
    has must be nameable. This is the test that fails when someone enables a new
    region without extending the manifests."""
    tracked = [slug for slug, group in LOCATION_GROUPS.items() if group.get("enabled")]
    gaps = {
        name: _adapter(name, location_groups=tracked).location_gaps()
        for name in sorted(ADAPTER_REGISTRY)
    }
    # Every shipped-default region is reachable at every tracked source. Adding
    # to this dict means a region was enabled that some source cannot serve —
    # which is a decision to make deliberately, not to discover from an empty
    # results page.
    assert {k: v for k, v in gaps.items() if v} == {}


#: Countries a place-searched source cannot be asked about, each with its reason.
#: Anything else missing from a manifest is a short list nobody decided on.
_NOT_DECLARED: dict[str, dict[str, str]] = {
    "accenture": {
        "india": "each surface answers its result window for India, not a count",
    },
    "apple": {
        slug: "Apple's place lookup names no code for it"
        for slug in ("cuba", "iran", "north_korea", "south_sudan", "sudan", "syria")
    },
}


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_every_country_is_declared_or_named_as_unaskable(name):
    """A user may pick any country: a place-searched source asks about every
    one, or names why it cannot. A hand-written short list fails here the day
    it is added, instead of reading as empty regions."""
    manifest = _adapter(name).location_queries
    if manifest is None:
        return
    missing = {
        country.slug for country in COUNTRIES
        if not any(location_group_covers(declared, country.slug) for declared in manifest)
    }
    exceptions = _NOT_DECLARED.get(name, {})
    assert missing == set(exceptions), (
        f"{name}: undeclared {sorted(missing - set(exceptions))}, "
        f"named as unaskable but declared {sorted(set(exceptions) - missing)}"
    )
