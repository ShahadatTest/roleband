"""What an age aggregate rests on: the share of its postings the employer dated.

The Statistics aggregates that summarise posting ages (Pace's median age and
age bands, how long closed postings stayed up, the Hiring rollup's median days
and long-open counts) keep their own clock: RoleBand's first sighting of a
posting or of its lineage. That clock is the same for every source, so it
compares them fairly, and it is deliberately NOT the age one posting shows
(`listed_days`, from `analytics.posting_reality.listing_age`), which starts at
an employer's earlier date where one exists.

A source that dates its postings would otherwise read as no older than one that
does not, so each such aggregate states beside it how many of its postings
carry an employer date. A posting is employer-dated when `jobs.posted_at` is
set; a stored earliest-date column does not change that meaning. The predicate
lives here once. Pure: no database import, so `velocity` stays DB-free.
"""

from __future__ import annotations


def employer_dated_sql(alias: str = "") -> str:
    """The predicate for a `text()` query over `jobs` (`alias` = "j." etc.)."""
    return f"{alias}posted_at IS NOT NULL"


def employer_dated_share(dated: int, total: int) -> float | None:
    """`dated / total` as a fraction; None when the aggregate summarises nothing,
    so an empty sample never reads as "none are dated"."""
    if total <= 0:
        return None
    return dated / total
