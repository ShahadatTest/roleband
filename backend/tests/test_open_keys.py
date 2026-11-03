"""The discovery frontier is read as keys, and the writer's rows without their vectors.

A discovery probe skips every posting it already holds open, so it needs the
open postings' keys and nothing else (`repo.load_open_keys`): one statement
across the run's companies, never whole rows, which carry the description and
the embedding. The keys must be the writer's own (`repo.load_company_jobs`): a
posting the stable binding knows by an alias is held under that alias, so a
frontier keyed otherwise would read the detail of a posting already held, or
skip a new one.

The writer's rows leave out the two columns the write path never assigns
(`embedding`, `search_vector`), with raiseload: a writer that reached for one
would fail here instead of loading it lazily under the async session.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import InvalidRequestError

from tracker.config import get_settings
from tracker.db.models import Job, JobSourceIdentity, SourceBinding, TrackedCompany
from tracker.db.repo import load_company_jobs, load_open_keys

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

NOW = datetime(2026, 10, 1, tzinfo=UTC)
_HEAVY_LABEL = re.compile(
    r"(?:\w+_)?(description_html|description_sections|description_text|embedding|search_vector)"
    r"(?:_\d+)?"
)


@contextmanager
def _statements(engine) -> Iterator[list[set[str]]]:
    """Each statement's returned `HEAVY`-named columns, one set per statement."""
    seen: list[set[str]] = []

    def record(_conn, cursor, _statement, _parameters, _context, _executemany):
        seen.append({
            match.group(1)
            for column in cursor.description or ()
            if (match := _HEAVY_LABEL.fullmatch(column[0]))
        })

    event.listen(engine.sync_engine, "after_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", record)


def _job(company: str, req_id: str, *, status: str = "open", **over) -> Job:
    return Job(
        company=company, req_id=req_id, dedupe_key=f"{company}:{req_id}",
        title="Staff Engineer", url=f"https://boards.example.test/{company}/{req_id}",
        status=status, locations=["London, UK"], level_band="staff", family="software_engineering",
        first_seen=NOW, last_seen=NOW, total_days_open=0, repost_count=0, **over,
    )


async def _binding(db, company: str, *, status: str) -> SourceBinding:
    binding = SourceBinding(
        company_slug=company, connector_kind="adapter", connector_id="greenhouse",
        status=status, closure_capability="authoritative" if status == "stable" else "none",
    )
    db.add(binding)
    await db.flush()
    return binding


async def _alias(db, binding: SourceBinding, job: Job, source_key: str) -> None:
    db.add(JobSourceIdentity(
        binding_id=binding.id, job_id=job.id, source_key=source_key, first_seen=NOW, last_seen=NOW,
    ))
    await db.flush()


async def _seed(db) -> None:
    for slug in ("acme", "globex", "initech"):
        db.add(TrackedCompany(
            slug=slug, display=slug.title(), adapter="greenhouse", board_token=slug,
            status="active", enabled=True, visible=True, source="catalog",
        ))
    await db.flush()
    stable = await _binding(db, "acme", status="stable")
    retired = await _binding(db, "acme", status="retired")
    jobs = {
        "plain": _job("acme", "plain"),
        "closed": _job("acme", "closed", status="closed"),
        # Rebound: the stable binding knows it by another key.
        "rebound": _job("acme", "rebound"),
        # Known by an alias only through a retired binding: held under its own key.
        "retired": _job("acme", "retired"),
        # Open under its own key, which the stable binding gave to a closed posting.
        "taken": _job("acme", "taken"),
        "shadowed": _job("acme", "shadowed", status="closed"),
        "globex": _job("globex", "one"),
        "initech": _job("initech", "one"),
    }
    db.add_all(jobs.values())
    await db.flush()
    await _alias(db, stable, jobs["plain"], "acme:plain")
    await _alias(db, stable, jobs["rebound"], "acme:rebound-new")
    await _alias(db, retired, jobs["retired"], "acme:retired-old")
    await _alias(db, stable, jobs["shadowed"], "acme:taken")
    await db.commit()


async def _writers_open_keys(db, company: str) -> frozenset[str]:
    return frozenset(
        key for key, job in (await load_company_jobs(db, company)).items() if job.status == "open"
    )


async def test_the_frontier_is_the_open_keys_the_writer_holds(db_session):
    await _seed(db_session)

    frontier = await load_open_keys(db_session, ["acme", "globex"])

    assert frontier == {
        "acme": frozenset({"acme:plain", "acme:rebound-new", "acme:retired"}),
        "globex": frozenset({"globex:one"}),
    }
    for company in ("acme", "globex"):
        assert frontier[company] == await _writers_open_keys(db_session, company)


async def test_the_frontier_is_one_statement_that_fetches_no_row_body(db_session):
    await _seed(db_session)

    with _statements(db_session.bind) as seen:
        await load_open_keys(db_session, ["acme", "globex", "initech"])

    assert seen == [set()]
    assert await load_open_keys(db_session, []) == {}


async def test_the_writers_rows_leave_the_vectors_unloaded_and_keep_the_description(db_session):
    await _seed(db_session)
    await db_session.execute(
        text(
            "UPDATE jobs SET embedding = cast(:vector AS vector), "
            "search_vector = to_tsvector('english', title), description_text = 'Build it.' "
            "WHERE dedupe_key = 'acme:plain'"
        ),
        {"vector": str([0.01] * get_settings().embedding_dim)},
    )
    await db_session.commit()
    db_session.expunge_all()

    with _statements(db_session.bind) as seen:
        existing = await load_company_jobs(db_session, "acme")

    fetched = set().union(*seen)
    assert {"description_html", "description_sections", "description_text"} <= fetched
    assert fetched.isdisjoint({"embedding", "search_vector"})
    row = existing["acme:plain"]
    assert row.description_text == "Build it."
    for column in ("embedding", "search_vector"):
        with pytest.raises(InvalidRequestError):
            getattr(row, column)
