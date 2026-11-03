"""The optional pay floor and how a posting's stated pay compares with it.

The floor is a fit input, never a scope gate: saving
one must not change what the Board lists. The comparison says nothing it
cannot verify: no hourly or monthly band, no other currency, and a band
whose basis is total or unstated can only be "below".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.factories import make_job
from tracker.analytics.pay_floor import floor_check
from tracker.settings_store import get_pay_floor, set_pay_floor

FLOOR = {"amount": 250_000, "currency": "USD"}


def _band(low, high, *, basis="base", period="year", currency="USD") -> dict:
    return {"disclosed": True, "base_min": low, "base_max": high, "currency": currency,
            "pay_basis": basis, "pay_period": period}


@pytest.mark.parametrize(("band", "verdict"), [
    (_band(290_000, 376_000), "clears"),
    (_band(250_000, 300_000), "clears"),  # the floor itself clears
    (_band(200_000, 300_000), "straddles"),
    (_band(180_000, 240_000), "below"),
    # A total or unstated-basis figure under the floor puts the base under it too.
    (_band(180_000, 240_000, basis="total"), "below"),
    (_band(180_000, 240_000, basis="unclear"), "below"),
])
def test_a_yearly_band_in_the_floors_currency_gets_a_verdict(band, verdict):
    assert floor_check(FLOOR, band)["verdict"] == verdict


@pytest.mark.parametrize("band", [
    # A total above the floor says nothing about the base inside it.
    _band(290_000, 376_000, basis="total"),
    _band(200_000, 300_000, basis="unclear"),
    # Never annualised, never converted, never guessed.
    _band(120, 160, period="hour"),
    _band(20_000, 25_000, period="month"),
    _band(600_000, 1_066_000, period="unclear"),
    _band(290_000, 376_000, currency="EUR"),
    {"disclosed": False},
    None,
])
def test_what_cannot_be_verified_gets_no_verdict(band):
    assert floor_check(FLOOR, band) is None


def test_no_floor_no_verdict():
    assert floor_check(None, _band(290_000, 376_000)) is None


@pytest.mark.asyncio
async def test_the_store_refuses_a_floor_it_cannot_hold(db_session):
    with pytest.raises(ValueError):
        await set_pay_floor(db_session, 0, "USD")
    with pytest.raises(ValueError):
        await set_pay_floor(db_session, 250_000, "US")
    assert await set_pay_floor(db_session, 250_000, "usd") == FLOOR
    assert await get_pay_floor(db_session) == FLOOR


@pytest.mark.asyncio
async def test_the_routes_save_read_and_remove_the_floor(api_client):
    assert (await api_client.get("/api/profile/pay-floor")).json() == {"pay_floor": None}
    assert (await api_client.put("/api/profile/pay-floor", json={"amount": 0, "currency": "USD"})).status_code == 422
    assert (await api_client.put("/api/profile/pay-floor", json={"amount": 250000, "currency": "US$"})).status_code == 422

    saved = await api_client.put("/api/profile/pay-floor", json={"amount": 250000, "currency": "gbp"})
    assert saved.json() == {"pay_floor": {"amount": 250000, "currency": "GBP"}}
    assert (await api_client.get("/api/profile/pay-floor")).json()["pay_floor"]["currency"] == "GBP"

    assert (await api_client.delete("/api/profile/pay-floor")).json() == {"pay_floor": None}
    assert (await api_client.get("/api/profile/pay-floor")).json() == {"pay_floor": None}


@pytest.mark.asyncio
async def test_job_detail_says_how_the_stated_base_compares(api_client, db_session):
    job = make_job(
        "floored", structured_at=datetime(2026, 9, 1, tzinfo=UTC), disclosed_base_min=290_000, disclosed_base_max=376_000,
        disclosed_currency="USD", disclosed_pay_basis="base", disclosed_pay_period="year",
    )
    db_session.add(job)
    await db_session.commit()

    assert (await api_client.get(f"/api/jobs/{job.id}")).json()["pay_floor_check"] is None
    await api_client.put("/api/profile/pay-floor", json={"amount": 250000, "currency": "USD"})
    check = (await api_client.get(f"/api/jobs/{job.id}")).json()["pay_floor_check"]
    assert check == {"verdict": "clears", "amount": 250000, "currency": "USD", "basis": "base"}


@pytest.mark.parametrize(("low", "high", "period"), [
    # A salary stored as hourly by a words-anywhere rule (Netflix's benefits line).
    (290_000, 376_000, "hour"),
    # The parser's own "could not tell" ("Base pay: $10,000 - $12,000 per
    # month" against a month ceiling at the yearly floor). Promoted to `year`, it
    # would clear or fall below a floor and be split into base, bonus and equity.
    (10_000, 12_000, "unclear"),
])
@pytest.mark.asyncio
async def test_a_stored_period_its_amount_contradicts_gets_no_verdict_and_no_split(
    api_client, db_session, low, high, period
):
    job = make_job(
        "contradicts", structured_at=datetime(2026, 9, 1, tzinfo=UTC), disclosed_base_min=low,
        disclosed_base_max=high, disclosed_currency="USD", disclosed_pay_basis="base",
        disclosed_pay_period=period,
    )
    db_session.add(job)
    await db_session.commit()
    await api_client.put("/api/profile/pay-floor", json={"amount": 11000, "currency": "USD"})

    body = (await api_client.get(f"/api/jobs/{job.id}")).json()
    assert body["disclosed_comp"]["pay_period"] == "unclear"
    assert body["pay_floor_check"] is None
    assert body["comp_package"]["no_split_reason"] == "period_unclear"


@pytest.mark.asyncio
async def test_a_floor_never_narrows_what_the_board_lists(api_client, db_session):
    """Negative control: the floor is a fit input, not a scope gate. A
    posting below it, and one that states no pay, both stay listed."""
    db_session.add_all([
        make_job("below", disclosed_base_min=100_000, disclosed_base_max=120_000,
             disclosed_currency="USD", disclosed_pay_basis="base", disclosed_pay_period="year"),
        make_job("silent"),
    ])
    await db_session.commit()
    before = (await api_client.get("/api/jobs")).json()["total"]
    await api_client.put("/api/profile/pay-floor", json={"amount": 250000, "currency": "USD"})
    assert (await api_client.get("/api/jobs")).json()["total"] == before == 2
