"""Per-company measures more than one interface builds from.

Two reads, both about what a company COSTS and what it is WORTH, and both
asked by two surfaces: the dashboard's Follow-all confirmation (through
`/api/companies/*`) and the catalog fact sheet (`scripts.company_fact_sheet`,
the input to the curated-membership decision). They live here rather than in
the router because a read a second surface needs is the
store's, not the transport's.

Both answer in the same shape and with the same discipline — **a company that
was never measured is ABSENT, never zero**. A missing slug means "no open
in-scope role" for the count and "never scanned" for the duration, and the
caller must say which; reading absence as zero would report an unscanned
company as instant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.models import Job, PostingInventory, ScrapeSourceRun, TrackedCompany

#: A run that read the whole board. Our own bounds (`capped`, `bounded`,
#: `truncated`) stopped early and would understate a scan; `failed`/`blocked`
#: measure how quickly a refusal comes back, not how long a scan takes. `empty`
#: read the whole board too: it is how long that board takes.
WHOLE_SCAN_OUTCOMES = (
    SourceOutcome.OK, SourceOutcome.LOSSY, SourceOutcome.DEGRADED, SourceOutcome.EMPTY,
)
SCAN_TIME_WINDOW = timedelta(days=30)


def is_followed() -> ColumnElement[bool]:
    """A `tracked_company` row the user follows: the one spelling.

    Followed (`enabled`) and collectable (`status = 'active'`; a `pending`
    company is not scanned yet). Promotion admits from it, retention splits
    on it, and the Board shows only its companies' postings. Visibility is a
    separate switch over followed companies (the register offers the eye
    only on a followed row) and is not part of this."""
    return and_(TrackedCompany.enabled.is_(True), TrackedCompany.status == "active")


def is_followed_row(row) -> bool:
    """`is_followed()` for a loaded `tracked_company` row: the same two
    conditions in Python, for a caller that already holds the rows."""
    return bool(row.enabled) and row.status == "active"


def followed_company(column) -> ColumnElement[bool]:
    """`column` names a company the user follows."""
    return exists().where(TrackedCompany.slug == column, is_followed())


async def display_names(session: AsyncSession) -> dict[str, str]:
    """Every tracked company's own name, by slug: followed or not, hidden or
    not. A name is not a posting, so no visibility rule applies; a Saved role
    at an unfollowed company still needs its company's name."""
    rows = await session.execute(
        select(TrackedCompany.slug, TrackedCompany.display).where(TrackedCompany.display != "")
    )
    return {slug: display for slug, display in rows.all()}


async def open_counts_by_company(session: AsyncSession) -> dict[str, int]:
    """Open, in-scope postings per company slug — the radar's own count."""
    rows = await session.execute(
        select(Job.company, func.count())
        .where(Job.status == "open", Job.in_scope.is_(True))
        .group_by(Job.company)
    )
    return {company: count for company, count in rows.all()}


async def scan_seconds_by_company(session: AsyncSession) -> dict[str, float]:
    """Median seconds one whole scan of a company takes, over the last 30 days.

    Only companies with a measured scan appear: a company never scanned has no
    duration, and the caller must say so rather than read the absence as zero.
    """
    elapsed = func.extract("epoch", ScrapeSourceRun.finished_at - ScrapeSourceRun.started_at)
    rows = await session.execute(
        select(
            ScrapeSourceRun.company_slug,
            func.percentile_cont(0.5).within_group(elapsed),
        )
        .where(
            ScrapeSourceRun.outcome.in_([outcome.value for outcome in WHOLE_SCAN_OUTCOMES]),
            ScrapeSourceRun.finished_at >= datetime.now(UTC) - SCAN_TIME_WINDOW,
        )
        .group_by(ScrapeSourceRun.company_slug)
    )
    return {slug: round(float(seconds), 1) for slug, seconds in rows.all()}


async def last_read_titles(session: AsyncSession, company: str) -> list[str]:
    """Every role title RoleBand has read at a company: the inventory (all rows
    a scan read, in scope or not) and its postings. What a board
    found under a new address must overlap to be called the company's
    (`board_relocate.shared_titles`)."""
    stmt = union(
        select(PostingInventory.title).where(PostingInventory.company == company),
        select(Job.title).where(Job.company == company),
    )
    return [title for (title,) in (await session.execute(stmt)).all() if title]
