"""SAP SuccessFactors career sites: multi-tenant.

    GET https://{host}/{site}/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=N
    GET https://{host}/{site}/job/{slug}/{id}/

The career-site builder SAP ships with SuccessFactors Recruiting, rendered
server-side from one template. Token `host|site`; EY: `careers.ey.com|ey`.
Pacing and the breaker are per tenant (each tenant is its own host).

**Listing.** A results table, 25 rows a page (the tenant's size; the walk
advances by the rows each page returned), sorted newest first, with the total
stated in the pagination label ("Results 1 - 25 of 8551"). A row holds the
title, the posting link (whose last path segment is the id) and ONE place,
followed by "+N more..." when the posting has others.

**A place is written `City, [Region,] CC, Postcode`** ("Pune, MH, IN, 411006",
"SG, 048583", "PY"). The two-letter codes cannot be matched as they stand:
IN (India), IL (Israel), CA (Canada), AR (Argentina) are also US state codes,
and region codes like HR (Haryana) are also country codes (Croatia). So the
country is read by POSITION (the last field once postcodes are dropped) and
written out by name; a region code is kept only in the US, where it is a
state. "Pune, MH, IN, 411006" -> "Pune, India"; "New York, NY, US, 10001" ->
"New York, NY, United States".

**Detail.** schema.org microdata: every place as a `PostalAddress`
(`addressLocality`, `addressRegion`, `addressCountry`; a "+80 more" posting
lists 81), `datePosted`, `hiringOrganization`, and the description. A row with
"+N more" is placed from its page during the listing when the scope's role
gate admits it (`place_wanted`), reusing places read within the
refresh window (`known_places`): its first place alone would hide
it from anyone tracking the others.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap, set_places
from tracker.connectors.sdk import Capabilities, FetchRequest
from tracker.platform.util import clean_location
from tracker.schema import (
    AccessSurface,
    CompensationFacts,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
)
from tracker.taxonomy.countries import COUNTRIES
from tracker.taxonomy.locations import US_STATE_CODES

_TENANTS = TenantMap({})
#: Seed and hard ceiling: 15,000 postings at 25 a page.
_MAX_PAGES = 600
_TOTAL = re.compile(r"of\s*([\d][\d,.]*)", re.IGNORECASE)
_POSTING_ID = re.compile(r"/job/[^?#]*?/(\d+)/?(?:[?#]|$)")
_MORE = re.compile(r"\+\s*\d+\s*more", re.IGNORECASE)
_CODE = re.compile(r"^[A-Z]{1,3}$")
_COUNTRY_BY_CODE = {country.alpha2.upper(): country.display for country in COUNTRIES}


@dataclass(frozen=True)
class SfTenant:
    host: str
    site: str

    def search_url(self) -> str:
        return f"https://{self.host}/{self.site}/search/"

    def probe_url(self) -> str:
        return self.search_url() + "?q=&sortColumn=referencedate&sortDirection=desc&startrow=0"


def parse_tenant(token: str) -> SfTenant:
    host, _, site = token.partition("|")
    if not host.strip() or not site.strip() or "|" in site:
        raise ValueError(f"successfactors board_token must be 'host|site', got {token!r}")
    return SfTenant(host.strip(), site.strip().strip("/"))


def declared_total(page: str) -> int | None:
    """The pagination label's total, "Results 1 - 25 of 8551"."""
    label = HTMLParser(page).css_first(".paginationLabel")
    match = _TOTAL.search(" ".join(label.text().split())) if label is not None else None
    if match is None:
        return None
    digits = re.sub(r"[,.]", "", match.group(1))
    return int(digits) if digits else None


def place_label(locality: str | None, region: str | None, country: str | None) -> str | None:
    """One place, the country written out by name and a region code kept only
    in the US. Returns None when nothing names a place."""
    code = (country or "").strip().upper()
    name = _COUNTRY_BY_CODE.get(code) if _CODE.match(code) else (country or "").strip() or None
    city = (locality or "").strip()
    region = (region or "").strip()
    keep_region = region and (code == "US" or not _CODE.match(region))
    parts = [part for part in (city, region if keep_region else "", name or "") if part]
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return clean_location(", ".join(deduped)) if deduped else None


def row_place(text: str) -> str | None:
    """A listing row's place, "City, [Region,] CC, Postcode", as a label."""
    fields = [f.strip() for f in text.split(",") if f.strip()]
    postcode = False
    while fields and any(ch.isdigit() for ch in fields[-1]):
        fields.pop()  # postcodes ("110 00", "T2P 1M4", "AZ1010")
        postcode = True
    if not fields:
        return None
    # The last field is the country by its POSITION: after a postcode, or
    # third after city and region. A bare "City, XX" with a code that is also
    # a US state ("Boston, MA", "Indianapolis, IN") has no position to read
    # and is kept as written, so the taxonomy places it, never Morocco or India.
    code = fields[-1]
    positional = postcode or len(fields) >= 3
    country = (
        code if _CODE.match(code) and code in _COUNTRY_BY_CODE
        and (positional or code not in US_STATE_CODES) else None
    )
    if country is None:
        return clean_location(", ".join(fields))
    rest = fields[:-1]
    city = rest[0] if rest else None
    region = ", ".join(rest[1:]) if len(rest) > 1 else None
    return place_label(city, region, country)


@dataclass(frozen=True)
class Row:
    posting_id: str
    title: str
    url: str
    place: str | None
    more: bool


def parse_rows(page: str, tenant: SfTenant) -> list[Row]:
    rows: list[Row] = []
    for tr in HTMLParser(page).css("tr.data-row"):
        link = tr.css_first("a.jobTitle-link")
        href = link.attributes.get("href") if link is not None else None
        match = _POSTING_ID.search(href or "")
        title = link.text(strip=True) if link is not None else ""
        if not match or not title:
            continue
        cell = tr.css_first(".colLocation")
        text = " ".join(cell.text().split()) if cell is not None else ""
        more = bool(_MORE.search(text))
        first = _MORE.split(text)[0].strip(" |") if text else ""
        rows.append(Row(
            posting_id=match.group(1),
            title=title,
            url=f"https://{tenant.host}{href}" if (href or "").startswith("/") else (href or ""),
            place=row_place(first) if first else None,
            more=more,
        ))
    return rows


@dataclass(frozen=True)
class Detail:
    description_html: str | None
    places: list[str]
    posted_at: datetime | None
    employer: str | None


def _content(node: Node, prop: str) -> str | None:
    found = node.css_first(f'[itemprop="{prop}"]')
    if found is None:
        return None
    value = found.attributes.get("content")
    return (value if value is not None else found.text(strip=True)) or None


def parse_detail(page: str) -> Detail:
    tree = HTMLParser(page)
    places: list[str] = []
    for address in tree.css('[itemprop="jobLocation"] [itemprop="address"]'):
        label = place_label(
            _content(address, "addressLocality"), _content(address, "addressRegion"),
            _content(address, "addressCountry"),
        )
        if label and label not in places:
            places.append(label)
    body = tree.css_first('[itemprop="description"]')
    posted = None
    raw = _content(tree.root, "datePosted") if tree.root is not None else None
    if raw:
        try:
            # "Sat Sep 26 02:00:00 UTC 2026"
            posted = datetime.strptime(raw, "%a %b %d %H:%M:%S UTC %Y").replace(tzinfo=UTC)
        except ValueError:
            posted = None
    return Detail(
        description_html=(body.html or None) if body is not None and body.text(strip=True) else None,
        places=places,
        posted_at=posted,
        employer=_content(tree.root, "hiringOrganization") if tree.root is not None else None,
    )


class SuccessFactorsAdapter(BaseAdapter):
    name = "successfactors"
    posted_date = "published"  # the detail's `datePosted`
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: The results table states its total.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url="https://{host}/{site}/search/",
        tenants=_TENANTS,
        tenant_url=lambda token: parse_tenant(token).probe_url(),
        read_count=declared_total,
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    @property
    def tenant(self) -> SfTenant:
        return parse_tenant(_TENANTS.resolve(self.company, self.board_token))

    async def fetch(self) -> AsyncIterator[RawJob]:
        # Policy before configuration: a refused company is refused as such.
        self.access.require()
        tenant = self.tenant
        total: int | None = None
        offset = 0
        seen: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[Row]:
            nonlocal total, offset
            resp = await self.context.fetch(FetchRequest(
                url=tenant.search_url(),
                query={"q": "", "sortColumn": "referencedate", "sortDirection": "desc", "startrow": offset},
                source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("search page failed", page=index, status=resp.status)
                stop()
                return []
            text = resp.text()
            if total is None:
                total = declared_total(text)
            rows = parse_rows(text, tenant)
            offset += len(rows)
            if not rows or (total is not None and offset >= total):
                stop()
            return rows

        async for row in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key="search", declared_total=lambda: total,
        ):
            if row.posting_id in seen:
                continue
            seen.add(row.posting_id)
            job = self._job(row, tenant)
            self.keep_held_places(job)
            if row.more:
                await self.place_from_page(job, self._read_places)
            yield job

        # Zero rows stay a failure, never `board_empty`:
        # no tenant's zero-result page has been seen, and this adapter reads
        # several hosts and sites, where a wrong site path may answer an empty
        # search. A fixture of a real empty board is what would make it proof.
        self.drift.require(bool(seen), "empty job list")
        self.close_listing(declared=total, unique=len(seen), field="the results table's total")

    async def _read_places(self, job: RawJob) -> list[str] | None:
        """A "+N more" row's places, from its page; its text and date are kept
        for hydrate. None: unreadable, and the first place stays."""
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page unreadable", req=job.req_id, status=resp.status)
            return None
        detail = parse_detail(resp.text())
        self._apply(job, detail)
        return detail.places

    def _apply(self, job: RawJob, detail: Detail) -> None:
        if detail.places:
            set_places(job, detail.places)
        if detail.description_html:
            job.description_html = detail.description_html
            job.description_complete = True
        if detail.posted_at is not None:
            job.posted_at = detail.posted_at
            if job.source_facts is not None:
                job.source_facts = replace(job.source_facts, first_published_at=detail.posted_at)

    def _job(self, row: Row, tenant: SfTenant) -> RawJob:
        places = [SourceLocation(label=row.place, is_primary=True)] if row.place else []
        return RawJob(
            company=self.company,
            req_id=row.posting_id,
            title=row.title,
            url=row.url,
            locations=[p.label for p in places],
            description_complete=False,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.HTML,
                tenant_identity=f"{tenant.host}|{tenant.site}",
                posting_id=row.posting_id,
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        if job.description_complete:
            return  # read while placing it (`_place`)
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page failed", req=job.req_id, status=resp.status)
            return
        self._apply(job, parse_detail(resp.text()))
