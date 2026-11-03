from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest

from tracker.analytics.level_evaluation import (
    NEAR,
    GroupInput,
    LabelTier,
    MaskMode,
    MatchRule,
    assert_no_grade_leak,
    endpoint_distance,
    independent_label,
    leakage_groups,
    majority_band,
    mask_inputs,
    match_anchors,
    observed_before,
    partition_reference,
    sealed_ids,
    usable_base,
)
from tracker.schema import LevelBand


def posting(**updates):
    row = {
        "id": 1, "company": "microsoft", "title": "Software Engineer",
        "family": "software_engineering", "track": "technical", "raw_level": "IC5",
        "location_groups": ["united_states"], "disclosed_base_min": 150000,
        "disclosed_base_max": 230000, "disclosed_currency": "USD",
        "disclosed_pay_basis": "base", "disclosed_pay_period": "year",
        "disclosed_confidence": "high", "disclosed_source": "connector",
        "description_text": "Own distributed systems and mentor engineers. Product IC5 requirements.",
    }
    return row | updates


@pytest.mark.parametrize("updates", [
    {"disclosed_pay_basis": "total"}, {"disclosed_pay_basis": "unclear"},
    {"disclosed_currency": "CAD"}, {"location_groups": []},
    {"location_groups": ["united_states", "canada"]},
    {"disclosed_pay_period": "hour"}, {"disclosed_base_max": None},
    {"disclosed_base_min": 300000}, {"disclosed_confidence": "low"},
    {"disclosed_base_min": 100, "disclosed_base_max": 200},
])
def test_noncomparable_compensation_cannot_be_an_anchor(updates):
    assert usable_base(posting())
    assert not usable_base(posting(**updates))
    assert independent_label(posting(**updates)) is None


def test_a_printed_label_ignores_all_previous_guesses_and_the_amount():
    original = independent_label(posting())
    changed = independent_label(posting(level_band="director_plus", level_basis="pay_grade",
                                        independent_band="principal", disclosed_base_min=700000,
                                        disclosed_base_max=900000))
    assert original is not None and changed is not None
    assert original.band == changed.band
    assert changed.tier is LabelTier.PRINTED
    assert changed.source == "structured_employer_grade"


def test_a_description_grade_is_read_independently_of_salary():
    label = independent_label(posting(raw_level=None, description_text=(
        "Software Engineering IC5 - The typical base pay range for this role is $150,000."
    )))
    assert label is not None and label.tier is LabelTier.PRINTED
    assert label.printed == "IC5"
    assert label.source == "description_employer_grade"


def test_a_pay_derived_stored_label_does_not_manufacture_an_anchor():
    assert independent_label(posting(raw_level=None, description_text="No employer grade.",
                                     level_basis="pay_grade", level_band="staff")) is None


_BODY = "Build payments orchestration systems with resilient storage and own distributed services across multiple regions."


@pytest.mark.parametrize("variant", range(50))
def test_planted_duplicate_variants_cannot_cross_evaluation_partitions(variant):
    base = GroupInput(1, "acme", "req-original", "Software Engineer", _BODY + " Salary $150000 USD.")
    kind = variant % 5
    other = replace(base, job_id=2, req_id="mirror-" + str(variant))
    if kind == 0:
        other = replace(other, title="  SOFTWARE  Engineer ", description=base.description.upper())
    elif kind == 1:
        other = replace(other, title="Staff Software Engineer", description=base.description)
    elif kind == 2:
        other = replace(other, description=_BODY + " Salary $170000 USD.")
    elif kind == 3:
        other = replace(other, title="Software Engineer II", description=base.description)
    else:
        other = replace(other, req_id=base.req_id, description="Changed description on the same source opening.")
    grouped = leakage_groups([base, other])
    assert grouped[1] == grouped[2]
    assert grouped == leakage_groups([other, base])


def test_a_semantic_cluster_does_not_merge_different_responsibilities():
    a = GroupInput(1, "acme", "1", "Software Engineer", _BODY, cluster_id=7)
    b = GroupInput(2, "acme", "2", "Software Engineer",
                   "Develop compiler optimizations for GPU kernels and analyze numerical precision across accelerated machine learning workloads.", cluster_id=7)
    assert leakage_groups([a, b])[1] != leakage_groups([a, b])[2]


def test_missing_descriptions_and_empty_requisitions_do_not_create_a_giant_group():
    assert len(set(leakage_groups([GroupInput(1, "acme"), GroupInput(2, "acme")]).values())) == 2


def test_cross_employer_grouping_requires_explicit_syndication():
    a = GroupInput(1, "acme", "1", "Software Engineer", _BODY, place_set_id=7)
    b = replace(a, job_id=2, company="other")
    assert leakage_groups([a, b])[1] != leakage_groups([a, b])[2]
    a, b = replace(a, syndication_id="verified-source"), replace(b, syndication_id="verified-source")
    assert leakage_groups([a, b])[1] == leakage_groups([a, b])[2]


def test_group_input_has_no_classified_level_or_compensation_fields():
    names = {f.name for f in fields(GroupInput)}
    assert not names.intersection({"raw_level", "level_band", "level_basis", "comp_median"})


def test_masking_modes_remove_all_grades_at_the_declared_granularity():
    target = posting()
    rows = [target, posting(id=2), posting(id=3, title="Infrastructure Engineer"),
            posting(id=4, disclosed_base_max=260000), posting(id=5, company="other")]
    assert sealed_ids(rows, target, MaskMode.OPENING) == {1}
    assert sealed_ids(rows, target, MaskMode.TITLE) == {1, 2, 4}
    assert sealed_ids(rows, target, MaskMode.SIGNATURE) == {1, 2, 3}


@pytest.mark.parametrize("channel", ["title", "description_text", "source_facts", "cached_features",
                                      "embedding", "search_vector", "raw_level", "level_band"])
def test_a_deliberately_leaked_grade_or_stale_cache_is_rejected(channel):
    value = {"grade": "IC5"} if channel in {"source_facts", "cached_features"} else "IC5"
    inputs = {channel: value}
    with pytest.raises(ValueError):
        assert_no_grade_leak(inputs, ["IC5"])
    cleaned = mask_inputs(inputs, ["IC5"])
    assert_no_grade_leak(cleaned, ["IC5"])


def test_masking_keeps_salary_and_required_years_and_distinguishes_the_harder_task():
    row = posting(title="Senior Software Engineer IC5", required_years=7)
    normal = mask_inputs(row, ["IC5"])
    hard = mask_inputs(row, ["IC5"], hard=True)
    assert "Senior" in normal["title"]
    assert "Senior" not in hard["title"]
    assert normal["required_years"] == 7
    assert normal["disclosed_base_min"] == 150000
    assert normal["disclosed_base_max"] == 230000
    assert "raw_level" not in normal


def test_numeric_employer_grades_do_not_erase_legitimate_experience_requirements():
    row = posting(title="Software Engineer 6", raw_level="6", required_years=6,
                  description_text="Level: 6. Requires 6 years of experience.",
                  source_facts={"grade_code": 6, "years": 6})
    with pytest.raises(ValueError):
        assert_no_grade_leak(row, ["6"])
    clean = mask_inputs(row, ["6"])
    assert "Engineer [withheld]" in clean["title"]
    assert "6 years of experience" in clean["description_text"]
    assert clean["required_years"] == 6
    assert clean["source_facts"] == {"years": 6}
    assert_no_grade_leak(clean, ["6"])


def test_held_out_atlas_rows_are_excluded_even_without_track_metadata():
    rows = [
        {"company": "microsoft", "family": "software_engineering", "base_min": 150000,
         "base_max": 230000, "rung": "IC5"},
        {"company": "microsoft", "family": "software_engineering", "base_min": 150000,
         "base_max": 260000, "rung": "IC6"},
        {"company": "other", "source_job_ids": [1], "rung": "IC5"},
    ]
    kept = partition_reference(rows, posting(), frozenset({1}), MaskMode.SIGNATURE)
    assert len(kept) == 1 and kept[0]["rung"] == "IC6"
    with pytest.raises(ValueError, match="source identities"):
        partition_reference(rows, posting(), frozenset({1}), MaskMode.OPENING)


def anchor(identifier, company, title, low=150000, high=230000):
    label = independent_label(posting(id=identifier, company=company, title=title, raw_level=None,
                                      disclosed_base_min=low, disclosed_base_max=high,
                                      description_text="Own a platform area and mentor peers."))
    assert label is not None
    return label


def test_a_repeated_requisition_cannot_manufacture_support():
    same_title = [anchor(1, "acme", "Staff Software Engineer"),
                  anchor(2, "acme", "Staff  Software Engineer")]
    assert {label.band for label in same_title} == {LevelBand.STAFF}
    assert majority_band(same_title) is None
    distinct = same_title[:1] + [anchor(3, "acme", "Staff Platform Engineer")]
    vote = majority_band(distinct)
    assert vote is not None and vote.band is LevelBand.STAFF and vote.identities == 2


def test_four_of_five_agreeing_is_the_floor_and_three_of_four_is_not():
    agreeing = [anchor(index, "acme", f"Staff {name} Engineer")
                for index, name in enumerate(("Platform", "Storage", "Payments", "Search"), start=1)]
    dissenting = anchor(5, "acme", "Senior Reliability Engineer")
    assert dissenting.band is LevelBand.SENIOR
    vote = majority_band([*agreeing, dissenting])
    assert vote is not None and vote.band is LevelBand.STAFF and vote.share == pytest.approx(0.8)
    assert majority_band([*agreeing[:3], dissenting]) is None


def test_one_employer_cannot_outvote_another_by_posting_volume():
    loud = [anchor(index, "acme", f"Staff {name} Engineer")
            for index, name in enumerate(("Platform", "Storage", "Payments", "Search", "Media"), start=1)]
    quiet = [anchor(6, "globex", "Senior Reliability Engineer")]
    by_volume = majority_band([*loud, *quiet])
    assert by_volume is not None and by_volume.band is LevelBand.STAFF
    assert majority_band([*loud, *quiet], per_employer=True) is None
    assert majority_band(loud, per_employer=True) is None


def test_a_range_matching_on_one_endpoint_only_is_not_a_near_match():
    target = anchor(1, "acme", "Staff Software Engineer")
    wider = anchor(2, "acme", "Staff Platform Engineer", high=300000)
    assert endpoint_distance(target, wider) == pytest.approx(endpoint_distance(wider, target))
    assert endpoint_distance(target, wider) > NEAR
    assert match_anchors(target, [wider], MatchRule.NEAREST_NEAR) == []
    assert match_anchors(target, [wider], MatchRule.NEAREST) == [wider]


def test_exact_matching_never_admits_a_nearly_equal_range():
    target = anchor(1, "acme", "Staff Software Engineer")
    almost = anchor(2, "acme", "Staff Platform Engineer", high=230001)
    equal = anchor(3, "acme", "Staff Storage Engineer")
    assert match_anchors(target, [almost, equal], MatchRule.EXACT) == [equal]
    assert match_anchors(target, [almost, equal], MatchRule.NEAREST_NEAR) == [equal]
    assert match_anchors(target, [almost], MatchRule.NEAREST_FIVE) == [almost]


def test_a_future_fact_cannot_enter_a_historical_prediction_even_if_backdated():
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    assert observed_before({"observed_at": "2026-07-23T00:00:00+00:00"}, cutoff)
    future = {"observed_at": "2026-10-01T00:00:00+00:00", "posted_at": "2009-01-01"}
    assert not observed_before(future, cutoff)
    assert not observed_before({"posted_at": "2009-01-01"}, cutoff)
    with pytest.raises(ValueError, match="timezone"):
        observed_before(future, datetime(2026, 8, 1))


@pytest.mark.parametrize("years", ["5 years", "5+ years", "5–8 years", "5 to 8 years"])
@pytest.mark.parametrize("hard", [False, True])
def test_experience_level_heading_keeps_years_without_exempting_actual_codes(years, hard):
    text = f"Ideal Experience Level: {years} or equivalent evidence. Employer Level: 5. IC5."
    clean = mask_inputs({"description_text": text}, ["5", "IC5"], hard=hard)
    assert f"Experience Level: {years}" in clean["description_text"]
    assert "Employer Level: 5" not in clean["description_text"]
    assert "IC5" not in clean["description_text"]
    assert_no_grade_leak(clean, ["5", "IC5"])
    with pytest.raises(ValueError):
        assert_no_grade_leak({"description_text": text}, ["5", "IC5"])


@pytest.mark.parametrize("text", ["Experience Level: 5", "Experience Level: IC5", "Experience Grade: 5 years",
                                       "Experience Level: 5, requires 8 years"])
def test_experience_word_alone_cannot_bypass_grade_masking(text):
    with pytest.raises(ValueError):
        assert_no_grade_leak({"description_text": text}, ["5", "IC5"])
    clean = mask_inputs({"description_text": text}, ["5", "IC5"])
    assert "[withheld]" in clean["description_text"]
    assert_no_grade_leak(clean, ["5", "IC5"])
