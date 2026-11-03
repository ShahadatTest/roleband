"""Statistics + demand surfaces: KPIs, compensation, trends, velocity, rollups.

Every route declares its response: velocity with the models beside its handler, the
others in `api/schemas/statistics.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cache

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import case, column, func, not_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.age_basis import employer_dated_share, employer_dated_sql
from tracker.analytics.comp_market import us_rows
from tracker.analytics.comp_package import choose_rung_row
from tracker.analytics.comp_residual import build_equity_residuals, build_source_comparison
from tracker.analytics.comp_stats import (
    build_comp_stats,
    build_comp_trajectory,
    build_disclosed_bands,
    build_disclosure_rates,
    rank_skill_comp,
)
from tracker.analytics.comp_trends import (
    DISCLOSURE_BASIS,
    build_comp_trend_series,
    build_disclosure_trend_series,
)
from tracker.analytics.hiring import build_hiring_places
from tracker.analytics.velocity import build_velocity
from tracker.api.deps import InsightsScopeDep, OffBoardDep, SessionDep, WindowDays
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.statistics import (
    CompensationStatsResponse,
    CompTrajectoryResponse,
    CompTrendsResponse,
    DemandResponse,
    DisclosureTrendsResponse,
    EquityValidationResponse,
    LevelGuideResponse,
    StatisticsOverviewResponse,
    StatsResponse,
)
from tracker.api.serializers.jobs import serialize_job
from tracker.comp_providers.base import OUR_PAY_COUNTRY
from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.db.models import (
    Cluster,
    CompanyProfile,
    CompSnapshot,
    DisclosureSnapshot,
    Favorite,
    Job,
    JobLifecycleEvent,
    JobLineageLink,
    JobPlaceSetMember,
    JobSkill,
    JobTwinLink,
    Notification,
    SkillConcept,
)
from tracker.db.queries.jobs import (
    board_count_stmt,
    exclude_hidden,
    facet_count_stmt,
    insights_role_conds,
    most_updated_open_stmt,
    new_listing_clause,
    open_in_scope_count_stmt,
    pair_on_board,
    place_set_later_ids,
    plausibly_listed,
    resolve_ordering,
    row_context,
)
from tracker.db.queries.reference_pay import reported_rows, split_rows
from tracker.db.queries.scope import level_key_expr
from tracker.db.queries.skills import ELIGIBLE_REQUIREMENT
from tracker.db.queries.skills import top_skills as read_top_skills
from tracker.intelligence_runtime.disclosed_comp import residual_band_versions
from tracker.levels.companies import COMPANIES
from tracker.levels.ladder import flat_guide, level_guide, lineage
from tracker.lineage.counts import is_new_job_clause
from tracker.platform.util import local_day_start_utc
from tracker.plugins.registry import PAY_LEVELS, reader_providers
from tracker.plugins.status import reference_changes
from tracker.schema import OUR_ESTIMATE_SOURCE, Arrival
from tracker.skills.analytics import COMPETENCY_CATEGORIES
from tracker.taxonomy.tracks import TRACKS, allowed_bands_for

router = APIRouter()


@router.get("/api/stats", response_model=StatsResponse)
async def stats(session: SessionDep, hidden: OffBoardDep) -> dict:
    today = local_day_start_utc()
    # The three chips open Board views (`/`, the New and Reposted lenses), so
    # each counts through the Board's own filter with the params that view
    # sends: dismissed roles, hidden companies and scope drop out exactly as
    # they do from the list. The New lens is the rule each row lights by
    # (`new_listing_clause`).
    board = {"status": "open", "hidden": hidden}
    open_total = await session.scalar(board_count_stmt(board))
    new_today = await session.scalar(board_count_stmt({**board, "new_today_only": True}))
    reposted_today = await session.scalar(board_count_stmt({**board, "repost_today_only": True}))
    # Lifecycle events have no company column; scope them to non-hidden jobs.
    visible_job_ids = exclude_hidden(select(Job.id).where(Job.in_scope.is_(True)), hidden)
    closed_today = await session.scalar(
        select(func.count())
        .select_from(JobLifecycleEvent)
        .where(
            JobLifecycleEvent.event_type == "closed",
            JobLifecycleEvent.created_at >= today,
            JobLifecycleEvent.job_id.in_(visible_job_ids),
        )
    )
    # Open roles per company, a place set once: the same count as
    # `open_total`, split.
    by_company = (await session.execute(facet_count_stmt(Job.company, hidden))).all()
    saved_total = await session.scalar(select(func.count()).select_from(Favorite))
    # The review queue's own count: the pairs it lists, so the
    # badge and the queue it opens cannot disagree.
    review_pending = await session.scalar(
        select(func.count())
        .select_from(JobLineageLink)
        .where(
            JobLineageLink.status == "pending",
            JobLineageLink.confidence == "suspected",
            pair_on_board(JobLineageLink.job_id, JobLineageLink.prior_job_id, hidden),
        )
    )
    twin_review_pending = await session.scalar(
        select(func.count())
        .select_from(JobTwinLink)
        .where(
            JobTwinLink.status == "pending",
            JobTwinLink.confidence == "suspected",
            pair_on_board(JobTwinLink.job_a_id, JobTwinLink.job_b_id, hidden),
        )
    )
    notif_unread = await session.scalar(
        select(func.count()).where(
            Notification.dismissed_at.is_(None),
            Notification.read_at.is_(None),
        )
    )
    notif_high_unread = await session.scalar(
        select(func.count()).where(
            Notification.dismissed_at.is_(None),
            Notification.read_at.is_(None),
            Notification.priority == "high",
        )
    )
    return {
        "open_total": open_total or 0,
        "new_today": new_today or 0,
        "reposted_today": reposted_today or 0,
        "closed_today": closed_today or 0,
        "saved_total": saved_total or 0,
        "review_pending": (review_pending or 0) + (twin_review_pending or 0),
        "notif_unread": notif_unread or 0,
        "notif_high_unread": notif_high_unread or 0,
        "by_company": {c: n for c, n in by_company},
    }


@router.get("/api/statistics/overview", response_model=StatisticsOverviewResponse)
async def statistics_overview(
    session: SessionDep, hidden: OffBoardDep, scope: InsightsScopeDep, days: WindowDays = 30
) -> dict:
    """Cockpit aggregate for the Statistics landing tab.

    KPI tiles + a short generated brief + highlight strips, pulling from the demand,
    skills, and cluster layers. `days<=0` means all-time; otherwise the new/closed
    counters are scoped to the last N days of lifecycle events (so the period control
    is meaningful as history accrues).
    """
    all_time = days <= 0
    cutoff = None if all_time else datetime.now(UTC) - timedelta(days=days)

    open_total = await session.scalar(open_in_scope_count_stmt(hidden, *scope.conds()))
    companies = await session.scalar(
        exclude_hidden(
            select(func.count(func.distinct(Job.company))).where(
                Job.status == "open", Job.in_scope.is_(True), *scope.conds()
            ), hidden
        )
    )
    saved_total = await session.scalar(select(func.count()).select_from(Favorite))

    visible_job_ids = exclude_hidden(select(Job.id).where(Job.in_scope.is_(True), *scope.conds()), hidden)

    def _events(kind: str):
        stmt = (
            select(func.count())
            .select_from(JobLifecycleEvent)
            .where(
                JobLifecycleEvent.event_type == kind,
                JobLifecycleEvent.job_id.in_(visible_job_ids),
            )
        )
        return stmt if cutoff is None else stmt.where(JobLifecycleEvent.created_at >= cutoff)

    # An opening is Pace's: a role first seen in the window, a place set once,
    # so Overview's "new" and Pace's "opened" are one number. A first read's
    # find was already listed (`schema.Arrival`): counted apart, never as new,
    # and neither is a repost.
    openings = exclude_hidden(
        select(
            func.count().filter(
                Job.arrival.is_distinct_from(Arrival.FIRST_READ.value), is_new_job_clause()
            ),
            func.count().filter(Job.arrival == Arrival.FIRST_READ.value),
        ).where(Job.in_scope.is_(True), *scope.conds(), Job.id.notin_(place_set_later_ids())),
        hidden,
    )
    if cutoff is not None:
        openings = openings.where(Job.first_seen >= cutoff)
    new_count, first_scan_count = (await session.execute(openings)).one()
    closed_count = await session.scalar(_events("closed"))

    # Top skills (distinct open jobs with a displayable requirement),
    # industries excluded (a vertical is not a skill).
    top_skills = [
        {"term": s["term"], "category": s["category"], "job_count": s["job_count"]}
        # Competencies apart: the most-named concepts are process,
        # leadership or collaboration, which would lead every Overview.
        for s in await read_top_skills(
            session, hidden, limit=5,
            narrowed=[*scope.conds(), SkillConcept.category.notin_(COMPETENCY_CATEGORIES)],
        )
    ]

    # Largest clusters, sized by the postings on the Board: `Cluster.size` is
    # precomputed over every company, hidden and unfollowed ones too, so read
    # alone it ranks clusters by roles this page excludes. The same
    # rule as `/api/clusters`.
    sizes = (
        await session.execute(
            exclude_hidden(
                select(Job.cluster_id, func.count().label("n")).where(
                    Job.cluster_id.isnot(None), Job.status == "open", Job.in_scope.is_(True),
                    *scope.conds(),
                ),
                hidden,
            )
            .group_by(Job.cluster_id)
            .order_by(func.count().desc(), Job.cluster_id)
            .limit(3)
        )
    ).all()
    by_id = {
        c.id: c
        for c in (
            await session.scalars(select(Cluster).where(Cluster.id.in_([cid for cid, _ in sizes])))
        ).all()
    }
    top_clusters = [
        {"id": c.id, "family_hint": c.family_hint, "terms": [t["term"] for t in (c.top_terms or [])[:3]], "size": n}
        for cid, n in sizes
        if (c := by_id.get(cid)) is not None
    ]

    # Open the longest: the open role listed longest, by the age one posting
    # shows (`listed_days`) and ordered by the Board's Age sort, its SQL twin.
    # Never our first-sighting clock: that is an aggregate's measure, not a
    # posting's age.
    # Three, beside the three largest groups, so the row stays even. Only
    # plausible ages.
    oldest = (
        await session.scalars(
            exclude_hidden(
                select(Job).where(*insights_role_conds(), *scope.conds(), plausibly_listed()), hidden
            ).order_by(*resolve_ordering("days_open", "desc")).limit(3)
        )
    ).all()
    longest = [
        {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "listed_days": serialize_job(job)["listed_days"],
        }
        for job in oldest
    ]

    return {
        "days": days,
        "kpis": {
            "open_total": open_total or 0,
            "new_count": new_count or 0,
            "first_scan_count": first_scan_count or 0,
            "closed_count": closed_count or 0,
            "companies": companies or 0,
            "saved_total": saved_total or 0,
        },
        "top_skills": top_skills,
        "top_clusters": top_clusters,
        "longest_open": longest,
    }


@router.get("/api/statistics/compensation", response_model=CompensationStatsResponse)
async def statistics_compensation(session: SessionDep, hidden: OffBoardDep, narrowed: InsightsScopeDep) -> dict:
    """Compensation across the roles open now: the roles Insights describes.

    Two different quantities live in this payload and must not be conflated:

    * `overall` / `histogram` / `by_level` / `by_company` / `by_family` / `by_skill`
      aggregate `Job.comp_median`, which is an *imputed total-comp estimate* — a
      lookup keyed by (company, level, family), not anything an employer said. It
      carries very few distinct values, so it is a reference point, not a sample.
    * `disclosed` carries the bands employers actually printed in the posting, as
      *base salary* (see `build_disclosed_bands`). Base pay and total comp cannot
      share an axis, so the UI keeps them in separate panels.
    * `disclosure` is the *rate* — how many open roles state pay at all, overall
      and per company/level. Basis-independent, and denominated in roles the
      disclosure pass has actually read (see `build_disclosure_rates`).

    Coverage is reported so the UI can state how much of the open set is estimated.

    No window. Keeping roles FIRST SEEN in the last N days would change the
    population, not the period: most open postings are first seen recently, so
    a 30-day window is nearly all-time and a 7-day one a sample of whatever was
    onboarded that week. The trend routes carry time.
    """
    # One predicate for every query below: filtering only some of them would mix
    # populations and silently misreport the coverage percentage.
    scope = [*insights_role_conds(), *narrowed.conds()]
    if hidden:
        scope.append(Job.company.notin_(hidden))

    total_open = await session.scalar(select(func.count()).where(*scope))
    # Every grouping by level reads the level key, never the stored band: a role
    # whose level we cannot place is `unstated`, not the Mid its sort default
    # says or the Senior/Staff a role word guessed.
    level = level_key_expr(Job).label("level")
    # The estimate is drawn in US dollars, the currency `stats` names. An
    # estimate in another currency (a plugin pricing non-US rungs) is not on
    # that axis, so it counts as unpriced here: nothing is converted.
    in_usd = Job.comp_currency == "USD"
    rows = (
        await session.execute(
            select(Job.company, Job.level_band, Job.family, case((in_usd, Job.comp_median)).label("comp_median"),
                   level).where(*scope)
        )
    ).all()

    stats = build_comp_stats([(r.company, r.level, r.family, r.comp_median) for r in rows], total_open or 0)

    # Roles our dataset prices by their base alone have no total, so the block
    # above cannot hold them; they are reported apart and labelled, never on
    # the totals' axis.
    base_rows = (
        await session.execute(
            select(Job.company, level, Job.family, Job.comp_base_median).where(
                *scope, in_usd, Job.comp_component == "base", Job.comp_median.is_(None),
                Job.comp_base_median.isnot(None),
            )
        )
    ).all()
    base = build_comp_stats([tuple(r) for r in base_rows], total_open or 0)
    stats["base_estimates"] = {
        "min_roles": base["min_roles"],
        "coverage": {"with_base": base["coverage"]["with_comp"], "total_open": base["coverage"]["total_open"]},
        "overall": base["overall"],
        "by_level": base["by_level"],
        "by_company": base["by_company"],
        "by_family": base["by_family"],
    }

    # "Skills that pay": what roles naming a skill concept pay over like
    # roles, same level and discipline. The stored band, not the
    # level key: it compares estimates with estimates looked up at that band,
    # and shows no level. Industries are not skills,
    # and what every role is expected to do sets no role apart.
    skill_rows = (
        await session.execute(
            select(SkillConcept.slug, SkillConcept.display, Job.level_band, Job.family, Job.comp_median)
            .select_from(JobSkill)
            .join(SkillConcept, SkillConcept.id == JobSkill.concept_id)
            .join(Job, Job.id == JobSkill.job_id)
            .where(
                *scope,
                *ELIGIBLE_REQUIREMENT,
                SkillConcept.category.notin_(COMPETENCY_CATEGORIES),
                Job.comp_median.isnot(None),
                in_usd,
            )
        )
    ).all()
    by_skill = rank_skill_comp(
        [(r.slug, r.level_band, r.family, r.comp_median) for r in skill_rows],
        [(r.level_band, r.family, r.comp_median) for r in rows],
    )
    stats["by_skill"] = by_skill

    # Employer-disclosed bands (base salary), kept apart from the estimate above.
    disclosed_rows = (
        await session.execute(
            select(
                Job.company,
                level,
                Job.disclosed_base_min,
                Job.disclosed_base_max,
                Job.disclosed_pay_basis,
                Job.disclosed_currency,
                Job.disclosed_pay_period,
            ).where(*scope, Job.disclosed_base_min.isnot(None))
        )
    ).all()
    stats["disclosed"] = build_disclosed_bands([tuple(r) for r in disclosed_rows])

    # Disclosure rate. Its own scan, unfiltered by `disclosed_base_min`: the rate's
    # denominator is every *checked* open role, so the roles that disclosed nothing
    # are exactly the rows that matter and the bands query above excludes them.
    rate_rows = (
        await session.execute(
            select(
                Job.company,
                level,
                Job.structured_at,
                Job.disclosed_base_min,
                Job.disclosed_base_max,
                Job.disclosed_pay_basis,
            ).where(*scope)
        )
    ).all()
    stats["disclosure"] = build_disclosure_rates([tuple(r) for r in rate_rows])

    stats["currency"] = "USD"
    return stats


async def _observed_splits(session: AsyncSession) -> dict:
    """Real per-level base/stock/bonus shares, harvested into Company Profiles.

    Where a (company, band) is covered, the split heuristic is not used at all.
    Only rows with a measured stock_pct qualify — NULL means "split unknown",
    not "no equity" (a 0.0, e.g. Netflix, is a real measurement and is kept).
    Keyed by (company, band) only, so it reads the reference ladder alone: with
    every family harvested an unfiltered read would let whichever
    family's row came last silently overwrite the rest. A band that collapses
    several rungs (Microsoft 65-67 are all principal) reads the row
    `comp_package.choose_rung_row` picks, the one the package beside it reads,
    never whichever row Postgres returned last.
    """
    providers = await reader_providers(session)
    splits_read = await split_rows(session, providers, OUR_PAY_COUNTRY)
    grouped: dict[tuple[str, str], list] = {}
    for row in us_rows(splits_read):  # a worldwide-mix row is not US pay
        grouped.setdefault((row.company_slug, row.band), []).append(row)
    splits: dict = {}
    for (company, band), candidates in grouped.items():
        chosen = choose_rung_row(company, band, candidates)
        splits[(company, band)] = {
            "base_pct": chosen.base_pct,
            "stock_pct": chosen.stock_pct,
            "bonus_pct": chosen.bonus_pct,
        }
    return splits


@router.get("/api/statistics/comp-trajectory", response_model=CompTrajectoryResponse)
async def statistics_comp_trajectory(session: SessionDep, hidden: OffBoardDep) -> dict:
    """Equity decomposition of open-role comp for the "Stock trajectory" view.

    Splits each open role's estimated total comp into base/bonus/equity (see
    `comp_split`) and partitions companies into public (equity tracks a listed
    ticker, so it flexes with the stock price) vs private/illiquid. The UI applies
    a stock-price scenario to the equity slice client-side. The roles
    `/api/statistics/compensation` describes: a place set once.
    """
    rows = (
        await session.execute(
            exclude_hidden(
                select(Job.company, Job.level_band, Job.family, Job.comp_median).where(*insights_role_conds()),
                hidden,
            )
        )
    ).all()

    observed = await _observed_splits(session)

    # Resolved identity beats the hardcoded PUBLIC_TICKERS table, which cannot
    # know about a company that listed later.
    profile_rows = (
        await session.execute(
            select(
                CompanyProfile.slug,
                CompanyProfile.is_public,
                CompanyProfile.ticker,
                CompanyProfile.equity_vehicle,
            )
        )
    ).all()
    profiles = {
        r.slug: {
            "is_public": r.is_public,
            "ticker": r.ticker,
            "equity_vehicle": r.equity_vehicle,
        }
        for r in profile_rows
    }

    # Our split heuristic is our data: it splits nothing while a plugin answers
    # pay, so a company its rows do not split is left out.
    ours = (await reader_providers(session)).source_for(PAY_LEVELS) is None
    return build_comp_trajectory(
        [tuple(r) for r in rows], observed=observed, profiles=profiles, heuristic=ours
    )


@cache
def _level_guide() -> dict:
    """The level guide is the pinned atlas and the code's catalog, both fixed
    for the life of the process, so it is built once."""
    guided = sorted(slug for slug, record in COMPANIES.items() if any(ladder.guide for ladder in record.ladders))
    known = set(guided)
    return {
        "companies": [{"slug": slug, "flat": flat_guide(slug), "levels": level_guide(slug)} for slug in guided],
        "unguided": [
            {"slug": slug, "same_as": next((up for up in lineage(slug)[1:] if up in known), None)}
            for slug in sorted(COMPANY_DISCOVERY) if slug not in known
        ],
        "tracks": {track.slug: allowed_bands_for(track.slug) for track in TRACKS},
    }


@router.get("/api/statistics/levels", response_model=LevelGuideResponse, response_model_exclude_unset=True)
async def statistics_levels() -> dict:
    """How every company with a reviewed ladder names each level, followed or
    not, for the Levels tab. Reference data: it reads no postings, so the
    Insights scope and window do not apply. Who is followed comes from
    `/api/companies/discovery`, which the screen already reads."""
    return _level_guide()


@router.get("/api/statistics/equity-validation", response_model=EquityValidationResponse)
async def statistics_equity_validation(session: SessionDep, hidden: OffBoardDep) -> dict:
    """Diagnostic: the modeled equity slice checked against employer-stated cash.

    For open roles with a stated base band (basis='base'), implied equity =
    comp_median − stated base × (1 + bonus share); `build_equity_residuals`
    aggregates that per (company, band) and compares it to the modeled equity
    share. Deliberately a separate endpoint — this is a model-confidence
    surface, not part of the hot compensation payload.
    """
    scope = [Job.status == "open", Job.in_scope.is_(True), Job.disclosed_base_min.isnot(None)]
    if hidden:
        scope.append(Job.company.notin_(hidden))
    rows = (
        await session.execute(
            select(
                Job.company,
                Job.level_band,
                Job.comp_median,
                Job.disclosed_base_min,
                Job.disclosed_base_max,
                Job.disclosed_currency,
                Job.disclosed_pay_basis,
                Job.disclosed_pay_period,
                Job.disclosed_bonus_pct,
                Job.structured_prompt_version,
            ).where(*scope)
        )
    ).all()

    observed = await _observed_splits(session)
    providers = await reader_providers(session)
    payload = build_equity_residuals(
        [tuple(r) for r in rows],
        observed=observed,
        # The current parser's stamp and v5's: a connector band keeps the stamp
        # it was written with, since the text pass never re-reads it.
        accepted_versions=await residual_band_versions(session),
        # Our split heuristic is our data: it models no share for a plugin's
        # figure, so a band its rows do not split is counted out.
        heuristic=providers.source_for(PAY_LEVELS) is None,
    )

    # Second, independent cross-check: self-reported realized equity share (a
    # plugin's `pay.observations`) vs the model. Only the latest snapshot; hidden
    # companies excluded. A reference surface, so a missing snapshot must not
    # break the primary residual payload.
    reported, latest = await reported_rows(session, providers, hidden=hidden or ())
    payload["reported"] = build_source_comparison(
        [(r.company_slug, r.band, r.total_usd, r.equity_usd) for r in reported],
        observed=observed,
        sources={r.provider for r in reported},
    )
    payload["reported"]["snapshot_date"] = latest.isoformat() if latest else None
    return payload


@router.get("/api/statistics/comp-trends", response_model=CompTrendsResponse)
async def statistics_comp_trends(
    session: SessionDep, hidden: OffBoardDep, scope: InsightsScopeDep, dim: str = "overall", days: WindowDays = 90
) -> dict:
    """Compensation percentiles over time from the `comp_snapshot` raw daily values.

    `dim` selects the grouping (`overall`/`company`/`level`/`family`); returns a
    shared sorted `dates` axis + one aligned `series` per key with `{date, p25, p50,
    p75, p90}` points (null-filled on days with no slice). `days<=0` = all history.

    Percentiles are recomputed here from the raw values of the *visible* companies,
    so hiding a company retroactively and exactly removes it from every point in the
    series (impossible from `comp_metrics`, whose stored percentiles can't be
    re-aggregated). History accrues one snapshot-set per pipeline run.
    """
    if dim not in ("overall", "company", "level", "family"):
        raise api_error(400, ErrorCode.INVALID_INPUT, "invalid dim")

    cutoff = None if days <= 0 else (
        datetime.now(UTC) - timedelta(days=days)
    ).replace(hour=0, minute=0, second=0, microsecond=0)

    # The series of the source answering pay: ours, or the plugin's
    # while it is selected; never a day written before sources were kept apart.
    shown = (await reader_providers(session)).source_for(PAY_LEVELS) or OUR_ESTIMATE_SOURCE
    stmt = select(CompSnapshot).where(CompSnapshot.source == shown)
    if cutoff is not None:
        stmt = stmt.where(CompSnapshot.metric_date >= cutoff)
    if hidden:
        stmt = stmt.where(CompSnapshot.company.notin_(hidden))
    stmt = stmt.where(*scope.conds(company=CompSnapshot.company, family=CompSnapshot.family))
    snapshots = (await session.scalars(stmt)).all()

    built = build_comp_trend_series(
        (
            (
                row.metric_date.date().isoformat(),
                row.company,
                row.level_band,
                row.family,
                row.comp_values,
            )
            for row in snapshots
        ),
        dim,
    )

    # Each series is its key; the client names it by `dim`.
    return {
        "dim": dim, "days": days, "dates": built["axis"], "series": built["series"],
        "reference_changes": await reference_changes(session, cutoff),
    }


@router.get("/api/statistics/disclosure-trends", response_model=DisclosureTrendsResponse)
async def statistics_disclosure_trends(
    session: SessionDep, hidden: OffBoardDep, scope: InsightsScopeDep, dim: str = "overall", days: WindowDays = 90
) -> dict:
    """Pay transparency over time from the `disclosure_snapshot` daily cells.

    `dim` selects the grouping (`overall`/`company`/`level`); returns a shared
    sorted `dates` axis + one aligned `series` per key. Each point carries both
    quantities the snapshot separates:

    * `rate` = `disclosed / checked` — the share of read open roles stating a pay
      band. Basis-independent; `open - checked` is reported so the UI can show the
      extraction backlog instead of counting it as employer silence.
    * `low_p50` / `high_p50` — the median published band, pooled strictly within
      `basis` (base salary). One vote per distinct band, since an employer hangs
      many reqs off one band.

    Counts are re-summed here from the raw cells rather than read as stored
    aggregates, so hiding a company retroactively and exactly removes it from
    every point in the series — the same property `comp-trends` relies on.
    """
    if dim not in ("overall", "company", "level"):
        raise api_error(400, ErrorCode.INVALID_INPUT, "invalid dim")

    cutoff = None if days <= 0 else (
        datetime.now(UTC) - timedelta(days=days)
    ).replace(hour=0, minute=0, second=0, microsecond=0)

    # Columns, not entities: the window holds a cell per company, level and
    # basis each day, and building an object per cell costs more than the query.
    stmt = select(
        DisclosureSnapshot.metric_date,
        DisclosureSnapshot.company,
        DisclosureSnapshot.level_band,
        DisclosureSnapshot.pay_basis,
        DisclosureSnapshot.roles,
        DisclosureSnapshot.checked,
        DisclosureSnapshot.bands,
    )
    if cutoff is not None:
        stmt = stmt.where(DisclosureSnapshot.metric_date >= cutoff)
    if hidden:
        stmt = stmt.where(DisclosureSnapshot.company.notin_(hidden))
    # The snapshot has no family column: the disciplines half of the scope
    # cannot apply, and the UI says so beside the chart.
    stmt = stmt.where(*scope.company_conds(DisclosureSnapshot.company))
    cells = (await session.execute(stmt)).all()

    built = build_disclosure_trend_series(
        ((metric_date.date().isoformat(), *cell) for metric_date, *cell in cells), dim
    )

    # Each series is its key ("cohort", "overall", a company or a level); the
    # client names it.
    series = built["series"]
    return {
        "dim": dim,
        "days": days,
        "basis": DISCLOSURE_BASIS,
        "dates": built["axis"],
        "series": series,
        "cohort": built["cohort"],
    }


class VelocityKpis(BaseModel):
    """Window totals."""

    open_total: int
    opened: int
    updated: int
    closed: int
    reposted: int
    #: Roles a company's first read found: already listed, never in `opened`
    #: or `net`.
    first_scan: int
    net: int
    median_days_open: float | None
    #: Share of the open roles behind `median_days_open` and `aging` that the
    #: employer dated (`analytics.age_basis`); None when there are none.
    employer_dated_share: float | None
    median_observed_listing_duration_days: float | None
    closed_sample: int
    #: The same share over the `closed_sample` postings behind the duration.
    closed_employer_dated_share: float | None


class VelocityAgingBand(BaseModel):
    """A fixed age band (`analytics.velocity.AGING_BANDS`); the client names it
    by `lo`."""

    lo: int
    hi: int | None
    count: int


class VelocityCompany(BaseModel):
    company: str
    open: int
    opened: int
    updated: int
    closed: int
    reposted: int
    median_days_open: float | None
    median_observed_listing_duration_days: float | None


class VelocityOut(BaseModel):
    days: int
    kpis: VelocityKpis
    aging: list[VelocityAgingBand]
    #: Observed listing durations of the postings that closed in the window, on
    #: the aging bands (never a time to hire).
    posted: list[VelocityAgingBand]
    by_company: list[VelocityCompany]


@router.get("/api/statistics/velocity", response_model=VelocityOut)
async def statistics_velocity(
    session: SessionDep, hidden: OffBoardDep, scope: InsightsScopeDep, days: WindowDays = 30
) -> dict:
    """Hiring-velocity motion over a time window (honors the period lens).

    Opened / updated / closed activity + net flow from lifecycle events, the aging
    distribution of still-open roles, and the observed listing duration of roles
    that closed in the window. `days<=0` means all-time. The duration needs a
    spread of closed roles, so it accrues with history; the UI flags a thin sample.

    It is not a time to fill: it measures how long we observed a posting
    advertised, and a public board says nothing about whether anyone was hired.
    """
    all_time = days <= 0
    cutoff = None if all_time else datetime.now(UTC) - timedelta(days=days)
    params: dict = {} if all_time else {"cutoff": cutoff}
    if hidden:
        params["hidden"] = hidden
    # Raw SQL can't take an ORM condition; `<> ALL(:hidden)` is the asyncpg-safe
    # exclusion, added only when something is hidden (empty arrays break inference).
    # The Insights scope, as the same fragment on every raw read.
    scope_job, scope_params = scope.sql("")
    scope_j, _ = scope.sql("j.")
    params.update(scope_params)
    hide_job = (" AND company <> ALL(:hidden)" if hidden else "") + scope_job
    hide_j = " AND ".join(
        c for c in ("j.company <> ALL(:hidden)" if hidden else "", scope_j.removeprefix(" AND ")) if c
    )
    # The roles Insights describes: in scope, a place set once. A set's
    # later members leave the ages, the openings and the durations, so the age
    # bands sum to the headline and an opening at five places is one opening.
    # One clock for the window and the ages: the app's, never the database's
    # `now()` beside a Python cutoff (the two disagree under a pinned test
    # clock).
    params["now"] = datetime.now(UTC)
    # The set is built once, inside the one statement below, and read by its
    # parts. Bound back as an id list it would grow with the data, and a
    # generic plan searches a bound array row by row.
    place_set_later = place_set_later_ids().cte("place_set_later").prefix_with("MATERIALIZED")
    not_later = "NOT ({c}id IN (SELECT id FROM place_set_later))"
    # A first read's find was already listed (`schema.Arrival`): it ages from
    # its listed date, since our first sighting of it is our onboarding, not
    # its opening. Roles we watched open keep the sighting clock.
    start = (
        "CASE WHEN {c}arrival = 'first_read' "
        "THEN least({c}first_posted_at, {c}first_seen) "
        "ELSE coalesce({c}lineage_first_seen, {c}first_seen) END"
    )

    open_total = await session.scalar(open_in_scope_count_stmt(hidden, *scope.conds()))

    # The parts share one column list (`part`, `company`, `days`,
    # `employer_dated`, `event_type`, `n`), each filling the columns it has.
    # Age is measured from the effective (lineage) first_seen so a reposted role
    # keeps accruing days-open instead of resetting. This aggregate keeps our own
    # first-sighting clock on purpose (the same for every source) for every role
    # we watched open; a first read's find starts at its listed date (`start`).
    # `employer_dated` feeds the share served beside it.
    open_sql = (
        "SELECT 'open' AS part, company, floor(extract(epoch FROM "
        f"(:now - {start.format(c='')}))/86400.0) AS days, "
        f"({employer_dated_sql()}) AS employer_dated, NULL::text AS event_type, NULL::bigint AS n "
        "FROM jobs WHERE status='open' AND in_scope IS true AND "
        + not_later.format(c="")
        + hide_job
    )

    # Openings are roles, counted once at their first sighting (`first_seen`),
    # whichever writer stored them: a first read's find is `first_scan`, apart
    # from opened and net; a repost/duplicate successor is `reposted`, so it
    # never inflates either. A place set's later member is the set's own
    # opening, left out. Only in-scope roles count.
    opening_where = [
        c for c in (
            "j.in_scope IS true", not_later.format(c="j."),
            None if all_time else "j.first_seen >= :cutoff", hide_j or None,
        ) if c
    ]
    opening_sql = (
        "SELECT 'event', j.company, NULL, NULL, "
        "CASE WHEN j.arrival = 'first_read' THEN 'first_scan' "
        "     WHEN j.lineage_role IN ('repost','duplicate') THEN 'reposted' "
        "     ELSE 'opened' END, "
        "count(*) "
        "FROM jobs j "
        "WHERE " + " AND ".join(opening_where) + " "
        "GROUP BY j.company, 5"
    )
    # The rest of the motion is events in the window: updates and closings.
    event_where = [
        c for c in (
            "j.in_scope IS true", "e.event_type IN ('changed','closed')",
            None if all_time else "e.created_at >= :cutoff", hide_j or None,
        ) if c
    ]
    event_sql = (
        "SELECT 'event', j.company, NULL, NULL, e.event_type, count(*) "
        "FROM job_lifecycle_events e JOIN jobs j ON j.id = e.job_id "
        "WHERE " + " AND ".join(event_where) + " "
        "GROUP BY j.company, e.event_type"
    )

    # Observed listing duration: one sample per role. A standalone closed job
    # counts; a lineage contributes exactly once, and only when no member is still
    # open — measured from its terminal member back to the effective first_seen.
    # `closed_at` is the reconciliation that FOUND it gone, so this is how long we
    # observed the posting advertised, never a hiring duration.
    hide_j2 = (" AND j.company <> ALL(:hidden)" if hidden else "") + scope_j
    duration_sql = (
        "SELECT 'closed', j.company, floor(extract(epoch FROM "
        f"(j.closed_at - {start.format(c='j.')}))/86400.0), "
        f"({employer_dated_sql('j.')}), NULL, NULL "
        "FROM jobs j LEFT JOIN job_lineage l ON l.id = j.lineage_id "
        "WHERE j.status='closed' AND j.closed_at IS NOT NULL AND j.in_scope IS true AND "
        + not_later.format(c="j.")
        + " "
        "AND (j.lineage_id IS NULL OR (l.open_members = 0 AND j.lineage_seq = l.size))"
        + ("" if all_time else " AND j.closed_at >= :cutoff")
        + hide_j2
    )

    # Column aliases avoid SQLAlchemy Row's reserved attrs (e.g. `.t`, `.count`).
    rows = (
        await session.execute(
            text(" UNION ALL ".join(
                f"({sql})" for sql in (open_sql, opening_sql, event_sql, duration_sql)
            ))
            .columns(*(column(name) for name in ("part", "company", "days", "employer_dated", "event_type", "n")))
            .add_cte(place_set_later),
            params,
        )
    ).all()
    open_rows = [r for r in rows if r.part == "open"]
    duration_rows = [r for r in rows if r.part == "closed"]

    return build_velocity(
        [(r.company, r.days) for r in open_rows],
        [(r.company, r.event_type, r.n) for r in rows if r.part == "event"],
        [(r.company, r.days) for r in duration_rows],
        open_total or 0,
        days,
        open_employer_dated=sum(1 for r in open_rows if r.employer_dated),
        closed_employer_dated=sum(1 for r in duration_rows if r.employer_dated),
    )


@router.get("/api/demand", response_model=DemandResponse)
async def demand(session: SessionDep, hidden: OffBoardDep, scope: InsightsScopeDep) -> dict:
    """The Hiring tab: where the roles Insights describes are open now.

    Read live, a place set once, never by summing `demand_metrics`: a rollup
    slice counts a POSTING once per location group, nested and region-expanded,
    so a role listed at many places reads as hundreds. The rollup stays the longitudinal record its post pass writes."""
    # Every open, in-scope posting with its place set, so a set's role carries
    # the places of all its members (the Board's place facet) and
    # counts once.
    member_rows = (
        await session.execute(
            exclude_hidden(
                select(Job.id, Job.company, Job.locations, JobPlaceSetMember.set_id)
                .outerjoin(
                    JobPlaceSetMember,
                    (JobPlaceSetMember.job_id == Job.id) & (JobPlaceSetMember.status == "auto"),
                )
                .where(Job.status == "open", Job.in_scope.is_(True), *scope.conds()),
                hidden,
            )
        )
    ).all()
    roles: dict[tuple[str, int], tuple[str, list[str]]] = {}
    for job_id, company, locations, set_id in member_rows:
        key = ("set", set_id) if set_id is not None else ("job", job_id)
        roles.setdefault(key, (company, []))[1].extend(locations or [])
    open_by_company: dict[str, int] = {}
    for company, _ in roles.values():
        open_by_company[company] = open_by_company.get(company, 0) + 1

    # The motion, by the header's lenses: roles new by the Board's rule (not
    # reposts) and roles closed today, a place set once. Not for me stays in:
    # Insights is the market.
    later = place_set_later_ids()
    new_rows = (
        await session.execute(
            exclude_hidden(
                select(Job.company, func.count()).where(
                    new_listing_clause(),
                    Job.in_scope.is_(True),
                    Job.id.notin_(later),
                    *scope.conds(),
                ),
                hidden,
            ).group_by(Job.company)
        )
    ).all()
    closed_rows = (
        await session.execute(
            exclude_hidden(
                select(Job.company, func.count(func.distinct(Job.id)))
                .join(JobLifecycleEvent, JobLifecycleEvent.job_id == Job.id)
                .where(
                    JobLifecycleEvent.event_type == "closed",
                    JobLifecycleEvent.created_at >= local_day_start_utc(),
                    Job.in_scope.is_(True),
                    Job.id.notin_(later),
                    *scope.conds(),
                ),
                hidden,
            ).group_by(Job.company)
        )
    ).all()
    new_today = dict(new_rows)
    closed_today = dict(closed_rows)
    companies = sorted(
        (
            {
                "company": company,
                "open": open_by_company.get(company, 0),
                "new_today": int(new_today.get(company, 0)),
                "closed_today": int(closed_today.get(company, 0)),
            }
            for company in set(open_by_company) | set(new_today) | set(closed_today)
        ),
        key=lambda c: (-c["open"], -c["new_today"], c["company"]),
    )

    roles_now = exclude_hidden(select(Job).where(*insights_role_conds(), *scope.conds()), hidden)
    # Longest-open: ordered by the age each row shows (`listed_days`), through
    # the Board's Age sort, never by our first sighting.
    # Only plausible ages: a 2016 employer date is a stale date, not
    # a role that has waited ten years. The rest are counted, never hidden.
    longest = (
        await session.scalars(
            roles_now.where(plausibly_listed()).order_by(*resolve_ordering("days_open", "desc")).limit(10)
        )
    ).all()
    implausibly_old = await session.scalar(
        exclude_hidden(
            select(func.count()).where(*insights_role_conds(), *scope.conds(), not_(plausibly_listed())), hidden
        )
    )
    open_count, dated_count = (
        await session.execute(
            exclude_hidden(
                select(
                    func.count(),
                    func.count().filter(text(employer_dated_sql("jobs."))),
                ).select_from(Job).where(*insights_role_conds(), *scope.conds()),
                hidden,
            )
        )
    ).one()
    reposted = (
        await session.scalars(
            roles_now.where(Job.repost_count > 0).order_by(Job.repost_count.desc(), Job.id).limit(10)
        )
    ).all()
    updated_rows = (
        await session.execute(most_updated_open_stmt(limit=10, hidden=hidden).where(*scope.conds()))
    ).all()
    places = build_hiring_places(locations for _, locations in roles.values())
    shown = list({job.id: job for job in [*longest, *reposted, *(job for job, _, _ in updated_rows)]}.values())
    ctx = await row_context(session, shown, unfollowed=hidden.unfollowed, standing=False)
    return {
        "open_total": len(roles),
        "new_today": sum(new_today.values()),
        "closed_today": sum(closed_today.values()),
        "companies": companies,
        "regions": places["regions"],
        "unplaced": places["unplaced"],
        "employer_dated_share": employer_dated_share(dated_count, open_count),
        "longest_open": [serialize_job(j, **ctx) for j in longest],
        "listed_over_a_year": implausibly_old or 0,
        "most_reposted": [serialize_job(j, **ctx) for j in reposted],
        "most_updated_open": [
            {
                **serialize_job(job, **ctx),
                "update_count": int(update_count or 0),
                "last_updated_at": last_updated_at,
            }
            for job, update_count, last_updated_at in updated_rows
        ],
    }
