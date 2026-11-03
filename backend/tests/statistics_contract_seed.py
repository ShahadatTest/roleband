"""Realistic rows and a pinned clock for the statistics and demand contract.

The statistics routes aggregate over jobs, lifecycle events, skills, clusters,
comp and disclosure snapshots, demand rollups and self-reported pay observations, and read
the clock for "today" and each window. `pin_statistics_clock` fixes both at
`NOW`: `datetime` and the user's local day start (UTC midnight here), in the
router and in `db/queries/jobs.py` (the new-listing clause reads the clock). Every row is written with a fixed
timestamp relative to `NOW`.

| key | what it exercises |
|---|---|
| `g-staff`, `g-staff-2` | one google staff base band twice (one band, two reqs), a stated bonus, python, three and zero updates, a saved role, the pending twin pair |
| `g-principal` | a band written by a retired prompt version (`stale_version`), sql |
| `g-senior` | the open role we first saw earliest, outside a 30-day window, a band with no stated bonus (modeled from the company's observed ladder) |
| `g-hourly`, `g-placeholder` | an hourly band and a `$1–$2` placeholder: `not_yearly` and `implausible`, as bands and as residuals |
| `g-closed` | closed today: counted closed, never listed as updated; employer-dated (the whole closed sample is) |
| `g-fleet-01..15` | fifteen senior roles naming python, enough for "skills that pay", first seen 4 days ago (not new); an industry concept that must never count as a skill; `01` employer-dated AFTER our first sighting (dated, but our sighting is its start) |
| `o-original`, `o-repost` | a lineage: the original first seen 2 days ago (new), the repost today (reposted, not new) with a suspected link awaiting review; a `total` band |
| `o-old`, `o-out` | an opening older than the window, first seen after `g-senior` but dated by its employer 120 days ago: the open role LISTED longest; an out-of-scope role, employer-dated and never counted |
| `n-staff` | no family, an `unclear` band, a public cash-election profile, two updates, reposted once; first seen exactly 3 days ago, the first age that is no longer new |
| `s-senior`, `s-unread` | no estimate; read and disclosing nothing, and not yet read; both first seen a day ago (new) |
| `h-staff` | a company the user hid: in no count, band, rollup, series or employer-dated share (it is dated) |

Every role was stored while its company was already read (`arrival` new), so
each opened at its first sighting: Overview and Pace count every original
role first seen in a window. A test that onboards a company stores its first
read's finds as `first_read`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_company, make_job
from tracker.db.models import (
    Cluster,
    CompanyCompLevel,
    CompanyProfile,
    CompSnapshot,
    DemandMetric,
    DisclosureSnapshot,
    ExternalCompObservation,
    Favorite,
    Job,
    JobLifecycleEvent,
    JobLineageLink,
    JobSkill,
    JobTwinLink,
    Notification,
    SkillConcept,
)
from tracker.intelligence.prompts import PROMPT_VERSION
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)
DAY_START = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
REPORTED_LATEST = date(2026, 7, 15)
#: The plugin whose own self-reported pay points the seed stores, read only
#: while it is installed, on and has read the company.
REPORTS_PLUGIN = "acme-reports"


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def pin_statistics_clock(monkeypatch) -> None:
    """`datetime.now` answers `NOW`, and the user's day starts at UTC midnight of it."""
    import tracker.api.routers.statistics as router
    import tracker.db.queries.jobs as job_queries

    def day_start(now=None, local_tz=None):
        return DAY_START

    monkeypatch.setattr(router, "datetime", _Clock)
    monkeypatch.setattr(router, "local_day_start_utc", day_start)
    monkeypatch.setattr(job_queries, "datetime", _Clock)
    monkeypatch.setattr(job_queries, "local_day_start_utc", day_start)


def _role(company: str, key: str, *, level: str = "staff", family: str | None = "product_management",
          comp: int | None = None, days_open: int = 5, **over) -> Job:
    over.setdefault("arrival", "new")
    return make_job(
        f"{company}-{key}", company=company, dedupe_key=f"{company}:{key}", level_band=level, family=family,
        comp_median=comp, first_seen=NOW - timedelta(days=days_open), last_seen=NOW, **over,
    )


def _stated(low: int, high: int, *, basis: str = "base", period: str = "year", bonus: float | None = None,
            version: str = PROMPT_VERSION) -> dict:
    return {
        "structured_at": NOW - timedelta(days=1), "disclosed_base_min": low, "disclosed_base_max": high,
        "disclosed_currency": "USD", "disclosed_pay_basis": basis, "disclosed_pay_period": period,
        "disclosed_bonus_pct": bonus, "disclosed_confidence": "high", "structured_prompt_version": version,
    }


def _concept(slug: str, display: str, facet: str, category: str) -> SkillConcept:
    return SkillConcept(
        slug=slug, display=display, facet=facet, category=category, description=f"{display}.", taxonomy_version="1",
    )


def _skill(job: Job, concept: SkillConcept, score: int = 80) -> JobSkill:
    return JobSkill(
        job_id=job.id, concept_id=concept.id, importance_score=score, importance_band="core", confidence="high",
        modality="required", content_hash=f"{job.id}-{concept.slug}", extractor_version="2.0.0", taxonomy_version="1",
    )


def _rung(slug: str, label: str, band: str, base: float | None, stock: float | None, bonus: float | None):
    return CompanyCompLevel(
        company_slug=slug, family=REFERENCE_FAMILY, level_label=label, band=band, tc_median=None,
        base_pct=base, stock_pct=stock, bonus_pct=bonus, provider="manual", fetched_at=NOW - timedelta(days=10),
    )


def _observation(slug: str, band: str | None, snapshot: date, n: int, total: int, equity: int):
    """A plugin's point as it sends it: a US point at a level our atlas bands
    when read (L6 is staff at google and netflix), or (`band=None`) a point
    paid in another market, which no US comparison reads."""
    us = band is not None
    return ExternalCompObservation(
        provider=REPORTS_PLUGIN, company_slug=slug, source_level="L6", band=None,
        function="software-engineering",
        location="united-states" if us else "united-kingdom", yoe=9, total_amount=total,
        base_amount=total - equity, equity_amount=equity, bonus_amount=0,
        currency="USD" if us else "GBP", country="US" if us else "GB",
        snapshot_date=snapshot, dedup_key=f"reports|{slug}|{snapshot.isoformat()}|{n}", ingested_at=NOW - timedelta(days=4),
    )


@dataclass(frozen=True)
class SeededStatistics:
    ids: dict[str, int]


async def seed_statistics(session: AsyncSession) -> SeededStatistics:
    session.add_all([
        make_company("hidden-co", "Hidden Co", visible=False, enabled=False, source="url"),
        CompanyProfile(slug="google", display_name="Google", is_public=True, ticker="GOOGL", equity_vehicle="rsu"),
        CompanyProfile(slug="netflix", display_name="Netflix", is_public=True, ticker="NFLX",
                       equity_vehicle="cash_election"),
        CompanyProfile(slug="stripe", display_name="Stripe", is_public=False, equity_vehicle="options"),
    ])
    await session.flush()

    jobs = {
        "g-staff": _role("google", "staff", comp=594000, days_open=5, repost_count=3, **_stated(250000, 320000, bonus=0.15)),
        "g-staff-2": _role("google", "staff-2", comp=594000, days_open=6, **_stated(250000, 320000, bonus=0.15)),
        "g-principal": _role("google", "principal", level="principal", comp=907556, days_open=10,
                             **_stated(340000, 450000, bonus=0.2, version="v0-retired")),
        "g-senior": _role("google", "senior", level="senior", comp=400000, days_open=60, **_stated(200000, 260000)),
        "g-hourly": _role("google", "hourly", level="senior", comp=380000, days_open=8, **_stated(90, 120, period="hour")),
        "g-placeholder": _role("google", "placeholder", level="senior", comp=380000, days_open=8, **_stated(1, 2)),
        "g-closed": _role("google", "closed", comp=594000, days_open=30, status="closed", closed_at=NOW - timedelta(hours=1),
                          posted_at=NOW - timedelta(days=40)),
        "o-original": _role("openai", "original", family="engineering_management", comp=700000, days_open=2,
                            lineage_role="original", **_stated(300000, 380000, basis="total")),
        "o-repost": _role("openai", "repost", comp=700000, days_open=0, lineage_role="repost", repost_count=1),
        "o-old": _role("openai", "old", level="principal", family="engineering_management", comp=850000, days_open=45,
                       posted_at=NOW - timedelta(days=120)),
        "o-out": _role("openai", "out-of-scope", comp=700000, in_scope=False, posted_at=NOW - timedelta(days=200)),
        "n-staff": _role("netflix", "staff", family=None, comp=756250, days_open=3, repost_count=1,
                         **_stated(440000, 725000, basis="unclear")),
        "s-senior": _role("stripe", "senior", level="senior", days_open=1, structured_at=NOW - timedelta(days=1)),
        "s-unread": _role("stripe", "unread", level="senior", days_open=1),
        "h-staff": _role("hidden-co", "staff", comp=999999, days_open=1, posted_at=NOW - timedelta(days=300),
                         **_stated(500000, 600000)),
    }
    for i in range(1, 16):
        jobs[f"g-fleet-{i:02d}"] = _role("google", f"fleet-{i:02d}", level="senior", comp=380000 + i * 5000, days_open=4)
    jobs["g-fleet-01"].posted_at = NOW - timedelta(days=3)
    session.add_all(jobs.values())
    await session.flush()

    python = _concept("python", "Python", "technology", "language")
    sql = _concept("sql", "SQL", "technology", "language")
    fintech = _concept("fintech", "Fintech", "industry", "domain")
    session.add_all([python, sql, fintech])
    await session.flush()
    fleet = [jobs[f"g-fleet-{i:02d}"] for i in range(1, 16)]
    session.add_all(
        [_skill(job, python) for job in [*fleet, jobs["g-staff"], jobs["g-staff-2"]]]
        + [_skill(job, sql, 60) for job in (jobs["g-staff"], jobs["g-principal"], jobs["o-original"])]
        + [_skill(job, fintech) for job in fleet]
    )

    def event(key: str, kind: str, at: datetime) -> JobLifecycleEvent:
        return JobLifecycleEvent(job_id=jobs[key].id, event_type=kind, detail={}, created_at=at)

    session.add_all([
        event("g-fleet-01", "opened", NOW - timedelta(hours=2)),
        event("o-original", "opened", NOW - timedelta(hours=3)),
        event("s-senior", "opened", NOW - timedelta(hours=4)),
        event("h-staff", "opened", NOW - timedelta(hours=1)),
        event("o-repost", "opened", NOW - timedelta(hours=5)),
        event("n-staff", "opened", NOW - timedelta(days=3)),
        event("o-old", "opened", NOW - timedelta(days=45)),
        event("g-closed", "closed", NOW - timedelta(hours=1)),
        event("g-staff", "changed", NOW - timedelta(days=3)),
        event("g-staff", "changed", NOW - timedelta(days=2)),
        event("g-staff", "changed", NOW - timedelta(days=1)),
        event("n-staff", "changed", NOW - timedelta(days=2)),
        event("n-staff", "changed", NOW - timedelta(hours=6)),
        event("o-original", "changed", NOW - timedelta(hours=7)),
        event("g-closed", "changed", NOW - timedelta(days=5)),
        event("g-closed", "changed", NOW - timedelta(days=4)),
    ])

    twin_a, twin_b = sorted((jobs["g-staff"].id, jobs["g-staff-2"].id))
    session.add_all([
        Favorite(job_id=jobs["g-staff"].id, created_at=NOW - timedelta(days=2)),
        Favorite(job_id=jobs["n-staff"].id, created_at=NOW - timedelta(days=1)),
        JobLineageLink(job_id=jobs["o-repost"].id, prior_job_id=jobs["o-original"].id, relation="repost",
                       method="title+embedding", confidence="suspected", status="pending", detector_version="d1"),
        JobLineageLink(job_id=jobs["g-staff-2"].id, prior_job_id=jobs["g-staff"].id, relation="duplicate",
                       method="title+embedding", confidence="auto", status="pending", detector_version="d1"),
        JobTwinLink(job_a_id=twin_a, job_b_id=twin_b, method="embedding", confidence="suspected", status="pending",
                    detector_version="t1"),
        *[
            Notification(created_at=NOW - timedelta(hours=n), priority=priority, category="new_role", title=f"Signal {n}",
                         source_type="event", source_id=n, read_at=read, dismissed_at=dismissed)
            for n, read, dismissed, priority in (
                (1, None, None, "high"), (2, None, None, "normal"), (3, NOW, None, "high"), (4, None, NOW, "high"),
            )
        ],
        # 13 precomputed over every company: one member is hidden-co's, which
        # the overview must not count.
        Cluster(model_version="c1", label="AI platform product", top_terms=[], family_hint="product_management", size=13),
        Cluster(model_version="c1", label="Engineering leadership", top_terms=[], family_hint="engineering_management",
                size=7),
        Cluster(model_version="c1", label="Payments", top_terms=[], family_hint=None, size=3),
        Cluster(model_version="c1", label="Tiny", top_terms=[], family_hint=None, size=1),
        _rung("google", "L6", "staff", 0.4579, 0.4579, 0.0842),
        _rung("google", "L7", "principal", None, None, None),
        _rung("netflix", "L6", "staff", 1.0, 0.0, 0.0),
    ])

    await session.flush()
    clusters = {c.label: c for c in (await session.scalars(select(Cluster))).all()}
    members = {
        "AI platform product": [*(f"g-fleet-{i:02d}" for i in range(1, 13)), "h-staff"],
        "Engineering leadership": ["g-staff", "g-staff-2", "g-principal", "g-senior", "g-hourly", "g-placeholder",
                                   "o-original"],
        "Payments": ["o-old", "n-staff", "s-senior"],
        "Tiny": ["s-unread"],
    }
    for label, keys in members.items():
        for key in keys:
            jobs[key].cluster_id = clusters[label].id

    def demand(day: datetime, company: str, family: str | None, group: str | None, counts: tuple, median: float | None):
        opened, new, closed, reposted, long_open = counts
        return DemandMetric(metric_date=day, company=company, family=family, location_group=group, open_count=opened,
                            new_count=new, closed_count=closed, reposted_count=reposted, long_open_count=long_open,
                            median_days_open=median)

    yesterday = DAY_START - timedelta(days=1)
    session.add_all([
        demand(DAY_START, "google", "product_management", "silicon_valley", (21, 1, 1, 0, 1), 5.0),
        demand(DAY_START, "openai", "engineering_management", None, (3, 1, 0, 1, 1), 23.5),
        demand(DAY_START, "hidden-co", "product_management", None, (1, 1, 0, 0, 0), 1.0),
        demand(yesterday, "google", "product_management", "silicon_valley", (20, 0, 0, 0, 1), 4.0),
    ])

    def comp(day: datetime, company: str, level: str, family: str, values: list[int]) -> CompSnapshot:
        return CompSnapshot(metric_date=day, company=company, level_band=level, family=family, comp_values=values,
                            source="roleband")

    two_days = DAY_START - timedelta(days=2)
    session.add_all([
        comp(yesterday, "google", "staff", "product_management", [594000, 594000]),
        comp(yesterday, "google", "senior", "product_management", [385000, 390000, 400000]),
        comp(yesterday, "openai", "staff", "engineering_management", [700000]),
        comp(yesterday, "netflix", "staff", "", [756250]),
        comp(yesterday, "hidden-co", "staff", "product_management", [999999]),
        comp(two_days, "google", "staff", "product_management", [580000]),
        comp(two_days, "openai", "staff", "engineering_management", [690000]),
        comp(DAY_START - timedelta(days=120), "google", "staff", "product_management", [500000]),
    ])

    def cell(day: datetime, company: str, level: str, basis: str, roles: int, checked: int, bands: list[dict]):
        return DisclosureSnapshot(metric_date=day, company=company, level_band=level, pay_basis=basis, roles=roles,
                                  checked=checked, bands=bands)

    session.add_all([
        cell(yesterday, "google", "staff", "base", 2, 2, [{"low": 250000, "high": 320000, "reqs": 2}]),
        cell(yesterday, "google", "senior", "base", 1, 1, [{"low": 200000, "high": 260000, "reqs": 1}]),
        cell(yesterday, "google", "senior", "", 15, 0, []),
        cell(yesterday, "netflix", "staff", "unclear", 1, 1, []),
        cell(yesterday, "stripe", "senior", "", 2, 1, []),
        cell(yesterday, "hidden-co", "staff", "base", 1, 1, [{"low": 500000, "high": 600000, "reqs": 1}]),
        cell(two_days, "google", "staff", "base", 1, 1, [{"low": 250000, "high": 320000, "reqs": 1}]),
        cell(two_days, "stripe", "senior", "", 2, 0, []),
        cell(DAY_START - timedelta(days=100), "google", "staff", "base", 1, 1, [{"low": 240000, "high": 300000, "reqs": 1}]),
        _observation("google", "staff", REPORTED_LATEST, 1, 600000, 250000),
        _observation("google", "staff", REPORTED_LATEST, 2, 420000, 0),
        _observation("netflix", "staff", REPORTED_LATEST, 1, 800000, 0),
        _observation("openai", None, REPORTED_LATEST, 1, 900000, 400000),
        _observation("hidden-co", "staff", REPORTED_LATEST, 1, 500000, 200000),
        _observation("google", "staff", date(2026, 7, 1), 1, 580000, 240000),
    ])
    await session.commit()
    return SeededStatistics(ids={key: job.id for key, job in jobs.items()})
