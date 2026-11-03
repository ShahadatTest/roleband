"""Oracle Cloud HCM Candidate Experience — multi-tenant.

    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&expand=requisitionList.secondaryLocations
        &finder=findReqs;siteNumber={site},limit=200,offset=N,sortBy=POSTING_DATES_DESC
    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
        ?expand=all&onlyData=true&finder=ById;Id="{id}",siteNumber={site}

The public REST API behind every tenant's Candidate Experience site
(`{host}/hcmUI/CandidateExperience/en/sites/{site}`). The token is `host|site`
(Fortinet: `edel.fa.us2.oraclecloud.com|CX_2001`): each tenant is its own
deployment, so pacing and the breaker are per tenant.

**Paging.** `limit`/`offset` go INSIDE the `finder` clause; outside it they
are silently ignored and page 1 repeats forever. A page size of 200 is
honoured.

**Completeness.** `TotalJobsCount` declares the board. A tenant can declare
more postings than any sort order or page size lists, stably: the
workplace-type facets each list exactly their count, and the shortfall is a
posting with no workplace type, apparently counted by the search index and
listable by no route. That explanation is NOT closure evidence: equal counts
cannot name the missing requisition, and a missing typed posting plus a listed
untyped one satisfy the same equality. Every shortfall goes through
`close_listing`, so such a board is `lossy`: not a pathology, closure withheld.
`typed` rides along as diagnostic evidence.

**Detail.** The listing has no description; `hydrate()` (kept postings only)
reads `ExternalDescriptionStr` (+ responsibilities/qualifications/corporate
blocks when a tenant fills them), the workplace type and the category. The
detail also carries recruiter contact fields; they are never read.

`robots.txt` on the tenant host answers a plain 404:
no file is served, so nothing restricts the route and it is not walled.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
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

_TENANTS = TenantMap({})
_API = "https://{host}/hcmRestApi/resources/latest"
_PAGE_SIZE = 200
#: Seed for the learned page budget, with headroom over a large tenant at 200 a page.
_MAX_PAGES = 50
_WORKPLACE = {
    "on-site": WorkplaceType.ONSITE,
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
}
#: Description blocks a tenant may fill, in display order.
_DETAIL_BLOCKS = (
    "ExternalDescriptionStr",
    "ExternalResponsibilitiesStr",
    "ExternalQualificationsStr",
    "CorporateDescriptionStr",
    "OrganizationDescriptionStr",
)


@dataclass(frozen=True)
class OracleTenant:
    host: str
    site: str

    def list_url(self) -> str:
        return f"{_API.format(host=self.host)}/recruitingCEJobRequisitions"

    def detail_url(self) -> str:
        return f"{_API.format(host=self.host)}/recruitingCEJobRequisitionDetails"

    def finder(self, offset: int, limit: int = _PAGE_SIZE) -> str:
        return (
            f"findReqs;siteNumber={self.site},limit={limit},offset={offset},"
            "sortBy=POSTING_DATES_DESC"
        )

    def posting_url(self, posting_id: str) -> str:
        return f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.site}/job/{posting_id}"


def parse_tenant(token: str) -> OracleTenant:
    parts = token.split("|")
    if len(parts) != 2 or not all(p.strip() for p in parts):
        raise ValueError(f"oracle board_token must be 'host|site', got {token!r}")
    return OracleTenant(parts[0].strip(), parts[1].strip())


def first_page_query(tenant: OracleTenant, offset: int = 0) -> dict[str, str]:
    return {
        "onlyData": "true",
        "expand": "requisitionList.secondaryLocations",
        "finder": tenant.finder(offset),
    }


def probe_url(tenant: OracleTenant) -> str:
    """Exactly the adapter's first request (a composite probe is
    proven by doing it). Its `TotalJobsCount` sizes the whole board."""
    return str(httpx.URL(tenant.list_url(), params=first_page_query(tenant)))


def search_body(text: str) -> dict | None:
    """The one search result the listing wraps everything in, or None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    return items[0]


def declared_total(text: str) -> int | None:
    """`TotalJobsCount`, for the token checker (the whole board's size)."""
    body = search_body(text)
    total = body.get("TotalJobsCount") if body else None
    return total if isinstance(total, int) else None


def typed_total(body: dict) -> int | None:
    """Postings the workplace-type facets account for, or None when unused."""
    facets = body.get("workplaceTypesFacet")
    if not isinstance(facets, list) or not facets:
        return None
    counts = [f.get("TotalCount") for f in facets if isinstance(f, dict)]
    return sum(c for c in counts if isinstance(c, int)) or None


def _places(row: dict) -> list[SourceLocation]:
    names = [row.get("PrimaryLocation")]
    for extra in row.get("secondaryLocations") or []:
        if isinstance(extra, dict):
            names.append(extra.get("Name"))
    places: list[SourceLocation] = []
    for name in names:
        label = clean_location(str(name)) if name else None
        if label and all(label != p.label for p in places):
            places.append(SourceLocation(label=label, is_primary=not places))
    return places


class OracleAdapter(BaseAdapter):
    name = "oracle"
    posted_date = "published"  # `PostedDate`, then `ExternalPostedStartDate`
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: `TotalJobsCount` sizes the board. A posting the index counts and no
    #: route lists is accounted for by `typed` below, not by dropping the rule.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url="https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber={site}",
        tenants=_TENANTS,
        tenant_url=lambda token: probe_url(parse_tenant(token)),
        # The probe asks for one row but the answer states the whole board.
        read_count=declared_total,
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    @property
    def tenant(self) -> OracleTenant:
        return parse_tenant(_TENANTS.resolve(self.company, self.board_token))

    async def fetch(self) -> AsyncIterator[RawJob]:
        # Policy before configuration: a refused company is refused as such,
        # never reported as a malformed token.
        self.access.require()
        tenant = self.tenant
        total: int | None = None
        typed: int | None = None
        seen: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total, typed
            resp = await self.context.fetch(FetchRequest(
                url=tenant.list_url(),
                query=first_page_query(tenant, index * _PAGE_SIZE),
                source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("requisitions page failed", page=index, status=resp.status)
                stop()
                return []
            body = search_body(resp.text())
            rows = body.get("requisitionList") if body else None
            if not body or not isinstance(rows, list):
                self.drift.invalidate_listing("requisitions page has no requisitionList", page=index)
                stop()
                return []
            if total is None and isinstance(body.get("TotalJobsCount"), int):
                total, typed = body["TotalJobsCount"], typed_total(body)
            if total is not None and (index + 1) * _PAGE_SIZE >= total:
                stop()
            return rows

        async for row in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key="requisitions",
            declared_total=lambda: total, page_size=_PAGE_SIZE,
        ):
            job = self._job(row, tenant)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job

        if not seen and total == 0 and self.drift.listing_complete:
            # The site stated TotalJobsCount 0 and served its requisitionList
            # empty. An unknown site answers the host's other listing rather
            # than 0, so 0 is this site's own answer.
            self.drift.board_empty("TotalJobsCount 0 and an empty requisitionList")
        else:
            self.drift.require(bool(seen), "empty job list")
        # Facet counts explain a discrepancy, but cannot identify an unread
        # requisition. Every shortfall withholds closure through the same gate.
        self.close_listing(
            declared=total, unique=len(seen), field="TotalJobsCount", typed=typed,
        )

    def _job(self, row: object, tenant: OracleTenant) -> RawJob | None:
        if not isinstance(row, dict):
            self.drift.drop_record("requisition is not an object")
            return None
        posting_id = str(row.get("Id") or "").strip()
        title = (row.get("Title") or "").strip()
        if not posting_id or not title:
            self.drift.drop_record("requisition missing Id/Title", keys=list(row)[:8])
            return None
        places = _places(row)
        posted = parse_datetime(row.get("PostedDate"))
        return RawJob(
            company=self.company,
            req_id=posting_id,
            title=title,
            url=tenant.posting_url(posting_id),
            locations=[p.label for p in places],
            description_complete=False,
            posted_at=posted,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity=f"{tenant.host}|{tenant.site}",
                posting_id=posting_id,
                first_published_at=posted,
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        tenant = self.tenant
        resp = await self.context.fetch(FetchRequest(
            url=tenant.detail_url(),
            query={
                "expand": "all",
                "onlyData": "true",
                "finder": f'ById;Id="{job.req_id}",siteNumber={tenant.site}',
            },
            source_key=self.company,
        ))
        if resp.status != 200:
            self.drift.note("requisition detail failed", req=job.req_id, status=resp.status)
            return
        detail = search_body(resp.text())
        if detail is None:
            self.drift.note("requisition detail has no item", req=job.req_id)
            return
        blocks = [detail.get(k) for k in _DETAIL_BLOCKS]
        body = "".join(b for b in blocks if isinstance(b, str) and b.strip())
        job.description_html = body or None
        job.description_complete = bool(body)
        workplace = _WORKPLACE.get(str(detail.get("WorkplaceType") or "").strip().lower())
        if workplace is not None:
            job.workplace_type = workplace
        category = detail.get("Category")
        if isinstance(category, str) and category.strip():
            job.department = category.strip()
        started = parse_datetime(detail.get("ExternalPostedStartDate"))
        if started is not None:
            job.posted_at = started
        schedule = str(detail.get("JobSchedule") or "").strip()
        if job.source_facts is not None and schedule:
            job.source_facts = replace(
                job.source_facts,
                employment_type_raw=schedule,
                employment_type_normalized=(
                    EmploymentType.FULL_TIME if schedule.lower() == "full time"
                    else EmploymentType.PART_TIME if schedule.lower() == "part time"
                    else EmploymentType.UNKNOWN
                ),
                first_published_at=started or job.source_facts.first_published_at,
            )
