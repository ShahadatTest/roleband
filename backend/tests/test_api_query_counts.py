"""Round trips per request for the job list, the scope catalog and the ops reads.

A refactor that adds a query to every request, or turns a batched per-row
lookup into one query per row, keeps every response byte-identical and every
contract test green. So the statement count is held here, over real HTTP
against the contract seed:

1. **A budget per request shape**. A budget is never raised to make a change pass; a lower count may lower it.
2. **Per-row lookups stay batched**: a page with many more rows costs exactly
   the statements the smaller page did.

The count is what the engine sends (`before_cursor_execute`) for the SECOND of
two identical requests, so pool warm-up never counts.

The ops reads (`/api/status`, `/api/schedule`, `/api/sync/targets`, in
`workflows/schedule_status.py`) are budgeted the same way, and the
roster-growth tests are their N+1 detector: every one of those reads walks a
roster, so a projection that loses its batching answers identically and
costs one statement per company. `/api/runs` is the control — it reads no roster,
so its count must not move when the roster grows.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event

from tests.factories import make_job
from tests.intelligence_contract_seed import (
    pin_integration_machine,
    seed_embed_measurement,
    seed_routing,
)
from tests.job_contract_seed import seed_job_contract
from tests.ops_contract_seed import (
    NOW,
    _binding,
    _company,
    _schedule,
    pin_ops_environment,
    seed_ops_contract,
)
from tracker.api.routers import intelligence as intelligence_router
from tracker.api.routers import jobs as jobs_router
from tracker.config import get_settings
from tracker.db.models import RoleCatalog, TrackedCompany

#: `no_escape` because the ops seed reaches the dispatcher spawn.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

#: Upper bounds.
#: The statements behind each, in order, so a changed count names what moved:
BUDGETS = {
    # hidden, count, page, favorites, dismissed, lineage, twins, then the
    # standing-posting sign's two reads: role starts, reopened
    "list_default": 9,
    # + intent setting row and the favorite/pursued/dismissed centroid reads
    "list_relevance_without_signal": 12,
    # hidden, count, ranked page, six page-context reads, advisory worlds
    "list_intent_ranked": 10,
    # hidden, title probe, match count, fused count, page, six context reads
    "search_exploratory": 11,
    # hidden, title probe, match count, fused count, the exact rows' fused ranks,
    # the exact rows, the related page, favorites, dismissed, twins, reopened
    # (no lineage or role-start read: neither seeded row belongs to one)
    "search_exact_title_with_related": 11,
    # hidden, identifier probe, the rows, six context reads
    "search_identifier": 9,
    # hidden, the four opt-in axes in ONE read, worlds,
    # tracked companies, location counts, catalog, ladders
    "scope_catalog_joint": 7,
    # + live track counts while the inventory is not joint-ready
    "scope_catalog_legacy": 8,
    # SELECT 1, newest full refreshed run, newest run, the stuck-run count, then
    # the scheduler projection (targets, stable bindings, schedule rows, provider
    # pressure), the derivation rows, and the flagged-binding report: ONE
    # statement joining health, company and the newest anomaly run,
    # then the reference block: ONE statement for the applied
    # set, the last change, pending jobs, running plugins and the install
    # count, which with nothing installed is also the whole provider set;
    # every supervised job's published state with its live run's progress
    # (ONE statement); whether a scan Sync asked for, or a re-embed of ours,
    # is queued or live (ONE statement for both); last, whether anyone holds
    # the re-embed lock (read, never taken)
    "status": 14,
    # targets, stable bindings, their schedule rows, provider pressure, then
    # the schedule plan: its recent runs, the awake samples, and the
    # repeat setting. The plan reuses the four rows above, so a roster's growth
    # still costs nothing.
    "schedule": 7,
    # targets, the binding-health join, the reference run's `per_source`, and
    # the flagged-binding report behind each row's `coverage`
    "sync_targets": 4,
    # the page. The control: no roster is walked here
    "runs": 1,
    # apple_fm, the lock probe (two), the corpus counts, the stale count, the
    # measurements, the tier choice, and the routing ladder's own six reads.
    "intelligence": 13,
    # the browse total, the persona, today's embedded count, the last embedded
    # stamp, the stored intent vector, the intent build's own read, and the
    # histogram.
    "fit": 7,
    # the stored intent vector, the intent build's own read, the band page, and
    # the rows' reader state: favorites, dismissed, twin and place counts (no
    # lineage read: no seeded row belongs to one)
    "fit_band": 6,
}

#: Every ops read that walks the roster, and the one that does not.
OPS = {
    "status": "/api/status",
    "schedule": "/api/schedule",
    "sync_targets": "/api/sync/targets",
    "runs": "/api/runs",
}

SEARCH = {
    "search_exploratory": "/api/jobs?sort=relevance&q=product%20manager",
    "search_exact_title_with_related": (
        "/api/jobs?sort=relevance&q=Platform%20Strategy%20Lead%2C%20Cloud&include_related=true"
    ),
    "search_identifier": "/api/jobs?sort=relevance&q=https%3A%2F%2Fcareers.example.test%2Fband",
}


@contextmanager
def _statements(engine) -> Iterator[list[str]]:
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def _measure(api_client, engine, path: str) -> tuple[int, dict]:
    warm = await api_client.get(path)
    assert warm.status_code == 200, warm.text
    with _statements(engine) as seen:
        response = await api_client.get(path)
    assert response.status_code == 200, response.text
    return len(seen), response.json()


@pytest_asyncio.fixture
async def seeded(db_session, monkeypatch):
    async def no_query_vector(_text):
        return None  # no model weights in tests: the lexical half ranks alone

    monkeypatch.setattr(jobs_router, "embed_query", no_query_vector)
    return await seed_job_contract(db_session)


async def test_the_default_list_stays_within_its_budget(api_client, db_session, seeded):
    count, body = await _measure(api_client, db_session.bind, "/api/jobs")
    assert body["items"], "the seed must put rows on the page, or nothing was measured"
    assert count <= BUDGETS["list_default"]


async def test_relevance_without_an_intent_signal_stays_within_its_budget(
    api_client, db_session, seeded
):
    count, body = await _measure(api_client, db_session.bind, "/api/jobs?sort=relevance")
    assert "ranked_by" not in body, "the seed has no embeddings, so this is the fallback"
    assert count <= BUDGETS["list_relevance_without_signal"]


async def test_the_intent_ranked_list_stays_within_its_budget(
    api_client, db_session, seeded, monkeypatch
):
    async def no_statement(_session):
        return None

    async def intent_vector(_session, _stored):
        return [0.01] * get_settings().embedding_dim

    monkeypatch.setattr(jobs_router, "get_intent_embedding", no_statement)
    monkeypatch.setattr(jobs_router, "build_intent_vector", intent_vector)

    count, body = await _measure(api_client, db_session.bind, "/api/jobs?sort=relevance")
    assert body["ranked_by"] == "intent" and body["items"]
    assert count <= BUDGETS["list_intent_ranked"]


@pytest.mark.parametrize("shape", sorted(SEARCH))
async def test_each_search_kind_stays_within_its_budget(api_client, db_session, seeded, shape):
    count, body = await _measure(api_client, db_session.bind, SEARCH[shape])
    assert body["items"], f"{shape} matched nothing, so nothing was measured"
    assert count <= BUDGETS[shape]


@pytest.mark.parametrize("path", ["/api/jobs", SEARCH["search_exploratory"]])
async def test_a_longer_page_costs_no_extra_statement(api_client, db_session, seeded, path):
    before, small = await _measure(api_client, db_session.bind, path)

    db_session.add_all(
        make_job(f"extra-{n}", dedupe_key=f"google:extra-{n}") for n in range(12)
    )
    await db_session.commit()
    after, large = await _measure(api_client, db_session.bind, path)

    assert len(large["items"]) >= len(small["items"]) + 12, "the page did not grow"
    assert after == before


async def _seed_catalog(session, slug: str, *, status: str) -> None:
    from datetime import UTC, datetime

    session.add(
        TrackedCompany(
            slug=slug, display=slug.title(), adapter="greenhouse", status="active",
            enabled=True, visible=True, source="catalog", role_catalog_status=status,
            # Seeded with catalog rows, so it was scanned: a never-scanned
            # company holds nothing back.
            role_catalog_scanned_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    session.add(
        RoleCatalog(
            role_group="software_engineering", company=slug, count=3,
            band_counts={"junior": 2, "staff": 1},
            band_track_counts={"junior": {"technical": 2}, "staff": {"technical": 1}},
            examples=["Junior Software Engineer", "Staff Software Engineer"],
        )
    )
    await session.commit()


@pytest.mark.parametrize(
    ("status", "shape", "joint"),
    [("ready", "scope_catalog_joint", True), ("partial", "scope_catalog_legacy", False)],
)
async def test_the_scope_catalog_stays_within_its_budget_as_companies_grow(
    api_client, db_session, status, shape, joint
):
    await _seed_catalog(db_session, "acme", status=status)
    count, body = await _measure(api_client, db_session.bind, "/api/scope/catalog")
    assert body["joint_counts_ready"] is joint
    assert count <= BUDGETS[shape]

    await _seed_catalog(db_session, "globex", status=status)
    grown, body = await _measure(api_client, db_session.bind, "/api/scope/catalog")
    assert [c["slug"] for c in body["companies"]] == ["acme", "globex"]
    assert grown == count


# --------------------------------------------------------------------------- #
# The ops reads
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def ops_seeded(db_session, monkeypatch, tmp_path):
    """The `mixed` roster with a live run: every branch these reads project.

    Freshness from the scheduler rather than the fallback, a queued binding, one
    queued behind a provider backoff, one behind a pause, a stuck `running` row
    and a policy-denied provider — so a projection that drops a branch is
    measured, not skipped.
    """
    pin_ops_environment(monkeypatch, tmp_path)
    return await seed_ops_contract(db_session, roster="mixed", live_run=True)


async def _grow_the_roster(session, slug: str) -> None:
    """One more scheduled connector, on a provider already in the pressure table."""
    session.add(_company(slug, slug.title(), "greenhouse"))
    await session.flush()
    binding = _binding(slug, "greenhouse")
    session.add(binding)
    await session.flush()
    session.add(
        _schedule(
            binding.id,
            "greenhouse",
            last_reconcile=NOW - timedelta(hours=3),
            next_reconcile=NOW + timedelta(hours=21),
            discovery=True,
        )
    )
    await session.commit()


@pytest.mark.parametrize("shape", sorted(OPS))
async def test_each_ops_read_stays_within_its_budget(api_client, db_session, ops_seeded, shape):
    count, body = await _measure(api_client, db_session.bind, OPS[shape])
    assert body, f"{shape} answered nothing, so nothing was measured"
    assert count <= BUDGETS[shape]


#: How many runs' `per_source` each ops read may fetch. A finished run's blob
#: holds every company's counts and errors: `/api/status` needs none, since it
#: counts the newest finished run's companies in SQL, the picker needs the
#: reference run's alone, and the run list each listed run's once.
RUN_BLOBS = {
    "status": lambda body: 0,
    "sync_targets": lambda body: 1,
    "runs": lambda body: len(body["items"]),
}

#: A result column carrying `per_source`, under any label SQLAlchemy gives it.
_PER_SOURCE = re.compile(r"(?:\w+_)?per_source(?:_\d+)?")


@contextmanager
def _per_source_rows(engine) -> Iterator[list[int]]:
    """`per_source` values returned while the block ran: each such column
    counts once per row, so a statement fetching the blob twice counts twice."""
    rows: list[int] = []

    def record(_conn, cursor, _statement, _parameters, _context, _executemany):
        columns = sum(1 for column in cursor.description or () if _PER_SOURCE.fullmatch(column[0]))
        rows.append(columns * max(cursor.rowcount, 0))

    event.listen(engine.sync_engine, "after_cursor_execute", record)
    try:
        yield rows
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", record)


@pytest.mark.parametrize("shape", sorted(RUN_BLOBS))
async def test_an_ops_read_fetches_only_the_run_summaries_it_answers_from(
    api_client, db_session, ops_seeded, shape
):
    with _per_source_rows(db_session.bind) as rows:
        response = await api_client.get(OPS[shape])
    assert response.status_code == 200, response.text
    body = response.json()
    assert sum(rows) == RUN_BLOBS[shape](body)


#: How many roster entries each read answers with. `/api/status` names a company
#: only when it is overdue, queued or excluded, so its roster size is the count
#: the scheduler projection reports rather than a slug in the body.
ROSTER_SIZE = {
    "status": lambda body: body["scheduler"]["required"],
    "schedule": lambda body: len(body["bindings"]),
    "sync_targets": lambda body: len(body["companies"]),
    "runs": lambda body: len(body["items"]),
}


@pytest.mark.parametrize("shape", sorted(OPS))
async def test_a_longer_roster_costs_an_ops_read_no_extra_statement(
    api_client, db_session, ops_seeded, shape
):
    before, small = await _measure(api_client, db_session.bind, OPS[shape])

    await _grow_the_roster(db_session, "stark")
    await _grow_the_roster(db_session, "wayne")
    after, large = await _measure(api_client, db_session.bind, OPS[shape])

    size = ROSTER_SIZE[shape]
    if shape == "runs":
        assert size(large) == size(small), "the control answered the roster after all"
        assert after == before == BUDGETS["runs"]
        return
    assert size(large) == size(small) + 2, f"{shape} did not see the longer roster"
    assert after == before


# --------------------------------------------------------------------------- #
# The intelligence state
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def intelligence_seeded(db_session, monkeypatch, tmp_path):
    """A routed ladder, a recorded rate, and a corpus with something in it.

    Non-empty on purpose: with no rows at all there is nothing to estimate, so
    the measurement row is not read and the request costs one statement less.
    Measuring the empty case would freeze a budget no real install runs at.
    """
    pin_integration_machine(monkeypatch, tmp_path)
    await seed_routing(db_session)
    await seed_embed_measurement(db_session)
    db_session.add(make_job("corpus-seed", dedupe_key="google:corpus-seed"))
    await db_session.commit()
    return db_session


async def test_the_intelligence_state_stays_within_its_budget(
    api_client, db_session, intelligence_seeded
):
    """The estimator is pure, so the measurement row is read once instead of
    once per tier option plus once for the work owed. The read is conditional
    on `rows > 0`: a fresh install with no corpus estimates nothing, so it
    must still read nothing.
    """
    count, body = await _measure(api_client, db_session.bind, "/api/intelligence")
    assert body["matching"]["tier"], "the machine pin must answer a tier, or nothing was measured"
    assert count <= BUDGETS["intelligence"]


async def test_a_larger_corpus_costs_the_intelligence_state_no_extra_statement(
    api_client, db_session, intelligence_seeded
):
    """Corpus progress is counted by aggregate, not per row."""
    before, small = await _measure(api_client, db_session.bind, "/api/intelligence")

    db_session.add_all(
        make_job(f"corpus-{n}", dedupe_key=f"google:corpus-{n}") for n in range(25)
    )
    await db_session.commit()
    after, large = await _measure(api_client, db_session.bind, "/api/intelligence")

    assert large["matching"]["corpus_total"] >= small["matching"]["corpus_total"] + 25
    assert after == before


def _fit_of(fit: float) -> list[float]:
    """A unit embedding whose cosine with an all-equal intent vector is `fit`."""
    dim = get_settings().embedding_dim
    along = [fit / dim**0.5] * dim
    across = (1 - fit**2) ** 0.5 / 2**0.5
    along[0] += across
    along[1] -= across
    return along


@pytest.mark.parametrize(
    ("shape", "path"),
    [("fit", "/api/intelligence/fit"), ("fit_band", "/api/intelligence/fit/band/good")],
)
async def test_each_fit_instrument_stays_within_its_budget(
    api_client, db_session, seeded, monkeypatch, shape, path
):
    """The histogram bins in SQL and the band preview pages in SQL; neither may
    become a per-row read when the board grows."""

    async def intent_vector(_session, _stored):
        return [0.01] * get_settings().embedding_dim

    monkeypatch.setattr(jobs_router, "build_intent_vector", intent_vector)
    monkeypatch.setattr(intelligence_router, "build_intent_vector", intent_vector)
    if shape == "fit_band":
        # Rows a fit of 0.55 from the intent puts in "good": the band's rows
        # read their reader state, and an empty band would measure none of it.
        db_session.add_all(
            make_job(f"good-{n}", dedupe_key=f"google:good-{n}", embedding=_fit_of(0.55)) for n in range(3)
        )
        await db_session.commit()

    count, body = await _measure(api_client, db_session.bind, path)
    assert body
    if shape == "fit_band":
        assert len(body["items"]) == 3, "the band holds the rows it was seeded with"
    assert count <= BUDGETS[shape]

    db_session.add_all(make_job(f"fit-{n}", dedupe_key=f"google:fit-{n}") for n in range(12))
    await db_session.commit()
    grown, _ = await _measure(api_client, db_session.bind, path)
    assert grown == count, "a longer board must not cost the instrument a statement"
