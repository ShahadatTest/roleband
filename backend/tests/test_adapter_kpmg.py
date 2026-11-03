"""KPMG US's own careers search.

The contracts, each on what a seeker would get wrong if it broke:

* **A card is a job at a place.** Cards sharing a `jobId` become one job with
  every card's places; nothing is double-counted.
* **Complete means every card was seen.** Unique card ids equal to the stated
  count is complete; fewer (the pages shifted and a card repeated), or no
  stated count, invalidates.
* **The posting page's JSON-LD fills the body**, even with the raw control
  characters KPMG leaves inside its strings; the career track is not a level.

"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.connectors.listing.kpmg import declared_total, job_posting, parse_cards
from tracker.platform.ratelimit import RateLimiter

FIX = Path(__file__).parent / "fixtures/listings/kpmg"
PAGE = json.loads((FIX / "page1.json").read_text())["html"]
POSTING = (FIX / "posting_133741.html").read_text()
CARDS = re.findall(r'<div class="search--item.*?</a>\s*</div>', PAGE, re.S)


def _page(cards: list[str], count: int) -> str:
    return (
        f'<div class="search--showing"><span data-action="count">{count}</span> Results</div>'
        f'<div class="holder--postings">{"".join(cards)}</div>'
    )


def _adapter(pages: dict[int, str]):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/jobdetail/"):
            return httpx.Response(200, text=POSTING)
        return httpx.Response(200, text=pages.get(int(request.url.params["spage"]), "<html></html>"))

    adapter = build_adapter("kpmg", "kpmg")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0)
    return adapter


async def _jobs(adapter):
    return [job async for job in adapter.fetch()]


def _same_job_other_place(card: str) -> str:
    """The same posting on a second card: its own card id, another place."""
    card = re.sub(r'data-id="\d+"', 'data-id="1"', card, count=1)
    return re.sub(r"\|[^<]*</div>", "| Boston, MA</div>", card, count=1)


def test_the_fixture_is_a_whole_board_of_real_cards():
    assert len(CARDS) == 12 and declared_total(PAGE) == 12
    first = parse_cards(PAGE)[0]
    assert first.practice == "Audit and Assurance" and first.level == "Experienced"
    assert first.places[:2] == ["Dallas, TX", "Montvale, NJ"]


@pytest.mark.asyncio
async def test_cards_sharing_a_job_become_one_job_with_every_place():
    extra = _same_job_other_place(CARDS[0])
    adapter = _adapter({1: _page([*CARDS, extra], 13)})
    jobs = await _jobs(adapter)

    assert len(jobs) == 12, "13 cards, 12 postings"
    job = next(j for j in jobs if j.req_id == "133741")
    assert job.locations[-1] == "Boston, MA" and "Dallas, TX" in job.locations
    assert [p.label for p in job.source_facts.locations] == job.locations
    assert job.department == "Audit and Assurance"
    assert job.raw_level is None, "'Experienced' is a career track, not a rung"
    assert adapter.drift.listing_complete and adapter.drift.alerts == []


@pytest.mark.asyncio
async def test_a_card_repeating_across_pages_is_never_complete():
    """The pages shifted: page 2 repeats a page-1 card and one card is never seen."""
    adapter = _adapter({1: _page(CARDS[:6], 12), 2: _page([CARDS[5], *CARDS[6:11]], 12)})
    await _jobs(adapter)
    assert not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_a_page_that_states_no_count_invalidates():
    adapter = _adapter({1: f'<div class="holder--postings">{"".join(CARDS)}</div>'})
    jobs = await _jobs(adapter)
    assert len(jobs) == 12 and not adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_the_posting_page_json_ld_fills_the_body():
    assert job_posting(POSTING)["title"] == "AI Engineer- Senior Associate"
    adapter = _adapter({1: _page(CARDS, 12)})
    job = next(j for j in await _jobs(adapter) if j.req_id == "133741")

    await adapter.hydrate(job)

    assert job.description_complete and job.description_html.startswith("<p>")
    assert "&lt;" not in job.description_html, "HTML-escaped once in the JSON-LD; unescaped here"
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-09-01"
