from tracker.lineage.content_diff import DescriptionDiff
from tracker.lineage.twins import TwinCandidate, connected_twin_ids, score_twin_candidate


def _diff(*, equivalent=False, comparable=True, token_similarity=0.9):
    return DescriptionDiff(comparable, equivalent, 8, 1, 1, 0.1, token_similarity, (), ())


def _candidate(**changes):
    values = dict(
        job_a_id=1,
        job_b_id=2,
        cosine=0.95,
        title_similarity=0.9,
        display_title_equal=False,
        title_grade_compatible=True,
        same_family=True,
        same_level_band=True,
        department_relation="same",
        same_lineage=False,
        description_diff=_diff(),
    )
    values.update(changes)
    return TwinCandidate(**values)


def test_near_title_with_any_full_description_difference_is_suspected():
    verdict = score_twin_candidate(_candidate())
    assert verdict.decision == "suspected"
    assert "near-title match" in verdict.reasons[-1]


def test_known_department_mismatch_rejects_but_missing_only_demotes():
    assert score_twin_candidate(_candidate(department_relation="mismatch")).decision == "reject"
    missing = score_twin_candidate(_candidate(department_relation="missing"))
    assert missing.decision == "suspected"
    assert any("department missing" in reason for reason in missing.reasons)


def test_identical_or_missing_descriptions_are_not_twin_evidence():
    assert score_twin_candidate(_candidate(description_diff=_diff(equivalent=True))).decision == "reject"
    assert score_twin_candidate(_candidate(description_diff=_diff(comparable=False))).decision == "reject"


def test_location_pay_and_time_are_not_candidate_fields_or_gates():
    assert score_twin_candidate(_candidate()).decision == "suspected"


def test_whole_description_must_be_close_without_prescribing_the_difference():
    assert score_twin_candidate(
        _candidate(description_diff=_diff(token_similarity=0.4))
    ).decision == "reject"


def test_connected_group_does_not_imply_transitive_direct_link():
    component, direct = connected_twin_ids(1, [(1, 2), (2, 3), (3, 4)])
    assert component == {2, 3, 4}
    assert direct == {2}


# --------------------------------------------------------------------------- #
# Threshold calibration invariants. The cosine floor is a cheap
# PRE-FILTER ahead of the authoritative whole-description overlap gate; these
# pin the relationship the calibration measured, so a future edit to either
# number has to face the reason the pair exists.
# --------------------------------------------------------------------------- #


def test_cosine_floor_stays_below_the_lowest_measured_true_twin():
    """In calibration over both half-samples, every pair clearing all other
    gates had cosine >= 0.899. A floor at or above that
    silently drops real twins, which is the expensive direction of wrong."""
    from tracker.config import get_settings

    assert get_settings().twin_cos_floor < 0.899


def test_the_text_gate_is_authoritative_not_the_cosine_floor():
    """A pair with a strong cosine but weak whole-description overlap is NOT a
    twin — the content gate decides, and no cosine can buy past it."""
    verdict = score_twin_candidate(_candidate(cosine=0.99, description_diff=_diff(token_similarity=0.3)))
    assert verdict.decision == "reject"
    assert any("whole-description overlap" in reason for reason in verdict.reasons)


def test_cosine_floor_still_rejects_below_itself():
    """It is a pre-filter, but a live one: a pair under the floor is rejected
    before the (expensive) description comparison is trusted."""
    from tracker.config import get_settings

    below = get_settings().twin_cos_floor - 0.01
    verdict = score_twin_candidate(_candidate(cosine=below))
    assert verdict.decision == "reject"
    assert any("semantic similarity" in reason for reason in verdict.reasons)


# --------------------------------------------------------------------------- #
# Identical titles in one department are matched automatically.
# --------------------------------------------------------------------------- #


def test_identical_titles_in_one_department_are_matched_automatically():
    # Fails "every twin is a review question" and "a title alone decides".
    verdict = score_twin_candidate(_candidate(display_title_equal=True))
    assert verdict.decision == "auto"
    assert "matched automatically" in verdict.reasons[-1]


def test_a_near_title_or_a_missing_department_stays_a_question():
    # Fails "auto whenever the text is close": each flag for a human keeps
    # the pair in the queue.
    assert score_twin_candidate(_candidate(display_title_equal=False)).decision == "suspected"
    assert score_twin_candidate(
        _candidate(display_title_equal=True, department_relation="missing")
    ).decision == "suspected"
    # The gates still come first: a grade question or a mismatch never auto.
    assert score_twin_candidate(
        _candidate(display_title_equal=True, title_grade_compatible=False)
    ).decision == "reject"
    assert score_twin_candidate(
        _candidate(display_title_equal=True, department_relation="mismatch")
    ).decision == "reject"
