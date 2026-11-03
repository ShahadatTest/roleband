"""Why two postings were paired, said as codes from the evidence's numbers.

The detectors keep English reasons for diagnostics; a reader is told codes
the dashboard words. They are derived from the numbers the evidence stores,
so a link written before codes existed says them too.
"""

from __future__ import annotations

from tracker.lineage.reasons import duplicate_reasons, twin_reasons


def test_a_same_title_repost_says_same_title_and_how_alike_the_descriptions_read():
    said = duplicate_reasons("title+embedding", "repost", {"cosine": 0.934, "title_jaccard": 1.0,
                                                            "reasons": ["normalized titles identical; cosine 0.93 >= 0.9"]})
    assert said == [{"code": "same_title", "params": {}}, {"code": "descriptions_alike", "params": {"pct": 93}}]


def test_a_title_overlap_duplicate_says_both_figures_and_that_both_were_open():
    said = duplicate_reasons("title_jaccard", "duplicate", {"cosine": 0.81, "title_jaccard": 0.6})
    assert [s["code"] for s in said] == ["titles_alike", "descriptions_alike", "listed_at_once"]
    assert said[0]["params"] == {"pct": 60}


def test_a_figure_the_evidence_lacks_is_left_unsaid_never_guessed():
    """The negative control: a link with no stored cosine says no percentage."""
    assert duplicate_reasons("embedding", "repost", {}) == []
    assert duplicate_reasons("human", "repost", {"cosine": 0.99}) == []


def test_a_twin_says_its_title_department_and_the_passages_that_differ():
    said = twin_reasons({
        "anchors": {"display_title_equal": False, "department_relation": "missing", "title_similarity": 0.72},
        "description_diff": {"left_only_count": 2, "right_only_count": 3},
    })
    assert said == [
        {"code": "titles_alike", "params": {"pct": 72}},
        {"code": "department_unknown", "params": {}},
        {"code": "passages_differ", "params": {"earlier": 2, "later": 3}},
    ]
    assert twin_reasons({"anchors": {"display_title_equal": True, "department_relation": "same"}}) == [
        {"code": "same_title", "params": {}}, {"code": "same_department", "params": {}}]
