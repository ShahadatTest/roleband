"""Apple's country codes are Apple's own, never ISO ones.

An ISO alpha-3 code fails three ways on Apple's search: `IND` is a US place, so
India would collect US roles and report itself covered; `SWE` and `JPN` are part
of Sweden and Japan, so the rows look right and most of the country is missing.
Each assertion below fails for a table built from ISO codes.
"""

from __future__ import annotations

import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing import adapter_location_gaps
from tracker.connectors.listing.apple import APPLE_LOCATION_CODES
from tracker.connectors.listing.apple_places import APPLE_COUNTRY_CODES
from tracker.taxonomy.countries import BY_SLUG

STOCKHOLM = "city_2673730"


@pytest.mark.parametrize(("slug", "code"), [("india", "INDC"), ("sweden", "SWEC"), ("japan", "JPNC")])
def test_a_country_whose_iso_code_is_another_place_uses_apples_code(slug, code):
    assert APPLE_COUNTRY_CODES[slug] == code
    assert APPLE_COUNTRY_CODES[slug] != BY_SLUG[slug].alpha3.upper()


def test_the_countries_shipped_before_keep_their_codes():
    assert APPLE_LOCATION_CODES["united_states"] == ["postLocation-USA"]
    assert APPLE_LOCATION_CODES["singapore"] == ["postLocation-SGP"]
    # The city code rides with the country's: GBR alone is not assumed to hold London.
    assert APPLE_LOCATION_CODES["uk"] == ["postLocation-GBR", "postLocation-LND"]


def test_every_code_is_a_bare_code_the_search_prefixes():
    assert all(code and not code.startswith("postLocation-") for code in APPLE_COUNTRY_CODES.values())
    assert set(APPLE_COUNTRY_CODES) <= set(BY_SLUG)


def test_stockholm_is_searched_through_sweden():
    assert adapter_location_gaps("apple", [STOCKHOLM]) == []
    adapter = build_adapter("apple", "apple", location_groups=[STOCKHOLM])
    assert adapter.planned_location_terms() == ["postLocation-SWEC"]


def test_only_the_tracked_places_are_sent():
    adapter = build_adapter("apple", "apple", location_groups=["sweden", "japan"])
    assert sorted(adapter.planned_location_terms()) == ["postLocation-JPNC", "postLocation-SWEC"]
