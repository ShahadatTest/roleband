"""Location-group matching and canonical role/domain classification."""

from __future__ import annotations

import re
from collections.abc import Sequence

from tracker.levels.titles import company_domains
from tracker.schema import RawJob
from tracker.taxonomy.cities import city_country
from tracker.taxonomy.domains import DOMAIN_GROUPS, match_domains, source_category
from tracker.taxonomy.locations import (
    LOCATION_GROUPS,
    city_for_piece,
    countries_for,
    location_pieces,
    metro_of_city,
    region_countries,
    region_places,
)
from tracker.taxonomy.roles import classify_department, classify_role, is_frontline_associate
from tracker.taxonomy.title_parse import normalize, org_path


def _depth(slug: str) -> int:
    """Nesting depth of a group (leaf metros/countries deeper than their parent).

    Cycle-guarded, matching `location_group_ancestors`. With three levels
    (region -> country -> metro) an accidental `parent` cycle would spin here
    forever rather than return a wrong answer, and this runs per job.
    """
    depth = 0
    cur: str | None = slug
    seen: set[str] = {slug}
    while cur:
        cur = LOCATION_GROUPS.get(cur, {}).get("parent")
        if cur and cur not in seen:
            seen.add(cur)
            depth += 1
        else:
            break
    return depth


def location_groups_for(locations: list[str]) -> list[str]:
    """Every taxonomy location group these raw strings fall into (no cities).
    See `location_slugs_for`, which adds the gazetteer cities."""
    return _resolve(locations)[0]


#: Separates the places one location string lists: "Chicago; San Francisco",
#: "Denver, CO or Long Beach, CA" (lowercase "or": "Portland, OR" is a state).
_PLACE_LIST_RE = re.compile(r";|\s+or\s+")


def specific_places(text: str) -> frozenset[str]:
    """The cities and metro areas a short place string names (`city_<id>`
    and `kind="metro"` groups): what tells one place's pay band from
    another's. A country or region is not specific, since a
    US-wide band and a Bay Area band both lie in the United States."""
    return frozenset(
        slug for slug in location_slugs_for([text])
        if slug.startswith("city_") or LOCATION_GROUPS.get(slug, {}).get("kind") == "metro"
    )


def first_place(locations: Sequence[str]) -> frozenset[str]:
    """`specific_places` of the place a posting names first: its first
    location, and of one that lists several, the first it lists. Empty for a
    posting whose first place names no city ("Remote", "United States")."""
    for location in locations:
        for part in _PLACE_LIST_RE.split(location):
            if part.strip():
                return specific_places(part.strip())
    return frozenset()


def location_slugs_for(locations: list[str]) -> list[str]:
    """`location_groups_for` plus the cities the places name, as stored on a
    job: taxonomy groups first (deepest first), then `city_<geonameid>`."""
    groups, cities = _resolve(locations)
    return groups + cities


def _resolve(locations: list[str]) -> tuple[list[str], list[str]]:
    """Every location-group slug these raw location strings fall into.

    Leaves match directly: `metro` groups by substring, `country` groups by
    parsed country (`countries_for`) or a city-substring fallback (bare "London").
    A matched group then implies its whole ancestor chain — a metro implies its
    country, a country implies its region — so a Munich posting yields
    [germany, europe] and a bare "Cupertino" yields [silicon_valley,
    united_states]. `region` groups never match directly; they surface only via a
    member country. The result is ordered most-specific (deepest) first, so `[0]`
    stays the fine leaf for the comp/primary axis. All matching groups are returned
    regardless of the user's tracked set — the enabled filter is applied downstream
    at scope-gate time, so toggling a location on later does not re-scrape history.

    Cities: each place is also looked up in the city gazetteer, and the city
    it names is appended as `city_<geonameid>` AFTER the taxonomy groups, so
    `[0]` never becomes a city. A city also implies its country and region, so
    a bare "Berlin" or "Tokyo", which no taxonomy group matches, lands in
    Germany or Japan.
    """
    pieces = location_pieces(locations)
    if not pieces:
        return [], []
    matched: set[str] = countries_for(locations) & set(LOCATION_GROUPS)
    # City substrings are read per place, and a place that names a country
    # decides which country its city is in: "San Jose, Costa Rica" is not the
    # Bay Area and "London, Ontario, Canada" is not the UK. A metro matches
    # only where its place names no country or its own; a country's city
    # fallback only where its place names no other country.
    cities: list[str] = []
    # Countries a place reaches only by naming a region. Sorted
    # after every place actually named, so `[0]` (the comp axis) is a named
    # place, or the region itself, never an arbitrary member country.
    by_region: set[str] = set()
    for piece in pieces:
        named = countries_for([piece])
        if not named:
            regions = region_places(piece)
            for slug in regions:
                if LOCATION_GROUPS.get(slug, {}).get("kind") == "country":
                    matched.add(slug)
                    continue
                matched.add(slug)
                by_region.update(c for c in region_countries(slug) if c not in matched)
            if regions:
                continue
        here: set[str] = set()
        for slug, group in LOCATION_GROUPS.items():
            subs = group.get("substrings", ())
            if not subs or not any(sub in piece for sub in subs):
                continue
            home = group.get("parent") if group.get("kind") == "metro" else slug
            if not named or home in named:
                matched.add(slug)
                here.add(home)
        # The countries this place names, or implies through a metro or a
        # city fallback, decide which city it can be ("Cupertino" is the one
        # in the US because Silicon Valley matched).
        city = city_for_piece(piece, named or here)
        if city is None:
            continue
        country = city_country(city)
        if country is None or (named and country.slug not in named):
            continue
        matched.add(country.slug)
        metro = metro_of_city(city)
        if metro:
            matched.add(metro)
        if city.slug not in cities:
            cities.append(city.slug)
    # Imply every matched group's ancestor chain (metro -> country -> region).
    for slug in list(matched):
        cur = LOCATION_GROUPS.get(slug, {}).get("parent")
        while cur and cur not in matched:
            matched.add(cur)
            cur = LOCATION_GROUPS.get(cur, {}).get("parent")
    by_region -= matched
    for slug in list(by_region):
        # A region's sub-regions come with it ("EMEA" reaches the Gulf).
        cur = LOCATION_GROUPS.get(slug, {}).get("parent")
        while cur and cur not in matched and cur not in by_region:
            matched.add(cur)
            cur = LOCATION_GROUPS.get(cur, {}).get("parent")
    matched |= by_region
    order = {slug: i for i, slug in enumerate(LOCATION_GROUPS)}
    return sorted(
        matched, key=lambda s: (s in by_region, -_depth(s), order.get(s, len(order))),
    ), cities


def match_location_groups(job: RawJob) -> list[str]:
    """Location slugs stored on a posting: groups, then cities (`location_slugs_for`)."""
    return location_slugs_for(job.locations)


def classify_family(job: RawJob) -> str | None:
    """Title wins; department/team only refine generic or unknown titles. An
    hourly frontline role is filed in no discipline, whatever its department."""
    if is_frontline_associate(job.title):
        return None
    department = " ".join(p for p in (job.department, job.team) if p)
    # Physical production leadership is operations. The title alone cannot
    # distinguish a factory from a publisher, and its product/team suffix is
    # no engineering role ("Head of Production, Compute & Comms").
    if (re.search(r"\bhead of production\b", job.title, re.I)
            and re.search(r"\bmanufacturing\b", department, re.I)):
        return "operations_facilities"
    title_family = classify_role(job.title)
    if title_family not in (None, "software_engineering"):
        return title_family
    return classify_department(department) or title_family


# Lives in the taxonomy layer (role_catalog tallies need it below enrich);
# re-exported here because it is part of this module's classification surface.
__all__ = [
    "classify_domain",
    "classify_domains",
    "classify_family",
    "location_groups_for",
    "match_location_groups",
    "source_category",
]

_DOMAIN_ORDER = {group.slug: i for i, group in enumerate(DOMAIN_GROUPS)}


def classify_domains(job: RawJob) -> list[str]:
    """Every world this work is about, primary first; [] when nothing says.

    Multi-label union across the signal ladder — the company's own internal
    vocabulary ("SSD Ops Integration" is Amazon delivery and no general
    lexicon says so), the employer's category field, the title's org path, and
    finally the whole title (the domain often sits in the role head itself:
    "Sr. Supply Chain Manager", which the org-path read deliberately skips).
    A single first-match label would let the scope gate drop a two-world
    posting ("ML EM, Ads Ranking") for a user who enabled the other world;
    recording every world keeps the axis fail-soft, since the gate passes a
    row when ANY of its domains is enabled.

    Ordering: company-vocabulary hits first (the employer knows its own orgs
    better than our lexicon), then generic hits in `DOMAIN_GROUPS` declared
    order, so `[0]` is the single label shown for display.

    `[]` is a real answer. Guessing a domain would hide a posting behind a
    filter the user set for a different kind of work.
    """
    category = source_category(job)
    title = normalize(job.title)
    own = company_domains(job.company, f"{category} {title}")
    generic = sorted(
        {
            slug
            for text in (category, org_path(job.title), title)
            for slug in match_domains(text)
        },
        key=lambda slug: _DOMAIN_ORDER.get(slug, len(_DOMAIN_ORDER)),
    )
    return own + [slug for slug in generic if slug not in set(own)]


def classify_domain(job: RawJob) -> str | None:
    """Primary domain (first of `classify_domains`), or None when nothing says."""
    domains = classify_domains(job)
    return domains[0] if domains else None
