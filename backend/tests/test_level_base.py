"""Our per-level base pay is a dataset file, and the profile shows it.

Contracts: `atlas/level_base.csv` is exactly what `enrich.level_pay.level_bases`
computes (a stale file fails and names the rebuild); rows contain amounts and
matching keys only; the company profile
shows our software-engineering rows only while no pay plugin is selected (one
source), with the bonus the company's policy states and never a
guessed one, and says when a level pays less base than the one under it.
"""

from __future__ import annotations

import pytest

from scripts.build_level_base import build_text
from tests.plugin_seed import cover
from tracker.db.models import CompanyProfile, PluginInstall
from tracker.enrich.level_pay import level_bases
from tracker.levels.atlas import LEVEL_BASE, load_level_base
from tracker.plugins.registry import PAY_LEVELS

pytestmark = pytest.mark.usefixtures("no_escape")


def test_the_file_is_what_our_evidence_computes():
    assert LEVEL_BASE.path.read_text(encoding="utf-8") == build_text(), (
        "atlas/level_base.csv is stale: run `.venv/bin/python -m scripts.build_level_base`")


def test_each_row_keeps_the_calculated_amount_without_traceability_fields():
    computed = {(k[0], k[1], k[2].value): v for k, v in level_bases().items()}
    rows = [row for rows in load_level_base().values() for row in rows]
    assert len(rows) == len(computed)
    for row in rows:
        assert set(row) == {"company", "family", "band", "base_usd", "stock_usd"}
        lb = computed[row["company"], row["family"], row["band"]]
        assert int(row["base_usd"]) == lb.base


async def _profile(api_client, db_session, slug):
    db_session.add(CompanyProfile(slug=slug, display_name=slug.title()))
    await db_session.commit()
    response = await api_client.get(f"/api/company-profiles/{slug}")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_the_profile_shows_our_base_with_the_bonus_its_policy_states(api_client, db_session):
    amazon = (await _profile(api_client, db_session, "amazon"))["level_base"]
    assert [(r["band"], r["base_usd"]) for r in amazon][:2] == [("entry", 129000), ("mid", 173496)]
    assert set(amazon[0]) == {"band", "base_usd", "bonus_ratio", "bonus_usd", "below_lower", "stock_usd", "total_usd"}
    assert {(r["bonus_ratio"], r["bonus_usd"]) for r in amazon} == {(0.0, 0)}  # Amazon pays no annual bonus
    google = {r["band"]: r for r in (await _profile(api_client, db_session, "google"))["level_base"]}
    assert (google["senior"]["bonus_ratio"], google["senior"]["bonus_usd"]) == (0.175, round(236000 * 0.175))
    assert (google["entry"]["bonus_ratio"], google["entry"]["bonus_usd"]) == (None, None)  # unverified is not 0


@pytest.mark.asyncio
async def test_a_level_paying_less_than_the_one_under_it_is_said(api_client, db_session):
    meta = {r["band"]: r for r in (await _profile(api_client, db_session, "meta"))["level_base"]}
    assert meta["staff"]["base_usd"] < meta["senior"]["base_usd"]
    assert meta["staff"]["below_lower"] is True
    assert meta["senior"]["below_lower"] is False and meta["entry"]["below_lower"] is False


@pytest.mark.asyncio
async def test_a_selected_pay_plugin_answers_alone(api_client, db_session):
    db_session.add(PluginInstall(plugin_id="tpl", name="T", version="1", source_dir="/x", manifest_sha="m",
                                 code_sha="c", manifest={"provides": [{"slot": PAY_LEVELS}]}, fingerprint="f",
                                 approved_fingerprint="f", enabled=True))
    await db_session.flush()
    cover(db_session, "tpl", (PAY_LEVELS,), ("amazon",))
    assert (await _profile(api_client, db_session, "amazon"))["level_base"] == []


def test_stock_is_the_reported_point_or_none_where_the_policy_grants_none():
    """Show stock for the companies our data holds it for. A
    policy of no stock is 0 (it wins over a estimated point); a estimated point's
    equity otherwise; nothing else is ever 0."""
    from tracker.levels.model import EQUITY_NONE
    from tracker.levels.pay import policy_for

    computed = {(k[0], k[1], k[2].value): v for k, v in level_bases().items()}
    for (company, _), rows in load_level_base().items():
        none = policy_for(company).equity_rule == EQUITY_NONE
        for row in rows:
            lb = computed[(company, row["family"], row["band"])]
            if none:
                assert row["stock_usd"] == "0"
            elif lb.estimated is not None and lb.estimated.equity is not None:
                assert int(row["stock_usd"]) == lb.estimated.equity
            else:
                assert row["stock_usd"] == ""
    assert any(r["stock_usd"] == "0" for rows in load_level_base().values() for r in rows)


@pytest.mark.asyncio
async def test_a_total_needs_base_bonus_and_stock(api_client, db_session):
    from tracker.api.routers.companies import _level_base_row

    # Amazon states its bonus (none), so its stock alone decides whether a total exists.
    known = _level_base_row("amazon", {"band": "senior", "base_usd": "200000", "stock_usd": "170160"})
    assert known["total_usd"] == 200000 + 0 + 170160
    assert _level_base_row("amazon", {"band": "senior", "base_usd": "200000", "stock_usd": ""})["total_usd"] is None
    assert _level_base_row("google", {"band": "entry", "base_usd": "150000", "stock_usd": "40000"})["total_usd"] is None
    google = {r["band"]: r for r in (await _profile(api_client, db_session, "google"))["level_base"]}
    assert all(r["total_usd"] is None for r in google.values() if r["bonus_ratio"] is None or r["stock_usd"] is None)


@pytest.mark.asyncio
async def test_a_profile_row_carries_no_source_metadata(api_client, db_session):
    rows = (await _profile(api_client, db_session, "1password"))["level_base"]
    assert rows
    for row in rows:
        assert not {"basis", "stated_by", "reported_rung", "stock_basis", "stock_stated_by", "stock_as_of"} & row.keys()
