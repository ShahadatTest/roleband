"""Jibe career sites — multi-tenant.

    GET https://{host}/api/jobs?page=N&limit=100

Jibe (iCIMS' hosted career-site layer) serves each tenant from the tenant's
own careers host, detected only by a `jibeapply` page marker. Token = that
host — GitHub: `www.github.careers`, Booking: `jobs.booking.com`. Pacing and
the breaker are per tenant.

**Listing.** One JSON route answers the whole board, 100 rows a page (a larger
`limit` is refused), each row `{"data": {...}}` with the full description
inline, so there is no detail request. `totalCount` states the board; a page
past the end answers `[]` with the same total.

**Completeness.** A row is keyed by `(req_id, language)`: a tenant publishing
a posting in two languages counts it twice in `totalCount` (`languageCounts`),
so unique keys below the total — rows repeating across pages — invalidate,
and the posting is yielded once.

**Fields.** `full_location` joins every place with "; " (Booking's "Lisbon,
Portugal; Faro, Portugal; Porto, Portugal"). `location_name` is the tenant's
own label ("US Remote", "Amsterdam Campus"), read only for "remote". GitHub
splits the body into `description`, `responsibilities` and `qualifications`;
all three are the description, in that order. `hiring_organization` names the
employer ("GitHub, Inc."; Booking's board carries "Booking.com" and "Booking
Holdings"). `salary_*` are zero: pay sits in the description text. `apply_url`
is the iCIMS tenant, never requested.

Tenant robots files allow `/` with `crawl-delay: 5`.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from tracker.connectors.extract.payload import text_of
from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap, require_tenant_host
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
_PAGE = 100
_MAX_PAGES = 50
_BODY = ("description", "responsibilities", "qualifications")
_EMPLOYMENT = {
    "FULL_TIME": EmploymentType.FULL_TIME,
    "PART_TIME": EmploymentType.PART_TIME,
    "CONTRACTOR": EmploymentType.CONTRACT,
    "INTERN": EmploymentType.INTERN,
    "TEMPORARY": EmploymentType.TEMPORARY,
}


def jobs_url(host: str) -> str:
    host = host.strip().strip("/")
    if not host or "/" in host or "|" in host:
        raise ValueError(f"jibe board_token must be the careers host, got {host!r}")
    return f"https://{host}/api/jobs"


def _payload(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def declared_total(text: str) -> int | None:
    data = _payload(text)
    total = data.get("totalCount") if data is not None else None
    return total if isinstance(total, int) else None


def stated_employer(text: str) -> str | None:
    """The employer most of the page's rows name (a board can carry a parent
    brand beside its own: Booking's board has both "Booking.com" and "Booking
    Holdings" rows)."""
    data = _payload(text)
    rows = data.get("jobs") if data is not None else None
    names = Counter(
        str(row["data"]["hiring_organization"]).strip()
        for row in rows or []
        if isinstance(row, dict) and isinstance(row.get("data"), dict) and row["data"].get("hiring_organization")
    )
    return names.most_common(1)[0][0] if names else None


class JibeAdapter(BaseAdapter):
    name = "jibe"
    posted_date = "published"  # `posted_date`
    #: `/api/jobs` states `totalCount` on every page.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url="https://{token}/api/jobs",
        tenants=_TENANTS,
        tenant_url=lambda token: jobs_url(token) + f"?page=1&limit={_PAGE}",
        identity_url="https://{token}/api/jobs?page=1&limit=100",
        read_count=declared_total,
        read_identity=stated_employer,
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)
    #: The tenant is the host its careers page is served from, which a pasted
    #: page can choose: every request, redirect hops included, stays on that
    #: host at a pinned public address.
    public_only = True

    @property
    def host(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token).strip().strip("/")

    def validate_destination(self, url: str) -> None:
        require_tenant_host(url, self.host)

    async def fetch(self) -> AsyncIterator[RawJob]:
        # Policy before configuration: a refused company is refused as such.
        self.access.require()
        host = self.host
        url = jobs_url(host)
        total: int | None = None
        listed = 0
        keys: set[tuple[str, str]] = set()
        seen: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list:
            nonlocal total, listed
            resp = await self.context.fetch(FetchRequest(
                url=url, query={"page": index + 1, "limit": _PAGE}, source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("jobs page failed", page=index + 1, status=resp.status)
                stop()
                return []
            data = _payload(resp.text())
            rows = data.get("jobs") if data is not None else None
            if data is None or not isinstance(rows, list):
                self.drift.invalidate_listing("jobs page has no jobs array", page=index + 1)
                stop()
                return []
            # The board's total is page 1's statement; a later page restating
            # it is not evidence the first one made.
            if index == 0 and isinstance(data.get("totalCount"), int):
                total = data["totalCount"]
            listed += len(rows)
            # Rows listed, not pages times the page size: a short page is not
            # the end while the total is unreached, and an empty one always is.
            if not rows or (total is not None and listed >= total):
                stop()
            return rows

        async for row in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key="jobs", declared_total=lambda: total, page_size=_PAGE,
        ):
            data = row.get("data") if isinstance(row, dict) else None
            if not isinstance(data, dict):
                self.drift.drop_record("row has no data object")
                continue
            req_id = text_of(data.get("req_id")) or text_of(data.get("slug"))
            if req_id is not None:
                keys.add((req_id, text_of(data.get("language")) or ""))
            if req_id in seen:
                continue
            job = self._job(data, host)
            if job is None:
                continue
            seen.add(job.req_id)
            yield job

        if not seen and not listed and total == 0 and self.drift.listing_complete:
            # Page 1 stated a total of 0 and served its `jobs` array empty: the
            # board itself says it lists nothing.
            self.drift.board_empty("totalCount 0 and an empty jobs array")
        else:
            self.drift.require(bool(seen), "empty job list")
        # Keyed by (req_id, language): one posting in three languages is three
        # rows of the board's own count, and one job.
        self.close_listing(declared=total, unique=len(keys), field="totalCount")

    def _job(self, data: dict, host: str) -> RawJob | None:
        req_id, title = text_of(data.get("req_id")) or text_of(data.get("slug")), text_of(data.get("title"))
        if not req_id or not title:
            self.drift.drop_record("row missing req_id/title", keys=list(data)[:8])
            return None
        places: list[SourceLocation] = []
        for raw in (text_of(data.get("full_location")) or text_of(data.get("short_location")) or "").split(";"):
            label = clean_location(raw) if raw.strip() else None
            if label and all(label != p.label for p in places):
                places.append(SourceLocation(label=label, country=text_of(data.get("country")), is_primary=not places))
        body = "".join(str(data[k]) for k in _BODY if isinstance(data.get(k), str) and data[k].strip())
        canonical = text_of((data.get("meta_data") or {}).get("canonical_url")) if isinstance(
            data.get("meta_data"), dict) else None
        # The tenant's own posting URL; Jibe's canonical can name its own host
        # (githubinc.jibeapply.com), and `/jobs/{id}` on the careers host
        # redirects to the tenant's path.
        url = canonical if canonical and urlsplit(canonical).hostname == host else f"https://{host}/jobs/{req_id}"
        categories = data.get("category") if isinstance(data.get("category"), list) else []
        employment = text_of(data.get("employment_type"))
        remote = "remote" in (text_of(data.get("location_name")) or "").lower()
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=[p.label for p in places],
            department=text_of(categories[0]) if categories else None,
            description_html=body or None,
            description_complete=bool(body),
            workplace_type=WorkplaceType.REMOTE if remote else WorkplaceType.UNKNOWN,
            posted_at=parse_datetime(data.get("posted_date")),
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity=text_of(data.get("client_code")) or host,
                posting_id=req_id,
                source_updated_at=parse_datetime(data.get("update_date")),
                employment_type_raw=employment,
                employment_type_normalized=_EMPLOYMENT.get(employment or "", EmploymentType.UNKNOWN),
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )
