"""The scan writer: upsert jobs, append observations, emit lifecycle events.

The upsert is the heart of longitudinal tracking. For each enriched job we diff
against current DB state to decide opened / reopened / changed, always append an
observation, and after a company's batch we close jobs that vanished from the
source. The other writes a scan and its passes make to `jobs` live here too:
the classification setters, the listed-rung refresh, absence and closure, and
the saved-scope projection (`apply_saved_scope_to_jobs`, under its lock), which
builds from the scope gate in `db/queries/scope.py`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, case, func, select, text, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key

from tracker.analytics.posting_reality import earliest_posted, plausible_posted
from tracker.connectors.detail.base import sections_to_text
from tracker.connectors.recipes.outcome import USABLE
from tracker.db.arrival import classify_arrivals
from tracker.db.models import (
    Job,
    JobCompEstimate,
    JobLifecycleEvent,
    JobObservation,
    JobSourceIdentity,
    PostingInventory,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
)
from tracker.db.pay_band import (
    CONNECTOR_READER_VERSION,
    BandChange,
    apply_band,
    pay_place_key,
)
from tracker.db.queries.runs import committed_per_source_expr, stale_run_where
from tracker.db.queries.scope import job_scope_expr, load_scope_exclusions
from tracker.health import RunScope
from tracker.pay_disclosure import settle_band
from tracker.platform.locks import advisory_xact_lock
from tracker.platform.util import html_to_text
from tracker.schema import (
    OUR_ESTIMATE_SOURCE,
    ClosureBasis,
    EnrichedJob,
    LevelBasis,
    LevelConfidence,
    RawJob,
    RoleTrack,
    WorkplaceType,
    merge_source_facts,
    parse_band,
)
from tracker.taxonomy.locations import normalize_cities
from tracker.taxonomy.role_answers import RoleAnswer

if TYPE_CHECKING:
    from tracker.enrich.inventory import InventoryRow

#: The smallest move of the employer's date recorded as a `redated` event.
REDATE_MIN = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(UTC)


async def load_fresh_description_keys(
    session: AsyncSession, companies, refresh_days: int
) -> frozenset[str]:
    """Dedupe keys whose description is recent enough not to fetch again.

    Membership means "we hold text AND fetched it within the window", so a row
    with no description is never in here and is always fetched.

    Read once per run and handed to collection, so the hot path never queries per
    job. Non-members are simply fetched, which is the safe direction: an empty
    set fetches every description.
    """
    slugs = list(companies)
    if not slugs or refresh_days <= 0:
        return frozenset()
    cutoff = _now() - timedelta(days=refresh_days)
    rows = await session.scalars(
        select(Job.dedupe_key).where(
            Job.company.in_(slugs),
            Job.description_text.isnot(None),
            Job.description_fetched_at.isnot(None),
            Job.description_fetched_at >= cutoff,
        )
    )
    return frozenset(rows.all())


async def load_known_places(
    session: AsyncSession, companies, refresh_days: int
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Places we hold for open postings read recently: {company: {req_id: places}}.

    For a board whose card says only "Multiple Locations" and whose places live
    on the posting page: the adapter reuses these instead
    of one detail request per posting per scan. Same freshness rule as
    `load_fresh_description_keys` (the detail was read within the window), so a
    stale place is read again rather than trusted forever. Read once per run.
    """
    slugs = list(companies)
    if not slugs or refresh_days <= 0:
        return {}
    cutoff = _now() - timedelta(days=refresh_days)
    rows = await session.execute(
        select(Job.company, Job.req_id, Job.locations).where(
            Job.company.in_(slugs),
            Job.status == "open",
            Job.description_fetched_at.isnot(None),
            Job.description_fetched_at >= cutoff,
        )
    )
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for company, req_id, locations in rows.all():
        if locations:
            out.setdefault(company, {})[req_id] = tuple(locations)
    return out


async def load_held_dates(
    session: AsyncSession, companies
) -> dict[str, dict[str, tuple[datetime | None, datetime]]]:
    """Every held posting's dates: {company: {dedupe_key: (first_posted_at, first_seen)}}.

    What the scan needs to read a pay grade for the year relevel reads it for
    (`level_mapper.level_date`): a posting that states no date is
    dated by our first sight of it, which only the stored row knows. Every
    status, since a closed posting that reopens keeps its first sight. Read
    once per run and handed to collection, like the keys above.
    """
    slugs = list(companies)
    if not slugs:
        return {}
    rows = await session.execute(
        select(Job.company, Job.dedupe_key, Job.first_posted_at, Job.first_seen).where(
            Job.company.in_(slugs)
        )
    )
    out: dict[str, dict[str, tuple[datetime | None, datetime]]] = {}
    for company, key, first_posted_at, first_seen in rows.all():
        out.setdefault(company, {})[key] = (first_posted_at, first_seen)
    return out


async def load_open_keys(session: AsyncSession, companies) -> dict[str, frozenset[str]]:
    """The keys of every open held posting: {company: keys}, a discovery run's frontier.

    Keyed as `load_company_jobs` keys its rows, so the frontier and the writer
    agree on which postings are held: a posting the company's stable binding
    knows by an alias is held under its aliases instead of its own dedupe key,
    and an alias wins over another posting's own key. One statement across the
    companies, reading keys and status only; read once per run, like the keys
    above.
    """
    slugs = list(companies)
    if not slugs:
        return {}
    alias = (
        select(JobSourceIdentity.job_id, JobSourceIdentity.source_key, SourceBinding.company_slug)
        .join(SourceBinding, SourceBinding.id == JobSourceIdentity.binding_id)
        .where(SourceBinding.status == "stable")
        .subquery()
    )
    rows = await session.execute(
        select(Job.company, Job.dedupe_key, Job.status, alias.c.source_key)
        .outerjoin(alias, and_(alias.c.job_id == Job.id, alias.c.company_slug == Job.company))
        .where(Job.company.in_(slugs))
    )
    held: dict[str, dict[str, bool]] = {}
    aliased: list[tuple[str, str, bool]] = []
    for company, key, status, source_key in rows.all():
        if source_key is None:
            held.setdefault(company, {})[key] = status == "open"
        else:
            aliased.append((company, source_key, status == "open"))
    for company, key, is_open in aliased:
        held.setdefault(company, {})[key] = is_open
    return {
        company: frozenset(key for key, is_open in keys.items() if is_open)
        for company, keys in held.items()
    }


async def load_company_jobs(session: AsyncSession, company: str) -> dict[str, Job]:
    """Every held posting of `company` by the key its source reads it under,
    for the writer to diff a scan against.

    The two vectors stay unloaded: the write path never reads them, and a
    reader that did would fail at once (raiseload) rather than load them lazily
    under the async session. The description stays loaded: the writer
    compares a new read against it.
    """
    rows = (
        await session.scalars(
            select(Job)
            .where(Job.company == company)
            .options(
                defer(Job.embedding, raiseload=True), defer(Job.search_vector, raiseload=True)
            )
        )
    ).all()
    existing = {job.dedupe_key: job for job in rows}
    by_id = {job.id: job for job in rows}
    aliases = (await session.execute(select(JobSourceIdentity.source_key, JobSourceIdentity.job_id)
        .join(SourceBinding, SourceBinding.id == JobSourceIdentity.binding_id)
        .where(SourceBinding.company_slug == company, SourceBinding.status == "stable"))).all()
    for _, job_id in aliases:
        if job_id in by_id:
            existing.pop(by_id[job_id].dedupe_key, None)
    for key, job_id in aliases:
        if job_id in by_id:
            existing[key] = by_id[job_id]
    return existing


def _apply_fields(job: Job, e: EnrichedJob, *, keep_comp: bool = False) -> BandChange | None:
    """`keep_comp`: the enrichment estimated nothing (deferred), so the
    job keeps the figures it shows; they move with the next estimate."""
    raw = e.raw
    job.title = raw.title
    job.url = raw.url
    job.department = raw.department
    job.team = raw.team
    # Search/list fallback content is acceptable evidence for a brand-new job,
    # but a transient detail failure must never downgrade an existing full JD.
    # Nor may a read that carries no text: a listing can mark itself complete
    # with empty content, which says nothing about the posting.
    text = sections_to_text(raw.description_sections) or html_to_text(raw.description_html)
    if (raw.description_complete or job.id is None) and (text or not job.description_text):
        job.description_html = raw.description_html
        job.description_sections = [section.as_dict() for section in raw.description_sections]
        job.description_text = text
        # Stamped only where the text was actually (re)written, so the freshness
        # window measures a real fetch. Listing-carried sources land here on
        # every scan — correctly: their text arrives with the listing, costs no
        # request, and is genuinely current.
        if job.description_text:
            job.description_fetched_at = _now()
    job.locations = list(raw.locations)
    job.location_groups = list(e.location_groups)
    job.domains = list(e.domains)
    job.location_cities = normalize_cities(raw.locations)
    job.workplace_type = raw.workplace_type.value
    # Same rule as the description and the posting date above: a read that
    # names no rung has not withdrawn the one a read did name. A listing-only
    # scan and an incomplete detail parse both arrive here with none, and
    # overwriting would leave `level_basis` saying `stated` beside nothing.
    if raw.raw_level is not None or job.id is None:
        job.raw_level = raw.raw_level
    job.level_band = e.level_band.value
    job.level_confidence = e.level_confidence.value
    job.level_basis = e.level_basis.value if e.level_basis is not None else None
    job.family = e.family
    job.track = e.track.value
    if not keep_comp:
        job.comp_low = e.comp_low
        job.comp_high = e.comp_high
        job.comp_median = e.comp_median
        job.comp_currency = e.comp_currency
        job.comp_provenance = e.comp_provenance
        job.comp_base_low = e.comp_base_low
        job.comp_base_median = e.comp_base_median
        job.comp_base_high = e.comp_base_high
        job.comp_component = e.comp_component
        job.comp_provider = e.comp_provider
        job.comp_as_of = e.comp_as_of
        if e.comp_ref_fp is not None:
            job.comp_ref_fp = e.comp_ref_fp
    # A publish or a creation date, per source (`BaseAdapter.posted_date`),
    # never an update time. Stored values cannot be read again from any board,
    # so the column's meaning stays fixed: a source's other dates go into
    # `source_facts` below, each under its real name.
    # Same rule as the description above: some sources date a posting only on
    # its detail page, and a rescan inside `description_refresh_days` skips that
    # read. A run that did not read the detail cannot withdraw the date one did.
    if raw.posted_at is not None or raw.description_complete or job.id is None:
        job.posted_at = raw.posted_at
    # The earliest date the employer ever gave: what the headline
    # age starts from, so a re-date later can never shorten it. Lowered by an
    # earlier date, never raised; a 1970 or a far-future date is ignored.
    job.first_posted_at = earliest_posted(
        job.first_posted_at,
        raw.posted_at,
        raw.source_facts.first_published_at if raw.source_facts is not None else None,
        read_at=_now(),
    )
    # `None` is "this adapter maps no facts", not "the source withdrew them".
    if raw.source_facts is not None:
        job.source_facts = merge_source_facts(job.source_facts, raw.source_facts)
    job.in_scope = True
    # Only a detail parse ever states pay in structure, so an incomplete one is
    # the same partial read whose text is kept out above. Taking its band while
    # refusing its text would store a figure from a page we decided not to
    # believe, under `disclosed_source = "connector"`.
    # A clear only from a reader that looked at what would carry the figure
    # (`raw.pay_looked`), and only of a band the connector owns: otherwise
    # `None` is "this adapter maps no pay field", not "the employer withdrew
    # the band", exactly as for `source_facts` above.
    if (
        raw.source_disclosed_comp is None and raw.pay_looked and raw.description_complete
        and job.id is not None and job.disclosed_source == "connector"
    ):
        return apply_band(
            job, None, source="connector", version=CONNECTOR_READER_VERSION,
            now=_now(), place_key=pay_place_key(raw.locations),
        )
    if raw.source_disclosed_comp is not None and (raw.description_complete or job.id is None):
        stated = raw.source_disclosed_comp
        # An unclear band is settled by the role or a stated salary, and its
        # bonus read against the settled basis, as in the text and page writers.
        settled = settle_band(
            stated.pay_basis, job.description_text, job.family, job.title,
            [stated.base_min, stated.base_max], stated_bonus=stated.bonus_pct,
        )
        values = {
            "disclosed_base_min": stated.base_min,
            "disclosed_base_max": stated.base_max,
            "disclosed_currency": stated.currency or "USD",
            "disclosed_pay_basis": settled.pay_basis,
            "disclosed_pay_period": stated.pay_period,
            "disclosed_snippet": stated.source_snippet,
            "disclosed_confidence": stated.confidence,
            "disclosed_bonus_pct": settled.bonus_pct,
        }
        return apply_band(
            job, values, source="connector", version=CONNECTOR_READER_VERSION,
            now=_now(), place_key=pay_place_key(raw.locations),
        )
    return None


def _snapshot(e: EnrichedJob, kept: dict | None = None) -> dict:
    """What this run OBSERVED — which is not always what the row now says.

    `source_facts` here is the incoming record, not the merged one on `jobs`: a
    compensation tier carried forward because we did not ask this time is the
    current view of the posting and was not an observation. Keeping the two
    apart is what makes the history answer "what did the board say that night?"
    rather than "what did we believe afterwards?".

    Deliberately NOT a lifecycle event. A source may move its update time on
    every body edit, so a `changed` event per fact delta would flood the history
    with events no reader wants.

    The estimate recorded is OURS, whichever source the job shows: the history
    never depends on which plugin was on that night. A run that deferred
    estimates records our stored estimate when the job has one (`kept`), else
    the (empty) projection.
    """
    ours = e.estimates.get(OUR_ESTIMATE_SOURCE) or kept
    return {
        "title": e.raw.title,
        "level_band": e.level_band.value,
        "level_confidence": e.level_confidence.value,
        "level_basis": e.level_basis.value if e.level_basis is not None else None,
        "family": e.family,
        "locations": e.raw.locations,
        "location_groups": e.location_groups,
        "domains": e.domains,
        "comp_median": ours["comp_median"] if ours else e.comp_median,
        "comp_provenance": ours["comp_provenance"] if ours else e.comp_provenance,
        "comp_sources": ours["sources"] if ours else e.comp_sources,
        "source_facts": e.raw.source_facts.as_dict() if e.raw.source_facts else None,
    }


def _deferred(e: EnrichedJob) -> bool:
    """No resolver ran (a row read after its source's time bound,
    `collection.retain(network=False)`, `EnrichedJob.estimated`)."""
    return not e.estimated


def _same_reference(job: Job, e: EnrichedJob) -> bool:
    """Is a `comp_median` move a fact about THIS job?

    Only when the stored estimate and the new one were computed under the same
    reference set; a move from a switch of sources or an atlas edition belongs to
    that switch's one `reference_change`, never to thousands of per-job events.
    An estimate with no reference fingerprint counts every move as the job's."""
    return e.comp_ref_fp is None or job.comp_ref_fp == e.comp_ref_fp


async def record_source_identity(
    session: AsyncSession, *, binding_id: int, job_id: int, source_key: str, now: datetime
) -> int:
    """The alias `(binding, source_key) -> job`, written as the posting is seen.

    Closure scope reads these: a binding may close a posting it owns, and a
    posting owned by another LIVE binding is the rebind case nothing closes.
    Without the write the ownership branch never fires and every posting is
    judged on the no-identity branch instead, which is the whole rule going
    unused rather than a visible failure.

    `last_seen` moves on every sighting; `first_seen` is kept, so the alias
    says when this binding first called the posting by this key.
    """
    stmt = (
        pg_insert(JobSourceIdentity)
        .values(binding_id=binding_id, job_id=job_id, source_key=source_key,
                first_seen=now, last_seen=now, origin="exact_auto")
        .on_conflict_do_update(
            constraint="uq_identity_binding_source_key",
            set_={"last_seen": now},
            where=JobSourceIdentity.job_id == job_id,
        )
        .returning(JobSourceIdentity.id)
    )
    return (await session.execute(stmt)).scalar_one()


async def upsert_job(
    session: AsyncSession,
    run: ScrapeRun,
    e: EnrichedJob,
    existing: dict[str, Job],
    *,
    binding_id: int | None = None,
) -> tuple[Job, bool]:
    """Upsert one enriched job. Returns (job, is_new).

    `binding_id` is the binding this scan read the posting under. None where
    no binding is in scope (a backfill, a test, a company with no binding
    row), and then the posting records no provenance rather than a wrong one.
    """
    now = _now()
    key = e.raw.dedupe_key()
    job = existing.get(key)
    if job is None and binding_id is not None:
        job = await session.scalar(select(Job).join(JobSourceIdentity).where(
            JobSourceIdentity.binding_id == binding_id, JobSourceIdentity.source_key == key,
            Job.company == e.raw.company,
        ))
    is_new = job is None

    if is_new:
        job = Job(
            company=e.raw.company,
            req_id=e.raw.req_id,
            dedupe_key=key,
            status="open",
            first_seen=now,
            last_seen=now,
            total_days_open=0,
            repost_count=0,
        )
        _apply_fields(job, e)
        session.add(job)
        await session.flush()
        _add_event(session, run, job, "opened", {})
    else:
        # Detect material changes before overwriting.
        changes = {}
        if job.title != e.raw.title:
            changes["title"] = {"from": job.title, "to": e.raw.title}
        if job.level_band != e.level_band.value:
            changes["level_band"] = {"from": job.level_band, "to": e.level_band.value}
        if job.family != e.family:
            changes["family"] = {"from": job.family, "to": e.family}
        # A deferred row learned nothing about pay: no move to record.
        if job.comp_median != e.comp_median and not _deferred(e) and _same_reference(job, e):
            changes["comp_median"] = {"from": job.comp_median, "to": e.comp_median}
        # The band the employer actually posted. Recorded separately from
        # `comp_median` because only this one is a fact about THIS job:
        # `comp_median` is a company+level+family cohort lookup, so it moves for
        # every row in a cohort whenever the lookup refreshes, and notifying on
        # it would flood the user with moves no posting made.
        # `notifications.classify_event` reads this key and ignores the other.
        # Kept in `changes` regardless of tracking so the lifecycle history
        # stays complete; the notification layer owns the gate.
        reopened = job.status == "closed"
        posted_before = job.posted_at
        if e.raw.source_facts is not None:
            # `existing` was loaded when the writer started on this company and
            # outlives its commits, while a posting-page read may have written
            # the form, pay tiers or a failure since. The merge below writes the
            # whole field, so it merges into the row as it is now, locked until
            # this write commits.
            await session.refresh(job, attribute_names=["source_facts"], with_for_update=True)
        band = _apply_fields(job, e, keep_comp=_deferred(e))
        if band is not None and band.moved and band.had_band:
            changes["disclosed_base"] = band.event_detail()
        # The employer moved its date. Recorded, because `posted_at`
        # is overwritten and `first_posted_at` keeps only the earliest: the
        # history is the one place a re-dating stays visible. A day of slack,
        # because a board that re-serializes the same date in another timezone
        # has not re-dated anything, and one whose earlier date was a parse
        # accident (an epoch zero) did not have a date to move.
        posted_before = plausible_posted(posted_before, now)
        posted_after = plausible_posted(job.posted_at, now)
        if (
            posted_before is not None
            and posted_after is not None
            and abs(posted_after - posted_before) >= REDATE_MIN
        ):
            _add_event(
                session, run, job, "redated",
                {"from": posted_before.isoformat(), "to": posted_after.isoformat()},
            )
        job.last_seen = now
        job.total_days_open = max(0, (now - job.first_seen).days)
        if reopened:
            job.status = "open"
            job.closed_at = None
            # The basis is evidence for a closure, so it dies with the closure.
            # A re-listed posting still carrying "absent from a complete
            # listing" would assert that about a job the source is listing right
            # now. Every closure keeps its own basis in the lifecycle event; the
            # row only ever describes the CURRENT state.
            job.closure_basis = None
            job.closure_run_id = None
            job.repost_count += 1
            _add_event(session, run, job, "reopened", {})
        if changes:
            _add_event(session, run, job, "changed", changes)

    # Always append an observation (append-only history). A deferred row of a
    # job we already estimated records our stored estimate, not a None no run
    # computed.
    kept = None
    if not is_new and _deferred(e):
        row = await session.get(JobCompEstimate, (job.id, OUR_ESTIMATE_SOURCE))
        if row is not None:
            kept = {"comp_median": row.comp_median, "comp_provenance": row.comp_provenance,
                    "sources": list(row.sources or [])}
    ours = e.estimates.get(OUR_ESTIMATE_SOURCE) or kept
    identity_id = (
        await record_source_identity(
            session, binding_id=binding_id, job_id=job.id, source_key=key, now=now
        )
        if binding_id is not None
        else None
    )
    session.add(
        JobObservation(
            job_id=job.id,
            run_id=run.id,
            observed_at=now,
            title=e.raw.title,
            level_band=e.level_band.value,
            family=e.family,
            locations=list(e.raw.locations),
            comp_median=ours["comp_median"] if ours else e.comp_median,
            payload=_snapshot(e, kept),
            binding_id=binding_id,
            source_identity_id=identity_id,
        )
    )
    await write_estimates(session, job.id, e.estimates)
    return job, is_new


async def write_estimates(session: AsyncSession, job_id: int, estimates: dict[str, dict]) -> None:
    """Each source's estimate for one job, upserted beside the other's."""
    for source, values in estimates.items():
        row = {k: v for k, v in values.items()}
        await session.execute(
            pg_insert(JobCompEstimate)
            .values(job_id=job_id, source=source, estimated_at=_now(), **row)
            .on_conflict_do_update(index_elements=["job_id", "source"], set_={**row, "estimated_at": _now()})
        )


#: The lifecycle event a promoted posting carries. Not `opened`: the
#: readers (digest, velocity, lineage counts, "new today", statistics,
#: notifications) count `opened` as a role that just appeared, and a promoted
#: posting may have been listed for weeks. Every reader ignores a type it does
#: not know, so a new type cannot be miscounted by a reader nobody updated.
ADDED_FROM_INVENTORY = "added"


def _enriched_from_inventory(row: PostingInventory) -> EnrichedJob:
    """The row as a scan would have enriched it, less what only a detail read
    or the comp providers supply (description, comp): the follow-up sync
    brings those."""
    raw = RawJob(
        company=row.company, req_id=row.req_id, title=row.title, url=row.url,
        locations=list(row.locations or []), department=row.department, team=row.team,
        description_complete=False, workplace_type=WorkplaceType(row.workplace_type),
        posted_at=row.posted_at, raw_level=row.raw_level,
    )
    return EnrichedJob(
        raw=raw,
        level_band=parse_band(row.level_band),
        level_confidence=LevelConfidence(row.level_confidence),
        level_basis=LevelBasis(row.level_basis) if row.level_basis else None,
        family=row.family,
        location_groups=list(row.location_groups or []),
        track=RoleTrack(row.track),
        domains=list(row.domains or []),
    )


async def admit_from_inventory(session: AsyncSession, rows: Sequence[PostingInventory]) -> list[Job]:
    """Create `jobs` rows for inventory postings the saved scope now admits.

    Field parity with a scan: the row goes through `_apply_fields` as a
    scanned one does. Then what a scan would not know is set from the
    inventory: `first_seen`/`last_seen` are when a sync first and last read
    the posting, one `added` event (run NULL, `basis: inventory`) and one
    observation under the run that last read it. The caller holds the run
    lock and has checked none of these keys is in `jobs`. `arrival` is set
    before return (`db/arrival.py`). Commits nothing.
    """
    now = _now()
    admitted: list[tuple[Job, PostingInventory, EnrichedJob]] = []
    for row in rows:
        if row.last_seen_run_id is None:
            # Its run is gone (the key is set NULL): no observation can name one. The next scan
            # of the company admits it the normal way.
            continue
        enriched = _enriched_from_inventory(row)
        job = Job(
            company=row.company, req_id=row.req_id, dedupe_key=row.dedupe_key, status="open",
            total_days_open=0, repost_count=0,
        )
        _apply_fields(job, enriched)
        job.first_seen = row.first_seen_at
        job.last_seen = row.last_seen_at
        session.add(job)
        admitted.append((job, row, enriched))
    await session.flush()
    for job, row, enriched in admitted:
        session.add(JobLifecycleEvent(
            job_id=job.id, run_id=None, event_type=ADDED_FROM_INVENTORY,
            detail={"basis": "inventory", "first_seen": row.first_seen_at.isoformat()},
            created_at=now,
        ))
        session.add(JobObservation(
            job_id=job.id, run_id=row.last_seen_run_id, observed_at=row.last_seen_at,
            title=row.title, level_band=row.level_band, family=row.family,
            locations=list(row.locations or []), comp_median=None, payload=_snapshot(enriched),
        ))
    await classify_arrivals(session, [job.id for job, _row, _enriched in admitted])
    return [job for job, _row, _enriched in admitted]


def refresh_held_reads(existing: dict[str, Job], reads: Mapping[str, InventoryRow]) -> list[int]:
    """Carry what a scan read into the held rows it judged out of scope.
    Ids of the rows changed. Commits nothing.

    A posting judged out is not written, so without this it keeps the places
    and title of its last in-scope read, and the run's writer, re-projecting
    the saved scope from stored columns, admits it again from them: a posting
    the board moved to London comes back in at its old place.

    Only the scope inputs a listing restates, each only where it states it:

    * places when the listing names one that classifies into a location
      group. A row with no place, or a card that only counts its places
      ("Multiple Locations", "62 Locations", where the cities are read from
      the page), says nothing about where the posting is; it withdraws none. A real place no group
      knows is a classification gap (`taxonomy/locations`), not evidence;
    * title, and the family, track and worlds read from it, when the board
      retitled the posting. An unchanged title leaves them: they may have
      been read with a department the listing does not carry;
    * team and department, each when the listing states one: a learned
      exclusion rule matches them (`scope_exclusion_expr`).

    Never the level: the stored one may be read from the posting's text or
    page, which a listing guess does not outrank (`refresh_listed_rungs`
    carries a printed rung). Never `in_scope`: the caller projects
    the scope saved NOW from what this wrote, so a save during the scan wins
    over the scope the scan started with."""
    changed: list[int] = []
    for key, read in reads.items():
        job = existing.get(key)
        if job is None or job.id is None:
            continue
        moved = False
        if read.location_groups and list(read.locations) != list(job.locations or []):
            job.locations = list(read.locations)
            job.location_groups = list(read.location_groups)
            job.location_cities = normalize_cities(list(read.locations))
            if read.workplace_type != WorkplaceType.UNKNOWN.value:
                job.workplace_type = read.workplace_type
            moved = True
        if read.title and read.title != job.title:
            job.title = read.title
            job.family = read.family
            job.track = read.track
            job.domains = list(read.domains)
            moved = True
        if read.team and read.team != job.team:
            job.team = read.team
            moved = True
        if read.department and read.department != job.department:
            job.department = read.department
            moved = True
        if moved:
            changed.append(job.id)
    return changed


def apply_scope_state(existing: dict[str, Job], scope_by_key: dict[str, bool]) -> int:
    """Update observed jobs' scope flag without emitting lifecycle events."""
    changed = 0
    for key, in_scope in scope_by_key.items():
        job = existing.get(key)
        if job is None or job.in_scope == in_scope:
            continue
        job.in_scope = in_scope
        changed += 1
    return changed


async def set_job_domains(session: AsyncSession, changes: list[dict]) -> None:
    """Write re-derived worlds, one `{"id", "domains"}` per changed row.

    The reclassify pass owns WHEN; this module owns the write, so `jobs` keeps
    its declared writers. Callers recompute `in_scope` afterwards —
    a world can have just appeared on, or left, a row the user filters by.
    """
    if changes:
        await session.execute(update(Job), changes)


async def fill_blank_description(session: AsyncSession, job_id: int, raw: RawJob, text: str) -> bool:
    """Give an open job with no text the text a posting read gave it. Reads the
    row again first: another writer may have filled it since the queue was
    read, and its text stays. Whether it wrote. Commits nothing."""
    job = await session.get(Job, job_id, populate_existing=True)
    if job is None or job.status != "open" or job.description_text is not None:
        return False
    job.description_html = raw.description_html
    job.description_sections = [s.as_dict() for s in raw.description_sections]
    job.description_text = text
    job.description_fetched_at = _now()
    return True


async def set_job_places(session: AsyncSession, changes: list[dict]) -> None:
    """Write re-derived places, one `{"id", "location_groups", "location_cities"}`
    per changed row. Same split as `set_job_roles`; callers
    recompute `in_scope`."""
    if changes:
        await session.execute(update(Job), changes)


async def set_job_roles(session: AsyncSession, changes: list[dict]) -> None:
    """Write re-derived role coordinates, one `{"id", "family", "track"}` per
    changed row. Same split as `set_job_domains`: the reclassify pass
    owns WHEN, this module owns the write; callers recompute `in_scope`."""
    if changes:
        await session.execute(update(Job), changes)


async def set_job_levels(session: AsyncSession, changes: list[dict]) -> None:
    """Write re-derived levels, one `{"id", "level_band", "level_confidence",
    "level_basis"}` per changed row. The `levels_backfill` pass owns
    WHEN; callers recompute `in_scope`."""
    if changes:
        await session.execute(update(Job), changes)


async def refresh_listed_rungs(session: AsyncSession) -> list[int]:
    """Carry the rung a board prints in its listing into held open rows the
    sync has read since it last wrote them. Ids of the rows changed.

    The sync writes only the rows it keeps, so a held row it now judges out of
    scope keeps the columns it was written with, while the posting inventory
    holds what the board printed at the latest read. A row promoted from an
    inventory read made before the board printed its rung holds no rung, reads
    as an unstated level the radar admits, and every run would re-project it
    back in although the sync, reading the printed rung, judges it out. The
    level the pass then re-reads is the board's.

    Only a rung the listing states, never NULL: a rung read from the posting's
    page or text (`stated_level`) is evidence a listing that prints none does
    not withdraw.

    A row is read under its own key and under each key a binding lists it by
    (`job_source_identities`), so it can match more than one inventory row.
    The newest read that prints a rung decides, the latest inventory row on a
    tie, and it is written only when it is newer than the row and differs
    from it. Each path is an equi-join, so the planner can hash or merge it;
    an OR across the two paths in one join condition leaves it a nested loop
    over every open row and every printed rung. Commits nothing."""
    printed = PostingInventory.raw_level.isnot(None)
    reads = union_all(
        select(
            Job.id.label("job_id"),
            PostingInventory.id.label("read_id"),
            PostingInventory.raw_level,
            PostingInventory.last_seen_at,
        )
        .join(PostingInventory, PostingInventory.dedupe_key == Job.dedupe_key)
        .where(Job.status == "open", printed),
        select(
            JobSourceIdentity.job_id,
            PostingInventory.id,
            PostingInventory.raw_level,
            PostingInventory.last_seen_at,
        )
        .join(
            PostingInventory,
            and_(
                PostingInventory.binding_id == JobSourceIdentity.binding_id,
                PostingInventory.dedupe_key == JobSourceIdentity.source_key,
            ),
        )
        .where(printed),
    ).subquery("listed_reads")
    newest = (
        select(reads.c.job_id, reads.c.raw_level, reads.c.last_seen_at)
        .distinct(reads.c.job_id)
        .order_by(reads.c.job_id, reads.c.last_seen_at.desc(), reads.c.read_id.desc())
        .subquery("newest_read")
    )
    changed = await session.scalars(
        update(Job)
        .where(
            Job.id == newest.c.job_id,
            Job.status == "open",
            newest.c.last_seen_at > Job.last_seen,
            Job.raw_level.is_distinct_from(newest.c.raw_level),
        )
        .values(raw_level=newest.c.raw_level)
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    return list(changed.all())


#: Orders every write of `jobs.in_scope` from the saved scope against the
#: saves that change it. Transaction-scoped: a save
#: takes it before re-projecting and the run's writer before its first row
#: write in a transaction, each holding it to its commit, so whichever commits
#: second reads what the first committed. Without it, a save that runs while a
#: scan is writing is undone by rows the scan stores under the scope it
#: started with.
SCOPE_PROJECTION_LOCK_KEY = 91241


async def hold_scope_projection(session: AsyncSession) -> None:
    await advisory_xact_lock(session, SCOPE_PROJECTION_LOCK_KEY)


async def apply_saved_scope_to_jobs(
    session: AsyncSession,
    enabled_roles: set[str] | list[str],
    enabled_bands: set[str] | list[str],
    enabled_tracks: set[str] | list[str],
    enabled_locations: set[str] | list[str],
    enabled_domains: set[str] | list[str],
    *,
    excluded_domains: set[str] | list[str],
    answers: Sequence[RoleAnswer] | None,
    excluded_locations: set[str] | list[str],
    include_unstated_level: bool,
    job_ids: Collection[int] | None = None,
) -> int:
    """Recompute `jobs.in_scope` after a settings change without lifecycle events.

    Pipeline collection uses `passes_filters()` before persistence. Existing rows
    need the same role + seniority + track + location + domain gate immediately
    when the user saves scope, otherwise normal board reads keep showing the
    previous `in_scope` set until a future scrape observes each source again.

    Learned company exclusions are loaded HERE, not passed in: they are part of
    what `in_scope` projects, and a caller that forgot them would silently
    resurrect every excluded row on the next unrelated scope save.

    Takes `SCOPE_PROJECTION_LOCK_KEY` first. `job_ids` limits the projection
    to those rows: the run's writer re-projects the rows it wrote.

    A row this session already holds takes the new flag as its stored value.
    The run's writer keeps the rows it re-projects and reads their flag again
    before its next commit; left expired, that read would need a load, which
    an async session cannot make from a plain attribute access.
    """
    await hold_scope_projection(session)
    exclusions = await load_scope_exclusions(session)
    expr = job_scope_expr(
        enabled_roles, enabled_bands, enabled_tracks, enabled_locations, enabled_domains,
        exclusions, excluded_domains=excluded_domains, answers=answers,
        excluded_locations=excluded_locations, include_unstated_level=include_unstated_level,
    )
    stmt = update(Job).where(Job.in_scope.is_distinct_from(expr))
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(list(job_ids)))
    changed = (await session.execute(
        stmt.values(in_scope=expr)
        .returning(Job.id, Job.in_scope)
        .execution_options(synchronize_session=False)
    )).all()
    for job_id, in_scope in changed:
        held = session.identity_map.get(identity_key(Job, job_id))
        if held is not None:
            set_committed_value(held, "in_scope", in_scope)
    return len(changed)


# --------------------------------------------------------------------------- #
# Closure by absence needs two misses
#
# One complete listing that does not name a posting is not enough to close it:
# postings drop out of a single listing and come back. The evidence lives on
# the posting, not on the company: two complete listings at least `min_gap` apart must miss it, and a
# failed, degraded or blocked scan of its company between them starts the count
# again. Seeing the posting in ANY scan resets it.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Absence:
    """One posting's evidence toward closure: misses counted, first one when."""

    scans: int = 0
    since: datetime | None = None

    @property
    def closes(self) -> bool:
        return self.scans >= 2


def count_miss(absence: Absence, *, now: datetime, min_gap: timedelta) -> Absence:
    """The evidence after one more complete listing that did not list the posting.

    Pure. A second miss sooner than `min_gap` after the first leaves the count
    at one and keeps the first miss as the anchor, so two scans an hour apart
    never add up to a closure however many of them there are.
    """
    if absence.scans <= 0 or absence.since is None:
        return Absence(1, now)
    if absence.closes or now - absence.since >= min_gap:
        return Absence(2, absence.since)
    return absence


def _absence(job: Job) -> Absence:
    return Absence(job.absent_scans or 0, job.absent_since)


def _set_absence(job: Job, absence: Absence) -> None:
    if _absence(job) != absence:
        job.absent_scans = absence.scans
        job.absent_since = absence.since


def reset_absence(jobs) -> None:
    """Start every posting's count again: it was seen, or its company's scan failed."""
    for job in jobs:
        _set_absence(job, Absence())


@dataclass(frozen=True)
class AbsenceTally:
    """What one complete listing said about the open postings it speaks for."""

    open: int
    missed: int
    #: Missed for the second time, `min_gap` or more after the first.
    second_miss: frozenset[int]

    @property
    def missing_share(self) -> float:
        return round(self.missed / self.open, 4) if self.open else 0.0


def record_absence(
    existing: dict[str, Job],
    seen_keys: set[str],
    *,
    speaks_for: frozenset[int],
    now: datetime,
    min_gap: timedelta,
) -> AbsenceTally:
    """Count this listing's misses on the open postings it speaks for.

    Called only for a listing that is closure evidence (`scan_may_close`) from a
    binding entitled to speak for these postings; `speaks_for` is that scope.
    Writes the evidence on each row and returns which postings it now closes.
    """
    seen_ids = {job.id for key, job in existing.items() if key in seen_keys}
    open_jobs = {
        job.id: job for job in existing.values()
        if job.status == "open" and job.id in speaks_for
    }
    missed = 0
    second: set[int] = set()
    for job in open_jobs.values():
        if job.id in seen_ids:
            continue
        missed += 1
        absence = count_miss(_absence(job), now=now, min_gap=min_gap)
        _set_absence(job, absence)
        if absence.closes:
            second.add(job.id)
    return AbsenceTally(open=len(open_jobs), missed=missed, second_miss=frozenset(second))


async def close_missing(
    session: AsyncSession,
    run: ScrapeRun,
    company: str,
    seen_keys: set[str],
    existing: dict[str, Job],
    *,
    closable_job_ids: frozenset[int] | None = None,
) -> int:
    """Mark still-open jobs that were not seen this run as closed.

    `closable_job_ids` is the binding-scoped allowlist from
    `tracker.db.binding.resolve_closure_scope`. When given, a job absent from
    the listing is closed **only** if it is in that scope -- so a rebind, whose
    source keys are all new, cannot close the company's entire history and
    reopen it as fabricated churn. `None` closes every unseen open job of the
    company.

    Every closure records its basis and the run that supplied the evidence.
    The basis is not a parameter: this function IS "absent from
    a complete listing" -- it runs only behind `scan_may_close` (uncapped,
    error-free, `list_complete`), so a caller choosing the basis could only
    choose one that contradicts the evidence the caller already established.
    `closed_at` stays detection time, which is what the statistics and the
    dashboard's *observed listing duration* are built on.

    The pipeline passes only postings `record_absence` found missed twice;
    this function closes whatever it is allowed to and decides
    nothing about how much absence is enough.
    """
    now = _now()
    closed = 0
    seen_ids = {job.id for key, job in existing.items() if key in seen_keys}
    for job in {job.id: job for job in existing.values()}.values():
        if job.id in seen_ids or job.status == "closed":
            continue
        if closable_job_ids is not None and job.id not in closable_job_ids:
            continue
        detail: dict = {"basis": ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value}
        if job.absent_since is not None:
            # The first of the two misses; this run is the second.
            detail["first_missed_at"] = job.absent_since.isoformat()
        job.status = "closed"
        job.closed_at = now
        job.closure_basis = ClosureBasis.ABSENT_FROM_COMPLETE_LISTING.value
        job.closure_run_id = run.id
        job.last_seen = job.last_seen or now
        reset_absence([job])
        # Also on the event, because the row remembers one closure and a
        # repeatedly re-listed posting has many. The append-only history is
        # where "why was it closed the third time" stays answerable.
        _add_event(session, run, job, "closed", detail)
        closed += 1
    return closed


def _add_event(session: AsyncSession, run: ScrapeRun, job: Job, event_type: str, detail: dict) -> None:
    session.add(
        JobLifecycleEvent(
            job_id=job.id,
            run_id=run.id,
            event_type=event_type,
            detail=detail,
            created_at=_now(),
        )
    )


async def reconcile_stale_runs(
    session: AsyncSession,
    older_than_minutes: int,
    heartbeat_stale_seconds: int | None = None,
) -> int:
    """Flip orphaned ``running`` ScrapeRuns to ``error``.

    A run whose process crashed, hung, or was killed leaves its committed row
    stuck in ``running``. A row is orphaned when EITHER:

    * its ``started_at`` is older than ``older_than_minutes`` (absolute
      backstop, independent of heartbeat), or
    * ``heartbeat_stale_seconds`` is given and its last beat
      (``heartbeat_at``, or ``started_at`` for a run that never beat) is older
      than that — a live run keeps beating, so silence means it died.

    Heartbeat detection catches a killed run in minutes; the start-time bound
    also reconciles rows that never beat. Closed as `_interrupted_record` says,
    with a reconcile note, so the run log and freshness surface stay honest.
    Returns rows reconciled.

    The two bounds themselves are `queries/runs.py::stale_run_where` — the one
    predicate `/api/status`'s stuck count also selects with. This
    caller answers with the DATABASE clock.
    """
    result = await session.execute(
        update(ScrapeRun)
        .where(
            stale_run_where(
                func.now(),
                stale_minutes=older_than_minutes,
                heartbeat_stale_seconds=heartbeat_stale_seconds,
            )
        )
        .values(**_interrupted_record())
    )
    return result.rowcount or 0


async def close_runs_left_running(session: AsyncSession) -> int:
    """Close every ``running`` ScrapeRun as `reconcile_stale_runs` closes an
    orphan, however recent its heartbeat. Only for a caller holding the run
    lock (`advisory_lock_key`): a run holds it from before it opens its row to
    its end, so then no ``running`` row is live. Returns rows closed."""
    result = await session.execute(
        update(ScrapeRun).where(ScrapeRun.status == "running").values(**_interrupted_record())
    )
    return result.rowcount or 0


def _interrupted_record() -> dict:
    """A run whose process ended before it did, closed as a stopped run is
    (`POST /api/sync/cancel`). A run writes `per_source` at its terminal
    record, which it never reached, so it reports the sources it committed;
    its status is their projection capped at ``partial``
    (`outcome.cancelled_run_status`), since ``error`` would deny the rows they
    wrote; and it covered less than it set out to, so it claims no full
    refresh."""
    usable = (
        select(ScrapeSourceRun.id)
        .where(
            ScrapeSourceRun.run_id == ScrapeRun.id,
            ScrapeSourceRun.outcome.in_([outcome.value for outcome in USABLE]),
        )
        .exists()
    )
    return {
        "status": case((usable, "partial"), else_="error"),
        "scope": RunScope.TARGETED.value,
        "finished_at": func.now(),
        "notes": func.coalesce(ScrapeRun.notes, "") + " [reconciled: stale/orphaned run]",
        "per_source": committed_per_source_expr(ScrapeRun.id),
    }


# The one search_vector build expression. Weighted so ts_rank_cd prefers a
# title hit over dozens of body-boilerplate hits (flat ranking buries a title
# match below many body matches). `setweight` itself is membership-blind, but
# the B tier indexes department/team lexemes, so `@@` (the lexical `q` filter
# included) also matches rows whose only hit is their employer-stated
# category. Deliberate: a user searching "payments" wants the Payments team's
# roles; the category fields are search surfaces, not just rank signals.
# The eval harness imports this to build its shadow table identically — edit
# here and both move together; a private copy drifts.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('english', coalesce(title,'')), 'A') || "
    "setweight(to_tsvector('english', coalesce(department,'') || ' ' || coalesce(team,'')), 'B') || "
    "setweight(to_tsvector('english', coalesce(description_text,'')), 'C')"
)


async def refresh_search_vectors(session: AsyncSession, job_ids: list[int]) -> None:
    """Rebuild the weighted FTS tsvector for touched jobs."""
    if not job_ids:
        return
    await session.execute(
        text(f"UPDATE jobs SET search_vector = {SEARCH_VECTOR_SQL} WHERE id = ANY(:ids)"),
        {"ids": job_ids},
    )
