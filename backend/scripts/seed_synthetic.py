"""Fill the database with a synthetic dataset, so a candidate build can be
validated without scraping anyone.

    python -m scripts.seed_synthetic              # seed (idempotent)
    python -m scripts.seed_synthetic --count 120
    python -m scripts.seed_synthetic --clear      # remove only its own rows

A candidate build is validated against a synthetic API dataset; this is it.
Without it, a fresh clone ends with "there are no jobs yet", and `setup.sh` points the new
contributor at `tracker.daily` -- a LIVE scrape of real employers' boards. In a
public repository that would be every new contributor pointing scrapers at real
job boards in order to look at a UI.

**What it reuses, and why that matters.** Synthetic `RawJob`s go through the real
enrichment (`annotate` + `build_enriched`) and the real persistence seam
(`persist_source`, the same function the pipeline's persist stage calls). Levels,
families, tracks, location groups and comp are therefore COMPUTED rather than
invented, canonical upserts and append-only observations behave exactly as they
do in production, and the ownership registry keeps its writers where they are
declared -- nothing new writes to `jobs`.

**What it deliberately does not do.**

* It registers no source. A synthetic adapter would need a `SOURCE_REVIEWS` row
  carrying a robots sha256 it cannot honestly supply, which is why
  `tests/example_adapter.py` is contained by location rather than registration.
* It resolves comp from `StaticCompProvider` alone, so it makes no network call.
  The pipeline's resolver would read stored and built-in rows first.
* It persists in `ScanMode.DISCOVERY`, which never closes a missing job, counts
  no miss and activates no binding. Fabricated rows must not be able to tell
  this system that a real requisition is gone, or that a binding reads its board.

**One thing it deliberately leaves alone.** The header's "Market data" badge
reads the SCHEDULER's last completed cycle (`ops.py`, `scheduler_status`), not
the run this script opens, so a seeded database still reads "no data yet". That
is true — no scan has run — and faking a scheduler cycle to silence a badge
would make the app lie about whether it has scraped anything. The Board, the
filters, comp and the detail views are all populated regardless.

**Safety.** Every requisition it writes carries the `SYNTH-` prefix, and it
refuses to write to a database holding any job without that prefix. The
longitudinal asset lives in one per-user cluster shared by every checkout
(`docs/development.md`), so a seeder that could not tell the two apart would be a data-loss
bug waiting to happen. It prints the cluster it resolved before it writes, and
`--clear` deletes by that prefix and nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select

from tracker.blueprint import BLUEPRINT
from tracker.comp_providers.static import StaticCompProvider
from tracker.company_store import ensure_builtins, ensure_source_bindings
from tracker.config import get_settings
from tracker.db.models import Job, ScrapeRun
from tracker.db.session import session_scope
from tracker.enrich.comp import CompResolver
from tracker.enrich.enricher import annotate, build_enriched
from tracker.schema import RawJob, WorkplaceType
from tracker.settings_store import set_enabled_bands
from tracker.workflows.collection_types import (
    ScanMode,
    SourceCollection,
    empty_stats,
)
from tracker.workflows.post_passes import PostPassContext, run_post_passes
from tracker.workflows.run_persistence import persist_source

#: The one marker that separates fabricated rows from the asset. Everything in
#: this module keys off it: the refusal, the idempotent upsert, and `--clear`.
SYNTHETIC_PREFIX = "SYNTH-"

#: The bands `_TITLES` produces. Kept beside the titles so the seeded scope and
#: the seeded data cannot drift apart.
_SEEDED_BANDS: tuple[str, ...] = ("senior", "staff", "principal", "director_plus")

#: Reserved by RFC 2606, so a synthetic apply URL can never resolve to a real
#: host even if something follows it.
SYNTHETIC_HOST = "https://jobs.example.invalid"

#: Senior and above on purpose: `CompResolver` returns no estimate below SENIOR
#: rather than fabricating one, so a dataset of junior roles would render a
#: comp-shaped UI with every comp cell empty and prove nothing.
_TITLES: tuple[tuple[str, str], ...] = (
    ("Senior Engineering Manager, Platform", "Engineering"),
    ("Staff Software Engineer, Infrastructure", "Engineering"),
    ("Principal Software Engineer, Distributed Systems", "Engineering"),
    ("Senior Staff Software Engineer, ML Systems", "Engineering"),
    ("Director of Engineering, Developer Platform", "Engineering"),
    ("Senior Product Manager, Growth", "Product"),
    ("Staff Product Manager, Payments", "Product"),
    ("Principal Product Manager, Enterprise", "Product"),
    ("Director of Product Management, Core", "Product"),
    ("Senior Technical Program Manager, Reliability", "Program Management"),
    ("Senior Data Scientist, Experimentation", "Data"),
    ("Staff Machine Learning Engineer, Ranking", "Engineering"),
)

_LOCATIONS: tuple[tuple[str, ...], ...] = (
    ("Mountain View, CA",),
    ("Seattle, WA",),
    ("New York, NY",),
    ("Austin, TX",),
    ("London, United Kingdom",),
    ("Dublin, Ireland",),
    ("Toronto, Canada",),
    ("San Francisco, CA", "New York, NY"),
    ("Remote, United States",),
)

_WORKPLACES: tuple[WorkplaceType, ...] = (
    WorkplaceType.ONSITE,
    WorkplaceType.HYBRID,
    WorkplaceType.REMOTE,
)

_TEAMS: tuple[str, ...] = (
    "Core Platform",
    "Developer Experience",
    "Payments",
    "Search Quality",
    "Identity",
    "Data Infrastructure",
)


def _description_html(title: str, company_name: str, team: str) -> str:
    return (
        f"<p>{company_name} is hiring a {title} on the {team} team. "
        "This posting is synthetic sample data and describes no real vacancy.</p>"
        "<h3>What you will do</h3>"
        "<ul><li>Own a surface end to end, from problem framing to launch.</li>"
        "<li>Partner with engineering, design and data on quarterly bets.</li>"
        "<li>Set the technical direction for a team of senior practitioners.</li></ul>"
        "<h3>What we look for</h3>"
        "<ul><li>Eight or more years of relevant experience.</li>"
        "<li>A track record of shipping at scale.</li></ul>"
    )


def _raw_jobs(count: int, *, seed: int) -> dict[str, list[RawJob]]:
    """Deterministic synthetic postings, grouped by company slug."""
    rng = random.Random(seed)
    companies = sorted(BLUEPRINT)
    now = datetime.now(UTC)
    by_company: dict[str, list[RawJob]] = {}
    for index in range(count):
        slug = companies[index % len(companies)]
        blueprint = BLUEPRINT[slug]
        # Titles ROTATE per company rather than being drawn independently. An
        # independent draw can give one company several identical postings,
        # which is a poor fixture to validate a build against and a
        # misleading duplicate review surface. The offset keeps two companies
        # from presenting their roles in the same order.
        seen_here = len(by_company.get(slug, ()))
        offset = companies.index(slug)
        title, department = _TITLES[(seen_here + offset) % len(_TITLES)]
        locations = list(_LOCATIONS[rng.randrange(len(_LOCATIONS))])
        team = _TEAMS[rng.randrange(len(_TEAMS))]
        req_id = f"{SYNTHETIC_PREFIX}{slug.upper()}-{index:04d}"
        by_company.setdefault(slug, []).append(
            RawJob(
                company=slug,
                req_id=req_id,
                title=title,
                url=f"{SYNTHETIC_HOST}/{slug}/{req_id}",
                locations=locations,
                department=department,
                team=team,
                description_html=_description_html(title, blueprint.display, team),
                workplace_type=_WORKPLACES[rng.randrange(len(_WORKPLACES))],
                posted_at=now - timedelta(days=rng.randrange(1, 60), hours=rng.randrange(24)),
            )
        )
    return by_company


def _safe_dsn() -> str:
    """The resolved connection with any password removed, for the banner."""
    parts = urlparse(get_settings().sync_database_url)
    host = parts.hostname or "(socket)"
    return f"{parts.scheme}://{host}{parts.path}"


async def _foreign_job_count(session) -> int:
    """Jobs this seeder did not write. Non-zero means refuse."""
    return await session.scalar(
        select(func.count())
        .select_from(Job)
        .where(~Job.req_id.startswith(SYNTHETIC_PREFIX))
    )


async def _synthetic_job_count(session) -> int:
    return await session.scalar(
        select(func.count()).select_from(Job).where(Job.req_id.startswith(SYNTHETIC_PREFIX))
    )


async def seed(session, count: int, *, seed_value: int, derived: bool = True) -> int:
    """Persist `count` synthetic postings. Returns the number of jobs now present.

    Takes the session rather than opening one, so a test can run this against the
    suite's scratch database instead of whatever `session_scope()` resolves.

    `derived` runs the post-passes afterwards, which is what fills the market-data
    panel and the Statistics screen — without them the app renders a Board under a
    header reading "No data yet". Tests turn it off: the passes commit per pass and
    one of them wants the embedding model.
    """
    by_company = _raw_jobs(count, seed=seed_value)
    resolver = CompResolver(providers=[StaticCompProvider()])
    try:
        foreign = await _foreign_job_count(session)
        if foreign:
            raise SystemExit(
                f"refusing to seed: {foreign} job(s) here were not written by this "
                f"script (no {SYNTHETIC_PREFIX!r} prefix). This looks like a real "
                "database. Point ROLEBAND_PGDATA at a throwaway cluster and set "
                'ROLEBAND_DATABASE_URL="" for a scratch checkout.'
            )

        # The normal bootstrap: tracked companies, then one binding each with
        # closure withheld pending validation. A fresh clone has neither, and
        # `persist_source` needs the binding for its `scrape_source_runs` row.
        # Both writes happen inside `company_store.py`, which is where the
        # ownership registry already declares them.
        await ensure_builtins(session)
        await ensure_source_bindings(session)

        # Tune the radar for the data about to be created, BEFORE persisting, so
        # `in_scope` is computed against a real scope rather than a default one.
        # Without any scope key the dashboard opens the onboarding wizard instead
        # of the Board (`!profile && !scope_configured`, App.tsx) -- a seeded
        # database would then validate the welcome screen. These are the bands
        # `_TITLES` actually produces.
        await set_enabled_bands(session, list(_SEEDED_BANDS))

        run = ScrapeRun(status="running", scope="targeted")
        session.add(run)
        await session.flush()

        touched: list[int] = []
        per_source: dict[str, dict] = {}
        for company, jobs in sorted(by_company.items()):
            enriched = []
            for job in jobs:
                enriched.append(await build_enriched(job, annotate(job), resolver))
            collection = SourceCollection(
                company=company,
                enriched=enriched,
                seen_keys={job.dedupe_key() for job in jobs},
                stats=empty_stats(),
                drift=[],
                list_complete=False,
            )
            collection.stats["scanned"] = len(jobs)
            collection.stats["kept"] = len(enriched)
            await persist_source(
                session,
                run,
                company,
                collection,
                provider_key="synthetic",
                scan_mode=ScanMode.DISCOVERY,
                max_list=None,
                touched_ids=touched,
            )
            per_source[company] = collection.stats

        run.status = "ok"
        run.finished_at = datetime.now(UTC)
        await session.flush()

        if derived:
            # The same derived-data passes the pipeline runs after persisting.
            # Individually scoped and failure-tolerant, so a machine without the
            # embedding model loses that one pass and keeps the rest.
            await run_post_passes(
                PostPassContext(
                    session=session,
                    touched_ids=touched,
                    per_source=per_source,
                    settings=get_settings(),
                    max_list=None,
                    scan_mode=ScanMode.DISCOVERY,
                )
            )

        return await _synthetic_job_count(session)
    finally:
        await resolver.aclose()


async def clear(session) -> int:
    """Delete only the rows carrying the synthetic prefix. Returns rows removed."""
    jobs = (
        await session.scalars(select(Job).where(Job.req_id.startswith(SYNTHETIC_PREFIX)))
    ).all()
    for job in jobs:
        await session.delete(job)
    await session.flush()
    return len(jobs)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=60, help="postings to create (default 60)")
    parser.add_argument("--seed", type=int, default=20260920, help="RNG seed for reproducibility")
    parser.add_argument("--clear", action="store_true", help="remove synthetic rows and exit")
    args = parser.parse_args()

    print(f"target: {_safe_dsn()}")
    if args.clear:
        async with session_scope() as session:
            removed = await clear(session)
        print(f"Removed {removed} synthetic job(s).")
        return
    async with session_scope() as session:
        total = await seed(session, args.count, seed_value=args.seed)
    print(f"Seeded synthetic data; {total} synthetic job(s) now present.")


if __name__ == "__main__":
    asyncio.run(main())
