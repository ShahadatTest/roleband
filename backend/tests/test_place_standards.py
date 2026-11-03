"""Places follow the world's standards.

Countries carry ISO 3166-1 codes and their Unicode CLDR English names, regions
their UN M49 code, the European Union its CLDR membership, and cities come
from the GeoNames gazetteer as `city_<geonameid>`. These tests pin what that
means for a person typing a place, a posting naming one, a saved scope holding
one and a source being asked about one. Pure: no database, no network.
"""

from __future__ import annotations

from pathlib import Path

from tracker.connectors.listing.base import country_manifest
from tracker.scope.places import search_places
from tracker.taxonomy.cities import city_by_slug, search_cities
from tracker.taxonomy.countries import BY_SLUG, COUNTRIES, UNIONS
from tracker.taxonomy.locations import (
    LOCATION_GROUPS,
    REGIONS,
    canonical_location_slugs,
    countries_for,
    location_group_ancestors,
    location_group_covers,
    location_node,
    uncovered_groups,
)
from tracker.vendored import by_name

STOCKHOLM = "city_2673730"
GOTHENBURG = "city_2711537"
SAN_JOSE_CA = "city_5392171"
LONDON_ONTARIO = "city_6058560"


# --- the standards themselves ---------------------------------------------- #


def test_country_names_are_cldr_and_the_old_names_still_match():
    assert BY_SLUG["turkey"].display == "Türkiye"
    assert BY_SLUG["ivory_coast"].display == "Côte d’Ivoire"
    # CLDR's standard name carries "SAR China"; its short form is what people say.
    assert BY_SLUG["hong_kong"].display == "Hong Kong"
    assert BY_SLUG["myanmar"].display == "Myanmar"
    # Untouched where CLDR already agreed.
    assert BY_SLUG["united_states"].display == "United States"
    assert BY_SLUG["uk"].display == "United Kingdom"
    # A posting in the old spelling, or with the accent, still resolves.
    assert countries_for(["Istanbul, Turkey"]) == {"turkey"}
    assert countries_for(["Istanbul, Türkiye"]) == {"turkey"}
    assert countries_for(["Abidjan, Côte d'Ivoire"]) == {"ivory_coast"}


def test_a_rename_never_changes_what_a_source_is_asked():
    """google, microsoft and workday send a country's name to the board's own
    search. That name is frozen as `query_name`, so adopting CLDR's "Türkiye"
    for display cannot silently turn into a query the board does not know."""
    manifest = country_manifest(lambda c: c.query_name)
    assert manifest["turkey"] == ["Turkey"]
    assert manifest["ivory_coast"] == ["Ivory Coast"]
    assert manifest["united_states"] == ["United States"]


def test_regions_name_their_m49_area_and_answer_to_its_name():
    assert REGIONS["north_america"]["m49"] == "021"
    assert REGIONS["latin_america"]["m49"] == "419"
    # Not M49 areas, said so rather than forced onto one.
    assert REGIONS["middle_east"]["m49"] is None
    assert REGIONS["gulf"]["m49"] is None
    assert search_places("northern america")["places"][0]["slug"] == "north_america"
    assert search_places("eastern asia")["places"][0]["slug"] == "east_asia"


def test_the_european_union_is_cldrs_27_all_in_europe():
    (eu,) = UNIONS
    assert eu.slug == "european_union" and eu.display == "European Union"
    assert len(eu.members) == 27
    assert {"germany", "france", "ireland", "cyprus"} <= set(eu.members)
    assert "uk" not in eu.members and "switzerland" not in eu.members
    assert all(LOCATION_GROUPS[m]["parent"] == "europe" for m in eu.members)


def test_the_city_table_is_the_pinned_geonames_snapshot():
    snapshot = by_name("geonames-cities15000")
    table = Path(__file__).resolve().parents[2] / snapshot.local_path
    head = table.read_text(encoding="utf-8").splitlines()[:4]
    assert f"Snapshot {snapshot.ref}" in head[1]
    assert "CC-BY-4.0" in head[1], "the attribution travels with the data"
    alpha2 = {c.alpha2.upper() for c in COUNTRIES}
    rows = [line.split("\t") for line in table.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    assert len(rows) > 30_000
    assert len({r[0] for r in rows}) == len(rows), "a GeoNames id is one city"
    assert all(r[3] in alpha2 for r in rows), "only countries the taxonomy tracks"


# --- a city in the tree ------------------------------------------------------ #


def test_a_city_hangs_off_its_metro_or_its_country():
    assert location_node(STOCKHOLM) == {"display": "Stockholm", "enabled": False, "kind": "city", "parent": "sweden"}
    assert location_group_ancestors(STOCKHOLM) == ["sweden", "europe"]
    # One of a metro's named cities, in the metro's country.
    assert location_group_ancestors(SAN_JOSE_CA) == ["silicon_valley", "united_states", "north_america"]
    # The same name in another country is not that metro.
    assert location_group_ancestors(LONDON_ONTARIO) == ["canada", "north_america"]
    assert location_node("city_0") is None
    assert location_node("city_nonsense") is None


def test_a_saved_scope_keeps_real_cities_in_order_and_drops_the_rest():
    assert canonical_location_slugs([GOTHENBURG, "city_0", STOCKHOLM, "uk", "no_such_place"]) == [
        "uk", STOCKHOLM, GOTHENBURG,
    ]


def test_a_source_asked_about_the_country_covers_its_cities():
    """Coverage flows down to a city exactly as to a metro: tracking only
    Stockholm must still plan the `sweden` query, and a source that can only
    be asked about Germany does not cover it."""
    assert location_group_covers("sweden", STOCKHOLM)
    assert location_group_covers("europe", STOCKHOLM)
    assert not location_group_covers("germany", STOCKHOLM)
    assert not location_group_covers(STOCKHOLM, "sweden"), "a city never covers its country"
    assert uncovered_groups({"sweden"}, {STOCKHOLM}) == set()
    assert uncovered_groups({"germany"}, {STOCKHOLM}) == {STOCKHOLM}


# --- search ------------------------------------------------------------------ #


def _places(query: str, limit: int = 6) -> list[tuple[str, str, str]]:
    return [(p["display"], p["kind"], p["context"]) for p in search_places(query, limit)["places"]]


def test_a_person_finds_their_city_by_its_name_or_the_one_they_grew_up_with():
    assert _places("stockholm") == [("Stockholm", "city", "Sweden")]
    bengaluru = search_places("bangalore")["places"][0]
    assert (bengaluru["display"], bengaluru["matched_by"]) == ("Bengaluru", "Bangalore")
    assert search_places("kiev")["places"][0]["display"] == "Kyiv"
    # Namesakes say where they are.
    assert _places("portland")[:3] == [
        ("Portland", "city", "Oregon, United States"),
        ("Portland", "city", "Maine, United States"),
        ("Portland", "city", "Texas, United States"),
    ]


def test_a_country_outranks_a_town_and_an_old_name_never_crowds_a_real_one():
    assert _places("georgia") == [("Georgia", "country", "Middle East")]
    # Sandusky, Ohio was once Portland: not an answer to "portland".
    assert all(display == "Portland" for display, _, _ in _places("portland"))
    assert search_places("turkey")["places"][0]["display"] == "Türkiye"
    assert search_places("holland")["places"][0]["display"] == "Netherlands"


def test_a_metro_stands_for_the_city_it_is_named_after():
    assert _places("london") == [("London", "metro", "United Kingdom"), ("London", "city", "Ontario, Canada")]
    assert [p["kind"] for p in search_places("new york")["places"]] == ["metro"]


def test_a_union_is_offered_beside_the_places():
    assert [u["slug"] for u in search_places("eu")["unions"]] == ["european_union"]
    assert [u["slug"] for u in search_places("european")["unions"]] == ["european_union"]
    assert search_places("stockholm")["unions"] == []


def test_search_is_prefix_and_needs_two_letters():
    assert search_cities("s") == []
    assert search_places("") == {"places": [], "unions": []}
    assert city_by_slug(STOCKHOLM) in [city for city, _ in search_cities("stockh")]
