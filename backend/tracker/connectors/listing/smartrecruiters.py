"""SmartRecruiters — one family, two routes.

**Board route, `smartrecruiters` (preferred).** The career page SmartRecruiters
publishes for job seekers, `careers.smartrecruiters.com/{token}`. It serves no
robots file (the host 302s `/robots.txt` to `jobs.smartrecruiters.com`, which
answers 404 with an HTML page), so it is not walled. Postings are grouped,
usually by location; some tenants group by department, and then each
posting prints its own place on the line a location board uses for employment
(`board_grouping`):

* the index page carries `data-groups-pages="N"` and the first groups; a board
  with no openings carries neither, only its no-openings notice;
* `/{token}/api/groups?page=1..N-1` returns the rest, and page N is empty;
* each group states its size (`<section data-qty="Q">`) but lists at most ~9
  postings, then a "Show more jobs" link: `/{token}/api/more?type=location&
  value=...&page=P`. Page `data-page` repeats what the group already showed, so
  paging starts at `data-page + 1`.

Completeness is proved per group: every group must list exactly the postings
it states. Descriptions come
from each posting's page on `jobs.smartrecruiters.com` (schema.org microdata),
fetched only in `hydrate()`, i.e. only for kept postings.

Each group page is read and its groups completed before the next page is
asked for, so a read always holds a place to continue from (`resume_point`):
the last page whose groups are all finished, by its number and by its groups'
headings and postings. Only the directory scan continues a read
(`resume_from`); the collector always reads from page one.

**API route, `smartrecruiters_api` (fallback).** The documented Posting API on
`api.smartrecruiters.com`, whose robots allows only `LinkedInBot` and gives
every other agent `Disallow: /`. So this route is WALLED: collected
only for a company whose user consented. It exists for tenants whose board is
not published on SmartRecruiters at all (the board root redirects to the
tenant's own career site), which the board route cannot read.

**The switch.** Each route checks the board root before it collects:

* the board route finds the board redirected off SmartRecruiters -> the
  company moves to the API route;
* the API route finds the board published -> the company moves back.

Either raises `RouteMoved`: that run is `unattempted` (no evidence about the
source, no closure), the pipeline records the new route on the company
(`company_store.record_route`), and the next run scans it under that route's
own policy. A company moving onto the walled route therefore waits for the
user's consent, and appears on Settings with the consent dialog like any other
walled company. Both routes name postings by the same id, so the company keeps
its jobs across a move; the new route's binding withholds closure until a
complete listing validates it, exactly as for any rebind.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.extract.payload import text_of
from tracker.connectors.listing.base import (
    BaseAdapter,
    BoardProbe,
    ReadPosition,
    RouteMoved,
    TenantMap,
)
from tracker.connectors.sdk import Capabilities, FetchRequest
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
from tracker.taxonomy.locations import countries_for

#: Company slug -> SmartRecruiters company identifier. Catalog rows carry their
#: own `board_token`; there is no built-in tenant, so the map is empty.
SMARTRECRUITERS_COMPANIES: dict[str, str] = {}
_TENANTS = TenantMap(SMARTRECRUITERS_COMPANIES)

BOARD_HOST = "careers.smartrecruiters.com"
_BOARD_ROOT = f"https://{BOARD_HOST}/{{token}}"
_GROUPS = f"https://{BOARD_HOST}/{{token}}/api/groups"
_JOB_HOST = "jobs.smartrecruiters.com"
_API_POSTINGS = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
_API_COMPANY = "https://api.smartrecruiters.com/v1/companies/{token}"

#: Seeds for the learned page budgets, with room above the largest boards
#: (a more-page adds about ten postings to a group).
_MAX_GROUP_PAGES = 60
_MAX_MORE_PAGES = 60
_API_PAGE_SIZE = 100
_MAX_API_PAGES = 100

_HTML_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
_POSTING_ID = re.compile(r"^https?://jobs\.smartrecruiters\.com/[^/?#]+/(\d+)")
_BOARD_TITLE = re.compile(r"^\s*Careers at\s+(.+?)\s*$")
#: The notice a board with no openings prints where its group list would be.
#: The page an unknown token lands on (the job search) carries no such notice.
_NO_OPENINGS = "#st-noOpeningsFound"

#: SmartRecruiters' employment labels, on both routes (the board prints the
#: API's `typeOfEmployment.label`).
_EMPLOYMENT = {
    "full-time": EmploymentType.FULL_TIME,
    "full time": EmploymentType.FULL_TIME,
    "permanent": EmploymentType.FULL_TIME,
    "part-time": EmploymentType.PART_TIME,
    "part time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "contractor": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "intern": EmploymentType.INTERN,
    "internship": EmploymentType.INTERN,
}
_WORKPLACE = {
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
    "on_site": WorkplaceType.ONSITE,
}


# --------------------------------------------------------------------------- #
# Board pages (pure parsing)
# --------------------------------------------------------------------------- #


@dataclass
class _Posting:
    posting_id: str
    title: str
    url: str
    #: The line the listing prints under the title: whatever the board does NOT
    #: group by. Employment on a board grouped by location, the posting's own
    #: place on one grouped by department (`board_grouping`).
    detail: str | None = None
    places: list[str] = field(default_factory=list)


@dataclass
class _Group:
    label: str
    stated: int
    postings: dict[str, _Posting]
    #: (path, type, value, first page to request) of the group's more-route.
    #: The type is the link's own `data-type`, None when it names none: only
    #: the board's word decides its grouping.
    more: tuple[str, str | None, str, int] | None = None
    #: The group page it was listed on (0 = the board index).
    page: int = 0


def board_is_published(final_url: str, status: int, body: str) -> bool | None:
    """True: the board is on SmartRecruiters. False: it redirected elsewhere.
    None: neither — a dead or changed page, for the caller to report.

    Off-platform is judged by the final HOST only: SmartRecruiters redirects a
    tenant that publishes its own career site to that site.
    """
    host = urlsplit(final_url).hostname or ""
    if not host.endswith("smartrecruiters.com"):
        return False
    if status == 200 and declared_group_pages(body) is not None:
        return True
    return None


def declared_group_pages(html: str) -> int | None:
    """The group pages a board index declares; None if the page is no board
    index. A board with no openings states no count, and its notice declares
    none."""
    tree = HTMLParser(html)
    node = tree.css_first("[data-groups-pages]")
    if node is None:
        return 0 if tree.css_first(_NO_OPENINGS) is not None else None
    try:
        return int(node.attributes.get("data-groups-pages") or "")
    except ValueError:
        return None


def board_name(html: str) -> str | None:
    """The company the board names (`og:title` "Careers at {Name}")."""
    tree = HTMLParser(html)
    for selector in ('meta[property="og:title"]', "title"):
        node = tree.css_first(selector)
        if node is None:
            continue
        text = node.attributes.get("content") if node.tag == "meta" else node.text()
        match = _BOARD_TITLE.match(text or "")
        if match:
            return match.group(1)
    return None


def board_posting_count(html: str) -> int | None:
    """Postings the index page states across its first groups; None if the page
    is not a board. A PRESENCE count, not the board's size."""
    if declared_group_pages(html) is None:
        return None
    return sum(group.stated for group in parse_groups(html))


def _postings_in(node: Node) -> dict[str, _Posting]:
    found: dict[str, _Posting] = {}
    for link in node.css("a.js-job-ad-link"):
        href = link.attributes.get("href") or ""
        match = _POSTING_ID.match(href)
        title_node = link.css_first(".job-title") or link
        title = title_node.text(strip=True)
        if not match or not title:
            continue
        detail = link.css_first(".job-desc span")
        found[match.group(1)] = _Posting(
            posting_id=match.group(1),
            title=title,
            url=href,
            detail=detail.text(strip=True) or None if detail is not None else None,
        )
    return found


def parse_groups(html: str) -> list[_Group]:
    groups: list[_Group] = []
    for section in HTMLParser(html).css("section.opening"):
        try:
            stated = int(section.attributes.get("data-qty") or "")
        except ValueError:
            continue
        heading = section.css_first(".opening-title")
        label = heading.text(strip=True) if heading is not None else ""
        more = None
        link = section.css_first("a.js-more")
        if link is not None:
            attrs = link.attributes
            try:
                more = (
                    attrs.get("data-more") or "",
                    attrs.get("data-type") or None,
                    unquote(attrs.get("data-value") or ""),
                    int(attrs.get("data-page") or "0") + 1,
                )
            except ValueError:
                more = None
        groups.append(_Group(label=label, stated=stated, postings=_postings_in(section), more=more))
    return groups


def _reads_as_place(text: str | None) -> bool:
    """ "City, Country" or "City, ST": a comma and a country. A bare heading is
    not enough: "IT" and "HR" are departments that read as Italy and Croatia."""
    return text is not None and "," in text and bool(countries_for([text]))


def board_grouping(groups: list[_Group], known: str | None = None) -> str:
    """What a board groups its postings by: "location", or another kind.

    The board says so only on a group's "Show more jobs" link (`data-type`),
    and groups one way throughout. Some boards group by department, where the
    heading is a department and each posting prints its own place. A board
    whose groups all fit on the page names no kind: it groups by something
    else only when most posting lines read as places and most headings do
    not; otherwise location (a heading "Agen, France" over a line "Temps
    plein" is a location board).

    `known` is what an earlier part of the same read decided (a resumed read):
    the tail of a board may hold no more-link to say it again.
    """
    for group in groups:
        if group.more is not None and group.more[1]:
            return group.more[1]
    if known is not None:
        return known
    details = [p.detail for group in groups for p in group.postings.values()]
    headings = [group.label for group in groups]
    if (
        details and headings
        and sum(map(_reads_as_place, details)) * 2 > len(details)
        and sum(map(_reads_as_place, headings)) * 2 < len(headings)
    ):
        return "department"
    return "location"


def parse_more(html: str) -> dict[str, _Posting]:
    tree = HTMLParser(html)
    node = tree.body or tree.root
    return _postings_in(node) if node is not None else {}


# --------------------------------------------------------------------------- #
# Job page microdata (pure parsing)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class JobPage:
    description_html: str | None
    posted_at: datetime | None
    employment: str | None
    workplace: WorkplaceType
    hiring_organization: str | None
    place: SourceLocation | None


def _meta(node: Node | None, prop: str) -> str | None:
    if node is None:
        return None
    found = node.css_first(f'meta[itemprop="{prop}"]')
    value = found.attributes.get("content") if found is not None else None
    return value.strip() if value and value.strip() else None


def parse_job_page(html: str) -> JobPage:
    """The posting page's microdata. Attribute names are read lower-case: the
    HTML parser folds `formattedAddress` / `workplaceType` as browsers do."""
    tree = HTMLParser(html)
    description = tree.css_first('[itemprop="description"]')
    location = tree.css_first('[itemprop="jobLocation"]')
    widget = location.css_first("spl-job-location") if location is not None else None
    organization = tree.css_first('[itemprop="hiringOrganization"]')
    employment = tree.css_first('[itemprop="employmentType"]')
    place = None
    if location is not None:
        locality, region, country = (
            _meta(location, "addressLocality"),
            _meta(location, "addressRegion"),
            _meta(location, "addressCountry"),
        )
        # The structured parts first: `formattedAddress` is whatever the tenant
        # typed, and it carries street addresses ("15725 Dallas Pkwy, 75001
        # Addison, ...") and work arrangements ("remote, Addison, ..."), neither
        # of which is a PLACE. It is the fallback, not the label.
        formatted = widget.attributes.get("formattedaddress") if widget is not None else None
        label = clean_location(", ".join(p for p in (locality, region, country) if p) or formatted)
        if label:
            place = SourceLocation(
                label=label, country=country, region=region, locality=locality, is_primary=True,
            )
    workplace = WorkplaceType.UNKNOWN
    if widget is not None:
        workplace = _WORKPLACE.get((widget.attributes.get("workplacetype") or "").lower(), WorkplaceType.UNKNOWN)
    root = tree.root
    return JobPage(
        description_html=description.html if description is not None else None,
        posted_at=parse_datetime(_meta(root, "datePosted")),
        employment=employment.text(strip=True) or None if employment is not None else None,
        workplace=workplace,
        hiring_organization=_meta(organization, "name"),
        place=place,
    )


def _employment(raw: str | None) -> EmploymentType:
    return _EMPLOYMENT.get((raw or "").strip().lower(), EmploymentType.UNKNOWN)


def _object(value: object) -> dict:
    """A payload member that should be an object; anything else reads as empty."""
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #

_CAPABILITIES = Capabilities(stream=False, post=False, impersonate=False, render=False)


class _SmartRecruitersBase(BaseAdapter):
    route_family = "smartrecruiters"
    required_capabilities = _CAPABILITIES

    def _token(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token)

    async def _board_root(self) -> tuple[bool | None, str, int, str]:
        resp = await self.context.fetch(
            FetchRequest(url=_BOARD_ROOT.format(token=self._token()), source_key=self.company)
        )
        body = resp.text()
        return board_is_published(resp.final_url, resp.status, body), resp.final_url, resp.status, body

    def _facts(
        self,
        posting_id: str,
        *,
        access_surface: AccessSurface,
        employment_type_raw: str | None,
        employment_type_normalized: EmploymentType,
        locations: list[SourceLocation],
        requisition_label: str | None = None,
        first_published_at: datetime | None = None,
    ) -> SourceJobFacts:
        return SourceJobFacts(
            provider=self.name,
            tenant_identity=self._token(),
            posting_id=posting_id,
            access_surface=access_surface,
            requisition_label=requisition_label,
            first_published_at=first_published_at,
            employment_type_raw=employment_type_raw,
            employment_type_normalized=employment_type_normalized,
            locations=locations,
            # Neither route carries pay fields; not asking is its own answer.
            compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
            observed_at=datetime.now(UTC),
        )


@dataclass
class _BoardRead:
    """One board read's state, shared by the steps `fetch` runs:
    the groups taken, pages served, each page's groups, the postings finished,
    and the position the read continued from."""

    index: str
    groups: list[_Group] = field(default_factory=list)
    #: Pages 0..served-1 served groups; compared with what the board declares.
    served: int = 0
    on_page: dict[int, list[_Group]] = field(default_factory=dict)
    #: Postings in the groups this read has finished, for its position.
    finished: set[str] = field(default_factory=set)
    before: ReadPosition = field(default_factory=lambda: ReadPosition(at={}))


class SmartRecruitersAdapter(_SmartRecruitersBase):
    """The public career board (unwalled). See the module docstring."""

    name = "smartrecruiters"
    posted_date = "published"  # the page's `datePosted`
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    board_probe = BoardProbe(
        jobs_url=_BOARD_ROOT,
        tenants=_TENANTS,
        # The board page names its company ("Careers at {Name}"), so the
        # same route that proves the board is live settles whose it is.
        identity_url=_BOARD_ROOT,
        read_count=board_posting_count,
        read_identity=board_name,
        counts_whole_board=False,
    )

    async def fetch(self) -> AsyncIterator[RawJob]:
        published, final_url, status, index = await self._board_root()
        if published is False:
            raise RouteMoved(
                self.name,
                "smartrecruiters_api",
                f"{self.company!r} publishes no board on SmartRecruiters (redirected to"
                f" {urlsplit(final_url).hostname}); moving it to the SmartRecruiters API route",
            )
        pages = declared_group_pages(index) if published else None
        if pages is None:
            self.drift.invalidate_listing("board index is not a SmartRecruiters board", status=status)
            return

        read = _BoardRead(index=index)
        self._completed_rows = lambda: self._group_jobs(read.groups)
        start, walk = await self._continue_from(read)
        if walk:
            await self._walk(read, start)
        async for job in self._verdict(read, pages):
            yield job

    async def _group_page(self, read: _BoardRead, number: int) -> list[_Group] | None:
        """One group page, each group tagged with it; None if it failed. A
        page already read while finding the place to continue is not asked
        for again."""
        if number in read.on_page:
            return read.on_page[number]
        if number == 0:
            found = parse_groups(read.index)
        else:
            resp = await self.context.fetch(
                FetchRequest(
                    url=_GROUPS.format(token=self._token()),
                    query={"page": number},
                    source_key=self.company,
                )
            )
            if resp.status != 200:
                self.drift.invalidate_listing("group page failed", page=number, status=resp.status)
                return None
            found = parse_groups(resp.text())
        for group in found:
            group.page = number
        if found:
            read.served = max(read.served, number + 1)
        read.on_page[number] = found
        return found

    async def _take(self, read: _BoardRead, group: _Group) -> None:
        read.groups.append(group)
        if group.more is not None and group.more[1] and self._known_grouping is None:
            self._known_grouping = group.more[1]  # the board's own word
        await self._finish_group(group)
        read.finished.update(group.postings)

    def _reached(self, read: _BoardRead, number: int) -> None:
        """Every group up to this page's last is finished: a read cut later
        continues after it. Only while the part read is complete, so a
        continued read can never inherit a part that was not."""
        if not self.drift.listing_complete or self.truncated:
            self.resume_point = None
            return
        self.resume_point = ReadPosition(
            at={
                "page": number,
                # Each group by its heading and its postings: a heading can
                # repeat (two groups with one heading, side by side).
                "groups": [[group.label, sorted(group.postings)] for group in read.on_page[number]],
                "grouping": self._known_grouping,
            },
            listed=read.before.listed | read.finished,
            unread_by_choice=read.before.unread_by_choice + self.unread_by_choice,
        )

    async def _continue_from(self, read: _BoardRead) -> tuple[int, bool]:
        """Where this read starts: (first group page to walk, whether to walk).

        Each group page is read and its groups finished before the next page
        is asked for, so a read always holds a place it can continue from.
        A page number alone is no address: pages shift as groups
        come and go. The board's order is its own (a locale collation, never
        ours to recompute), and paging slices it without gaps, so the place
        is just after the last group the read finished. A group added before
        it pushes it onto the next page, which is read anyway; none, or one
        removed, leaves it on its own page. Not found on either, the read
        starts over. A group is known by its heading AND a posting it listed:
        headings repeat, and taking a new group for a finished one would skip
        it while the read still claimed the board whole.
        """
        found = self._held_position()
        if found is None:
            return 0, True
        held, number, done = found
        # Cut again before the place is found, the read is still there.
        self.resume_point = held

        def finished_before(group: _Group) -> bool:
            return any(label == group.label and not ids.isdisjoint(group.postings) for label, ids in done)

        for probe in (number + 1, number):
            page = await self._group_page(read, probe)
            if page is None:
                return 0, False  # the board's own failure, already recorded
            last = max((i for i, group in enumerate(page) if finished_before(group)), default=None)
            if last is None:
                continue
            grouping = held.at.get("grouping")
            self.resumed, read.before = True, held
            self._known_grouping = grouping if isinstance(grouping, str) else None
            for group in page[last + 1:]:
                if not finished_before(group):
                    await self._take(read, group)
            self._reached(read, probe)
            return probe + 1, True
        self.resume_point = None
        self.drift.note("the place to continue from has moved; reading from the start",
                        page=number, group=done[-1][0])
        return 0, True

    async def _walk(self, read: _BoardRead, start: int) -> None:
        """Read the group pages from `start`, finishing each group, holding the
        place after every page's last group."""

        async def fetch_page(number: int, stop: Callable[[], None]) -> list[_Group]:
            found = await self._group_page(read, number)
            if found is None:
                stop()
                return []
            return found

        async for group in self.paged_listing(
            fetch_page, max_pages=_MAX_GROUP_PAGES, query_key="groups", start=start,
        ):
            await self._take(read, group)
            if group is read.on_page[group.page][-1]:
                self._reached(read, group.page)

    async def _verdict(self, read: _BoardRead, pages: int) -> AsyncIterator[RawJob]:
        """Judge what was read against what the board declares, then list it."""
        # A ceiling hit is OUR bound (`truncated`, already recorded): keep what
        # was read, and do not also blame the source for pages we never asked.
        if not self.truncated and read.served < pages:
            # Fewer pages than the board declared: postings we never saw.
            self.drift.invalidate_listing(
                "board served fewer group pages than it declared", declared=pages, served=read.served,
            )
        elif read.served > pages:
            # More than declared loses nothing: every page served was read until
            # one came back empty, and each group still proves its own count.
            self.drift.note("board served more group pages than it declared",
                            declared=pages, served=read.served)

        jobs = {job.req_id: job for job in self._group_jobs(read.groups)}
        if not jobs and pages == 0 and not self.resumed:
            # A published board index declaring no group page and listing no
            # group: the board's own statement that it lists nothing.
            # An unknown token answers no board index at all
            # (`board_is_published`), so this is not a wrong tenant's answer.
            self.drift.board_empty("board index declares no group page")
            return
        # A continued read may find nothing after its position; the part before
        # it listed what it listed.
        self.drift.require(bool(jobs) or (self.resumed and bool(read.before.listed)), "empty job list")
        self._completed_rows = jobs.values
        for key, job in list(jobs.items()):
            yield job
            jobs.pop(key)

    #: What the board's more-links said it groups by, in this read or the part
    #: of it before a resume; None while none has said.
    _known_grouping: str | None = None

    def _held_position(self) -> tuple[ReadPosition, int, list[tuple[str, set[str]]]] | None:
        """`resume_from`, when it names a page and the groups finished on it,
        with that page and each of those groups as its heading and postings."""
        held = self.resume_from
        if held is None:
            return None
        page, groups = held.at.get("page"), held.at.get("groups")
        if not (isinstance(page, int) and page >= 0 and isinstance(groups, list) and groups):
            return None
        done: list[tuple[str, set[str]]] = []
        for group in groups:
            if not (
                isinstance(group, list) and len(group) == 2
                and isinstance(group[0], str) and isinstance(group[1], list)
            ):
                return None
            done.append((group[0], set(group[1])))
        return held, page, done

    async def _finish_group(self, group: _Group) -> None:
        """Page a group to the size it states, or leave it unread by choice."""
        if self._unwanted(group):
            # Its first postings are already listed; the rest are at a place
            # the caller cannot keep, so they are left unread.
            self.unread_by_choice += group.stated - len(group.postings)
            return
        bound_fired = await self._complete_group(group)
        if not bound_fired and len(group.postings) < group.stated:
            # The group states its size, so the postings its route never served
            # are a known number, not an unknown slice of the board: a counted
            # loss, weighed against what was read like any dropped record.
            self.drift.records_unaccounted(
                group.stated - len(group.postings),
                "group lists fewer postings than it states",
                group=group.label, stated=group.stated, listed=len(group.postings),
            )

    def _unwanted(self, group: _Group) -> bool:
        """A location group with more pages that the caller does not want."""
        return (
            self.wanted_place is not None
            and group.more is not None
            and group.more[1] == "location"
            and len(group.postings) < group.stated
            and not self.wanted_place(group.label)
        )

    def _group_jobs(self, groups: list[_Group]) -> Iterator[RawJob]:
        """Merge every completed group, including a partly expanded last group."""
        by_place = board_grouping(groups, self._known_grouping) == "location"
        postings: dict[str, _Posting] = {}
        for group in groups:
            for posting in group.postings.values():
                known = postings.setdefault(posting.posting_id, posting)
                place = group.label if by_place else posting.detail
                if place and place not in known.places:
                    known.places.append(place)
        for posting in postings.values():
            employment = posting.detail if by_place else None
            places = [
                SourceLocation(label=label, is_primary=i == 0)
                for i, label in enumerate(p for p in (clean_location(x) for x in posting.places) if p)
            ]
            job = RawJob(
                company=self.company,
                req_id=posting.posting_id,
                title=posting.title,
                url=posting.url,
                locations=[place.label for place in places],
                # The body is on the posting's page; `hydrate` reads it for
                # kept postings only.
                description_complete=False,
                source_facts=self._facts(
                    posting.posting_id,
                    access_surface=AccessSurface.HTML,
                    employment_type_raw=employment,
                    employment_type_normalized=_employment(employment),
                    locations=places,
                ),
            )
            self.keep_held_places(job)
            yield job

    async def _complete_group(self, group: _Group) -> bool:
        """Page a group's more-route until it lists what it states.

        Stops on a page that did not answer (the listing is invalid), on a page
        that adds nothing (the route ran dry: the caller counts the shortfall
        as the source's) or on the page ceiling, which is
        OUR bound: it marks the listing truncated and returns True so the
        shortfall is not also blamed on the source.
        """
        if group.more is None or len(group.postings) >= group.stated:
            return False
        path, kind, value, page = group.more
        for _ in range(self.page_budget("more", _MAX_MORE_PAGES)):
            if len(group.postings) >= group.stated:
                return False
            resp = await self.context.fetch(
                FetchRequest(
                    url=f"https://{BOARD_HOST}{path}",
                    # A link naming no type is requested as `location`; only
                    # the grouping does not assume it.
                    query={"type": kind or "location", "value": value, "page": page},
                    source_key=self.company,
                )
            )
            if resp.status != 200:
                # A page that did not answer may have held any of the rest.
                self.drift.invalidate_listing(
                    "group page answered non-200", group=group.label, status=resp.status, page=page,
                )
                return False
            new = {k: v for k, v in parse_more(resp.text()).items() if k not in group.postings}
            if not new:
                return False
            group.postings.update(new)
            page += 1
        if len(group.postings) < group.stated:
            self.truncated = True
            return True
        return False

    async def hydrate(self, job: RawJob) -> None:
        # HTML, asked for by name. The posting host negotiates: our default
        # `Accept` prefers JSON, and it then answers an undocumented JSON form
        # without the structured address or workplace type (and with the
        # recruiter's name, which we have no use for).
        resp = await self.context.fetch(
            FetchRequest(url=job.url, headers={"Accept": _HTML_ACCEPT}, source_key=self.company)
        )
        if resp.status != 200:
            self.drift.note("posting page failed", req=job.req_id, status=resp.status)
            return
        page = parse_job_page(resp.text())
        if page.description_html is None:
            self.drift.note("posting page carried no description microdata", req=job.req_id)
        job.description_html = page.description_html
        job.description_complete = bool(page.description_html)
        job.posted_at = page.posted_at or job.posted_at
        if page.workplace is not WorkplaceType.UNKNOWN:
            job.workplace_type = page.workplace
        if job.source_facts is not None:
            job.source_facts = replace(
                job.source_facts,
                first_published_at=page.posted_at,
                employment_type_raw=page.employment or job.source_facts.employment_type_raw,
                employment_type_normalized=_employment(page.employment)
                if page.employment
                else job.source_facts.employment_type_normalized,
                locations=[page.place] if page.place is not None else job.source_facts.locations,
            )
        if page.place is not None and page.place.label not in job.locations:
            job.locations = [page.place.label, *job.locations]


class SmartRecruitersApiAdapter(_SmartRecruitersBase):
    """The documented Posting API — walled, used only when the board is not on
    SmartRecruiters and the user consented. See the module docstring."""

    name = "smartrecruiters_api"
    posted_date = "published"  # `releasedDate`
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: The Posting API states `totalFound`. The
    #: BOARD route does not: its count is a presence check, not the board's
    #: size, and its completeness is per group.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url=_API_POSTINGS + "?limit=1",
        tenants=_TENANTS,
        identity_url=_API_COMPANY,
        counts_whole_board=False,
    )

    async def fetch(self) -> AsyncIterator[RawJob]:
        # The unwalled board wins whenever the company publishes one again.
        published, _, _, _ = await self._board_root()
        if published is True:
            raise RouteMoved(
                self.name,
                "smartrecruiters",
                f"{self.company!r} publishes its board on SmartRecruiters again;"
                " moving it back to the board route",
            )

        total: int | None = None
        seen: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total
            resp = await self.context.fetch(
                FetchRequest(
                    url=_API_POSTINGS.format(token=self._token()),
                    query={"limit": _API_PAGE_SIZE, "offset": index * _API_PAGE_SIZE},
                    source_key=self.company,
                )
            )
            if resp.status != 200:
                self.drift.invalidate_listing("postings page failed", page=index, status=resp.status)
                stop()
                return []
            data = resp.json()
            content = data.get("content") if isinstance(data, dict) else None
            if not isinstance(data, dict) or not isinstance(content, list):
                self.drift.invalidate_listing("postings page has no 'content' array", page=index)
                stop()
                return []
            if total is None and isinstance(data.get("totalFound"), int):
                total = data["totalFound"]
            if total is not None and (index + 1) * _API_PAGE_SIZE >= total:
                stop()
            return content

        async for item in self.paged_listing(
            fetch_page,
            max_pages=_MAX_API_PAGES,
            query_key="postings",
            declared_total=lambda: total,
            page_size=_API_PAGE_SIZE,
        ):
            job = self._job(item)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        self.close_listing(declared=total, unique=len(seen), field="totalFound")

    def _job(self, item: object) -> RawJob | None:
        if not isinstance(item, dict):
            self.drift.drop_record("posting is not an object")
            return None
        posting_id, title = text_of(item.get("id")), text_of(item.get("name"))
        if not posting_id or not title:
            self.drift.drop_record("posting missing id/name", keys=list(item)[:8])
            return None
        location = _object(item.get("location"))
        locality, region, country = (
            text_of(location.get("city")), text_of(location.get("region")), text_of(location.get("country")),
        )
        label = clean_location(
            text_of(location.get("fullLocation")) or ", ".join(p for p in (locality, region, country) if p)
        )
        places = [SourceLocation(label=label, country=country, region=region, locality=locality, is_primary=True)] if label else []
        kind = _object(item.get("typeOfEmployment"))
        department = _object(item.get("department"))
        level = _object(item.get("experienceLevel"))
        posted = parse_datetime(item.get("releasedDate"))
        return RawJob(
            company=self.company,
            req_id=posting_id,
            title=title,
            url=f"https://{_JOB_HOST}/{self._token()}/{posting_id}",
            locations=[p.label for p in places],
            department=text_of(department.get("label")),
            description_complete=False,
            workplace_type=WorkplaceType.REMOTE if location.get("remote") is True else WorkplaceType.UNKNOWN,
            posted_at=posted,
            raw_level=text_of(level.get("label")),
            source_facts=self._facts(
                posting_id,
                access_surface=AccessSurface.PUBLIC_API,
                requisition_label=text_of(item.get("refNumber")),
                first_published_at=posted,
                employment_type_raw=text_of(kind.get("label")),
                employment_type_normalized=_employment(text_of(kind.get("label"))),
                locations=places,
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        resp = await self.context.fetch(
            FetchRequest(url=f"{_API_POSTINGS.format(token=self._token())}/{job.req_id}", source_key=self.company)
        )
        if resp.status != 200:
            self.drift.note("posting detail failed", req=job.req_id, status=resp.status)
            return
        data = resp.json()
        sections = ((data.get("jobAd") or {}).get("sections") or {}) if isinstance(data, dict) else {}
        parts = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key) if isinstance(sections, dict) else None
            if isinstance(section, dict) and text_of(section.get("text")):
                parts.append(f"<h2>{section.get('title') or key}</h2>{section['text']}")
        job.description_html = "".join(parts) or None
        job.description_complete = bool(parts)
        url = text_of(data.get("postingUrl")) if isinstance(data, dict) else None
        if url:
            job.url = url
