"""How a role arrived decides whether our sighting dates it (`db/arrival.py`).

Each case stores reads the way a scan does: the kept postings through the
writer (`persist_rows`), then the inventory, then the source-run row, which a
read writes last. The Board's New view, the header count and Overview read
the stored answer, so each case asks them, not the column alone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from tests.factories import make_company, make_enriched, make_job
from tracker.db import repo
from tracker.db.inventory_store import write_inventory
from tracker.db.models import (
    Job,
    PostingInventory,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
)
from tracker.db.queries.jobs import board_count_stmt
from tracker.db.repo import admit_from_inventory, load_company_jobs
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import inventory_row
from tracker.settings_store import set_retention_days
from tracker.workflows import arrival_backfill
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.run_persistence import persist_rows

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC).replace(microsecond=0)
COMPANY = "acme"


class Board:
    """acme's board as a scan reads it, and what the writer stored."""

    def __init__(self, session, monkeypatch) -> None:
        self.session = session
        self.monkeypatch = monkeypatch
        self.binding_id: int | None = None

    async def follow(self) -> None:
        self.session.add(make_company(COMPANY, "Acme"))
        await self.session.flush()
        binding = SourceBinding(company_slug=COMPANY, connector_kind="greenhouse", connector_id=COMPANY)
        self.session.add(binding)
        await self.session.flush()
        self.binding_id = binding.id

    def _posting(self, req_id: str, posted: datetime | None):
        enriched = make_enriched(company=COMPANY, req_id=req_id, title=f"Staff Software Engineer {req_id}")
        enriched.raw.posted_at = posted
        return enriched

    async def read(
        self,
        at: datetime,
        kept: tuple[str, ...] = (),
        *,
        held: tuple[str, ...] = (),
        outcome: str = "ok",
        complete: bool = True,
        inventory: bool = True,
        posted: dict[str, datetime] | None = None,
    ) -> dict[str, Job]:
        """One read finishing a minute after `at`. `kept` postings are stored
        as roles at `at`; `held` ones only reach the inventory (out of scope)."""
        posted = posted or {}
        run = ScrapeRun(status="ok", started_at=at, per_source={}, drift_alerts=[])
        self.session.add(run)
        await self.session.flush()
        self.monkeypatch.setattr(repo, "_now", lambda: at)
        kept_rows = [self._posting(key, posted.get(key)) for key in kept]
        await persist_rows(
            self.session, run, kept_rows, await load_company_jobs(self.session, COMPANY),
            scan_mode=ScanMode.RECONCILE, touched_ids=[], binding_id=self.binding_id,
        )
        if inventory:
            read = [*kept_rows, *(self._posting(key, posted.get(key)) for key in held)]
            rows = {e.raw.dedupe_key(): inventory_row(e.raw, annotate(e.raw)) for e in read}
            await write_inventory(
                self.session, run_id=run.id, company=COMPANY, binding_id=self.binding_id, rows=rows,
                seen_keys=set(rows), authoritative=complete, now=at + timedelta(seconds=30), touch_hours=12,
            )
        self.session.add(ScrapeSourceRun(
            run_id=run.id, binding_id=self.binding_id, company_slug=COMPANY, provider_key=COMPANY,
            scan_mode="reconcile", outcome=outcome, started_at=at, finished_at=at + timedelta(minutes=1),
            kept=len(kept), list_complete=complete,
        ))
        await self.session.commit()
        return await self.roles()

    async def admit(self, *keys: str, at: datetime) -> dict[str, Job]:
        """A scope change brings held postings onto the Board at `at`."""
        self.monkeypatch.setattr(repo, "_now", lambda: at)
        rows = (await self.session.scalars(select(PostingInventory).where(
            PostingInventory.req_id.in_(keys), PostingInventory.company == COMPANY,
        ))).all()
        await admit_from_inventory(self.session, rows)
        await self.session.commit()
        return await self.roles()

    async def roles(self) -> dict[str, Job]:
        self.session.expire_all()
        jobs = (await self.session.scalars(select(Job).where(Job.company == COMPANY))).all()
        return {job.req_id: job for job in jobs}


@pytest_asyncio.fixture
async def board(db_session, monkeypatch) -> Board:
    state = Board(db_session, monkeypatch)
    await state.follow()
    return state


async def _new(api_client) -> set[str]:
    """The roles the Board calls new, asked three ways that must agree: the
    header's count, the New view, and the rows lit on the whole open Board."""
    stats = (await api_client.get("/api/stats")).json()
    lens = (await api_client.get("/api/jobs", params={"limit": 200, "new_today_only": "true"})).json()
    every = (await api_client.get("/api/jobs", params={"limit": 200, "status": "open"})).json()
    lit = {row["req_id"] for row in every["items"] if row["new_listing"]}
    listed = {row["req_id"] for row in lens["items"]}
    assert stats["new_today"] == lens["total"] == len(lit), (stats["new_today"], listed, lit)
    assert listed == lit
    return lit


def _arrivals(roles: dict[str, Job]) -> dict[str, str | None]:
    return {key: job.arrival for key, job in sorted(roles.items())}


# --------------------------------------------------------------------------- #
# A company's first read
# --------------------------------------------------------------------------- #


async def test_a_first_read_is_new_on_the_employers_date_alone(api_client, board):
    """At a company followed today, a posting the employer dated yesterday is
    new and one dated last month is not; an undated find never is."""
    roles = await board.read(NOW - timedelta(hours=1), ("yesterday", "last-month", "undated"), posted={
        "yesterday": NOW - timedelta(days=1), "last-month": NOW - timedelta(days=30),
    })
    assert set(_arrivals(roles).values()) == {"first_read"}
    assert await _new(api_client) == {"yesterday"}
    overview = (await api_client.get("/api/statistics/overview?days=30")).json()["kpis"]
    assert (overview["new_count"], overview["first_scan_count"]) == (0, 3)


async def test_a_read_after_a_complete_one_dates_what_it_finds(api_client, board):
    await board.read(NOW - timedelta(days=2), ("listed",))
    roles = await board.read(NOW - timedelta(hours=1), ("listed", "fresh"))
    assert _arrivals(roles) == {"fresh": "new", "listed": "first_read"}
    assert roles["fresh"].first_seen == NOW - timedelta(hours=1)
    assert await _new(api_client) == {"fresh"}
    overview = (await api_client.get("/api/statistics/overview?days=30")).json()["kpis"]
    velocity = (await api_client.get("/api/statistics/velocity?days=30")).json()["kpis"]
    assert (overview["new_count"], overview["first_scan_count"]) == (1, 1)
    assert (velocity["opened"], velocity["first_scan"]) == (1, 1)


async def test_without_an_inventory_the_sighting_is_the_roles_creation(api_client, board):
    await board.read(NOW - timedelta(days=2), ("listed",), inventory=False)
    roles = await board.read(NOW - timedelta(hours=1), ("listed", "fresh"), inventory=False)
    assert _arrivals(roles) == {"fresh": "new", "listed": "first_read"}
    assert roles["fresh"].first_seen == NOW - timedelta(hours=1)
    assert await _new(api_client) == {"fresh"}


async def test_a_capped_read_before_the_first_full_one_proves_nothing(api_client, board):
    """An operator's cap kept part of the board: what the first full read
    finds beyond it was listed all along."""
    await board.read(NOW - timedelta(hours=5), ("a",), outcome="capped", complete=False)
    roles = await board.read(NOW - timedelta(hours=3), ("a", "b", "c"))
    assert _arrivals(roles) == {"a": "first_read", "b": "first_read", "c": "first_read"}
    roles = await board.read(NOW - timedelta(hours=1), ("a", "b", "c", "d"))
    assert roles["d"].arrival == "new"
    assert await _new(api_client) == {"d"}


async def test_an_empty_board_is_a_complete_read(api_client, board):
    """A board that proved it lists nothing was read in full: its first role
    is an opening, not a first read."""
    await board.read(NOW - timedelta(days=1), (), outcome="empty", complete=False)
    roles = await board.read(NOW - timedelta(hours=1), ("first",))
    assert roles["first"].arrival == "new"
    assert await _new(api_client) == {"first"}


@pytest.mark.parametrize(("outcome", "third"), [
    ("truncated", "new"),
    ("bounded", "new"),
    ("suspended", "first_read"),
    ("degraded", "first_read"),
])
async def test_a_source_that_never_completes_is_known_after_two_reads_cut_at_our_ceiling(
    api_client, board, outcome, third,
):
    """A board our page or time ceiling always cuts never reads complete, so
    two such reads that kept postings make it known. A sleeping host or a
    broken source says nothing about what the board held."""
    await board.read(NOW - timedelta(hours=5), ("a",), outcome=outcome, complete=False)
    roles = await board.read(NOW - timedelta(hours=3), ("a", "b"), outcome=outcome, complete=False)
    assert roles["b"].arrival == "first_read"
    roles = await board.read(NOW - timedelta(hours=1), ("a", "b", "c"), outcome=outcome, complete=False)
    assert roles["c"].arrival == third
    assert await _new(api_client) == ({"c"} if third == "new" else set())


# --------------------------------------------------------------------------- #
# The inventory's earlier sighting
# --------------------------------------------------------------------------- #


async def test_a_posting_held_out_of_scope_ages_from_the_inventorys_sighting(api_client, board):
    """A role that came into scope today counts when it appeared yesterday and
    not when the inventory saw it 19 days ago."""
    await board.read(NOW - timedelta(days=30), ("a",))
    await board.read(NOW - timedelta(days=19), ("a",), held=("old",))
    await board.read(NOW - timedelta(hours=20), ("a",), held=("old", "recent"))
    roles = await board.admit("old", "recent", at=NOW)
    assert _arrivals(roles) == {"a": "first_read", "old": "already_listed", "recent": "already_listed"}
    assert roles["old"].first_seen == NOW - timedelta(days=19, seconds=-30)
    assert roles["recent"].first_seen == NOW - timedelta(hours=20, seconds=-30)
    assert await _new(api_client) == {"recent"}
    # Pace and Overview count each at its first sighting, not at the admit.
    overview = (await api_client.get("/api/statistics/overview?days=7")).json()["kpis"]
    assert (overview["new_count"], overview["first_scan_count"]) == (1, 0)


async def test_a_catch_up_of_postings_a_first_read_listed_is_a_first_read(api_client, board):
    """The inventory saw these postings during the company's first read and
    a later read stored them: the first read's sighting still dates nothing."""
    await board.read(NOW - timedelta(days=10), ("a",), held=("b",))
    roles = await board.read(NOW - timedelta(hours=1), ("a", "b"))
    assert roles["b"].arrival == "first_read"
    assert roles["b"].first_seen == NOW - timedelta(days=10, seconds=-30)
    assert await _new(api_client) == set()


async def test_a_role_already_on_the_board_moves_back_to_its_first_sighting(board):
    """A posting the inventory read before it was stored keeps the earlier
    sighting as its `first_seen`, and says it was already listed."""
    await board.read(NOW - timedelta(days=9), ("a",))
    await board.read(NOW - timedelta(days=5), ("a",), held=("b",))
    roles = await board.read(NOW - timedelta(hours=2), ("a", "b"))
    assert roles["b"].arrival == "already_listed"
    assert roles["b"].first_seen == NOW - timedelta(days=5, seconds=-30)


# --------------------------------------------------------------------------- #
# Following a company again
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("retention", "gap_days", "arrival"), [
    (30, 20, "new"),
    (30, 45, "first_read"),
    (None, 45, "new"),
])
async def test_a_company_followed_again_after_its_window_starts_over(
    api_client, db_session, board, retention, gap_days, arrival,
):
    """Retention removes a company's inventory rows once no read has touched
    them for the window, so a read back after it is a first read; inside it,
    a posting that appeared meanwhile is an opening."""
    await set_retention_days(db_session, retention)
    await board.read(NOW - timedelta(days=gap_days), ("a",))
    roles = await board.read(NOW - timedelta(hours=1), ("a", "b"))
    assert roles["b"].arrival == arrival
    assert await _new(api_client) == ({"b"} if arrival == "new" else set())


# --------------------------------------------------------------------------- #
# Parity: where the old rule was right, the stored answer is the same
# --------------------------------------------------------------------------- #


async def _first_scan_finds_by_the_old_rule(session) -> set[int]:
    """The reference: the postings whose `opened` event belongs to their
    company's first collecting run."""
    rows = await session.execute(text(
        "WITH first AS (SELECT j.company, min(e.run_id) AS run_id FROM jobs j "
        "JOIN job_lifecycle_events e ON e.job_id = j.id WHERE e.event_type = 'opened' GROUP BY j.company) "
        "SELECT e.job_id FROM job_lifecycle_events e JOIN jobs j ON j.id = e.job_id "
        "JOIN first f ON f.company = j.company AND f.run_id = e.run_id WHERE e.event_type = 'opened'"
    ))
    return set(rows.scalars().all())


async def test_where_the_old_rule_was_right_the_stored_answer_agrees(db_session, board):
    await board.read(NOW - timedelta(days=6), ("a", "b"))
    await board.read(NOW - timedelta(days=3), ("a", "b", "c"))
    roles = await board.read(NOW - timedelta(hours=1), ("a", "b", "c", "d"))
    old = await _first_scan_finds_by_the_old_rule(db_session)
    assert {job.id for job in roles.values() if job.arrival == "first_read"} == old
    assert {job.req_id for job in roles.values() if job.id in old} == {"a", "b"}


# --------------------------------------------------------------------------- #
# The writer leaves nothing unclassified, and the backfill classifies the rest
# --------------------------------------------------------------------------- #


async def test_no_role_a_writer_stores_is_left_unclassified(db_session, board):
    await board.read(NOW - timedelta(days=3), ("a",), held=("h",))
    await board.read(NOW - timedelta(hours=1), ("a", "b"))
    await board.admit("h", at=NOW)
    assert await db_session.scalar(select(func.count()).select_from(Job).where(Job.arrival.is_(None))) == 0


async def _stored_before_arrival_existed(session, board) -> dict[str, int]:
    """Two reads of acme as the old writer left them: no `arrival`, and
    `first_seen` the creation even where the inventory saw a posting first."""
    await board.read(NOW - timedelta(days=6), ("a",), held=("b",))
    await board.read(NOW - timedelta(days=2), ("a", "b", "c"))
    await session.execute(text(
        "UPDATE jobs SET arrival = NULL, first_seen = e.created_at FROM job_lifecycle_events e "
        "WHERE e.job_id = jobs.id AND e.event_type = 'opened'"
    ))
    await session.commit()
    return {key: job.id for key, job in (await board.roles()).items()}


async def test_the_backfill_classifies_stored_roles_as_the_writer_would(db_session, board, scratch_scope):
    ids = await _stored_before_arrival_existed(db_session, board)
    assert await arrival_backfill.backfill_arrivals(batch=2) == 3
    roles = await board.roles()
    assert _arrivals(roles) == {"a": "first_read", "b": "first_read", "c": "new"}
    # `b` was in the first read's inventory: it starts there now.
    assert roles["b"].first_seen == NOW - timedelta(days=6, seconds=-30)
    assert roles["c"].first_seen == NOW - timedelta(days=2)
    assert {key: job.id for key, job in roles.items()} == ids
    assert await arrival_backfill.backfill_arrivals() == 0


async def test_a_backfill_that_dies_keeps_its_saved_batches_and_resumes(
    db_session, board, scratch_scope, monkeypatch,
):
    await _stored_before_arrival_existed(db_session, board)
    real = arrival_backfill.classify_arrivals
    calls = []

    async def dies_on_the_second_batch(session, chunk):
        calls.append(list(chunk))
        if len(calls) == 2:
            raise RuntimeError("killed")
        return await real(session, chunk)

    monkeypatch.setattr(arrival_backfill, "classify_arrivals", dies_on_the_second_batch)
    with pytest.raises(RuntimeError, match="killed"):
        await arrival_backfill.backfill_arrivals(batch=1)
    db_session.expire_all()
    unclassified = await db_session.scalar(select(func.count()).select_from(Job).where(Job.arrival.is_(None)))
    assert unclassified == 2

    monkeypatch.setattr(arrival_backfill, "classify_arrivals", real)
    assert await arrival_backfill.backfill_arrivals(batch=1) == 2
    assert _arrivals(await board.roles()) == {"a": "first_read", "b": "first_read", "c": "new"}


# --------------------------------------------------------------------------- #
# The New count's cost does not grow with history
# --------------------------------------------------------------------------- #


async def _buffers_to_count_new(session) -> int:
    stmt = board_count_stmt({"status": "open", "hidden": [], "new_today_only": True})
    sql = str(stmt.compile(dialect=session.bind.dialect, compile_kwargs={"literal_binds": True}))
    plan = (await session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"))).scalar_one()
    root = (json.loads(plan) if isinstance(plan, str) else plan)[0]["Plan"]
    return root["Shared Hit Blocks"] + root["Shared Read Blocks"]


async def test_the_new_count_reads_about_as_much_over_ten_times_the_history(db_session):
    db_session.add(make_company("google", "Google"))
    await db_session.flush()

    async def history(n: int, start: int) -> None:
        db_session.add_all(
            make_job(f"old-{i}", first_seen=NOW - timedelta(days=40 + i % 300), arrival="new")
            for i in range(start, start + n)
        )
        await db_session.commit()
        await db_session.execute(text("ANALYZE jobs"))

    db_session.add(make_job("today", first_seen=NOW - timedelta(hours=1), arrival="new"))
    await history(2_000, 0)
    small = await _buffers_to_count_new(db_session)
    await history(18_000, 2_000)
    large = await _buffers_to_count_new(db_session)
    assert await db_session.scalar(board_count_stmt({"status": "open", "hidden": [], "new_today_only": True})) == 1
    assert large / small < 1.5, (small, large)
