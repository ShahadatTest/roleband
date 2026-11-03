"""The places a Google results card lists.

A card names a few places and folds the rest into "+2 more". Only that marker is
dropped: a city whose name holds "more" is a place a person filters by. The
country the listing was searched under is kept beside them only when no listed
place already lies in it.
"""

from __future__ import annotations

from tracker.connectors.listing.google import GoogleAdapter
from tracker.enrich.classify import location_slugs_for


def _card(places: str) -> str:
    return (
        '<html><body><ul><li><a aria-label="Learn more about Staff Engineer" '
        'href="jobs/results/123456-staff-engineer">Staff Engineer</a>'
        f'<span><i>place</i>{places}</span></li></ul></body></html>'
    )


def test_a_city_named_with_more_is_kept_and_the_marker_is_dropped():
    [job] = GoogleAdapter("google")._parse_cards(
        _card("Baltimore, MD, USA; Livermore, CA, USA; +2 more"), "United States",
    )
    assert job.locations == ["Baltimore, MD, USA", "Livermore, CA, USA"]


def test_the_marker_is_dropped_however_it_is_spaced():
    [job] = GoogleAdapter("google")._parse_cards(_card("Morelia, Mexico; + 11  MORE"), "Mexico")
    assert job.locations == ["Morelia, Mexico"]


def test_a_searched_country_a_listed_place_lies_in_is_not_added_as_a_place():
    [job] = GoogleAdapter("google")._parse_cards(_card("Sunnyvale, CA, USA"), "United States")
    assert job.locations == ["Sunnyvale, CA, USA"]
    # The posting still files under the country it was found in.
    assert {"silicon_valley", "united_states", "north_america"} <= set(location_slugs_for(job.locations))


def test_a_searched_country_hidden_behind_more_is_kept():
    # Searched under the UK, the card lists only its German and Swiss offices:
    # the UK one is folded into "+1 more", and the country is the only trace of it.
    [job] = GoogleAdapter("google")._parse_cards(
        _card("Hamburg, Germany; Zürich, Switzerland; +1 more"), "United Kingdom",
    )
    assert job.locations == ["Hamburg, Germany", "Zürich, Switzerland", "United Kingdom"]
    assert "uk" in location_slugs_for(job.locations)


def test_a_card_that_lists_no_place_keeps_the_searched_country():
    html = (
        '<html><body><ul><li><a aria-label="Learn more about Staff Engineer" '
        'href="jobs/results/123456-staff-engineer">Staff Engineer</a></li></ul></body></html>'
    )
    [job] = GoogleAdapter("google")._parse_cards(html, "United States")
    assert job.locations == ["United States"]
