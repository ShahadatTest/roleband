""""Anywhere" keeps a place the taxonomy gains later.

The walk stores "Anywhere" as every top-level place, the ten regions, and
stored rows carry every ancestor of their places. So a country,
metro or city added under a region later is already inside "Anywhere": no
sentinel is needed, as it is for role answers. That holds only
while every place descends from a region. A place added outside every region
would sit outside "Anywhere" silently; this file fails it by name.
"""

from __future__ import annotations

from tracker.taxonomy.cities import _gazetteer
from tracker.taxonomy.locations import LOCATION_GROUPS, REGIONS, location_group_ancestors
from tracker.taxonomy.place_scope import place_admits

TOP_LEVEL = {slug for slug, group in LOCATION_GROUPS.items() if not group.get("parent")}


def test_the_top_level_is_the_regions():
    assert TOP_LEVEL == {slug for slug, region in REGIONS.items() if not region.get("parent")}


def test_every_place_descends_from_a_region():
    orphans = sorted(
        slug for slug in LOCATION_GROUPS
        if slug not in TOP_LEVEL and not set(location_group_ancestors(slug)) & TOP_LEVEL
    )
    assert orphans == [], f"outside every region, so outside Anywhere: {orphans}"


def test_every_city_in_the_gazetteer_descends_from_a_region():
    orphans = sorted(
        f"{city.name} ({city.country})" for city in _gazetteer().by_id.values()
        if not set(location_group_ancestors(city.slug)) & TOP_LEVEL
    )
    assert orphans[:20] == [], f"{len(orphans)} cities outside every region"


def test_anywhere_admits_a_posting_in_any_place():
    for slug in [*LOCATION_GROUPS, *(c.slug for c in list(_gazetteer().by_id.values())[:2000])]:
        stored = [slug, *location_group_ancestors(slug)]
        assert place_admits(stored, TOP_LEVEL, set()), slug


def test_a_place_outside_every_region_is_caught():
    """The planted case: an orphan fails the walk down, so the checks above
    constrain something."""
    assert not set(location_group_ancestors("atlantis")) & TOP_LEVEL
    assert not place_admits(["atlantis"], TOP_LEVEL, set())
