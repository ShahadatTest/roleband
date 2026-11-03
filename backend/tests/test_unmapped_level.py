"""A level we cannot place never decides a posting.

"Senior Manager", "Engineering Manager", "Lead" name a level in the company's
own terms. Where the company's ladder is not mapped, the shared band is our
guess, and a guess that gates would, for a person tracking principal and
director+, pass "Manager, Data Science", hide "Senior Manager, Data Science" as
staff, and pass "Senior Manager, Security Architecture" as principal because
"Architecture" contains "architect". So every such posting follows the person's
switch, and a level the title states gates.
"""

from __future__ import annotations

import pytest

from tests.factories import scope_filter
from tracker.enrich.enricher import annotate, passes_filters
from tracker.schema import LevelBasis, RawJob

_BANDS = frozenset({"principal", "director_plus"})


def _passes(title: str, include_unplaced: bool, company: str = "acme") -> bool:
    ann = annotate(RawJob(company=company, req_id="x", title=title, url="", locations=["London, UK"]))
    scope = scope_filter(
        bands=_BANDS,
        roles={ann.family},
        tracks={ann.track.value},
        locations={"uk"},
        domains=(),
        include_unstated_level=include_unplaced,
    )
    return passes_filters(ann, scope)


_UNPLACED = [
    "Manager, Data Science",  # states nothing
    "Senior Manager, Data Science",  # a manager rank, guessed staff
    "Senior Manager, Security Architecture",  # guessed principal from "Architecture"
    "Engineering Manager",  # a role, guessed staff
    "Lead Product Manager",  # a role, guessed staff
]


@pytest.mark.parametrize("title", _UNPLACED)
def test_a_level_we_cannot_place_follows_the_switch(title):
    assert _passes(title, include_unplaced=True)
    assert not _passes(title, include_unplaced=False)


@pytest.mark.parametrize("title", _UNPLACED[1:])
def test_a_manager_rank_is_unmapped_never_not_stated(title):
    # The card must not say "level not stated" for a title that names one.
    ann = annotate(RawJob(company="acme", req_id="x", title=title, url=""))
    assert ann.basis is LevelBasis.UNMAPPED


@pytest.mark.parametrize(("title", "passes"), [
    ("Director, Data Science", True),  # states director+: in, switch or not
    ("Senior Product Manager", False),  # states senior: out, switch or not
    ("Principal Product Manager", True),
])
def test_a_level_the_title_states_gates_whatever_the_switch(title, passes):
    assert _passes(title, include_unplaced=True) is passes
    assert _passes(title, include_unplaced=False) is passes


def test_a_company_ladder_still_places_a_manager_rank():
    # Google's own words place "Senior Software Engineering Manager" at L7
    # (principal): mapped, so it gates as a stated level.
    ann = annotate(RawJob(company="google", req_id="x", title="Senior Software Engineering Manager, Search", url=""))
    assert ann.basis is LevelBasis.COMPANY
    assert _passes("Senior Software Engineering Manager, Search", include_unplaced=False, company="google")
