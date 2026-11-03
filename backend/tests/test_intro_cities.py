"""The welcome planet's cities: the committed file is current, and the rules hold.

The list is generated (`scripts/gen_intro_cities.py`) from the committed city
table, offline, so a stale `introCities.gen.ts` is caught here rather than in a
review of a 400-line diff.
"""

from __future__ import annotations

from scripts.gen_intro_cities import (
    _EXCLUDED,
    _FLOOR,
    _MIN_GAP,
    _SPACING,
    OUT,
    _degrees_apart,
    build,
    read_table,
    select,
)


def test_the_committed_file_is_what_the_generator_writes():
    assert OUT.read_text(encoding="utf-8") == build(), "rerun: python -m scripts.gen_intro_cities"


def test_the_real_table_spreads_cities_and_leaves_excluded_countries_blank():
    rows = read_table()
    kept = select(rows)
    assert 350 <= len(kept) <= 600
    points = set(kept)
    by_country: dict[str, int] = {}
    for country, _pop, lon, lat in rows:
        if (lon, lat) in points:
            by_country[country] = by_country.get(country, 0) + 1
    assert not set(by_country) & _EXCLUDED
    # Big countries carry many dots, not one each.
    for country, at_least in {"US": 15, "CA": 4, "BR": 15, "CN": 20, "AU": 4}.items():
        assert by_country.get(country, 0) >= at_least, (country, by_country.get(country))
    for i, a in enumerate(kept):
        for b in kept[i + 1:]:
            assert _degrees_apart(a, b) >= _MIN_GAP


def test_a_bigger_city_nearby_wins_and_every_country_keeps_its_largest():
    rows = [
        ("US", 8_000_000, -74.0, 40.7),  # New York
        ("US", 2_000_000, -74.2, 40.7),  # inside New York's spacing: dropped
        ("US", 3_000_000, -118.2, 34.1),  # Los Angeles: far away, kept
        ("US", 200_000, -100.0, 45.0),  # below the floor and not its country's largest
        ("LU", 130_000, 6.13, 49.61),  # Luxembourg: small, but its country's largest
        ("RU", 12_000_000, 37.6, 55.8),  # Moscow: an excluded country
    ]
    kept = select(rows)
    assert (-74.0, 40.7) in kept and (-118.2, 34.1) in kept
    assert (-74.2, 40.7) not in kept
    assert (-100.0, 45.0) not in kept
    assert (6.13, 49.61) in kept
    assert (37.6, 55.8) not in kept
    assert _degrees_apart((-74.0, 40.7), (-74.2, 40.7)) < _SPACING
    assert 200_000 < _FLOOR
