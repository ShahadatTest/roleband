"""HTML parsing preserves the posting a reader sees, including embedded markup."""

from __future__ import annotations

import json

import pytest

from tests.contracts.conftest import MODE_NORMAL, build_harness, run_fetch
from tracker.connectors.extract import EXTRACTOR_VERSION, PARSER_ID, visible_text
from tracker.connectors.extract.payload import job_posting


@pytest.mark.asyncio
@pytest.mark.parametrize("name,req_id,title,locations,url", [
    ("avature", "214164", "Director, PE Shared Services", ["Hyderabad, India"],
     "https://jobs.ea.com/en_US/careers/JobDetail/Director-PE-Shared-Services/214164"),
    ("google", "109876543210987654", "Senior Staff Software Engineer, Spanner",
     ["Mountain View, CA, USA", "Sunnyvale, CA, USA", "Singapore"],
     "https://www.google.com/about/careers/applications/jobs/results/109876543210987654-senior-staff-software-engineer-spanner"),
    ("kpmg", "133741", "AI Engineer- Senior Associate",
     ["Dallas, TX", "Montvale, NJ", "New York, NY", "Orlando, FL", "Philadelphia, PA", "Washington, DC"],
     "https://www.kpmguscareers.com/jobdetail/?jobId=133741"),
    ("smartrecruiters", "744000148443769", "bonding Firmenkontaktmesse Aachen", ["Aachen, Germany"],
     "https://jobs.smartrecruiters.com/RolandBerger/744000148443769-bonding-firmenkontaktmesse-aachen"),
    ("successfactors", "1431366233", "Senior Consultant - Financial Due Diligence (M&A)",
     ["Prague 1 - Nove Mesto, Czechia"],
     "https://careers.ey.com/ey/job/Prague-1-Nove-Mesto-Senior-Consultant-Financial-Due-Diligence-%28M&A%29-110-00/1431366233/"),
    ("tiktok", "7686714309884578101", "Workplace Manager",
     ["San Jose, California, United States of America"], "https://lifeattiktok.com/search/7686714309884578101"),
])
async def test_captured_html_retains_identity_title_places_and_destination(name, req_id, title, locations, url):
    jobs = await run_fetch(build_harness(name, MODE_NORMAL))
    posting = next(job for job in jobs if job.req_id == req_id)
    assert (posting.title, posting.locations, posting.url) == (title, locations, url)


def test_json_ld_preserves_escaped_closing_tags_inside_a_description():
    description = "<h2>Responsibilities</h2><p>Build systems.</p>"
    payload = json.dumps({"@type": "JobPosting", "description": description}).replace("</", "<\\/")
    page = f'<html><script type="application/ld+json">{payload}</script></html>'
    assert job_posting(page)["description"] == description
    assert visible_text(description) == "Responsibilities Build systems."


def test_html5_table_repair_keeps_visible_content_and_removes_hidden_content():
    markup = '<table><p>Staff Engineer</p><tr><td>Build systems<td hidden>POISON</table>'
    assert visible_text(markup) == "Staff Engineer Build systems"


def test_validation_fingerprint_names_the_parser_engine():
    assert PARSER_ID.startswith("selectolax.lexbor ")
    assert EXTRACTOR_VERSION >= 2
