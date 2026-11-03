"""Boards whose listing is a sitemap and whose postings are JSON-LD.

Families read this way for one reason: their search route is either
disallowed by robots or served by an endpoint robots disallows, while the
sitemap and the posting pages are allowed and complete. None publishes a total
anywhere else, so:

**The sitemap IS the declared inventory.** Every posting URL it names becomes
one of three things, and that is what completeness means here:

* a posting, built from the page's JSON-LD `JobPosting`;
* an `observe_present` key — the page would not read, but the id WAS listed, so
  closure must not close a posting that is live;
* a 404, which is a posting closed between the two requests: no loss at all.

**One request per posting per scan.** No family here publishes a per-posting
change stamp a reader could trust (`lastmod` is the sitemap's own build time),
so the whole board is re-read each scan. That cost is why `max_jobs` exists: a
board past it is cut by US, which is `truncated` (non-authoritative), never
drift.

**What is never read**, in one place because it is a property of this shape
rather than of one tenant:

* `workHours` — a tenant can put its **hiring manager's name** there, and a
  recruiter contact is never stored;
* `employmentType` that is not schema.org's own vocabulary — a tenant's grade
  ("Established") is not an employment type;
* `streetAddress` — a place is locality, region and country.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from tracker.connectors.extract.payload import job_posting, text_of
from tracker.connectors.extract.sitemap import SitemapSource
from tracker.connectors.listing.base import BaseAdapter
from tracker.connectors.sdk import FetchRequest
from tracker.platform.safe_fetch import BlockedDestination
from tracker.platform.sitemaps import parse_sitemap, walk_sitemaps
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import (
    AccessSurface,
    CompensationFacts,
    EmploymentType,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
    WorkplaceType,
)

#: schema.org's own vocabulary. A tenant's grade ("Established") is not one.
EMPLOYMENT = {
    "FULL_TIME": EmploymentType.FULL_TIME,
    "PART_TIME": EmploymentType.PART_TIME,
    "CONTRACTOR": EmploymentType.CONTRACT,
    "TEMPORARY": EmploymentType.TEMPORARY,
    "INTERN": EmploymentType.INTERN,
    "INTERNSHIP": EmploymentType.INTERN,
}
_WORKPLACE = {"telecommute": WorkplaceType.REMOTE, "remote": WorkplaceType.REMOTE}


def sitemap_locs(xml: str) -> list[str]:
    """Every `<loc>` in a sitemap, in document order, deduplicated."""
    document = parse_sitemap(xml)
    return list(document.urls) if document is not None else []


def places_of(posting: dict) -> list[SourceLocation]:
    """Locality, region and country — never `streetAddress`."""
    raw = posting.get("jobLocation")
    places: list[SourceLocation] = []
    for entry in (raw if isinstance(raw, list) else [raw]):
        address = entry.get("address") if isinstance(entry, dict) else None
        if not isinstance(address, dict):
            continue
        country = text_of(address.get("addressCountry"))
        parts = [text_of(address.get("addressLocality")), text_of(address.get("addressRegion")), country]
        label = clean_location(", ".join(p for p in parts if p))
        if label and all(label != p.label for p in places):
            places.append(SourceLocation(label=label, country=country, is_primary=not places))
    return places


def employment_of(posting: dict) -> tuple[str | None, EmploymentType]:
    """(raw, normalized) — raw only when schema.org defines the word, so a
    tenant's own grade never lands in an employment-type field."""
    value = posting.get("employmentType")
    raw = text_of(value[0] if isinstance(value, list) and value else value)
    normalized = EMPLOYMENT.get((raw or "").upper().replace("-", "_").replace(" ", "_"), EmploymentType.UNKNOWN)
    return (raw if normalized is not EmploymentType.UNKNOWN else None), normalized


class SitemapBoardAdapter(BaseAdapter):
    """Sitemap as the listing, JSON-LD posting pages as the postings."""

    public_only = True

    @property
    def sitemap_source(self) -> SitemapSource:
        assert self.board_probe is not None and self.board_probe.sitemap is not None
        return self.board_probe.sitemap(self.tenant_identity)

    def validate_destination(self, url: str) -> None:
        self.sitemap_source.validate(url)

    #: Our own ceiling on postings fetched in one scan; past it the run is ours
    #: to call `truncated`, never the source's to be blamed for.
    max_jobs = 1500
    #: Sitemap index children to follow, if a tenant splits its sitemap.
    max_sitemaps = 20
    access_surface = AccessSurface.HTML

    @property
    @abstractmethod
    def sitemap_url(self) -> str:
        """The board's sitemap, for the tenant this adapter was built for."""

    @abstractmethod
    def posting_id(self, url: str) -> str | None:
        """The posting id in a URL, or None when the URL is not a posting."""

    @property
    def tenant_identity(self) -> str:
        return self.board_token or self.company

    async def fetch(self) -> AsyncIterator[RawJob]:
        # Policy before configuration: a refused company is refused as such.
        self.access.require()
        urls = await self._board()
        if urls is None:
            return
        if len(urls) > self.max_jobs:
            self.truncated = True
            urls = urls[: self.max_jobs]
        # After the cut, so ORDER is all it changes: the same pages are read.
        urls = self.likely_first(urls)

        built = 0
        for url in urls:
            req_id = self.posting_id(url)
            if req_id is None:
                continue
            try:
                resp = await self.context.fetch(FetchRequest(url=url, source_key=self.company))
            except BlockedDestination as exc:
                self.drift.invalidate_listing("posting destination rejected", reason=str(exc))
                self.drift.observe_present(req_id, "posting destination rejected")
                continue
            if resp.status == 404:
                # Closed between the sitemap and this request: the board moved
                # on, nothing was lost.
                self.drift.note("posting gone since the sitemap", req=req_id)
                continue
            posting = job_posting(resp.text()) if resp.status == 200 else None
            title = text_of(posting.get("title")) if posting else None
            if not posting or not title:
                # The id was listed, so closure can still reconcile it; only
                # this run's copy is missing.
                self.drift.observe_present(req_id, "posting page unreadable", status=resp.status)
                continue
            built += 1
            yield self.build_job(posting, req_id, url, title)

        # A fully read, valid sitemap naming no posting is evidence of an empty
        # board; one naming postings none of which could be read is not.
        if not urls:
            # A sitemap whose entries are all someone else's pages is not
            # empty; the walk recorded that as a failure already.
            if not self.drift.listing_invalidated:
                self.drift.board_empty("a valid sitemap named no postings")
        else:
            self.drift.require(bool(built), "empty job list")

    def url_hint(self, url: str) -> RawJob | None:
        """A provisional posting read from the URL alone, or None.

        For ORDER only (`likely_first`): a family whose posting URLs name the
        title overrides it. Never persisted, never a posting's facts.
        """
        return None

    def likely_first(self, urls: list[str]) -> list[str]:
        """The URLs whose own words pass the user's role gate, then the rest.

        This shape reads one page per posting, so a board's time is its size
        while a user needs a thin slice of it.
        Reading the likely ones first puts them on the Board in the first
        minute; every URL is still read, so the listing, and closure, are
        exactly as complete. Without a gate (smoke, tests) or a
        hint, document order stands.
        """
        if self.place_gate is None:
            return urls
        likely: list[str] = []
        rest: list[str] = []
        for url in urls:
            hint = self.url_hint(url)
            (likely if hint is not None and self.place_wanted(hint) else rest).append(url)
        return likely + rest

    async def _board(self) -> list[str] | None:
        """Every posting URL the sitemap names, following a sitemap index."""
        async def read(url: str) -> str | None:
            try:
                response = await self.context.fetch(FetchRequest(url=url, source_key=self.company))
            except BlockedDestination:
                return None
            return response.text() if response.status == 200 else None

        inventory = await walk_sitemaps(
            self.sitemap_url, read, accepts=self.sitemap_source.accepts,
            is_posting=lambda url: self.posting_id(url) is not None,
            max_documents=self.max_sitemaps + 1, max_postings=self.max_jobs,
        )
        self.truncated |= inventory.truncated
        for failure in inventory.failures:
            self.drift.invalidate_listing(failure)
        return list(inventory.urls) if inventory.recognized else None

    def build_job(self, posting: dict, req_id: str, url: str, title: str) -> RawJob:
        places = places_of(posting)
        raw_employment, normalized = employment_of(posting)
        body = text_of(posting.get("description"))
        remote = str(posting.get("jobLocationType") or "").strip().lower()
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=[p.label for p in places],
            department=text_of(posting.get("occupationalCategory")),
            description_html=body,
            description_complete=bool(body),
            workplace_type=_WORKPLACE.get(remote, WorkplaceType.UNKNOWN),
            posted_at=parse_datetime(posting.get("datePosted")),
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=self.access_surface,
                tenant_identity=self.tenant_identity,
                posting_id=req_id,
                employment_type_raw=raw_employment,
                employment_type_normalized=normalized,
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )
