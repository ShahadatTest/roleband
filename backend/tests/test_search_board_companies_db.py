"""Search reads a company name as a filter for the companies the Board shows.

A query that names a followed company is filtered to it, whether the company
is a built-in or a catalog one. A named company the Board does not show (not
followed, or hidden) stays in the remainder: search reads only the Board's
companies, so a filter to any other could only empty the search.
"""

from __future__ import annotations

import pytest

from tests.factories import make_company
from tracker.search.best_match import board_company_names, relevance_search

BROWSE = {"status": "open", "hidden": []}


async def _no_vector(_text):
    return None


@pytest.mark.asyncio
async def test_a_followed_catalog_company_named_in_a_query_filters_the_search(db_session):
    db_session.add_all([
        make_company("stripe", "Stripe"),
        make_company("airbnb", "Airbnb", enabled=False),
        make_company("lyft", "Lyft", visible=False),
    ])
    await db_session.commit()

    assert set(await board_company_names(db_session)) == {"stripe"}

    followed = await relevance_search(db_session, BROWSE, "stripe staff engineer", 25, 0, embed=_no_vector)
    assert followed.parsed.company == ["stripe"]
    assert followed.parsed.level_band == ["staff"]

    for slug in ("airbnb", "lyft"):
        result = await relevance_search(db_session, BROWSE, f"{slug} staff engineer", 25, 0, embed=_no_vector)
        assert result.parsed.company == [], f"{slug} is off the Board"
        assert slug in result.parsed.remainder.lower()


@pytest.mark.asyncio
async def test_money_named_in_a_query_bounds_the_base_each_row_shows(db_session):
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.db.repo import refresh_search_vectors

    db_session.add(make_company("stripe", "Stripe"))
    for req, posted, estimate in (("posted-250", (250_000, 300_000), 150_000), ("estimate-150", None, 150_000)):
        db_session.add(Job(company="stripe", req_id=req, dedupe_key=f"stripe:{req}", title="Staff Engineer",
                           url=f"https://example.com/{req}", level_band="staff", family="software_engineering",
                           comp_base_median=estimate,
                           comp_median=400_000, comp_currency="USD",
                           disclosed_pay_basis="base" if posted else None, disclosed_pay_period="year" if posted else None,
                           disclosed_currency="USD" if posted else None,
                           disclosed_base_min=posted[0] if posted else None, disclosed_base_max=posted[1] if posted else None))
    await db_session.commit()
    await refresh_search_vectors(db_session, list((await db_session.scalars(select(Job.id))).all()))
    await db_session.commit()

    unbounded = await relevance_search(db_session, BROWSE, "stripe staff engineer", 25, 0, embed=_no_vector)
    assert {row.job.req_id for row in unbounded.rows} == {"posted-250", "estimate-150"}
    result = await relevance_search(db_session, BROWSE, "stripe staff engineer $200k+", 25, 0, embed=_no_vector)
    assert result.parsed.comp_min == 200_000
    # Both rows estimate a 400k total; only the base the row shows decides.
    assert [row.job.req_id for row in result.rows] == ["posted-250"]
