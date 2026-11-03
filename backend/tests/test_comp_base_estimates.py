"""Insights keeps an estimated base apart from an estimated total.

A posting our dataset can price only by its base (`comp_component = "base"`)
has no total, so the compensation statistics, which aggregate totals, would
leave it out with no word. Such postings are reported in their own
labelled block, never on the totals' axis: a base beside a total reads as a
lower-paying role.
"""

from __future__ import annotations

import pytest

from tests.factories import make_job
from tracker.analytics.comp_stats import COMP_MIN_ROLES
from tracker.db.models import Job

pytestmark = pytest.mark.usefixtures("no_escape")

ROUTE = "/api/statistics/compensation"


def _base_only(key: str, base: int, **over) -> Job:
    return make_job(key, comp_component="base", comp_median=None, comp_base_median=base,
                comp_base_low=int(base * 0.85), comp_base_high=int(base * 1.15), comp_provider="builtin", **over)


def _total(key: str, total: int, **over) -> Job:
    over.setdefault("comp_base_median", None)
    return make_job(key, company="meta", dedupe_key=f"meta:{key}", comp_component="total", comp_median=total,
                comp_low=int(total * 0.85), comp_high=int(total * 1.15), **over)


@pytest.mark.asyncio
async def test_base_only_roles_are_reported_apart_and_never_on_the_totals_axis(api_client, db_session):
    n = COMP_MIN_ROLES
    db_session.add_all([_base_only(f"b{i}", 240_000 + 1_000 * i) for i in range(n)])
    db_session.add_all([_total(f"t{i}", 500_000) for i in range(n)])
    # A priced total that also states its base is a total, and stays one.
    db_session.add(_total("both", 500_000, comp_base_median=300_000))
    await db_session.commit()

    body = (await api_client.get(ROUTE)).json()

    assert body["coverage"]["with_comp"] == n + 1
    assert body["overall"]["p50"] == 500_000  # no base pulled the totals down
    base = body["base_estimates"]
    assert base["coverage"] == {"with_base": n, "total_open": 2 * n + 1}
    assert base["overall"]["p50"] == 242_000
    assert [(r["level_band"], r["count"]) for r in base["by_level"]] == [("staff", n)]
    assert [(r["company"], r["count"]) for r in base["by_company"]] == [("google", n)]
    assert [(r["family"], r["count"]) for r in base["by_family"]] == [("product_management", n)]
    assert base["min_roles"] == COMP_MIN_ROLES


@pytest.mark.asyncio
async def test_with_no_base_only_role_the_block_is_empty_not_missing(api_client, db_session):
    db_session.add_all([_total(f"t{i}", 500_000) for i in range(COMP_MIN_ROLES)])
    await db_session.commit()
    base = (await api_client.get(ROUTE)).json()["base_estimates"]
    assert base["coverage"]["with_base"] == 0
    assert (base["overall"], base["by_level"], base["by_company"], base["by_family"]) == (None, [], [], [])
