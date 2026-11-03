"""Junior reads as Entry; Intern is a rung of its own.

A stored row, a scan tally, a saved choice or an old link may still name
"junior"; every reader takes it as Entry, never as an error and never as
nothing. Other unknown values fail or are dropped.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from tracker.db.queries.jobs import level_band_clause
from tracker.levels import LEVELS
from tracker.schema import LEVEL_BAND_ORDER, LevelBand, band_slug, parse_band


def test_seven_rungs_with_intern_below_entry():
    assert [level.slug for level in LEVELS] == [
        "intern", "entry", "mid", "senior", "staff", "principal", "director_plus",
    ]
    assert [level.display for level in LEVELS][:2] == ["Intern", "Entry / Junior"]
    assert LEVEL_BAND_ORDER["intern"] < LEVEL_BAND_ORDER["entry"] < LEVEL_BAND_ORDER["mid"]
    assert "junior" not in LEVEL_BAND_ORDER


def test_a_stored_junior_reads_as_entry_and_anything_else_unknown_still_fails():
    assert parse_band("junior") is LevelBand.ENTRY
    assert parse_band("intern") is LevelBand.INTERN
    assert parse_band(LevelBand.STAFF) is LevelBand.STAFF
    with pytest.raises(ValueError):
        parse_band("bogus")
    assert (band_slug("junior"), band_slug("staff"), band_slug("bogus")) == ("entry", "staff", "bogus")


def test_an_old_board_link_for_junior_filters_entry():
    sql = str(level_band_clause(["junior"]).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "'entry'" in sql and "'junior'" not in sql
