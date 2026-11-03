"""The statistics and demand routes' response contract.

`tracker/api/schemas/statistics.py` declares what `/api/stats`, the Statistics
overview, compensation, stock trajectory, equity validation, both trends and
`/api/demand` send. These tests hold it to its sources:

1. **Vocabularies**: trend dimensions against what each handler accepts; split,
   model and bonus sources against `analytics`; the pooled basis; the assumptions.
2. **An empty radar**: every route answers its empty shape.
3. **Each route over real HTTP** against `tests/statistics_contract_seed.py`: the
   populations each counts (open, in scope, visible, inside the window), today's
   new and reposted roles kept apart, the estimate kept apart from printed bands,
   the rate denominated in roles read, packages that sum, residuals and their
   exclusions, series recomputed from visible raw values, and the demand lists.
4. **Hiding a company** removes it from every route.
5. **Drift**: a builder that adds, drops or mistypes a key fails the response.

`pin_statistics_clock` fixes "now" and the user's day start; `no_escape` guards
every test.
"""

from __future__ import annotations

from datetime import timedelta
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api_errors import said
from tests.factories import make_company
from tests.plugin_seed import cover
from tests.statistics_contract_seed import (
    DAY_START,
    NOW,
    REPORTED_LATEST,
    REPORTS_PLUGIN,
    SeededStatistics,
    _role,
    _stated,
    pin_statistics_clock,
    seed_statistics,
)
from tracker.analytics import comp_residual, comp_split, comp_trends
from tracker.analytics.comp_trends import DISCLOSURE_BASIS
from tracker.api.routers import statistics as router
from tracker.api.schemas import statistics as contract
from tracker.api.schemas.jobs import JobRow
from tracker.company_directory import FOLLOWED_WITH_SET
from tracker.db.models import (
    CompSnapshot,
    DisclosureSnapshot,
    Job,
    JobCompEstimate,
    JobFeedback,
    JobLifecycleEvent,
    JobPlaceSet,
    JobPlaceSetMember,
    PluginInstall,
    ScrapeRun,
    TrackedCompany,
)

ROUTES = {
    "stats": "/api/stats",
    "overview": "/api/statistics/overview",
    "compensation": "/api/statistics/compensation",
    "trajectory": "/api/statistics/comp-trajectory",
    "equity": "/api/statistics/equity-validation",
    "comp_trends": "/api/statistics/comp-trends",
    "disclosure_trends": "/api/statistics/disclosure-trends",
    "demand": "/api/demand",
}


@pytest_asyncio.fixture
async def clock(monkeypatch, no_escape):
    pin_statistics_clock(monkeypatch)


@pytest_asyncio.fixture
async def seeded(api_client, db_session, clock) -> SeededStatistics:
    return await seed_statistics(db_session)


def _fields(model) -> list[str]:
    return list(model.model_fields)


async def _get(api_client, path: str, status: int = 200) -> dict:
    response = await api_client.get(path)
    assert response.status_code == status, response.text
    return response.json()


def _day(days_before_today: int) -> str:
    return (DAY_START - timedelta(days=days_before_today)).date().isoformat()


def _zulu(at) -> str:
    return at.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def test_each_literal_is_the_vocabulary_it_mirrors():
    assert set(get_args(contract.SplitSource)) == {comp_split.SOURCE_OBSERVED, comp_split.SOURCE_HEURISTIC, "mixed"}
    assert set(get_args(contract.ModelSource)) == {comp_split.SOURCE_OBSERVED, comp_split.SOURCE_HEURISTIC}
    assert set(get_args(contract.BonusSource)) == {comp_residual.BONUS_STATED, comp_residual.BONUS_MODELED}
    assert get_args(contract.DisclosureTrendsResponse.model_fields["basis"].annotation) == (DISCLOSURE_BASIS,)
    assert _fields(contract.EquityAssumptions) == list(comp_split.equity_assumptions())


def test_every_shape_forbids_a_key_its_model_does_not_name():
    built = [
        model for model in vars(contract).values()
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__module__ == contract.__name__
    ]
    assert len(built) >= 40
    assert [m.__name__ for m in built if m.model_config.get("extra") != "forbid"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "dims", "refused"),
    [
        ("comp_trends", get_args(contract.CompTrendDim), "bogus"),
        ("disclosure_trends", get_args(contract.DisclosureTrendDim), "family"),
    ],
    ids=["comp", "disclosure"],
)
async def test_a_trend_accepts_exactly_its_dimensions(api_client, seeded, route, dims, refused):
    for dim in dims:
        assert (await _get(api_client, f"{ROUTES[route]}?dim={dim}"))["dim"] == dim
    assert said(await _get(api_client, f"{ROUTES[route]}?dim={refused}", status=400)) == {"detail": "invalid dim"}


# --------------------------------------------------------------------------- #
# 2. An empty radar
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_an_empty_radar_answers_every_shape_with_nothing_in_it(api_client, clock):
    assert await _get(api_client, ROUTES["stats"]) == {
        "open_total": 0, "new_today": 0, "reposted_today": 0, "closed_today": 0, "saved_total": 0,
        "review_pending": 0, "notif_unread": 0, "notif_high_unread": 0, "by_company": {},
    }
    overview = await _get(api_client, ROUTES["overview"])
    assert (overview["top_skills"], overview["top_clusters"], overview["longest_open"]) == ([], [], [])
    compensation = await _get(api_client, ROUTES["compensation"])
    assert (compensation["overall"], compensation["histogram"], compensation["coverage"]) == (
        None, [], {"with_comp": 0, "total_open": 0, "pct": 0.0},
    )
    assert compensation["disclosure"]["overall"] == {"open": 0, "checked": 0, "disclosed": 0, "rate": None}
    trajectory = await _get(api_client, ROUTES["trajectory"])
    assert (trajectory["overall"], trajectory["public"], trajectory["private"]) == (None, [], [])
    equity = await _get(api_client, ROUTES["equity"])
    assert (equity["groups"], equity["reported"]["groups"], equity["reported"]["snapshot_date"]) == ([], [], None)
    assert equity["reported"]["sources"] == []
    assert (await _get(api_client, ROUTES["comp_trends"]))["series"] == []
    assert (await _get(api_client, ROUTES["disclosure_trends"]))["dates"] == []
    assert await _get(api_client, ROUTES["demand"]) == {
        "open_total": 0, "new_today": 0, "closed_today": 0, "companies": [], "regions": [], "unplaced": 0,
        "employer_dated_share": None, "longest_open": [], "listed_over_a_year": 0, "most_reposted": [],
        "most_updated_open": [],
    }


# --------------------------------------------------------------------------- #
# 3. Each route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_header_counts_today_apart_from_reposts_and_counts_only_visible_open_roles(api_client, seeded):
    body = await _get(api_client, ROUTES["stats"])
    assert list(body) == _fields(contract.StatsResponse)
    assert body == {
        "open_total": 27,  # 21 google, 3 openai, 1 netflix, 2 stripe; the hidden, closed and out-of-scope never
        "new_today": 3,  # openai's original and both stripe roles; not the repost, the hidden role or older roles
        "reposted_today": 1,
        "closed_today": 1,
        "saved_total": 2,
        "review_pending": 2,  # the suspected repost and the suspected twin pair; not the auto link
        "notif_unread": 2,  # neither the read nor the dismissed one
        "notif_high_unread": 1,  # one high unread; the read and the dismissed high ones are not
        "by_company": {"google": 21, "netflix": 1, "openai": 3, "stripe": 2},
    }


@pytest.mark.asyncio
async def test_the_overview_scopes_openings_to_its_window_and_names_the_leaders(api_client, seeded):
    body = await _get(api_client, ROUTES["overview"])
    assert list(body) == _fields(contract.StatisticsOverviewResponse)
    assert body["kpis"] == {
        # Every original role first seen in the 30 days, `g-closed` at its edge.
        "open_total": 27, "new_count": 25, "first_scan_count": 0, "closed_count": 1, "companies": 4, "saved_total": 2,
    }
    # Skills from evidence-grounded requirements; an industry is never a skill.
    assert body["top_skills"] == [
        {"term": "python", "category": "language", "job_count": 17},
        {"term": "sql", "category": "language", "job_count": 3},
    ]
    # Slugs only; the dashboard names a cluster by its terms, then its family.
    assert [(c["family_hint"], c["terms"], c["size"]) for c in body["top_clusters"]] == [
        ("product_management", [], 12),
        ("engineering_management", [], 7),
        (None, [], 3),
    ]
    # The role listed longest by its own age (`listed_days`): `o-old`, which the
    # employer dated 120 days ago, not `g-senior`, which we saw first (60 days).
    hardest, *rest = body["longest_open"]
    assert len(rest) == 2 and all(list(row) == _fields(contract.OverviewHardest) for row in body["longest_open"])
    assert (hardest["id"], hardest["title"], hardest["company"]) == (
        seeded.ids["o-old"], "Staff Product Manager, openai-old", "openai",
    )
    demand = await _get(api_client, ROUTES["demand"])
    rows = {row["id"]: row for row in demand["longest_open"]}
    assert hardest["listed_days"] == rows[seeded.ids["o-old"]]["listed_days"]
    assert hardest["listed_days"] - rows[seeded.ids["g-senior"]]["listed_days"] == 60
    # The dashboard builds the brief from these facts
    # (`statistics/names.test.ts`); the response carries no English brief.
    assert "brief" not in body
    all_time = await _get(api_client, f"{ROUTES['overview']}?days=0")
    # `o-old` and `g-senior` join; the repost is never new (as Pace and the header).
    assert (all_time["days"], all_time["kpis"]["new_count"]) == (0, 27)


@pytest.mark.asyncio
async def test_compensation_keeps_the_estimate_apart_from_printed_bands_over_the_roles_open_now(api_client, seeded):
    body = await _get(api_client, ROUTES["compensation"])
    assert list(body) == _fields(contract.CompensationStatsResponse)
    # Every open role, whenever we first saw it: `g-senior` (60 days) and
    # `o-old` (45) are in. A window that kept only roles FIRST SEEN in it would
    # change the population, not the period. Stripe carries no estimate.
    assert body["coverage"] == {"with_comp": 25, "total_open": 27, "pct": 0.926}
    assert (body["overall"]["count"], body["overall"]["min"], body["overall"]["max"]) == (25, 380000, 907556)
    assert all(isinstance(body["overall"][p], float) for p in ("p25", "p50", "p75", "p90"))
    # A group needs `min_roles` priced roles: netflix (1) and openai (3)
    # must not rank first and second on one and three lookups.
    assert body["min_roles"] == 5
    assert [row["level_band"] for row in body["by_level"]] == ["senior", "staff"]
    assert [row["company"] for row in body["by_company"]] == ["google"]
    assert [row["family"] for row in body["by_family"]] == ["product_management"]
    assert all(row["count"] >= 5 for key in ("by_level", "by_company", "by_family") for row in body[key])
    assert all(list(row) == _fields(contract.CompFamilySummary) for row in body["by_family"])
    # Only a skill enough priced roles name; its premium is over like roles, same level and discipline.
    # 17 roles name Python; `count` is the 15 in a (level, discipline) cell with enough roles to compare.
    [python] = body["by_skill"]
    assert (python["term"], python["count"]) == ("python", 15)
    assert isinstance(python["premium"], float)

    # One band per distinct print, with the reqs on it; what cannot sit on a base axis is counted, not dropped.
    # `g-senior`'s band is in: it is open, however long ago we first saw it.
    assert body["disclosed"] == {
        "bands": [
            {"company": "google", "level_band": "senior", "low": 200000, "high": 260000, "reqs": 1},
            {"company": "google", "level_band": "staff", "low": 250000, "high": 320000, "reqs": 2},
            {"company": "google", "level_band": "principal", "low": 340000, "high": 450000, "reqs": 1},
        ],
        "reqs": 4, "companies": 1,
        # The hourly band is pay, just not yearly; only the placeholder is implausible.
        "excluded": {"unclear": 1, "total": 1, "not_usd": 0, "not_yearly": 1, "implausible": 1},
        "truncated": False,
    }
    # The rate is denominated in roles the disclosure pass has read: `o-old` was never read.
    assert body["disclosure"]["overall"] == {"open": 27, "checked": 9, "disclosed": 8, "rate": 0.8889}
    rates = {row["company"]: row for row in body["disclosure"]["by_company"]}
    assert {c: (r["checked"], r["disclosed"], r["rate"]) for c, r in rates.items()} == {
        "google": (6, 6, 1.0), "openai": (1, 1, 1.0), "netflix": (1, 1, 1.0), "stripe": (1, 0, 0.0),
    }
    assert body["disclosure"]["by_company"][-1]["company"] == "stripe"
    assert body["currency"] == "USD"
    # The Window lens is not this route's: a stray `days` changes nothing.
    assert await _get(api_client, f"{ROUTES['compensation']}?days=7") == body


@pytest.mark.asyncio
async def test_a_role_whose_level_we_cannot_place_never_counts_under_a_level_on_pay(api_client, db_session, seeded):
    # A bare title is stored at Mid for sorting and a role-word title
    # at the band its word guessed. Grouped by that band, bare
    # titles would make a "Mid-level" row of published pay above Senior.
    before = await _get(api_client, ROUTES["compensation"])
    bare = [
        _role("google", f"bare-{i}", level="mid", comp=640000, level_basis="none", title="Product Manager, Ads",
              **(_stated(260000, 350000) if i == 0 else {}))
        for i in range(5)
    ]
    guess = _role("google", "guess", level="senior", comp=640000, level_basis="unmapped",
                  title="Product Manager, Search", **_stated(180000, 295000))
    db_session.add_all([*bare, guess])
    await db_session.flush()
    # Our own estimate beside each job's copy: what the daily rollup reads.
    db_session.add_all([JobCompEstimate(job_id=job.id, source="roleband", comp_median=job.comp_median)
                        for job in (*bare, guess)])
    await db_session.commit()

    body = await _get(api_client, ROUTES["compensation"])
    # The estimate by level is unchanged: no Mid-level row of bare titles, no
    # Senior pulled by a guess, and no row restating a guessed lookup.
    assert body["by_level"] == before["by_level"]
    # Printed bands keep placed rows separate from the unplaced row, which is last.
    assert body["disclosed"]["bands"][:3] == before["disclosed"]["bands"]
    assert [(b["level_band"], b["low"], b["high"]) for b in body["disclosed"]["bands"][3:]] == [
        ("unstated", 260000, 350000), ("unstated", 180000, 295000),
    ]
    assert not [b for b in body["disclosed"]["bands"] if b["level_band"] == "mid"]
    # Rates keep each level separate and count unplaced roles once, in the last row.
    rates = body["disclosure"]["by_level"]
    assert rates[:-1] == before["disclosure"]["by_level"]
    assert rates[-1] == {"level_band": "unstated", "open": 6, "checked": 2, "disclosed": 2, "rate": 1.0}

    # The daily rollups the trends read store the same key.
    await comp_trends.compute_comp_metrics(db_session)
    await comp_trends.compute_disclosure_metrics(db_session)
    await db_session.commit()
    comp_keys = set((await db_session.scalars(select(CompSnapshot.level_band).where(
        CompSnapshot.company == "google", CompSnapshot.metric_date >= DAY_START))).all())
    cell_keys = set((await db_session.scalars(select(DisclosureSnapshot.level_band).where(
        DisclosureSnapshot.company == "google", DisclosureSnapshot.metric_date >= DAY_START))).all())
    assert "unstated" in comp_keys and "unstated" in cell_keys
    assert "mid" not in comp_keys | cell_keys


@pytest.mark.asyncio
async def test_pay_in_another_currency_stays_off_the_dollar_axes_and_is_counted(api_client, db_session, seeded):
    # The panel and both trends draw US dollars. A London role with a pound band
    # and a pound estimate clears every size floor, so only its currency keeps it
    # off those axes; it still counts as open, read and disclosed.
    before = await _get(api_client, ROUTES["compensation"])
    london = _role("google", "london", level="staff", comp=180000, comp_currency="GBP", locations=["London, UK"],
                   **{**_stated(150000, 210000), "disclosed_currency": "GBP"})
    db_session.add(london)
    await db_session.flush()
    # The daily rollup reads each job's own estimate rows: one in pounds, one in dollars beside it.
    db_session.add_all([
        JobCompEstimate(job_id=london.id, source="roleband", comp_median=180000, comp_currency="GBP"),
        JobCompEstimate(job_id=seeded.ids["g-staff"], source="roleband", comp_median=594000),
    ])
    await db_session.commit()

    body = await _get(api_client, ROUTES["compensation"])
    assert body["overall"] == before["overall"]
    assert body["by_level"] == before["by_level"]
    assert body["coverage"]["with_comp"] == before["coverage"]["with_comp"]
    assert body["coverage"]["total_open"] == before["coverage"]["total_open"] + 1
    assert body["disclosed"]["bands"] == before["disclosed"]["bands"]
    assert body["disclosed"]["excluded"] == {**before["disclosed"]["excluded"], "not_usd": 1}
    assert body["disclosure"]["overall"]["disclosed"] == before["disclosure"]["overall"]["disclosed"] + 1

    await comp_trends.compute_comp_metrics(db_session)
    await comp_trends.compute_disclosure_metrics(db_session)
    await db_session.commit()
    values = (await db_session.scalars(select(CompSnapshot.comp_values).where(
        CompSnapshot.company == "google", CompSnapshot.level_band == "staff", CompSnapshot.metric_date >= DAY_START,
    ))).all()
    assert [v for vs in values for v in vs] == [594000]
    cell = (await db_session.scalars(select(DisclosureSnapshot).where(
        DisclosureSnapshot.company == "google", DisclosureSnapshot.level_band == "staff",
        DisclosureSnapshot.pay_basis == "base", DisclosureSnapshot.metric_date >= DAY_START,
    ))).one()
    assert cell.bands == [{"low": 250000, "high": 320000, "reqs": 2}]
    assert cell.roles == 3


@pytest.mark.asyncio
async def test_the_by_level_trends_show_printed_pay_for_unplaced_roles_but_never_their_estimate(
    api_client, db_session, seeded
):
    yesterday = DAY_START - timedelta(days=1)
    db_session.add_all([
        CompSnapshot(metric_date=yesterday, company="google", level_band="unstated", family="product_management",
                     comp_values=[640000, 640000], source="roleband"),
        DisclosureSnapshot(metric_date=yesterday, company="google", level_band="unstated", pay_basis="base",
                           roles=2, checked=2, bands=[{"low": 260000, "high": 350000, "reqs": 2}]),
    ])
    await db_session.commit()
    comp = await _get(api_client, f"{ROUTES['comp_trends']}?dim=level")
    assert "unstated" not in [s["key"] for s in comp["series"]]
    printed = await _get(api_client, f"{ROUTES['disclosure_trends']}?dim=level")
    [unplaced] = [s for s in printed["series"] if s["key"] == "unstated"]
    assert unplaced["points"][-1]["low_p50"] == 260000.0


@pytest.mark.asyncio
async def test_the_trajectory_packages_sum_and_split_listed_from_private(api_client, seeded):
    body = await _get(api_client, ROUTES["trajectory"])
    assert list(body) == _fields(contract.CompTrajectoryResponse)
    assert body["assumptions"] == comp_split.equity_assumptions()
    packages = [body["overall"], *body["public"], *body["private"]]
    assert all(p["base"] + p["bonus"] + p["equity"] == p["median_tc"] for p in packages)

    public = {row["company"]: row for row in body["public"]}
    assert list(public) == ["google", "netflix"]  # most equity first
    assert all(list(row) == _fields(contract.TrajectoryPublicCompany) for row in body["public"])
    assert (public["google"]["ticker"], public["google"]["equity_vehicle"], public["google"]["count"]) == ("GOOGL", "rsu", 21)
    # A listed cash election carries no equity, and that is a measurement.
    assert {k: public["netflix"][k] for k in ("ticker", "equity_vehicle", "equity_pct", "split_source")} == {
        "ticker": "NFLX", "equity_vehicle": "cash_election", "equity_pct": 0.0, "split_source": "measured",
    }
    [openai] = body["private"]
    assert list(openai) == _fields(contract.TrajectoryPrivateCompany)
    assert (openai["company"], openai["equity_vehicle"], openai["split_source"]) == ("openai", None, "heuristic")
    assert body["overall"]["count"] == 22


@pytest.mark.asyncio
async def test_equity_validation_implies_equity_from_stated_cash_and_counts_every_exclusion(
    api_client, seeded, db_session
):
    body = await _get(api_client, ROUTES["equity"])
    assert list(body) == _fields(contract.EquityValidationResponse)
    groups = {(g["company"], g["band"]): g for g in body["groups"]}
    assert list(groups) == [("google", "senior"), ("google", "staff")]
    staff, senior = groups[("google", "staff")], groups[("google", "senior")]
    assert {k: staff[k] for k in ("reqs", "bands", "comp_medians", "modeled_pct", "model_source", "bonus_source")} == {
        "reqs": 2, "bands": 1, "comp_medians": [594000], "modeled_pct": 0.4579, "model_source": "measured",
        "bonus_source": "stated",
    }
    # No stated bonus and no observed senior rung: the bonus comes from google's other rungs.
    assert (senior["model_source"], senior["bonus_source"]) == ("heuristic", "modeled")
    for group in groups.values():
        assert group["implied_equity"]["low"] <= group["implied_equity"]["mid"] <= group["implied_equity"]["high"]
        shares = group["implied_pct"]
        assert group["consistent"] is (shares["low"] <= group["modeled_pct"] <= shares["high"])
    assert body["excluded"] == {
        "basis_not_base": 2, "not_usd": 0, "not_yearly": 1, "stale_version": 1, "implausible": 1,
        # Ours answers pay: our heuristic models the senior share, so nothing is unsplit.
        "unsplit": 0,
    }
    assert body["coverage"] == {"rows": 8, "used_reqs": 3, "distinct_bands": 2, "companies": {"google": 3}}

    # Our dataset holds no reported points: without the plugin RoleBand reads none
    # of its stored ones; on, and having read the companies, it answers alone,
    # each point banded from our atlas when read.
    assert (body["reported"]["snapshot_date"], body["reported"]["coverage"]["observations"]) == (None, 0)
    db_session.add(PluginInstall(
        plugin_id=REPORTS_PLUGIN, name="Acme reports", version="1.0.0", source_dir="/x", manifest_sha="m",
        code_sha="c", fingerprint="f", approved_fingerprint="f", enabled=True,
        manifest={"plugin": {"id": REPORTS_PLUGIN}, "provides": [{"slot": "pay.observations"}]},
    ))
    await db_session.flush()
    cover(db_session, REPORTS_PLUGIN, ("pay.observations",), ("google", "netflix", "openai", "hidden-co"))
    await db_session.commit()
    reported = (await _get(api_client, ROUTES["equity"]))["reported"]
    assert (reported["sources"], reported["snapshot_date"], reported["coverage"]) == (
        [REPORTS_PLUGIN], REPORTED_LATEST.isoformat(), {"observations": 3, "bands": 2},
    )
    by_group = {(g["company"], g["band"]): g for g in reported["groups"]}
    assert {k: by_group[("google", "staff")][k] for k in ("n", "n_estd", "model_stock_pct")} == {
        "n": 2, "n_estd": 1, "model_stock_pct": 0.4579,
    }
    assert {k: by_group[("netflix", "staff")][k] for k in ("n_estd", "source_eq_share_estd", "delta_estd_vs_model")} == {
        "n_estd": 0, "source_eq_share_estd": None, "delta_estd_vs_model": None,
    }


@pytest.mark.asyncio
async def test_comp_trends_recompute_percentiles_from_visible_raw_values_inside_the_window(api_client, seeded):
    body = await _get(api_client, ROUTES["comp_trends"])
    assert list(body) == _fields(contract.CompTrendsResponse)
    assert (body["dim"], body["days"], body["dates"]) == ("overall", 90, [_day(2), _day(1)])
    [market] = body["series"]
    assert (market["key"], market["count"]) == ("", 7)
    # Two raw values on the older day, seven on the newer: exact percentiles, never re-aggregated.
    assert [p["p50"] for p in market["points"]] == [635000.0, 594000.0]

    by_company = await _get(api_client, f"{ROUTES['comp_trends']}?dim=company")
    assert [s["key"] for s in by_company["series"]] == ["netflix", "openai", "google"]
    netflix = by_company["series"][0]
    assert netflix["points"][0] == {"date": _day(2), "p25": None, "p50": None, "p75": None, "p90": None}

    by_family = await _get(api_client, f"{ROUTES['comp_trends']}?dim=family")
    assert [s["key"] for s in by_family["series"]] == ["engineering_management", "product_management"]
    assert (await _get(api_client, f"{ROUTES['comp_trends']}?days=0"))["dates"] == [_day(120), _day(2), _day(1)]


@pytest.mark.asyncio
async def test_disclosure_trends_rate_every_basis_and_pool_bands_within_one(api_client, seeded):
    body = await _get(api_client, ROUTES["disclosure_trends"])
    assert list(body) == _fields(contract.DisclosureTrendsResponse)
    assert (body["basis"], body["dates"]) == ("base", [_day(2), _day(1)])
    market, cohort = body["series"]
    assert market["points"][1] == {
        "date": _day(1), "open": 21, "checked": 5, "disclosed": 4, "rate": 0.8,
        "bands": 2, "reqs": 3, "low_p50": 225000.0, "high_p50": 290000.0,
    }
    # Netflix and stripe were first read yesterday, so the market line moved with
    # the company set; the cohort line follows google alone.
    assert body["cohort"] == {"since": _day(2), "companies": 1}
    assert cohort["key"] == "cohort"
    assert [p["rate"] for p in cohort["points"]] == [1.0, 1.0]
    assert cohort["points"][1]["checked"] == 3

    by_company = await _get(api_client, f"{ROUTES['disclosure_trends']}?dim=company")
    assert [s["key"] for s in by_company["series"]] == ["google", "netflix", "stripe"]
    netflix = by_company["series"][1]
    # A day the series has no cell: nothing checked, no rate, and `date` first like every point.
    assert list(netflix["points"][0]) == _fields(contract.DisclosureTrendPoint)
    assert netflix["points"][0] == {
        "date": _day(2), "open": 0, "checked": 0, "disclosed": 0, "rate": None,
        "bands": 0, "reqs": 0, "low_p50": None, "high_p50": None,
    }
    # An unclear band is disclosed but never pooled.
    assert (netflix["points"][1]["disclosed"], netflix["points"][1]["bands"]) == (1, 0)


@pytest.mark.asyncio
async def test_the_disclosure_trends_read_their_cells_as_columns(api_client, db_session, seeded):
    """The window holds a cell per company, level and basis each day, and an
    object per cell costs the request more than its query. Reading the seeded
    cells as entities is the control: the probe sees those loads."""
    loaded: list[DisclosureSnapshot] = []

    def record(target, _context):
        loaded.append(target)

    event.listen(DisclosureSnapshot, "load", record)
    try:
        for dim in get_args(contract.DisclosureTrendDim):
            assert (await _get(api_client, f"{ROUTES['disclosure_trends']}?dim={dim}"))["series"]
        assert loaded == []
        async with AsyncSession(db_session.bind) as fresh:
            assert (await fresh.scalars(select(DisclosureSnapshot))).all()
        assert loaded
    finally:
        event.remove(DisclosureSnapshot, "load", record)


async def _add_a_place_set_and_an_other_company(db_session, seeded: SeededStatistics) -> dict[str, int]:
    """One stripe role listed at three places (a place set), each posting
    opened today; stripe followed through the Other companies set; and an opening
    today on the out-of-scope `o-out`. Returns the set members' ids."""
    members = {
        key: _role("stripe", key, level="senior", days_open=0, locations=locations, location_groups=[])
        for key, locations in (
            ("pm-emea", ["Remote - EMEA"]), ("pm-london", ["London, UK"]), ("pm-berlin", ["Berlin, Germany"]),
        )
    }
    db_session.add_all(members.values())
    db_session.add(make_company("stripe", "Stripe", source=FOLLOWED_WITH_SET))
    await db_session.flush()
    place_set = JobPlaceSet(company="stripe", title="product manager", text_hash="0" * 32, size=3,
                            places=["Remote - EMEA", "London, UK", "Berlin, Germany"], rule_version="t1")
    db_session.add(place_set)
    await db_session.flush()
    for i, job in enumerate(members.values()):
        job.first_seen = NOW - timedelta(minutes=30 - i)  # pm-emea is the set's first member
        db_session.add(JobPlaceSetMember(job_id=job.id, set_id=place_set.id, status="auto"))
        db_session.add(JobLifecycleEvent(job_id=job.id, event_type="opened", detail={}, created_at=NOW - timedelta(minutes=20)))
    db_session.add(JobLifecycleEvent(job_id=seeded.ids["o-out"], event_type="opened", detail={},
                                     created_at=NOW - timedelta(minutes=10)))
    await db_session.commit()
    return {key: job.id for key, job in members.items()}


@pytest.mark.asyncio
async def test_hiring_counts_each_role_once_by_company_and_by_place(api_client, db_session, seeded):
    """Hiring counts a place set as one role, without summing per-location
    posting slices. A place that names only a region counts as region-wide,
    never once per country."""
    await _add_a_place_set_and_an_other_company(db_session, seeded)
    body = await _get(api_client, ROUTES["demand"])
    assert list(body) == _fields(contract.DemandResponse)
    assert (body["open_total"], body["new_today"], body["closed_today"], body["unplaced"]) == (28, 4, 1, 0)
    # The set is one stripe role (2 + 1, never 2 + 3) and one new role; the
    # out-of-scope opening and the hidden company's count nowhere.
    assert [(c["company"], c["open"], c["new_today"], c["closed_today"]) for c in body["companies"]] == [
        ("google", 21, 0, 1),
        ("stripe", 3, 3, 0),
        ("openai", 3, 1, 0),
        ("netflix", 1, 0, 0),
    ]
    assert sum(c["open"] for c in body["companies"]) == body["open_total"]
    regions = {r["key"]: r for r in body["regions"]}
    assert [r["key"] for r in body["regions"]] == ["north_america", "africa", "europe", "middle_east"]
    assert regions["north_america"] == {
        "key": "north_america", "open": 27, "region_wide": 0, "countries": [{"key": "united_states", "open": 27}],
    }
    # Named in Europe (London, Berlin), so not Europe-wide; EMEA reaches Africa and
    # the Middle East only as a whole, so it is in no country there.
    assert regions["europe"] == {
        "key": "europe", "open": 1, "region_wide": 0,
        "countries": [{"key": "germany", "open": 1}, {"key": "uk", "open": 1}],
    }
    assert regions["africa"] == {"key": "africa", "open": 1, "region_wide": 1, "countries": []}
    assert regions["middle_east"] == {"key": "middle_east", "open": 1, "region_wide": 1, "countries": []}

    # The persistent-role lists, ordered by the age each row shows, not by our
    # first sighting: the role its employer dated 120 days ago leads the one we
    # saw first, 60 days ago.
    assert all(list(row) == _fields(JobRow) for row in body["longest_open"] + body["most_reposted"])
    longest = body["longest_open"]
    assert [row["id"] for row in longest[:2]] == [seeded.ids["o-old"], seeded.ids["g-senior"]]
    ages = [row["listed_days"] for row in longest]
    assert ages == sorted(ages, reverse=True)
    assert len(longest) == 10
    # Two of the 28 open roles are dated by their employer; the hidden,
    # out-of-scope and closed rows are dated too and must not count.
    assert body["employer_dated_share"] == 2 / 28
    reposted = [row["id"] for row in body["most_reposted"]]
    assert reposted[0] == seeded.ids["g-staff"]
    assert set(reposted[1:]) == {seeded.ids["o-repost"], seeded.ids["n-staff"]}
    updated = body["most_updated_open"]
    assert all(list(row) == _fields(contract.UpdatedOpenJob) for row in updated)
    # Two updates at least, still open, never closed.
    assert [(row["id"], row["update_count"], row["last_updated_at"]) for row in updated] == [
        (seeded.ids["g-staff"], 3, _zulu(NOW - timedelta(days=1))),
        (seeded.ids["n-staff"], 2, _zulu(NOW - timedelta(hours=6))),
    ]


@pytest.mark.asyncio
async def test_every_insights_tab_describes_one_set_of_roles(api_client, db_session, seeded):
    """Counting a place set once on Overview, every posting on Pace's ages and
    Pay, every place membership on Hiring and roles out of scope in Pace's
    openings gives five numbers for "open". Every tab reads one rule, so each
    headline is the same number."""
    await _add_a_place_set_and_an_other_company(db_session, seeded)
    overview = await _get(api_client, ROUTES["overview"])
    velocity = await _get(api_client, "/api/statistics/velocity?days=30")
    compensation = await _get(api_client, ROUTES["compensation"])
    hiring = await _get(api_client, ROUTES["demand"])
    headlines = {
        "overview": overview["kpis"]["open_total"],
        "pace": velocity["kpis"]["open_total"],
        "pace age bands": sum(band["count"] for band in velocity["aging"]),
        "pay": compensation["coverage"]["total_open"],
        "hiring": hiring["open_total"],
    }
    assert headlines == dict.fromkeys(headlines, 28)
    # Pace's openings: the 25 seeded original roles first seen in the window and
    # the set once; never the out-of-scope opening, the set's other two members
    # or the repost. Overview's "new" is the same number.
    assert (velocity["kpis"]["opened"], velocity["kpis"]["reposted"]) == (26, 1)
    assert overview["kpis"]["new_count"] == velocity["kpis"]["opened"]


async def _onboard_a_company(db_session) -> dict[str, int]:
    """`acme` arrives today: its FIRST run finds three roles its board was already
    listing (one dated by its employer 200 days ago, one 20 days ago, one
    undated), and a later run finds one that opened while we watched."""
    first, later = ScrapeRun(started_at=NOW - timedelta(hours=4), status="ok"), ScrapeRun(
        started_at=NOW - timedelta(hours=2), status="ok")
    db_session.add_all([first, later])
    await db_session.flush()
    found = {
        "acme-dated": _role("acme", "dated", days_open=0, first_posted_at=NOW - timedelta(days=200),
                            arrival="first_read"),
        "acme-recent": _role("acme", "recent", days_open=0, first_posted_at=NOW - timedelta(days=20),
                             arrival="first_read"),
        "acme-undated": _role("acme", "undated", days_open=0, arrival="first_read"),
        "acme-new": _role("acme", "new", days_open=0),
    }
    db_session.add_all(found.values())
    await db_session.flush()
    for key, job in found.items():
        run = later if key == "acme-new" else first
        job.first_seen = run.started_at
        db_session.add(JobLifecycleEvent(job_id=job.id, run_id=run.id, event_type="opened", detail={},
                                         created_at=run.started_at))
    await db_session.commit()
    return {key: job.id for key, job in found.items()}


@pytest.mark.asyncio
async def test_a_scope_narrows_every_tab_to_one_side_and_its_two_sides_add_up(api_client, db_session, seeded):
    """The Other companies can hold most open roles across most of the
    companies, so every unscoped ranking is their long tail. A scope
    (`?side=` and `?family=`) narrows every tab alike; Your companies and Other
    companies partition All, and a discipline narrows the same way."""
    await _add_a_place_set_and_an_other_company(db_session, seeded)  # stripe: the one Other company

    async def headlines(query: str) -> dict:
        overview = await _get(api_client, f"{ROUTES['overview']}?{query}")
        velocity = await _get(api_client, f"/api/statistics/velocity?days=30&{query}")
        pay = await _get(api_client, f"{ROUTES['compensation']}?{query}")
        hiring = await _get(api_client, f"{ROUTES['demand']}?{query}")
        return {
            "overview": overview["kpis"]["open_total"], "pace": velocity["kpis"]["open_total"],
            "pace bands": sum(b["count"] for b in velocity["aging"]), "pay": pay["coverage"]["total_open"],
            "hiring": hiring["open_total"], "companies": sorted(c["company"] for c in hiring["companies"]),
        }

    every, yours, other = [await headlines(q) for q in ("side=all", "side=yours", "side=other")]
    assert other == {
        "overview": 3, "pace": 3, "pace bands": 3, "pay": 3, "hiring": 3, "companies": ["stripe"],
    }  # s-senior, s-unread and the place set once
    assert {k: v for k, v in yours.items() if k != "companies"} == dict.fromkeys(
        ["overview", "pace", "pace bands", "pay", "hiring"], 25
    )
    assert "stripe" not in yours["companies"]
    for key in ("overview", "pace", "pay", "hiring"):
        assert yours[key] + other[key] == every[key] == 28, key

    # A discipline: the two engineering-management roles (`o-original`, `o-old`).
    em = await headlines("family=engineering_management")
    assert {k: v for k, v in em.items() if k != "companies"} == dict.fromkeys(
        ["overview", "pace", "pace bands", "pay", "hiring"], 2
    )
    assert em["companies"] == ["openai"]

    # The skills reads narrow the same way: stripe names no skill.
    assert (await _get(api_client, "/api/skills/top?side=other"))["items"] == []
    assert [i["term"] for i in (await _get(api_client, "/api/skills/top?side=yours"))["items"]] == ["python", "sql"]
    assert await _get(api_client, f"{ROUTES['overview']}?side=everyone", status=422)


@pytest.mark.asyncio
async def test_a_company_first_scan_is_never_new_and_ages_from_its_listed_date(api_client, db_session, seeded):
    """A first read reads a board that was already listing, so every posting on
    it is stored at once. Counted as new, a set of companies arriving at once
    swamps the month's openings, and aged by our first sighting its postings
    all read "under a week"."""
    await _onboard_a_company(db_session)
    overview = await _get(api_client, ROUTES["overview"])
    assert (overview["kpis"]["new_count"], overview["kpis"]["first_scan_count"]) == (26, 3)

    velocity = await _get(api_client, "/api/statistics/velocity?days=30")
    assert (velocity["kpis"]["opened"], velocity["kpis"]["first_scan"]) == (26, 3)
    assert velocity["kpis"]["net"] == 26 - velocity["kpis"]["closed"]
    bands = {band["lo"]: band["count"] for band in velocity["aging"]}
    # acme-dated starts at its employer's date, 200 days ago, not at this morning;
    # acme-recent at 20 days; the undated find and the watched opening at today.
    assert bands[90] == 1  # 3 months and more
    assert bands[14] == 1  # 2 to 4 weeks

    hiring = await _get(api_client, ROUTES["demand"])
    assert hiring["new_today"] == 4  # the seed's three and acme-new, never the first scan's three
    assert [(c["company"], c["new_today"]) for c in hiring["companies"] if c["company"] == "acme"] == [("acme", 1)]


@pytest.mark.asyncio
async def test_the_longest_open_lists_leave_out_a_stale_date_and_count_it(api_client, db_session, seeded):
    """An employer date years old ("Listed for 3,905 days") is a stale date, not
    a role that waited ten years. Such a role keeps its age, leaves the
    longest-open lists and is counted."""
    db_session.add(_role("openai", "evergreen", first_posted_at=NOW - timedelta(days=3000)))
    await db_session.commit()
    hiring = await _get(api_client, ROUTES["demand"])
    assert hiring["listed_over_a_year"] == 1
    assert hiring["longest_open"][0]["id"] == seeded.ids["o-old"]
    overview = await _get(api_client, ROUTES["overview"])
    assert overview["longest_open"][0]["id"] == seeded.ids["o-old"]


@pytest.mark.asyncio
async def test_velocity_states_the_employer_dated_share_of_each_age_sample(api_client, seeded):
    """Pace's ages keep our first-sighting clock; each sample says how much of it
    the employer dated: the open roles behind the median and the bands (2 of 27
    visible, in scope), and the closed postings behind how long postings stay up
    (`g-closed`, dated). Hidden and out-of-scope rows never count."""
    kpis = (await _get(api_client, "/api/statistics/velocity?days=0"))["kpis"]
    assert kpis["employer_dated_share"] == 2 / 27
    assert (kpis["closed_sample"], kpis["closed_employer_dated_share"]) == (1, 1.0)


@pytest.mark.asyncio
async def test_each_header_chip_counts_the_board_view_it_opens(api_client, db_session, seeded):
    """The chips are links to Board views, so a chip and its list are one
    number: `open_total` never counts roles marked Not for me, which the Board
    hides. Marking one plain role, one of today's new roles and today's repost moves
    every chip with its list."""
    for key in ("g-senior", "s-senior", "o-repost"):
        db_session.add(JobFeedback(job_id=seeded.ids[key], verdict="dismissed"))
    await db_session.commit()

    body = await _get(api_client, ROUTES["stats"])
    lenses = {"open_total": "", "new_today": "&new_today_only=true", "reposted_today": "&repost_today_only=true"}
    board = {
        chip: (await _get(api_client, f"/api/jobs?status=open&limit=1{query}"))["total"]
        for chip, query in lenses.items()
    }
    assert {chip: body[chip] for chip in lenses} == board
    assert board == {"open_total": 24, "new_today": 2, "reposted_today": 0}, (
        "27, 3 and 1 before the marks: each marked role leaves its own chip"
    )


# --------------------------------------------------------------------------- #
# 4. Hiding a company
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_hiding_a_company_removes_it_from_every_route(api_client, db_session, seeded):
    for path in ROUTES.values():
        assert "hidden-co" not in (await api_client.get(path)).text, path
    assert "google" in (await api_client.get(ROUTES["stats"])).text

    db_session.add(make_company("google", "Google", visible=False))
    await db_session.commit()
    for path in [*ROUTES.values(), f"{ROUTES['comp_trends']}?dim=company", f"{ROUTES['disclosure_trends']}?dim=company"]:
        assert "google" not in (await api_client.get(path)).text, path
    assert (await _get(api_client, ROUTES["stats"]))["open_total"] == 6


@pytest.mark.asyncio
async def test_a_company_the_user_stopped_following_leaves_every_route_and_keeps_its_rows(
    api_client, db_session, seeded
):
    """The Board and every count read the companies the user follows.
    Unfollowing leaves `visible` true, so a route reading `visible` alone keeps
    the company's postings on the Board unverified, since nothing scans a
    company nobody follows. The rows are
    kept, untouched; following again brings them back in the same request."""
    db_session.add(make_company("google", "Google", enabled=False))
    await db_session.commit()
    for path in [*ROUTES.values(), f"{ROUTES['comp_trends']}?dim=company", f"{ROUTES['disclosure_trends']}?dim=company"]:
        assert "google" not in (await api_client.get(path)).text, path
    assert (await _get(api_client, ROUTES["stats"]))["open_total"] == 6
    # Nothing is deleted, closed or rewritten.
    google = (await db_session.scalars(select(Job).where(Job.company == "google"))).all()
    assert len(google) == 22 and sum(job.status == "open" for job in google) == 21

    # Following again (google is walled, so the follow itself goes through its
    # consent dialog; the row it writes is this). No scan runs in between.
    google_row = await db_session.get(TrackedCompany, "google")
    google_row.enabled = True
    await db_session.commit()
    assert (await _get(api_client, ROUTES["stats"]))["open_total"] == 27
    assert "google" in (await api_client.get(ROUTES["stats"])).text


# --------------------------------------------------------------------------- #
# 5. Drift
# --------------------------------------------------------------------------- #


def _adding(real):
    def drifted(*args, **kwargs):
        return {**real(*args, **kwargs), "unmodelled": True}

    return drifted


def _each_skill_without_premium(real):
    def drifted(*args, **kwargs):
        return [{k: v for k, v in row.items() if k != "premium"} for row in real(*args, **kwargs)]

    return drifted


def _each_group_without_modeled_share(real):
    def drifted(*args, **kwargs):
        body = real(*args, **kwargs)
        return {**body, "groups": [{k: v for k, v in g.items() if k != "modeled_pct"} for g in body["groups"]]}

    return drifted


def _series_without_count(real):
    def drifted(*args, **kwargs):
        body = real(*args, **kwargs)
        return {**body, "series": [{k: v for k, v in s.items() if k != "count"} for s in body["series"]]}

    return drifted


def _points_with_an_extra_key(real):
    def drifted(*args, **kwargs):
        body = real(*args, **kwargs)
        return {**body, "series": [{**s, "points": [{**p, "median": None} for p in s["points"]]} for s in body["series"]]}

    return drifted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "drift", "route"),
    [
        ("build_comp_stats", _adding, "compensation"),
        ("rank_skill_comp", _each_skill_without_premium, "compensation"),
        ("build_comp_trajectory", _adding, "trajectory"),
        ("build_equity_residuals", _each_group_without_modeled_share, "equity"),
        ("build_comp_trend_series", _series_without_count, "comp_trends"),
        ("build_disclosure_trend_series", _points_with_an_extra_key, "disclosure_trends"),
        ("serialize_job", _adding, "demand"),
    ],
    # No builder here writes English: the dashboard names families, so there is
    # no name left to drift.
    ids=["comp_stats_key_added", "skill_premium_dropped", "trajectory_key_added", "residual_share_dropped",
         "trend_count_dropped", "disclosure_point_key_added", "demand_row_key_added"],
)
async def test_a_builder_that_drifts_fails_the_response(api_client, seeded, monkeypatch, name, drift, route):
    monkeypatch.setattr(router, name, drift(getattr(router, name)))
    with pytest.raises(ResponseValidationError):
        await api_client.get(ROUTES[route])
