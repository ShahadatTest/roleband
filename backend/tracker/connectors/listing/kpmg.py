"""KPMG US — its own careers search.

    GET https://www.kpmguscareers.com/job-search/?spage=N&order=posted
    GET https://www.kpmguscareers.com/jobdetail/?jobId={id}

KPMG US runs its own WordPress search, rendered server-side, 12 result cards a
page with the total stated (`<span data-action="count">N</span> Results`).

**A card is a job at a place, not a job.** Each card carries the posting's
`jobId` and its own `data-id`; the same `jobId` can appear on several cards,
each card id unique and stable across sort orders. So
completeness compares unique CARD ids with the stated count (fewer
means the pages shifted under us), and jobs merge their cards' places.

**Detail.** Each posting page carries a schema.org `JobPosting` in JSON-LD
(raw control characters inside strings, so parsed non-strictly): description
(HTML-escaped), `datePosted` ("Sep 1, 2026"), `hiringOrganization`. Pay is not
on the page ("the ranges displayed below or via the URL below"), so none is
read.

`robots.txt` disallows only a click-tracking script
(`.../google/record-click.php`); neither route is restricted.
"""

from __future__ import annotations

import html
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from tracker.connectors.extract.payload import job_posting
from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.connectors.sdk import Capabilities, FetchRequest
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import (
    AccessSurface,
    CompensationFacts,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
)

BASE = "https://www.kpmguscareers.com"
SEARCH_URL = f"{BASE}/job-search/"
_TENANTS = TenantMap({})
_MAX_PAGES = 120  # 12 cards a page, with headroom over the board
_COUNT = re.compile(r'data-action="count">\s*([\d,]+)\s*<')
_JOB_ID = re.compile(r"jobId=(\d+)")


def declared_total(page: str) -> int | None:
    match = _COUNT.search(page)
    return int(match.group(1).replace(",", "")) if match else None


@dataclass
class Card:
    card_id: str
    job_id: str
    title: str
    practice: str | None
    level: str | None
    places: list[str] = field(default_factory=list)


def parse_cards(page: str) -> list[Card]:
    cards: list[Card] = []
    for link in HTMLParser(page).css('a[href*="/jobdetail/?jobId="]'):
        job = _JOB_ID.search(link.attributes.get("href") or "")
        card_id = (link.attributes.get("data-id") or "").strip()
        title_node = link.css_first(".h4") or link.css_first(".h5")
        title = title_node.text(strip=True) if title_node is not None else ""
        if not job or not card_id or not title:
            continue
        level = link.css_first(".bg-search")
        practice = link.css_first(".text-blue")
        places: list[str] = []
        detail = link.css_first(".list-view .text-xs")
        if detail is not None and "|" in detail.text():
            for raw in detail.text().split("|", 1)[1].split(";"):
                label = clean_location(raw.strip())
                if label and label not in places:
                    places.append(label)
        cards.append(Card(
            card_id=card_id,
            job_id=job.group(1),
            title=title,
            practice=practice.text(strip=True) or None if practice is not None else None,
            level=level.text(strip=True) or None if level is not None else None,
            places=places,
        ))
    return cards


class KpmgAdapter(BaseAdapter):
    name = "kpmg"
    posted_date = "published"  # the detail's `datePosted`
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: The search states its result count.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url=SEARCH_URL,
        tenants=_TENANTS,
        # One company, one fixed route; the stated count sizes the board.
        tenant_url=lambda _token: SEARCH_URL,
        read_count=declared_total,
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    async def fetch(self) -> AsyncIterator[RawJob]:
        declared: int | None = None
        card_ids: set[str] = set()
        jobs: dict[str, RawJob] = {}
        self._completed_rows = jobs.values

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[Card]:
            nonlocal declared
            resp = await self.context.fetch(FetchRequest(
                url=SEARCH_URL, query={"spage": index + 1, "order": "posted"}, source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("search page failed", page=index + 1, status=resp.status)
                stop()
                return []
            text = resp.text()
            if declared is None:
                declared = declared_total(text)
            cards = parse_cards(text)
            if declared is not None and len(card_ids) + len(cards) >= declared:
                stop()
            return cards

        async for card in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key="search", declared_total=lambda: declared,
        ):
            card_ids.add(card.card_id)
            known = jobs.get(card.job_id)
            if known is None:
                jobs[card.job_id] = self._job(card)
                continue
            for label in card.places:
                if label not in known.locations:
                    known.locations.append(label)
                    if known.source_facts is not None:
                        known.source_facts = replace(
                            known.source_facts,
                            locations=[*known.source_facts.locations, SourceLocation(label=label)],
                        )

        self.drift.require(bool(jobs), "empty job list")
        self.close_listing(
            declared=declared, unique=len(card_ids), field="the search's result count"
        )
        for key, job in list(jobs.items()):
            yield job
            jobs.pop(key)

    def _job(self, card: Card) -> RawJob:
        places = [SourceLocation(label=label, is_primary=i == 0) for i, label in enumerate(card.places)]
        return RawJob(
            company=self.company,
            req_id=card.job_id,
            title=card.title,
            url=f"{BASE}/jobdetail/?jobId={card.job_id}",
            locations=list(card.places),
            department=card.practice,
            # `card.level` is the career TRACK ("Experienced", "Contractor"),
            # not a ladder rung; the title carries the rung.
            description_complete=False,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.HTML,
                tenant_identity="kpmguscareers.com",
                posting_id=card.job_id,
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page failed", req=job.req_id, status=resp.status)
            return
        posting = job_posting(resp.text())
        if posting is None:
            self.drift.note("posting page carried no JobPosting", req=job.req_id)
            return
        description = posting.get("description")
        body = html.unescape(description) if isinstance(description, str) and description.strip() else None
        job.description_html = body
        job.description_complete = bool(body)
        posted = parse_datetime(posting.get("datePosted"))
        if posted is not None:
            job.posted_at = posted
            if job.source_facts is not None:
                job.source_facts = replace(job.source_facts, first_published_at=posted)
