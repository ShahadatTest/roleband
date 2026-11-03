"""Place search for the location step: every standard place a person may type.

One ranked answer over the fixed taxonomy (metros, countries by their CLDR
names and every alias, regions by their name and UN M49 name), the political
unions CLDR groups (the European Union), and the GeoNames cities.
Pure: no database, so the search answers the instant the page
asks, before any scan has run.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.taxonomy.cities import City, city_country, fold, search_cities
from tracker.taxonomy.countries import BY_SLUG, UNIONS
from tracker.taxonomy.locations import LOCATION_GROUPS, REGIONS, metro_of_city

__all__ = ["search_places"]

#: Ranks, best first. A taxonomy place always outranks a city of the same
#: strength: "Georgia" is the country before any town called Georgia.
_EXACT, _PREFIX, _WORD = 0, 1, 2


@dataclass(frozen=True)
class _Hit:
    rank: int
    order: int
    item: dict


def _strength(needle: str, names: list[str]) -> tuple[int, str] | None:
    """How well `needle` matches the best of `names`, and which name it was."""
    best: tuple[int, str] | None = None
    for name in names:
        key = fold(name)
        if key == needle:
            strength = _EXACT
        elif key.startswith(needle):
            strength = _PREFIX
        elif f" {needle}" in f" {key}":
            strength = _WORD
        else:
            continue
        if best is None or strength < best[0]:
            best = (strength, name)
    return best


def _names(slug: str, group: dict) -> list[str]:
    names = [group["display"]]
    kind = group.get("kind")
    if kind == "country" and slug in BY_SLUG:
        names += list(BY_SLUG[slug].aliases)
    elif kind == "region":
        names += list(REGIONS.get(slug, {}).get("aliases", ()))
    elif kind == "metro":
        # A metro's plain city names ("bay area", "seattle") find it; the
        # state-qualified patterns ("san mateo, ca") are matching rules, not names.
        names += [sub for sub in group.get("substrings", ()) if "," not in sub and len(sub) >= 4]
    return names


def _context(slug: str, group: dict) -> str:
    parent = group.get("parent")
    if parent and parent in LOCATION_GROUPS:
        return LOCATION_GROUPS[parent]["display"]
    return ""


def _city_item(city: City, via: str | None) -> dict | None:
    country = city_country(city)
    if country is None:
        return None
    metro = metro_of_city(city)
    if metro and fold(LOCATION_GROUPS[metro]["display"]) in {
        fold(city.name), *(fold(alt) for alt in city.alternates)
    }:
        # London in the London metro, New York City in New York: the metro is
        # already this answer, and two rows for one place read as a mistake.
        return None
    place = [city.admin1_name] if city.admin1_name and fold(city.admin1_name) != fold(city.name) else []
    return {
        "slug": city.slug,
        "display": city.name,
        "kind": "city",
        "parent": metro or country.slug,
        "context": ", ".join([*place, country.display]),
        "matched_by": via,
    }


def search_places(query: str, limit: int = 10) -> dict:
    """`{"places": [...], "unions": [...]}` for `query`, best first."""
    needle = fold(query)
    if not needle:
        return {"places": [], "unions": []}

    hits: list[_Hit] = []
    for order, (slug, group) in enumerate(LOCATION_GROUPS.items()):
        found = _strength(needle, _names(slug, group))
        if found is None:
            continue
        strength, name = found
        hits.append(_Hit(strength, order, {
            "slug": slug,
            "display": group["display"],
            "kind": group.get("kind", "country"),
            "parent": group.get("parent"),
            "context": _context(slug, group),
            "matched_by": None if fold(name) == fold(group["display"]) else name,
        }))

    taken = {hit.item["slug"] for hit in hits}
    # A place the query names exactly ("georgia") is the answer; a town that
    # only shares an old name with it is noise under it.
    named_exactly = any(hit.rank == _EXACT for hit in hits)
    for position, (city, via) in enumerate(search_cities(query, limit=limit * 2)):
        item = _city_item(city, via)
        if item is None or item["slug"] in taken or (via is not None and named_exactly):
            continue
        # A city ranks after every taxonomy place of the same strength; among
        # cities, search_cities already put exact before prefix, then the most
        # populous first.
        strength = _EXACT if fold(city.name) == needle and via is None else _PREFIX
        hits.append(_Hit(strength, len(LOCATION_GROUPS) + position, item))

    hits.sort(key=lambda hit: (hit.rank, hit.item["kind"] == "city", hit.order))
    unions = [
        {"slug": union.slug, "display": union.display, "members": list(union.members)}
        for union in UNIONS
        if _strength(needle, [union.display, *(["eu"] if union.slug == "european_union" else [])])
    ]
    return {"places": [hit.item for hit in hits[:limit]], "unions": unions}
