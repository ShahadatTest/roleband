"""Accenture — its own careers search API, and its Workday board for the rest.

    POST https://www.accenture.com/api/accenture/elastic/findjobs
         (form: startIndex, maxResultSize, jobCountry, jobLanguage, countrySite, sortBy, ...)
    POST https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs
         (json: appliedFacets.locationCountry, limit, offset)
    GET  https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers{externalPath}

The own search is what `accenture.com/{site}/careers/jobsearch` calls in the
browser. `accenture.pinpointhq.com` holds only a few graduate postings, while
this first-party API serves the whole board per country with full descriptions
and each posting's career level (`careerLevel`, the rung most titles do not
name). It is the source wherever it can be asked about a country.

**One own-search query per country.** The API is narrowed by `jobCountry` +
`countrySite` + `jobLanguage`, and fails CLOSED: an unknown country, or a country
with the wrong site or language, answers 0. So these countries are a manifest,
hand-probed rather than generated, in the site's own language (`Deutschland` on
`de-de`, `日本` on `jp-ja`). India is left out everywhere: it answers 10,000 here
and far more on the board, which is each surface's result window, not a count.

**Every other country from the Workday board**, the ATS behind the own search
(the own search's rows link to it). Ids are the board's requisition ids, the
same values the own search returns, so one `seen` set keeps a posting listed on
both once. The board is narrowed by its `locationCountry` facet, an exact
filter; its word search (`searchText`) matches any posting that mentions the
country. Facet ids are read from the board's own first answer, which lists
every country holding an open role with its id, so none are stored. The rows
name no `locationsText`: the place is the bullet after the id. The board states
no career level, and its text costs one detail request per kept posting.

**Completeness per query.** `totalHits.total` and the board's `total` declare
each country. The own search's default sort (`sortBy=0`, vector relevance)
repeats rows across pages, so the adapter pages `sortBy=1`, which lists every
row once. Unique ids below a total, a total at a window, or `overMaxHits`
invalidates.

`www.accenture.com/robots.txt` disallows `*/careers/jobsearch?` (the search
PAGE with a query string) and careers registration/form/profile paths; the API
route matches none of them. The board's robots.txt allows its site paths and
disallows `/refreshFacet/`; the CXS routes are unmentioned.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from functools import cache
from typing import Any, NamedTuple
from urllib.parse import urlencode

from tracker.connectors.extract.payload import text_of
from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap, country_manifest
from tracker.connectors.listing.workday import WorkdayBoard, detail_places, posting_key
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
from tracker.taxonomy.countries import BY_SLUG, COUNTRIES, Country

FIND_JOBS = "https://www.accenture.com/api/accenture/elastic/findjobs"
_TENANTS = TenantMap({})
_PAGE = 100
_MAX_PAGES = 60
#: The search's result window: a total at or above it is the window, not a count.
_WINDOW = 10000

BOARD = WorkdayBoard("accenture.wd103.myworkdayjobs.com", "accenture", "AccentureCareers")
_BOARD_PAGE = 20  # Workday serves at most 20 rows a page
_BOARD_MAX_PAGES = 100
_BOARD_WINDOW = 2000
_COUNTRY_FACET = "locationCountry"
#: A board bullet that holds the place slot and names no place.
_NO_PLACE = frozenset({"location negotiable"})
#: The board's name for a country, where it is none of ours.
_BOARD_NAMES = {"china": "China/Mainland", "hong_kong": "China/Hong Kong SAR"}


class OwnSearch(NamedTuple):
    """One country on the own search, as its site names it."""

    country: str
    site: str
    language: str


class BoardCountry(NamedTuple):
    """One country on the Workday board, by our country slug."""

    slug: str


#: Location group -> its own-search query, each hand-probed (a wrong one answers 0).
OWN_SEARCH_QUERIES: dict[str, list[OwnSearch]] = {
    "united_states": [OwnSearch("USA", "us-en", "en")],
    "uk": [OwnSearch("United Kingdom", "gb-en", "en")],
    "canada": [OwnSearch("Canada", "ca-en", "en")],
    "singapore": [OwnSearch("Singapore", "sg-en", "en")],
    "australia": [OwnSearch("Australia", "au-en", "en")],
    "germany": [OwnSearch("Deutschland", "de-de", "de")],
    "ireland": [OwnSearch("Ireland", "ie-en", "en")],
    "japan": [OwnSearch("日本", "jp-ja", "ja")],
    "netherlands": [OwnSearch("Netherlands", "nl-en", "en")],
    "poland": [OwnSearch("Poland", "pl-en", "en")],
    "spain": [OwnSearch("España", "es-es", "es")],
    "sweden": [OwnSearch("Sweden", "se-en", "en")],
}
ACCENTURE_LOCATION_QUERIES: dict[str, list[OwnSearch | BoardCountry]] = {
    **{
        slug: terms
        for slug, terms in country_manifest(lambda c: BoardCountry(c.slug)).items()
        if slug != "india"
    },
    **{slug: list[OwnSearch | BoardCountry](terms) for slug, terms in OWN_SEARCH_QUERIES.items()},
}
_WORKPLACE = {"on-site": WorkplaceType.ONSITE, "remote": WorkplaceType.REMOTE, "hybrid": WorkplaceType.HYBRID}
_SECTIONS = ("jobDescription", "qualification", "additionalInformation")


def search_form(
    country: str, site: str, start: int, size: int = _PAGE, language: str = "en"
) -> dict[str, str]:
    """The form the careers page posts, with the stable sort (`sortBy=1`)."""
    return {
        "startIndex": str(start), "maxResultSize": str(size), "jobKeyword": "",
        "jobCountry": country, "jobLanguage": language, "countrySite": site, "sortBy": "1",
        "searchType": "vectorSearch", "enableQueryBoost": "true", "minScore": "0.6",
        "getFeedbackJudgmentEnabled": "true", "useCleanEmbedding": "true", "score": "true",
        "totalHits": "true", "debugQuery": "false", "jobFilters": "[]",
    }


@cache
def _board_country_slugs() -> dict[str, str]:
    """Every name a country may go by on the board, lower-cased, to its slug."""
    names: dict[str, str] = {}
    for country in COUNTRIES:
        for name in (country.display, country.query_name, *country.aliases):
            names.setdefault(name.lower(), country.slug)
    for slug, name in _BOARD_NAMES.items():
        names[name.lower()] = slug
    return names


def _names_country(label: str, places: list[str]) -> bool:
    """Whether `label` is a country no place in `places` already names."""
    slug = _board_country_slugs().get(label.lower())
    return slug is not None and not any(label.lower() in place.lower() for place in places)


def board_country_facets(body: object) -> tuple[dict[str, str], list[str]]:
    """`(slug -> facet id, board names matching no country)` from a board answer.

    The facet can be nested in a group, as Workday does for location facets.
    """
    names = _board_country_slugs()
    ids: dict[str, str] = {}
    unknown: list[str] = []

    def walk(facets: object, parameter: str | None) -> None:
        for facet in facets if isinstance(facets, list) else []:
            if not isinstance(facet, dict):
                continue
            here = facet.get("facetParameter") or parameter
            for value in facet.get("values") or []:
                if not isinstance(value, dict):
                    continue
                if "values" in value:
                    walk([value], here)
                elif here == _COUNTRY_FACET and value.get("id"):
                    name = str(value.get("descriptor") or "")
                    slug = names.get(name.lower())
                    if slug:
                        ids[slug] = str(value["id"])
                    else:
                        unknown.append(name)

    walk(body.get("facets") if isinstance(body, dict) else None, None)
    return ids, unknown


class AccentureAdapter(BaseAdapter):
    name = "accenture"
    posted_date = "none"  # the own search states no date
    listing_scope = "filtered"  # one search per location term
    detail = "per_posting"  # board rows read their text in `hydrate`
    text_from_posting = True  # a board row's detail address is its url
    #: `totalHits.total` and the board's `total` state each country's board.
    #: At the result window it is the window, not a count — `saturated`.
    declares_total = True
    location_queries = ACCENTURE_LOCATION_QUERIES
    board_probe = BoardProbe(
        jobs_url=FIND_JOBS,
        tenants=_TENANTS,
        # One company, one fixed route. The probe sends the adapter's own form
        # POST: a GET of this route answers 404 HTML while the POST serves the
        # board, so a GET says nothing about the board.
        # One row of one country: presence, not the board's size.
        tenant_url=lambda _token: FIND_JOBS,
        method="POST",
        probe_body=search_form(
            OWN_SEARCH_QUERIES["united_states"][0].country,
            OWN_SEARCH_QUERIES["united_states"][0].site,
            0,
            size=1,
            language=OWN_SEARCH_QUERIES["united_states"][0].language,
        ),
        probe_encoding="form",
        counts_whole_board=False,
    )
    required_capabilities = Capabilities(stream=False, post=True, impersonate=False, render=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: The board's country facet ids, read once a scan; None until read or
        #: when the read failed.
        self._board_facets: dict[str, str] | None = None
        self._board_facets_read = False

    async def fetch(self) -> AsyncIterator[RawJob]:
        async for job in self.scan_location_queries(self.planned_location_terms(), self._query):
            yield job

    def _query(self, query: OwnSearch | BoardCountry, seen: set[str]) -> AsyncIterator[RawJob]:
        if isinstance(query, BoardCountry):
            return self._board_country(query, seen)
        return self._country(query, seen)

    async def _country(self, query: OwnSearch, seen: set[str]) -> AsyncIterator[RawJob]:
        country, site, language = query
        total: int | None = None
        saturated = False
        query_ids: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total, saturated
            resp = await self.context.fetch(FetchRequest(
                url=FIND_JOBS, method="POST",
                # The transport sends `body` as-is: encode the form here.
                body=urlencode(search_form(country, site, index * _PAGE, language=language)).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("findjobs page failed", country=country, status=resp.status)
                stop()
                return []
            try:
                data = resp.json()
            except ValueError:
                data = None
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(data, dict) or not isinstance(rows, list):
                self.drift.invalidate_listing("findjobs page has no data array", country=country)
                stop()
                return []
            hits = data.get("totalHits")
            if not isinstance(hits, dict):
                hits = {}
            if total is None and isinstance(hits.get("total"), int):
                total = hits["total"]
                saturated = str(hits.get("overMaxHits")).lower() == "true" or total >= _WINDOW
            if total is not None and (index + 1) * _PAGE >= min(total, _WINDOW):
                stop()
            return rows

        async for row in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key=country,
            declared_total=lambda: total, page_size=_PAGE, country=country,
        ):
            job = self._job(row, site)
            if job is None:
                continue
            query_ids.add(job.req_id)
            if job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job

        if saturated:
            self.drift.invalidate_listing("country total is the result window", country=country, total=total)
        else:
            self.close_listing(
                declared=total, unique=len(query_ids), field="the country total", country=country,
            )

    async def _board_country_ids(self) -> dict[str, str] | None:
        """Slug -> the board's country facet id, from the board's first answer."""
        if self._board_facets_read:
            return self._board_facets
        self._board_facets_read = True
        resp = await self.post(
            BOARD.cxs + "/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        )
        try:
            body = resp.json() if resp.status_code == 200 else None
        except (ValueError, json.JSONDecodeError):
            body = None
        ids, unknown = board_country_facets(body)
        if not ids:
            self.drift.invalidate_listing("board answered no country list", status=resp.status_code)
            return None
        if unknown:
            # Roles in a country no location group can hold: never asked for.
            self.drift.note("board names countries we cannot place", names=sorted(unknown))
        self._board_facets = ids
        return ids

    async def _board_country(self, query: BoardCountry, seen: set[str]) -> AsyncIterator[RawJob]:
        ids = await self._board_country_ids()
        if ids is None:
            return
        facet = ids.get(query.slug)
        if facet is None:
            # The list names every country holding an open role, so a country
            # it leaves out has none: a complete, empty listing.
            return
        country = BY_SLUG[query.slug]
        total: int | None = None
        saturated = False
        query_ids: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total, saturated
            offset = index * _BOARD_PAGE
            resp = await self.post(BOARD.cxs + "/jobs", json={
                "appliedFacets": {_COUNTRY_FACET: [facet]}, "limit": _BOARD_PAGE,
                "offset": offset, "searchText": "",
            })
            try:
                data = resp.json() if resp.status_code == 200 else None
            except (ValueError, json.JSONDecodeError):
                data = None
            postings = data.get("jobPostings") if isinstance(data, dict) else None
            if not isinstance(data, dict) or not isinstance(postings, list):
                self.drift.invalidate_listing(
                    "board page failed", country=query.slug, status=resp.status_code, offset=offset
                )
                stop()
                return []
            if total is None and isinstance(data.get("total"), int):
                # The board states its total on the first page only.
                total = data["total"]
                saturated = total >= _BOARD_WINDOW
            if not postings or (total is not None and offset + _BOARD_PAGE >= min(total, _BOARD_WINDOW)):
                stop()
            return postings

        async for item in self.paged_listing(
            fetch_page, max_pages=_BOARD_MAX_PAGES, query_key=f"board:{query.slug}",
            declared_total=lambda: total, page_size=_BOARD_PAGE, country=query.slug,
        ):
            job = self._board_job(item, country)
            if job is None:
                continue
            query_ids.add(job.req_id)
            if job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job

        if saturated:
            self.drift.invalidate_listing("board country total is the window", country=query.slug, total=total)
        else:
            self.close_listing(
                declared=total, unique=len(query_ids), field="the board's country total", country=query.slug,
            )

    def _board_job(self, item: object, country: Country) -> RawJob | None:
        if not isinstance(item, dict):
            self.drift.drop_record("board posting is not an object")
            return None
        req_id, title = posting_key(item), text_of(item.get("title"))
        path = text_of(item.get("externalPath"))
        if not req_id or not title or not path:
            self.drift.drop_record("board posting missing id/title/externalPath", keys=list(item)[:8])
            return None
        # The row's bullets are its id and then its primary place;
        # `locationsText`, which other Workday boards fill, is absent here. The
        # country filter matches a posting with ANY place in the country, so the
        # primary place can be elsewhere ("Copenhagen" under Sweden): the two
        # are kept apart, never joined into one place.
        place = text_of(item.get("locationsText")) or next(
            (text for bullet in item.get("bulletFields") or []
             if (text := text_of(bullet)) and text != req_id),
            None,
        )
        listed = clean_location(place) if place and place.lower() not in _NO_PLACE else None
        locations = [listed] if listed else []
        if country.display not in locations:
            locations.append(country.display)
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=BOARD.posting_url(path),
            locations=locations,
            description_html=None,
            description_complete=False,
            workplace_type=WorkplaceType.UNKNOWN,
            posted_at=None,
        )

    def _board_path(self, job: RawJob) -> str | None:
        """A board posting's detail path, from its url; None for an own-search one."""
        prefix = BOARD.posting_url("")
        return job.url[len(prefix):] if job.url.startswith(prefix + "/job/") else None

    async def hydrate(self, job: RawJob) -> None:
        # Own-search rows carry their whole text inline.
        path = self._board_path(job)
        if path is None or job.description_complete:
            return
        resp = await self.get(BOARD.cxs + path)
        if resp.status_code != 200:
            self.drift.note("board detail failed", status=resp.status_code, req=job.req_id)
            return
        try:
            info = (resp.json() or {}).get("jobPostingInfo") or {}
        except (ValueError, json.JSONDecodeError):
            self.drift.note("board detail is not JSON", req=job.req_id)
            return
        if not isinstance(info, dict):
            return
        description = info.get("jobDescription")
        if isinstance(description, str) and description.strip():
            job.description_html = description
            job.description_complete = True
        posted = parse_datetime(info.get("startDate")) or parse_datetime(info.get("postedOn"))
        if posted is not None:
            job.posted_at = posted
        # The detail's places lead; the filtered country stays unless a detail
        # place already names it, since the detail's places carry no country.
        places = detail_places(info)
        if places:
            job.locations = [
                *places,
                *(loc for loc in job.locations if loc not in places and _names_country(loc, places)),
            ]

    def _job(self, row: object, site: str) -> RawJob | None:
        if not isinstance(row, dict):
            self.drift.drop_record("posting is not an object")
            return None
        req_id, title = text_of(row.get("requisitionId")), text_of(row.get("title"))
        if not req_id or not title:
            self.drift.drop_record("posting missing requisitionId/title", keys=list(row)[:8])
            return None
        listed = row.get("location")
        raw_places = listed if isinstance(listed, list) else [row.get("feedCity")]
        places: list[SourceLocation] = []
        for raw in raw_places:
            label = clean_location(str(raw)) if raw else None
            if label and all(label != p.label for p in places):
                places.append(SourceLocation(label=label, country=text_of(row.get("country")), is_primary=not places))
        body = "".join(str(row[k]) for k in _SECTIONS if isinstance(row.get(k), str) and row[k].strip())
        families = row.get("jobFamilyGroup") if isinstance(row.get("jobFamilyGroup"), list) else []
        schedule = text_of(row.get("jobScheduleDescription"))
        url = (text_of(row.get("jobDetailUrl")) or "").replace("{0}", site)
        updated = parse_datetime(row.get("updateDate"))
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=[p.label for p in places],
            department=text_of(families[0]) if families else None,
            # `businessArea` ("Industry X", "Accenture Flex") is not a team and is
            # empty on some rows; the family group is the domain signal.
            description_html=body or None,
            description_complete=bool(body),
            workplace_type=_WORKPLACE.get(str(row.get("remoteType") or "").strip().lower(), WorkplaceType.UNKNOWN),
            # Accenture's ladder rung ("Analyst", "Senior Analyst", "Manager").
            raw_level=text_of(row.get("careerLevel")),
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity="accenture.com",
                posting_id=req_id,
                source_updated_at=updated,
                employment_type_raw=schedule,
                employment_type_normalized=(
                    EmploymentType.FULL_TIME if (schedule or "").lower() == "full time"
                    else EmploymentType.PART_TIME if (schedule or "").lower() == "part time"
                    else EmploymentType.UNKNOWN
                ),
                locations=places,
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )
