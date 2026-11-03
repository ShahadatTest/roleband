"""The tuning pass: which runs teach, and what they write.

`test_tuning.py` covers the policy. This covers the half that decides *whether
the policy ever sees a run* — which is where a tuner does its real damage. A
bound learned from a run that was cut short is not a smaller bound, it is a
bound that will truncate the next healthy run, and then keep learning from the
truncation.
"""

from __future__ import annotations

import pytest

from tracker.config import Settings
from tracker.db.models import SourceBindingTuning
from tracker.platform.paging import StopReason
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows.tuning_pass import (
    SOURCE_LEVEL_KEY,
    budget_cut,
    is_teachable,
    learn_bounds,
    load_page_budgets,
)


def query(key: str = "united_states", pages: int = 40, reason: str = "exhausted") -> dict:
    return {
        "query_key": key,
        "pages_used": pages,
        "items": pages * 20,
        "stop_reason": reason,
        "ceiling": 100,
        "declared_total": None,
        "page_size": 20,
    }


def stats(**overrides) -> dict:
    base = {
        "scanned": 800,
        "errors": [],
        "capped": False,
        "bounded": False,
        "blocked": False,
        "truncated": False,
        "duration_seconds": 480.0,
        "queries": [query()],
    }
    base.update(overrides)
    return base


# -- which runs are allowed to teach ----------------------------------------- #


@pytest.mark.parametrize(
    "case,source_stats,expected",
    [
        ("a clean, complete run", stats(), True),
        (
            "truncated: THE case to learn from — the bound fired",
            stats(truncated=True, queries=[query(reason="ceiling")]),
            True,
        ),
        (
            "errored mid-listing: fewer pages for reasons unrelated to board size",
            stats(errors=["HTTPError: 500"]),
            False,
        ),
        ("blocked by a WAF: no evidence about the board at all", stats(blocked=True), False),
        ("operator cap: the page count measures --max-list", stats(capped=True), False),
        (
            "bounded: OUR time ceiling cut it, so the pages are censored by us",
            stats(bounded=True),
            False,
        ),
    ],
)
def test_teachability(case, source_stats, expected):
    assert is_teachable(source_stats) is expected, case


def test_a_truncated_run_teaches_but_a_bounded_one_does_not():
    """These two look alike — both incomplete, both health-inert — and they must
    not be treated alike. `truncated` is our PAGE bound firing, which is exactly
    the evidence the tuner needs; `bounded` is our TIME bound cutting a source
    mid-listing, which tells us nothing about how many pages the board has."""
    assert is_teachable(stats(truncated=True)) is True
    assert is_teachable(stats(bounded=True)) is False


@pytest.mark.parametrize(
    "source_stats,expected",
    [
        (stats(bounded=True), True),
        (stats(bounded=True, errors=["HTTPError: 503"]), False),
        (stats(bounded=True, suspended=True), False),
        (stats(bounded=True, blocked=True), False),
        (stats(), False),
    ],
)
def test_only_a_read_our_budget_alone_cut_is_evidence_the_budget_was_too_low(source_stats, expected):
    assert budget_cut(source_stats) is expected


# -- what the pass writes ----------------------------------------------------- #


class _Binding:
    def __init__(self, id: int, slug: str) -> None:
        self.id = id
        self.company_slug = slug
        self.status = "stable"


class _Result:
    def __init__(self, rows) -> None:
        self._rows = list(rows)

    def scalars(self):
        return self._rows

    def all(self):
        return self._rows


class _Session:
    """Boundary stub. Answers the pass's two SELECTs in order and collects
    `add()`; the subject under test is the fold, not SQLAlchemy."""

    def __init__(self, bindings, tuning_rows=()) -> None:
        self._results = [_Result(bindings), _Result(tuning_rows)]
        self.added = []

    async def execute(self, _stmt):
        return self._results.pop(0) if self._results else _Result([])

    def add(self, obj):
        self.added.append(obj)


class _RaisingSession:
    async def execute(self, _stmt):  # pragma: no cover - must never be reached
        raise AssertionError("an unteachable run must not touch the database")

    def add(self, obj):  # pragma: no cover
        raise AssertionError("an unteachable run must not write")


@pytest.mark.asyncio
async def test_a_capped_run_never_reaches_the_database():
    """Belt and braces with the pass's own `capped_ok=False` registration: if
    the pass were ever re-registered as capped-safe, this still refuses."""
    result = await learn_bounds(
        _RaisingSession(), {"google": stats(capped=True)}, Settings()
    )
    assert result == {"bindings": 0, "queries": 0, "skipped": 1, "budgets_raised": 0}


@pytest.mark.asyncio
async def test_a_first_run_creates_a_row_per_query_plus_the_source_level_row():
    session = _Session([_Binding(7, "google")])

    result = await learn_bounds(
        session,
        {"google": stats(queries=[query("united_states", 40), query("London, UK", 6)])},
        Settings(),
    )

    assert result["bindings"] == 1 and result["queries"] == 2
    by_key = {row.query_key: row for row in session.added}
    assert set(by_key) == {"united_states", "London, UK", SOURCE_LEVEL_KEY}

    # Each query's own evidence, kept separately — the input divergence will
    # become bound divergence over runs (below).
    assert by_key["united_states"].page_samples == [40]
    assert by_key["London, UK"].page_samples == [6]

    # The duration sample lands only on the source-level row: duration is a
    # property of the source, and recording it per query would turn one run's
    # 480s into a 480s budget for each of them.
    assert by_key[SOURCE_LEVEL_KEY].duration_samples == [480.0]
    assert by_key["united_states"].duration_samples == []

    # ...and one sample is not yet a budget: until there is a spread to measure
    # the operator's global ceiling stands.
    assert by_key[SOURCE_LEVEL_KEY].tuned_budget_seconds is None

    # Neither bound jumps on first sight: with no history the seed ceiling is
    # all there is, so the first run takes one decay step, not a leap to target.
    assert by_key["united_states"].tuned_max_pages == 90
    assert by_key["London, UK"].tuned_max_pages == 90


@pytest.mark.asyncio
async def test_per_query_bounds_diverge_over_runs_to_fit_each_query():
    """The reason the table is keyed per query and not per source.

    One source, two queries an order of magnitude apart. Run the real pass
    repeatedly against stable boards and the bounds must separate — a single
    per-source number would have to be either wasteful for London or truncating
    for the US.
    """
    binding = _Binding(7, "google")
    rows: list = []
    for _ in range(40):
        session = _Session([binding], list(rows))
        await learn_bounds(
            session,
            {"google": stats(queries=[query("united_states", 40), query("London, UK", 6)])},
            Settings(),
        )
        rows.extend(session.added)

    by_key = {row.query_key: row for row in rows}
    us = by_key["united_states"].tuned_max_pages
    london = by_key["London, UK"].tuned_max_pages

    assert us > london, "the two queries settled on different bounds"
    assert us >= 40, "and each still fits the board it was learned from"
    assert london >= 6
    # Each settled exactly on its own target: pages * 1.5 headroom.
    assert us == 60  # ceil(40 * 1.5)
    assert london == 9  # ceil(6 * 1.5), still above the floor of 8


@pytest.mark.asyncio
async def test_a_second_run_folds_into_the_existing_row_rather_than_adding_one():
    binding = _Binding(7, "google")
    first = _Session([binding])
    await learn_bounds(first, {"google": stats(queries=[query("united_states", 40)])}, Settings())
    existing = [row for row in first.added if row.query_key == "united_states"][0]
    source_row = [row for row in first.added if row.query_key == SOURCE_LEVEL_KEY][0]

    second = _Session([binding], [existing, source_row])
    await learn_bounds(
        second, {"google": stats(queries=[query("united_states", 44)])}, Settings()
    )

    assert second.added == [], "no duplicate row for a query already tracked"
    assert existing.page_samples == [40, 44], "evidence accumulates"
    assert existing.tuned_max_pages >= 44


@pytest.mark.asyncio
async def test_a_company_without_a_stable_binding_is_skipped_not_crashed():
    """A company added during this run has observations but nothing to key them
    to. It must be ignored quietly; the next run seeds it."""
    session = _Session([])  # no bindings returned
    result = await learn_bounds(session, {"mistral": stats()}, Settings())

    assert result["bindings"] == 0
    assert session.added == []


# -- reading the bounds back -------------------------------------------------- #


class _RowSession:
    def __init__(self, rows) -> None:
        self._rows = rows

    async def execute(self, _stmt):
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_page_budgets_exclude_the_source_level_row():
    """`*` is not a query. Handing it to an adapter as a page budget would give
    every unnamed query a ceiling derived from the widest one."""
    budgets = await load_page_budgets(
        _RowSession(
            [
                ("google", "united_states", 90),
                ("google", "London, UK", 12),
                ("google", SOURCE_LEVEL_KEY, 90),
            ]
        ),
        ["google"],
    )

    assert budgets == {"google": {"united_states": 90, "London, UK": 12}}


@pytest.mark.asyncio
async def test_no_companies_means_no_query_at_all():
    assert await load_page_budgets(_RaisingSession(), []) == {}


# -- the adapter side of the same contract ------------------------------------ #


def test_an_adapter_falls_back_to_its_seed_when_nothing_is_learned():
    """Tuning is additive: a company with no history behaves exactly as an
    untuned one."""
    from tracker.connectors.listing.google import GoogleAdapter

    adapter = GoogleAdapter("google")
    # Walled: a consenting user, so the paging record is what is tested.
    adapter.collection_consent = SOURCE_REVIEWS["google"].wall_fingerprint
    assert adapter.page_budget("United States", seed=400) == 400


def test_a_learned_bound_replaces_the_seed_but_still_clamps():
    from tracker.connectors.listing.google import GoogleAdapter

    adapter = GoogleAdapter("google", page_budgets={"United States": 90, "London, UK": 99_999})

    assert adapter.page_budget("United States", seed=400) == 90
    # A row hand-edited in the DB cannot push an adapter past the published max.
    assert adapter.page_budget("London, UK", seed=400) == 1000
    assert adapter.page_budget("Singapore", seed=400) == 400


@pytest.mark.asyncio
async def test_paging_records_what_it_did_for_the_next_tuning_pass():
    """The observation is the input to everything above; without it the pass has
    nothing to learn from, and no other test here would notice."""
    import httpx

    from tracker.connectors.listing.base import RateLimiter
    from tracker.connectors.listing.google import GoogleAdapter

    card = (
        '<li><a aria-label="Learn more about Engineer {i}" '
        'href="jobs/results/{i}-role">Engineer {i}</a></li>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # Two pages of 20 against a declared 40: page 1 is "1 to 20 of 40" so
        # the pager continues, page 2 ends exactly at the total and stops
        # naturally. A fixture declaring the full total on page 1 would stop
        # after one request and silently test nothing.
        page = int(request.url.params.get("page"))
        if page > 2:
            return httpx.Response(200, text="<html><body></body></html>")
        body = "".join(card.format(i=page * 20 + n) for n in range(20))
        through = page * 20
        return httpx.Response(
            200,
            text=(
                "<html><body><main><ul>" + body + "</ul>"
                f'<span aria-live="polite">Showing 1 to {through} of 40 rows</span>'
                "</main></body></html>"
            ),
        )

    adapter = GoogleAdapter("google")
    # Walled: a consenting user, so the paging record is what is tested.
    adapter.collection_consent = SOURCE_REVIEWS["google"].wall_fingerprint
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)

    [job async for job in adapter._fetch_location("United States", set())]

    assert len(adapter.query_observations) == 1
    observed = adapter.query_observations[0]
    assert observed.query_key == "United States", "keyed by the query, not the adapter"
    assert observed.stop_reason is StopReason.STOPPED, "reached the declared total"
    assert observed.declared_total == 40
    assert observed.page_size == 20
    assert observed.ceiling == 400
    assert observed.pages_used == 2


@pytest.mark.asyncio
async def test_source_costs_are_the_median_learned_time_and_the_postings_held(db_session):
    """What orders a run's lanes: a company's typical scan time and
    what it holds for the user now. A company never timed is absent."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from tracker.company_store import ensure_builtins, ensure_source_bindings
    from tracker.db.models import Job, SourceBinding, SourceBindingTuning
    from tracker.workflows.tuning_pass import SOURCE_LEVEL_KEY, load_source_costs

    await ensure_builtins(db_session)
    await ensure_source_bindings(db_session)
    bindings = {
        row.company_slug: row
        for row in (await db_session.scalars(select(SourceBinding).where(SourceBinding.status == "stable"))).all()
    }
    db_session.add_all([
        SourceBindingTuning(binding_id=bindings["amazon"].id, query_key=SOURCE_LEVEL_KEY,
                            duration_samples=[500.0, 520.0, 9000.0]),
        SourceBindingTuning(binding_id=bindings["amazon"].id, query_key="united_states",
                            duration_samples=[1.0]),
    ])
    t0 = datetime(2026, 9, 1, tzinfo=UTC)

    def job(key, *, status="open", in_scope=True):
        return Job(company="amazon", req_id=key, dedupe_key=f"amazon:{key}", title="Staff Engineer",
                   url=f"https://example.test/{key}", locations=[], location_groups=[],
                   workplace_type="onsite", level_band="staff", level_confidence="confirmed",
                   family="software_engineering", track="technical", comp_currency="USD",
                   status=status, in_scope=in_scope, first_seen=t0, last_seen=t0, description_sections=[])

    db_session.add_all([job("a"), job("b"), job("c", status="closed"), job("d", in_scope=False)])
    await db_session.commit()

    costs = await load_source_costs(db_session, ["amazon", "apple"])

    assert set(costs) == {"amazon"}, "a company never timed keeps its place"
    assert (costs["amazon"].seconds, costs["amazon"].kept) == (520.0, 2)


@pytest.mark.asyncio
async def test_a_bounded_run_multiplies_its_learned_budget_and_folds_nothing_else():
    """A learned budget that cuts every read never moves, because a cut read
    teaches nothing. So the cut doubles it;
    the run's pages and duration stay out of the samples."""
    row = SourceBindingTuning(binding_id=7, query_key=SOURCE_LEVEL_KEY, page_samples=[103],
                              duration_samples=[410.0, 420.0, 430.0], tuned_max_pages=155,
                              tuned_budget_seconds=736.0, stop_reason_hist={"stopped": 3}, saturated=False)
    session = _Session([row])
    result = await learn_bounds(session, {"qualcomm": stats(bounded=True, duration_seconds=736.0)}, Settings())
    assert result["budgets_raised"] == 1 and result["bindings"] == 0
    assert row.tuned_budget_seconds == 1472.0
    assert (row.duration_samples, row.page_samples, row.tuned_max_pages) == ([410.0, 420.0, 430.0], [103], 155)


@pytest.mark.asyncio
async def test_a_bounded_run_that_also_errored_raises_nothing():
    result = await learn_bounds(_RaisingSession(), {"x": stats(bounded=True, errors=["boom"])}, Settings())
    assert result["budgets_raised"] == 0


@pytest.mark.asyncio
async def test_a_bounded_run_raises_the_budget_the_next_run_reads(db_session):
    """On real rows: the cut raises the source-level budget `load_source_budgets`
    hands the next run, and leaves a per-query row and another company alone."""
    from sqlalchemy import select

    from tracker.company_store import ensure_builtins, ensure_source_bindings
    from tracker.db.models import SourceBinding
    from tracker.workflows.tuning_pass import load_source_budgets

    await ensure_builtins(db_session)
    await ensure_source_bindings(db_session)
    bindings = {
        row.company_slug: row
        for row in (await db_session.scalars(select(SourceBinding).where(SourceBinding.status == "stable"))).all()
    }
    db_session.add_all([
        SourceBindingTuning(binding_id=bindings["amazon"].id, query_key=SOURCE_LEVEL_KEY,
                            duration_samples=[410.0, 420.0, 430.0], tuned_budget_seconds=736.0),
        SourceBindingTuning(binding_id=bindings["amazon"].id, query_key="united_states", tuned_max_pages=50),
        SourceBindingTuning(binding_id=bindings["google"].id, query_key=SOURCE_LEVEL_KEY,
                            duration_samples=[100.0, 110.0, 120.0], tuned_budget_seconds=180.0),
    ])
    await db_session.flush()

    result = await learn_bounds(db_session, {"amazon": stats(bounded=True, duration_seconds=736.0)}, Settings())
    await db_session.flush()

    assert result["budgets_raised"] == 1
    assert await load_source_budgets(db_session, ["amazon", "google"]) == {"amazon": 1472.0, "google": 180.0}
    per_query = await db_session.scalar(select(SourceBindingTuning).where(
        SourceBindingTuning.binding_id == bindings["amazon"].id, SourceBindingTuning.query_key == "united_states"))
    assert per_query.tuned_max_pages == 50 and per_query.tuned_budget_seconds is None
