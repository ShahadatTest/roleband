"""The spelling-only normaliser behind the agent tools' closed filters."""

from __future__ import annotations

from tracker.enrich.classify import location_slugs_for
from tracker.mcp.vocab import Resolution, normalize, vocabulary
from tracker.taxonomy.locations import location_names


def test_spelling_is_normalised_and_nothing_fuzzier():
    assert normalize("  Product-Management ") == normalize("product management") == "product_management"
    assert normalize("AI / ML") == "ai_ml"
    # Not a guess: a plural or an abbreviation is a different value.
    assert normalize("Product Managers") != normalize("Product Management")


def test_a_display_name_never_shadows_a_slug():
    vocab = vocabulary([("new_york", "New York"), ("york", "New York")])
    assert vocab["new_york"] == "new_york", "the first owner of a display name keeps it"
    assert vocab["york"] == "york"


def test_duplicates_collapse_and_only_all_unknown_drops_the_filter():
    vocab = vocabulary([("openai", "OpenAI")])
    res = Resolution()
    res.resolve("companies", ["OpenAI", "openai", "Initech"], vocab)
    res.resolve("families", None, vocab)
    assert res.kept == {"companies": ["openai"]}
    assert res.dropped_filters == []
    assert [i["value"] for i in res.ignored] == ["Initech"]
    res.resolve("locations", ["Narnia"], {})
    assert res.dropped_filters == ["locations"] and "locations" not in res.kept


def test_a_place_name_resolves_to_the_most_exact_thing_it_names():
    """The taxonomy's own names, one precedence: a group's display name, then a
    city the user tracks, then what people type for a country ("USA"), then the
    places a group is made of ("Bay Area"). No alpha-2: "CA" is Canada to the
    country table and California to a person."""
    seattle = next(s for s in location_slugs_for(["Seattle, WA, USA"]) if s.startswith("city_"))
    untracked = vocabulary(location_names())
    tracked = vocabulary(location_names([seattle]))

    assert untracked[normalize("London")] == "london", "a display name outranks uk's city fallback"
    assert untracked[normalize("USA")] == "united_states"
    assert untracked[normalize("Bay Area")] == "silicon_valley"
    assert untracked[normalize("Seattle")] == "pacific_northwest"
    assert tracked[normalize("Seattle")] == seattle, "a tracked city outranks the metro holding it"
    assert normalize("CA") not in untracked and normalize("Gondor") not in tracked
