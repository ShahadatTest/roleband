"""Where the Hiring tab says roles are open. Pure, DB-free.

A `demand_metrics` slice counts a POSTING once per location group. Groups nest
(a London posting is london, uk and europe) and a place that names only a
region expands to every country in it ("Remote EMEA" is every EMEA country), so
summed slices multiply each posting many times over. This counts ROLES, each
once per region and once per country it names.

Two kinds of place, read per place the posting lists (`location_pieces`):

* A place that names a country, or a city or metro in one ("London, UK",
  "Munich"), puts the role in that country and its region.
* A place that names only a region ("Remote - EMEA", "Americas") puts the role
  in the region as *region-wide*, never in each country. The Board's place
  filter admits such a role in every country (a person tracking Germany should
  see a remote-EMEA role); a count by country must not multiply it.

A place set is one role: the caller passes the union of its
members' places as one role. A role whose places name nothing we can place
("Remote", "Anywhere") is counted as unplaced, never dropped.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from functools import lru_cache

from tracker.enrich.classify import location_groups_for
from tracker.taxonomy.locations import (
    LOCATION_GROUPS,
    location_group_ancestors,
    location_pieces,
    region_places,
)


def _top_region(slug: str) -> str | None:
    """The top-level region above a group (the Gulf is in the Middle East)."""
    node = LOCATION_GROUPS.get(slug, {})
    if node.get("kind") == "region" and not node.get("parent"):
        return slug
    chain = location_group_ancestors(slug)
    return chain[-1] if chain else None


@lru_cache(maxsize=8192)
def place_reach(piece: str) -> tuple[frozenset[str], frozenset[str]]:
    """`(countries, region_wide)` one place names: the countries it is in, and
    the top-level regions it names as a whole. Cached: postings repeat places."""
    named_regions = region_places(piece)
    if named_regions:
        countries: set[str] = set()
        regions: set[str] = set()
        for slug in named_regions:
            kind = LOCATION_GROUPS.get(slug, {}).get("kind")
            if kind == "country":  # a pair of countries named as a region (ANZ)
                countries.add(slug)
            elif (top := _top_region(slug)) is not None:
                regions.add(top)
        return frozenset(countries), frozenset(regions)
    groups = location_groups_for([piece])
    return (
        frozenset(g for g in groups if LOCATION_GROUPS.get(g, {}).get("kind") == "country"),
        frozenset(),
    )


def role_reach(locations: Sequence[str]) -> tuple[set[str], set[str]]:
    """`(countries, region_wide)` over every place one role lists."""
    countries: set[str] = set()
    wide: set[str] = set()
    for piece in location_pieces(list(locations)):
        named, regions = place_reach(piece)
        countries |= named
        wide |= regions
    return countries, wide


def build_hiring_places(roles: Iterable[Sequence[str]]) -> dict:
    """Roles per region and per country, each role once in each.

    `roles`: one list of location strings per role. Returns `{"regions": [...],
    "unplaced": n}`; a region is `{key, open, region_wide, countries}` where
    `region_wide` counts the roles in the region that name no country in it,
    and `countries` is `[{key, open}]`. Regions and countries are ranked by
    open roles, then by key, so the order is stable.
    """
    region_open: Counter[str] = Counter()
    region_wide: Counter[str] = Counter()
    country_open: Counter[str] = Counter()
    unplaced = 0
    for locations in roles:
        countries, wide = role_reach(locations)
        by_region: dict[str, set[str]] = {}
        for country in countries:
            top = _top_region(country)
            if top is not None:
                by_region.setdefault(top, set()).add(country)
        regions = set(by_region) | wide
        if not regions:
            unplaced += 1
            continue
        for region in regions:
            region_open[region] += 1
            if region not in by_region:
                region_wide[region] += 1
        for country in countries:
            country_open[country] += 1

    def ranked(counter: Counter[str], keys: Iterable[str]) -> list[str]:
        return sorted(keys, key=lambda k: (-counter[k], k))

    regions_out = []
    for region in ranked(region_open, region_open):
        members = [c for c in country_open if _top_region(c) == region]
        regions_out.append({
            "key": region,
            "open": region_open[region],
            "region_wide": region_wide[region],
            "countries": [{"key": c, "open": country_open[c]} for c in ranked(country_open, members)],
        })
    return {"regions": regions_out, "unplaced": unplaced}
