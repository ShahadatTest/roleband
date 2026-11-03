"""Eightfold job pages, read for every tenant, and the pay reads that cannot
isolate a figure.

The fixtures are real PCSX detail payloads, trimmed to the fields the reader
takes: each tenant words its pay statement its own way, which is the case one
employer's phrasing cannot cover.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracker.connectors.detail import get_detail_connector, structure_job_detail
from tracker.connectors.detail.ashby import AshbyDetailConnector
from tracker.connectors.detail.base import (
    PAY_SECTION_KEY,
    pay_unread,
    promote_section,
    sections_to_text,
)
from tracker.connectors.detail.eightfold import EightfoldDetailConnector
from tracker.connectors.detail.greenhouse import GreenhouseDetailConnector
from tracker.connectors.detail.netflix import NetflixDetailConnector
from tracker.connectors.detail.openai import OpenAIDetailConnector
from tracker.connectors.listing.base import SchemaDriftDetector
from tracker.db.models import Job
from tracker.db.repo import _apply_fields
from tracker.schema import EnrichedJob, JobDescriptionSection, LevelBand, LevelConfidence, RawJob

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "listings" / "eightfold"


def _payload(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())["data"]


def _pay(sections: list[JobDescriptionSection]) -> list[JobDescriptionSection]:
    return [section for section in sections if section.key == PAY_SECTION_KEY]


def test_every_tenant_but_netflix_is_read_without_netflix_s_wording():
    assert type(get_detail_connector("micron", "eightfold")) is EightfoldDetailConnector
    assert type(get_detail_connector("qualcomm", "eightfold")) is EightfoldDetailConnector
    assert type(get_detail_connector("netflix", "eightfold")) is NetflixDetailConnector


@pytest.mark.parametrize("fixture, company, band, opens", [
    ("micron_detail.json", "micron", (186_000, 317_000),
     "The US base salary range that Micron Technology estimates it could pay"),
    ("qualcomm_detail.json", "qualcomm", (174_400, 261_600),
     "Pay range and Other Compensation & Benefits:"),
])
def test_a_tenant_s_own_pay_wording_is_read_as_a_complete_page_with_its_band(
    fixture, company, band, opens
):
    read = get_detail_connector(company, "eightfold").parse_payload(_payload(fixture))

    assert read.mode == "primary" and read.complete
    assert read.source_disclosed_comp is not None
    comp = read.source_disclosed_comp
    assert (comp.base_min, comp.base_max) == band
    assert (comp.pay_basis, comp.pay_period) == ("base", "year")
    [pay] = _pay(read.sections)
    # The whole statement moves, from its first word, and only once.
    assert pay.content.startswith(opens)
    low = f"{band[0]:,}"
    assert sections_to_text(read.sections).count(low) == 1
    assert all(low not in section.content for section in read.sections if section is not pay)


def test_a_posting_that_states_a_band_per_place_leaves_the_band_to_the_text_pass():
    """PayPal names San Jose and Scottsdale, each with its own range. The text
    pass picks the one for the posting's place; this reader knows no place and
    would take the first, so it states none."""
    read = get_detail_connector("paypal", "eightfold").parse_payload(
        _payload("paypal_two_place_pay_detail.json")
    )

    assert read.mode == "primary" and read.complete
    assert read.source_disclosed_comp is None
    text = sections_to_text(read.sections) or ""
    assert "$116,500.00 - $173,250.00" in text and "$100,500.00 - $149,600.00" in text


def test_a_tenant_page_with_no_bold_headings_is_one_section_not_drift():
    job = RawJob(company="boston-consulting-group", req_id="1", title="Consultant",
                 url="https://example.test/1", description_html="<p>Advise clients.</p>")
    drift = SchemaDriftDetector("eightfold:boston-consulting-group")

    structure_job_detail(job, drift, source="eightfold")

    assert [s.content for s in job.description_sections] == ["Advise clients."]
    assert not drift.alerts


def test_netflix_still_notes_a_range_outside_its_pay_paragraph_and_keeps_the_page():
    raw = (
        "<p><b>The Role</b></p><p>Lead the product.</p>"
        "<p>The US base salary range for this full-time position is $186,000.00 - $317,000.00.</p>"
    )
    job = RawJob(company="netflix", req_id="1", title="Director",
                 url="https://example.test/1", description_html=raw)
    drift = SchemaDriftDetector("eightfold:netflix")

    structure_job_detail(job, drift, source="eightfold")

    assert drift.alerts[-1]["reason"] == "Netflix compensation paragraph schema changed"
    assert job.description_complete
    assert not job.pay_looked


# --------------------------------------------------------------------------- #
# A read that holds the text but could not isolate the pay
# --------------------------------------------------------------------------- #

_ASHBY_FLAG_NO_SALARY = {
    "descriptionHtml": "<h3>About the Role</h3><p>Secure our systems.</p>",
    "shouldDisplayCompensationOnJobPostings": True,
}


@pytest.mark.parametrize("read", [
    lambda: AshbyDetailConnector().parse_payload(_ASHBY_FLAG_NO_SALARY),
    lambda: OpenAIDetailConnector().parse_payload(_ASHBY_FLAG_NO_SALARY),
    lambda: GreenhouseDetailConnector().parse_html(
        "<h2>About</h2><p>Lead.</p><div class=\"content-pay-transparency\"></div>"
    ),
    lambda: NetflixDetailConnector().parse_html(
        "<p><b>The Role</b></p><p>Lead.</p><p>Pay is $186,000.00 - $317,000.00.</p>"
    ),
], ids=["ashby", "openai", "greenhouse", "netflix"])
def test_a_pay_block_that_cannot_be_isolated_still_completes_the_text(read):
    result = read()
    assert result.mode == "failover" and result.reason
    assert result.sections and result.complete
    assert result.source_disclosed_comp is None


def test_a_pay_failover_with_no_text_is_never_complete():
    assert not pay_unread([], "no text").complete


def _held_job() -> Job:
    job = Job()
    job.id = 7
    job.description_text = "About the Role\nOld text."
    job.description_html = "<h2>About the Role</h2><p>Old text.</p>"
    job.description_sections = [{"key": "about_the_role", "title": "About the Role", "content": "Old text."}]
    job.description_fetched_at = None
    job.disclosed_source = "text"
    job.disclosed_base_min, job.disclosed_base_max = 150_000, 200_000
    return job


def test_a_held_posting_read_in_full_without_its_pay_takes_the_new_text_and_keeps_its_band():
    """The loop this closes: an incomplete read never stamps the fetch, so the
    posting is fetched again every scan and the employer's edit never lands."""
    raw = RawJob(company="notion", req_id="1", title="Staff Engineer", url="https://example.test/1")
    structure_job_detail(
        raw,
        SchemaDriftDetector("ashby:notion"),
        payload={**_ASHBY_FLAG_NO_SALARY, "descriptionHtml": "<h3>About the Role</h3><p>New text.</p>"},
        source="ashby",
    )
    job = _held_job()

    _apply_fields(job, EnrichedJob(raw=raw, level_band=LevelBand.STAFF,
                                   level_confidence=LevelConfidence.CONFIRMED,
                                   family="software_engineering", location_groups=[]))

    assert "New text." in (job.description_text or "")
    assert job.description_fetched_at is not None
    assert (job.disclosed_source, job.disclosed_base_min, job.disclosed_base_max) == ("text", 150_000, 200_000)


# --------------------------------------------------------------------------- #
# Carving a quote whose whitespace the scanner folded
# --------------------------------------------------------------------------- #

def test_a_quote_with_folded_line_breaks_is_carved_once_from_the_body():
    body = JobDescriptionSection(
        "closing", "Closing",
        "We never charge fees.\n\nThe base salary range is:\n\n$186,000.00 - $317,000.00 a year\n"
        "Bonuses may apply.\nEqual opportunity employer.",
    )
    quote = JobDescriptionSection(PAY_SECTION_KEY, "Compensation",
                                  "range is: $186,000.00 - $317,000.00 a year Bonuses")

    sections = promote_section([body], quote)

    assert [s.key for s in sections] == ["closing", PAY_SECTION_KEY]
    assert sections[0].content == "We never charge fees.\n\nEqual opportunity employer."
    assert sections[1].content == (
        "The base salary range is:\n\n$186,000.00 - $317,000.00 a year\nBonuses may apply."
    )


def test_a_quote_that_opens_on_the_last_sentence_s_full_stop_leaves_it_in_the_body():
    body = JobDescriptionSection("job_area", "Job Area", "Follow the law.\n\nPay range: $1,000 - $2,000")
    quote = JobDescriptionSection(PAY_SECTION_KEY, "Compensation", ". Pay range: $1,000 - $2,000")

    sections = promote_section([body], quote)

    assert sections[0].content == "Follow the law."
    assert sections[1].content == "Pay range: $1,000 - $2,000"


def test_a_quote_whose_words_differ_from_every_section_is_not_carved():
    body = JobDescriptionSection("closing", "Closing", "The base salary range is $1,000 - $2,000.")
    quote = JobDescriptionSection(PAY_SECTION_KEY, "Compensation", "base pay range is $1,000 - $2,000")

    sections = promote_section([body], quote)

    assert sections[0] == body
    assert sections[1] == quote
