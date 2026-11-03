"""`levels.words.resolve_band`: a band for every rung a pay source publishes.

The company ladders (`levels.companies`) are written for the SWE ladder's
labels. Every other family names its rungs differently: a ladder code with
the family's title behind it (Amazon "L6 SDM"), a bare
manager code (Apple "M2", Nvidia "M4"), or a plain title (Netflix "Lead Product
Manager"). Each path below is one of those, and the order of the paths is the
order of trust: the ladder, then the family table's code for the same rung, then
the seniority words — which must agree with how a posting's title is banded, or
the comp lookup joins a "Group Product Manager" job to some other rung.
"""

from __future__ import annotations

import pytest

from tracker.levels.ladder import band_for
from tracker.levels.words import resolve_band
from tracker.schema import LevelBand


def test_seed_label_wins_outright():
    assert resolve_band("google", "L6") is LevelBand.STAFF
    assert resolve_band("amazon", "Principal SDE") is LevelBand.PRINCIPAL


@pytest.mark.parametrize(
    ("company", "label", "band"),
    [
        ("amazon", "L6 SDM", LevelBand.SENIOR),
        ("amazon", "L7", LevelBand.PRINCIPAL),
        ("microsoft", "64", LevelBand.SENIOR),
        ("openai", "L7", LevelBand.DIRECTOR_PLUS),
        ("apple", "M2", LevelBand.STAFF),
        ("nvidia", "M4", LevelBand.PRINCIPAL),
        ("nvidia", "IC7", LevelBand.DIRECTOR_PLUS),
    ],
)
def test_ladder_code_at_the_head_of_a_qualified_label(company, label, band):
    assert resolve_band(company, label) is band


def test_family_table_alias_outranks_the_seniority_word():
    """A family table names a rung by its L-number while the page label carries no
    seniority word ("Product Manager - Technical" at Amazon's L6). The code, paired
    to the page by median TC, outranks the word: L6 is Amazon's senior rung."""
    assert resolve_band("amazon", "Product Manager - Technical", aliases=["L6"]) is LevelBand.SENIOR
    # Without the alias the word is all there is: a bare title is the mid rung.
    assert resolve_band("amazon", "Product Manager - Technical") is LevelBand.MID


@pytest.mark.parametrize(
    ("label", "band"),
    [
        ("Product Manager", LevelBand.MID),
        ("Senior Product Manager", LevelBand.SENIOR),
        ("Lead Product Manager", LevelBand.STAFF),
        ("Group Product Manager", LevelBand.PRINCIPAL),  # as level_mapper reads a posting
        ("Principal EM", LevelBand.PRINCIPAL),
        ("Director", LevelBand.DIRECTOR_PLUS),
        ("Senior Director", LevelBand.DIRECTOR_PLUS),
        ("VP", LevelBand.DIRECTOR_PLUS),
        ("Partner", LevelBand.DIRECTOR_PLUS),
        # The first full-time rung is Entry; Junior reads as Entry.
        ("Associate Product Manager", LevelBand.ENTRY),
        ("APM1", LevelBand.ENTRY),  # Google's live product-manager ladder
        ("Product Manager Intern", LevelBand.INTERN),
        ("L9 / L10", LevelBand.MID),  # no seed for this company: the code path needs one
        ("Product Manager I", LevelBand.ENTRY),
        ("Product Manager II", LevelBand.MID),
        ("Product Manager III", LevelBand.SENIOR),
        ("Software Engineer 5", LevelBand.SENIOR),
    ],
)
def test_named_rung_reads_its_seniority_words(label, band):
    # A company with no seed at all, so only the words can answer.
    assert resolve_band("stripe-like-unknown", label) is band


def test_resolve_never_returns_none_but_band_for_still_does():
    """`band_for` keeps its contract (None = not a seeded rung) for the callers that
    depend on it; `resolve_band` is the harvester's total function."""
    assert band_for("google", "Head of Everything") is None
    assert resolve_band("google", "Head of Everything") is LevelBand.DIRECTOR_PLUS
