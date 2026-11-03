"""World cities: the GeoNames gazetteer behind city search and city scope.

The table is `cities.tsv`, generated from the GeoNames `cities15000` snapshot
(licence CC-BY-4.0; attribution: GeoNames, geonames.org) by
`scripts.gen_city_table` and pinned in `tracker.vendored`. It is loaded once,
lazily, on first use.

A city is a location slug like any other, `city_<geonameid>`: the GeoNames id
is the identity, so a renamed city (Bangalore, now Bengaluru) keeps its slug
and its saved scopes. Its parent is the metro it belongs to when it is one of a
metro's named cities, else its country.
"""

from __future__ import annotations

import bisect
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tracker.taxonomy.countries import COUNTRIES, Country

__all__ = [
    "CITY_PREFIX", "City", "city_by_slug", "city_country", "city_for_place", "fold",
    "is_city_slug", "search_cities",
]

_TABLE = Path(__file__).with_name("cities.tsv")

CITY_PREFIX = "city_"

#: A bare city name with no country beside it ("Berlin") is trusted only when
#: it is a real city and clearly the one meant: at least this many people, and
#: this many times the next namesake. "Portland" is Oregon, many times Maine's;
#: "Cambridge" (England and Massachusetts, close in size) is nobody.
_BARE_MIN_POPULATION = 100_000
_BARE_DOMINANCE = 5
#: A bare ALTERNATE name ("Bangalore" alone) is held to a higher bar: an old
#: or foreign name is only trusted for a large city.
_BARE_ALTERNATE_MIN_POPULATION = 500_000


def fold(text: str) -> str:
    """Lowercase ASCII with accents removed: 'São Paulo' -> 'sao paulo'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


@dataclass(frozen=True)
class City:
    geonameid: int
    name: str
    asciiname: str
    #: ISO 3166-1 alpha-2, upper case.
    country: str
    admin1: str
    admin1_name: str
    population: int
    lat: float
    lon: float
    alternates: tuple[str, ...]

    @property
    def slug(self) -> str:
        return f"{CITY_PREFIX}{self.geonameid}"

    @property
    def primary_keys(self) -> frozenset[str]:
        """The folded forms of the city's own name."""
        return frozenset({fold(self.name), self.asciiname.lower()})


class _Gazetteer:
    def __init__(self, cities: list[City]):
        self.by_id: dict[int, City] = {c.geonameid: c for c in cities}
        self.primary: dict[str, list[City]] = {}
        self.alternate: dict[str, list[City]] = {}
        keys: list[tuple[str, int]] = []
        for city in cities:
            for key in city.primary_keys:
                self.primary.setdefault(key, []).append(city)
                keys.append((key, city.geonameid))
            for alt in city.alternates:
                key = fold(alt)
                if key not in city.primary_keys:
                    self.alternate.setdefault(key, []).append(city)
                    keys.append((key, city.geonameid))
        for bucket in (*self.primary.values(), *self.alternate.values()):
            bucket.sort(key=lambda c: -c.population)
        #: Sorted (key, geonameid) pairs, so a prefix search is two bisects.
        self.sorted_keys = sorted(set(keys))


@lru_cache(maxsize=1)
def _gazetteer() -> _Gazetteer:
    cities: list[City] = []
    with _TABLE.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            cities.append(City(
                geonameid=int(f[0]), name=f[1], asciiname=f[2], country=f[3], admin1=f[4],
                admin1_name=f[5], population=int(f[6] or 0), lat=float(f[7]), lon=float(f[8]),
                alternates=tuple(a for a in f[10].split("|") if a) if len(f) > 10 else (),
            ))
    return _Gazetteer(cities)


_COUNTRY_BY_ALPHA2: dict[str, Country] = {c.alpha2.upper(): c for c in COUNTRIES}
_ALPHA2_BY_SLUG: dict[str, str] = {c.slug: c.alpha2.upper() for c in COUNTRIES}


def is_city_slug(slug: str) -> bool:
    return city_by_slug(slug) is not None


def city_by_slug(slug: str) -> City | None:
    if not slug.startswith(CITY_PREFIX):
        return None
    try:
        geonameid = int(slug[len(CITY_PREFIX):])
    except ValueError:
        return None
    return _gazetteer().by_id.get(geonameid)


def city_country(city: City) -> Country | None:
    return _COUNTRY_BY_ALPHA2.get(city.country)


def city_for_place(
    place: str,
    country_slugs: set[str],
    state_codes: set[str] | None = None,
    reserved: frozenset[str] = frozenset(),
    weak: frozenset[str] = frozenset(),
) -> City | None:
    """The city a posting's place names, or None.

    `place` is one place string ("Stockholm, Sweden", "Portland, OR, USA").
    Its comma- and dash-separated segments are tried in order; the first that
    names a city decides. `country_slugs` are the countries the place already
    names (or implies through a metro): when there are any, only cities in
    them count, and the city's alternate names count too ("Bangalore, India").
    With none, only a city's own name counts, and only a dominant namesake
    (`_BARE_MIN_POPULATION`, `_BARE_DOMINANCE`). `state_codes` (GeoNames admin1
    codes, "OR") pick between same-named cities in one country. A segment in
    `reserved` (a country, a state, a region, "remote") is never a city:
    "Remote, Mexico" is the country, not Mexico City by its alternate name.
    A segment in `weak` (a state named like a city: Washington, New York) is
    tried only after every other segment: "United States, Washington, Redmond"
    is Redmond.
    """
    table = _gazetteer()
    allowed = {_ALPHA2_BY_SLUG[s] for s in country_slugs if s in _ALPHA2_BY_SLUG}
    segments = place_segments(place)
    segments = [seg for seg in segments if seg not in weak] + [seg for seg in segments if seg in weak]
    for segment in segments:
        if segment in reserved:
            continue
        if allowed:
            # A city's own name first; an old or foreign name only where no
            # city carries this one as its own ("Portland, OH" is not Sandusky,
            # once called Portland; "Bangalore, India" is Bengaluru).
            found = [c for c in table.primary.get(segment, ()) if c.country in allowed]
            if not found:
                found = [c for c in table.alternate.get(segment, ()) if c.country in allowed]
            if not found:
                continue
            if state_codes:
                # A named state is a constraint, not a hint: "Hudson,
                # Massachusetts" has no Hudson of 15,000 in the table, and
                # falling back would find Jersey City by its old name.
                found = [c for c in found if c.admin1 in state_codes]
                if not found:
                    return None
            return max(found, key=lambda c: c.population)
        own = table.primary.get(segment, [])
        others = table.alternate.get(segment, [])
        if not own and not others:
            continue
        everyone = sorted({c.geonameid: c for c in (*own, *others)}.values(), key=lambda c: -c.population)
        top = everyone[0]
        runner_up = everyone[1].population if len(everyone) > 1 else 0
        floor = _BARE_MIN_POPULATION if top in own else _BARE_ALTERNATE_MIN_POPULATION
        if top.population >= floor and top.population >= _BARE_DOMINANCE * runner_up:
            return top
        return None
    return None


def place_segments(place: str) -> list[str]:
    """A place's folded segments, split on commas, " - ", " / ", ";" and brackets."""
    folded = fold(place)
    for sep in (" - ", " / ", "(", ")", ";"):
        folded = folded.replace(sep, ",")
    return [seg.strip(" .") for seg in folded.split(",") if seg.strip(" .")]


def search_cities(query: str, limit: int = 8) -> list[tuple[City, str | None]]:
    """Cities whose name or an alternate name starts with `query`.

    Ranked by an exact match first, then population. Each result carries the
    alternate name it matched by, when it was not the city's own name, so the
    search can say "Bengaluru (Bangalore)".
    """
    needle = fold(query)
    if len(needle) < 2:
        return []
    table = _gazetteer()
    start = bisect.bisect_left(table.sorted_keys, (needle, -1))
    hits: dict[int, tuple[City, str | None, bool]] = {}
    for key, geonameid in table.sorted_keys[start:]:
        if not key.startswith(needle):
            break
        city = table.by_id[geonameid]
        via = None if key in city.primary_keys else next(
            (alt for alt in city.alternates if fold(alt) == key), None,
        )
        exact = key == needle
        best = hits.get(geonameid)
        if best is None or (exact and not best[2]) or (best[1] is not None and via is None):
            hits[geonameid] = (city, via, exact or (best[2] if best else False))
    ranked = sorted(hits.values(), key=lambda h: (not h[2], h[1] is not None, -h[0].population))
    # Old and foreign names only when no city answers to the query by its own
    # name: "portland" is the three Portlands, not Sandusky (once Portland);
    # "bangalore" is Bengaluru because no city is called that today.
    if any(via is None for _, via, _ in ranked):
        ranked = [hit for hit in ranked if hit[1] is None]
    return [(city, via) for city, via, _ in ranked[:limit]]
