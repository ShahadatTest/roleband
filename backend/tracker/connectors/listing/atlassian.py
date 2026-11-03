"""Atlassian — its own careers listing endpoint.

    GET https://www.atlassian.com/endpoint/careers/listings

What `atlassian.com/company/careers/all-jobs` loads in the browser: ONE JSON
array holding every open posting with its description sections and pay text.
Atlassian's iCIMS sitemaps (regional hosts) list only part of the board, while
this endpoint lists the whole board, first-party, so Atlassian is collected
here.

`www.atlassian.com/robots.txt` has no rule matching `/endpoint/careers/listings`
for `User-agent: *` (allowed by absence; the `atlassian-bot` group's
`/company/careers/detail/*` is not ours and not this route), so it is not
walled. The response repeats some rows verbatim: a repeat is deduplicated,
never counted as a lost record.

One request is the whole board, so there is no paging to terminate and
`hydrate()` is a no-op. The row is handed on as `detail_payload`:
`connectors/detail/atlassian.py` builds the sections from its fields and reads a
disclosed band from `payRanges` alone ("base pay range for new hires is: ...").
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

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

LISTINGS_URL = "https://www.atlassian.com/endpoint/careers/listings"
_TENANTS = TenantMap({})
#: Description sections in the order the careers page renders them.
_SECTIONS = ("overview", "responsibilities", "qualifications", "compensation", "payRanges")
_REMOTE = "remote"


def parse_location(raw: str) -> tuple[SourceLocation | None, bool]:
    """One `"City - Country - address"` entry -> (place, remote-eligible).

    The forms: `San Francisco - United States -  San
    Francisco, California 94104 United States` (an office), `Remote - UK -
    Remote` (remote within a country), `Remote - Remote` (remote, no place),
    `Mountain View - United States or Remote - ...` (an office OR remote),
    `Canada -     Canada` (a country only). The third part is a typed street
    address and is never the label: a label is a PLACE.
    """
    parts = [p.strip() for p in raw.split(" - ")]
    parts = [p for p in parts if p]
    if not parts:
        return None, False
    remote = False
    city = parts[0]
    country = parts[1] if len(parts) > 1 else None
    if country and country.lower().endswith(" or remote"):
        country, remote = country[: -len(" or remote")].strip(), True
    if city.lower() == _REMOTE:
        remote = True
        if country is None or country.lower() == _REMOTE:
            return None, True
        label = clean_location(country)
        return (SourceLocation(label=label, country=country) if label else None), True
    if country is None or country.lower() == _REMOTE:
        label = clean_location(city)
        return (SourceLocation(label=label, country=city) if label else None), remote or country is not None
    if city == country:
        label = clean_location(country)
        return (SourceLocation(label=label, country=country) if label else None), remote
    label = clean_location(f"{city}, {country}")
    return (SourceLocation(label=label, country=country, locality=city) if label else None), remote


class AtlassianAdapter(BaseAdapter):
    name = "atlassian"
    posted_date = "none"  # the listing states no date
    board_probe = BoardProbe(
        jobs_url=LISTINGS_URL,
        tenants=_TENANTS,
        # One company, one fixed route: the token names nothing, so the route
        # is built without it (the composite-token hook). The listing
        # states no tenant name, so identity is reported `unstated`.
        tenant_url=lambda _token: LISTINGS_URL,
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    async def fetch(self) -> AsyncIterator[RawJob]:
        resp = await self.context.fetch(FetchRequest(url=LISTINGS_URL, source_key=self.company))
        if resp.status != 200:
            self.drift.invalidate_listing("non-200 listings payload", status=resp.status)
            return
        try:
            rows = resp.json()
        except ValueError:
            self.drift.invalidate_listing("listings payload is not JSON")
            return
        if not isinstance(rows, list):
            self.drift.invalidate_listing("listings payload is not an array")
            return
        self.drift.require(len(rows) > 0, "empty job list")

        seen: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                self.drift.drop_record("listing entry is not an object")
                continue
            req_id = str(row.get("id") or "").strip()
            title = (row.get("title") or "").strip()
            if not req_id or not title:
                self.drift.drop_record("listing missing id/title", keys=list(row)[:8])
                continue
            if req_id in seen:
                # The endpoint repeats some rows verbatim. A
                # repeat that DIFFERS is worth knowing about; neither is a loss.
                if seen[req_id] != row:
                    self.drift.note("listing repeats an id with different content", req=req_id)
                continue
            seen[req_id] = row
            yield self._job(req_id, title, row)

    def _job(self, req_id: str, title: str, row: dict) -> RawJob:
        places: list[SourceLocation] = []
        remote_entries = 0
        raw_locations = row.get("locations")
        if not isinstance(raw_locations, list):
            raw_locations = []
        for raw in raw_locations:
            place, remote = parse_location(str(raw))
            remote_entries += remote
            if place is not None and all(place.label != known.label for known in places):
                places.append(SourceLocation(
                    label=place.label, country=place.country, locality=place.locality,
                    is_primary=not places,
                ))
        body = "".join(str(row[key]) for key in _SECTIONS if isinstance(row.get(key), str) and row[key].strip())
        portal = row.get("portalJobPost")
        if not isinstance(portal, dict):
            portal = {}
        url = portal.get("portalUrl") or row.get("applyUrl") or ""
        kind = row.get("type") if isinstance(row.get("type"), str) else None
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=[p.label for p in places],
            department=(row.get("category") or "").strip() or None,
            description_html=body or None,
            description_complete=bool(row.get("responsibilities") or row.get("overview")),
            # The row itself: `detail/atlassian.py` builds sections from its
            # fields and reads the band from `payRanges` alone.
            detail_payload=row,
            # The posting lists "Remote" as one of its locations: the employer
            # says it can be done remotely. Otherwise this payload says nothing
            # about onsite vs hybrid, so it stays unknown.
            workplace_type=WorkplaceType.REMOTE if remote_entries else WorkplaceType.UNKNOWN,
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity="atlassian",
                posting_id=req_id,
                employment_type_raw=kind,
                employment_type_normalized=(
                    EmploymentType.FULL_TIME if (kind or "").lower().replace("-", " ") == "full time"
                    else EmploymentType.UNKNOWN
                ),
                locations=places,
                # Pay arrives as prose inside the description; the detail
                # parser reads the band from there, so nothing is asserted here.
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )
