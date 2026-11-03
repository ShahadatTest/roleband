"""Avature career portals — multi-tenant.

    GET https://{host}/{portal}/SearchJobs/?jobRecordsPerPage=20&jobOffset=N
    GET https://{host}/{portal}/JobDetail/{slug}/{id}

Avature serves each tenant's portal from the tenant's own host, rendered
server-side from one template (`/portal/N/`, `portalpacks`). Token
`host|portal` — Electronic Arts: `jobs.ea.com|en_US/careers`. Pacing and the
breaker are per tenant.

**Listing.** The tenant fixes the page size and ignores `jobRecordsPerPage`
(EA 20 a page, Synopsys 6), so the walk advances `jobOffset` by the cards each
page actually returned. The page states the total (`aria-label="326
results"`). A card holds the title, the detail link (whose last segment is the
posting id), and a subtitle of labelled spans — the tenant chooses which:
`list-item-location`, `-workerType`, `-department` (EA); `-hireType`, `-posted`
("Posted 02-Sep-2026") (Synopsys). Unique ids below the stated total invalidate.

**Detail.** Labelled field blocks, no JSON-LD, laid out per tenant. EA: `Work
Model` (workplace), `Studio/Department`, and unlabelled blocks — the first
states the locations ("Locations: Hyderabad, Telangana, India"), the rest are
the description. Synopsys: `City`, `State/Province`, `Country` (the place),
`Job Category`, `Remote Eligible`, `Date Posted`, and the body under the label
`Job Description and Requirements`. A labelled block is a fact unless its label
names the description; no other labelled value enters the description.

**Portal shapes** are declared in the token, never guessed from a page (the
Eightfold `|pcsx` precedent). `host|portal` is the search shape above.
`host|portal|openroles` is Two Sigma's shape:
`SearchJobs` answers 404 and `OpenRoles` lists 10 cards a page, states NO
total anywhere, and puts the place in the card's first unlabelled span
("United States - NY New York") with department and level after it. An
uncounted board ends on its empty page, which is the closure evidence every
uncounted family uses; no total is invented for it. The level ("Experienced")
is a grade, not an employment type, and is not read. Its detail page repeats
the title and country as unlabelled blocks before its labelled facts, so the
description is the unlabelled blocks AFTER the last fact.

`host|portal|folder` is Bain's shape: the
portal lists "folders" (`/FolderDetail/{slug}/{id}`, paged by
`folderRecordsPerPage`/`folderOffset`, 10 a page whatever is asked) and states
its total only as text ("1-10 of 266 results"). Its default order repeats one
posting across a page boundary and never shows another, the same on every
read, so a default walk can never be complete. Sorted by the portal's own
"Posted date" column, the walk reads every posting.
The column is a tenant field id (`schemaField_3_194_3`), so the walk reads it
from the page's sort control rather than naming it. The card's one place span
lists cities comma-joined ("New York, San Francisco"), each a place.

EA's robots allows `/*/careers`, Synopsys' and Two Sigma's `/careers`, each except URLs
carrying `qtvc=`, which the adapter never sends. Synopsys' own careers site
(`careers.synopsys.com`, Radancy TalentBrew) disallows `/search-jobs/`; its
postings apply through this Avature portal, which is where the adapter reads. Some Avature tenants sit behind a bot wall (TSMC: a Cloudflare
challenge on every request); a tenant is added only after
its portal answers an identified client.
"""

from __future__ import annotations

import html
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.extract.payload import job_posting
from tracker.connectors.listing.base import (
    BaseAdapter,
    BoardProbe,
    TenantMap,
    require_tenant_host,
    set_places,
)
from tracker.connectors.sdk import Capabilities, FetchRequest
from tracker.platform.safe_fetch import BlockedDestination
from tracker.platform.util import clean_location
from tracker.schema import (
    AccessSurface,
    CompensationFacts,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
    WorkplaceType,
)

_TENANTS = TenantMap({})
_PAGE = 20
#: Seed and hard ceiling, sized for a large tenant at the smallest page size (6).
_MAX_PAGES = 200
_TOTAL = re.compile(r'aria-label="(\d[\d,]*) results?"')
#: The id is the link's last path segment (EA) or its `jobId` parameter
#: (TSMC: `/JobDetail?jobId=562&source=...`).
_POSTING_ID = re.compile(r"/(?:Job|Folder)Detail(?:/[^/?#]+/(\d+)|\?(?:[^#]*&)?jobId=(\d+))")
_POSTED = re.compile(r"(\d{1,2}-[A-Za-z]{3}-\d{4})")
#: "Posted: Sep 01, 2023" (TSMC).
_POSTED_US = re.compile(r"([A-Za-z]{3} \d{1,2}, \d{4})")
#: Label words that head a section of the posting's text rather than a fact.
_SECTION_WORDS = ("responsibilit", "qualification", "requirement")
_WORKPLACE = {"on-site": WorkplaceType.ONSITE, "onsite": WorkplaceType.ONSITE, "office": WorkplaceType.ONSITE,
              "remote": WorkplaceType.REMOTE, "hybrid": WorkplaceType.HYBRID}


SEARCH, OPENROLES, CAPPED, FOLDER = "search", "openroles", "capped", "folder"
_ROUTES = {SEARCH: "SearchJobs", OPENROLES: "OpenRoles", CAPPED: "SearchJobs", FOLDER: "SearchJobs"}
#: A folder portal fixes 10 a page (Bain ignores 50).
_FOLDER_PAGE = 10
#: "1-10 of 266 results", the folder portal's only statement of its total.
_LEGEND_TOTAL = re.compile(r"\bof\s+(\d[\d,]*)\s+results?\b")
#: The portal's own sort control names the posted-date column's field id.
_POSTED_SORT = re.compile(r'data-sortBy="([^"]+)"\s+aria-label="Sort jobs by Posted date"')
#: A card's place that names no place: the posting page states the real ones.
_GENERIC_PLACES = {"multiple locations"}
#: Re-reads, one row earlier each, when an overlapping page lost its anchor.
_STEP_BACKS = 3
_CAPPED_TOTAL = re.compile(r'data-total="(\d[\d,]*)"')


@dataclass(frozen=True)
class AvatureTenant:
    host: str
    portal: str
    shape: str = SEARCH

    @property
    def counted(self) -> bool:
        """Whether this portal's listing states its total."""
        return self.shape in (SEARCH, FOLDER)

    def search_url(self) -> str:
        return f"https://{self.host}/{self.portal}/{_ROUTES[self.shape]}/"

    def page_query(self, offset: int, sort: str | None = None) -> dict[str, object]:
        if self.shape != FOLDER:
            return {"jobRecordsPerPage": _PAGE, "jobOffset": offset}
        query: dict[str, object] = {"folderRecordsPerPage": _FOLDER_PAGE, "folderOffset": offset}
        if sort:
            query.update(folderSort=sort, folderSortDirection="DESC")
        return query

    def probe_url(self) -> str:
        return self.search_url() + "?" + "&".join(f"{k}={v}" for k, v in self.page_query(0).items())


def parse_tenant(token: str) -> AvatureTenant:
    host, _, rest = token.partition("|")
    portal, _, shape = rest.partition("|")
    shape = shape.strip().lower() or SEARCH
    if not host.strip() or not portal.strip() or shape not in _ROUTES:
        raise ValueError(
            f"avature board_token must be 'host|portal' or 'host|portal|openroles|capped|folder', got {token!r}"
        )
    return AvatureTenant(host.strip(), portal.strip().strip("/"), shape)


def declared_total(page: str) -> int | None:
    """`aria-label="326 results"` (search), else the folder legend "of 266 results"."""
    match = _TOTAL.search(page)
    if match is None:
        legend = HTMLParser(page).css_first(".list-controls__text__legend")
        match = _LEGEND_TOTAL.search(" ".join(legend.text().split())) if legend is not None else None
    return int(match.group(1).replace(",", "")) if match else None


def posted_sort(page: str) -> str | None:
    """The field id the portal sorts "Posted date" by, from its own control."""
    match = _POSTED_SORT.search(page)
    return match.group(1) if match else None


def folder_places(text: str | None) -> list[str]:
    """A folder card's place span: cities, comma-joined ("Boston, New York")."""
    places: list[str] = []
    for raw in (text or "").split(","):
        place = clean_location(raw.strip())
        if place and place not in places:
            places.append(place)
    return places


@dataclass(frozen=True)
class Card:
    posting_id: str
    title: str
    url: str
    location: str | None
    department: str | None
    worker_type: str | None
    posted_at: datetime | None = None


def parse_posted(text: str | None) -> datetime | None:
    """"Posted 02-Sep-2026" / "02-Sep-2026" -> that day (UTC)."""
    for pattern, form in ((_POSTED, "%d-%b-%Y"), (_POSTED_US, "%b %d, %Y")):
        match = pattern.search(text or "")
        if match:
            try:
                return datetime.strptime(match.group(1), form).replace(tzinfo=UTC)
            except ValueError:
                return None
    return None


def _span(node: Node, name: str) -> str | None:
    found = node.css_first(f".list-item-{name}")
    text = found.text(strip=True) if found is not None else ""
    return text or None


def _unlabelled_subtitle(article: Node) -> tuple[str | None, str | None]:
    """OpenRoles cards: the place, then (in the sub-text) the department."""
    header = article.css_first(".article__header__content__text")
    if header is None:
        return None, None
    place = next((
        child.text(strip=True) for child in header.iter()
        if child.tag == "span" and child.text(strip=True)
    ), None)
    sub = header.css_first(".article__header__content__sub-text span")
    return place, (sub.text(strip=True) or None) if sub is not None else None


def _capped_subtitle(article: Node) -> tuple[str | None, str | None]:
    """Deloitte cards: `org | legal entity | place`, unlabelled; the place may be
    generic. The legal entity ("Deloitte Consulting LLP") is not a department,
    which feeds role classification, so it is not read."""
    spans = [s.text(strip=True) for s in article.css(".article__header__text__subtitle span")]
    spans = [s for s in spans if s]
    return (spans[-1] if len(spans) >= 3 else None), None


def _folder_subtitle(article: Node) -> tuple[str | None, str | None]:
    """Bain cards: one unlabelled span, the place (cities comma-joined)."""
    spans = [s.text(strip=True) for s in article.css(".article__header__text__subtitle span")]
    return next((s for s in spans if s), None), None


def capped_total(page: str) -> int | None:
    """`data-total="1234"` is a count; `"999+"` is a display cap, never a count."""
    match = _CAPPED_TOTAL.search(page)
    return int(match.group(1).replace(",", "")) if match and "+" not in match.group(0) else None


def parse_cards(page: str, shape: str = SEARCH) -> list[Card]:
    cards: list[Card] = []
    for article in HTMLParser(page).css("article.article--result"):
        link = (article.css_first("a.link_result") or article.css_first('a[href*="/JobDetail"]')
                or article.css_first('h3 a[href*="/FolderDetail"]'))
        href = link.attributes.get("href") if link is not None else None
        match = _POSTING_ID.search(href or "")
        title = link.text(strip=True) if link is not None else ""
        if not match or not title:
            continue
        posting_id = match.group(1) or match.group(2)
        if shape in (OPENROLES, CAPPED, FOLDER):
            place, department = (
                _unlabelled_subtitle if shape == OPENROLES
                else _capped_subtitle if shape == CAPPED else _folder_subtitle
            )(article)
            cards.append(Card(
                posting_id=posting_id, title=title, url=href or "",
                location=place, department=department, worker_type=None,
            ))
            continue
        cards.append(Card(
            posting_id=posting_id, title=title, url=href or "",
            location=_span(article, "location"), department=_span(article, "department"),
            worker_type=(_span(article, "workerType") or _span(article, "hireType")
                         or _span(article, "employmentType")),
            posted_at=parse_posted(_span(article, "posted")),
        ))
    return cards


@dataclass(frozen=True)
class Detail:
    description_html: str | None
    locations: list[str]
    workplace: WorkplaceType
    department: str | None
    posted_at: datetime | None = None


def parse_detail(page: str, shape: str = SEARCH) -> Detail:
    """Labelled blocks are facts, except one whose label names the description;
    unlabelled ones are the locations line, then the description, in page
    order. OpenRoles: only unlabelled blocks after the last fact describe."""
    labelled: dict[str, str] = {}
    body: list[str] = []
    locations: list[str] = []
    fields = HTMLParser(page).css(".article__content__view__field")
    if shape == OPENROLES:
        last_fact = max((
            i for i, f in enumerate(fields)
            if (lab := f.css_first(".article__content__view__field__label")) is not None
            and lab.text(strip=True)
        ), default=-1)
        for field in fields[: last_fact + 1]:
            label, value = (field.css_first(f".article__content__view__field__{p}") for p in ("label", "value"))
            if label is not None and value is not None and label.text(strip=True):
                labelled[label.text(strip=True).lower()] = value.text(strip=True)
        body = [
            value.html or "" for field in fields[last_fact + 1:]
            if (value := field.css_first(".article__content__view__field__value")) is not None
            and value.text(strip=True)
        ]
        fields = []
    for field in fields:
        label = field.css_first(".article__content__view__field__label")
        value = field.css_first(".article__content__view__field__value")
        if value is None:
            continue
        text = value.text(strip=True)
        heading = label.text(strip=True) if label is not None else ""
        name = heading.lower()
        if name and "description" in name:
            body.append(value.html or "")
        elif name and any(word in name for word in _SECTION_WORDS):
            # TSMC: "Job Responsibilities", "Job Qualifications" are the posting's
            # own text under a heading, not facts; the heading is kept.
            body.append(f"<h3>{html.escape(heading)}</h3>{value.html or ''}")
        elif name:
            labelled[name] = text
        elif text.lower().startswith("locations:") and not locations:
            for raw in re.split(r"\s*[;|]\s*", text.split(":", 1)[1]):
                place = clean_location(raw)
                if place and place not in locations:
                    locations.append(place)
        elif text:
            body.append(value.html or "")
    if not locations:
        # Deloitte: the posting page lists every place under the header.
        for para in HTMLParser(page).css(".article__header--locations p"):
            place = clean_location(para.text(strip=True))
            if place and place not in locations:
                locations.append(place)
    if not body:
        # No field blocks at all (Deloitte): the page's own JobPosting text.
        posting = job_posting(page)
        description = posting.get("description") if posting else None
        if isinstance(description, str) and description.strip():
            body.append(description)
    if not locations:
        # Synopsys states the place as fields, not a line.
        parts = [labelled.get(k, "").strip() for k in ("city", "state/province", "country")]
        place = clean_location(", ".join(p for p in parts if p)) if any(parts) else None
        if place:
            locations.append(place)
    workplace = _WORKPLACE.get(labelled.get("work model", "").strip().lower(), WorkplaceType.UNKNOWN)
    if workplace is WorkplaceType.UNKNOWN and labelled.get("remote eligible", "").strip().lower() == "yes":
        workplace = WorkplaceType.REMOTE
    return Detail(
        description_html="".join(body) or None,
        locations=locations,
        workplace=workplace,
        department=(labelled.get("studio/department") or labelled.get("department")
                    or labelled.get("job category") or labelled.get("function")
                    or labelled.get("career area") or labelled.get("work areas")),
        posted_at=(parse_posted(labelled.get("date posted") or labelled.get("posted"))
                   or _json_ld_posted(page)),
    )


def _json_ld_posted(page: str) -> datetime | None:
    """The page's JobPosting `datePosted`, an ISO date (Bain states no labelled date)."""
    posting = job_posting(page)
    raw = posting.get("datePosted") if posting else None
    try:
        return datetime.strptime(raw.strip()[:10], "%Y-%m-%d").replace(tzinfo=UTC) if isinstance(raw, str) else None
    except ValueError:
        return None


class AvatureAdapter(BaseAdapter):
    name = "avature"
    posted_date = "published"  # the card's or the detail's "Posted" date
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: Two routes to the same portals and posting ids: this
    #: one, and `avature_tls` for a portal that refuses an identified client.
    route_family = "avature"
    #: The search page states its result total. Per
    #: tenant, not per family: an `|openroles` portal states none, and `fetch`
    #: says so on the instance before the epilogue.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url="https://{host}/{portal}/SearchJobs/",
        tenants=_TENANTS,
        tenant_url=lambda token: parse_tenant(token).probe_url(),
        read_count=declared_total,
        uncounted_rows=lambda token, page: (
            None if parse_tenant(token).counted else len(parse_cards(page, parse_tenant(token).shape))
        ),
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)
    #: The tenant is the host its careers page is served from, which a pasted
    #: page can choose: every request, redirect hops included, stays on that
    #: host at a pinned public address.
    public_only = True

    @property
    def tenant(self) -> AvatureTenant:
        return parse_tenant(_TENANTS.resolve(self.company, self.board_token))

    def validate_destination(self, url: str) -> None:
        require_tenant_host(url, self.tenant.host)

    def _on_tenant(self, job: RawJob) -> bool:
        """Whether the posting's link stays on the tenant's host. A link the
        page points elsewhere is never read, on either route."""
        try:
            self.validate_destination(job.url)
        except BlockedDestination:
            self.drift.note("posting link leaves the tenant's host", req=job.req_id)
            return False
        return True

    async def fetch(self) -> AsyncIterator[RawJob]:
        # Policy before configuration: a refused company is refused as such.
        self.access.require()
        tenant = self.tenant
        self.declares_total = tenant.counted
        total: int | None = None
        offset = 0
        anchor: str | None = None
        seen: set[str] = set()
        sort: str | None = None
        if tenant.shape == FOLDER:
            # One read of the default order, only to learn the posted-date
            # column: the default order hides a posting.
            first = await self.context.fetch(FetchRequest(
                url=tenant.search_url(), query=tenant.page_query(0), source_key=self.company,
            ))
            sort = posted_sort(first.text()) if first.status == 200 else None
            if sort is None:
                self.drift.note("folder portal offers no posted-date sort; walking its default order")

        async def read(index: int, stop: Callable[[], None]) -> tuple[str, list[Card]] | None:
            resp = await self.context.fetch(FetchRequest(
                url=tenant.search_url(),
                query=tenant.page_query(offset, sort),
                source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("search page failed", page=index, status=resp.status)
                stop()
                return None
            text = resp.text()
            return text, parse_cards(text, tenant.shape)

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[Card]:
            nonlocal total, offset
            answer = await read(index, stop)
            if answer is None:
                return []
            text, cards = answer
            if total is None and tenant.counted:
                total = declared_total(text)
            # The tenant's page size, not ours: advance by what came back.
            offset += len(cards)
            if not cards or (total is not None and offset >= total):
                stop()
            return cards

        async def fetch_overlapping(index: int, stop: Callable[[], None]) -> list[Card]:
            """An uncounted board has no total to expose a lost row, so pages
            overlap by one: each must contain the previous page's last posting.
            Missing means rows moved UP (a posting closed mid-walk) and one may
            have slipped between pages; re-read one row earlier until the anchor
            is found, or give up the listing's closure authority."""
            nonlocal total, offset, anchor
            for step_back in range(_STEP_BACKS + 1):
                answer = await read(index, stop)
                if answer is None:
                    return []
                text, cards = answer
                if tenant.shape == CAPPED and total is None:
                    total = capped_total(text)
                if not cards or anchor is None or anchor in {c.posting_id for c in cards}:
                    break
                if step_back == _STEP_BACKS or offset == 0:
                    self.drift.invalidate_listing(
                        "pages shifted past reconciliation", offset=offset, anchor=anchor,
                    )
                    break
                offset -= 1
            if cards:
                anchor = cards[-1].posting_id
                offset += max(1, len(cards) - 1)
            return cards

        async for card in self.paged_listing(
            fetch_page if tenant.counted else fetch_overlapping,
            max_pages=_MAX_PAGES, query_key="search", declared_total=lambda: total, page_size=None,
        ):
            if card.posting_id in seen:
                continue
            seen.add(card.posting_id)
            job = self._job(card, tenant)
            self.keep_held_places(job)
            if card.location and card.location.strip().lower() in _GENERIC_PLACES:
                await self.place_from_page(job, self._read_places, clear_listed_place=True)
            yield job

        self.drift.require(bool(seen), "empty job list")
        if tenant.shape == CAPPED:
            # A board that states a real count below its display cap is held to it.
            self.declares_total = total is not None
        self.close_listing(declared=total, unique=len(seen), field="the search's result total")

    async def _read_places(self, job: RawJob) -> list[str] | None:
        """A "Multiple Locations" card's places, from its page. Everything else
        the page states is kept too (`_apply`), since hydration does not read
        it again. The card's label names no place, so a card left unplaced is
        shown to nobody either way. Read only for a posting the role gate
        admits: a tenant with many such cards would spend most of a scan on
        them unfiltered."""
        if not self._on_tenant(job):
            return None
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page unreadable", req=job.req_id, status=resp.status)
            return None
        detail = parse_detail(resp.text(), self.tenant.shape)
        self._apply(job, detail)
        return detail.locations

    @staticmethod
    def _apply(job: RawJob, detail: Detail) -> None:
        """What a posting page states, onto its row: one rule for a page read
        while placing a card and for one read by `hydrate`, which skips a
        posting already read. The card keeps its department and date where it
        states them; the page's places are the fuller ones."""
        job.description_html = detail.description_html
        job.description_complete = bool(detail.description_html)
        if detail.workplace is not WorkplaceType.UNKNOWN:
            job.workplace_type = detail.workplace
        job.department = job.department or detail.department
        if job.posted_at is None and detail.posted_at is not None:
            job.posted_at = detail.posted_at
            if job.source_facts is not None:
                job.source_facts = replace(job.source_facts, first_published_at=detail.posted_at)
        if detail.locations:
            set_places(job, detail.locations)

    def _job(self, card: Card, tenant: AvatureTenant) -> RawJob:
        if tenant.shape == FOLDER:
            labels = folder_places(card.location)
        else:
            label = clean_location(card.location) if card.location else None
            labels = [label] if label else []
        places = [SourceLocation(label=label, is_primary=i == 0) for i, label in enumerate(labels)]
        return RawJob(
            company=self.company,
            req_id=card.posting_id,
            title=card.title,
            url=card.url,
            locations=[p.label for p in places],
            department=card.department,
            posted_at=card.posted_at,
            description_complete=False,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.HTML,
                tenant_identity=f"{tenant.host}|{tenant.portal}",  # the shape is ours, not the tenant's
                posting_id=card.posting_id,
                employment_type_raw=card.worker_type,
                first_published_at=card.posted_at,
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        if job.description_complete:
            return  # read while placing it (`_read_places`)
        if not self._on_tenant(job):
            return
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page failed", req=job.req_id, status=resp.status)
            return
        self._apply(job, parse_detail(resp.text(), self.tenant.shape))


class AvatureTlsAdapter(AvatureAdapter):
    """An Avature portal behind a bot wall that refuses identified clients.

    TSMC: careers.tsmc.com answers every identified request, robots
    included, with a Cloudflare challenge (403), while its robots file allows
    `/*/careers`. A browser TLS fingerprint (`curl_cffi`) reads the same
    portal completely. The wall is
    recorded on this route's register row (`refuses_identified_client`,
    `fetch_tier=tls_fingerprint`), so the company is walled: never curated,
    collected only after a user follows it and consents, and fetched on that
    tier only then. Parsing is the family's; nothing else differs.
    """

    name = "avature_tls"
    #: Its tier cannot pin addresses (`make_tier_client` refuses), and its
    #: tenants come from the catalog, never from a pasted page. Posting links
    #: are still held to the tenant's host (`_on_tenant`).
    public_only = False
    posted_date = "published"  # the card's or the detail's "Posted" date
