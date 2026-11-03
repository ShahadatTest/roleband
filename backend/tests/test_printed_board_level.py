"""A rung the employer prints in a public board field.

Five Greenhouse employers publish their own level in a custom field
(`metadata`): Waymo "Job Level" ["6"], Reddit "Management Level" "IC4",
Dropbox "Dropboxer Level", SambaNova "Level", SharkNinja "Level". The listing
carries it, so the posting states its level before any page is read. Each
value is banded only where postings whose title states the band agreed on it
(2+ anchors, 80%+); a value they did not settle is
left out and the title decides.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.greenhouse import printed_rung
from tracker.enrich.level_mapper import full_read_can_state, read_level
from tracker.levels.ladder import printed_field
from tracker.schema import LevelBand, LevelBasis, RawJob


def _meta(name: str, value, value_type: str = "single_select") -> dict:
    # The shape the board serves.
    return {"id": 4012, "name": name, "value": value, "value_type": value_type}


def _job(n: int, title: str, metadata: list[dict]) -> dict:
    return {
        "id": n, "title": title, "location": {"name": "Mountain View, CA"}, "offices": [],
        "absolute_url": f"https://boards.greenhouse.io/x/jobs/{n}",
        "first_published": "2026-09-01T00:00:00Z", "content": "<p>x</p>", "metadata": metadata,
    }


async def _fetch(company: str, jobs: list[dict]) -> dict[str, RawJob]:
    adapter = build_adapter(company, "greenhouse", board_token=company)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"jobs": jobs, "meta": {"total": len(jobs)}})
    ))
    adapter._limiter = RateLimiter(0.0)
    return {job.req_id: job async for job in adapter.fetch()}


@pytest.mark.asyncio
async def test_the_listing_carries_the_rung_the_employer_prints():
    jobs = await _fetch("waymo", [
        _job(1, "Strategic Sourcing Manager - Contract Manufacturing", [
            _meta("Employment Type", "Regular"), _meta("Job Level", ["6"], "multi_select"),
        ]),
        _job(2, "Software Engineer, Planner", [_meta("Job Level", ["6", "5"], "multi_select")]),
        _job(3, "Software Engineer, Perception", [_meta("Job Level", None, "multi_select")]),
        _job(4, "Software Engineer, Simulation", []),
    ])
    assert jobs["1"].raw_level == "6"
    assert jobs["2"].raw_level == "5/6"  # a dual rung, ascending: the lower one bands it
    assert jobs["3"].raw_level is None
    assert jobs["4"].raw_level is None


@pytest.mark.asyncio
async def test_a_field_nobody_declared_is_never_read_as_a_level():
    # SharkNinja's "Level" is declared; the same name at another board is not
    # evidence: a custom field means what its employer made it mean.
    jobs = await _fetch("acme", [_job(1, "Manager, Analytics", [_meta("Level", "Director")])])
    assert printed_field("acme") is None
    assert jobs["1"].raw_level is None


@pytest.mark.parametrize(("company", "title", "printed", "band", "basis"), [
    # The employer's rung outranks a title that names none, or a different one.
    ("waymo", "Strategic Sourcing Manager - Contract Manufacturing", "6", LevelBand.STAFF, LevelBasis.STATED),
    ("waymo", "Software Engineer, Planner", "5/6", LevelBand.SENIOR, LevelBasis.STATED),
    ("waymo", "Technical Program Manager, Hardware", "7", LevelBand.PRINCIPAL, LevelBasis.STATED),
    ("reddit", "Software Engineer, Ads Measurement", "IC4", LevelBand.SENIOR, LevelBasis.STATED),
    ("reddit", "Engineering Manager, Safety", "D1", LevelBand.DIRECTOR_PLUS, LevelBasis.STATED),
    ("dropbox", "Engineering Manager, Core Sync", "MGR7", LevelBand.DIRECTOR_PLUS, LevelBasis.STATED),
    ("sambanova", "Senior Analyst Relations Manager", "IC4", LevelBand.PRINCIPAL, LevelBasis.STATED),
    ("sharkninja", "Brand Manager, Haircare", "Senior", LevelBand.SENIOR, LevelBasis.STATED),
    # A director title is never pulled down by a lower printed rung.
    ("waymo", "Head of Logistics", "7", LevelBand.DIRECTOR_PLUS, LevelBasis.GENERIC),
    # A value the anchors did not settle is not read: the title decides.
    ("reddit", "Senior Client Account Manager", "IC5", LevelBand.SENIOR, LevelBasis.GENERIC),
    ("waymo", "Software Engineer, Simulation", "4", LevelBand.MID, LevelBasis.NONE),
    ("sharkninja", "Manager, Media Scale Markets", "Lead", LevelBand.MID, LevelBasis.NONE),
])
def test_a_printed_board_rung_is_read_as_the_employer_states_it(company, title, printed, band, basis):
    reading = read_level(RawJob(company=company, req_id="x", title=title, url="", raw_level=printed), None)
    assert (reading.band, reading.basis) == (band, basis)


def test_a_rung_printed_in_a_listing_field_never_makes_the_page_worth_reading():
    # The rung is on the listing; the page does not repeat it. Microsoft's is
    # in the posting text, so its page can state it (control). No family, so
    # no measured range enters the question.
    assert not full_read_can_state(RawJob(company="waymo", req_id="x", title="Software Engineer", url=""), None)
    assert full_read_can_state(RawJob(company="microsoft", req_id="x", title="Software Engineer", url=""), None)


def test_printed_rung_ignores_an_empty_or_undeclared_field():
    assert printed_rung({"metadata": [_meta("Job Level", [])]}, "Job Level") is None
    assert printed_rung({"metadata": [_meta("Job Level", ["6"])]}, None) is None
    assert printed_rung({}, "Job Level") is None


def test_every_company_printing_a_rung_in_its_text_has_a_reader():
    """Two registries say who prints a rung: the atlas (`prints_rungs_in_text`,
    which codes band) and the text readers (`stated_level`). A company the atlas
    says prints in its text, with no reader, would have its descriptions read
    for a level that is never found."""
    from tracker.levels.atlas import PRINTED, read_rows
    from tracker.levels.ladder import prints_rungs_in_text
    from tracker.taxonomy.stated_level import PRINTING_COMPANIES

    printing = {row["company"] for row in read_rows(PRINTED) if prints_rungs_in_text(row["company"])}
    assert printing, "the atlas names at least one company printing in its text"
    assert printing <= PRINTING_COMPANIES
