"""The scope joint must answer exactly what `passes_filters` would.

`scope_cells` exists so a client can intersect the five axes instead of adding
up marginals. That is only worth anything if applying the gate to the cells
gives the same number as running the real gate over the postings they came
from — otherwise the screen is precise about the wrong figure, which is worse
than the full-market volume it replaced.

So the load-bearing test here is an agreement property over a population built
to hit the edges the gate actually has: multi-location postings, multi-label
domains, and unclassified postings that must pass the domain axis whatever the
user selected.
"""

from __future__ import annotations

import itertools
import random

import pytest

from tracker.enrich.enricher import Annotation, ScopeFilter, passes_filters
from tracker.schema import LevelBand, LevelConfidence, RawJob, RoleTrack
from tracker.scope.catalog_store import _ordered_scope_cells
from tracker.taxonomy.role_catalog import add_to_catalog

BANDS = [LevelBand.MID, LevelBand.SENIOR, LevelBand.STAFF, LevelBand.PRINCIPAL]
TRACKS = [RoleTrack.TECHNICAL, RoleTrack.MANAGEMENT, RoleTrack.PRODUCT_PROGRAM]
# Real shapes: a leaf carries its ancestors, a multi-city posting carries two
# leaves, and `location_groups` is never empty for a catalogued posting.
LOCATION_SETS = [
    ["silicon_valley", "united_states", "north_america"],
    ["pacific_northwest", "united_states", "north_america"],
    ["uk"],
    ["london", "uk"],
    ["silicon_valley", "united_states", "north_america", "london", "uk"],
    ["singapore"],
]
# [] is the fail-open case and must be represented.
DOMAIN_SETS = [
    [],
    ["ai_ml"],
    ["cloud_infra"],
    ["ai_ml", "cloud_infra"],
    ["logistics_fulfillment", "retail_commerce"],
]
FAMILIES = ["product_management", "ml_ai_research", "engineering_management"]


def _population() -> list[Annotation]:
    """Every combination once, so no edge is left to a random draw."""
    return [
        Annotation(
            band=band,
            confidence=LevelConfidence.CONFIRMED,
            family=family,
            location_groups=list(locations),
            track=track,
            domains=list(domains),
        )
        for band, track, locations, domains, family in itertools.product(
            BANDS, TRACKS, LOCATION_SETS, DOMAIN_SETS, FAMILIES
        )
    ]


def _tallies(population: list[Annotation]) -> dict:
    tallies: dict = {}
    for index, ann in enumerate(population):
        raw = RawJob(
            company="acme", req_id=str(index), title="Role", url=f"https://x/{index}"
        )
        add_to_catalog(tallies, raw, ann)
    return tallies


def _cell_passes(cell: dict, scope: ScopeFilter) -> bool:
    """The gate as a client must implement it, read off a stored cell.

    Mirrors `enricher.passes_filters` minus the role axis (a cell lives under
    its role group) and minus `rule_excluded`, which is not an axis: it matches
    a posting's verbatim team/department, which no aggregate can carry.
    """
    if cell["band"] not in scope.enabled_bands:
        return False
    if cell["track"] not in scope.enabled_tracks:
        return False
    if not scope.enabled_locations.intersection(cell["locations"]):
        return False
    if (
        scope.enabled_domains
        and cell["domains"]
        and not scope.enabled_domains.intersection(cell["domains"])
    ):
        return False
    return True


def _scope(rng: random.Random) -> ScopeFilter:
    def pick(options: list[str], *, allow_empty: bool) -> frozenset[str]:
        low = 0 if allow_empty else 1
        return frozenset(rng.sample(options, rng.randint(low, len(options))))

    return ScopeFilter(
        enabled_bands=pick([b.value for b in BANDS], allow_empty=False),
        enabled_roles=pick(FAMILIES, allow_empty=False),
        enabled_tracks=pick([t.value for t in TRACKS], allow_empty=False),
        enabled_locations=pick(
            sorted({slug for group in LOCATION_SETS for slug in group}), allow_empty=False
        ),
        # The one axis whose empty set means "no narrowing" rather than
        # "nothing passes", so it must be drawn empty sometimes.
        enabled_domains=pick(
            sorted({slug for group in DOMAIN_SETS for slug in group}), allow_empty=True
        ),
    )


def test_cells_reproduce_the_gate_over_every_combination():
    population = _population()
    tallies = _tallies(population)
    cells_by_family = {
        family: _ordered_scope_cells(tally) for family, tally in tallies.items()
    }
    rng = random.Random(20260921)

    for _ in range(300):
        scope = _scope(rng)
        expected = sum(
            1
            for ann in population
            if ann.family in scope.enabled_roles and passes_filters(ann, scope)
        )
        actual = sum(
            cell["count"]
            for family, cells in cells_by_family.items()
            if family in scope.enabled_roles
            for cell in cells
            if _cell_passes(cell, scope)
        )
        assert actual == expected, (
            f"cells disagree with passes_filters for "
            f"bands={sorted(scope.enabled_bands)} tracks={sorted(scope.enabled_tracks)} "
            f"locations={sorted(scope.enabled_locations)} "
            f"domains={sorted(scope.enabled_domains)}"
        )


def test_cells_account_for_every_catalogued_posting_exactly_once():
    population = _population()
    tallies = _tallies(population)
    for family, tally in tallies.items():
        cells = _ordered_scope_cells(tally)
        assert sum(cell["count"] for cell in cells) == tally.count
        assert sum(cell["count"] for cell in cells) == sum(tally.band_counts.values())
        assert len({(c["band"], c["track"], tuple(c["locations"]), tuple(c["domains"]))
                    for c in cells}) == len(cells), f"{family} has duplicate coordinates"


def test_an_unclassified_posting_passes_a_narrowed_domain_axis():
    """The fail-open rule, stated as its own case rather than left to the sweep."""
    tallies = _tallies(
        [
            Annotation(
                band=LevelBand.STAFF,
                confidence=LevelConfidence.CONFIRMED,
                family="product_management",
                location_groups=["uk"],
                track=RoleTrack.PRODUCT_PROGRAM,
                domains=[],
            )
        ]
    )
    (cell,) = _ordered_scope_cells(tallies["product_management"])
    assert cell["domains"] == []
    scope = ScopeFilter(
        enabled_bands=frozenset({"staff"}),
        enabled_roles=frozenset({"product_management"}),
        enabled_tracks=frozenset({"product_program"}),
        enabled_locations=frozenset({"uk"}),
        enabled_domains=frozenset({"ai_ml"}),
    )
    assert _cell_passes(cell, scope) is True


def test_a_location_set_is_matched_by_overlap_not_by_containment():
    """A posting in two places passes when EITHER is selected."""
    tallies = _tallies(
        [
            Annotation(
                band=LevelBand.STAFF,
                confidence=LevelConfidence.CONFIRMED,
                family="product_management",
                location_groups=["silicon_valley", "united_states"],
                track=RoleTrack.PRODUCT_PROGRAM,
                domains=["ai_ml"],
            )
        ]
    )
    (cell,) = _ordered_scope_cells(tallies["product_management"])
    base = dict(
        enabled_bands=frozenset({"staff"}),
        enabled_roles=frozenset({"product_management"}),
        enabled_tracks=frozenset({"product_program"}),
        enabled_domains=frozenset(),
    )
    assert _cell_passes(cell, ScopeFilter(enabled_locations=frozenset({"uk"}), **base)) is False
    for selected in ({"silicon_valley"}, {"united_states"}, {"united_states", "uk"}):
        assert _cell_passes(
            cell, ScopeFilter(enabled_locations=frozenset(selected), **base)
        ) is True


def test_the_same_places_in_a_different_order_are_one_cell():
    """`location_groups_for` orders by specificity, which is not a stable key.

    Two postings in the same places can arrive with their groups in different
    orders. Counted as written they would be two coordinates carrying one
    posting each, which no client could tell from two genuinely different
    location sets.
    """
    def ann(groups: list[str], domains: list[str]) -> Annotation:
        return Annotation(
            band=LevelBand.STAFF,
            confidence=LevelConfidence.CONFIRMED,
            family="product_management",
            location_groups=groups,
            track=RoleTrack.PRODUCT_PROGRAM,
            domains=domains,
        )

    tallies = _tallies(
        [
            ann(["silicon_valley", "united_states"], ["ai_ml", "cloud_infra"]),
            ann(["united_states", "silicon_valley"], ["cloud_infra", "ai_ml"]),
        ]
    )
    cells = _ordered_scope_cells(tallies["product_management"])
    assert len(cells) == 1
    assert cells[0]["count"] == 2


def test_stored_cells_are_ordered_so_an_unchanged_board_rewrites_identically():
    first = _tallies(_population())
    shuffled = _population()
    random.Random(7).shuffle(shuffled)
    second = _tallies(shuffled)
    for family in first:
        assert _ordered_scope_cells(first[family]) == _ordered_scope_cells(second[family])


@pytest.mark.parametrize("zero_count", [0, -1])
def test_a_zero_cell_is_never_stored(zero_count):
    tallies = _tallies(
        [
            Annotation(
                band=LevelBand.STAFF,
                confidence=LevelConfidence.CONFIRMED,
                family="product_management",
                location_groups=["uk"],
                track=RoleTrack.PRODUCT_PROGRAM,
                domains=[],
            )
        ]
    )
    tally = tallies["product_management"]
    tally.scope_cells[("senior", "technical", ("uk",), ())] = zero_count
    assert [cell["count"] for cell in _ordered_scope_cells(tally)] == [1]
