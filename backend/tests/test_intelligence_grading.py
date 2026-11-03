"""Accuracy and parseability answer different questions.

A parsed wrong answer is not accurate, and an SDK error supplies no answer
to grade. The fold must keep those axes separate, including failures recorded
only in route_attempts after escalation, rather than scoring a deployment
defect against a model or hiding a rejected answer.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tracker.intelligence.policy import TierMeasurement
from tracker.intelligence.telemetry import fold_measurements, grade_row


def _row(
    provider: str = "omlx",
    validation_result: str = "ok",
    failure_class: str | None = None,
    latency_ms: int | None = 1000,
    meta: dict | None = None,
):
    return SimpleNamespace(
        provider=provider,
        validation_result=validation_result,
        failure_class=failure_class,
        latency_ms=latency_ms,
        meta=meta or {},
    )


# -- disclosed_comp: the deterministic referee -------------------------------- #


def test_a_band_that_survives_grounding_is_a_correct_answer():
    row = _row(meta={"disclosed": True})
    assert grade_row("disclosed_comp", row) is True


def test_a_band_that_fails_grounding_is_a_wrong_answer():
    """`extract.py` writes `invalid`/`validation` when the model claims a band
    that fails grounding."""
    row = _row(validation_result="invalid", failure_class="validation")
    assert grade_row("disclosed_comp", row) is False


def test_a_band_the_model_missed_but_the_extractor_found_is_a_wrong_answer():
    """The response parsed, so it is logged `validation_result="ok"`, and a
    deterministic extractor then found, in the same input text, a band the
    model said was not there. Dropping a real band is a wrong answer, never a
    success."""
    row = _row(validation_result="ok", meta={"deterministic_recovery": True})

    assert row.validation_result == "ok", "the parseability axis is untouched"
    assert grade_row("disclosed_comp", row) is False


def test_a_mechanical_failure_is_ungraded_not_wrong():
    """`sdk_error` is an SDK bug. A call that never reached the model says nothing about its judgement, and
    scoring it as a wrong answer would blame a model for a deployment defect."""
    for failure in ("sdk_error", "timeout", "unavailable"):
        assert grade_row("disclosed_comp", _row("apple_fm", "invalid", failure)) is None


def test_no_band_claimed_and_none_recovered_stays_ungraded():
    """The posting probably has no pay band — but nothing here can prove it.
    Inventing a verdict from silence would make the metric unfalsifiable, and
    would hand a model that answers "no band" to everything a perfect score."""
    assert grade_row("disclosed_comp", _row(meta={"disclosed": False})) is None
    assert grade_row("disclosed_comp", _row(meta={})) is None


def test_the_test_task_grades_the_same_way_as_the_production_one():
    """`disclosed_comp_test` is the bench's task name for the identical work;
    prefix matching grades both."""
    row = _row(meta={"disclosed": True})
    assert grade_row("disclosed_comp_test", row) is True


# -- duplicate_review: the human referee -------------------------------------- #


def _review(link_id: int, recommendation: str, kind: str = "duplicate", **kw):
    return _row(meta={"link_id": link_id, "proposal_kind": kind,
                      "recommendation": recommendation}, **kw)


def test_agreeing_with_the_human_verdict_is_correct():
    verdicts = {("duplicate", 43): "confirmed"}
    assert grade_row("duplicate_review", _review(43, "confirmed"), verdicts) is True


def test_disagreeing_with_the_human_verdict_is_wrong():
    verdicts = {("duplicate", 43): "rejected"}
    assert grade_row("duplicate_review", _review(43, "confirmed"), verdicts) is False


def test_proposal_kind_is_required_because_link_ids_collide():
    """Lineage and twin ids are separate sequences and their exclusivity means
    the SAME pair appears under both endpoints. Grading id 43 without knowing
    which table it came from can score the model against another link's
    verdict."""
    verdicts = {("duplicate", 43): "confirmed", ("twin", 43): "rejected"}

    assert grade_row("duplicate_review", _review(43, "confirmed", kind="twin"), verdicts) is False
    assert grade_row("duplicate_review", _review(43, "confirmed"), verdicts) is True

    without_kind = _row(meta={"link_id": 43, "recommendation": "confirmed"})
    assert grade_row("duplicate_review", without_kind, verdicts) is None


def test_an_unreviewed_link_is_ungraded():
    """A `pending` link has no verdict. It appears in no verdict map, and the
    absence must read as "not yet judged", never as a disagreement."""
    assert grade_row("duplicate_review", _review(99, "confirmed"), {}) is None
    assert grade_row("duplicate_review", _review(99, "confirmed"), None) is None


def test_uncertain_counts_as_wrong_so_hedging_cannot_buy_accuracy():
    """Treating a hedge as unmeasurable would let a model reach 100% accuracy by
    never committing: the same falsifiability rule that makes synthetic negative
    controls mandatory. A judge that will not judge did not help."""
    verdicts = {("duplicate", 43): "confirmed"}
    assert grade_row("duplicate_review", _review(43, "uncertain"), verdicts) is False


def test_synthetic_controls_are_not_graded_from_the_database():
    """The bench's controls carry negative ids with no link row. Their ground
    truth lives in the bench script, and encoding "a control is always rejected"
    here would bake one script's construction into the substrate."""
    assert grade_row("duplicate_review_control", _review(-3, "rejected"), {}) is None


def test_an_unknown_task_is_never_graded():
    """A task with no referee must report "no evidence", not a default verdict."""
    assert grade_row("some_future_task", _row(meta={"disclosed": True})) is None


# -- the fold, and the two axes staying separate ------------------------------- #


def test_accuracy_is_none_rather_than_zero_when_nothing_could_be_graded():
    """`None` and 0.0 are opposite findings. Collapsing them makes a tier with
    no measurement look like the worst tier available — and `skip_reason`
    reads records to veto tiers."""
    unmeasured = TierMeasurement(provider="omlx", attempts=10, ok=10)
    assert unmeasured.accuracy is None
    assert TierMeasurement(provider="omlx", attempts=1, graded=2, correct=0).accuracy == 0.0


def test_the_fold_reproduces_the_live_apple_fm_geometry():
    """The fold keeps the two distinct measurements, both
    right. 40 sdk_error + 12 grounding failures + 74 grounded + 1 silent no-band."""
    rows = (
        [_row("apple_fm", "invalid", "sdk_error") for _ in range(40)]
        + [_row("apple_fm", "invalid", "validation") for _ in range(12)]
        + [_row("apple_fm", meta={"disclosed": True}) for _ in range(74)]
        + [_row("apple_fm", meta={"disclosed": False})]
    )

    measured = fold_measurements(rows, task_type="disclosed_comp_test")["apple_fm"]

    assert measured.attempts == 127
    assert measured.ok == 75
    assert round(measured.success_rate, 3) == 0.591
    assert measured.graded == 86
    assert measured.correct == 74
    assert round(measured.accuracy, 3) == 0.860
    assert measured.success_rate < measured.accuracy, "the two axes are not the same question"


def test_a_fold_without_a_task_type_grades_nothing_and_still_measures():
    """Grading needs to know which referee applies. Callers that only want the
    parseability axis still get it."""
    measured = fold_measurements([_row(meta={"disclosed": True})])["omlx"]
    assert measured.attempts == 1 and measured.ok == 1
    assert measured.graded == 0 and measured.accuracy is None


def test_an_earlier_tier_whose_answer_was_refuted_is_graded_wrong():
    """The shape of an escalation.

    A refuted answer NEVER appears as a row of its own: the row belongs to
    whichever tier answered next, and the rejected tier survives only in
    `route_attempts`. Skipping those on the theory that "a failure entry has no
    answer to judge" makes the metric flatter the tier it exists to expose: a
    run that refutes some answers would still report 100% accuracy.
    """
    rows = [
        _row(
            "omlx",
            meta={
                "disclosed": True,
                "route_attempts": [
                    {"provider": "apple_fm", "outcome": "failed", "failure_class": "validation"}
                ],
            },
        )
    ]

    measured = fold_measurements(rows, task_type="disclosed_comp")

    assert measured["apple_fm"].attempts == 1
    assert measured["apple_fm"].graded == 1
    assert measured["apple_fm"].correct == 0
    assert measured["apple_fm"].accuracy == 0.0
    assert measured["omlx"].graded == 1 and measured["omlx"].correct == 1


def test_an_earlier_tier_that_merely_broke_is_still_ungraded():
    """The other half: `validation` is the only failure class that
    is a judgement. A timeout or SDK error means no answer ever existed, and
    scoring it would blame a model for a deployment defect."""
    for failure in ("timeout", "sdk_error", "unsupported_schema"):
        rows = [
            _row(
                "omlx",
                meta={
                    "disclosed": True,
                    "route_attempts": [
                        {"provider": "apple_fm", "outcome": "failed", "failure_class": failure}
                    ],
                },
            )
        ]
        measured = fold_measurements(rows, task_type="disclosed_comp")
        assert measured["apple_fm"].attempts == 1, failure
        assert measured["apple_fm"].graded == 0, failure
        assert measured["apple_fm"].accuracy is None, failure


def test_the_live_escalation_run_reports_apple_fm_at_its_true_accuracy():
    """An escalation run: 45 answers accepted, 3 refuted and escalated to omlx.
    The refuted three are the whole point: 100% would be a lie."""
    accepted = [_row("apple_fm", meta={"disclosed": True}) for _ in range(45)]
    escalated = [
        _row(
            "omlx",
            meta={
                "disclosed": True,
                "route_attempts": [
                    {"provider": "apple_fm", "outcome": "failed", "failure_class": "validation"},
                    {"provider": "omlx", "outcome": "ok"},
                ],
            },
        )
        for _ in range(3)
    ]

    measured = fold_measurements(accepted + escalated, task_type="disclosed_comp")

    apple = measured["apple_fm"]
    assert apple.attempts == 48
    assert apple.graded == 48 and apple.correct == 45
    assert round(apple.accuracy, 3) == 0.938, "94%, not 100%"
    assert measured["omlx"].correct == 3


@pytest.mark.parametrize("recommendation,verdict,expected", [
    ("confirmed", "confirmed", True),
    ("rejected", "rejected", True),
    ("confirmed", "rejected", False),
    ("rejected", "confirmed", False),
])
def test_the_two_vocabularies_line_up_directly(recommendation, verdict, expected):
    """The model's `recommendation` and the link's human `status` use the same
    words, so grading is a comparison rather than a translation table. A
    translation layer here would be a place for the two to silently drift."""
    graded = grade_row(
        "duplicate_review", _review(7, recommendation), {("duplicate", 7): verdict}
    )
    assert graded is expected
