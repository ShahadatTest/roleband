"""The daily discovery digest: one fit-ranked row per day, instead of one per posting.

Discovery and tracking are two different products and do not share one bell.
Tracking is event-driven and deserves an interrupt (`events.classify_event`,
gated by `tracked.py`). Discovery is a browsing errand with a daily rhythm, and
paying it out as interrupts buries the feed in rows nobody acts on.

The same information lands here as one row per day that had any new role,
ranked by cosine fit against the standing intent vector, so the lead line is
the best role of the day rather than whichever the scraper happened to reach
first. Grouping alone is not enough; unranked noise is noise.

Idempotent by construction. Every run recomputes the whole day from
`job_lifecycle_events` and rewrites that day's single row, so every run of a
day converges on one accurate digest instead of appending partial ones, and a
re-run after a failure repairs the row rather than duplicating it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_store import off_board_company_slugs
from tracker.db.models import Job, JobFeedback, JobLifecycleEvent
from tracker.db.queries.companies import display_names
from tracker.db.queries.jobs import listed_recently_clause
from tracker.db.repo import ADDED_FROM_INVENTORY
from tracker.notifications import say as S
from tracker.notifications.channels import deliver
from tracker.notifications.events import ClassifiedNotif, _said
from tracker.notifications.render import company_namer
from tracker.platform.local_zone import local_zone
from tracker.search import fit as fit_scale
from tracker.search.fit import fit_expr
from tracker.semantic.intent import build_intent_vector
from tracker.settings_store import get_intent_embedding

logger = logging.getLogger(__name__)


#: Roles carried in the digest's `meta.top` (the body names only the first).
DIGEST_TOP_N = 5


#: Hard ceiling on rows pulled for ranking. A day that opens more than this is
#: already past any digest's usefulness; its count and companies stay exact,
#: counted over every candidate once the sample reaches the ceiling
#: (`_digest_totals`).
_DIGEST_SCAN_LIMIT = 500


# Run health has no notification of its own: it would name the same error
# sources and drift rows as the `sync_warning`/`sync_failed` notification for
# that run, so `run_diagnostics` hangs off the sync notification itself (see
# `classify_sync_result`).


@dataclass(frozen=True)
class DigestMatch:
    """One newly-opened role considered for the day's digest."""

    job_id: int
    company: str
    title: str
    fit: float | None = None


def fit_label(fit: float | None) -> str | None:
    """The digest's word for the fit band a score falls in, read from the edges
    the Intelligence screen draws (`search/fit.FIT_BAND_EDGES`), so the two
    never disagree about what "Strong" means."""
    if fit is None:
        return None
    for _key, label, edge in fit_scale.FIT_BAND_EDGES:
        if fit >= edge:
            return label
    return "Weak"


def classify_daily_digest(
    day: str,
    matches: list[DigestMatch],
    top_n: int = 5,
    *,
    names: Mapping[str, str] | None = None,
    totals: tuple[int, list[str]] | None = None,
) -> ClassifiedNotif | None:
    """One row for the day's new roles, fit-ranked. None when nothing opened.

    `totals` is (count, companies) over every role the day opened, for a day
    whose `matches` are a capped sample; without it both come from `matches`.

    No notification per new posting: discovery is a browsing errand with a
    daily rhythm, not an interrupt per role, so the same information is one row
    per day that had any new role at all, with nothing lost.

    Ranking, not just grouping: `matches` arrives sorted by cosine fit against
    the standing intent vector, so the body leads with the best role of the day
    rather than an arbitrary one. Grouped noise is still noise.

    No pay-threshold alert either: `comp_median` is a company+level cohort
    lookup, so a threshold on it says only "this cohort pays well", never "this
    role does", and the fit ranking already orders the same roles by something
    that is actually about the role.
    """
    if not matches:
        return None

    count, companies = totals if totals is not None else (len(matches), sorted({m.company for m in matches}))
    top = matches[:top_n]
    lead = top[0]
    band = fit_label(lead.fit)

    lead_say: S.Say = S.say("notif-digest-lead", title=lead.title, company=company_namer(names)(lead.company))
    if band:
        lead_say = S.say("notif-digest-fit", band=S.say(f"notif-fit-{band.lower()}"), lead=lead_say)
    if count > 1:
        lead_say = S.say("notif-digest-more", lead=lead_say, more=count - 1)
    return ClassifiedNotif(
        priority="normal",
        category="daily_digest",
        meta={
            "day": day,
            "count": count,
            "companies": companies,
            "ranked": any(m.fit is not None for m in matches),
            "say": _said(S.say("notif-digest", count=count), lead_say),
            "top": [
                {
                    "job_id": m.job_id,
                    "company": m.company,
                    "title": m.title,
                    "fit": round(m.fit, 4) if m.fit is not None else None,
                    "fit_band": fit_label(m.fit),
                }
                for m in top
            ],
        },
    )


def local_today() -> date:
    """The user's current calendar day, in the machine's own timezone.

    Deliberately local, not UTC. This is a local-first single-user tool, and a
    "daily" digest that rolls over at UTC midnight cuts the day in the wrong
    place for everyone not on UTC -- at UTC+2, roles found after 01:00 local
    land in *yesterday's* digest and the morning read is short by exactly the
    roles the night scrape just discovered.
    """
    return datetime.now(local_zone()).date()


def digest_days(moments: Iterable[datetime | None]) -> list[date]:
    """Every local calendar day a run touched, today always included.

    The scheduler runs through the night, so a scrape spanning local midnight is
    a nightly occurrence, not an edge case. Its events land on BOTH sides of the
    boundary, and reconciling only `local_today()` leaves the earlier group in no
    digest at all: yesterday's row was computed before those roles existed, and
    nothing goes back for them.

    Today is always in the set so a run that produced no events still reconciles
    the current day.
    """

    tz = local_zone()
    days = {local_today()}
    for moment in moments:
        if moment is None:
            continue
        # Rows are written tz-aware; a naive one could only come from a DB that
        # dropped the offset, and reading it as UTC is what the column means.
        aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        days.add(aware.astimezone(tz).date())
    return sorted(days)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """Local midnight to local midnight, tz-aware so the DB comparison is exact."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=local_zone())
    return start, start + timedelta(days=1)


def _candidate_stmt(day: date, tracked: set[int], off_board: Sequence[str] = ()) -> Select:
    """Roles first stored on `day` that are new by the Board's rule at the
    day's end, and still what the user asked to see.

    Five exclusions, each load-bearing:

    * a creation event (`opened` by a scan, `added` by a scope change) -- a
      change or a closure is not a discovery.
    * not listed recently (`listed_recently_clause`) -- a posting that was
      on the board long before we stored it, or that only a company's first
      read dates, is not news.
    * `lineage_role` successors -- a repost is the same role wearing a new
      req_id, and announcing it as new would count a single role over and
      over.
    * tracked ids -- those already produced their own per-role notification;
      appearing in both channels would double-report one event.
    * dismissed ("not for me") -- the user has already answered this question,
      and a digest that re-offers a rejected role is not learning from them.

    `in_scope` and `off_board` keep the digest honest against the Board: the
    digest must never advertise a role the Board would not display, so a
    hidden company's new roles never reach it.
    """
    start, end = _day_bounds(day)
    conds = [
        JobLifecycleEvent.event_type.in_(("opened", ADDED_FROM_INVENTORY)),
        JobLifecycleEvent.created_at >= start,
        JobLifecycleEvent.created_at < end,
        listed_recently_clause(end),
        Job.in_scope.is_(True),
        func.coalesce(Job.lineage_role, "original").not_in(("repost", "duplicate")),
        Job.id.not_in(select(JobFeedback.job_id).where(JobFeedback.verdict == "dismissed")),
    ]
    if tracked:
        conds.append(Job.id.not_in(tracked))
    if off_board:
        conds.append(Job.company.not_in(list(off_board)))
    return select(Job).join(JobLifecycleEvent, JobLifecycleEvent.job_id == Job.id).where(and_(*conds))


async def collect_digest_matches(
    session: AsyncSession, day: date, tracked: set[int]
) -> list[DigestMatch]:
    """The day's new roles, best fit first. Unranked (no intent signal) keeps DB order.

    A fresh install has no statement and no feedback, so `build_intent_vector`
    returns None. The digest still ships -- unranked but complete -- rather than
    withholding the day's roles until the user has trained it.
    """
    base = _candidate_stmt(day, tracked, await off_board_company_slugs(session)).distinct()

    stored = await get_intent_embedding(session)
    intent_vec = await build_intent_vector(session, stored["vector"] if stored else None)

    if intent_vec is None:
        rows = (await session.scalars(base.limit(_DIGEST_SCAN_LIMIT))).all()
        return [DigestMatch(job_id=j.id, company=j.company, title=j.title) for j in rows]

    # The same expression the settings instrument bins; a
    # compile-comparison test holds the two to identical SQL.
    fit = fit_expr(intent_vec).label("fit")
    # Rows without an embedding are ranked last rather than dropped: the digest
    # is a count of what opened, and silently shrinking it would misreport the day.
    ranked = (
        select(Job, fit)
        .where(Job.id.in_(select(base.subquery().c.id)))
        .order_by(fit.desc().nullslast())
        .limit(_DIGEST_SCAN_LIMIT)
    )
    return [
        DigestMatch(
            job_id=job.id,
            company=job.company,
            title=job.title,
            fit=float(score) if score is not None else None,
        )
        for job, score in (await session.execute(ranked)).all()
    ]


async def _digest_totals(session: AsyncSession, day: date, tracked: set[int]) -> tuple[int, list[str]]:
    """How many roles `day` opened and at which companies, over every candidate
    rather than the ranked sample."""
    base = _candidate_stmt(day, tracked, await off_board_company_slugs(session))
    count = await session.scalar(base.with_only_columns(func.count(func.distinct(Job.id))))
    companies = (await session.scalars(base.with_only_columns(Job.company).distinct())).all()
    return int(count or 0), sorted(companies)


async def generate_daily_digest(
    session: AsyncSession,
    tracked: set[int],
    *,
    day: date | None = None,
    names: dict[str, str] | None = None,
) -> int:
    """Write or refresh the digest row for `day`. Returns rows written (0 or 1).

    `read_at` is deliberately preserved on refresh. Re-marking the digest unread
    every time a later run adds a role would make it one interrupt per scrape,
    so the day's digest rings once, when it first appears, and thereafter
    updates quietly in place.

    `names` is the register's `slug -> display`, read here when not passed.
    """
    target = day or local_today()
    matches = await collect_digest_matches(session, target, tracked)
    if names is None and matches:
        names = await display_names(session)
    totals = await _digest_totals(session, target, tracked) if len(matches) >= _DIGEST_SCAN_LIMIT else None
    classified = classify_daily_digest(
        target.isoformat(), matches, top_n=DIGEST_TOP_N, names=names, totals=totals,
    )
    if classified is None:
        return 0

    # Refresh, not do-nothing: the day's row is a live recomputation. `created_at`
    # is NOT refreshable, so the digest holds its place in the feed instead of
    # jumping to the top on every scrape.
    await deliver(
        session,
        {
            "created_at": datetime.now(UTC),
            "priority": classified.priority,
            "category": classified.category,
            "title": classified.title,
            "body": classified.body,
            "job_id": None,
            "run_id": None,
            "source_type": "digest",
            "source_id": target.toordinal(),
            "meta": classified.meta or {},
        },
        refresh=("title", "body", "meta", "priority"),
    )
    return 1
