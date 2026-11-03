"""Eightfold AI careers sites — every tenant, on either of Eightfold's two APIs.

A tenant is `"{host}|{domain}"`, or `"{host}|{domain}|pcsx"` for a tenant on
Eightfold's newer careers product. The two are different APIs, not
two spellings of one, and a tenant answers exactly one of them:

    v2   GET https://{host}/api/apply/v2/jobs?domain={domain}&start=N&num=10
         -> {"count", "positions": [...]}   detail: /api/apply/v2/jobs/{id}
    pcsx GET https://{host}/api/pcsx/search?domain={domain}&start=N
         -> {"data": {"count", "positions": [...]}}
         detail: /api/pcsx/position_details?position_id={id}&domain={domain}

A PCSX tenant answers the v2 route with 403 "Not authorized for PCSX". The
dialect is stated
in the token rather than detected, so a run never spends a failing request
finding out, and a tenant that moves between products shows up as a 403 — a
source change — instead of a silent fallback. Tenant hosts serve the same
robots template, allowing both `/api/apply` and `/api/pcsx`.

Both APIs cap a page at 10 and paginate by `start` until `start >= count`. The
list omits descriptions; `hydrate()` fetches them per job for keepers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import RawJob, WorkplaceType

#: Built-in Eightfold companies: slug -> tenant token. A DB-added company
#: overrides it through `board_token` without a code change.
EIGHTFOLD_TENANTS: dict[str, str] = {
    "netflix": "explore.jobs.netflix.net|netflix.com",
}
_TENANTS = TenantMap(EIGHTFOLD_TENANTS)

_PAGE = 10  # server cap on both APIs
# The hard ceiling the learned per-binding bound can grow into, so it sits well
# above the largest tenant rather than at it.
_MAX_PAGES = 400
# Sort order per pass, keyed by "is PCSX". The first pass is the listing; the
# rest recover what it hid. Offset paging over an order with ties is not a
# partition, and each order ties differently: on PCSX, relevance can
# consistently drop one posting while listing another twice, and timestamp
# drops a varying few per run, while the union of one pass of each reaches the
# declared count. So a recovery pass changes the order rather than repeating
# it. v2 is known to page completely on relevance, so it repeats that.
_SWEEP_ORDERS: dict[bool, tuple[str, ...]] = {
    True: ("relevance", "timestamp", "relevance"),
    False: ("relevance", "relevance", "relevance"),
}

_WORKPLACE_MAP = {
    "onsite": WorkplaceType.ONSITE,
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
}


@dataclass(frozen=True)
class EightfoldTenant:
    host: str
    domain: str
    pcsx: bool

    @property
    def list_url(self) -> str:
        if self.pcsx:
            return f"https://{self.host}/api/pcsx/search"
        return f"https://{self.host}/api/apply/v2/jobs"


def parse_tenant(token: str) -> EightfoldTenant:
    """`host|domain` or `host|domain|pcsx`; anything else is a configuration error."""
    parts = token.split("|")
    if len(parts) not in (2, 3) or not all(parts[:2]):
        raise ValueError(
            f"eightfold board_token must be 'host|domain' or 'host|domain|pcsx', got {token!r}"
        )
    if len(parts) == 3 and parts[2] != "pcsx":
        raise ValueError(f"unknown eightfold API {parts[2]!r} in {token!r}")
    return EightfoldTenant(host=parts[0], domain=parts[1], pcsx=len(parts) == 3)


def probe_url(tenant: EightfoldTenant) -> str:
    """The first listing page — the route `fetch()` requests first."""
    return f"{tenant.list_url}?domain={tenant.domain}&start=0"


class EightfoldAdapter(BaseAdapter):
    name = "eightfold"
    #: `t_create`, or PCSX `postedTs` then `creationTs`; never `t_update`,
    #: which moves on every edit.
    posted_date = "created"
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    #: `count` sizes the board and drives the paging stop itself, so a run
    #: without it cannot even terminate correctly.
    declares_total = True
    # The token checker reads this. `counts_whole_board=False`: one page is ten
    # postings, so the probe proves presence, not size.
    board_probe = BoardProbe(
        jobs_url="https://{host}/api/{apply/v2/jobs|pcsx/search}?domain={domain}&start=0",
        tenants=_TENANTS,
        counts_whole_board=False,
        tenant_url=lambda token: probe_url(parse_tenant(token)),
    )

    @property
    def tenant(self) -> EightfoldTenant:
        token = _TENANTS.resolve(self.company, self.board_token)
        if token == self.company and "|" not in token:
            # No token and no module-map entry: the slug fallback is not a host.
            raise ValueError(f"no Eightfold host/domain configured for '{self.company}'")
        return parse_tenant(token)

    async def fetch(self) -> AsyncIterator[RawJob]:
        tenant = self.tenant
        total: int | None = None
        orders = _SWEEP_ORDERS[tenant.pcsx]
        sweep_order = [orders[0]]  # the pass in progress; `page` reads it per request
        ran_out = False

        async def page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total, ran_out
            start = index * _PAGE
            params: dict = {"domain": tenant.domain, "start": start, "sort_by": sweep_order[0]}
            if not tenant.pcsx:
                params["num"] = _PAGE
            resp = await self.get(tenant.list_url, params=params)
            if resp.status_code != 200:
                self.drift.invalidate_listing(
                    "non-200 job list", status=resp.status_code, start=start
                )
                stop()
                return []
            body = resp.json()
            data = body.get("data") if tenant.pcsx else body
            if not isinstance(data, dict):
                self.drift.invalidate_listing("missing 'data' envelope", start=start)
                stop()
                return []
            if total is None:
                total = data.get("count")
                self.drift.require(isinstance(total, int), "missing 'count' in response")
            positions = data.get("positions")
            if not isinstance(positions, list):
                self.drift.invalidate_listing("missing 'positions' array", start=start)
                stop()
                return []
            if not positions:
                # The board ran out before its count: it shrank during the walk,
                # so the count overstates it. The shortfall is a known number of
                # rows, which `close_listing` records as lost: a few on a large
                # board read as a moving board, most of it as a broken one.
                ran_out = isinstance(total, int) and start < total
                stop()
                return []
            if total is not None and start + _PAGE >= total:
                stop()
            return positions

        seen: set[str] = set()

        async def sweep(query_key: str | None) -> AsyncIterator[RawJob]:
            async for pos in self.paged_listing(
                page,
                max_pages=_MAX_PAGES,
                declared_total=lambda: total,
                page_size=_PAGE,
                query_key=query_key,
            ):
                job = self._to_rawjob(pos, tenant)
                if job is not None and job.req_id not in seen:
                    seen.add(job.req_id)
                    yield job

        async for job in sweep(None):
            yield job

        # Offset paging over an order with ties is not a partition: a row that
        # moves between two requests is read twice, and the row it displaced is
        # read never. The declared count exposes that — fewer UNIQUE postings
        # than it states means some exist that we did not see — so re-page for
        # the unseen, then refuse to call a short listing complete. A listing
        # claimed complete while short would close live postings.
        for attempt, order in enumerate(orders[1:], start=1):
            # A board that ran out cannot reach its count in any order: another
            # pass would walk it all again for rows that no longer exist.
            if ran_out or not self._short(total, seen):
                break
            sweep_order[0] = order
            async for job in sweep(f"recovery-{attempt}"):
                yield job
        if not seen and total == 0 and self.drift.listing_complete:
            # The tenant stated a count of 0 and served `positions` empty; an
            # unknown domain answers 404.
            self.drift.board_empty("count 0 and an empty positions array")
        if self.drift.listing_complete:
            # Guarded, not because the rule differs, but because a listing
            # already broken upstream has been reported once (`_short` reads the
            # same flag before deciding a recovery sweep is worth it).
            self.close_listing(
                declared=total, unique=len(seen),
                field="the declared count", sweeps=len(orders),
            )

    def _short(self, total: int | None, seen: set[str]) -> bool:
        """Short of the declared count, on a listing otherwise read in full.

        Only then is re-paging worth it: a truncated or already-broken listing
        is non-authoritative anyway, and has no count left to reach.
        """
        return (
            isinstance(total, int)
            and len(seen) < total
            and self.drift.listing_complete
            and not self.truncated
        )

    def _to_rawjob(self, pos: dict, tenant: EightfoldTenant) -> RawJob | None:
        req_id = str(
            pos.get("id") or pos.get("ats_job_id") or pos.get("atsJobId")
            or pos.get("display_job_id") or pos.get("displayJobId") or ""
        )
        title = pos.get("name") or pos.get("posting_name")
        if not req_id or not title:
            # One unusable row, not a broken listing — see `drop_record`.
            self.drift.drop_record(
                "position missing id/title", keys=list(pos.keys())[:8]
            )
            return None

        locations = []
        for loc in pos.get("locations") or ([pos["location"]] if pos.get("location") else []):
            name = clean_location(loc)
            if name and name not in locations:
                locations.append(name)

        workplace = _WORKPLACE_MAP.get(
            str(pos.get("work_location_option") or pos.get("workLocationOption") or "").lower(),
            WorkplaceType.UNKNOWN,
        )
        url = pos.get("canonicalPositionUrl") or pos.get("positionUrl")
        if isinstance(url, str) and url.startswith("/"):
            url = f"https://{tenant.host}{url}"

        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url or f"https://{tenant.host}/careers/job/{req_id}",
            locations=locations,
            department=pos.get("department"),
            team=pos.get("business_unit"),
            description_html=None,  # filled by hydrate()
            description_complete=False,
            workplace_type=workplace,
            # Never `t_update`: it moves on every edit, so as the
            # posting date it would re-date the posting at each one and reset
            # the listing age. The creation time is the posting's own start.
            posted_at=parse_datetime(
                pos.get("t_create") or pos.get("postedTs") or pos.get("creationTs")
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        tenant = self.tenant
        if tenant.pcsx:
            resp = await self.get(
                f"https://{tenant.host}/api/pcsx/position_details",
                params={"position_id": job.req_id, "domain": tenant.domain, "hl": "en"},
            )
        else:
            resp = await self.get(f"{tenant.list_url}/{job.req_id}", params={"domain": tenant.domain})
        if resp.status_code != 200:
            self.drift.note("non-200 job detail", status=resp.status_code, req=job.req_id)
            return
        detail = resp.json()
        if tenant.pcsx:
            detail = detail.get("data") if isinstance(detail, dict) else None
            desc = detail.get("jobDescription") if isinstance(detail, dict) else None
        else:
            desc = detail.get("job_description")
        if isinstance(desc, str) and desc.strip():
            job.description_html = desc
            job.detail_payload = detail
            job.description_complete = True
        else:
            self.drift.note("detail missing job description", req=job.req_id)
