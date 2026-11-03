"""Pure-logic tests for skill trend + overlap aggregation (no DB).

The DB upsert in `compute_skill_demand` is exercised live via the pipeline hook;
here we pin the pivot/selection and pairing math that powers the Trends and Overlap
Statistics sub-tabs.
"""

from __future__ import annotations

from tracker.skills.analytics import build_trend_series, compute_overlap, seriate, set_changes


def test_trend_series_aligns_and_zero_fills_missing_dates():
    # 'rust' is absent on d1; it must appear as 0 on that day, not be dropped.
    rows = [
        ("2026-07-11", "python", 5),
        ("2026-07-12", "python", 7),
        ("2026-07-12", "rust", 3),
    ]
    dates, series = build_trend_series(rows)
    assert dates == ["2026-07-11", "2026-07-12"]

    by_term = {s["term"]: s for s in series}
    assert [p["job_count"] for p in by_term["python"]["points"]] == [5, 7]
    assert [p["job_count"] for p in by_term["rust"]["points"]] == [0, 3]


def test_trend_series_current_and_delta_use_window_ends():
    rows = [("2026-07-10", "go", 10), ("2026-07-11", "go", 4), ("2026-07-12", "go", 8)]
    _, series = build_trend_series(rows)
    go = series[0]
    assert go["current"] == 8  # last point
    assert go["delta"] == -2  # last minus first (8 - 10), not min/max


def test_trend_series_default_picks_top_by_latest_date():
    rows = [
        ("2026-07-11", "python", 99),  # big earlier, but drops to 1 latest
        ("2026-07-12", "python", 1),
        ("2026-07-11", "rust", 2),
        ("2026-07-12", "rust", 40),  # top on the latest date
    ]
    _, series = build_trend_series(rows, limit=1)
    assert [s["term"] for s in series] == ["rust"]


def test_trend_series_explicit_terms_preserve_order_and_filter():
    rows = [("2026-07-12", "python", 5), ("2026-07-12", "rust", 3)]
    _, series = build_trend_series(rows, terms=["rust", "python", "ghost"])
    # 'ghost' has no rows and is dropped; requested order is preserved.
    assert [s["term"] for s in series] == ["rust", "python"]


def test_overlap_weighs_a_skill_by_how_few_companies_name_it():
    """A skill every compared company names says nothing about a pair."""
    skill_sets = {
        "a": {"python": 5, "rust": 2, "go": 1},
        "b": {"python": 4, "rust": 6},
        "c": {"scala": 3, "python": 1},
        "d": {"scala": 2},
    }
    pairs = {(p["a"], p["b"]): p for p in compute_overlap(skill_sets, ["a", "b", "c", "d"])}
    # Python is named by three of four: weighed little. Rust, by two: what a and b share.
    ab, ac = pairs[("a", "b")], pairs[("a", "c")]
    assert (ab["shared"], ab["union"]) == (2, 3)
    assert ab["top_shared_terms"][0] == "rust"
    assert ab["similarity"] > ac["similarity"] > 0
    assert pairs[("c", "d")]["top_shared_terms"] == ["scala"]
    assert ("a", "d") not in pairs  # nothing shared, no pair


def test_a_skill_every_company_names_scores_nothing():
    pairs = compute_overlap({"a": {"python": 5}, "b": {"python": 1}}, ["a", "b"])
    assert pairs[0]["similarity"] == 0.0


def test_seriation_puts_similar_companies_side_by_side():
    pairs = [
        {"a": "x1", "b": "x2", "similarity": 0.9}, {"a": "y1", "b": "y2", "similarity": 0.8},
        {"a": "x1", "b": "y1", "similarity": 0.1}, {"a": "x2", "b": "y2", "similarity": 0.05},
        {"a": "x1", "b": "y2", "similarity": 0.0}, {"a": "x2", "b": "y1", "similarity": 0.0},
    ]
    order = seriate(["x1", "y1", "x2", "y2"], pairs)
    assert {frozenset(order[:2]), frozenset(order[2:])} == {frozenset({"x1", "x2"}), frozenset({"y1", "y2"})}
    assert seriate(["a", "b"], []) == ["a", "b"]


def test_a_point_is_its_share_of_the_days_mentions_and_competencies_are_not_picked():
    """A raw count moves with whatever is measured; a share of the day's
    mentions does not jump when a company set arrives. Competencies are left out
    of the automatic pick, as on the Skills tab."""
    rows = [
        ("2026-10-01", "python", 10), ("2026-10-01", "roadmapping", 30), ("2026-10-01", "sql", 10),
        ("2026-10-03", "python", 100), ("2026-10-03", "roadmapping", 300), ("2026-10-03", "sql", 100),
    ]
    axis, series = build_trend_series(rows, exclude={"roadmapping"})
    assert [s["term"] for s in series] == ["python", "sql"]
    python = series[0]
    assert [(p["job_count"], p["share"]) for p in python["points"]] == [(10, 0.2), (100, 0.2)]
    # Ten times the count, the same share: no change in demand.
    assert (python["delta"], python["share_delta"], python["current_share"]) == (90, 0.0, 0.2)
    # Named terms are still returned, competency or not.
    assert [s["term"] for s in build_trend_series(rows, terms=["roadmapping"])[1]] == ["roadmapping"]


def test_a_day_whose_mentions_jump_is_marked_as_a_change_in_what_is_measured():
    rows = [("d1", "a", 100), ("d2", "a", 110), ("d3", "a", 400), ("d4", "a", 390), ("d5", "a", 100)]
    assert set_changes(rows) == ["d3", "d5"]
    assert set_changes([]) == []
