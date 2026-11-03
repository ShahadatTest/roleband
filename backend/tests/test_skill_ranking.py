"""`skills.analytics.rank_skills`: what is characteristic of a slice.

A ranking by count leads every slice with the same competencies. These pin the
distinctiveness ranking, with negative controls: a skill
at the market's own rate is not distinctive, and a tiny sample cannot outrank a
well-evidenced one.
"""

from __future__ import annotations

from tracker.skills.analytics import COMPETENCY_CATEGORIES, rank_skills

META = {
    "python": ("Python", "language"),
    "kubernetes": ("Kubernetes", "infra"),
    "rust": ("Rust", "language"),
    "sql": ("SQL", "language"),
    "roadmapping": ("Roadmapping", "process"),
    "mentorship": ("Mentorship", "leadership"),
}
MARKET = {"python": 600, "kubernetes": 100, "rust": 10, "sql": 300, "roadmapping": 420, "mentorship": 200}


def test_the_whole_market_ranks_skills_by_share_and_lists_competencies_apart():
    out = rank_skills(MARKET, 1000, MARKET, 1000, META, narrowed=False)
    assert [r["term"] for r in out["items"]] == ["python", "sql", "kubernetes", "rust"]
    assert [r["term"] for r in out["competencies"]] == ["roadmapping", "mentorship"]
    assert {r["lift"] for r in out["items"]} == {1.0}
    assert {r["distinctiveness"] for r in out["items"]} == {0.0}
    assert out["items"][0]["share"] == 0.6 and out["roles"] == 1000


def test_a_narrowed_slice_leads_with_what_sets_it_apart_not_what_it_names_most():
    # 50 platform roles: Python named by 30 (60%, the market's own rate),
    # Kubernetes by 25 (50% against the market's 10%).
    slice_counts = {"python": 30, "kubernetes": 25, "sql": 5, "roadmapping": 40}
    out = rank_skills(slice_counts, 50, MARKET, 1000, META, narrowed=True)
    assert [r["term"] for r in out["items"]] == ["kubernetes", "python", "sql"]
    k8s = next(r for r in out["items"] if r["term"] == "kubernetes")
    py = next(r for r in out["items"] if r["term"] == "python")
    assert k8s["lift"] == 5.0 and k8s["distinctiveness"] > 5
    # Negative control: at the market's own rate a skill is not distinctive.
    assert abs(py["distinctiveness"]) < 0.5 and py["lift"] == 1.0
    # SQL is named LESS than the market: it ranks below, never above.
    assert [r["term"] for r in out["items"]][-1] == "sql"
    assert [r["term"] for r in out["competencies"]] == ["roadmapping"]


def test_a_tiny_sample_cannot_outrank_a_well_evidenced_skill():
    # Rust: 2 of 3 roles (67% against 1%); Kubernetes: 30 of 60 (50% against 10%).
    small = rank_skills({"rust": 2, "kubernetes": 30}, 60, MARKET, 1000, META, narrowed=True)
    assert [r["term"] for r in small["items"]] == ["kubernetes", "rust"], "below MIN_DISTINCTIVE_ROLES ranks last"
    # The same share on more roles is more distinctive: the prior shrinks a small sample.
    few = rank_skills({"kubernetes": 4}, 8, MARKET, 1000, META, narrowed=True)["items"][0]
    many = rank_skills({"kubernetes": 40}, 80, MARKET, 1000, META, narrowed=True)["items"][0]
    assert few["share"] == many["share"] == 0.5
    assert many["distinctiveness"] > few["distinctiveness"] > 0


def test_competencies_are_the_process_leadership_and_collaboration_categories():
    assert COMPETENCY_CATEGORIES == {"process", "leadership", "collaboration"}


def test_nothing_in_is_nothing_out():
    assert rank_skills({}, 0, {}, 0, META, narrowed=True) == {
        "items": [], "competencies": [], "roles": 0, "market_roles": 0, "narrowed": True,
    }
