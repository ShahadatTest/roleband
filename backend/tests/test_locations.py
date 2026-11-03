"""City normalization: free-form posting locations -> canonical office labels.

The same office must collapse to ONE label regardless of source phrasing, and
non-offices (country-only, "Multiple Locations") must yield nothing — a wrong
merge or a phantom "US" office would corrupt the per-company offices view.
"""

from __future__ import annotations

import asyncio

import pytest

from tracker.api.routers.companies import _company_locations
from tracker.enrich.classify import location_groups_for
from tracker.taxonomy.locations import countries_for, normalize_cities

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


class TestCountriesFor:
    def test_us_shapes(self):
        for raw in (
            "Mountain View, CA, USA",
            "United States, Washington, Redmond",
            "Austin, Texas, USA",
            "Denver, Colorado, USA",  # non-metro US city
            "Remote, US",
            "USA - Remote",
        ):
            assert countries_for([raw]) == {"united_states"}, raw

    def test_foreign_countries(self):
        assert countries_for(["London, England, GBR"]) == {"uk"}
        assert countries_for(["Singapore"]) == {"singapore"}
        assert countries_for(["Dublin, D, IE"]) == {"ireland"}
        assert countries_for(["Vancouver, British Columbia, Canada"]) == {"canada"}
        assert countries_for(["Munich, Germany"]) == {"germany"}

    def test_foreign_token_wins_over_colliding_state_abbrev(self):
        # ", ES"/"IT" are Spain/Italy, not US states; Germany "DE" is not Delaware.
        assert countries_for(["Madrid, MD, ES"]) == {"spain"}
        assert countries_for(["Milan, Lombardy, IT"]) == {"italy"}

    def test_no_false_us_from_substring(self):
        # "Busan" contains the letters "usa" but is not the token "usa". South
        # Korea is a real group, so the assertion is that the US is ABSENT
        # rather than that nothing matched.
        assert countries_for(["Busan, South Korea"]) == {"south_korea"}
        assert countries_for(["Seoul, Korea, South"]) == {"south_korea"}
        assert countries_for([]) == set()

    def test_a_state_name_that_is_also_a_country_needs_a_non_us_context(self):
        # Georgia is the only ISO name colliding with a US state name. Without
        # the guard, `out |= foreign` tags the country on a US posting too.
        assert countries_for(["Atlanta, Georgia, USA"]) == {"united_states"}
        assert countries_for(["Tbilisi, Georgia"]) == {"georgia"}

    def test_georgia_beside_a_place_that_is_not_georgian_is_the_us_state(self):
        # Salesforce writes "State - City" with no country: "Georgia - Atlanta"
        # beside "Illinois - Chicago" must not read as the country. With no
        # "USA", the other place decides.
        assert countries_for(["Georgia - Atlanta"]) == {"united_states"}
        assert countries_for(["Atlanta, Georgia"]) == {"united_states"}
        assert countries_for(["Georgia - Atlanta - Remote"]) == {"united_states"}
        # Negative controls, all real: Fundraise Up's "Georgia - Remote" beside
        # "Armenia - Remote", SearchAPI's "Remote - Georgia". Nothing else is
        # named, so it is the country; so is a Georgian city by any name.
        assert countries_for(["Georgia - Remote"]) == {"georgia"}
        assert countries_for(["Remote - Georgia"]) == {"georgia"}
        assert countries_for(["Georgia"]) == {"georgia"}
        assert countries_for(["Georgia (Remote), EMEA"]) == {"georgia"}
        assert countries_for(["Batumi, Georgia"]) == {"georgia"}
        assert countries_for(["Tiflis - Georgia"]) == {"georgia"}

    def test_alpha2_codes_colliding_with_a_state_abbrev_are_never_admitted(self):
        # CA/Canada, IN/India, LA/Laos, IL/Israel collide with US state codes; any
        # of them admitted would mis-tag a US posting as foreign.
        for loc, expected in [
            ("Los Angeles, CA, USA", "canada"),
            ("Indianapolis, IN, USA", "india"),
            ("New Orleans, LA, USA", "laos"),
            ("Chicago, IL, USA", "israel"),
        ]:
            assert countries_for([loc]) == {"united_states"}, loc
            assert expected not in countries_for([loc])

    def test_native_name_aliases_that_are_english_place_words_lose_to_a_state(self):
        # The country vocabulary includes Iceland's alias `island`, and Jordan is a common
        # US place name, so these read as foreign countries. The damage is not a
        # stray badge: a foreign match suppresses the `united_states` branch, so
        # a New York borough would be tagged Europe and NOT the US, invisible to
        # anyone tracking the United States.
        for loc in [
            "Staten Island, NY",
            "Rhode Island, RI",
            "Long Island City, NY",
            "West Jordan, UT",
        ]:
            assert countries_for([loc]) == {"united_states"}, loc

    def test_a_country_named_in_its_own_field_is_never_disqualified(self):
        # The rule above only fires on a token found INSIDE a larger field. A
        # country standing as its own comma field is a named country, whatever
        # sits beside it — including an alpha-2 next to a state abbrev.
        assert countries_for(["Reykjavik, Iceland"]) == {"iceland"}
        assert countries_for(["Amman, Jordan"]) == {"jordan"}
        assert countries_for(["Madrid, MD, ES"]) == {"spain"}
        # And the state must be a DIFFERENT token than the country itself, or
        # Georgia disqualifies Georgia.
        assert countries_for(["Tbilisi, Georgia"]) == {"georgia"}

    def test_multi_country_posting_returns_all(self):
        got = countries_for(["San Francisco, CA | London, UK | Singapore"])
        assert got == {"united_states", "uk", "singapore"}


class TestNormalizeCities:
    def test_same_office_collapses_across_source_phrasings(self):
        # Google, Microsoft/Workday, and Eightfold phrase Mountain View differently.
        for raw in (
            "Mountain View, CA, USA",
            "Mountain View, CA, US",
            "United States, California, Mountain View",
            "Mountain View, California, USA",
            "Mountain View",
        ):
            assert normalize_cities([raw]) == ["Mountain View, CA"], raw

    def test_country_first_workday_order_is_flipped(self):
        assert normalize_cities(["United States, Washington, Redmond"]) == ["Redmond, WA"]

    def test_uk_regions_collapse_to_uk(self):
        assert normalize_cities(["London, England, GBR"]) == ["London, UK"]
        assert normalize_cities(["Cambridge, England, GB"]) == ["Cambridge, UK"]
        # ...while the Massachusetts Cambridge stays distinct.
        assert normalize_cities(["Cambridge, MA, US"]) == ["Cambridge, MA"]

    def test_multi_location_string_splits_and_dedupes(self):
        cities = normalize_cities(
            ["San Francisco, CA | New York City, NY | Seattle, WA", "San Francisco"]
        )
        assert cities == ["San Francisco, CA", "New York, NY", "Seattle, WA"]

    def test_remote_and_non_offices(self):
        assert normalize_cities(["Remote, US"]) == ["Remote (US)"]
        assert normalize_cities(["USA - Remote"]) == ["Remote (US)"]
        # A remote place keeps the one country it names; without it every
        # remote place outside the US was one office and one pay location.
        assert normalize_cities(["Germany (Remote)", "Remote - UK", "Remote, US", "Remote"]) == [
            "Remote (Germany)", "Remote (UK)", "Remote (US)", "Remote"]
        assert normalize_cities(["Remote - Germany"]) == normalize_cities(["Germany (Remote)"])
        # Several countries or a region name no one country: bare. "or" is
        # also Oregon's code, which must not make this a US place.
        assert normalize_cities(["Remote - Germany or France"]) == ["Remote"]
        assert normalize_cities(["Remote (EMEA)"]) == ["Remote"]
        # Country-only / multiple-locations strings are not offices.
        assert normalize_cities(["US"]) == []
        assert normalize_cities(["United States, Multiple Locations, Multiple Locations"]) == []
        assert normalize_cities([]) == []

    def test_singapore_city_state(self):
        assert normalize_cities(["Singapore"]) == ["Singapore"]
        assert normalize_cities(["Singapore, Singapore, Singapore"]) == ["Singapore"]

    def test_unknown_city_degrades_to_tidied_label_not_nothing(self):
        # Never seen in an alias table, still parseable -> keep it visible.
        assert normalize_cities(["Bee Cave, Texas, USA"]) == ["Bee Cave, TX"]
        assert normalize_cities(["Zürich, Switzerland"]) == ["Zürich, Switzerland"]


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    async def execute(self, stmt, params=None):
        self.params = params
        return _Rows(self.rows)


def test_company_locations_carries_group_badges():
    # The SQL orders busiest-first; the helper adds the coarse scope-group badges.
    session = _FakeSession([("Sunnyvale, CA", 12), ("London, UK", 3), ("Boise, ID", 1)])
    out = asyncio.run(_company_locations(session, "apple"))

    assert session.params == {"slug": "apple"}
    assert [(loc["city"], loc["open_count"]) for loc in out] == [
        ("Sunnyvale, CA", 12),
        ("London, UK", 3),
        ("Boise, ID", 1),
    ]
    # Nested badges, most-specific first: a Bay Area city carries its metro AND
    # its country; London carries its metro, its country AND the Europe umbrella;
    # every US city carries the country badge, metro or not (Boise).
    assert out[0]["groups"] == ["silicon_valley", "united_states", "north_america"]
    assert out[1]["groups"] == ["london", "uk", "europe"]
    assert out[2]["groups"] == ["united_states", "north_america"]


def test_company_locations_names_the_country_group():
    """The country is named, not left for the dashboard to pick out of `groups`.

    Deepest-first ordering means `groups[0]` is a metro as often as a country,
    so a caller grouping by country needs this field rather than a positional
    guess.
    """
    session = _FakeSession([("Sunnyvale, CA", 12), ("London, UK", 3), ("Reykjavik, Iceland", 1)])
    out = asyncio.run(_company_locations(session, "apple"))

    assert [loc["country"] for loc in out] == ["united_states", "uk", "iceland"]
    # Not the leaf and not the umbrella: the metro and the region are both wrong
    # answers that a positional guess would return.
    assert out[0]["groups"][0] == "silicon_valley"
    assert out[0]["groups"][-1] == "north_america"


def test_company_locations_keeps_a_city_whose_country_is_unresolved():
    """`None` is a real answer and the row survives it.

    `de` is deliberately excluded from the US state tokens (mis-tagging
    Frankfurt is the worse error), so Wilmington is a real office with no
    country. Dropping it would silently hide open roles. (Toronto, ON resolves
    to a Canadian province, and that is asserted too.)
    """
    session = _FakeSession([("Wilmington, DE", 4), ("Toronto, ON", 2)])
    out = asyncio.run(_company_locations(session, "amazon"))

    assert [loc["city"] for loc in out] == ["Wilmington, DE", "Toronto, ON"]
    assert [loc["country"] for loc in out] == [None, "canada"]
    assert [loc["open_count"] for loc in out] == [4, 2]


# -- silicon_valley coverage ------------------------------------------------ #


@pytest.mark.parametrize("raw", [
    "Redwood City, CA",
    "Redwood City, California, United States of America",  # Electronic Arts
    "US, CA, Santa Clara",  # Nvidia's Workday order
    "Santa Clara, California, USA",
    "San Bruno, CA, USA",  # YouTube
    "Foster City, CA",
    "Milpitas, California",
    "San Mateo, CA, USA",
    "San Carlos, California",
    "Belmont, CA",
    "Fremont, CA, USA",
    "US, CA, Fremont",
])
def test_bay_area_cities_are_silicon_valley(raw):
    groups = location_groups_for([raw])
    assert groups[0] == "silicon_valley" and "united_states" in groups, raw


@pytest.mark.parametrize("raw", [
    "Redwood Falls, MN",  # a similarly named town, not the Bay Area
    "San Carlos, Philippines",
    "San Mateo, Rizal, Philippines",
    "Belmont, MA",
    "Fremont, NE",
    "Fremont, Ohio",
])
def test_namesakes_elsewhere_are_not_silicon_valley(raw):
    assert "silicon_valley" not in location_groups_for([raw]), raw


@pytest.mark.parametrize(
    ("raw", "country", "not_groups"),
    [
        # A US metro's city name in another country is that country's city.
        ("San Jose, Costa Rica", "costa_rica", {"silicon_valley", "united_states"}),
        ("Santa Clara, Cuba", "cuba", {"silicon_valley", "united_states"}),
        # A UK city fallback in another country likewise.
        ("London, Ontario, Canada", "canada", {"london", "uk"}),
        ("London, Kentucky, USA", "united_states", {"london", "uk"}),
    ],
)
def test_a_place_naming_a_country_decides_where_its_city_is(raw, country, not_groups):
    groups = location_groups_for([raw])
    assert country in groups, (raw, groups)
    assert not (set(groups) & not_groups), (raw, groups)


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        # Unqualified cities keep matching, and their own country beside them.
        (["San Jose"], {"silicon_valley", "united_states"}),
        (["San Jose, CA, USA"], {"silicon_valley", "united_states"}),
        (["London"], {"london", "uk"}),
        (["London, England, United Kingdom"], {"london", "uk"}),
        # Each place is read on its own: one posting in both San Joses is both.
        (["San Jose, CA", "San Jose, Costa Rica"], {"silicon_valley", "united_states", "costa_rica"}),
        (["San Jose, CA | London, Ontario, Canada"], {"silicon_valley", "united_states", "canada"}),
    ],
)
def test_cities_in_their_own_country_still_match(locations, expected):
    groups = set(location_groups_for(locations))
    assert expected <= groups, (locations, groups)
    if "canada" in expected:
        assert "uk" not in groups, "London, Ontario sits beside a US place, still not the UK"


def test_a_us_place_elsewhere_in_the_posting_does_not_move_a_foreign_city():
    """Countries are read per place, not per posting: Boston makes the posting
    American, not San Jose, Costa Rica."""
    groups = location_groups_for(["San Jose, Costa Rica", "Boston, MA"])
    assert {"costa_rica", "united_states"} <= set(groups)
    assert "silicon_valley" not in groups


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Boards that publish one free-text place and no country (Deel).
        ("Stockholm", "sweden"), ("Milan", "italy"), ("Warsaw", "poland"),
        ("Vienna", "austria"), ("Munich", "germany"), ("Helsinki", "finland"),
        ("Amsterdam", "netherlands"), ("Paris", "france"), ("Athens", "greece"),
        ("Sydney", "australia"), ("Columbus", "united_states"),
        ("Salt Lake City", "united_states"),
        # Workday site labels that name a campus, not a country (snap).
        ("Abingdon - 141 Park Drive", "uk"),
    ],
)
def test_a_bare_city_resolves_to_its_country(raw, expected):
    """Locations fail CLOSED, so a posting no group matches is invisible."""
    assert expected in location_groups_for([raw]), raw


@pytest.mark.parametrize(
    ("raw", "expected", "not_group"),
    [
        ("Milan, MI", "united_states", "italy"),
        ("Vienna, VA", "united_states", "austria"),
        ("Amsterdam, NY", "united_states", "netherlands"),
        ("Paris, TX", "united_states", "france"),
        ("Athens, GA", "united_states", "greece"),
        ("Warsaw, IN", "united_states", "poland"),
        ("Abingdon, VA", "united_states", "uk"),
        ("Portland, Victoria, Australia", "australia", "united_states"),
        ("Sydney, Nova Scotia, Canada", "canada", "australia"),
    ],
)
def test_a_bare_city_never_beats_a_named_country(raw, expected, not_group):
    """The fallback is for a place that names no country; one that does decides
    where its city is (the same rule as San Jose, Costa Rica)."""
    groups = location_groups_for([raw])
    assert expected in groups and not_group not in groups, (raw, groups)



@pytest.mark.parametrize(("raw", "expected", "not_group"), [
    # A Canadian place written the American way.
    ("Toronto, ON", "canada", "united_states"),
    ("Vancouver, BC", "canada", "united_states"),
    ("Montreal, Quebec", "canada", "united_states"),
    ("London, ON", "canada", "uk"),
    # ...and the places that only look Canadian.
    ("Ontario, CA", "united_states", "canada"),
    ("Vancouver, WA", "united_states", "canada"),
    ("Amsterdam, NL", "netherlands", "canada"),
    ("Lima, PE", "peru", "canada"),
])
def test_a_canadian_province_names_canada_and_nothing_else_does(raw, expected, not_group):
    groups = location_groups_for([raw])
    assert expected in groups and not_group not in groups, (raw, groups)


@pytest.mark.parametrize(("raw", "expected"), [
    # "and" is Andorra's alpha-3 and "St" São Tomé's alpha-2. Read as
    # words, they can misclassify a conjunction as a country and hide the real place.
    ("London and Remote", "uk"),
    ("New York and San Francisco", "united_states"),
    ("Paris and London", "france"),
])
def test_an_english_word_is_not_a_country_code(raw, expected):
    groups = location_groups_for([raw])
    assert expected in groups and "andorra" not in groups, (raw, groups)
    assert "sao_tome_and_principe" not in location_groups_for(["St. Albans"])


@pytest.mark.parametrize(("raw", "expected"), [
    ("Remote - USA", "united_states"),
    ("Berlin DEU", "germany"),
    ("Remote - GBR", "uk"),
    ("Andorra la Vella, AND", "andorra"),
])
def test_a_country_code_written_as_one_still_counts(raw, expected):
    assert expected in location_groups_for([raw]), raw


@pytest.mark.parametrize("place,country,not_country", [
    ("Korea", "south_korea", "north_korea"),          # TSMC's board string
    ("Seoul, Korea", "south_korea", "north_korea"),
    ("North Korea", "north_korea", "south_korea"),     # "korea" inside it is not a second country
    ("Equatorial Guinea", "equatorial_guinea", "guinea"),
    ("Papua New Guinea", "papua_new_guinea", "guinea"),
    ("South Sudan", "south_sudan", "sudan"),
    ("Sydney, New South Wales, Australia", "australia", "uk"),  # a state holding a UK nation
    ("NSW, New South Wales", "australia", "uk"),
])
def test_a_country_named_only_inside_another_countrys_name_is_not_named(place, country, not_country):

    found = countries_for([place])
    assert country in found and not_country not in found, found


def test_two_countries_named_in_their_own_right_are_both_kept():

    assert {"guinea", "equatorial_guinea"} <= countries_for(["Guinea; Equatorial Guinea"])
    assert {"guinea", "equatorial_guinea"} <= countries_for(["Conakry, Guinea, Malabo, Equatorial Guinea"])


# --- A place that names only a region ---

@pytest.mark.parametrize("place,includes,excludes", [
    # Shopify's remote roles: the Americas reach the US and Brazil, not Europe.
    ("Americas", {"north_america", "latin_america", "united_states", "canada", "brazil"}, {"germany", "uk"}),
    ("Remote - EMEA", {"europe", "middle_east", "gulf", "africa", "germany", "uae", "nigeria"}, {"united_states", "india"}),
    ("APAC", {"east_asia", "southeast_asia", "south_asia", "oceania", "japan", "australia"}, {"germany", "united_states"}),
    ("ANZ", {"australia", "new_zealand", "oceania"}, {"japan", "fiji"}),
    ("Europe (Remote)", {"europe", "france"}, {"united_states"}),
    ("LATAM", {"latin_america", "mexico"}, {"united_states"}),
])
def test_a_region_only_place_counts_as_its_regions_and_their_countries(place, includes, excludes):
    groups = set(location_groups_for([place]))
    assert includes <= groups, includes - groups
    assert not excludes & groups, excludes & groups


@pytest.mark.parametrize("place", ["Global", "Worldwide", "Anywhere", "Remote"])
def test_a_place_that_names_no_region_stays_unplaced(place):
    assert location_groups_for([place]) == []


def test_a_region_beside_a_named_place_names_only_that_place():
    assert set(location_groups_for(["London, Europe"])) == {"london", "uk", "europe"}


def test_the_primary_group_is_a_named_place_or_the_region_never_a_member_country():
    assert location_groups_for(["Americas"])[0] == "north_america"
    assert location_groups_for(["Toronto", "Americas"])[0] == "canada"
