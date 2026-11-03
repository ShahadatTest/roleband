"""Ashby public job-board API, one board per tenant.

    GET https://api.ashbyhq.com/posting-api/job-board/{name}

The payload inlines `descriptionHtml`/`descriptionPlain` for every posting, so it
can exceed 10 MB. We stream it to a temp file and parse incrementally with ijson
to keep memory flat.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import TypedDict

import ijson

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.platform.clock import SourceClock
from tracker.platform.http import stream_with_retry
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import (
    AccessSurface,
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

BOARD_NAMES = {"openai": "openai"}
_TENANTS = TenantMap(BOARD_NAMES)

_WORKPLACE_MAP: dict[str | None, WorkplaceType] = {
    "OnSite": WorkplaceType.ONSITE,
    "Onsite": WorkplaceType.ONSITE,
    "Remote": WorkplaceType.REMOTE,
    "Hybrid": WorkplaceType.HYBRID,
}

#: Ashby's own words -> ours. The raw string is kept alongside regardless, so an
#: unmapped value degrades to UNKNOWN instead of being lost or guessed at.
_EMPLOYMENT_MAP = {
    "fulltime": EmploymentType.FULL_TIME,
    "parttime": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "intern": EmploymentType.INTERN,
    "temporary": EmploymentType.TEMPORARY,
}

#: `"1 YEAR"` -> `year`. Ashby states a count and a unit; a count other than one
#: is not something we can flatten into an interval, so it stays unmapped.
_INTERVALS = {"YEAR": "year", "MONTH": "month", "WEEK": "week", "DAY": "day", "HOUR": "hour"}


class AshbyAdapter(BaseAdapter):
    name = "ashby"
    posted_date = "published"  # `publishedAt`
    #: No `identity_url`: the response is `{jobs, apiVersion}` and names no
    #: tenant, so a wrong-but-live board name cannot be caught by a probe.
    board_probe = BoardProbe(
        jobs_url="https://api.ashbyhq.com/posting-api/job-board/{token}",
        tenants=_TENANTS,
    )

    def _board_name(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token)

    async def fetch(self) -> AsyncIterator[RawJob]:
        board = self._board_name()
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"

        # Stream to a temp file so a multi-MB body never lands fully in memory.
        # Opening the stream goes through the shared retry policy, so a 429 +
        # Retry-After backs off exactly like every other adapter request.
        #
        # The deadline and breaker are passed explicitly: the whole body is
        # drained *before* `ijson` yields its first posting, so the per-item
        # cooperative check in the pipeline cannot fire during the download.
        # Without them the hard backstop (which discards data) would be the only
        # limit, and an uncapped `Retry-After` sleep would be unbounded.
        with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
            async with stream_with_retry(
                self.client,
                "GET",
                url,
                retry=self._retry_policy(),
                limiter=self._limiter,
                breaker=self._breaker,
                deadline=self._deadline,
                log_name=self.name,
                params={"includeCompensation": "true"},
            ) as resp:
                if resp.status_code != 200:
                    self.drift.board_missing("non-200 job board", status=resp.status_code)
                    return
                async for chunk in resp.aiter_bytes():
                    tmp.write(chunk)
                    # Bytes arriving are the only liveness evidence available
                    # during a large download; without this the stall window
                    # would expire mid-transfer on a perfectly healthy board.
                    if isinstance(self._deadline, SourceClock):
                        self._deadline.progress()
            tmp.flush()
            tmp.seek(0)

            listed = 0
            for posting in ijson.items(tmp, "jobs.item"):
                if isinstance(posting, dict) and posting.get("isListed") is not False:
                    listed += 1
                job = self._to_rawjob(posting)
                if job is not None:
                    yield job
            if listed:
                return
            # Nothing listed. Counting `jobs.item` alone cannot tell an empty
            # array from a body with no `jobs` key, and only the empty array is
            # positive empty evidence. Unlisted
            # rows are the tenant's drafts, not postings: a board of only those
            # lists nothing. An unknown token answers 404.
            tmp.seek(0)
            if any(isinstance(jobs, list) for jobs in ijson.items(tmp, "jobs")):
                self.drift.board_empty("jobs array present with no listed postings")
            else:
                self.drift.invalidate_listing("missing 'jobs' array in payload")

    def _to_rawjob(self, posting: dict) -> RawJob | None:
        if posting.get("isListed") is False:
            return None
        req_id = str(posting.get("id") or "")
        title = posting.get("title")
        if not req_id or not title:
            # One unusable row, not a broken listing — see `drop_record`.
            self.drift.drop_record(
                "posting missing id/title", keys=list(posting.keys())[:8]
            )
            return None

        locations = []
        primary = clean_location(posting.get("location"))
        if primary:
            locations.append(primary)
        for sec in posting.get("secondaryLocations") or []:
            name = clean_location(sec.get("location") if isinstance(sec, dict) else sec)
            if name and name not in locations:
                locations.append(name)

        workplace = _WORKPLACE_MAP.get(posting.get("workplaceType"), WorkplaceType.UNKNOWN)
        if workplace is WorkplaceType.UNKNOWN and posting.get("isRemote"):
            workplace = WorkplaceType.REMOTE

        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=posting.get("jobUrl") or posting.get("applyUrl") or "",
            locations=locations,
            department=posting.get("department"),
            team=posting.get("team"),
            description_html=posting.get("descriptionHtml"),
            detail_payload=posting,
            workplace_type=workplace,
            posted_at=parse_datetime(posting.get("publishedAt")),
            # Built HERE, at yield time: `detail_payload` is cleared once the
            # detail connector has run, so anything read later is read from None.
            source_facts=self._facts(posting, req_id),
        )

    def _facts(self, posting: dict, req_id: str) -> SourceJobFacts:
        """Employment type, structured addresses, and every tier the board states.

        A posting may carry several tiers. Each tier is a complete offer for a different location or level, so they
        are stored whole — a min/max taken across tiers is a band no employer
        ever offered. Components keep their own currency and interval for the
        same reason: an equity percentage is not an equity amount.
        """
        locations: list[SourceLocation] = []
        primary = clean_location(posting.get("location"))
        if primary:
            locations.append(
                SourceLocation(label=primary, is_primary=True, **_address(posting.get("address")))
            )
        for sec in posting.get("secondaryLocations") or []:
            if not isinstance(sec, dict):
                continue
            name = clean_location(sec.get("location"))
            if name and all(name != known.label for known in locations):
                locations.append(SourceLocation(label=name, **_address(sec.get("address"))))

        raw_type = posting.get("employmentType")
        compensation = posting.get("compensation")
        tiers = _tiers(compensation) if isinstance(compensation, dict) else []
        now = datetime.now(UTC)
        return SourceJobFacts(
            provider=self.name,
            access_surface=AccessSurface.PUBLIC_API,
            tenant_identity=self._board_name(),
            posting_id=req_id,
            # The board API names no separate underlying job id: a posting's
            # key set has `id` and nothing else. Absent, not guessed.
            #
            # `publishedAt` is Ashby's own "when the job was LAST published", so
            # it lands on `last_published_at`. Reading it as first publication
            # makes a claim the board never made: a republished posting moves
            # the field, and RoleBand would record that movement as the role
            # first appearing. First
            # publication stays unknown — Greenhouse states `first_published`
            # and Ashby does not, and an absent field is not a licence to reuse
            # the nearest one.
            last_published_at=parse_datetime(posting.get("publishedAt")),
            source_updated_at=parse_datetime(posting.get("updatedAt")),
            employment_type_raw=str(raw_type) if raw_type else None,
            employment_type_normalized=_EMPLOYMENT_MAP.get(
                str(raw_type or "").replace(" ", "").replace("-", "").lower(),
                EmploymentType.UNKNOWN,
            ),
            locations=locations,
            compensation=CompensationFacts(
                tiers=tiers,
                # The board answers compensation in the SAME response, so a
                # posting with none has told us there is none — a fact about the
                # employer, not about our retrieval.
                state=(
                    RetrievalState.PRESENT
                    if tiers
                    else RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE
                ),
                observed_at=now,
            ),
            observed_at=now,
        )


class _Address(TypedDict):
    country: str | None
    region: str | None
    locality: str | None


def _address(address: object) -> _Address:
    """Only what the source declares as a country/region/locality.

    `addressCountry` is whatever Ashby's tenant typed — "US", "United States",
    "Deutschland". It is preserved verbatim and never validated into an ISO code
    we would then be asserting on the employer's behalf.

    **Two documented shapes, not one.** Ashby nests the primary address under
    `postalAddress` and states the secondary one's fields directly under
    `address`. Reading only the nested form is not
    a partial read of the secondary shape — it loses country, region AND
    locality on every secondary location, while the label survives, so the loss
    is invisible downstream. Both forms are accepted here rather than branching
    at the two call sites: which shape a payload uses is the source's business,
    and a tenant serving the nested form in a secondary slot should not be
    punished for it.
    """
    if not isinstance(address, dict):
        return {"country": None, "region": None, "locality": None}
    postal = address.get("postalAddress")
    fields = postal if isinstance(postal, dict) else address
    return {
        "country": fields.get("addressCountry") or None,
        "region": fields.get("addressRegion") or None,
        "locality": fields.get("addressLocality") or None,
    }


def _tiers(compensation: dict) -> list[CompTier]:
    """Prefer the full tier list; fall back to the board's summary components.

    `compensationTiers` is the complete statement. `summaryComponents` is the
    one-tier flattening Ashby also serves, and reading it as a SECOND tier would
    double every posting that carries both.
    """
    declared = compensation.get("compensationTiers")
    if isinstance(declared, list) and declared:
        return [
            CompTier(
                title=tier.get("title") or None,
                additional_information=tier.get("additionalInformation") or None,
                components=_components(tier.get("components")),
            )
            for tier in declared
            if isinstance(tier, dict)
        ]
    components = _components(compensation.get("summaryComponents"))
    if not components:
        return []
    return [
        CompTier(
            title=compensation.get("compensationTierSummary") or None,
            components=components,
        )
    ]


def _components(raw: object) -> list[CompComponent]:
    parts: list[CompComponent] = []
    for part in raw if isinstance(raw, list) else []:
        if not isinstance(part, dict):
            continue
        kind = part.get("compensationType")
        if not kind:
            continue
        # "1 YEAR" -> year; anything else keeps no interval rather than a wrong one.
        interval_words = str(part.get("interval") or "").split()
        interval = None
        if len(interval_words) == 2 and interval_words[0] == "1":
            interval = _INTERVALS.get(interval_words[1].upper())
        elif len(interval_words) == 1:
            interval = _INTERVALS.get(interval_words[0].upper())
        parts.append(
            CompComponent(
                type=str(kind).lower(),
                min=_number(part.get("minValue")),
                max=_number(part.get("maxValue")),
                currency=part.get("currencyCode") or None,
                interval=interval,
                source_text=part.get("summary") or None,
            )
        )
    return parts


def _number(value: object) -> float | None:
    """A JSON number as a float, or None — `Decimal` included.

    `Decimal` is not a fussy edge case here, it is the ONLY type this adapter
    ever sees for a fractional amount: `fetch()` parses with `ijson`, which
    yields `Decimal` for any number carrying a fraction and `int` for the rest.
    Accepting `int | float` alone would keep every whole salary and silently
    null every fractional one: equity percentages, which Ashby states
    fractionally (`0.5` to `1.75`), would read as equity stated without an
    amount. A test that builds payloads from Python dicts holds floats and
    never crosses this parser boundary.

    Non-finite values are rejected: `float('nan')` is not JSON-serializable and
    would fail at persistence, far from here. `bool` stays rejected — Python
    says it is an `int`, Ashby does not.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    number = float(value)
    return number if isfinite(number) else None
