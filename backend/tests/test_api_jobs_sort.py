"""Ordering contract for the paginated /api/jobs list.

The resolver builds the ORDER BY applied to the full filtered dataset before
LIMIT/OFFSET, so these assertions pin the column, direction, NULL placement, and
the stable tiebreaker that keeps pagination consistent.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from tracker.analytics.comp_package import build_job_package
from tracker.api.app import app
from tracker.db.models import Job
from tracker.db.queries.jobs import (
    BEST_FIT_SORT,
    DEFAULT_SORT,
    SORT_COLUMNS,
    apply_job_filters,
    posting_conds,
    resolve_ordering,
)
from tracker.platform.util import local_day_start_utc


def _sql(sort: str, order: str) -> str:
    stmt = select(Job.id).order_by(*resolve_ordering(sort, order))
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_required_columns_are_sortable():
    # Acceptance: Location, Estimated Total Compensation, Age.
    for key in ("location", "comp_median", "days_open"):
        assert key in SORT_COLUMNS


def test_location_sort_orders_by_primary_location_ascending():
    sql = _sql("location", "asc")
    # Postgres arrays are 1-indexed; primary location is locations[1].
    assert "jobs.locations[1] ASC" in sql
    assert "NULLS LAST" in sql


def test_comp_sort_desc_orders_by_median_high_to_low():
    sql = _sql("comp_median", "desc")
    assert "jobs.comp_median DESC NULLS LAST" in sql


def test_age_sort_orders_by_the_listed_duration():
    # "Age" desc (listed longest first) sorts the duration each row shows DESC.
    # It starts at the earliest date either side states for THIS posting: the
    # employer's first published date, or our first sighting. Neither the
    # lineage nor the employer's CURRENT date moves it. It ends at the closing
    # for a closed posting, and now for an open one.
    listed_for = (
        "coalesce(CASE WHEN (jobs.status != 'open') THEN jobs.closed_at END, now()) - "
        "least(jobs.first_posted_at, jobs.first_seen)"
    )
    assert f"{listed_for} DESC" in _sql("days_open", "desc")
    assert f"{listed_for} ASC" in _sql("days_open", "asc")


def test_ordering_always_has_stable_id_tiebreaker():
    # Guarantees deterministic pagination across rows sharing a sort value.
    for key in SORT_COLUMNS:
        assert _sql(key, "asc").rstrip().endswith("jobs.id DESC")


def test_unknown_sort_falls_back_to_default_column():
    fallback_col = str(select(Job.id).order_by(*resolve_ordering("not_a_column", "desc")))
    default_col = str(select(Job.id).order_by(*resolve_ordering(DEFAULT_SORT, "desc")))
    assert fallback_col == default_col


def test_the_sort_keys_the_list_publishes_are_its_columns_and_best_fit():
    # The dashboard types its sort keys from what `/api/jobs` publishes: a
    # column missing here cannot be asked for, and a key here with no column
    # would quietly order by the default.
    query = {p["name"]: p["schema"] for p in app.openapi()["paths"]["/api/jobs"]["get"]["parameters"]}
    assert set(query["sort"]["enum"]) == set(SORT_COLUMNS) | {BEST_FIT_SORT}
    assert query["order"]["enum"] == ["asc", "desc"]


def test_direction_flips_column_ordering():
    assert "ASC" in _sql("comp_median", "asc").split("ORDER BY", 1)[1]
    assert "DESC" in _sql("comp_median", "desc").split("ORDER BY", 1)[1]


def test_the_new_filter_ranges_over_the_indexed_listed_age():
    """`ix_jobs_open_listed_since` serves the New view only while the filter
    states its expression and its predicate verbatim, and reads no events."""
    stmt = apply_job_filters(select(Job.id), {"new_today_only": True})
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "least(jobs.first_posted_at, jobs.first_seen) >" in sql
    assert "jobs.status = 'open'" in sql
    assert "job_lifecycle_events" not in sql


def test_today_uses_the_users_local_calendar_not_utc_midnight():
    # 01:30 UTC on Jul 16 is still Jul 15 in Los Angeles. The signal count must
    # not reset during the user's evening.
    now = datetime(2026, 7, 16, 1, 30, tzinfo=UTC)
    start = local_day_start_utc(now, ZoneInfo("America/Los_Angeles"))
    assert start == datetime(2026, 7, 15, 7, 0, tzinfo=UTC)


def test_regular_board_filter_still_uses_current_scope():
    stmt = apply_job_filters(select(Job.id), {})
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "jobs.in_scope IS true" in sql


def test_discloses_pay_filter_requires_a_band_and_nothing_else():
    """A stored band is the evidence: a page or connector band is
    stated pay before the text pass reads the posting. The DB-backed case is
    `test_posting_pages.test_a_page_band_read_before_the_text_is_on_every_pay_reader`."""
    stmt = apply_job_filters(select(Job.id), {"discloses_pay": True})
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "structured_at" not in sql
    assert "jobs.disclosed_base_min IS NOT NULL" in sql
    assert "jobs.disclosed_base_max IS NOT NULL" in sql


def test_discloses_pay_filter_is_off_by_default():
    stmt = apply_job_filters(select(Job.id), {"discloses_pay": False})
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "disclosed_base_min" not in sql


def test_the_not_for_me_lens_orders_by_the_mark_newest_first():
    # The lens is a review list: the row the reader marked LAST is first, so a
    # mis-click is the first row. The key exists, reads the mark's
    # timestamp through a correlated subquery (the ordinary list query gains
    # no join), and descends with the stable tiebreaker.
    assert "dismissed_at" in SORT_COLUMNS
    sql = _sql("dismissed_at", "desc")
    assert "SELECT job_feedback.created_at" in sql
    assert "job_feedback.job_id = jobs.id" in sql
    assert "DESC NULLS LAST, jobs.id DESC" in sql


# --------------------------------------------------------------------------- #
# Pay shows a total, else an estimated base: like with like
# --------------------------------------------------------------------------- #




async def _pay_rows(db):
    rows = {"total-400": (400_000, None), "total-300": (300_000, 150_000), "base-350": (None, 350_000),
            "base-250": (None, 250_000), "none": (None, None)}
    for req, (total, base) in rows.items():
        db.add(Job(company="acme", req_id=req, dedupe_key=f"acme:{req}", title="Senior Engineer",
                   url=f"https://example.com/{req}", level_band="senior", comp_median=total,
                   comp_base_median=base))
    await db.commit()


@pytest.mark.asyncio
async def test_pay_sort_ranks_totals_then_bases_and_never_a_base_against_a_total(db_session):
    await _pay_rows(db_session)
    order = lambda direction: select(Job.req_id).order_by(*resolve_ordering("comp_median", direction))  # noqa: E731
    desc = list((await db_session.execute(order("desc"))).scalars())
    assert desc == ["total-400", "total-300", "base-350", "base-250", "none"]
    asc = list((await db_session.execute(order("asc"))).scalars())
    assert asc == ["total-300", "total-400", "base-250", "base-350", "none"]


@pytest.mark.asyncio
async def test_the_agent_minimum_pay_reads_the_total_else_the_estimated_base(db_session):
    await _pay_rows(db_session)
    kept = set((await db_session.execute(
        select(Job.req_id).where(*posting_conds({"comp_min": 300_000}))
    )).scalars())
    assert kept == {"total-400", "total-300", "base-350"}  # total-300's base (150k) is not what it shows


def test_a_posting_with_only_a_base_estimate_shows_a_base_and_no_total():
    package = build_job_package(
        company="acme", band="senior", family=None, comp_low=None, comp_median=None, comp_high=None,
        comp_provenance=None, disclosed={"disclosed": False},
        base_estimate={"low": 170_000, "median": 200_000, "high": 230_000, "provider": "builtin", "as_of": None},
    )
    assert package["total"] is None and package["estimate"] is None
    assert package["base_estimate"]["median"] == 200_000
    assert [(c["kind"], c["low"], c["high"]) for c in package["components"]] == [("base", 170_000, 230_000)]


def test_a_total_wins_and_the_base_estimate_stays_out_of_the_package():
    package = build_job_package(
        company="acme", band="senior", family=None, comp_low=340_000, comp_median=400_000, comp_high=460_000,
        comp_provenance="x", disclosed={"disclosed": False},
        base_estimate={"low": 1, "median": 2, "high": 3, "provider": "builtin", "as_of": None},
    )
    assert package["base_estimate"] is None and package["total"] is not None


# --------------------------------------------------------------------------- #
# The Board's pay column: the base each row shows
# --------------------------------------------------------------------------- #

# req_id -> (posted basis, period, currency, posted min, posted max, estimated base, estimate currency).
# Each estimate is set so that reading it where the row does not show it would
# move the row: the posted ones sit above every figure that counts.
_BASE_ROWS = {
    "posted-usd": ("base", "year", "USD", 150_000, 200_000, 300_000, "USD"),
    "estimate-only": (None, None, None, None, None, 180_000, "USD"),
    "posted-hourly": ("base", "hour", "USD", 45, 60, 400_000, "USD"),
    "posted-gbp": ("base", "year", "GBP", 60_000, 80_000, 390_000, "USD"),
    "posted-total": ("total", "year", "USD", 250_000, 300_000, 170_000, "USD"),
    "posted-period-unclear": ("base", "unclear", "USD", 150_000, 200_000, 210_000, "USD"),
    "posted-max-only": ("base", "year", "USD", None, 160_000, None, "USD"),
    # A stored period its size rules out: the row shows the estimate, so the figure is the estimate.
    "posted-hour-too-big": ("base", "hour", "USD", 150_000, 200_000, 300_000, "USD"),
    # No stored period: read by size, as yearly.
    "posted-no-period": ("base", None, "USD", 155_000, 190_000, 390_000, "USD"),
    # An estimate in another currency is shown in it and compares with nothing.
    "estimate-eur": (None, None, None, None, None, 90_000, "EUR"),
    "nothing": (None, None, None, None, None, None, "USD"),
}


def _base_job(req, **extra):
    basis, period, currency, low, high, estimate, estimate_currency = _BASE_ROWS[req]
    return Job(disclosed_pay_basis=basis, disclosed_pay_period=period, disclosed_currency=currency,
               disclosed_base_min=low, disclosed_base_max=high, comp_base_median=estimate,
               comp_currency=estimate_currency, **extra)


async def _base_rows(db):
    for req in _BASE_ROWS:
        db.add(_base_job(req, company="acme", req_id=req, dedupe_key=f"acme:{req}", title="Senior Engineer",
                         url=f"https://example.com/{req}", level_band="senior"))
    await db.commit()


@pytest.mark.asyncio
async def test_the_sort_figure_is_the_base_the_row_shows_in_yearly_dollars_or_nothing(db_session):
    """Parity with the row's own rule (`posted_base`, then the estimate): the
    SQL figure must never rank or filter a row by a number it does not show."""
    from tracker.api.serializers.jobs import posted_base
    from tracker.db.queries.jobs import base_pay

    await _base_rows(db_session)
    figures = dict((await db_session.execute(select(Job.req_id, base_pay()))).all())
    for req in _BASE_ROWS:
        job = _base_job(req)
        shown = posted_base(job)
        if shown is not None:
            expected = (shown["min"] if shown["min"] is not None else shown["max"]) \
                if shown["period"] == "year" and shown["currency"] == "USD" else None
        else:
            expected = job.comp_base_median if job.comp_currency == "USD" else None
        assert figures[req] == expected, req


@pytest.mark.asyncio
async def test_base_pay_sort_reads_the_posted_low_end_else_the_estimate(db_session):
    await _base_rows(db_session)
    order = lambda direction: select(Job.req_id).order_by(*resolve_ordering("base_pay", direction))  # noqa: E731
    ranked = ["posted-hour-too-big", "posted-period-unclear", "estimate-only", "posted-total",
              "posted-max-only", "posted-no-period", "posted-usd"]
    desc = list((await db_session.execute(order("desc"))).scalars())
    assert desc[:7] == ranked
    # Shown but not comparable, or nothing at all: last, never ranked by an estimate the row hides.
    assert set(desc[7:]) == {"posted-hourly", "posted-gbp", "estimate-eur", "nothing"}
    asc = list((await db_session.execute(order("asc"))).scalars())
    assert asc[:7] == ranked[::-1]


@pytest.mark.asyncio
async def test_base_pay_bounds_read_the_figure_the_row_shows(db_session):
    await _base_rows(db_session)

    async def kept(params):
        return set((await db_session.execute(select(Job.req_id).where(*posting_conds(params)))).scalars())

    # posted-usd's estimate (300k), and the hourly, pound and no-period rows' estimates, are not what they show.
    assert await kept({"base_min": 175_000}) == {"posted-hour-too-big", "posted-period-unclear", "estimate-only"}
    assert await kept({"base_max": 160_000}) == {"posted-usd", "posted-max-only", "posted-no-period"}
    assert await kept({"base_min": 160_000, "base_max": 175_000}) == {"posted-total", "posted-max-only"}


def test_a_row_carries_only_a_posted_base_it_can_write():
    from tracker.api.serializers.jobs import posted_base

    assert posted_base(_base_job("posted-usd")) == {"min": 150_000, "max": 200_000, "currency": "USD", "period": "year"}
    assert posted_base(_base_job("posted-hourly")) == {"min": 45, "max": 60, "currency": "USD", "period": "hour"}
    assert posted_base(_base_job("posted-gbp"))["currency"] == "GBP"
    assert posted_base(_base_job("posted-no-period"))["period"] == "year"
    assert posted_base(_base_job("posted-total")) is None
    assert posted_base(_base_job("posted-period-unclear")) is None
    assert posted_base(_base_job("posted-hour-too-big")) is None
    assert posted_base(_base_job("nothing")) is None


@pytest.mark.asyncio
async def test_the_list_sorts_and_bounds_by_base_and_sends_the_posted_range(api_client, db_session):
    await _base_rows(db_session)
    body = (await api_client.get("/api/jobs?sort=base_pay&order=desc&base_min=150000&status=open")).json()
    reqs = [job["req_id"] for job in body["items"]]
    assert reqs == ["posted-hour-too-big", "posted-period-unclear", "estimate-only", "posted-total",
                    "posted-max-only", "posted-no-period", "posted-usd"]
    by_req = {job["req_id"]: job for job in body["items"]}
    assert by_req["posted-usd"]["posted_base"] == {"min": 150_000, "max": 200_000, "currency": "USD", "period": "year"}
    assert by_req["estimate-only"]["posted_base"] is None
