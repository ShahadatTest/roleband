"""Amazon — amazon.jobs public search JSON API.

    GET https://www.amazon.jobs/en/search.json?result_limit=100&offset=N&sort=recent
        &normalized_country_code[]=USA&normalized_state_name[]=California

The list response inlines the full `description`, `basic_qualifications`, and
`preferred_qualifications` for every hit, so there is no per-job detail call —
`fetch()` yields complete postings and `hydrate()` is a no-op. Amazon has no
API-side metro filter we can rely on (`loc_query`/`city[]` are geocoded and
ignored without a lat/long anchor), so we narrow source-side by the coarsest
reliable facet and let the downstream substring location-group matching pick the
exact metros, exactly as the Google adapter does.

Country is not coarse enough for the US. The USA query reports `hits=10000` at
every reachable offset and nothing past it, so that number is a result WINDOW
and the query is a view rather than a listing. `fetch()` therefore probes each
group and splits any saturated one along `normalized_state_name[]` —
51 leaves that each fit under the window, plus a shard for the state-less
remote remainder, and an audit that the leaves really do cover what the parent
query showed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from tracker.connectors.listing.base import BaseAdapter, country_manifest
from tracker.platform.paging import expand_saturated
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import RawJob, WorkplaceType

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.amazon.jobs/en/search.json"
_ORIGIN = "https://www.amazon.jobs"
_PAGE = 100  # server honors up to 100 per page
# amazon.jobs refuses any offset at or past this for EVERY query, so `hits` is a
# count only while it is below it. The USA query reports exactly 10000 at every
# reachable offset and 0 past it, while its state facets sum to more: the parts
# exceed the whole, so 10000 is the window.
_RESULT_WINDOW = 10_000
# A query cannot outrun the window, so this is the true page bound rather than a
# guess: a lower one would leave addressable postings unread and trip the page
# ceiling every run.
_MAX_PAGES = _RESULT_WINDOW // _PAGE

# Our location-group slugs -> amazon.jobs source-side query params, by ISO-3166
# alpha-3 country code. US-wide subsumes the Bay Area; the substring/country
# matcher in config.LOCATION_GROUPS re-tags silicon_valley et al. from the metro.
# `normalized_country_code[]` takes ISO alpha-3, so the whole planet is one
# mechanical rule. It fails closed: an unrecognised code returns 0 rather than
# the board, which is what makes generating an entry per country safe, unlike
# `city[]`, which is silently ignored and would re-collect everything
# once per shard.
AMAZON_LOCATION_QUERY: dict[str, list[tuple[str, str]]] = country_manifest(
    lambda c: ("normalized_country_code[]", c.alpha3.upper())
)
#: One search: a location group and the query params that select it.
_Query = tuple[str, Sequence[tuple[str, str]]]

# Refinement facet for a saturated country query. The USA query reports the
# 10,000 window at every offset, so it is a view rather than a listing; asking
# per state turns it back into one: every state is under the window, and
# together the state facets address more than the country query can.
#
# `normalized_state_name[]` is the only US facet that is safe to shard on. It
# takes full names ("WA" returns 0) and an unrecognized value returns 0, so a
# typo under-collects rather than leaking. `city[]` is SILENTLY IGNORED — a
# nonsense city still returns all 10,000 — so a city shard would re-collect the
# whole board once per shard and claim it as coverage.
_US_STATE_FACETS: tuple[str, ...] = (
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
)

#: Per location group, the facets a saturated query splits into. States do not
#: quite partition the US board: a few postings carry no state at all, and they
#: are `city="Virtual"` remote roles, high-value and invisible to every state
#: shard. `normalized_location[]=USA` is the shard
#: that reaches them. GBR/SGP are far under the window and never split.
_REFINEMENTS: dict[str, list[tuple[str, tuple[str, str]]]] = {
    "united_states": [
        *((state, ("normalized_state_name[]", state)) for state in _US_STATE_FACETS),
        ("state-less", ("normalized_location[]", "USA")),
    ],
}

#: Share of the audit sample the leaves may miss before the refinement stops
#: counting as a partition. Not zero: the sample is taken before the leaf scan,
#: and a posting filled during the leaf scan in between is a legitimate miss.
_AUDIT_MISS_TOLERANCE = 0.05


def _audit_offsets() -> list[int]:
    """Offsets sampled from a saturated parent query to audit its refinement.

    Spread across the window on purpose: `sort=recent` puts the newest postings
    at offset 0, and a facet hole would hide in the OLD stratum — exactly the
    postings the window was already biased against. Derived from the window
    rather than fixed so the sample follows a retuned constant.
    """
    return sorted({0, _RESULT_WINDOW // 2, max(0, _RESULT_WINDOW - _PAGE)})


class AmazonAdapter(BaseAdapter):
    name = "amazon"
    posted_date = "published"  # `posted_date`
    listing_scope = "windowed"  # country queries, saturated ones split by state and audited
    location_queries = AMAZON_LOCATION_QUERY
    #: `hits` sizes each group's listing below the window; at the
    #: window the query is marked `truncated`, which the check stands down for.
    declares_total = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Forwarded verbatim, so a bound the base gains needs no edit here.
        super().__init__(*args, **kwargs)
        #: req_ids the saturated parent queries showed us, sampled before the
        #: refined vocabulary replaced them. Empty when nothing was refined.
        self._audit_sample: set[str] = set()
        #: How many strata we set out to sample, and how many actually came
        #: back. They must match: a sample that partly failed makes the audit
        #: EASIER to pass (fewer postings to account for) while testing less,
        #: so counting is the only way to tell a clean audit from a hollow one.
        self._audit_expected = 0
        self._audit_landed = 0

    async def fetch(self) -> AsyncIterator[RawJob]:
        # A saturated country query is a view of the board, not the board. Ask
        # the source what each query declares, and split the ones that come back
        # with the window instead of a count.
        queries = await expand_saturated(
            self.planned_location_items(),
            declared_total=self._declared_total,
            refine=self._refine,
            window=_RESULT_WINDOW,
        )
        seen: set[str] = set()
        async for job in self.scan_location_queries(queries, self._fetch_group, seen=seen):
            yield job
        self._audit_partition(seen)

    def _refine(self, query: _Query) -> list[_Query]:
        """Split one location group into the source's own declared facets."""
        group, loc_params = query
        return [
            (f"{group}/{label}", [*loc_params, param])
            for label, param in _REFINEMENTS.get(group, ())
        ]

    async def _declared_total(self, query: _Query) -> int | None:
        """Probe one query's `hits`, and sample it when it is about to be split.

        Returning ``None`` keeps the query whole, so a probe failure degrades to
        the unrefined query rather than dropping the group. The
        listing pass that follows records the real drift; noting it here too
        would double-report one broken endpoint every run.
        """
        group, loc_params = query
        if not self._refine(query):
            # Nothing to split this into, so the answer cannot change what we
            # do — and `_fetch_group` still detects saturation from its own
            # first page. Skipping the probe saves a request per unrefinable
            # group (GBR, SGP) that would otherwise be spent to learn nothing.
            return None
        head_offset, *deeper = _audit_offsets()
        total, items = await self._search_page(loc_params, offset=head_offset)
        if total is None:
            logger.warning("amazon: could not probe declared total (group=%s)", group)
            return None
        if total >= _RESULT_WINDOW and self._refine(query):
            # The probe already paid for the newest stratum; only the deeper
            # samples cost extra requests.
            strata = [items]
            for offset in deeper:
                _, more = await self._search_page(loc_params, offset=offset)
                strata.append(more)
            self._audit_expected += len(strata)
            for stratum in strata:
                if not stratum:
                    continue
                self._audit_landed += 1
                self._bank_sample(stratum)
        return total

    async def _search_page(
        self, loc_params: Sequence[tuple[str, str]], *, offset: int
    ) -> tuple[int | None, list[dict]]:
        """One raw search page: its declared `hits` and its hits."""
        params = [
            ("result_limit", str(_PAGE)),
            ("offset", str(offset)),
            ("sort", "recent"),
            *loc_params,
        ]
        resp = await self.get(_SEARCH_URL, params=params)
        if resp.status_code != 200:
            return None, []
        data = resp.json()
        total = data.get("hits")
        jobs = data.get("jobs")
        return (total if isinstance(total, int) else None, jobs if isinstance(jobs, list) else [])

    def _bank_sample(self, items: list[dict]) -> None:
        # Only postings the leaves could actually yield. A hit we would drop in
        # `_to_rawjob` anyway (no title) is already recorded as drift there, and
        # banking it here would charge the refinement for someone else's bug.
        for item in items:
            req_id = str(item.get("id_icims") or item.get("id") or "")
            if req_id and item.get("title"):
                self._audit_sample.add(req_id)

    def _audit_partition(self, seen: set[str]) -> None:
        """Did the refined vocabulary actually cover the query it replaced?

        The claim refinement makes is strong — that the narrow queries see
        everything the country query saw, and more — and it is the claim that
        re-authorizes closing amazon's jobs. So it is measured rather than
        asserted: postings the parent query showed us that no leaf returned mean
        the facet does not partition the parent, and the honest response is the
        same one a saturated query gets. `truncated`, not drift: an incomplete
        refinement is OUR vocabulary being wrong, not the source misbehaving.

        The audit must first establish that it *ran*. A sample stratum that
        failed to download does not weaken this check, it flatters it: fewer
        postings to account for, and the ones lost are the deep ones. Offset 0
        is the newest stratum and the leaves find it trivially, so an audit
        reduced to offset 0 passes while proving only the easy half — of a
        refinement whose entire purpose is reaching the postings the window
        hid. Not verifying and verifying clean must therefore reach different
        conclusions, and only the latter may claim a complete listing.
        """
        if not self._audit_expected:
            return  # nothing was refined, so there is no claim to audit

        if self._audit_landed < self._audit_expected or not self._audit_sample:
            self.truncated = True
            logger.warning(
                "amazon: partition audit inconclusive — %s of %s sampled strata reached "
                "the source (%s postings); collecting, but not claiming a complete listing",
                self._audit_landed,
                self._audit_expected,
                len(self._audit_sample),
            )
            return

        missed = self._audit_sample - seen
        # Logged unconditionally, so "no misses" and "barely sampled anything"
        # are distinguishable in the run record rather than both reading clean.
        logger.info(
            "amazon: partition audit — %s of %s sampled postings unreachable by any leaf "
            "(%s/%s strata)",
            len(missed),
            len(self._audit_sample),
            self._audit_landed,
            self._audit_expected,
        )
        if len(missed) > _AUDIT_MISS_TOLERANCE * len(self._audit_sample):
            self.truncated = True
            logger.warning(
                "amazon: refinement missed %s of %s sampled postings "
                "(state facets no longer partition the country query)",
                len(missed),
                len(self._audit_sample),
            )

    async def _fetch_group(self, query: _Query, seen: set[str]) -> AsyncIterator[RawJob]:
        group, loc_params = query
        total: int | None = None
        group_ids: set[str] = set()
        unkeyed = 0  # rows served with no id: still rows `hits` includes

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal total
            offset = index * _PAGE
            params = [
                ("result_limit", str(_PAGE)),
                ("offset", str(offset)),
                ("sort", "recent"),
                *loc_params,
            ]
            resp = await self.get(_SEARCH_URL, params=params)
            if resp.status_code != 200:
                self.drift.invalidate_listing(
                    "non-200 search", status=resp.status_code, group=group, offset=offset
                )
                stop()
                return []
            data = resp.json()
            if total is None:
                total = data.get("hits")
                self.drift.require(isinstance(total, int), "missing 'hits' count", group=group)
                if isinstance(total, int) and total >= _RESULT_WINDOW:
                    # Saturated: `hits` is the window, not a count. We collect
                    # everything addressable and say so — claiming a complete
                    # listing here would authorize closing the postings the
                    # window hides.
                    self.truncated = True
            jobs = data.get("jobs")
            if not isinstance(jobs, list):
                self.drift.invalidate_listing("missing 'jobs' array", group=group, offset=offset)
                stop()
                return []
            if not jobs:
                if isinstance(total, int) and offset < total:
                    self.drift.invalidate_listing(
                        "jobs ended before hits count", group=group, offset=offset, total=total
                    )
                stop()
                return []
            if isinstance(total, int) and offset + _PAGE >= total:
                stop()
            return jobs

        # `group` is the group NAME — `_fetch_group` unpacked it from the
        # (name, params) tuple above. It is the tuning key on its own; indexing
        # it would take the first CHARACTER and collapse every query into a row
        # per letter ("u", "s"). Keying on the
        # whole tuple would be the opposite failure: any facet edit would start
        # a fresh row and re-learn from nothing.
        async for item in self.paged_listing(
            fetch_page,
            max_pages=_MAX_PAGES,
            query_key=group,
            declared_total=lambda: total,
            page_size=_PAGE,
            group=group,
        ):
            # The group's own rows, before the cross-group dedupe.
            key = item.get("id_icims") or item.get("id") if isinstance(item, dict) else None
            if key:
                group_ids.add(str(key))
            else:
                unkeyed += 1
            job = self._to_rawjob(item)
            if job is None or job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        self.close_listing(declared=total, unique=len(group_ids) + unkeyed, field="hits", group=group)

    def _to_rawjob(self, item: dict) -> RawJob | None:
        req_id = str(item.get("id_icims") or item.get("id") or "")
        title = item.get("title")
        job_path = item.get("job_path")
        if not req_id or not title:
            # One unusable row, not a broken listing — see `drop_record`.
            self.drift.drop_record(
                "hit missing id_icims/title", keys=list(item.keys())[:8]
            )
            return None

        locations: list[str] = []
        primary = clean_location(item.get("normalized_location"))
        if primary:
            locations.append(primary)
        # `locations` is a list of JSON-encoded objects; each carries its own
        # normalizedLocation so multi-site roles match every relevant metro.
        for entry in item.get("locations") or []:
            name = None
            if isinstance(entry, str):
                try:
                    name = clean_location(json.loads(entry).get("normalizedLocation"))
                except (ValueError, AttributeError, TypeError):
                    name = None
            elif isinstance(entry, dict):
                name = clean_location(entry.get("normalizedLocation") or entry.get("location"))
            if name and name not in locations:
                locations.append(name)

        url = f"{_ORIGIN}{job_path}" if job_path else _ORIGIN
        # The list payload carries the complete description + qualifications, so the
        # detail connector structures straight from it — no hydrate round-trip.
        detail_payload = {
            "description": item.get("description"),
            "basic_qualifications": item.get("basic_qualifications"),
            "preferred_qualifications": item.get("preferred_qualifications"),
        }

        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=locations,
            department=item.get("job_category") or item.get("business_category"),
            team=(item.get("team") or {}).get("label") if isinstance(item.get("team"), dict) else None,
            description_html=item.get("description"),
            detail_payload=detail_payload,
            workplace_type=WorkplaceType.UNKNOWN,
            posted_at=parse_datetime(item.get("posted_date")),
        )
