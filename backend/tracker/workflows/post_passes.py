"""Post-persist passes: the one producer table for every derived surface.

A table, not a plugin registry. Order is load-bearing: content_fingerprint precedes
embeddings + disclosed_comp (they gate on content_changed_at); lineage runs after
embeddings (needs fresh vectors) and before demand_metrics (reads lineage_role);
place_sets run just before lineage, whose detector gates on them;
twins run after the lineage projection so same-opening pairs never enter the
twin review queue.

`run_post_passes` owns the skip/failure policy and each pass's transaction
boundary: commit after a pass, roll back after a failure, one derivation-state
record per pass that ran. A new derived table is a `POST_PASSES` entry plus a
`post_pass:` claim in `db/ownership.py`, in the same change.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.comp_trends import compute_comp_metrics, compute_disclosure_metrics
from tracker.analytics.demand import DEMAND_PASS, compute_demand_metrics, demand_day
from tracker.company_store import get_active_targets
from tracker.config import Settings
from tracker.connectors import (
    RateLimiterPool,
    build_adapter,
    structure_job_detail,
    text_from_posting,
)
from tracker.connectors.detail.base import sections_to_text
from tracker.content import fingerprint_content
from tracker.db.inventory_store import reclassify_inventory_if_changed
from tracker.db.models import DerivationState, Job, ScrapeRun
from tracker.db.queries.scope import unplaced_level_expr
from tracker.db.repo import (
    fill_blank_description,
    refresh_search_vectors,
    set_job_domains,
    set_job_places,
    set_job_roles,
)
from tracker.enrich.classify import classify_domains, classify_family, location_slugs_for
from tracker.enrich.inventory import classifier_fingerprint
from tracker.enrich.track import classify_track
from tracker.intelligence_runtime.disclosed_comp import (
    backlog_ids,
    correct_pay_periods,
    extract_disclosed_comp,
)
from tracker.lineage.detect import detect_lineage, rebuild_lineage_projection
from tracker.lineage.place_sets import PlaceSetReads, rebuild_place_sets
from tracker.lineage.twins import detect_twins
from tracker.platform.util import describe_exception, html_to_text
from tracker.plugins import reestimate as reestimate_module
from tracker.plugins.reestimate import reestimate
from tracker.profiles.prices import PRICES_PASS, run_refresh
from tracker.schema import RawJob
from tracker.scope.projection import recompute_saved_scope
from tracker.scope.promotion import promote_locked
from tracker.semantic.cluster import rebuild_clusters
from tracker.semantic.embed import EMBED_COMMIT_BATCH, embed_jobs, stale_job_ids
from tracker.semantic.similarity import refresh_similarity
from tracker.semantic.tier_store import reconcile_tier
from tracker.settings_store import get_setting_dict, set_setting_dict
from tracker.skills.analytics import compute_skill_demand
from tracker.skills.extract import extract_requirements
from tracker.source_policy import collection_access, scanned_automatically
from tracker.taxonomy.locations import normalize_cities
from tracker.workflows.collection_types import ScanMode, SourceStats
from tracker.workflows.posting_pages import page_band, read_posting_pages
from tracker.workflows.profile_inference_pass import run_profile_inference
from tracker.workflows.relevance_pass import run_relevance_review
from tracker.workflows.relevel import relevel_jobs
from tracker.workflows.retention import apply_retention
from tracker.workflows.tuning_pass import learn_bounds

logger = logging.getLogger(__name__)

@dataclass
class PostPassContext:
    """Inputs shared by every post-persist pass; results accumulate in-place.

    Typed: every pass reads the same session and settings shapes, and `touched_ids` (the rows this run wrote, extended in place by the
    backfills that refill rows) is a scheduling optimisation, never proof that
    all stale work was reached. Each pass's result is its own summary."""

    session: AsyncSession
    touched_ids: list[int]
    per_source: dict[str, SourceStats]
    settings: Settings
    max_list: int | None
    #: The run these passes belong to, for a pass that records history.
    run: ScrapeRun | None = None
    scan_mode: ScanMode = ScanMode.RECONCILE
    results: dict[str, Any] = field(default_factory=dict)

    @property
    def clean_companies(self) -> set[str]:
        """Companies whose collection had no errors (lineage/twins scope)."""
        return {c for c, s in self.per_source.items() if not s["errors"]}


@dataclass(frozen=True)
class PostPass:
    """One post-persist pass.

    ``capped_ok=False`` = full-scrape only (a capped scan didn't reconcile
    closures, same rule as ``close_missing``). ``fatal=True`` failures fail
    the run; non-fatal passes log a warning and the loop continues.
    """

    name: str
    #: May return a summary for its derivation row (`_record_derivation`).
    run: Callable[[PostPassContext], Awaitable[dict | None]]
    capped_ok: bool = True
    discovery_ok: bool = False
    fatal: bool = False
    enabled: Callable[[Settings], bool] = staticmethod(lambda settings: True)
    #: Runs on a schedule of its own (`run_scheduled_pass`, the supervisor's job
    #: of the same name), never as part of a pipeline run.
    scheduled: bool = False


async def _pass_search_vectors(ctx: PostPassContext) -> None:
    await refresh_search_vectors(ctx.session, ctx.touched_ids)


async def _pass_content_fingerprint(ctx: PostPassContext) -> None:
    await fingerprint_content(ctx.session, ctx.touched_ids)


async def _pass_skills_requirements(ctx: PostPassContext) -> None:
    # Evidence-grounded requirements; incremental via its own
    # requirements_content_hash gate.
    await extract_requirements(ctx.session, ctx.touched_ids)


async def backfill_missing_descriptions(
    session: AsyncSession, *, limit: int, collected: Collection[str] = (),
) -> list[int]:
    """Fetch text for open rows that have none. Returns the job ids filled.

    Oldest first, so the longest-owed debt drains first rather than newer rows
    perpetually jumping the queue, except that a row on the Board whose level
    is not stated goes ahead: its text is what can name its
    level (a stated range, `levels_backfill` reads it), and until then the
    person sees it unplaced.

    Only rows this pass can fill are selected, so `limit` counts them:
    a followed company (`get_active_targets`) the source policy
    lets us collect (`collection_access`, with the user's consent for a walled
    one), whose adapter reads a posting's text from the posting alone
    (`text_from_posting`). Selecting the oldest blanks and skipping the ones
    no adapter can fill would let unfillable rows hold the head of the queue
    every run, so no newer blank is ever reached.

    A company RoleBand scans only when the user asks (`scanned_automatically`)
    is asked only by a run that scanned it, `collected`, which for such a
    company is a sync the user started: this drain runs after every run,
    scheduled ones included, and must not make one of them reach it. An
    adapter whose `hydrate` needs the listing's payload is fillable only
    because it rebuilds that payload from the posting url
    (`payload_from_posting`).

    Every fetch is individually guarded: this runs after persistence, drains a
    backlog, and must never be able to fail a scrape that already succeeded.

    It owns its transactions, as the first pass may. Each fetch is a paced
    request, so a transaction held across the drain would keep one snapshot
    open for the whole of it, holding back vacuum and every writer waiting on
    this run. The queue is read and that transaction ended before the first
    request; each fill is then written and committed on its own, after its row
    is read again, since another writer may have given it text meanwhile.
    """
    if limit <= 0:
        return []
    fillable = {
        slug: cfg
        for slug, cfg in (await get_active_targets(session)).items()
        if text_from_posting(cfg["adapter"])
        and not collection_access(cfg["adapter"], company=slug, consent=cfg.get("consent")).denied
        and (slug in collected or scanned_automatically(cfg["adapter"], slug, cfg.get("consent")))
    }
    if not fillable:
        return []
    rows = (
        await session.scalars(
            select(Job)
            .where(
                Job.status == "open",
                Job.description_text.is_(None),
                Job.company.in_(sorted(fillable)),
            )
            .order_by(
                # NULL-safe: a NULL basis would sort first descending.
                and_(Job.in_scope.is_(True), unplaced_level_expr(Job)).desc(),
                Job.first_seen.asc(),
            )
            .limit(limit)
        )
    ).all()
    if not rows:
        return []
    postings = [
        (
            job.id,
            job.company,
            RawJob(
                company=job.company,
                req_id=job.req_id,
                title=job.title,
                url=job.url,
                locations=list(job.locations or []),
                # The row has no text, so neither has the posting rebuilt from
                # it. `RawJob` defaults to complete, and some adapters skip a
                # posting whose text is complete.
                description_complete=False,
            ),
        )
        for job in rows
    ]
    await session.commit()

    # One pacer per host for the whole drain, shared across processes like the
    # collection's. Without it each posting builds an adapter with a private
    # limiter whose first wait is immediate, so a drain of one company's rows
    # would go out back to back, at no pace at all.
    limiter_pool = RateLimiterPool()
    filled: list[int] = []
    for job_id, company, raw in postings:
        cfg = fillable[company]
        try:
            adapter = build_adapter(
                company,
                cfg["adapter"],
                cfg.get("board_token"),
                board_region=cfg.get("board_region"),
                limiter_pool=limiter_pool,
                # The adapter re-checks the policy on entry: it must see the
                # consent the selection saw.
                consent=cfg.get("consent"),
            )
            async with adapter:
                # What the listing row carried, where `hydrate` needs it and
                # the posting can rebuild it.
                raw.detail_payload = adapter.payload_from_posting(raw)
                await adapter.hydrate(raw)
                structure_job_detail(
                    raw, adapter.drift, payload=raw.detail_payload, source=cfg["adapter"]
                )
        except Exception as exc:  # noqa: BLE001 - a backlog drain is best effort
            logger.warning(
                "description backfill failed for job %s: %s",
                job_id, describe_exception(exc), exc_info=True,
            )
            continue
        text = sections_to_text(raw.description_sections) or html_to_text(
            raw.description_html
        )
        if not text:
            # The source served no text for it. Not an error and not a fill:
            # counting it as either would either hide a real gap or invent one.
            continue
        wrote = await fill_blank_description(session, job_id, raw, text)
        await session.commit()
        if wrote:
            filled.append(job_id)
    return filled


async def reclassify_domains(
    session: AsyncSession, job_ids: Collection[int] | None = None
) -> dict[str, int]:
    """Bring every stored row's `domains` (or only `job_ids`') in line with the
    current lexicon.

    Two debts, one pass. NULL is a row that predates the axis. A STALE answer is
    a row classified under an older lexicon, the debt every vocabulary change
    creates. A still-listed row repairs itself on its next scan,
    because `_apply_fields` rewrites `domains` on every observation; a row that
    is never re-observed (closed, or its company paused) would keep the old
    answer indefinitely, and the scope screen's counts would disagree with the
    board.

    Pure derivation from stored fields, no network. Reads narrow columns (an
    ORM load would pull every description) and writes only rows whose answer
    changed, so once caught up this is a scan that writes nothing.

    `in_scope` is recomputed when anything changed. Skipping that because the
    axis "defaults to all worlds" fails the moment a user switches one off: a
    reclassified row can gain or lose exactly the world they hid.
    """
    stmt = select(Job.id, Job.company, Job.req_id, Job.title, Job.url,
                  Job.department, Job.team, Job.domains).order_by(Job.id.asc())
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(list(job_ids)))
    rows = (await session.execute(stmt)).all()
    changes = []
    for row in rows:
        fresh = classify_domains(RawJob(
            company=row.company, req_id=row.req_id, title=row.title, url=row.url or "",
            department=row.department, team=row.team,
        ))
        if row.domains is None or list(row.domains) != fresh:
            changes.append({"id": row.id, "domains": fresh})
    await set_job_domains(session, changes)
    rescoped = await recompute_saved_scope(session) if changes else 0
    return {"reclassified": len(changes), "in_scope_changed": rescoped}


#: The classifier fingerprint each `jobs` reclassify pass last read the whole
#: table under, by pass.
JOBS_CLASSIFIED_KEY = "jobs_classified_with"


async def _rows_to_reclassify(ctx: PostPassContext, axis: str) -> list[int] | None:
    """The rows a reclassify pass reads this run. None is the whole table: the
    first run after the classifier changed, which only a code or data change
    can make stale. Otherwise the run's own rows: a row a scan writes is
    classified by the current code, and one whose title, team, department or
    places a listing moved joins `touched_ids` too."""
    stored = await get_setting_dict(ctx.session, JOBS_CLASSIFIED_KEY) or {}
    return None if stored.get(axis) != classifier_fingerprint() else list(ctx.touched_ids)


async def _mark_reclassified(ctx: PostPassContext, axis: str) -> None:
    stored = dict(await get_setting_dict(ctx.session, JOBS_CLASSIFIED_KEY) or {})
    await set_setting_dict(ctx.session, JOBS_CLASSIFIED_KEY, {**stored, axis: classifier_fingerprint()})


async def _pass_domains_backfill(ctx: PostPassContext) -> None:
    rows = await _rows_to_reclassify(ctx, "domains")
    ctx.results["domains"] = await reclassify_domains(ctx.session, rows)
    if rows is None:
        await _mark_reclassified(ctx, "domains")


async def reclassify_roles(
    session: AsyncSession, job_ids: Collection[int] | None = None
) -> dict[str, int]:
    """Bring every stored row's `family` and `track` (or only `job_ids`') in
    line with the taxonomy.

    The same debt as `reclassify_domains`, for the role axes: both are computed
    at write time, so a taxonomy or classifier change (IC "... Manager"
    titles leave management) only reaches rows that are observed again. A
    closed row, or one at a paused company, would keep the old answer and the
    board would disagree with the scope screen. A post-pass, so the debt
    drains without anyone running a command.

    Pure derivation from stored fields; narrow reads; writes only changed rows,
    so once caught up it is a scan that writes nothing. `in_scope` is recomputed
    when anything changed: family and track are scope axes.
    """
    changes = await pending_roles(session, job_ids)
    await set_job_roles(session, changes)
    # The family is an estimate input no fingerprint names.
    await reestimate_module.refresh_jobs(session, [change["id"] for change in changes])
    rescoped = await recompute_saved_scope(session) if changes else 0
    return {"reclassified": len(changes), "in_scope_changed": rescoped}


async def pending_roles(
    session: AsyncSession, job_ids: Collection[int] | None = None
) -> list[dict]:
    """The rows (of all, or of `job_ids`) whose family or track the taxonomy
    reads differently now, one `{"id", "family", "track"}` each: the derivation
    `reclassify_roles` writes, and `scripts.backfill_classifier` writes in
    batches."""
    stmt = select(Job.id, Job.company, Job.req_id, Job.title, Job.url,
                  Job.department, Job.team, Job.family, Job.track).order_by(Job.id.asc())
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(list(job_ids)))
    rows = (await session.execute(stmt)).all()
    changes = []
    for row in rows:
        family = classify_family(RawJob(
            company=row.company, req_id=row.req_id, title=row.title, url=row.url or "",
            department=row.department, team=row.team,
        ))
        track = classify_track(row.title, family).value
        if family != row.family or track != row.track:
            changes.append({"id": row.id, "family": family, "track": track})
    return changes


async def reclassify_places(
    session: AsyncSession, job_ids: Collection[int] | None = None
) -> dict[str, int]:
    """Bring every stored row's places (or only `job_ids`') in line with the
    location taxonomy.

    The third debt of the same kind: `location_groups` and
    `location_cities` are derived from the stored `locations` at write time,
    so a taxonomy change reaches only rows observed again: a row storing a
    metro and its country without the region is missed by "Anywhere in North
    America", and a region-only place ("EMEA", "Americas") counts as its
    regions and countries only once derived again. Place exceptions also rely
    on every row being ancestor-closed.

    Pure derivation from stored fields (`location_slugs_for`, the function
    ingest uses); narrow reads; writes only changed rows; `in_scope`
    recomputed when anything changed. The posting inventory's rows are
    reclassified by `_pass_inventory_promotion`, not here.
    """
    stmt = select(Job.id, Job.locations, Job.location_groups, Job.location_cities).order_by(Job.id.asc())
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(list(job_ids)))
    rows = (await session.execute(stmt)).all()
    changes = []
    for row in rows:
        places = list(row.locations or [])
        groups = location_slugs_for(places)
        cities = normalize_cities(places)
        if list(row.location_groups or []) != groups or list(row.location_cities or []) != cities:
            changes.append({"id": row.id, "location_groups": groups, "location_cities": cities})
    await set_job_places(session, changes)
    rescoped = await recompute_saved_scope(session) if changes else 0
    return {"reclassified": len(changes), "in_scope_changed": rescoped}


async def _pass_places_backfill(ctx: PostPassContext) -> None:
    rows = await _rows_to_reclassify(ctx, "places")
    ctx.results["places"] = await reclassify_places(ctx.session, rows)
    if rows is None:
        await _mark_reclassified(ctx, "places")


async def _pass_inventory_promotion(ctx: PostPassContext) -> None:
    """Bring the posting inventory in line with the taxonomy, then admit what
    the saved scope now keeps. After the three `jobs` reclassify
    passes, so both tables file a posting alike; before `search_vectors`, so
    every derivation pass covers the admitted rows. The run holds the run
    lock, so this is the lock-free promotion; it also drains a save that found
    a run holding the lock, or admitted fewer rows than qualified."""
    # Only after a classifier change: otherwise every row's cost is spent every run.
    reclassified = await reclassify_inventory_if_changed(ctx.session)
    result = await promote_locked(ctx.session)
    ctx.touched_ids.extend(result.job_ids)
    ctx.results["inventory"] = {
        "reclassified": reclassified, "promoted": result.promoted, "pending": result.pending,
    }


async def _pass_inventory_retention(ctx: PostPassContext) -> None:
    """Remove inventory postings no scan read within the user's window.
    The run holds the run lock, so no lock is taken here."""
    result = await apply_retention(ctx.session, now=datetime.now(UTC))
    ctx.results["retention"] = {"removed": result.removed, "more": result.more}


async def _pass_roles_backfill(ctx: PostPassContext) -> None:
    rows = await _rows_to_reclassify(ctx, "roles")
    ctx.results["roles"] = await reclassify_roles(ctx.session, rows)
    if rows is None:
        await _mark_reclassified(ctx, "roles")


async def _pass_levels_backfill(ctx: PostPassContext) -> None:
    ctx.results["levels"] = await relevel_jobs(ctx.session)


async def _pass_description_backfill(ctx: PostPassContext) -> None:
    """Fetch descriptions for open rows that still have none.

    "A later reconcile will pick it up" is an inference from re-observation, not
    a mechanism: a row a discovery probe created can miss every later full
    scan and sit open and blank indefinitely.

    The queue is a query, not a table (`status='open' AND description_text IS
    NULL` is the debt, oldest first, at the companies this pass can ask), so
    there is no bookkeeping to drift out of sync with reality.
    Bounded per run and best-effort per row: this drains a
    backlog, it must never be able to fail a scrape.
    """
    filled = await backfill_missing_descriptions(
        ctx.session, limit=ctx.settings.description_backfill_per_run, collected=set(ctx.per_source),
    )
    # Downstream passes work from `touched_ids`; a row we just gave text to has
    # to join them or its description would sit there unindexed and unenriched.
    ctx.touched_ids.extend(job_id for job_id in filled if job_id not in ctx.touched_ids)
    ctx.results["description_backfill"] = {"filled": len(filled)}


async def _pass_embeddings(ctx: PostPassContext) -> dict:
    """Encode the rows this run touched, in committed chunks, within a budget.

    Chunked and committed rather than one transaction over the queue: encoding
    a backlog takes longer than the window `reconcile_stale_runs` allows a run,
    so a single transaction would be rolled back by the kill that follows and
    the next run would start from the same place. Each chunk that commits is
    work no later failure can take back, and `stale_predicate` makes the
    remainder its own queue next run.

    The pass is the only post-pass that self-commits mid-way besides
    `reference`; `run_post_passes` tolerates that (`expire_on_commit=False`)
    and still commits after it returns.
    """
    # Adopt the shared tier choice before encoding anything. The
    # decision file is per-checkout while the vectors land in the one shared
    # DB, so without this a worktree whose file predates a switch made
    # elsewhere would embed into that shared space at the *other* tier: the
    # mixed space the forced re-embed exists to prevent. Never fatal: a tier we
    # cannot read leaves the file's own decision standing.
    try:
        await reconcile_tier(ctx.session)
    except Exception:  # noqa: BLE001 — the file's decision still stands
        logger.warning("could not reconcile the embedding tier", exc_info=True)

    queue = await stale_job_ids(ctx.session, ctx.touched_ids)
    deadline = time.monotonic() + ctx.settings.embedding_budget_seconds
    embedded = 0
    done = 0
    for start in range(0, len(queue), EMBED_COMMIT_BATCH):
        chunk = queue[start : start + EMBED_COMMIT_BATCH]
        embedded += await embed_jobs(ctx.session, chunk)
        await ctx.session.commit()
        done += len(chunk)
        # After the chunk, never before: the budget bounds how long the pass
        # runs, it must never be the reason a run embeds nothing.
        if time.monotonic() >= deadline:
            break
    deferred = len(queue) - done
    if deferred:
        logger.info("embedding budget reached: %d embedded, %d left for the next run", embedded, deferred)
    return {"embedded": embedded, "deferred": deferred}


async def _pass_disclosed_comp(ctx: PostPassContext) -> dict:
    # On by default: bounded by intelligence_max_per_run. Deterministic,
    # no provider, so no host can fail to run it; the standalone
    # backfill CLI remains for bulk catch-up.
    cap = ctx.settings.intelligence_max_per_run
    run_id = ctx.run.id if ctx.run is not None else None
    touched = await extract_disclosed_comp(
        ctx.session,
        ctx.touched_ids,
        cap=cap,
        # A row whose text states no band keeps the one its page stated.
        page_band=page_band,
        run_id=run_id,
    )
    # A budget of its own, after the touched rows: what this run's rows owe
    # can never use it up, so the backlog moves forward every run.
    backlog = await extract_disclosed_comp(
        ctx.session,
        await backlog_ids(ctx.session, limit=cap),
        page_band=page_band,
        run_id=run_id,
    )
    return {
        "touched": touched["processed"],
        "backlog": backlog["processed"],
        "disclosed": touched["disclosed"] + backlog["disclosed"],
    }


async def _pass_reference(ctx: PostPassContext) -> dict | None:
    """Re-estimate every stored job when the reference set moved during the run:
    a plugin's publish or an atlas change may move what the
    estimate reads (rungs are banded when read). Before `comp_metrics`,
    so today's pay statistics read the new values.
    A no-op when nothing moved; batches commit, the run holds the lock."""
    result = await reestimate(ctx.session)
    summary = {
        "current": result.current,
        "applied": result.applied,
        "written": result.written,
        "change_id": result.change_id,
    }
    ctx.results["reference"] = summary
    return summary


async def _pass_pay_periods(ctx: PostPassContext) -> None:
    """Rewrite stored pay periods the period rule shows to be wrong:
    pure derivation over stored text, touching only rows whose period
    contradicts their amount, so once caught up it writes nothing."""
    ctx.results["pay_periods"] = await correct_pay_periods(ctx.session)


async def _pass_posting_pages(ctx: PostPassContext) -> None:
    """Read owed posting pages: the application form and structured pay the
    listing does not carry. After `disclosed_comp`, because the
    queue is "the text stated no pay", and a bounded best-effort drain like
    the description backfill."""
    ctx.results["posting_pages"] = await read_posting_pages(
        ctx.session, limit=ctx.settings.posting_pages_per_run
    )


async def _pass_relevance_review(ctx: PostPassContext) -> None:
    await run_relevance_review(
        ctx.session, cap=ctx.settings.relevance_review_max_per_run
    )


async def _pass_profile_inference(ctx: PostPassContext) -> None:
    await run_profile_inference(ctx.session)


async def _pass_place_sets(ctx: PostPassContext) -> None:
    # One role listed once per place: whole-corpus and pure over
    # stored rows, so a capped run may refresh it. Before lineage, so the
    # detector's same-set gate reads this run's sets.
    ctx.results["place_sets"] = await rebuild_place_sets(ctx.session)


async def _pass_lineage(ctx: PostPassContext) -> None:
    # Repost lineage: link near-identical re-listings under new req_ids so the
    # successor counts as a repost, not a brand-new job. The run's own rows
    # first; then, within the same cap, any posting whose detector inputs moved
    # outside this run (a relevel, a place or pay change, a predecessor that
    # changed). Repeated until the cap or nothing is stale, so a
    # successor a changed predecessor marked is read in the same run. One
    # `PlaceSetReads` for the whole pass: each company's place-set texts
    # are read and compared once, however many of its postings are checked.
    budget = ctx.settings.lineage_max_per_run
    place_sets = PlaceSetReads()
    touched = await detect_lineage(
        ctx.session, ctx.touched_ids, companies=ctx.clean_companies, cap=budget,
        place_sets=place_sets,
    )
    budget -= touched["processed"]
    while budget > 0:
        caught_up = await detect_lineage(
            ctx.session, None, companies=ctx.clean_companies, cap=budget,
            place_sets=place_sets,
        )
        if not caught_up["processed"]:
            break
        budget -= caught_up["processed"]
    await rebuild_lineage_projection(ctx.session)


async def _pass_twins(ctx: PostPassContext) -> None:
    # Twin opportunities remain independent demand; time never gates a pair.
    # The run's own stale rows first; then, within the same cap, any posting
    # still unchecked or marked by a neighbour that moved. Repeated until the
    # cap or nothing is stale, as the lineage pass does.
    budget = ctx.settings.twin_max_per_run
    touched = await detect_twins(
        ctx.session, ctx.touched_ids, companies=ctx.clean_companies, cap=budget,
    )
    budget -= touched["processed"]
    while budget > 0:
        caught_up = await detect_twins(
            ctx.session, None, companies=ctx.clean_companies, cap=budget,
        )
        if not caught_up["processed"]:
            break
        budget -= caught_up["processed"]


async def _pass_clusters(ctx: PostPassContext) -> None:
    # KMeans role clusters over ALL open, embedded jobs (not just touched_ids):
    # neighbor/cluster structure is a whole-corpus property, so this is correct
    # on capped runs too. Self-guards on too-few embeddings (returns 0), and
    # only relabels a corpus the last fit already clustered.
    ctx.results["clusters"] = await rebuild_clusters(ctx.session)


async def _pass_similarity(ctx: PostPassContext) -> None:
    # Precomputed nearest-neighbor sets (within/cross company), refreshed for
    # what changed since the last run; whole-corpus, so capped runs keep it too.
    ctx.results["similarity_rows"] = await refresh_similarity(ctx.session)


async def _pass_demand_metrics(ctx: PostPassContext) -> dict:
    # The day is recorded on the pass's derivation row: a day with nothing to
    # write is still a completed day.
    today = demand_day()
    ctx.results["demand_slices"] = await compute_demand_metrics(ctx.session, today=today)
    return {"metric_date": today.date().isoformat()}


async def _pass_skill_demand(ctx: PostPassContext) -> None:
    await compute_skill_demand(ctx.session)


async def _pass_comp_metrics(ctx: PostPassContext) -> None:
    await compute_comp_metrics(ctx.session)


async def _pass_disclosure_metrics(ctx: PostPassContext) -> None:
    # Pay transparency: what employers literally published, per (company, level,
    # basis). Its own pass rather than a tail of comp_metrics: different source
    # columns, different denominator, and a failure in one should not blank the
    # other's history.
    ctx.results["disclosure_cells"] = await compute_disclosure_metrics(ctx.session)


async def _pass_prices(ctx: PostPassContext) -> dict:
    # Listed companies' daily closes, on the supervisor's schedule, never a
    # scan's: waiting for a scan to end kept a saved key from showing a price for
    # most of an hour. Only with a real feed key; `run_refresh` takes the prices
    # lock, reserves every request in the ledger and commits per ticker.
    summary = await run_refresh(ctx.session, ctx.settings)
    ctx.results["prices"] = summary.get("priced", 0)
    return summary


async def _pass_tuning(ctx: PostPassContext) -> None:
    ctx.results["tuning"] = await learn_bounds(ctx.session, ctx.per_source, ctx.settings)


POST_PASSES: tuple[PostPass, ...] = (
    # FIRST, and it extends `touched_ids`: every pass below reads description
    # text (fingerprint, skills, embedding, disclosed comp), so a row filled here
    # joins their queues in this run. Ordering it later would leave a backfilled
    # description with no fingerprint, no skills and no embedding until whenever
    # that row next happened to be touched. `discovery_ok` because a probe is
    # what creates the debt.
    PostPass("description_backfill", _pass_description_backfill, discovery_ok=True),
    # Pure CPU derivation over stored fields (no network); `capped_ok` because
    # a capped scan changes nothing about rows already persisted.
    PostPass("domains_backfill", _pass_domains_backfill, discovery_ok=True),
    # Same shape for family and track: a classifier change reaches
    # rows the scraper will not rewrite.
    PostPass("roles_backfill", _pass_roles_backfill, discovery_ok=True),
    # And for levels: a ladder, title-rule or pay-grade change reaches
    # rows the scraper will not rewrite. After roles: it reads the stored family.
    PostPass("levels_backfill", _pass_levels_backfill, discovery_ok=True),
    # And for places: the location taxonomy moves too.
    PostPass("places_backfill", _pass_places_backfill, discovery_ok=True),
    PostPass("inventory_promotion", _pass_inventory_promotion, discovery_ok=True),
    # Time-based and global: it removes what no scan has read for the user's
    # window, so it needs no run to have read anything. Full runs only
    # (`capped_ok=False`): an operator's capped smoke never deletes, and the
    # scheduler's idle tick covers the weeks with no run at all.
    PostPass(
        "inventory_retention",
        _pass_inventory_retention,
        capped_ok=False,
        enabled=lambda s: s.inventory_retention_enabled and s.inventory_enabled,
    ),
    PostPass("search_vectors", _pass_search_vectors, discovery_ok=True, fatal=True),
    PostPass(
        "content_fingerprint", _pass_content_fingerprint, discovery_ok=True, fatal=True
    ),
    PostPass("skills_requirements", _pass_skills_requirements, discovery_ok=True),
    PostPass("embeddings", _pass_embeddings, discovery_ok=True, fatal=True),
    PostPass(
        "disclosed_comp",
        _pass_disclosed_comp,
        discovery_ok=True,
        enabled=lambda s: s.intelligence_extract_in_pipeline,
    ),
    # Pure CPU over stored text; after disclosed_comp so a band written this run
    # is already on the new rule and never a candidate.
    PostPass("pay_periods", _pass_pay_periods),
    # Before `comp_metrics`, so today's pay statistics read the new estimates.
    PostPass("reference", _pass_reference, discovery_ok=True),
    # Network, bounded: one paced request per owed page. Full runs only, never
    # a capped smoke or a discovery probe.
    PostPass("posting_pages", _pass_posting_pages, capped_ok=False),
    # Advisory only: stores a verdict row, never touches domains/in_scope.
    # Runs after domains_backfill (above) so "unclassified" is real, not
    # merely not-yet-derived. Standing-debt drain like the backfills:
    # `capped_ok` because it reviews rows already persisted.
    PostPass(
        "relevance_review",
        _pass_relevance_review,
        discovery_ok=True,
        enabled=lambda s: s.relevance_review_in_pipeline,
    ),
    # Deterministic scoring over the user's own saves/passes/companies/intent
    # -> profile_suggestions. Proposals only: nothing
    # applies without an explicit accept. Cheap, no model call, always on;
    # `capped_ok` because it reads only already-persisted user signals.
    PostPass("profile_inference", _pass_profile_inference, discovery_ok=True),
    # Whole-corpus, so not a discovery pass (those are incremental over the
    # probe's rows); `capped_ok` because it reads only stored rows.
    PostPass("place_sets", _pass_place_sets, enabled=lambda s: s.place_sets_enabled),
    PostPass("lineage", _pass_lineage, capped_ok=False, enabled=lambda s: s.lineage_enabled),
    PostPass("twins", _pass_twins, capped_ok=False, enabled=lambda s: s.twin_enabled),
    PostPass("clusters", _pass_clusters),
    PostPass("similarity", _pass_similarity),
    PostPass(DEMAND_PASS, _pass_demand_metrics, fatal=True),
    PostPass("skill_demand", _pass_skill_demand, fatal=True),
    PostPass("comp_metrics", _pass_comp_metrics, fatal=True),
    PostPass("disclosure_metrics", _pass_disclosure_metrics, fatal=True),
    PostPass(PRICES_PASS, _pass_prices, scheduled=True),
    # `capped_ok=False`: a `--max-list` scan stopped where the operator said, so
    # its page counts measure the cap, not the board. Learning from one would
    # ratchet every bound down to the cap and truncate the next full run.
    PostPass("tuning", _pass_tuning, capped_ok=False),
)


async def _record_derivation(session: AsyncSession, name: str, *, ok: bool, detail: dict) -> None:
    """Upsert the per-pass derivation-state row (freshness/health projection).

    Committed on its own so a later pass's failure never rolls it back. Only
    passes that actually *ran* touch their row: a capped/disabled skip leaves
    the prior state intact, so a capped run can't refresh an "ok" it didn't earn.

    Best-effort: this is observability, not the pass's own work, so a failure to
    record must never break the run. On error we roll back and log; the pass
    result already stands, committed before this call.
    """
    now = func.now()
    values = {
        "name": name,
        "last_run_at": now,
        "last_status": "ok" if ok else "error",
        "detail": detail,
    }
    if ok:
        values["last_ok_at"] = now
    stmt = pg_insert(DerivationState).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DerivationState.name],
        set_={k: v for k, v in values.items() if k != "name"},
    )
    try:
        await session.execute(stmt)
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - state recording must not fail a run
        await session.rollback()
        logger.warning(
            "derivation-state record for %s failed: %s", name, describe_exception(exc), exc_info=True
        )


async def run_post_passes(ctx: PostPassContext) -> None:
    """Execute POST_PASSES in table order with the shared skip/failure policy."""
    await _run_passes(ctx, refresh=False)


async def run_refresh_passes(ctx: PostPassContext) -> None:
    """The passes a long run takes over the rows it has written so far, while
    it still reads: the incremental ones a discovery probe runs (search,
    embeddings, pay estimates, skills), so new roles are findable and priced
    before the run ends. The whole-corpus passes (duplicates, clusters,
    metrics, tuning) wait for the end, where every pass runs again over all
    the run's rows. None is fatal here: the end of the run is where a failure
    fails it."""
    await _run_passes(ctx, refresh=True)


async def _run_passes(ctx: PostPassContext, *, refresh: bool) -> None:
    for p in POST_PASSES:
        if p.scheduled or not p.enabled(ctx.settings):
            continue
        if (refresh or ctx.scan_mode is ScanMode.DISCOVERY) and not p.discovery_ok:
            continue
        if ctx.max_list is not None and not p.capped_ok:
            continue
        # Each pass gets a committed boundary. Fatal passes and non-fatal passes
        # share one session, and several passes do not self-commit, so a failed
        # flush leaves the shared session in a pending-rollback state. Committing
        # after each pass means a later failure can never discard an earlier
        # pass's work, and a caught non-fatal failure is followed by rollback so
        # the next pass starts on a clean session instead of dying on
        # PendingRollbackError. (`expire_on_commit=False`, so intermediate
        # commits don't invalidate ORM state; passes are idempotent/incremental,
        # so finer-grained durability is safe.)
        if p.fatal and not refresh:
            try:
                detail = await p.run(ctx)
                await ctx.session.commit()
            except Exception as exc:
                # Record the failure before propagating: otherwise last_status
                # keeps reporting the previous run's "ok" for as long as the
                # pass keeps failing. Rollback first so the recorder gets a
                # clean session instead of a pending-rollback one.
                await ctx.session.rollback()
                await _record_derivation(
                    ctx.session, p.name, ok=False, detail={"error": describe_exception(exc)}
                )
                raise
            await _record_derivation(ctx.session, p.name, ok=True, detail=detail or {})
            continue
        try:
            detail = await p.run(ctx)
            await ctx.session.commit()
        except Exception as exc:  # noqa: BLE001 - non-fatal pass must not stall the run
            await ctx.session.rollback()
            error = describe_exception(exc)
            logger.warning("%s pass skipped: %s", p.name, error, exc_info=True)
            await _record_derivation(ctx.session, p.name, ok=False, detail={"error": error})
        else:
            await _record_derivation(ctx.session, p.name, ok=True, detail=detail or {})


async def run_scheduled_pass(name: str, session: AsyncSession, settings: Settings) -> dict:
    """Run one pass that keeps a schedule of its own, and record it as a pipeline
    run would. The same runner for the supervisor's job and a hand-run entry."""
    p = next(candidate for candidate in POST_PASSES if candidate.name == name and candidate.scheduled)
    ctx = PostPassContext(session=session, touched_ids=[], per_source={}, settings=settings, max_list=None)
    try:
        detail = await p.run(ctx)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        await _record_derivation(session, p.name, ok=False, detail={"error": describe_exception(exc)})
        raise
    detail = detail or {}
    if detail.get("skipped") != "busy":
        # A run that found another holding the lock did nothing worth a row.
        await _record_derivation(session, p.name, ok=True, detail=detail)
    return detail
