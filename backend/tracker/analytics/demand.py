"""Demand-signal engine.

Rolls up the longitudinal history into `demand_metrics` per (company × family ×
location group) each run: how many are open/new/closed/reposted, how many have
been open a long time (the hard-to-fill signal), and the median days-open. No
surface reads it: the Hiring tab counts roles live, because a slice
counts a POSTING once per location group (nested and region-expanded), so
summed slices multiply each posting. The rollup stays the dated history of
that motion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import column, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import DemandMetric, Job
from tracker.db.queries.jobs import listed_recently_clause, place_set_later_ids
from tracker.lineage.counts import EFFECTIVE_FIRST_SEEN_SQL, event_bucket

#: The post pass that writes this rollup; its derivation row names the day
#: the rollup last completed (`current_demand_day`).
DEMAND_PASS = "demand_metrics"


def demand_day(now: datetime | None = None) -> datetime:
    """The rollup's day: UTC midnight of `now`."""
    return (now or datetime.now(UTC)).replace(hour=0, minute=0, second=0, microsecond=0)


async def compute_demand_metrics(session: AsyncSession, *, today: datetime | None = None) -> int:
    """Recompute today's demand rollups. Returns the number of slices written.

    The day's rows are REPLACED, never merged: a slice whose last posting
    left scope, moved place or closed with no event today is gone from today,
    as in `compute_disclosure_metrics`. Earlier days are untouched. Delete and insert share the
    caller's transaction, so a failure keeps the day it would have replaced.
    """
    long_days = get_settings().long_open_days
    today = today or demand_day()

    # Demand is kept per taxonomy group only: a job's `city_<geonameid>` slugs
    # are left out, so a longitudinal table does not start growing a
    # row per city without anyone deciding it should.
    # Open-job aggregates per (company, family, location_group). Age is measured
    # from the effective (lineage) first_seen so a role that was closed and
    # reposted keeps accruing days-open instead of resetting to zero.
    open_rows = (
        await session.execute(
            text(
                f"""
                SELECT j.company, j.family, lg AS location_group,
                       count(*) AS open_count,
                       count(*) FILTER (
                           WHERE (now() - {EFFECTIVE_FIRST_SEEN_SQL}) >= make_interval(days => :long)
                       ) AS long_open_count,
                       percentile_cont(0.5) WITHIN GROUP (
                           ORDER BY EXTRACT(EPOCH FROM (now() - {EFFECTIVE_FIRST_SEEN_SQL})) / 86400.0
                       ) AS median_days_open
                FROM jobs j, unnest(j.location_groups) AS lg
                WHERE j.status = 'open' AND j.in_scope IS true
                  AND lg NOT LIKE 'city\\_%'
                GROUP BY j.company, j.family, lg
                """
            ),
            {"long": long_days},
        )
    ).all()

    # A place set's later members: their openings are the role's
    # first member's, so they are neither new demand nor reposts. Read by the
    # one ORM rule the Board collapses by, never restated in SQL here, and
    # inside the statement rather than bound back as an id list.
    place_set_later = place_set_later_ids().cte("place_set_later")
    # Roles new by the Board's rule at the day's end, by the same ORM clause.
    listed_recently = (
        select(Job.id).where(listed_recently_clause(today + timedelta(days=1))).cte("listed_recently")
    )

    # Today's lifecycle-event counts per slice, split by lineage_role so an
    # `opened` event on a repost/duplicate successor is booked as reposted, not new.
    event_rows = (
        await session.execute(
            text(
                """
                SELECT j.company, j.family, lg AS location_group,
                       e.event_type, j.lineage_role,
                       j.id IN (SELECT id FROM place_set_later) AS later,
                       j.id IN (SELECT id FROM listed_recently) AS new_listing, count(*) AS n
                FROM job_lifecycle_events e
                JOIN jobs j ON j.id = e.job_id, unnest(j.location_groups) AS lg
                WHERE e.created_at >= :today AND j.in_scope IS true
                  AND lg NOT LIKE 'city\\_%'
                GROUP BY j.company, j.family, lg, e.event_type, j.lineage_role, later, new_listing
                """
            )
            .columns(
                *(
                    column(name)
                    for name in (
                        "company", "family", "location_group", "event_type", "lineage_role",
                        "later", "new_listing", "n",
                    )
                )
            )
            .add_cte(place_set_later, listed_recently),
            {"today": today},
        )
    ).all()

    # Merge into per-slice dicts.
    slices: dict[tuple, dict] = {}

    def _slice(company, family, lg) -> dict:
        key = (company, family, lg)
        if key not in slices:
            slices[key] = {
                "open_count": 0,
                "new_count": 0,
                "closed_count": 0,
                "reposted_count": 0,
                "long_open_count": 0,
                "median_days_open": None,
            }
        return slices[key]

    for r in open_rows:
        s = _slice(r.company, r.family, r.location_group)
        s["open_count"] = r.open_count
        s["long_open_count"] = r.long_open_count
        s["median_days_open"] = float(r.median_days_open) if r.median_days_open is not None else None

    # reposted_count now has two sources (reopened events AND opened events on
    # repost/duplicate successors), so accumulate rather than assign.
    for r in event_rows:
        col = event_bucket(
            r.event_type, r.lineage_role, later_in_place_set=r.later, new_listing=r.new_listing
        )
        if col:
            _slice(r.company, r.family, r.location_group)[col] += r.n

    # `filter_by`, as `comp_trends` does: replacing its own day is not a read, and
    # nothing reads this table (`db/ownership.py` says `readers=()`).
    await session.execute(delete(DemandMetric).filter_by(metric_date=today))
    if slices:
        await session.execute(
            insert(DemandMetric),
            [
                {"metric_date": today, "company": company, "family": family, "location_group": lg, **s}
                for (company, family, lg), s in slices.items()
            ],
        )
    return len(slices)

