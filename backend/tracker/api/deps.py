"""Shared FastAPI dependencies: session-per-request, the off-Board company list,
and the process's posting-page reads.

A route that waits on the outside (a careers site, a model server, a cloud
provider) ends its read first with `end_read`, so no pooled connection idles
in a transaction while the outside answers.

The SQL guard that applies the list lives with the other browse reads
(`db/queries/jobs.py::exclude_hidden`), and the local calendar day with the
platform helpers (`platform/util.py::local_day_start_utc`)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_store import OffBoardSlugs, off_board_company_slugs
from tracker.db.queries.insights import InsightsScope, Side, resolve_insights_scope
from tracker.db.session import get_session_factory
from tracker.platform.util import MAX_WINDOW_DAYS
from tracker.workflows.posting_pages import OpenPageReads


async def get_session() -> AsyncIterator[AsyncSession]:
    # Resolved per request, not at import: with the embedded server, touching
    # the factory starts Postgres, and importing this module must not.
    async with get_session_factory()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def end_read(session: AsyncSession) -> None:
    """End the request's read before it waits on the outside.

    An open transaction holds its locks for as long as a site or a model takes
    to answer, so a migration's ALTER waits behind it and every later query on
    that table waits behind the ALTER. Rows already loaded keep their values
    (the session does not expire them on commit) and the next statement opens
    a new transaction for whatever the route writes afterwards. Called before
    anything is written: a session holding unsaved changes is refused, because
    ending the read would commit them.
    """
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("a read was ended with unsaved changes in the session")
    await session.commit()


async def get_off_board_companies(session: SessionDep) -> OffBoardSlugs:
    """Per-request list of companies whose postings stay off browse/aggregate
    surfaces: hidden, or not followed. Resolved fresh each request so
    a visibility or follow toggle takes effect at once."""
    return await off_board_company_slugs(session)


#: Companies excluded from every browse/aggregate read surface (never memoized).
OffBoardDep = Annotated[OffBoardSlugs, Depends(get_off_board_companies)]


def get_page_reads(request: Request) -> OpenPageReads:
    """The app's one `OpenPageReads`: its pacer, breakers and
    per-posting readers are process state, so they live on the app that serves
    the opens, not in the workflows layer. Built at the first open rather than
    at startup: that is after the lifespan enabled shared pacing, and an app
    built without its lifespan (the tests) still gets one."""
    reads = getattr(request.app.state, "page_reads", None)
    if reads is None:
        reads = request.app.state.page_reads = OpenPageReads()
    return reads


PageReadsDep = Annotated[OpenPageReads, Depends(get_page_reads)]


# --- Request bounds --------------------------------------------- #
# A paging or window value out of range is a 422 here, before any query: a
# negative LIMIT/OFFSET is a PostgreSQL error after the count queries ran, a
# negative slice drops rows silently, and a window of a million days
# overflows a date. Limits keep their per-route ceilings.


#: Rows to skip: never negative.
Offset = Annotated[int, Query(ge=0)]
#: A window in days where 0 means all time (Statistics' All-time sends 0).
WindowDays = Annotated[int, Query(ge=0, le=MAX_WINDOW_DAYS)]


async def get_insights_scope(
    session: SessionDep,
    side: Annotated[Side, Query()] = "all",
    family: Annotated[list[str] | None, Query()] = None,
) -> InsightsScope:
    """The companies side and disciplines an Insights read is narrowed to
    (`db/queries/insights.py`)."""
    return await resolve_insights_scope(session, side, family)


#: An Insights read's scope: `?side=all|yours|other&family=...`.
InsightsScopeDep = Annotated[InsightsScope, Depends(get_insights_scope)]
