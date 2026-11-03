"""`serialize_job` exposes disclosed_comp on the detail view only, with the
correct not-processed / processed-none / disclosed shapes."""

from __future__ import annotations

from datetime import UTC, datetime

from tracker.api.serializers.jobs import serialize_job
from tracker.db.models import Job

CHECKED = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _job() -> Job:
    j = Job()
    j.id = 1
    j.company = "anthropic"
    j.title = "Program Manager"
    j.description_text = "Annual Salary: $210,000—$260,000 USD"
    return j


def test_not_processed_yields_null():
    j = _job()
    j.structured_at = None
    data = serialize_job(j, detail=True)
    assert data["disclosed_comp"] is None


def test_a_band_stated_before_the_text_was_read_is_shown():
    """A page or connector band is stated pay whether or not the text pass has
    read the posting; `checked_at` names a text read, so none here."""
    j = _job()
    j.structured_at = None
    j.disclosed_base_min = 210000
    j.disclosed_base_max = 260000
    j.disclosed_currency = "USD"
    j.disclosed_pay_period = "year"
    j.disclosed_source = "page"
    dc = serialize_job(j, detail=True)["disclosed_comp"]
    assert (dc["disclosed"], dc["base_min"], dc["from_pay_field"], dc["checked_at"]) == (True, 210000, True, None)


def test_processed_with_band():
    j = _job()
    j.structured_at = CHECKED
    j.disclosed_base_min = 210000
    j.disclosed_base_max = 260000
    j.disclosed_currency = "USD"
    # Anthropic never says whether its "Annual Salary" figure is base or total.
    j.disclosed_pay_basis = "unclear"
    j.disclosed_pay_period = "year"
    j.disclosed_snippet = "$210,000—$260,000 USD"
    j.disclosed_confidence = "high"

    dc = serialize_job(j, detail=True)["disclosed_comp"]
    assert dc["disclosed"] is True
    assert dc["base_min"] == 210000 and dc["base_max"] == 260000
    assert dc["currency"] == "USD"
    assert dc["pay_basis"] == "unclear"
    assert dc["snippet"] == "$210,000—$260,000 USD"
    assert dc["checked_at"] == CHECKED


def test_stated_bonus_pct_is_exposed():
    j = _job()
    j.structured_at = CHECKED
    j.disclosed_base_min, j.disclosed_base_max = 240000, 334000
    j.disclosed_pay_basis = "base"
    j.disclosed_bonus_pct = 0.25  # Google states "+ 25% bonus target"
    assert serialize_job(j, detail=True)["disclosed_comp"]["bonus_pct"] == 0.25


def test_processed_no_band():
    j = _job()
    j.structured_at = CHECKED  # checked, posting disclosed nothing
    dc = serialize_job(j, detail=True)["disclosed_comp"]
    assert dc["disclosed"] is False
    assert dc["base_min"] is None


def test_list_view_omits_disclosed_comp():
    j = _job()
    j.structured_at = CHECKED
    data = serialize_job(j, detail=False)
    assert "disclosed_comp" not in data
    assert "description_text" not in data  # detail-only fields stay off list rows
    assert "description_sections" not in data


def test_detail_exposes_structured_description_sections():
    j = _job()
    j.description_sections = [
        {"key": "summary", "title": "Summary", "content": "Build the platform."},
        {
            "key": "pay_and_benefits",
            "title": "Pay & Benefits",
            "content": "Base pay range: $250,800 to $376,300.",
        },
    ]
    data = serialize_job(j, detail=True)
    assert [section["key"] for section in data["description_sections"]] == [
        "summary",
        "pay_and_benefits",
    ]
    assert "$250,800" in data["description_sections"][1]["content"]


def test_list_rows_carry_a_cheap_discloses_pay_flag():
    """The board badge and the `discloses_pay` filter need one boolean, not the whole
    band object — list payloads stay thin."""
    j = _job()
    j.structured_at = CHECKED
    j.disclosed_base_min, j.disclosed_base_max = 240000, 334000
    assert serialize_job(j, detail=False)["discloses_pay"] is True


def test_list_rows_expose_role_track_for_visible_classification():
    j = _job()
    j.track = "product_program"
    assert serialize_job(j, detail=False)["track"] == "product_program"


def test_discloses_pay_is_false_when_the_posting_stated_nothing():
    j = _job()
    j.structured_at = CHECKED  # checked; no band
    assert serialize_job(j, detail=False)["discloses_pay"] is False


def test_estimate_and_disclosed_coexist():
    j = _job()
    j.comp_low, j.comp_high, j.comp_median = 560000, 840000, 700000
    j.structured_at = CHECKED
    j.disclosed_base_min, j.disclosed_base_max = 210000, 260000
    data = serialize_job(j, detail=True)
    # The level-seeded estimate is untouched by the disclosed band.
    assert data["comp_median"] == 700000
    assert data["disclosed_comp"]["base_max"] == 260000
