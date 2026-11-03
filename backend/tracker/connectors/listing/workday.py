"""Generic Workday CXS adapter — one class, many tenants.

Workday's public "candidate experience" (CXS) API is multi-tenant: every company
on Workday exposes the same shape under its own host + site id, so a single
adapter parameterized by (host, site) serves all of them, any Workday company
by config alone.

    POST https://{host}/wday/cxs/{tenant}/{site}/jobs
        body {"appliedFacets": {}, "limit": 20, "offset": N, "searchText": "..."}
        -> {"total": int, "jobPostings": [{title, externalPath, locationsText,
                                            postedOn, bulletFields:[reqId]}]}
    GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}
        -> {"jobPostingInfo": {jobDescription(html), location, startDate,
                               timeType, jobReqId, externalUrl, ...}}

The list omits the description, so `hydrate()` fetches per kept job (Netflix/Google
pattern). Workday caps `limit` at 20 and has no stable, tenant-portable location
facet (facet ids are opaque GUIDs that drift), so we narrow the same way the
Google adapter does: issue one `searchText` query per configured location term
and let `config.LOCATION_GROUPS` substring-match the exact metros downstream.

Resolution mirrors Greenhouse/Ashby: a DB-registered company passes its host+site
in `board_token` ("{host}|{site}"); a built-in falls back to `WORKDAY_TENANTS`.
The CXS tenant is the host's first label (`nvidia.wd5.myworkdayjobs.com`), except
on Workday's shared `wd{N}.myworkdaysite.com` hosts, where the host names no
tenant and the token names it: "{host}|{site}|{tenant}".
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import NamedTuple

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap, country_manifest
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import RawJob, WorkplaceType

_PAGE = 20  # Workday hard-caps the CXS page size at 20 (limit>20 returns none)
# 2000 postings a term: CXS serves a single searchText up to its 2000-row window
# (`_WINDOW`), so this drains a high-volume metro and pages a country-wide term
# to the window.
_MAX_PAGES = 100
#: CXS caps `total` itself at 2000, so a total at the cap is the window, not a
#: count. Offsets past a total still return rows, so the declared total is the
#: only end a term has — and the only evidence.
_WINDOW = 2000

# Built-in Workday companies: slug -> "{host}|{site}". `tenant` (the CXS path
# segment) is the host's first label. A DB-added company overrides via
# board_token "{host}|{site}" without a code change.
WORKDAY_TENANTS: dict[str, str] = {
    "nvidia": "nvidia.wd5.myworkdayjobs.com|NVIDIAExternalCareerSite",
}
_TENANTS = TenantMap(WORKDAY_TENANTS)

# Location-group slug -> source-side `searchText` terms. Generic place names, not
# tenant-specific; the downstream substring matcher validates the real metro.
# Country display names for the whole planet, then hand-verified overrides.
# Workday's location term is free text per tenant; smoke covers the live half.
WORKDAY_LOCATION_QUERIES: dict[str, list[str]] = {
    **country_manifest(lambda c: c.query_name),
    "silicon_valley": ["Santa Clara", "Sunnyvale", "San Francisco", "San Jose"],
    "united_states": ["United States"],  # broad free-text; validate per tenant in smoke
    "uk": ["United Kingdom", "London"],
    "singapore": ["Singapore"],
}


class WorkdayBoard(NamedTuple):
    """One tenant's board: every Workday URL we build comes from here."""

    host: str
    tenant: str
    site: str

    @property
    def cxs(self) -> str:
        return f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}"

    def posting_url(self, external_path: str) -> str:
        """The human posting page (`jobPostingInfo.externalUrl`'s shape).

        On a shared `myworkdaysite.com` host the site is not at the root:
        `/recruiting/{tenant}/{site}/job/...` (`/{site}/job/...` answers 500
        there).
        """
        if self.host.endswith(".myworkdaysite.com"):
            return f"https://{self.host}/recruiting/{self.tenant}/{self.site}{external_path}"
        return f"https://{self.host}/{self.site}{external_path}"


def parse_board(token: str) -> WorkdayBoard:
    """`host|site`, or `host|site|tenant` when the host does not name the tenant."""
    parts = token.split("|")
    if len(parts) not in (2, 3) or not all(part.strip() for part in parts):
        raise ValueError(
            f"workday board_token must be 'host|site' or 'host|site|tenant', got {token!r}"
        )
    host, site = parts[0].strip(), parts[1].strip()
    tenant = parts[2].strip() if len(parts) == 3 else host.split(".", 1)[0]
    return WorkdayBoard(host, tenant, site)


#: A listing row that COUNTS its places instead of naming them ("2 Locations").
#: No location group can match it, and locations fail closed, so without its
#: page such a row is collected and shown to nobody.
COUNT_ONLY_LOCATION = re.compile(r"\d+ Locations?")


def posting_key(item: dict) -> str:
    """A listing row's requisition id: the bare `bulletFields` entry the
    `externalPath` ends with, else the first bare entry holding a digit, else
    the id after the last "_" in `externalPath`, else the first bare entry,
    else "".

    A bullet is not always the id. A tenant can badge featured postings
    (`["Spotlight Job", "JR0287131"]`); keyed by the badge, every badged row
    would collapse into one and the term would read as short of its total. An
    id never holds whitespace, a badge often does. A ONE-word badge ("Remote",
    "Hybrid", "New") holds no whitespace either: an id holds a digit, a badge
    does not, and the path names the id.
    """
    bare = [
        text for bullet in item.get("bulletFields") or []
        if (text := str(bullet).strip() if bullet is not None else "") and not re.search(r"\s", text)
    ]
    path = str(item.get("externalPath") or "")
    path_id = path.rsplit("_", 1)[-1] if path else ""
    for text in bare:
        if path_id and (path_id.startswith(text) or text.startswith(path_id)):
            return text
    for text in bare:
        if any(ch.isdigit() for ch in text):
            return text
    return path_id or (bare[0] if bare else "")


def detail_places(info: dict) -> list[str]:
    """Every place a CXS detail answer names: `location`, then
    `additionalLocations`, cleaned and de-duplicated in that order."""
    places: list[str] = []
    for raw in [info.get("location"), *(info.get("additionalLocations") or [])]:
        place = clean_location(raw) if isinstance(raw, str) else None
        if place and place not in places:
            places.append(place)
    return places


def cxs_jobs_url(token: str) -> str:
    """The CXS jobs route for a token — the one the adapter posts.

    Module-level so `BoardProbe` and `_resolve` cannot describe different
    routes: a probe that checks a route the adapter does not fetch verifies
    nothing.
    """
    return parse_board(token).cxs + "/jobs"


def declared_total(body: str) -> int | None:
    """`total` off a CXS page: the board's own count of its postings."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    total = data.get("total") if isinstance(data, dict) else None
    return total if isinstance(total, int) else None


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    posted_date = "published"  # the detail's `startDate`, else `postedOn`
    listing_scope = "filtered"  # one `searchText` query per location term
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # its `detail_payload` rebuilt from the posting url
    location_queries = WORKDAY_LOCATION_QUERIES
    #: `total` sizes each term below the window.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url="https://{token}/wday/cxs/jobs",  # unused: `tenant_url` builds the real one
        tenants=_TENANTS,
        tenant_url=cxs_jobs_url,
        # The route answers 400 to a GET, so the checker
        # asks the way the adapter does, for the smallest page Workday serves.
        method="POST",
        probe_body={"limit": 1, "offset": 0, "searchText": ""},
        read_count=declared_total,
        # One posting was requested, so the count proves the board SERVES roles;
        # `total` is the board's own size, which is why it is still read.
        counts_whole_board=True,
    )

    def _resolve(self) -> WorkdayBoard:
        token = _TENANTS.resolve(self.company, self.board_token)
        if "|" not in token and not self.board_token:
            # No token and no module-map entry: the slug fallback is not a host.
            raise ValueError(f"no Workday host/site configured for '{self.company}'")
        return parse_board(token)

    async def fetch(self) -> AsyncIterator[RawJob]:
        board = self._resolve()
        jobs_url = board.cxs + "/jobs"
        def fetch_term(term: str, seen: set[str]) -> AsyncIterator[RawJob]:
            return self._fetch_term(jobs_url, board, term, seen)

        async for job in self.scan_location_queries(self.planned_location_terms(), fetch_term):
            yield job

    async def _fetch_term(
        self,
        jobs_url: str,
        board: WorkdayBoard,
        term: str,
        seen: set[str],
    ) -> AsyncIterator[RawJob]:
        total: int | None = None
        term_ids: set[str] = set()
        unkeyed = 0  # rows served with no id: still rows `total` includes

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total
            offset = index * _PAGE
            body = {"appliedFacets": {}, "limit": _PAGE, "offset": offset, "searchText": term}
            resp = await self.post(jobs_url, json=body)
            if resp.status_code != 200:
                self.drift.invalidate_listing(
                    "non-200 jobs search", status=resp.status_code, term=term, offset=offset
                )
                stop()
                return []
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                # A 303 to the tenant's maintenance page is followed to non-JSON
                # HTML (status 200). Degrade to drift, never crash the source.
                self.drift.invalidate_listing(
                    "non-JSON jobs response (redirect/maintenance?)",
                    url=str(resp.url), term=term, offset=offset,
                )
                stop()
                return []
            if total is None:
                total = data.get("total")
                self.drift.require(isinstance(total, int), "missing 'total' count", term=term)
                if isinstance(total, int) and total >= _WINDOW:
                    # The window, not a count: collect what is addressable and
                    # never claim the term complete (amazon's rule).
                    self.truncated = True
            postings = data.get("jobPostings")
            if not isinstance(postings, list):
                self.drift.invalidate_listing("missing 'jobPostings' array", term=term, offset=offset)
                stop()
                return []
            if not postings:
                stop()
                return []
            if isinstance(total, int) and offset + _PAGE >= total:
                stop()
            return postings

        async for item in self.paged_listing(
            fetch_page,
            max_pages=_MAX_PAGES,
            query_key=term,
            declared_total=lambda: total,
            page_size=_PAGE,
            term=term,
        ):
            # The term's own rows, keyed as `_to_rawjob` keys them, before the
            # cross-term dedupe.
            if isinstance(item, dict):
                key = posting_key(item)
                if key:
                    term_ids.add(key)
                else:
                    unkeyed += 1
            job = self._to_rawjob(item, board)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            # Before the count-only branch: a page read in this scan replaces
            # the set, and a row whose card is not count-only never reaches
            # that branch at all, which is where held places were being lost.
            self.keep_held_places(job)
            if COUNT_ONLY_LOCATION.fullmatch(str(item.get("locationsText") or "").strip()):
                await self.place_from_page(job, partial(self._read_places, board=board))
            yield job
        self.close_listing(declared=total, unique=len(term_ids) + unkeyed, field="total", term=term)

    async def _read_places(self, job: RawJob, board: WorkdayBoard) -> list[str] | None:
        """A count-only row's places, from its detail. The answer is kept on
        the payload and `hydrate` reuses it, so a row that turns out in scope
        costs no second request. The query term is no substitute: a row
        returned for "United States" can be placed elsewhere. Only rows the role
        gate admits are read, since a large board's count-only rows would
        overrun its time budget. None: unreadable, and the row stays as it was,
        unplaced."""
        payload = job.detail_payload if isinstance(job.detail_payload, dict) else {}
        info = await self._fetch_info(board, str(payload.get("external_path") or ""), job.req_id)
        if info is None:
            return None
        payload["info"] = info
        return detail_places(info)

    async def _fetch_info(self, board: WorkdayBoard, external_path: str, req_id: str) -> dict | None:
        if not external_path:
            return None
        resp = await self.get(board.cxs + external_path)
        if resp.status_code != 200:
            self.drift.note("non-200 job detail", status=resp.status_code, req=req_id)
            return None
        try:
            info = (resp.json() or {}).get("jobPostingInfo") or {}
        except (ValueError, json.JSONDecodeError):
            self.drift.note("non-JSON job detail (redirect/maintenance?)", req=req_id)
            return None
        return info if isinstance(info, dict) else None

    def _to_rawjob(self, item: dict, board: WorkdayBoard) -> RawJob | None:
        external_path = item.get("externalPath")
        title = item.get("title")
        req_id = posting_key(item)
        if not req_id or not title or not external_path:
            # One unusable row inside a page that otherwise served fine. What we
            # can still say about it depends entirely on whether it named itself.
            if req_id:
                # It did. A tenant can serve `{"bulletFields": ["JR..."]}` for
                # a requisition whose external posting record is broken, and
                # keep serving it for hours — stable across refetches, returned
                # by a direct id search, present run after run. Treating it as
                # loss would suppress closure for the whole board on every one
                # of those runs. We cannot refresh the posting, but
                # we know the req is on the board — which is all closure asks —
                # so the listing is complete and the row keeps whatever we last
                # stored for it. When the source eventually drops the
                # row the listing stops mentioning it and it closes normally.
                self.observe_unusable(
                    req_id,
                    "posting served without title/externalPath",
                    keys=list(item.keys())[:8],
                )
            else:
                # It did not: an anonymous row is a posting we cannot even name,
                # so its absence proves nothing and the loss is real. Countable,
                # though — one bad row is not a broken listing.
                self.drift.drop_record(
                    "posting missing externalPath/title/reqId", keys=list(item.keys())[:8]
                )
            return None

        location = clean_location(item.get("locationsText"))
        locations = [location] if location else []
        workplace = (
            WorkplaceType.REMOTE
            if location and "remote" in location.lower()
            else WorkplaceType.UNKNOWN
        )
        # `externalPath` carries the ephemeral detail path for hydrate(); the human
        # URL matches jobPostingInfo.externalUrl (`WorkdayBoard.posting_url`).
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=board.posting_url(external_path),
            locations=locations,
            description_html=None,
            detail_payload={
                "external_path": external_path,
                "host": board.host,
                "site": board.site,
                "tenant": board.tenant,
            },
            description_complete=False,
            workplace_type=workplace,
            # Workday list dates are relative strings ("Posted Today", "Posted 30+
            # Days Ago") with no absolute date; hydrate() sets posted_at from the
            # precise startDate. Leave it unset here rather than guess a date.
            posted_at=None,
        )

    def payload_from_posting(self, job: RawJob) -> dict | None:
        """The listing's detail address, from the posting's own url.

        Every url we store is `WorkdayBoard.posting_url(external_path)`, so
        what follows this company's board prefix is the external path. Without
        it the description backfill could not refetch a stored posting's
        detail, because a stored posting carries no listing payload. None for a url that is
        not this company's board: a guessed address is no detail request."""
        try:
            board = self._resolve()
        except ValueError:
            return None
        prefix = board.posting_url("")
        if not job.url.startswith(prefix + "/job/"):
            return None
        return {
            "external_path": job.url[len(prefix):],
            "host": board.host,
            "site": board.site,
            "tenant": board.tenant,
        }

    async def hydrate(self, job: RawJob) -> None:
        payload = job.detail_payload if isinstance(job.detail_payload, dict) else {}
        external_path = payload.get("external_path")
        host = payload.get("host")
        site = payload.get("site")
        if not external_path or not host or not site:
            return
        # A payload that names no tenant: its host's label is it.
        tenant = payload.get("tenant") or host.split(".", 1)[0]
        info = payload.get("info")
        if not isinstance(info, dict):
            info = await self._fetch_info(WorkdayBoard(host, tenant, site), external_path, job.req_id)
            if info is None:
                return
        description = info.get("jobDescription")
        if description:
            job.description_html = description
            job.description_complete = True
        # Detail carries a precise date + the canonical location; prefer them.
        posted = parse_datetime(info.get("startDate")) or parse_datetime(info.get("postedOn"))
        if posted is not None:
            job.posted_at = posted
        # Every place the detail names leads, then any listing place it did not
        # repeat; a count ("2 Locations") is never kept beside real places.
        places = detail_places(info)
        if places:
            job.locations = places + [
                loc for loc in job.locations
                if loc not in places and not COUNT_ONLY_LOCATION.fullmatch(loc)
            ]
        # Hand the whole info dict to the detail connector for section parsing.
        job.detail_payload = info
