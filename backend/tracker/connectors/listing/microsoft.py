"""Microsoft — apply.careers.microsoft.com (Eightfold PCSX).

Microsoft's careers site runs Eightfold's Personalized Career Site (PCSX). The
classic Eightfold `/api/apply/v2/jobs` endpoint is gated here ("Not authorized
for PCSX"); the live SPA instead calls:

    GET /api/pcsx/search?domain=microsoft.com&query=&location=<term>&start=N&sort_by=timestamp
        -> {status, data:{positions:[{id, displayJobId, name, locations[],
                          standardizedLocations[], postedTs, department,
                          workLocationOption, positionUrl}], count:<total>}}
    GET /api/pcsx/position_details?position_id=<id>&domain=microsoft.com&hl=en
        -> {data:{jobDescription:"<html>", ...}}  (US pay range is in the HTML)

Request frugality (Microsoft rate-limits; keep the request count low):
- Page size is server-capped at 10, so we DON'T fetch the whole board.
  Instead we issue one `location=` query per tracked metro and paginate only that
  slice (the downstream substring matcher validates the exact metro), stopping
  exactly at `start >= data.count`.
- One shared pacer (BaseAdapter) with a slightly higher min-delay than default.
No cookies/handshake needed — the search + detail endpoints are anonymous.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from tracker.connectors.listing.base import BaseAdapter, country_manifest
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import RawJob, WorkplaceType

_ORIGIN = "https://apply.careers.microsoft.com"
_SEARCH_URL = f"{_ORIGIN}/api/pcsx/search"
_DETAIL_URL = f"{_ORIGIN}/api/pcsx/position_details"
_DOMAIN = "microsoft.com"
_PAGE = 10  # PCSX search hard-caps the page size at 10
_MAX_PAGES = 120  # per location term; US-wide term needs depth (metros stop early)

# Location-group slug -> source-side `location=` terms. Kept small on purpose
# (fewer terms = fewer requests); the downstream substring matcher in
# config.LOCATION_GROUPS narrows to the exact tracked metros.
# Country display names for the whole planet, then the hand-verified entries
# layered on top. Microsoft's `location` is free text and fails closed (a
# nonsense term returns count=0), so the generated half is safe; the overrides
# below carry terms measured to beat the generated one.
MICROSOFT_LOCATION_QUERIES: dict[str, list[str]] = {
    **country_manifest(lambda c: c.query_name),
    "silicon_valley": ["Mountain View", "San Francisco", "Santa Clara"],
    "united_states": ["United States"],  # broad; validate in smoke, then trim metros
    # The city term alone misses UK roles outside London. Both are queried and
    # the pager dedupes across them (`scan_location_queries` shares one `seen`
    # set), so coverage is a union by construction rather than an assumption
    # that the country term is a strict superset.
    # A nonsense term returns 0, so this filter fails closed.
    "uk": ["United Kingdom", "London"],
    "singapore": ["Singapore"],
}

_WORKPLACE: dict[str | None, WorkplaceType] = {
    "onsite": WorkplaceType.ONSITE,
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
}


class MicrosoftAdapter(BaseAdapter):
    name = "microsoft"
    posted_date = "published"  # `postedTs`
    listing_scope = "filtered"  # one query per location term
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    # A touch more polite than the 2s default — Microsoft's PCSX is rate-limited
    # and one collector stream serves the whole company.
    min_delay = 3.0
    location_queries = MICROSOFT_LOCATION_QUERIES
    #: `data.count` sizes each term's listing.
    declares_total = True

    async def fetch(self) -> AsyncIterator[RawJob]:
        async for job in self.scan_location_queries(
            self.planned_location_terms(), self._fetch_term
        ):
            yield job

    async def _fetch_term(self, term: str, seen: set[str]) -> AsyncIterator[RawJob]:
        total: int | None = None
        term_ids: set[str] = set()
        unkeyed = 0  # rows served with no id: still rows the count includes

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total
            start = index * _PAGE
            params = {
                "domain": _DOMAIN,
                "query": "",
                "location": term,
                "start": str(start),
                "sort_by": "timestamp",
            }
            resp = await self.get(_SEARCH_URL, params=params)
            if resp.status_code != 200:
                self.drift.invalidate_listing(
                    "non-200 search", status=resp.status_code, term=term, start=start
                )
                stop()
                return []
            data = (resp.json() or {}).get("data") or {}
            if total is None:
                total = data.get("count")
                self.drift.require(isinstance(total, int), "missing 'count'", term=term)
            positions = data.get("positions")
            if not isinstance(positions, list):
                self.drift.invalidate_listing("missing 'positions' array", term=term, start=start)
                stop()
                return []
            if not positions:
                stop()
                return []
            if isinstance(total, int) and start + _PAGE >= total:
                stop()
            return positions

        async for item in self.paged_listing(
            fetch_page,
            max_pages=_MAX_PAGES,
            query_key=term,
            declared_total=lambda: total,
            page_size=_PAGE,
            term=term,
        ):
            # Every row this TERM served, before the cross-term dedupe: `count`
            # sizes the term, not the union.
            if isinstance(item, dict) and item.get("id"):
                term_ids.add(str(item["id"]))
            else:
                unkeyed += 1
            job = self._to_rawjob(item)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        self.close_listing(declared=total, unique=len(term_ids) + unkeyed, field="count", term=term)

    def _to_rawjob(self, item: dict) -> RawJob | None:
        if not isinstance(item, dict):
            return None
        req_id = str(item.get("id") or "")
        title = item.get("name")
        if not req_id or not title:
            # One unusable row, not a broken listing — see `drop_record`.
            self.drift.drop_record("position missing id/name", keys=list(item.keys())[:8])
            return None
        # standardizedLocations ("Redmond, WA, US") match the config substrings
        # more cleanly than the verbose `locations` ("United States, Washington,
        # Redmond"); keep both so nothing is lost.
        locations: list[str] = []
        for loc in (item.get("standardizedLocations") or []) + (item.get("locations") or []):
            name = clean_location(loc if isinstance(loc, str) else None)
            if name and name not in locations:
                locations.append(name)
        position_url = item.get("positionUrl") or f"/careers/job/{req_id}"
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=f"{_ORIGIN}{position_url}",
            locations=locations,
            department=item.get("department"),
            description_html=None,
            description_complete=False,
            workplace_type=_WORKPLACE.get(item.get("workLocationOption"), WorkplaceType.UNKNOWN),
            posted_at=parse_datetime(item.get("postedTs")),
        )

    async def hydrate(self, job: RawJob) -> None:
        params = {"position_id": job.req_id, "domain": _DOMAIN, "hl": "en"}
        resp = await self.get(_DETAIL_URL, params=params)
        if resp.status_code != 200:
            self.drift.note("non-200 position_details", status=resp.status_code, req=job.req_id)
            return
        data = (resp.json() or {}).get("data") or {}
        description = data.get("jobDescription")
        if description:
            job.description_html = description
            job.description_complete = True
