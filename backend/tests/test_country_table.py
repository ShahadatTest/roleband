"""The generated country table, and the collision rules that keep it safe.

The table is generated (`scripts/gen_country_table.py`), so these are not
"does the data look right" tests — they pin the **rules** a regeneration must
keep obeying, and the properties `LOCATION_GROUPS` consumers depend on.

The rules exist because country vocabulary collides with US geography in three
specific ways, and every one of them mis-tags a real posting when it slips.
"""

from __future__ import annotations

from tracker.enrich.classify import location_groups_for
from tracker.taxonomy.countries import BY_SLUG, COUNTRIES
from tracker.taxonomy.locations import (
    _FOREIGN_COUNTRY_TOKENS,
    _STATE_ABBREV,
    LOCATION_GROUPS,
    REGIONS,
    countries_for,
    location_group_ancestors,
)

_STATE_NAMES = frozenset(_STATE_ABBREV)
_STATE_ABBREVS = frozenset(v.lower() for v in _STATE_ABBREV.values())


# --- table integrity -------------------------------------------------------- #


def test_every_country_is_well_formed():
    seen: set[str] = set()
    for c in COUNTRIES:
        assert c.slug and c.slug not in seen, f"duplicate slug {c.slug}"
        seen.add(c.slug)
        assert c.region in REGIONS, f"{c.slug} -> unknown region {c.region}"
        lon, lat = c.centroid
        assert -180 <= lon <= 180 and -90 <= lat <= 90, f"{c.slug} centroid {c.centroid}"
        assert len(c.alpha3) == 3, c.slug
        assert c.aliases, f"{c.slug} has no match tokens"


def test_the_whole_planet_is_reachable():
    """Every inhabited region has countries under it so a seeker can express
    any market."""
    # Every region has members: an empty region is a header the user can select
    # that can never match anything.
    assert {c.region for c in COUNTRIES} == set(REGIONS)
    assert len(COUNTRIES) > 190


def test_slugs_that_users_may_already_have_saved_never_move():
    """`settings_store._get_enabled_slugs` silently drops a stored slug that no
    longer exists, which would narrow someone's saved scope without telling
    them. Renaming any of these is therefore a data-loss bug, not a refactor."""
    for slug in (
        "united_states", "uk", "singapore", "canada", "japan", "china",
        "ireland", "germany", "switzerland", "spain", "italy", "poland",
    ):
        assert slug in BY_SLUG, f"{slug} was renamed; saved scopes would lose it"


# --- the three collision rules ---------------------------------------------- #


def test_no_admitted_alpha2_collides_with_a_us_state_abbreviation():
    """Rule 2, asserted directly. Re-admitting `in`/India or `ca`/Canada would
    make "Indianapolis, IN, USA" and "Los Angeles, CA" read as foreign."""
    admitted_alpha2 = {
        c.alpha2 for c in COUNTRIES if c.alpha2 and c.alpha2 in _FOREIGN_COUNTRY_TOKENS
    }
    assert not (admitted_alpha2 & _STATE_ABBREVS)


def test_alpha2_exclusion_actually_bites():
    """A guard against the rule passing vacuously: the collisions must EXIST and
    be excluded, not merely be absent from the data. If a future dataset stopped
    carrying alpha-2 entirely, the rule above would pass while protecting
    nothing — this is what notices."""
    by_alpha2 = {c.alpha2: c.slug for c in COUNTRIES if c.alpha2}
    colliding = set(by_alpha2) & _STATE_ABBREVS
    assert len(colliding) > 15, "expected many alpha-2/state collisions"
    for code in ("ca", "in", "la", "il"):
        assert code in colliding, f"{code} should collide with a state abbrev"
        # The country never claims that token; it stays available to US parsing.
        assert _FOREIGN_COUNTRY_TOKENS.get(code) != by_alpha2[code]


def test_no_match_token_collides_with_a_us_state_abbreviation():
    """The invariant behind rule 2, over the WHOLE vocabulary rather than just
    alpha-2 — aliases and slug-derived tokens go through the same door. `uk` is
    two letters and admitted precisely because it is not a state abbrev."""
    assert not (set(_FOREIGN_COUNTRY_TOKENS) & _STATE_ABBREVS)
    assert _FOREIGN_COUNTRY_TOKENS["uk"] == "uk"


def test_a_country_name_that_is_also_a_state_name_needs_a_non_us_signal():
    """Rule 3. Georgia is the only case in ISO 3166 and it must work in both
    directions — the country on its own, the state when the US is named."""
    collisions = {c.slug for c in COUNTRIES if c.display.lower() in _STATE_NAMES}
    assert collisions == {"georgia"}, f"new name collision: {collisions}"

    assert countries_for(["Atlanta, Georgia, USA"]) == {"united_states"}
    assert countries_for(["Atlanta, GA, USA"]) == {"united_states"}
    assert countries_for(["Tbilisi, Georgia"]) == {"georgia"}


# --- what the taxonomy consumers rely on ------------------------------------ #


def test_every_country_hangs_off_a_region_and_regions_are_the_roots():
    for slug, group in LOCATION_GROUPS.items():
        if group["kind"] == "country":
            assert group.get("parent") in REGIONS, slug
        elif group["kind"] == "region" and slug != "gulf":
            assert group.get("parent") is None, slug
    # Gulf is the one nested region: GCC roles are advertised as "the Gulf", so
    # it is a group rather than a slice the user assembles by hand.
    assert LOCATION_GROUPS["gulf"]["parent"] == "middle_east"
    assert location_group_ancestors("uae") == ["gulf", "middle_east"]


def test_leaves_are_declared_before_their_umbrellas():
    """Declaration order is the tiebreak in `location_groups_for`, the
    canonical order in `settings_store`, and the payload order in the scope
    catalog. Metros must precede countries, countries must precede regions."""
    order = list(LOCATION_GROUPS)
    kinds = [LOCATION_GROUPS[s]["kind"] for s in order]
    assert kinds.index("metro") < kinds.index("country") < kinds.index("region")
    assert order.index("silicon_valley") < order.index("united_states")
    assert order.index("united_states") < order.index("north_america")


def test_only_the_shipped_eight_are_enabled_by_default():
    """New countries ship OFF. That is what keeps the adapter coverage contract
    satisfiable — a source only has to declare queries for regions we ship
    tracked — while Settings still offers the whole planet."""
    enabled = {s for s, g in LOCATION_GROUPS.items() if g.get("enabled")}
    assert enabled == {
        "silicon_valley", "pacific_northwest", "new_york", "austin", "dc_metro",
        "united_states", "uk", "singapore",
    }


def test_previously_unmatchable_markets_now_resolve():
    """These postings must match a location group and survive `passes_filters`;
    missing country vocabulary would silently discard them."""
    cases = {
        "Bengaluru, Karnataka, India": ["india", "south_asia"],
        "Dubai, United Arab Emirates": ["uae", "gulf", "middle_east"],
        "Sydney, NSW, Australia": ["australia", "oceania"],
        "Tel Aviv, Israel": ["israel", "middle_east"],
        "São Paulo, Brazil": ["brazil", "latin_america"],
        "Riyadh, Saudi Arabia": ["saudi_arabia", "gulf", "middle_east"],
        "Lagos, Nigeria": ["nigeria", "africa"],
    }
    for raw, expected in cases.items():
        assert location_groups_for([raw]) == expected, raw


def test_deepest_first_ordering_survives_the_third_level():
    """`location_groups[0]` is the comp/primary axis and the single badge
    `JobCard` renders. A region must never displace the finer leaf."""
    assert location_groups_for(["Mountain View, CA, USA"])[0] == "silicon_valley"
    assert location_groups_for(["Dubai, UAE"])[0] == "uae"
    assert location_groups_for(["Tokyo, Japan"])[0] == "japan"
