"""A parser fix reaches the postings already stored, and only the bands our
text pass wrote.

The text pass re-reads a posting when its text changes or the extractor's
version moves. A pass that cannot tell a band it wrote from one a connector
read out of a structured field clears both when the text states no band. Rows below have unchanged text
and an old stamp; the repair is the normal pass, bounded and resumable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.factories import make_job
from tracker.connectors.listing.greenhouse import pay_tiers
from tracker.db.models import Job
from tracker.intelligence_runtime.disclosed_comp import extract_disclosed_comp
from tracker.pay_disclosure import PAY_PARSER_VERSION
from tracker.schema import (
    AccessSurface,
    ApplicationFormFacts,
    PostingPage,
    RetrievalState,
    SourceJobFacts,
)
from tracker.workflows.posting_pages import apply_page, page_band

OLD = "disclosed_comp/v5"
THEN = datetime(2026, 9, 1, tzinfo=UTC)
NO_PAY = "Lead programs across twelve countries. Great benefits."


def _row(key: str, desc: str, *, band: tuple[int, int] | None = None, source: str | None = None,
         snippet: str | None = "stored snippet", **over) -> Job:
    fields = dict(
        description_text=desc, description_sections=[], content_changed_at=THEN - timedelta(days=1),
        structured_at=THEN, structured_prompt_version=OLD, disclosed_source=source,
    )
    if band is not None:
        fields.update(
            disclosed_base_min=band[0], disclosed_base_max=band[1], disclosed_currency="USD",
            disclosed_pay_basis="unclear", disclosed_pay_period="year", disclosed_snippet=snippet,
            disclosed_confidence="high",
        )
    fields.update(over)
    return make_job(key, **fields)


def _page_row() -> Job:
    """A Greenhouse posting whose band only its posting page states."""
    facts = SourceJobFacts(provider="greenhouse", access_surface=AccessSurface.PUBLIC_API,
                           tenant_identity="figma", posting_id="6150563004").as_dict()
    job = _row("page", NO_PAY, source_facts=facts)
    fixture = Path(__file__).parent / "fixtures" / "greenhouse_posting" / "figma.json"
    ranges = json.loads(fixture.read_text())["pay_input_ranges"]
    apply_page(job, PostingPage(ApplicationFormFacts(state=RetrievalState.PRESENT, observed_at=THEN),
                                pay_tiers(ranges, THEN)))
    return job


@pytest_asyncio.fixture
async def stored(db_session):
    rows = {
        # An older text pass stored a sign-on bonus as a base band (now rejected).
        "bonus": _row("bonus", "Sign-on bonus of $50,000 - $100,000 for eligible hires.",
                      band=(50_000, 100_000), source="text"),
        # An older text pass found nothing in a code-prefixed salary (now read).
        "missed": _row("missed", "Base: SEK 900000 - 1200000 per year."),
        # A connector read this band from a structured field; the text states none.
        "connector": _row("connector", NO_PAY, band=(180_000, 240_000), source="connector"),
        # The text states the band it already holds.
        "same": _row("same", "Salary range: $150,000 - $200,000 per year.",
                     band=(150_000, 200_000), source="text",
                     snippet="Salary range: $150,000 - $200,000 per year."),
        "page": _page_row(),
        # Our text pass read this band; the posting's text has since gone
        # missing. No text is no evidence of no band.
        "no-text": _row("no-text", None, band=(224_000, 356_500), source="text",
                        content_changed_at=THEN + timedelta(hours=1)),
    }
    db_session.add_all(rows.values())
    await db_session.commit()
    return rows


async def _bands(db_session) -> dict[str, tuple]:
    rows = (await db_session.scalars(select(Job).execution_options(populate_existing=True))).all()
    return {
        job.req_id: (job.disclosed_base_min, job.disclosed_base_max, job.disclosed_currency,
                     job.disclosed_source, job.structured_prompt_version)
        for job in rows
    }


@pytest.mark.asyncio
async def test_the_normal_pass_repairs_what_the_text_pass_wrote_and_nothing_else(db_session, stored):
    ids = [job.id for job in stored.values()]

    summary = await extract_disclosed_comp(db_session, ids, cap=None, page_band=page_band)

    bands = await _bands(db_session)
    assert bands["bonus"] == (None, None, None, None, PAY_PARSER_VERSION)
    assert bands["missed"] == (900_000, 1_200_000, "SEK", "text", PAY_PARSER_VERSION)
    assert bands["same"] == (150_000, 200_000, "USD", "text", PAY_PARSER_VERSION)
    assert bands["page"][:4] == (235_000, 317_000, "USD", "page"), "the page band is the fallback"
    assert bands["no-text"] == (224_000, 356_500, "USD", "text", PAY_PARSER_VERSION)
    # Never handed to the text pass: not stale, not counted against the cap.
    assert bands["connector"] == (180_000, 240_000, "USD", "connector", OLD)
    assert summary["processed"] == 5

    again = await extract_disclosed_comp(db_session, ids, cap=None, page_band=page_band)
    assert again["processed"] == 0, "a second pass writes nothing"


@pytest.mark.asyncio
async def test_a_repair_is_bounded_per_run_and_resumes_where_it_stopped(db_session, stored):
    ids = [job.id for job in stored.values()]

    first = await extract_disclosed_comp(db_session, ids, cap=2, page_band=page_band)
    second = await extract_disclosed_comp(db_session, ids, cap=2, page_band=page_band)
    third = await extract_disclosed_comp(db_session, ids, cap=2, page_band=page_band)

    fourth = await extract_disclosed_comp(db_session, ids, cap=2, page_band=page_band)
    assert [first["processed"], second["processed"], third["processed"], fourth["processed"]] == [2, 2, 1, 0]
    stamps = {req: stamp for req, (*_band, stamp) in (await _bands(db_session)).items()}
    assert stamps == {
        "bonus": PAY_PARSER_VERSION, "missed": PAY_PARSER_VERSION, "same": PAY_PARSER_VERSION,
        "page": PAY_PARSER_VERSION, "no-text": PAY_PARSER_VERSION, "connector": OLD,
    }


@pytest.mark.asyncio
async def test_the_pass_stores_the_band_for_the_postings_own_place(db_session):
    """A posting stating Microsoft's two bands stores the one for
    its first place. Stored by an older parser as the US band; the version
    bump re-reads it. Redmond keeps the US band: no band names it."""
    text = (
        "Software Engineering M5 - The typical base pay range for this role across the U.S. is "
        "USD $142,800 - $274,800 per year. There is a different range applicable to specific work "
        "locations, within the San Francisco Bay area and New York City metropolitan area, and the "
        "base pay range for this role in those locations is USD $188,000 - $304,200 per year."
    )
    rows = [
        _row("bay", text, band=(142_800, 274_800), source="text", company="microsoft",
             locations=["Mountain View, CA, US", "United States, California, Mountain View"]),
        _row("redmond", text, band=(142_800, 274_800), source="text", company="microsoft",
             locations=["Redmond, WA, US", "Mountain View, CA, US"]),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    await extract_disclosed_comp(db_session, [row.id for row in rows], cap=None, page_band=page_band)

    bands = await _bands(db_session)
    assert bands["bay"][:3] == (188_000, 304_200, "USD")
    assert bands["redmond"][:3] == (142_800, 274_800, "USD")
