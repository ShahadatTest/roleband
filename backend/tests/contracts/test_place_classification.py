"""A place the board states must be a place the taxonomy knows.

Locations FAIL CLOSED: `db/repo.py` gates on
`location_groups && enabled_locations`, so a posting whose stated place matches
no group is in no group, passes no location filter, and is invisible to every
user — with no error, no drift alert and no anomaly. Nothing downstream can
tell it apart from a posting that simply isn't in your region.

A board can list bare city names ("Stockholm") that the taxonomy knows only as
part of a country-qualified place: those postings are collected, stored, and
shown to nobody while every test the adapter has stays green.

`test_location_coverage.py` is the other half of this and does not cover it: it
asks whether an adapter can QUERY a region, never whether the place a board
ANSWERS with lands anywhere.
"""

from __future__ import annotations

import pytest

from tests.contracts.conftest import MODE_NORMAL, build_harness, run_fetch
from tracker.connectors import ADAPTER_REGISTRY
from tracker.enrich.classify import match_location_groups

ADAPTER_NAMES = sorted(ADAPTER_REGISTRY)

#: Fixture postings whose stated place genuinely belongs to no group, with the
#: reason. A place here is a DECISION that the taxonomy should not name it —
#: not a shrug. Keep it empty unless a board really does state such a place.
#:
#: Shape: adapter name -> {place label: why}.
UNPLACEABLE: dict[str, dict[str, str]] = {}


def _unplaceable(name: str, label: str) -> bool:
    return label in UNPLACEABLE.get(name, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_every_place_a_board_states_lands_in_a_location_group(name):
    """The posting the user never sees.

    Asserted over each adapter's own fixtures, which are the recorded shape of
    that board's real responses — so a board that states places in a form the
    taxonomy cannot read fails here, at the adapter that introduced it, rather
    than months later in a corpus read.
    """
    adapter = build_harness(name, MODE_NORMAL)
    jobs = await run_fetch(adapter)
    if not jobs:
        pytest.skip(f"{name} fixtures yield no postings")

    invisible = []
    for job in jobs:
        if match_location_groups(job):
            continue
        for label in job.locations or ["(no location at all)"]:
            if not _unplaceable(name, label):
                invisible.append((job.req_id, label))

    assert not invisible, (
        f"{name}: {len(invisible)} fixture posting(s) state a place that matches no location "
        f"group, so they would be collected and shown to nobody: {invisible[:5]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_a_posting_states_a_place_at_all(name):
    """Empty `locations` is the same invisibility by a shorter route, and it is
    the easier mistake: a board that moves its place into a field the adapter
    stopped reading yields postings that parse perfectly."""
    adapter = build_harness(name, MODE_NORMAL)
    jobs = await run_fetch(adapter)
    if not jobs:
        pytest.skip(f"{name} fixtures yield no postings")

    placeless = [job.req_id for job in jobs if not job.locations]
    assert not placeless, (
        f"{name}: {len(placeless)} fixture posting(s) state no place at all: {placeless[:5]}"
    )


def test_the_unplaceable_list_names_only_live_adapters():
    """An exemption that outlives its adapter stops being a decision."""
    for name, places in UNPLACEABLE.items():
        assert name in ADAPTER_REGISTRY, f"{name} is not an adapter"
        assert places, f"{name}: an empty exemption entry claims nothing; remove it"
        for label, reason in places.items():
            assert reason.strip(), f"{name}/{label}: an exemption needs its reason"
