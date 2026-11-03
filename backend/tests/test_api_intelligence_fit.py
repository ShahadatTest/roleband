"""Fit: the ranking card's instrument data (`tracker/search/fit.py`).

Three invariants worth pinning:

1. The histogram runs over EXACTLY the board's default browse base — the same
   `apply_job_filters` conditions (open, in-scope, not dismissed, hidden
   companies excluded) — plus one addition of its own: only embedded rows can
   be binned. The settings screen must quote the same total the board shows.
2. The presentational bands are exact sums of histogram bins: nothing is
   split, double-counted, or dropped, so the four counts always sum to the
   binned total. A failed implementation here misreports the user's board.
3. There is ONE fit expression. The daily digest ranks by the same
   `1 - cosine_distance`, and the two are held to identical SQL rather than to
   each other's prose. `search/best_match.py` is deliberately NOT folded in: it
   projects the DISTANCE under its own name, which reaches the client.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from tracker.db.models import Job
from tracker.search import fit
from tracker.search.fit import (
    FIT_BAND_EDGES,
    FIT_BIN_WIDTH,
    band_bounds,
    band_stmt,
    fit_bands,
    fit_expr,
    histogram_stmt,
)

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_histogram_runs_over_the_board_browse_base_plus_embedded_only():
    sql = _sql(histogram_stmt({"status": "open", "hidden": ["meta"]}, [0.1, 0.2]))
    where = sql.split("WHERE", 1)[1]
    # The board's standing visibility: open, in scope, dismissed excluded,
    # hidden companies excluded.
    assert "jobs.status =" in where
    assert "jobs.in_scope IS true" in where
    assert "NOT IN" in where  # dismissed + hidden exclusions
    # Its own addition: only embedded rows can be binned.
    assert "jobs.embedding IS NOT NULL" in where
    # Binned by cosine fit, grouped by the bucket expression.
    assert "<=>" in sql
    assert "floor" in sql
    assert "GROUP BY" in sql


def test_band_edges_are_exact_bin_boundaries():
    # If an edge is not a multiple of the bin width, a bin straddles two bands
    # and the quantization silently miscounts.
    for _key, _label, edge in FIT_BAND_EDGES:
        ratio = edge / FIT_BIN_WIDTH
        assert abs(ratio - round(ratio)) < 1e-9


def test_bands_partition_the_histogram():
    by_bin = [(7, 1), (20, 10), (21, 5), (24, 5), (25, 3), (29, 2), (30, 4), (37, 1)]
    bands = fit_bands(by_bin)
    assert [b["key"] for b in bands] == ["strong", "good", "some", "weak"]
    # Exact partition: every bin lands in exactly one band.
    assert sum(b["count"] for b in bands) == sum(c for _, c in by_bin)
    # Boundary bins land on the higher band's floor, not below it.
    assert bands[0]["count"] == 5  # bins 30 and 37 (fit >= 0.60)
    assert bands[1]["count"] == 5  # bins 25..29
    assert bands[2]["count"] == 10  # bins 21..24
    assert bands[3]["count"] == 11  # bins 7 and 20


def test_bands_survive_an_empty_histogram():
    bands = fit_bands([])
    assert [b["count"] for b in bands] == [0, 0, 0, 0]


def test_band_bounds_mirror_the_quantization_edges():
    assert band_bounds("strong") == (0.60, None)
    assert band_bounds("good") == (0.50, 0.60)
    assert band_bounds("some") == (0.42, 0.50)
    assert band_bounds("weak") == (None, 0.42)


def test_each_band_carries_the_lower_edge_the_screen_draws(monkeypatch):
    """The dashboard draws a band's line where the payload says, so the edge it
    is sent must be the one the counts were cut at, edge moved or not."""
    assert [(b["key"], b["lower_edge"]) for b in fit_bands([])] == [
        ("strong", 0.60), ("good", 0.50), ("some", 0.42), ("weak", None),
    ]
    monkeypatch.setattr(fit, "FIT_BAND_EDGES", (("strong", "Strong", 0.70), ("good", "Good", 0.40),
                                                ("some", "Fair", 0.30)))
    bands = fit_bands([(16, 1), (34, 2), (35, 4)])  # fits 0.32, 0.68, 0.70
    assert [(b["key"], b["count"], b["lower_edge"]) for b in bands] == [
        ("strong", 4, 0.70), ("good", 2, 0.40), ("some", 1, 0.30), ("weak", 0, None),
    ]


def test_band_preview_runs_over_the_same_base_best_first():
    sql = _sql(band_stmt({"status": "open", "hidden": ["meta"]}, [0.1, 0.2], "good", 3))
    where = sql.split("WHERE", 1)[1]
    # The board's standing visibility plus embedded-only — the same base the
    # histogram binned, or the preview shows roles the band count excludes.
    assert "jobs.status =" in where
    assert "jobs.in_scope IS true" in where
    assert "jobs.embedding IS NOT NULL" in where
    # A bounded band constrains both sides; best fit first; a few rows only.
    assert where.count("<=>") >= 2
    assert "ORDER BY" in sql and "DESC" in sql
    assert "LIMIT" in sql


def test_the_digest_ranks_by_the_same_expression_the_instrument_bins():
    """Compile-compared, not asserted in prose: `notifications/digest.py` ranks
    the day's roles by fit, and a second spelling of `1 - cosine_distance` is how
    the settings card and the digest would come to disagree about what fit means.
    """
    from tracker.notifications import digest

    assert "fit_expr" in Path(digest.__file__).read_text(encoding="utf-8")
    assert _sql(fit_expr([0.1, 0.2]).label("fit")) == _sql(
        (1 - Job.embedding.cosine_distance([0.1, 0.2])).label("fit")
    )


def test_best_match_is_not_the_same_expression_and_is_left_alone():
    """The positive control for the sharing above. Best match orders by the
    DISTANCE and projects it as `intent_distance`; the row order is the same but
    the column is not, and it reaches the client. Folding it in would be a wire
    change disguised as a deduplication."""
    assert _sql(fit_expr([0.1, 0.2])) != _sql(Job.embedding.cosine_distance([0.1, 0.2]))
    assert "intent_distance" in Path(
        __import__("tracker.search.best_match", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
