"""Where a role may be: the places included, and the places excepted inside them.

"Anywhere in the US except New York" is stored as the US with New York
excepted, never as the other US metros: those would drop every US role filed at
the country itself (remote, towns outside the metros). The location axis stores
the exceptions, and the gate reads them per place.

A posting's `location_groups` is ancestor-closed: every place it names, with
each place's parents (a New York posting holds new_york, united_states,
north_america). Its most specific places are the ones no other of its groups
sits under. A posting is in when one of those places is covered by an
included place before an excepted one, walking up. So:

- "US except New York": a New York role leaves; a remote-US role (its most
  specific place is the US) and a New York or Austin role (Austin) stay.
- "UK except London" plus London: the more specific answer wins, London stays.

Only taxonomy places and the cities the person named take part: an unnamed
city is dropped from the posting's set first, because the role catalog keeps
only named cities (`scope/catalog.py`), and the three gates must agree. The
cost: "New York or Denver" reads as New York only under "US except New York".
With no exceptions this is exactly an overlap with the included places.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

from tracker.taxonomy.cities import CITY_PREFIX
from tracker.taxonomy.locations import LOCATION_GROUPS, location_group_ancestors


def _relevant(groups: Iterable[str], named: Collection[str]) -> set[str]:
    return {slug for slug in groups if not slug.startswith(CITY_PREFIX) or slug in named}


def _nearest(slug: str, included: Collection[str], excepted: Collection[str]) -> str | None:
    """"in", "out" or None: the first mark on the way up from `slug`."""
    for place in (slug, *location_group_ancestors(slug)):
        if place in included:
            return "in"
        if place in excepted:
            return "out"
    return None


def place_admits(groups: Iterable[str], included: Collection[str], excepted: Collection[str]) -> bool:
    """The location gate for one posting (see the module docstring)."""
    if not excepted:
        return any(slug in included for slug in groups)
    named = {*included, *excepted}
    have = _relevant(groups, named)
    parents = {parent for slug in have for parent in location_group_ancestors(slug)}
    return any(_nearest(slug, included, excepted) == "in" for slug in have - parents)


def place_witnesses(included: Collection[str], excepted: Collection[str]) -> list[tuple[str, frozenset[str]]]:
    """The gate as finitely many SQL-sized tests: a posting is in when it holds
    some `place` and none of that place's `blockers`.

    Equivalent to `place_admits` over an ancestor-closed set: a place covered by
    an inclusion witnesses the posting unless an excepted place it holds sits
    strictly under it. Witnesses are taxonomy groups and the
    named cities; blockers are the exceptions below each."""
    named = {*included, *excepted}
    candidates = [*LOCATION_GROUPS, *(slug for slug in named if slug.startswith(CITY_PREFIX))]
    out: list[tuple[str, frozenset[str]]] = []
    for place in candidates:
        if _nearest(place, included, excepted) != "in":
            continue
        blockers = frozenset(e for e in excepted if place in location_group_ancestors(e))
        out.append((place, blockers))
    return out


def excepted_under(included: Collection[str], excepted: Iterable[str]) -> list[str]:
    """The exceptions that still mean something: each strictly inside an
    included place. Removing the US drops "except New York" with it."""
    return [slug for slug in excepted if any(parent in included for parent in location_group_ancestors(slug))]
