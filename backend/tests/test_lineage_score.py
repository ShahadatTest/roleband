"""The repost/duplicate decision tree: gates reject; cosine ranks survivors."""

from __future__ import annotations

from tracker.lineage.score import Candidate, LineageThresholds, score_pair

CFG = LineageThresholds()


def cand(**over) -> Candidate:
    base = dict(
        job_id=2,
        prior_job_id=1,
        cosine=0.95,
        title_display_equal=True,
        title_equal=False,
        title_jaccard=0.8,
        title_grade_compatible=True,
        concurrent=False,
        gap_days=12,
        location_overlap=True,
        both_locations_empty=False,
        location_jaccard=1.0,
        same_family=True,
        same_level_band=True,
        prior_lineage_size=1,
        has_descriptions=True,
        band_relation="unknown",
    )
    base.update(over)
    return Candidate(**base)


# --- DECIDE ------------------------------------------------------------------

def test_exact_title_with_modest_cosine_auto_links_as_repost():
    v = score_pair(cand(title_equal=True, cosine=0.83), CFG)
    assert v.decision == "auto"
    assert v.relation == "repost"
    assert v.method == "title+embedding"


def test_different_title_high_cosine_auto_links():
    v = score_pair(cand(title_equal=False, title_jaccard=0.8, cosine=0.96), CFG)
    assert v.decision == "auto"
    assert v.method == "embedding"


def test_mid_cosine_goes_to_review():
    assert score_pair(cand(cosine=0.93), CFG).decision == "suspected"


def test_low_cosine_rejects():
    assert score_pair(cand(cosine=0.79, title_jaccard=0.1), CFG).decision == "reject"


def test_reworded_title_recovered_via_jaccard_into_review():
    v = score_pair(cand(cosine=0.90, title_equal=False, title_jaccard=0.8), CFG)
    assert v.decision == "suspected"
    assert v.method == "title_jaccard"


# --- GATES -------------------------------------------------------------------

def test_family_mismatch_rejects():
    assert score_pair(cand(same_family=False), CFG).decision == "reject"


def test_level_band_mismatch_rejects():
    assert score_pair(cand(same_level_band=False), CFG).decision == "reject"


def test_no_location_overlap_rejects_unless_both_empty_and_title_equal():
    assert score_pair(cand(location_overlap=False), CFG).decision == "reject"
    v = score_pair(
        cand(location_overlap=False, both_locations_empty=True, title_equal=True, cosine=0.85),
        CFG,
    )
    assert v.decision == "auto"


def test_partial_raw_location_overlap_rejects_even_when_location_groups_match():
    assert score_pair(cand(location_jaccard=0.25), CFG).decision == "reject"


def test_explicit_title_grade_mismatch_rejects_before_embedding_score():
    assert score_pair(cand(cosine=0.99, title_grade_compatible=False), CFG).decision == "reject"


def test_different_role_titles_reject_even_at_a_high_cosine():
    assert score_pair(cand(cosine=0.99, title_jaccard=0.6), CFG).decision == "reject"


def test_concurrent_titles_must_match_before_embedding_can_nominate_a_duplicate():
    assert score_pair(cand(concurrent=True, cosine=1.0, title_display_equal=False), CFG).decision == "reject"


def test_no_descriptions_and_titles_differ_rejects():
    assert score_pair(cand(has_descriptions=False, title_equal=False), CFG).decision == "reject"


def test_period_mismatch_is_a_hard_gate():
    assert score_pair(cand(band_relation="period_mismatch"), CFG).decision == "reject"


# --- DEMOTIONS ---------------------------------------------------------------

def test_concurrent_prior_is_a_duplicate_and_demoted_for_human_review():
    v = score_pair(cand(concurrent=True, cosine=0.99, gap_days=30), CFG)
    assert v.relation == "duplicate"
    assert v.decision == "suspected"  # concurrent links never auto-link


def test_large_gap_is_context_not_a_verdict_input():
    assert score_pair(cand(cosine=0.99, gap_days=400), CFG).decision == "auto"


def test_prior_lineage_at_cap_demotes():
    at_cap = CFG.max_size
    assert score_pair(cand(cosine=0.99, prior_lineage_size=at_cap), CFG).decision == "suspected"


def test_disjoint_disclosed_bands_reject():
    assert score_pair(cand(cosine=0.99, band_relation="disjoint"), CFG).decision == "reject"


def test_overlapping_bands_do_not_boost_a_suspected_pair():
    # An 0.90 cosine pair is suspected; a matching disclosed band must NOT promote it,
    # because level-and-locale-wide bands make equality uninformative.
    assert score_pair(cand(cosine=0.90, band_relation="overlap"), CFG).decision == "suspected"


def test_unknown_band_leaves_verdict_unchanged():
    with_band = score_pair(cand(cosine=0.96, band_relation="unknown"), CFG)
    assert with_band.decision == "auto"


def test_gap_is_context_not_a_verdict_input():
    v = score_pair(cand(concurrent=False, cosine=0.99, gap_days=0), CFG)
    assert v.decision == "auto"


# --- Word overlap demotes a title-only match ------------------------
# Among identical-title auto links in [0.915, 0.955) whose descriptions share
# under 60% of their words, labelled pairs are mostly two different openings
# under a generic title. Such a link goes to review.

def test_identical_titles_over_different_descriptions_go_to_review():
    v = score_pair(cand(title_equal=True, cosine=0.93, word_overlap=0.39), CFG)
    assert v.decision == "suspected"
    assert v.method == "title+embedding"
    assert any("share 39% of their words" in r for r in v.reasons)


def test_word_overlap_only_ever_demotes_never_rejects():
    # Even a very low overlap is a review, never a reject: some such pairs are reposts.
    v = score_pair(cand(title_equal=True, cosine=0.86, word_overlap=0.05), CFG)
    assert v.decision == "suspected"


def test_identical_titles_with_shared_descriptions_still_auto_link():
    for overlap in (0.6, 0.85, None):  # at the bar, above it, or no text to compare
        v = score_pair(cand(title_equal=True, cosine=0.93, word_overlap=overlap), CFG)
        assert v.decision == "auto", overlap


def test_an_embedding_only_match_is_not_demoted_by_word_overlap():
    # At or above cos_auto the embedding alone decides; the overlap
    # demotion must not extend past its configured score window.
    v = score_pair(cand(title_equal=False, cosine=0.96, word_overlap=0.3), CFG)
    assert v.decision == "auto"
    v = score_pair(cand(title_equal=True, cosine=0.96, word_overlap=0.3), CFG)
    assert v.decision == "auto"
