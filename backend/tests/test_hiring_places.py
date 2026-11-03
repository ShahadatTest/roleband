"""`analytics.hiring`: roles per region and country, each once.

Summing rollup slices that count a posting once per location group, nested
and region-expanded, would count a London posting three times (london, uk,
europe) and a "Remote - EMEA" one over a hundred times. These pin the per-role
count on the place strings boards really send.
"""

from __future__ import annotations

from tracker.analytics.hiring import build_hiring_places, role_reach


def _regions(roles):
    return {r["key"]: r for r in build_hiring_places(roles)["regions"]}


def test_a_region_only_place_is_region_wide_and_in_no_country():
    countries, wide = role_reach(["Remote - EMEA"])
    assert (countries, wide) == (set(), {"europe", "middle_east", "africa"})
    regions = _regions([["Remote - EMEA"]])
    assert regions["europe"] == {"key": "europe", "open": 1, "region_wide": 1, "countries": []}
    # The Board's filter admits it in every EMEA country; a count must not.
    assert all(r["countries"] == [] for r in regions.values())


def test_a_named_place_counts_once_at_its_country_and_region_never_per_level():
    regions = _regions([["London, UK"], ["London, UK | Manchester, UK"]])
    assert regions == {"europe": {"key": "europe", "open": 2, "region_wide": 0, "countries": [{"key": "uk", "open": 2}]}}


def test_a_role_named_in_a_region_is_not_region_wide_there_even_beside_a_region_place():
    countries, wide = role_reach(["Remote Sweden", "Remote EMEA"])
    assert "sweden" in countries
    regions = _regions([["Remote Sweden", "Remote EMEA"]])
    assert (regions["europe"]["open"], regions["europe"]["region_wide"]) == (1, 0)
    assert (regions["africa"]["open"], regions["africa"]["region_wide"]) == (1, 1)


def test_a_role_in_two_regions_counts_once_in_each():
    regions = _regions([["London, UK", "New York, NY"]])
    assert {k: r["open"] for k, r in regions.items()} == {"europe": 1, "north_america": 1}


def test_a_region_named_as_a_pair_of_countries_is_those_countries():
    countries, wide = role_reach(["ANZ"])
    assert (countries, wide) == ({"australia", "new_zealand"}, set())


def test_a_place_that_names_nothing_is_unplaced_never_dropped():
    out = build_hiring_places([["Remote"], ["Anywhere"], ["Berlin, Germany"]])
    assert out["unplaced"] == 2
    assert [r["key"] for r in out["regions"]] == ["europe"]


def test_order_is_by_open_roles_then_key():
    out = build_hiring_places([["Tokyo, Japan"], ["Berlin, Germany"], ["Paris, France"], ["Munich, Germany"]])
    assert [r["key"] for r in out["regions"]] == ["europe", "east_asia"]
    assert out["regions"][0]["countries"] == [{"key": "germany", "open": 2}, {"key": "france", "open": 1}]


def test_nothing_in_is_nothing_out():
    assert build_hiring_places([]) == {"regions": [], "unplaced": 0}
