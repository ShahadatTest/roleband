"""How the dedup feature bench counts: pure arithmetic, no DB.

The bench's verdict is an argument about whether a feature separates one
opening from two, so the parts that turn text into a number and numbers into a
verdict are pinned here, including the control arm that lets the run fail.
"""

from __future__ import annotations

import pytest

from scripts.bench_dedup_features import (
    EXIT_UNMEASURED,
    Pair,
    render,
    separation,
)
from tracker.config import get_settings
from tracker.lineage.content_diff import signature, signature_jaccard


def test_the_signature_is_a_set_of_longer_words_ignoring_case():
    # Distinct words over three characters: "team" x3
    # counts once, "our"/"and"/"AI" are too short, case folds.
    assert signature("Our TEAM and our team build AI tooling for the team") == frozenset(
        {"team", "build", "tooling"}
    )


def test_repeated_boilerplate_cannot_raise_the_signature_score():
    # A bag of words would score the padded pair higher; a set cannot.
    base = "lead payments platform strategy"
    padded = base + " equal opportunity employer" * 20
    other = "lead payments platform roadmap" + " equal opportunity employer" * 20
    assert signature_jaccard(padded, other) == signature_jaccard(
        base + " equal opportunity employer", "lead payments platform roadmap equal opportunity employer"
    )


def test_a_missing_description_is_no_score_not_a_zero():
    assert signature_jaccard(None, "lead payments platform") is None
    assert signature_jaccard("a an of", "lead payments platform") is None
    assert signature_jaccard("lead payments platform", "lead payments platform") == 1.0


def test_separation_reads_as_the_probability_of_ranking_higher():
    assert separation([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert separation([0.1, 0.2], [0.9, 0.8]) == 0.0
    assert separation([0.5], [0.5]) == 0.5
    assert separation([0.9, 0.3], [0.5]) == 0.5
    assert separation([], [0.5]) is None


def _pair(cohort: str, cosine: float, sig: float, n: int) -> Pair:
    return Pair(cohort, n, n + 1000, "acme", "Staff PM", "Staff PM", cosine, sig, sig)


def test_the_run_fails_when_another_company_outranks_a_confirmed_opening(capsys):
    # The negative control is what lets the bench fail: broken inputs (a title-
    # only embedding, a wrong description) put another company's posting above
    # one opening listed twice.
    opening = [_pair("same_opening", 0.99, 0.95, n) for n in range(3)]
    healthy = [_pair("control_cross_company", 0.50, 0.15, 10 + n) for n in range(3)]
    assert render(opening + healthy, listing=0) == 0

    broken = [_pair("control_cross_company", 0.995, 0.15, 10 + n) for n in range(3)]
    assert render(opening + broken, listing=0) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_pair_without_both_descriptions_is_left_out_of_every_feature(capsys):
    # The title-only embedding scores 0.45: letting cosine alone count it would
    # fail the run on evidence the other features never saw.
    opening = [_pair("same_opening", 0.99, 0.95, n) for n in range(3)]
    title_only = Pair("same_opening", 99, 98, "acme", "Staff PM", "Staff PM", 0.45, None, None)
    control = [_pair("control_cross_company", 0.50, 0.15, 10 + n) for n in range(3)]
    assert render([*opening, title_only, *control], listing=0) == 0
    out = capsys.readouterr().out
    assert "n=3 (1 without both descriptions, left out)" in out
    assert "99<-98 acme (same_opening): cosine now 0.450" in out


_OPENINGS = [_pair("same_opening", 0.99, 0.95, n) for n in range(3)]
_CONTROLS = [_pair("control_cross_company", 0.50, 0.15, 10 + n) for n in range(3)]
_TITLE_ONLY = Pair("same_opening", 99, 98, "acme", "Staff PM", "Staff PM", 0.45, None, None)


@pytest.mark.parametrize(
    "pairs",
    [[], _OPENINGS, _CONTROLS, [_TITLE_ONLY, *_CONTROLS]],
    ids=["nothing", "no_control", "no_confirmed_opening", "opening_without_descriptions"],
)
def test_a_run_with_an_empty_side_is_unmeasured_not_a_pass(pairs, capsys):
    """A benchmark that cannot fail measures nothing. With no scored pair on
    either side of the control comparison, `separation` is None, and a pass
    would rest on no evidence."""
    assert render(pairs, listing=0) == EXIT_UNMEASURED
    assert "UNMEASURED" in capsys.readouterr().out


def test_the_disagreement_bands_are_the_detector_s_own(monkeypatch, capsys):
    """The report's bands follow `lineage_cos_suspect` and `lineage_cos_auto`,
    not a copy of them that stops matching the detector when either is tuned."""
    monkeypatch.setattr(get_settings(), "lineage_cos_suspect", 0.93)
    monkeypatch.setattr(get_settings(), "lineage_cos_auto", 0.97)
    pending = [_pair("pending_lineage", cos, 0.30, 100 + n) for n, cos in enumerate((0.92, 0.95, 0.98))]

    assert render([*_OPENINGS, *_CONTROLS, *pending], listing=0) == 0
    out = capsys.readouterr().out
    assert "cosine >= 0.93," in out
    assert "2 of 2 high-cosine proposals" in out, "0.92 is under the suspect floor"
    assert "cosine [0.930, 0.970): 1 of 1" in out
    assert "cosine [0.970, 1.000): 1 of 1" in out
