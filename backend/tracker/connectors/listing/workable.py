"""Workable — public board widget API (multi-tenant).

    GET https://apply.workable.com/api/v1/widget/accounts/{token}?details=true

One request returns the WHOLE board: `{"name": ..., "description": ..., "jobs":
[...]}`, each job carrying its full `description` HTML. So there is no paging to
terminate and no detail route to call — `fetch()` yields complete postings and
`hydrate()` stays a no-op, like Lever.

`apply.workable.com/robots.txt` is `Disallow:` with an empty value — RFC 9309's
"nothing is disallowed" — and declares no `Crawl-delay`, so the 2.0s default
pacer needs no per-adapter override. Its `Content-Signal` line is recorded in
`source_review.SOURCE_REVIEWS["workable"]`, not here: this module reaches a
source, and what we are permitted to do with what comes back is a review
decision.

**The token is the account slug**, the same segment a tenant's public board URL
uses (`apply.workable.com/{token}/`). The board states its own name, so a
token check can settle whose board it is — see `BoardProbe.identity_url`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from tracker.connectors.extract.payload import text_of
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

#: Company slug -> Workable account slug. A DB-registered company overrides via
#: `board_token` without a code change; there is no built-in tenant, so the
#: map is empty and `TenantMap` falls through to the company slug.
WORKABLE_ACCOUNTS: dict[str, str] = {}
_TENANTS = TenantMap(WORKABLE_ACCOUNTS)

_ACCOUNT_ROOT = "https://apply.workable.com/api/v1/widget/accounts/{token}"

#: Workable's own `employment_type` vocabulary, hyphenated where Lever's
#: `commitment` is spaced ("Full-time" vs "Full time"), which is why this is its
#: own table rather than a shared one — a per-source vocabulary belongs to its
#: source. Normalized alongside the raw string, never instead of it.
_EMPLOYMENT = {
    "full time": EmploymentType.FULL_TIME,
    "part time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "contractor": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "internship": EmploymentType.INTERN,
    "intern": EmploymentType.INTERN,
}


class WorkableAdapter(BaseAdapter):
    name = "workable"
    #: `published_on`, else `created_at`: declared as the weaker of the two,
    #: since that is what it can be.
    posted_date = "created"
    board_probe = BoardProbe(
        jobs_url=_ACCOUNT_ROOT,
        tenants=_TENANTS,
        # The account payload names its tenant, so a 200 from the WRONG
        # account is detectable here, and the route is the same one `fetch`
        # uses rather than a second endpoint that could drift away from it.
        identity_url=_ACCOUNT_ROOT,
    )
    #: One buffered GET of a JSON board. No streaming, no render, no POST —
    #: declaring the minimum is what makes capability negotiation useful.
    required_capabilities = Capabilities(
        stream=False, post=False, impersonate=False, render=False
    )

    def _account(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token)

    async def fetch(self) -> AsyncIterator[RawJob]:
        token = self._account()
        resp = await self.context.fetch(
            FetchRequest(
                url=_ACCOUNT_ROOT.format(token=token),
                query={"details": "true"},
                source_key=self.company,
            )
        )
        if resp.status != 200:
            self.drift.board_missing("non-200 account payload", status=resp.status)
            return
        data = resp.json()
        if not isinstance(data, dict):
            self.drift.invalidate_listing("account payload is not an object")
            return
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            self.drift.invalidate_listing("missing 'jobs' array in payload")
            return
        if not jobs:
            # The account object answered with its own `jobs` array, empty: the
            # board itself says it lists nothing.
            self.drift.board_empty("jobs array present and empty")
            return

        for job in jobs:
            if not isinstance(job, dict):
                self.drift.drop_record("job entry is not an object")
                continue
            req_id = str(job.get("shortcode") or "")
            title = job.get("title")
            if not req_id or not title:
                # One unusable row, not a broken listing — see `drop_record`.
                self.drift.drop_record(
                    "job missing shortcode/title", keys=list(job.keys())[:8]
                )
                continue

            places = _places(job)
            yield RawJob(
                company=self.company,
                req_id=req_id,
                title=title,
                url=job.get("url") or job.get("shortlink") or "",
                locations=[place.label for place in places],
                department=job.get("department"),
                # `function` is deliberately NOT `team`. It is Workable's own
                # fixed job-function taxonomy ("Engineering", "Science"), which
                # is BROADER than `department` ("Product", "Open Source"), not
                # a sub-unit of it — so reading it as a team inverts the two.
                # It is also optional: many rows leave it empty.
                # The whole job dict reaches `detail_payload`, so nothing is
                # lost by declining to promote it into a field that means
                # something else.
                description_html=job.get("description"),
                # Completeness is OBSERVED, never assumed. `?details=true` is
                # what puts the body in the listing, so a payload fetched
                # without it — or a row the tenant left empty — carries no
                # description at all, and claiming otherwise would tell the
                # pipeline it holds a body it does not have. There is no detail
                # route to recover it from either: `hydrate()` is a no-op here,
                # so the claim would never be corrected.
                description_complete=bool((job.get("description") or "").strip()),
                detail_payload=job,
                workplace_type=_workplace(job.get("telecommuting")),
                posted_at=parse_datetime(job.get("published_on") or job.get("created_at")),
                source_facts=self._facts(job, req_id, token, places),
            )

    def _facts(
        self, job: dict, req_id: str, token: str, places: list[SourceLocation]
    ) -> SourceJobFacts:
        """What Workable states, and nothing adjacent to it.

        `shortcode` is the posting and the only identifier in the payload: there
        is no separate underlying-job id, so `source_job_id` stays absent rather
        than repeating the posting id under a second name. `code` is the
        employer's own requisition string and is frequently `""` or `null` —
        both mean "not stated", and neither is a label.
        """
        raw_type = job.get("employment_type")
        return SourceJobFacts(
            provider=self.name,
            access_surface=AccessSurface.PUBLIC_API,
            tenant_identity=token,
            posting_id=req_id,
            requisition_label=text_of(job.get("code")),
            first_published_at=parse_datetime(job.get("published_on")),
            source_created_at=parse_datetime(job.get("created_at")),
            employment_type_raw=text_of(raw_type),
            employment_type_normalized=_EMPLOYMENT.get(
                str(raw_type or "").strip().lower().replace("-", " ").replace("_", " "),
                EmploymentType.UNKNOWN,
            ),
            locations=places,
            # The widget payload carries no pay fields at all, on any board.
            # Not asking is its own answer and must never read as "the employer
            # disclosed nothing".
            compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
            observed_at=datetime.now(UTC),
        )


def _workplace(telecommuting: object) -> WorkplaceType:
    """`telecommuting` is one boolean, so it can answer exactly one question.

    True means the employer flagged the role as remote. False does NOT mean
    onsite — Workable has no field distinguishing onsite from hybrid, so
    reading the absent flag as ONSITE would assert a placement the board never
    made. It stays UNKNOWN, which is the same rule `SourceLocation` follows for
    a country it was not given.
    """
    return WorkplaceType.REMOTE if telecommuting is True else WorkplaceType.UNKNOWN


def _places(job: dict) -> list[SourceLocation]:
    """Structured locations, preferring the array the source structures itself.

    `locations[]` states `city`/`region`/`country` per entry and is the only
    form that can express a multi-location posting; the top-level
    `city`/`state`/`country` triple mirrors the first entry and is the fallback
    when the array is absent. `countryCode` is deliberately not read: the
    country name is what the tenant typed, and promoting a two-letter code into
    a field we would then be asserting on the employer's behalf is the thing
    `SourceLocation` exists to refuse.

    Each entry's `hidden` flag is a display preference about the employer's own
    advertisement — and the top-level `city` states the same place regardless,
    so it is published either way. Dropping a stated location on it would narrow
    location scope over someone's board styling.
    """
    entries = job.get("locations")
    if not isinstance(entries, list) or not entries:
        entries = [{
            "city": job.get("city"),
            "region": job.get("state"),
            "country": job.get("country"),
        }]

    places: list[SourceLocation] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        locality = text_of(entry.get("city"))
        region = text_of(entry.get("region"))
        country = text_of(entry.get("country"))
        label = clean_location(", ".join(p for p in (locality, region, country) if p))
        if not label or any(label == known.label for known in places):
            continue
        places.append(
            SourceLocation(
                label=label,
                country=country,
                region=region,
                locality=locality,
                is_primary=not places,
            )
        )
    return places
