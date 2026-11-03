"""Pure-logic tests for cluster labeling (no DB, no model)."""

from __future__ import annotations

from tracker.semantic.cluster import _label


def test_label_uses_top_three_terms():
    terms = [
        {"term": "llm", "display": "LLMs", "weight": 9.0},
        {"term": "pytorch", "display": "PyTorch", "weight": 7.0},
        {"term": "cuda", "display": "CUDA / GPU", "weight": 5.0},
        {"term": "python", "display": "Python", "weight": 3.0},
    ]
    label = _label(terms, "ml_ai_research")
    assert label == "LLMs · PyTorch · CUDA / GPU"  # only top 3, in order


def test_label_falls_back_to_family_when_no_terms():
    # role_display maps the slug to a human family name.
    assert _label([], "engineering_management") == "Engineering Management"


def test_label_handles_no_terms_and_no_family():
    assert _label([], None) == "Unlabeled cluster"


# --------------------------------------------------------------------------- #
# Labels that say what a group is, and a group count that holds still
# --------------------------------------------------------------------------- #

from tracker.semantic.cluster import (  # noqa: E402
    LABEL_EXCLUDED_CATEGORIES,
    characteristic_terms,
    stable_k,
)
from tracker.skills.analytics import COMPETENCY_CATEGORIES  # noqa: E402

_META = {
    "roadmapping": ("Roadmapping", "process"),
    "python": ("Python", "language"),
    "cuda": ("CUDA / GPU", "ml_ai"),
    "kubernetes": ("Kubernetes", "infra"),
    "sql": ("SQL", "language"),
}


def test_a_group_is_labelled_by_what_sets_it_apart_never_by_a_competency():
    # Every role names Roadmapping; Python is everywhere; CUDA only in group 0,
    # Kubernetes only in group 1. By frequency both groups read "Roadmapping, Python".
    members = {
        0: [{"roadmapping", "python", "cuda"}] * 8 + [{"roadmapping", "python"}] * 2,
        1: [{"roadmapping", "python", "kubernetes", "sql"}] * 6 + [{"roadmapping", "python"}] * 4,
    }
    terms = characteristic_terms(members, _META)
    assert [t["term"] for t in terms[0]] == ["cuda"]
    assert [t["term"] for t in terms[1]] == ["kubernetes", "sql"]
    # Python is as common here as everywhere: weight 0, never a label.
    assert all(t["term"] not in {"python", "roadmapping"} for g in terms.values() for t in g)


def test_a_concept_named_by_one_member_is_noise_not_a_label():
    members = {0: [{"cuda"}] + [{"python"}] * 9, 1: [{"python"}] * 10}
    assert characteristic_terms(members, _META)[0] == []


def test_a_group_whose_roles_share_no_skill_is_named_by_its_discipline():
    # Two of three hundred roles name Cryptography, a little more often than
    # roles elsewhere: a positive weight, yet it describes almost no member.
    members = {
        0: [{"cryptography"}] * 2 + [set()] * 298,
        1: [{"python"}] * 100 + [set()] * 100,
    }
    meta = {**_META, "cryptography": ("Cryptography", "security")}
    terms = characteristic_terms(members, meta)
    assert terms[0] == []
    assert _label(terms[0], "product_management") == "Product Management"
    assert [t["term"] for t in terms[1]] == ["python"]


def test_a_label_skill_is_named_by_one_in_ten_of_the_group():
    # Swift is eight times as common here as elsewhere, but six roles in a
    # hundred are not the group; ten in a hundred are.
    elsewhere = [set()] * 600
    six = characteristic_terms({0: [{"swift"}] * 6 + [set()] * 94, 1: elsewhere}, _META)
    ten = characteristic_terms({0: [{"swift"}] * 10 + [set()] * 90, 1: elsewhere}, _META)
    assert six[0] == []
    assert [t["term"] for t in ten[0]] == ["swift"]


def test_a_skill_as_common_everywhere_is_not_a_label_however_many_name_it():
    # SQL in 11% of the group against 9% of all roles: over one in ten, but
    # no more this group's than any other's. Machine Learning in a third of
    # the group against a quarter overall does set it apart.
    members = {
        0: [{"sql"}] * 11 + [{"machine_learning"}] * 33 + [set()] * 56,
        1: [{"sql"}] * 90 + [{"machine_learning"}] * 207 + [set()] * 603,
    }
    assert [t["term"] for t in characteristic_terms(members, _META)[0]] == ["machine_learning"]


def test_the_label_exclusions_are_the_competencies():
    assert LABEL_EXCLUDED_CATEGORIES == COMPETENCY_CATEGORIES


def test_the_group_count_holds_unless_another_k_is_clearly_better():
    scores = {6: 0.110, 7: 0.118, 8: 0.105}
    assert stable_k(scores, None) == 7  # nothing standing: the best
    assert stable_k(scores, 6) == 6  # 7 is better by 0.008, under the margin: hold
    assert stable_k({6: 0.10, 7: 0.15}, 6) == 7  # clearly better: change
    assert stable_k(scores, 12) == 7  # a standing k outside the range cannot hold
