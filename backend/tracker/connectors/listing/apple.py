"""Apple — jobs.apple.com private JSON API (CSRF-gated, Akamai-fronted).

Flow:
  1. GET  /api/v1/CSRFToken             -> read `x-apple-csrf-token` header + cookies
  2. POST /api/v1/search                -> paginated results (page size 20)
  3. GET  /api/v1/jobDetails/{position} -> full description (hydrate, keepers only)

We scope the search to our target metros via `filters.postingpostLocation` so we
page through a bounded set rather than all of Apple.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from tracker.connectors.detail import structure_job_detail
from tracker.connectors.listing.apple_places import APPLE_COUNTRY_CODES
from tracker.connectors.listing.base import BaseAdapter
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import RawJob, WorkplaceType

_ORIGIN = "https://jobs.apple.com"
_CSRF_URL = f"{_ORIGIN}/api/v1/csrfToken"
_SEARCH_URL = f"{_ORIGIN}/api/v1/search"


def search_body(locations: list[str], page: int = 1) -> dict:
    """One search page's body. Without `format` the search answers every
    query with zero results, so a count read without it reads nothing."""
    return {
        "query": "",
        "filters": {"locations": locations},
        "page": page,
        "locale": "en-us",
        "sort": "newest",
        "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
    }
_DETAIL_URL = f"{_ORIGIN}/api/v1/jobDetails"
_PAGE_SIZE = 20
_MAX_PAGES = 300  # combined US+UK+SGP search at 20/page, with headroom
# The search intermittently answers a mid-listing page with
# `{"totalRecords": 0, "searchResults": []}`, on a sizeable share of identical
# requests. A page past the real end answers the same bytes, so the two are told
# apart by position: we stop at the declared total, so an empty page before it is
# the flake and is retried. Read as the end, it would invalidate the run of a
# healthy board. Six attempts make a lost page rare, not impossible.
_SOFT_EMPTY_ATTEMPTS = 6

# Our location-group slugs -> Apple postLocation codes. Apple ORs all codes into
# one combined search, so US-wide (postLocation-USA) subsumes the Bay Area
# (SCV/CUP/SVL); the downstream country/metro matcher
# re-tags silicon_valley et al. from each posting's returned city.
# Country codes come only from Apple's own lookup (`apple_places`): an ISO code
# can name another place (`IND` is in the US) or part of the country (`SWE`
# is part of Sweden, `SWEC` the whole).
APPLE_LOCATION_CODES: dict[str, list[str]] = {
    **{slug: [f"postLocation-{code}"] for slug, code in APPLE_COUNTRY_CODES.items()},
    # `postLocation-GBR` is the country code and `postLocation-LND` the city one.
    # The city code alone misses UK roles outside London. Both are sent because Apple filters in ONE
    # combined request (`filters.locations` is a list), so the union costs no
    # extra call and needs no assumption that GBR is a strict superset.
    # `postLocation-UKIR` does not exist (0), and a nonsense code returns 0 —
    # this filter fails closed, so a wrong value under-collects rather than
    # silently returning the whole board.
    "uk": ["postLocation-GBR", "postLocation-LND"],
}


def _requisition(item: object) -> str | None:
    """The id a search row is keyed by: `reqId`, else `positionId`.

    `positionId` alone is not enough: one position is posted per location
    under several reqIds, so keyed by position a walk would count fewer rows
    than the board serves and a discovery probe would miss the rows we hold.
    """
    if not isinstance(item, dict):
        return None
    key = item.get("reqId") or item.get("positionId")
    return str(key) if key else None


@dataclass
class _SearchWalk:
    """One listing walk's running state: the total the first
    real answer declared, and the transient answers retried along the way."""

    total: int | None = None
    soft_empty_retries: int = 0


class AppleAdapter(BaseAdapter):
    name = "apple"
    posted_date = "published"  # `postDateInGMT`
    listing_scope = "filtered"  # one search over the planned postLocation codes
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    # Combined newest-first feed. The frontier stop normally ends the probe far
    # earlier; sixteen pages (~320 newest postings) is the burst allowance.
    discovery_max_pages = 16
    # `"sort": "newest"` on the search payload, so a recognized row proves
    # everything below it is older.
    discovery_frontier_ordered = True
    location_queries = APPLE_LOCATION_CODES
    #: `res.totalRecords` sizes the whole listing: every location code rides in
    #: ONE combined search, so there is one count and one query to hold it to.
    declares_total = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Forwarded verbatim so this adapter never has to be revisited when the
        # base gains another injected bound (limiter/breaker/deadline).
        super().__init__(*args, **kwargs)
        self._csrf: str | None = None
        self._detail_access_blocked = False

    def default_headers(self) -> dict[str, str]:
        headers = super().default_headers()
        headers.update(
            {
                "Origin": _ORIGIN,
                "Referer": f"{_ORIGIN}/en-us/search",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        return headers

    async def _ensure_csrf(self) -> bool:
        resp = await self.get(_CSRF_URL)
        token = resp.headers.get("x-apple-csrf-token")
        if not token:
            self.drift.note("no x-apple-csrf-token header", status=resp.status_code)
            return False
        self._csrf = token
        return True

    def _location_codes(self) -> list[str]:
        # Apple posts all codes in ONE combined query, so this is a single
        # request's filter list rather than a query vocabulary to iterate.
        return self.planned_location_terms()

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not await self._ensure_csrf():
            self.drift.invalidate_listing("listing unavailable without CSRF token")
            return

        walk = _SearchWalk()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            return await self._search_page(walk, index, stop)

        ids: set[str] = set()
        unkeyed = 0  # rows served with no id: still rows `totalRecords` includes
        async for item in self.paged_listing(
            fetch_page,
            max_pages=_MAX_PAGES,
            declared_total=lambda: walk.total,
            page_size=_PAGE_SIZE,
            item_key=_requisition,
        ):
            # Counted before a row can be dropped: the board counts rows it
            # SERVED, readable or not.
            key = _requisition(item)
            if key:
                ids.add(key)
            else:
                unkeyed += 1
            job = self._to_rawjob(item)
            if job is not None:
                yield job
        # A newest-first board that gains a posting mid-walk shifts rows down:
        # one is re-read and none is missed. One that loses a posting shifts
        # every later row up, past the reader — a counted, bounded loss.
        if walk.total is not None or not self.drift.listing_invalidated:
            # A first page already lost never read the total: "the board
            # stated no totalRecords" would blame the board for our lost page.
            self.close_listing(declared=walk.total, unique=len(ids) + unkeyed, field="totalRecords")
        if walk.soft_empty_retries:
            # One line per run, not per page: the rate is what an operator
            # needs to see drift toward the attempt budget.
            self.drift.note("retried transient search answers", retries=walk.soft_empty_retries)

    async def _search(self, page: int) -> httpx.Response | None:
        """One search page, the CSRF token refreshed once if it expired."""
        body = search_body(self._location_codes(), page)
        while True:
            resp = await self.post(
                _SEARCH_URL, json=body, headers={"X-Apple-CSRF-Token": self._csrf or ""}
            )
            if resp.status_code != 401:
                return resp
            # Token expired mid-run; refresh once and retry this page.
            if not await self._ensure_csrf():
                self.drift.invalidate_listing("401 and CSRF refresh failed", page=page)
                return None

    async def _search_page(self, walk: _SearchWalk, index: int, stop: Callable[[], None]) -> list[dict]:
        """One page of the walk: its results, after the soft-empty retries; the
        first real answer's `totalRecords` becomes the walk's total."""
        page = index + 1
        for attempt in range(_SOFT_EMPTY_ATTEMPTS):
            resp = await self._search(page)
            if resp is None:
                stop()
                return []
            if resp.status_code != 200:
                self.drift.invalidate_listing(
                    "non-200 search", status=resp.status_code, page=page
                )
                stop()
                return []
            try:
                payload = resp.json()
            except ValueError:
                # The search occasionally answers 200 with a non-JSON body.
                # Same budget as the soft-empty, then a lost page, not a crash.
                payload = None
            if not isinstance(payload, dict):
                if attempt == _SOFT_EMPTY_ATTEMPTS - 1:
                    self.drift.invalidate_listing(
                        "search answered non-JSON", page=page,
                        content_type=resp.headers.get("content-type"),
                    )
                    stop()
                    return []
                walk.soft_empty_retries += 1
                continue
            res = payload.get("res") or {}
            soft_empty = res.get("totalRecords") == 0 and res.get("searchResults") == []
            if not soft_empty:
                break
            if attempt == _SOFT_EMPTY_ATTEMPTS - 1:
                if walk.total is None:
                    # Page 1 never answered for real. Accepted, `totalRecords:
                    # 0` would end the walk as a complete zero-row listing
                    # through `close_listing(0, 0)`. Apple cannot prove an
                    # empty board (the search is location-filtered, and this
                    # answer is the known flake), so it is never `board_empty`.
                    self.drift.invalidate_listing(
                        "search answered empty on every attempt",
                        page=page, retries=walk.soft_empty_retries,
                    )
                    # The retries are this message's; not noted twice.
                    walk.soft_empty_retries = 0
                    stop()
                    return []
                break
            walk.soft_empty_retries += 1

        if walk.total is None:
            walk.total = res.get("totalRecords")
            self.drift.require(isinstance(walk.total, int), "missing totalRecords")
        results = res.get("searchResults")
        if not isinstance(results, list):
            self.drift.invalidate_listing("missing searchResults array", page=page)
            stop()
            return []
        if not results:
            if isinstance(walk.total, int) and (page - 1) * _PAGE_SIZE < walk.total:
                self.drift.invalidate_listing(
                    "results ended before totalRecords", page=page, total=walk.total
                )
            stop()
            return []
        if walk.total is not None and page * _PAGE_SIZE >= walk.total:
            stop()
        return results

    def _to_rawjob(self, item: dict) -> RawJob | None:
        position_id = str(item.get("positionId") or "")
        req_id = _requisition(item) or ""
        title = item.get("postingTitle")
        if not req_id or not title:
            # One unusable row, not a broken listing — see `drop_record`.
            self.drift.drop_record(
                "result missing reqId/title", keys=list(item.keys())[:8]
            )
            return None

        locations = []
        for loc in item.get("locations") or []:
            name = clean_location(loc.get("name") if isinstance(loc, dict) else loc)
            if name and name not in locations:
                locations.append(name)

        slug = str(title).lower().replace(" ", "-")
        url = f"{_ORIGIN}/en-us/details/{position_id}/{slug}" if position_id else _ORIGIN

        workplace = WorkplaceType.REMOTE if item.get("homeOffice") else WorkplaceType.ONSITE

        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=locations,
            team=item.get("team", {}).get("teamName") if isinstance(item.get("team"), dict) else item.get("team"),
            description_html=item.get("jobSummary"),  # short summary; hydrate() fills full text
            description_complete=False,
            workplace_type=workplace,
            posted_at=parse_datetime(item.get("postDateInGMT")),
            raw_level=item.get("jobLevel"),
        )

    async def hydrate(self, job: RawJob) -> None:
        # A repeated auth failure is a backend block, not a per-job data error.
        # Preserve the list summary and stop making paid/paced detail requests
        # for the rest of this run rather than repeatedly challenging Apple.
        if self._detail_access_blocked:
            return
        # positionId is embedded in the detail URL we built.
        try:
            position_id = job.url.rstrip("/").split("/details/")[1].split("/")[0]
        except (IndexError, ValueError):
            return
        if not self._csrf:
            await self._ensure_csrf()
        resp = await self._get_detail(position_id)
        if resp.status_code == 401:
            refreshed = await self._ensure_csrf()
            if refreshed:
                resp = await self._get_detail(position_id)
            if not refreshed or resp.status_code == 401:
                self._detail_access_blocked = True
                self.drift.note(
                    "detail access blocked after CSRF refresh; hydration disabled for run",
                    status=401,
                    req=job.req_id,
                )
                return
        elif resp.status_code == 403:
            self._detail_access_blocked = True
            self.drift.note(
                "detail access forbidden; hydration disabled for run",
                status=403,
                req=job.req_id,
            )
            return
        if resp.status_code != 200:
            # The short jobSummary already populated description_html, so the full
            # detail is a best-effort bonus. Only flag drift if we have nothing.
            if not job.description_html:
                self.drift.note("non-200 detail (no summary)", status=resp.status_code, req=job.req_id)
            return
        structure_job_detail(job, self.drift, payload=resp.json(), source=self.name)
        if not job.description_sections and not job.description_html:
            self.drift.note("detail had no description fields", req=job.req_id)

    async def _get_detail(self, position_id: str) -> httpx.Response:
        return await self.get(
            f"{_DETAIL_URL}/{position_id}",
            params={"locale": "en-us"},
            headers={"X-Apple-CSRF-Token": self._csrf or ""},
        )
