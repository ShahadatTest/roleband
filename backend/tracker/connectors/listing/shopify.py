"""Shopify: its own careers page, from the data the page streams.

    GET https://www.shopify.com/careers
    GET https://www.shopify.com/careers/{slug}_{posting id}

Shopify hires through Ashby but publishes no Ashby job board (the `shopify`
board answers 404); its careers page is a React Router page whose loader data
(`extract.turbo_stream`) holds every listed posting. The page's HTML renders
only some of them, so the HTML is not the listing; the stream is.

The stream carries the list in one of two shapes, and the adapter reads
whichever the page sends:

* `roles`: one summary per opening (id, title, link, discipline, and places
  written "Remote - Ireland"). The posting page supplies the date, the
  employment type and the description.
* `jobPostingsWithJobs` with the tenant's location table: Ashby's internal
  record per row, the posting (title, team, location ids, workplace,
  employment type, published date) and its job, which also carries the hiring
  team's names and emails.

**Only named fields are read.** Names and emails are never read, kept or
logged; the adapter builds its `RawJob` from an allowlist and hands no raw row
onward.

**Complete means the page decoded.** The page states no total and pages
nothing: one response is the listing, as Atlassian's is. A page whose stream
does not decode, or holds neither list, invalidates the listing.

**Places.** A summary's place is the text after its "Remote - " (or "Hybrid - ",
"Onsite - ") prefix, and the prefix is the workplace. An Ashby record names a
primary location and secondary ones by id; the location table resolves each
to a name and a postal address. A location with a city is written "City,
Region, Country"; otherwise its name ("Ireland", "Americas"). A posting that
names only "Americas" (remote) counts as the Americas' regions and countries.

**Detail.** The posting page streams the posting's Ashby record with
`descriptionHtml`, `publishedDate` and `employmentType`. No pay is published
(`compensation.shouldDisplayCompensation` false throughout).

Robots (`www.shopify.com/robots.txt`) allows `/careers` and the posting pages;
it disallows `/careers/search?*`, `/careers/portal/*`, any `page=` or
`country=` query and `*.data`, none of which is requested.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from tracker.connectors.extract.payload import text_of
from tracker.connectors.extract.turbo_stream import loader_data
from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.connectors.sdk import Capabilities, FetchRequest
from tracker.platform.util import clean_location
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

CAREERS_URL = "https://www.shopify.com/careers"
POSTING_URL = "https://www.shopify.com/careers/{slug}_{id}"
_LIST_ROUTE = "($locale)/careers"
_POSTING_ROUTE = "($locale)/careers/$posting"
_TENANTS = TenantMap({})
_SLUG = re.compile(r"[^a-z0-9]+")
_PLACE = re.compile(r"^\s*(remote|hybrid|on-?site)\s+-\s+(.+)$", re.IGNORECASE)
_WORKPLACE = {"remote": WorkplaceType.REMOTE, "hybrid": WorkplaceType.HYBRID, "onsite": WorkplaceType.ONSITE}
_EMPLOYMENT = {"fulltime": EmploymentType.FULL_TIME, "parttime": EmploymentType.PART_TIME,
               "contract": EmploymentType.CONTRACT, "intern": EmploymentType.INTERN,
               "temporary": EmploymentType.TEMPORARY}
_ROLE_PATH = "/careers/"


def _string(value: object) -> str | None:
    """A field the page states as a string, read as `text_of` reads it; any
    other value is no text. The stream decodes references, so a field can
    hold an object, even one that contains itself, and its repr is never a
    team, a title or an id."""
    return text_of(value) if isinstance(value, str) else None


def slug(title: str) -> str:
    """The page's own slug: lowercase words joined by hyphens (the id decides)."""
    return _SLUG.sub("-", title.lower()).strip("-") or "posting"


def location_label(location: Mapping) -> str | None:
    """A city location as "City, Region, Country"; any other by its name."""
    address = location.get("address")
    postal = address.get("postalAddress") if isinstance(address, Mapping) else None
    if isinstance(postal, Mapping) and _string(postal.get("addressLocality")):
        parts = [_string(postal.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")]
        return clean_location(", ".join(p for p in parts if p))
    name = _string(location.get("name"))
    return clean_location(name) if name else None


def role_place(label: str) -> tuple[str | None, WorkplaceType]:
    """A summary's place and workplace: "Remote - Ireland" is Ireland, remote."""
    match = _PLACE.match(label)
    if match is None:
        return clean_location(label) or None, WorkplaceType.UNKNOWN
    mode = match.group(1).lower().replace("-", "")
    return clean_location(match.group(2)) or None, _WORKPLACE.get(mode, WorkplaceType.UNKNOWN)


def _published(posting: Mapping) -> datetime | None:
    published = _string(posting.get("publishedDate"))
    try:
        return datetime.strptime(published, "%Y-%m-%d").replace(tzinfo=UTC) if published else None
    except ValueError:
        return None


def _posting_list(data: Mapping | None) -> list | None:
    """The page's list in either shape, or None when it streams neither."""
    for key in ("roles", "jobPostingsWithJobs"):
        rows = data.get(key) if data else None
        if isinstance(rows, list):
            return rows
    return None


def count_postings(page: str) -> int | None:
    """Listed postings in a careers page's stream (the probe's count)."""
    rows = _posting_list(loader_data(page, _LIST_ROUTE))
    return len(rows) if rows is not None else None


class ShopifyAdapter(BaseAdapter):
    name = "shopify"
    posted_date = "published"  # the posting's published day
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: The page states no total; the one response is the listing.
    declares_total = False
    board_probe = BoardProbe(
        jobs_url=CAREERS_URL,
        tenants=_TENANTS,
        tenant_url=lambda _token: CAREERS_URL,
        read_count=count_postings,
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    async def fetch(self) -> AsyncIterator[RawJob]:
        resp = await self.context.fetch(FetchRequest(url=CAREERS_URL, source_key=self.company))
        if resp.status != 200:
            self.drift.invalidate_listing("careers page failed", status=resp.status)
            return
        data = loader_data(resp.text(), _LIST_ROUTE)
        roles = data.get("roles") if data else None
        rows = data.get("jobPostingsWithJobs") if data else None
        if isinstance(roles, list):
            for found in self._roles(roles):
                yield found
            return
        if not isinstance(rows, list):
            self.drift.invalidate_listing("careers page streamed no posting list")
            return
        table = data.get("atsLocations") if data else None
        locations = {
            loc["id"]: loc for loc in (table if isinstance(table, list) else [])
            if isinstance(loc, Mapping) and isinstance(loc.get("id"), str)
        }
        seen: set[str] = set()
        unlisted = 0
        for row in rows:
            posting = row.get("jobPosting") if isinstance(row, Mapping) else None
            if not isinstance(posting, Mapping):
                self.drift.drop_record("row without a posting")
                continue
            if posting.get("isListed") is False:
                unlisted += 1
                continue
            job = self._job(posting, locations)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        if not seen and unlisted == len(rows):
            # The decoded list is present and holds nothing public: the board's
            # own statement that it lists nothing. One
            # company's page, so no other tenant can answer this way.
            self.drift.board_empty("posting list streamed with no listed posting", unlisted=unlisted)
            return
        self.drift.require(bool(seen), "empty job list")

    def _roles(self, roles: list) -> Iterator[RawJob]:
        seen: set[str] = set()
        for role in roles:
            if not isinstance(role, Mapping):
                self.drift.drop_record("role that is not a record")
                continue
            job = self._role(role)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        if not roles:
            # The decoded list is present and holds nothing: the board's own
            # statement that it lists nothing.
            self.drift.board_empty("role list streamed empty", unlisted=0)
            return
        self.drift.require(bool(seen), "empty job list")

    def _role(self, role: Mapping) -> RawJob | None:
        role_id, title = _string(role.get("id")), _string(role.get("title"))
        if not role_id or not title:
            self.drift.drop_record("role without id or title", req=role_id)
            return None
        stated = role.get("locations")
        if not isinstance(stated, list) or not stated:
            stated = [role.get("location")]
        labels: list[str] = []
        modes: set[WorkplaceType] = set()
        for raw in stated:
            text = _string(raw)
            if not text:
                continue
            label, mode = role_place(text)
            modes.add(mode)
            if label and label not in labels:
                labels.append(label)
        href = _string(role.get("href"))
        url = (CAREERS_URL.removesuffix("/careers") + href if href and href.startswith(_ROLE_PATH)
               else POSTING_URL.format(slug=slug(title), id=role_id))
        return RawJob(
            company=self.company,
            req_id=role_id,
            title=title,
            url=url,
            locations=labels,
            department=_string(role.get("discipline")),
            workplace_type=modes.pop() if len(modes) == 1 else WorkplaceType.UNKNOWN,
            description_complete=False,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity="shopify.com",
                posting_id=role_id,
                locations=[SourceLocation(label=label, is_primary=i == 0) for i, label in enumerate(labels)],
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    def _job(self, posting: Mapping, locations: Mapping[str, Mapping]) -> RawJob | None:
        posting_id, title = _string(posting.get("id")), _string(posting.get("title"))
        if not posting_id or not title:
            self.drift.drop_record("posting without id or title", req=posting_id)
            return None
        ids = posting.get("locationIds")
        if not isinstance(ids, Mapping):
            ids = {}
        refs = [ids.get("primaryLocationId"), *(ids.get("secondaryLocationIds") or [])]
        labels: list[str] = []
        for ref in refs:
            label = location_label(locations[ref]) if isinstance(ref, str) and ref in locations else None
            if label and label not in labels:
                labels.append(label)
        named = clean_location(_string(posting.get("locationName")))
        if not labels and named:
            labels.append(named)
        employment = _string(posting.get("employmentType"))
        posted = _published(posting)
        return RawJob(
            company=self.company,
            req_id=posting_id,
            title=title,
            url=POSTING_URL.format(slug=slug(title), id=posting_id),
            locations=labels,
            department=_string(posting.get("teamName")),
            workplace_type=_WORKPLACE.get((_string(posting.get("workplaceType")) or "").lower(),
                                          WorkplaceType.UNKNOWN),
            posted_at=posted,
            description_complete=False,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity="shopify.com",
                posting_id=posting_id,
                source_job_id=_string(posting.get("jobId")),
                first_published_at=posted,
                employment_type_raw=employment,
                employment_type_normalized=_EMPLOYMENT.get((employment or "").lower(), EmploymentType.UNKNOWN),
                locations=[SourceLocation(label=label, is_primary=i == 0) for i, label in enumerate(labels)],
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page failed", req=job.req_id, status=resp.status)
            return
        data = loader_data(resp.text(), _POSTING_ROUTE)
        posting = data.get("jobPosting") if data else None
        if not isinstance(posting, Mapping):
            posting = {}
        body = _string(posting.get("descriptionHtml"))
        if body is None:
            self.drift.note("posting page streamed no description", req=job.req_id)
            return
        job.description_html = body
        job.description_complete = True
        # A `roles` summary states no date, employment type or workplace; the
        # posting's own record does. What the listing already stated stands.
        posted = _published(posting)
        job.posted_at = job.posted_at or posted
        if job.workplace_type is WorkplaceType.UNKNOWN:
            job.workplace_type = _WORKPLACE.get((_string(posting.get("workplaceType")) or "").lower(),
                                                WorkplaceType.UNKNOWN)
        facts = job.source_facts
        if facts is not None and facts.employment_type_raw is None:
            employment = _string(posting.get("employmentType"))
            job.source_facts = replace(
                facts,
                source_job_id=facts.source_job_id or _string(posting.get("jobId")),
                first_published_at=facts.first_published_at or posted,
                employment_type_raw=employment,
                employment_type_normalized=_EMPLOYMENT.get((employment or "").lower(), EmploymentType.UNKNOWN),
            )
