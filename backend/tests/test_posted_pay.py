"""Posted pay is independent evidence; a price never manufactures a level."""

from datetime import UTC, datetime

import pytest

from tracker.enrich.level_mapper import read_level
from tracker.enrich.level_pay import posted_bases, posted_title_grades
from tracker.levels import atlas
from tracker.pay_store.posted_pay import build
from tracker.schema import LevelBand, LevelConfidence, RawJob, SourceDisclosedComp


def _posting(id=1, **changes):
    return {
        "id": id, "company": "anthropic", "title": "Senior Staff Software Engineer, API",
        "department": "Engineering", "team": "API", "raw_level": None,
        "location_groups": ["silicon_valley", "united_states"],
        "disclosed_currency": "USD", "disclosed_pay_basis": "base", "disclosed_pay_period": "year",
        "disclosed_base_min": 405_000, "disclosed_base_max": 485_000,
        "first_posted_at": datetime(2026, 1, 1, tzinfo=UTC), "posted_at": None,
        "first_seen": datetime(2026, 2, 1, tzinfo=UTC), **changes,
    }


def _rows(postings):
    return build(postings, {"anthropic", "microsoft", "1password", "intel"}, "2026-10-10").rows


def _grades(postings):
    # Round-trip through the real atlas writer: CSV values are strings.
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(atlas.posted_pay_text(_rows(postings)))))
    return posted_title_grades(rows)


@pytest.mark.parametrize("title,family", [
    ("Senior Product Manager, Manufacturing Software", "product_management"),
    ("Senior Technical Program Manager, Advanced Effects", "technical_program_management"),
    ("Senior Materials Program Manager", "program_management"),
])
def test_explicit_senior_pm_marker_confirms_pay_independently_of_its_range(title, family):
    raw = RawJob(company="anduril", title=title, req_id="", url="")
    reading = read_level(raw, family)
    assert (reading.band, reading.confidence) == (LevelBand.SENIOR, LevelConfidence.CONFIRMED)
    grades = _grades([_posting(company="1password", title=title,
                              disclosed_base_min=120_000, disclosed_base_max=180_000)])
    assert len(grades) == 1
    assert (grades[0].family, grades[0].band) == (family, LevelBand.SENIOR)


@pytest.mark.parametrize("company,title", [
    ("1password", "Product Manager"),
    ("1password", "Technical Program Manager"),
    ("1password", "Senior and Principal Product Manager"),
    ("intel", "Senior Product Manager"),
])
def test_bare_dual_and_employer_weak_pm_levels_do_not_anchor_posted_pay(company, title):
    assert _grades([_posting(company=company, title=title)]) == []


def test_one_stated_posting_prices_the_level_but_never_maps_its_range():
    grades = _grades([_posting(company="1password", title="Senior Staff Product Manager, Device Security",
                              disclosed_base_min=178_000, disclosed_base_max=258_000)])
    pay = posted_bases(grades)[("1password", "product_management", LevelBand.PRINCIPAL)]
    assert (pay.base_min, pay.base_max, pay.ranges) == (178_000, 258_000, 1)
    assert grades[0].anchors == 1
    assert pay.postings == 1
    plain = RawJob(company="1password", title="Product Manager", req_id="", url="")
    without_pay = read_level(plain, "product_management")
    plain.source_disclosed_comp = SourceDisclosedComp(
        base_min=178_000, base_max=258_000, currency="USD", pay_basis="base", pay_period="year")
    assert read_level(plain, "product_management") == without_pay


@pytest.mark.parametrize("title,family", [
    ("AI Product Manager Graduate (Product-Social) - 2027 Start", "product_management"),
    ("Junior Solutions Engineer - Partnerships, Ads", "solutions_sales_eng"),
    ("Software Engineer, University Graduate", "software_engineering"),
])
def test_explicit_early_career_titles_are_independent_entry_pay_evidence(title, family):
    grades = _grades([_posting(company="1password", title=title)])
    assert len(grades) == 1
    assert (grades[0].family, grades[0].band) == (family, LevelBand.ENTRY)
    assert grades[0].anchors == 1


@pytest.mark.parametrize("title", [
    "Software Engineer", "Engineering Manager", "Senior / Staff Software Engineer",
    "Staff + Senior Software Engineer", "Lead Software Engineer", "Graduate / Senior Product Manager",
])
def test_unplaced_role_words_and_dual_levels_price_nothing(title):
    assert _grades([_posting(title=title)]) == []


def test_printed_level_survives_but_a_director_overriding_it_does_not_price_it():
    rows = [_posting(company="microsoft", title="Software Engineer", raw_level="IC4"),
            _posting(2, company="microsoft", title="Director, Software Engineering", raw_level="IC4")]
    grades = _grades(rows)
    assert len(grades) == 1
    assert grades[0].band is LevelBand.SENIOR


@pytest.mark.parametrize("change, reason", [
    ({"company": "not-named"}, "company not named"),
    ({"location_groups": ["uk"]}, "not exclusively US locations"),
    ({"location_groups": ["united_states", "canada"]}, "not exclusively US locations"),
    ({"location_groups": []}, "not exclusively US locations"),
    ({"disclosed_currency": "CAD"}, "not annual USD base"),
    ({"disclosed_pay_basis": "total"}, "not annual USD base"),
    ({"disclosed_pay_basis": "unclear"}, "not annual USD base"),
    ({"disclosed_pay_period": "hour"}, "not annual USD base"),
    ({"disclosed_base_max": None}, "no valid complete range"),
    ({"disclosed_base_min": 500_000}, "no valid complete range"),
    ({"disclosed_base_min": 0}, "no valid complete range"),
    ({"disclosed_base_min": 100, "disclosed_base_max": 200}, "not annual USD base"),
    ({"first_posted_at": None, "first_seen": None}, "no year"),
])
def test_non_base_foreign_incomplete_and_invalid_pay_is_counted_and_excluded(change, reason):
    built = build([_posting(**change)], {"anthropic"}, "2026-10-10")
    assert built.rows == []
    assert built.dropped == {reason: 1}


def test_deduplicated_postings_weight_the_range_and_latest_year_wins():
    older = _posting(5, first_posted_at=datetime(2025, 1, 1, tzinfo=UTC),
                     disclosed_base_min=1_000_000, disclosed_base_max=2_000_000)
    rows = [_posting(1), _posting(1), _posting(2), _posting(3),
            _posting(4, disclosed_base_min=350_000, disclosed_base_max=850_000), older]
    built = _rows(rows)
    assert sum(r["n"] for r in built) == 5
    pay = posted_bases(_grades(rows))[("anthropic", "software_engineering", LevelBand.PRINCIPAL)]
    assert (pay.year, pay.base_min, pay.base_max, pay.ranges) == (2026, 405_000, 485_000, 2)
    assert pay.postings == 4


def test_context_and_exact_ranges_remain_separate_cells():
    rows = _rows([_posting(), _posting(2, team="Infrastructure"),
                  _posting(3, raw_level="IC5"), _posting(4, disclosed_base_max=490_000)])
    assert len(rows) == 4
    assert all(r["as_of"] == "2026-10-10" for r in rows)
    assert all("band" not in r and "family" not in r for r in rows)


def test_a_reviewed_capture_and_stored_job_at_one_requisition_count_once():
    rows = _rows([_posting(id=-1, req_id="official-123"), _posting(id=500, req_id="official-123")])
    assert len(rows) == 1 and rows[0]["n"] == 1


@pytest.mark.parametrize("title", ["Flight Analysis Engineer I/II", "Ground Systems Engineer II/Senior"])
def test_dual_rung_codes_do_not_price_the_upper_level(title):
    from tracker.enrich.level_mapper import title_states_band

    raw = RawJob(company="rocket-lab", req_id="", title=title, url="")
    reading = read_level(raw, "software_engineering")
    assert not title_states_band(title, reading, company=raw.company)


def test_reviewed_capture_requires_provenance_and_parses_evidence_dates(tmp_path):
    import json

    from scripts.build_posted_pay import evidence_rows

    path = tmp_path / "capture.json"
    row = _posting(req_id="123", source_url="https://careers.example.test/123", snippet="Base pay $405k–$485k")
    path.write_text(json.dumps([row], default=str))
    loaded = evidence_rows([path])
    assert loaded[0]["first_posted_at"].year == 2026
    assert _rows(loaded)[0]["n"] == 1
    del row["snippet"]
    path.write_text(json.dumps([row], default=str))
    with pytest.raises(ValueError, match="pay quote"):
        evidence_rows([path])


def test_shipped_singleton_answers_anthropic_principal_and_1password_principal():
    from tracker.enrich.level_pay import level_bases

    for company, family in (("anthropic", "software_engineering"), ("1password", "product_management")):
        pay = level_bases()[(company, family, LevelBand.PRINCIPAL)].posted
        assert pay is not None
        assert pay.base_min > 0 and pay.base_max >= pay.base_min


def test_employer_captures_fill_project_management_operations_and_entry_product_gaps():
    from tracker.enrich.level_pay import level_bases

    shadow = level_bases()
    ey = shadow[("ey", "program_management", LevelBand.SENIOR)].posted
    assert ey is not None and ey.base_min == ey.base_max == 205_510
    for company, family, band in (
        ("amazon", "operations_facilities", LevelBand.SENIOR),
        ("tiktok", "product_management", LevelBand.ENTRY),
        ("tiktok", "legal_policy", LevelBand.SENIOR),
    ):
        pay = shadow[(company, family, band)].posted
        assert pay is not None and pay.postings >= 1 and 0 < pay.base_min <= pay.base_max
