"""Shared builders for backend tests: stored rows, a scope, and stand-ins.

A test module takes its rows and doubles from here or from a `*_contract_seed`
module, never from another test module: a test module's helpers change with
its own tests, and a second module leaning on them breaks when they do.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from tracker.db.models import Job, TrackedCompany
from tracker.enrich.enricher import ScopeFilter, annotate
from tracker.platform.drift import SchemaDriftDetector
from tracker.schema import (
    EnrichedJob,
    LevelBand,
    LevelConfidence,
    RawJob,
    WorkplaceType,
    dedupe_key_for,
)

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

#: Adyen's posting states one base band per place, San Francisco's first.
ADYEN_PAY_TEXT = ("The annual base salary range for this role is $258,000 - $348,000 in San Francisco and "
                  "$235,000 - $317,000 in Chicago, plus RSUs.")


def make_job(req_id: str, *, company: str = "google", **over: Any) -> Job:
    """A stored posting in the writer's shape: a staff product manager at
    `company` in Mountain View, open, in scope and first seen at `T0`.

    `over` replaces any field. `dedupe_key` is the company's and the
    requisition's unless given, built as the writer builds it."""
    row: dict[str, Any] = {
        "company": company,
        "req_id": req_id,
        "title": f"Staff Product Manager, {req_id}",
        "url": f"https://careers.example.test/{req_id}",
        "department": "Cloud",
        "team": None,
        "locations": ["Mountain View, CA, USA"],
        "location_groups": ["silicon_valley"],
        "domains": ["ai_ml"],
        "workplace_type": "onsite",
        "level_band": "staff",
        "level_confidence": "confirmed",
        "family": "product_management",
        "track": "product_program",
        "comp_currency": "USD",
        "status": "open",
        "in_scope": True,
        "first_seen": T0,
        "last_seen": T0,
        "description_sections": [],
    }
    row.update(over)
    row.setdefault("dedupe_key", dedupe_key_for(row["company"], row["req_id"]))
    # In the writer's shape: a posting read once with an employer
    # date has that date as the earliest one it ever gave.
    row.setdefault("first_posted_at", row.get("posted_at"))
    return Job(**row)


def make_company(slug: str, display: str, **over: Any) -> TrackedCompany:
    """A followed catalog company on a Greenhouse board whose role catalog
    was read at `T0`; `over` replaces any field."""
    row: dict[str, Any] = {
        "slug": slug,
        "display": display,
        "adapter": "greenhouse",
        "board_token": slug,
        "careers_url": f"https://careers.example.test/{slug}",
        "status": "active",
        "enabled": True,
        "visible": True,
        "source": "catalog",
        "role_catalog_status": "ready",
        "role_catalog_scanned_at": T0,
        "role_catalog_error": None,
        "created_at": T0,
    }
    row.update(over)
    return TrackedCompany(**row)


def scope_filter(
    *,
    bands: Iterable[str],
    roles: Iterable[str],
    tracks: Iterable[str],
    locations: Iterable[str],
    domains: Iterable[str],
    **rest: Any,
) -> ScopeFilter:
    """A `ScopeFilter` named axis by axis. Its five axes share one type, so a
    positional call with two of them swapped still runs; `rest` takes the
    defaulted fields (exclusions, answers) by their own names."""
    return ScopeFilter(
        enabled_bands=frozenset(bands),
        enabled_roles=frozenset(roles),
        enabled_tracks=frozenset(tracks),
        enabled_locations=frozenset(locations),
        enabled_domains=frozenset(domains),
        **rest,
    )


def scope_for(job: RawJob) -> ScopeFilter:
    """A radar that looks for exactly this kind of role, read off the real annotator."""
    ann = annotate(job)
    return scope_filter(
        bands={ann.band.value}, roles={ann.family}, tracks={ann.track.value},
        locations=ann.location_groups, domains=(),
    )


#: Staff engineering managers in the United States: the radar `detail_posting`
#: rows are written for.
STAFF_EM_SCOPE = scope_filter(
    bands={"staff"}, roles={"engineering_management"}, tracks={"management"},
    locations={"united_states"}, domains=(),
)


#: Senior product managers in the United States: the radar `PayingSource`
#: rows pass on their titles, before the detail read decides their level.
SENIOR_PM_SCOPE = scope_filter(
    bands={"senior"}, roles={"product_management"}, tracks={"product_program"},
    locations={"united_states"}, domains=(),
)


class Upserted:
    """What an `app_settings` upsert answers a fake session that records the
    statement: its RETURNING row, holding the value as written
    (`settings_store.set_setting_dict` reads it back)."""

    def __init__(self, stmt: Any) -> None:
        self._row = SimpleNamespace(value=stmt.compile().params["value"])

    def scalar_one(self) -> Any:
        return self._row


class NoComp:
    """A pay resolver that finds nothing, for a collection where pay is not
    what the test is about."""

    async def resolve(self, ctx):
        return None, []


class Allowed:
    """A collection access that lets the read through, for a walled source
    whose consent gate is not what the test is about."""

    def require(self) -> None:
        return None


def detail_posting(index: int) -> RawJob:
    """An engineering manager at acme in Mountain View whose listing carries
    no description: its text exists only once the detail page is read."""
    return RawJob(
        company="acme",
        req_id=f"req-{index}",
        title="Engineering Manager",
        url=f"https://example.test/{index}",
        locations=["Mountain View, CA, USA"],
        description_complete=False,
    )


class DetailSource:
    """A listing of `count` detail postings that records every hydrate call
    and answers each with a full description; otherwise inert."""

    def __init__(self, count: int = 3) -> None:
        self.company = "acme"
        self.drift = SchemaDriftDetector("acme")
        self.truncated = False
        self.query_observations: list = []
        self.hydrated: list[str] = []
        self._count = count

    def location_gaps(self) -> list[str]:
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for index in range(self._count):
            yield detail_posting(index)

    async def hydrate(self, job: RawJob) -> None:
        self.hydrated.append(job.req_id)
        job.description_html = f"<p>Full description for {job.req_id}</p>"
        job.description_complete = True


class PayingSource:
    """Google's listing of bare "Product Manager" titles, posted on `POSTED`.
    Each detail page states the base range `ranges` gives its requisition, in
    Google's own sentence, which the detail connector reads."""

    POSTED = datetime(2026, 6, 1, tzinfo=UTC)

    def __init__(self, ranges: dict[str, tuple[int, int]]) -> None:
        self.company = "google"
        self.drift = SchemaDriftDetector("google")
        self.truncated = False
        self.query_observations: list = []
        self._ranges = ranges

    def location_gaps(self) -> list[str]:
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for req in self._ranges:
            yield RawJob(company="google", req_id=req, title="Product Manager, Google Analytics",
                         url=f"https://example.test/{req}", locations=["Mountain View, CA, USA"],
                         description_complete=False, posted_at=self.POSTED)

    async def hydrate(self, job: RawJob) -> None:
        low, high = self._ranges[job.req_id]
        job.description_html = (
            "<h3>Minimum qualifications:</h3><ul><li>Bachelor's degree.</li></ul>"
            f"<p>The US base salary range for this full-time position is ${low:,}-${high:,} "
            "+ bonus + equity + benefits.</p>"
        )
        job.description_complete = True


def make_enriched(
    *,
    company: str = "acme",
    req_id: str = "1",
    title: str = "Staff Software Engineer",
    family: str | None = "swe",
    level_band: LevelBand = LevelBand.STAFF,
    comp_median: int | None = 500_000,
    locations: list[str] | None = None,
) -> EnrichedJob:
    """An enriched staff posting at `company` as the scan hands it to the
    writer, with a static-seed pay estimate around `comp_median`."""
    raw = RawJob(
        company=company,
        req_id=req_id,
        title=title,
        url=f"https://example.com/{req_id}",
        locations=list(locations or ["Mountain View, CA"]),
        department="Engineering",
        team="Infra",
        description_html="<p>Build things.</p>",
        workplace_type=WorkplaceType.ONSITE,
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_level="L6",
    )
    return EnrichedJob(
        raw=raw,
        level_band=level_band,
        level_confidence=LevelConfidence.CONFIRMED,
        family=family,
        location_groups=["silicon_valley"],
        comp_low=comp_median and int(comp_median * 0.8),
        comp_high=comp_median and int(comp_median * 1.2),
        comp_median=comp_median,
        comp_currency="USD",
        comp_provenance="Acme Staff (static seed)",
        comp_sources=[{"source": "static", "median": comp_median}],
    )
