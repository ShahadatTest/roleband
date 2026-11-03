"""Lever — public postings API (multi-tenant).

    GET https://api.lever.co/v0/postings/{site}?mode=json&limit=50&skip=N

The v0 postings feed is the documented public board every Lever tenant exposes.
`api.lever.co/robots.txt` is `Allow: /` with `Crawl-delay: 1`; our 2.0s default
pacer is stricter, so no per-adapter `min_delay` override is needed.

Why not the company's own careers site: `lifeatspotify.com/robots.txt` disallows
`/api/` and `/_next/data/`, its sitemap carries no job URLs, and `/jobs` renders
no cards server-side — the board is fetched client-side from the one path
robots.txt forbids. Lever is the compliant surface, and it is also the richer
one: every posting inlines its full description, so `fetch()` yields complete
postings and `hydrate()` stays a no-op.

Pagination has no declared total, so a **short page is the termination signal**:
Lever answers `limit` exactly until the board runs out. That is a natural stop,
which is why `_MAX_PAGES` here is a non-termination backstop and never the
operative bound.

Dates: Lever exposes `createdAt` (epoch ms) and no `updatedAt`. It records when
the posting was opened and does not move when the body is edited, so it feeds
`posted_at` for display only. Change detection is `content.content_fingerprint`
over title + description text — never this field.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import (
    AccessSurface,
    BoardRegion,
    CompComponent,
    CompensationFacts,
    CompTier,
    EmploymentType,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
    WorkplaceType,
)

#: Lever's regional deployments. SEPARATE tenant namespaces, not mirrors: a
#: global tenant answers 404 on the EU host and vice versa, with the same body
#: `{"ok":false,"error":"Document not found"}` a nonexistent site returns.
#: So the region has to be carried from URL resolution;
#: it can never be recovered from a failed fetch, which is indistinguishable
#: from a dead board token. `tracker.ats_detect` maps hosts to regions and this
#: maps regions back to hosts; `board_probe.region_hosts` is the shared copy the
#: token checker reads, so nothing builds a Lever host independently.
REGION_HOSTS: dict[str, str] = {
    BoardRegion.GLOBAL.value: "api.lever.co",
    BoardRegion.EU.value: "api.eu.lever.co",
}
_POSTINGS_PATH = "/v0/postings"
_PAGE = 50  # server honors an explicit limit; 50 keeps one response ~0.5MB
_MAX_PAGES = 200  # backstop against a non-terminating feed (~10k postings)

# Company slug -> Lever site name. A DB-registered company overrides via
# `board_token` without a code change.
LEVER_SITES: dict[str, str] = {"spotify": "spotify"}
_TENANTS = TenantMap(LEVER_SITES)

#: Lever's `workplaceType` vocabulary maps 1:1 onto ours.
_WORKPLACE = {
    "onsite": WorkplaceType.ONSITE,
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
}

#: `categories.commitment` is a free-text tenant field, so this maps what has
#: actually been observed and keeps the raw string for everything else
#: ("Permanent", "Short Term", "Full Time Contractor", or none). "Permanent" is
#: an employment BASIS, and reading it as full-time
#: would assert hours the posting never stated.
_COMMITMENT = {
    "full time": EmploymentType.FULL_TIME,
    "fulltime": EmploymentType.FULL_TIME,
    "part time": EmploymentType.PART_TIME,
    "parttime": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "contractor": EmploymentType.CONTRACT,
    "full time contractor": EmploymentType.CONTRACT,
    "intern": EmploymentType.INTERN,
    "internship": EmploymentType.INTERN,
    "temporary": EmploymentType.TEMPORARY,
    "short term": EmploymentType.TEMPORARY,
}


class LeverAdapter(BaseAdapter):
    name = "lever"
    posted_date = "created"  # `createdAt`, the only date Lever serves
    #: `limit=1` keeps the verification payload to one posting on the same route
    #: the adapter pages. No `identity_url`: the response is a BARE ARRAY of
    #: postings — no envelope to carry a tenant name.
    board_probe = BoardProbe(
        jobs_url=f"https://{{host}}{_POSTINGS_PATH}/{{token}}?mode=json&limit=1",
        tenants=_TENANTS,
        region_hosts=REGION_HOSTS,
        counts_whole_board=False,
    )

    def _host(self) -> str:
        """This tenant's API host. Unknown/absent region means the global one,
        which is what a row or caller with no region means."""
        return REGION_HOSTS.get(self.board_region or "", REGION_HOSTS[BoardRegion.GLOBAL.value])

    def pacing_scope(self) -> str:
        """One bucket per REGION, not per family. Two hosts with separate
        capacity and separate failure modes: sharing a pacer would give each
        region half its allowance, and sharing a breaker would let an outage in
        one open the circuit on the other."""
        return f"{self.name}:{self.board_region or BoardRegion.GLOBAL.value}"

    def _site(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token)

    async def fetch(self) -> AsyncIterator[RawJob]:
        site = self._site()
        url = f"https://{self._host()}{_POSTINGS_PATH}/{site}"
        seen: set[str] = set()
        first_page_empty = False

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal first_page_empty
            resp = await self.get(
                url,
                params=[
                    ("mode", "json"),
                    ("limit", str(_PAGE)),
                    ("skip", str(index * _PAGE)),
                ],
            )
            if resp.status_code != 200:
                # The first page is the board root: an unknown site 404s there.
                # A later page that fails is a lost page.
                if index == 0:
                    self.drift.board_missing("non-200 postings", status=resp.status_code, site=site, skip=0)
                else:
                    self.drift.invalidate_listing(
                        "non-200 postings", status=resp.status_code, site=site, skip=index * _PAGE
                    )
                stop()
                return []
            data = resp.json()
            if not isinstance(data, list):
                self.drift.invalidate_listing("postings payload is not an array", site=site)
                stop()
                return []
            # Short page => the board ended here. Declaring the stop now (rather
            # than paying for one more empty page) is what keeps the natural
            # termination independent of `_MAX_PAGES`.
            if len(data) < _PAGE:
                stop()
            if index == 0 and not data:
                first_page_empty = True
            return data

        async for item in self.paged_listing(
            fetch_page,
            max_pages=_MAX_PAGES,
            query_key=site,
            # Lever's feed declares no count — it ends by serving a short page.
            page_size=_PAGE,
            site=site,
        ):
            job = self._to_rawjob(item)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        # Only when nothing upstream already invalidated the listing: a non-200
        # or non-array page recorded its own alert, and stacking a second
        # "zero postings" on top of it is noise, not signal.
        if not seen and self.drift.listing_complete:
            if first_page_empty:
                # The first page answered an array with nothing in it; an
                # unknown site or region answers 404.
                self.drift.board_empty("first page served an empty array", site=site)
            else:
                self.drift.invalidate_listing("parsed zero postings (schema drift?)", site=site)

    def _to_rawjob(self, item: dict) -> RawJob | None:
        req_id = str(item.get("id") or "")
        title = item.get("text")
        if not req_id or not title:
            # One unusable row, not a broken listing — see `drop_record`.
            self.drift.drop_record(
                "posting missing id/text", keys=list(item.keys())[:8]
            )
            return None

        categories = item.get("categories")
        if not isinstance(categories, dict):
            categories = {}
        # `allLocations` carries every site a multi-location posting is open at;
        # `location` is the primary and may repeat one of them.
        locations: list[str] = []
        raw_locations = categories.get("allLocations")
        candidates = list(raw_locations) if isinstance(raw_locations, list) else []
        candidates.append(categories.get("location"))
        for candidate in candidates:
            name = clean_location(candidate) if isinstance(candidate, str) else None
            if name and name not in locations:
                locations.append(name)

        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=item.get("hostedUrl") or item.get("applyUrl") or "",
            locations=locations,
            department=categories.get("department"),
            team=categories.get("team"),
            description_html=item.get("description"),
            # The list payload is the complete posting; the detail connector
            # structures straight from it — no hydrate round-trip.
            detail_payload=item,
            description_complete=True,
            workplace_type=_WORKPLACE.get(
                str(item.get("workplaceType") or "").lower(), WorkplaceType.UNKNOWN
            ),
            # Display only — see the module docstring. Lever has no `updatedAt`.
            posted_at=parse_datetime(item.get("createdAt")),
            source_facts=self._facts(item, req_id, categories, locations),
        )

    def _facts(
        self, item: dict, req_id: str, categories: dict, locations: list[str]
    ) -> SourceJobFacts:
        """Country and commitment are Lever's; the salary fields may not be there.

        `country` is a top-level field on the posting and applies to the primary
        location only — `allLocations` can span countries (London + Stockholm),
        so attaching one country code to all of them would be
        an invention. `createdAt` is a CREATION time and feeds
        `source_created_at`, never `first_published_at`: Lever does not say when
        the posting went up.

        Which location is primary comes from `categories.location`, which is
        where Lever states it. It is NOT `locations[0]`: that list is assembled
        `allLocations` first with the declared primary appended and deduped, and
        Lever documents only that the primary "also appears in the allLocations
        array" — no ordering guarantee. Reading the first
        element would let a posting whose `allLocations` happened to lead with a
        different site (Stockholm ahead of the declared New York) flag the
        wrong location primary and hang the posting's one country code on it —
        the country invention this docstring forbids, arriving through
        the back door. A posting that declares no primary gets none: an
        `is_primary` nobody asserted is worth less than an absent one.

        Salary is optional per tenant and often absent. Absent from a successful
        response is the employer's answer, so the description-based fallback
        (`enrich`) stays the
        route to a number and this records that the structured fields were empty.
        """
        country = item.get("country") or None
        declared = categories.get("location")
        primary = clean_location(declared) if isinstance(declared, str) else None
        structured: list[SourceLocation] = [
            SourceLocation(
                label=label,
                country=country if label == primary else None,
                is_primary=label == primary,
            )
            for label in locations
        ]

        commitment = categories.get("commitment")
        components = _salary(item)
        now = datetime.now(UTC)
        return SourceJobFacts(
            provider=self.name,
            access_surface=AccessSurface.PUBLIC_API,
            tenant_identity=self._site(),
            posting_id=req_id,
            source_created_at=parse_datetime(item.get("createdAt")),
            employment_type_raw=str(commitment) if commitment else None,
            employment_type_normalized=_COMMITMENT.get(
                str(commitment or "").strip().lower(), EmploymentType.UNKNOWN
            ),
            locations=structured,
            compensation=CompensationFacts(
                tiers=[CompTier(components=components)] if components else [],
                state=(
                    RetrievalState.PRESENT
                    if components
                    else RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE
                ),
                observed_at=now,
            ),
            observed_at=now,
        )


def _salary(item: dict) -> list[CompComponent]:
    """`salaryRange` when the tenant publishes it; nothing invented when not."""
    band = item.get("salaryRange")
    if not isinstance(band, dict):
        return []
    low, high = band.get("min"), band.get("max")
    if low is None and high is None:
        return []
    return [
        CompComponent(
            type="salary",
            min=float(low) if isinstance(low, int | float) else None,
            max=float(high) if isinstance(high, int | float) else None,
            currency=band.get("currency") or None,
            interval=str(band.get("interval") or "").lower() or None,
            source_text=item.get("salaryDescriptionPlain") or item.get("salaryDescription") or None,
        )
    ]
