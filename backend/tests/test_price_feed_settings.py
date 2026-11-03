"""Settings > Plugins > Stock prices: the price feed's key.

Contracts: the key is write-only (no response carries it, not even after a
save); a blank or spaced key is refused; DELETE forgets it; the state says
where the key in use comes from and what the last run did. Fail-first: a GET
that echoed `api_key` failed `test_no_response_ever_carries_the_key`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

import tracker.api.routers.companies as companies_router
import tracker.api.routers.settings as settings_router
from tracker.db import job_store
from tracker.db.models import (
    CompanyPrice,
    CompanyProfile,
    DerivationState,
    JobRequest,
    PriceFeedRequest,
)
from tracker.prices import provider as P
from tracker.prices.provider import Bar, Fetched
from tracker.profiles import prices as price_store

pytestmark = pytest.mark.usefixtures("no_escape")

KEY = "tk_0123456789abcdef"
ROUTE = "/api/settings/price-feed"


ENV = type("S", (), {"tiingo_api_key": None, "price_feed_hourly_limit": 50,
                     "price_feed_daily_limit": 1000, "price_feed_monthly_symbols": 500})()


class _Feed:
    """The live feed, answering what the test scripts; it is never the network."""

    source = "tiingo"
    attribution = "test"
    metered = True

    def __init__(self, outcome=P.OK):
        self.outcome = outcome
        self.asked: list[str] = []

    async def fetch(self, ticker, since):
        self.asked.append(ticker)
        if self.outcome != P.OK:
            return Fetched(self.outcome)
        # Recent closes: a quote over a week old is not written.
        today = datetime.now(UTC).date()
        return Fetched(P.OK, [Bar(today - timedelta(days=1), 9, 11, 9, 10.0, 5), Bar(today, 10, 12, 10, 11.0, 6)])


@pytest.fixture
def feed(monkeypatch):
    answering = _Feed()
    monkeypatch.setattr(price_store, "get_price_provider", lambda settings, api_key=None: answering)
    return answering


@pytest.fixture(autouse=True)
def _no_environment_key(monkeypatch):
    monkeypatch.setattr(settings_router, "get_settings", lambda: ENV)
    monkeypatch.setattr(companies_router, "get_settings", lambda: ENV)


@pytest.mark.asyncio
async def test_no_key_says_so(api_client):
    r = await api_client.get(ROUTE)
    assert r.status_code == 200
    assert r.json() == {"configured": False, "origin": None, "priced": 0, "as_of": None,
                        "last_run_at": None, "refused": None, "waiting": 0, "next_at": None,
                        "key_check": None}


@pytest.mark.asyncio
async def test_no_response_ever_carries_the_key(api_client):
    saved = await api_client.put(ROUTE, json={"api_key": f"  {KEY} "})
    assert saved.status_code == 200
    assert saved.json()["configured"] is True and saved.json()["origin"] == "settings"
    read = await api_client.get(ROUTE)
    for r in (saved, read):
        assert KEY not in r.text and "api_key" not in r.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "   ", "two words"])
async def test_a_blank_or_spaced_key_is_refused(api_client, bad):
    r = await api_client.put(ROUTE, json={"api_key": bad})
    assert r.status_code == 422
    assert (await api_client.get(ROUTE)).json()["configured"] is False


@pytest.mark.asyncio
async def test_delete_forgets_the_key(api_client):
    await api_client.put(ROUTE, json={"api_key": KEY})
    r = await api_client.delete(ROUTE)
    assert r.status_code == 200 and r.json()["configured"] is False


@pytest.mark.asyncio
async def test_the_state_counts_live_prices_and_reads_the_last_run(api_client, db_session):
    db_session.add_all([
        CompanyProfile(slug="acme", display_name="Acme", is_public=True, ticker="ACME"),
        CompanyProfile(slug="sample", display_name="Sample", is_public=True, ticker="SMPL"),
    ])
    await db_session.commit()
    ran = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    db_session.add_all([
        CompanyPrice(company_slug="acme", ticker="ACME", price=Decimal("10"), as_of=date(2026, 10, 9), source="tiingo"),
        # The offline sample is not a live price.
        CompanyPrice(company_slug="sample", ticker="SMPL", price=Decimal("10"), as_of=date(2026, 10, 10), source="fixture"),
        DerivationState(name="prices", last_run_at=ran, last_status="ok", detail={"refused": "unauthorized"}),
    ])
    await db_session.commit()
    body = (await api_client.get(ROUTE)).json()
    assert (body["priced"], body["as_of"], body["refused"]) == (1, "2026-10-09", "unauthorized")
    assert body["last_run_at"].startswith("2026-10-12T09:00")


@pytest.mark.asyncio
async def test_a_chart_says_whether_a_key_is_set_and_credits_nobody_while_empty(api_client, db_session, feed):
    """The empty chart must not say "offline sample" with no key and nothing
    shown; it knows whether to point at Settings or wait for the next scan."""
    db_session.add(CompanyProfile(slug="acme", display_name="Acme", is_public=True, ticker="ACME"))
    await db_session.commit()
    before = (await api_client.get("/api/company-profiles/acme/prices")).json()
    assert (before["feed_configured"], before["attribution"], before["bars"]) == (False, None, [])
    feed.outcome = P.TIMEOUT
    await api_client.put(ROUTE, json={"api_key": KEY})
    after = (await api_client.get("/api/company-profiles/acme/prices")).json()
    assert (after["feed_configured"], after["attribution"]) == (True, None)


async def _requests(db_session) -> list[tuple[str, str]]:
    db_session.expire_all()
    rows = await db_session.scalars(select(JobRequest).where(JobRequest.job == "prices").order_by(JobRequest.id))
    return [(row.requested_by, row.state) for row in rows]


@pytest.mark.asyncio
async def test_a_saved_key_shows_its_first_price_before_the_save_answers(api_client, db_session, feed):
    """S2: the key's first request is the first followed ticker's bars, stored at
    once; the rest are the prices job's, asked for in the same save."""
    db_session.add(CompanyProfile(slug="acme", display_name="Acme", is_public=True, ticker="ACME"))
    await db_session.commit()
    saved = await api_client.put(ROUTE, json={"api_key": KEY})
    assert saved.status_code == 200
    assert (saved.json()["key_check"], saved.json()["priced"]) == ("ok", 1)
    assert feed.asked == ["ACME"]
    chart = (await api_client.get("/api/company-profiles/acme/prices")).json()
    assert chart["bars"] and chart["attribution"] == "Price data: Tiingo"
    assert await _requests(db_session) == [("key_saved", "queued")]
    [reserved] = list(await db_session.scalars(select(PriceFeedRequest)))
    assert (reserved.purpose, reserved.outcome) == ("check", "ok")


@pytest.mark.asyncio
async def test_a_key_the_feed_refuses_is_not_saved_and_the_dialog_is_told(api_client, db_session, feed):
    db_session.add(CompanyProfile(slug="acme", display_name="Acme", is_public=True, ticker="ACME"))
    await db_session.commit()
    feed.outcome = P.UNAUTHORIZED
    refused = await api_client.put(ROUTE, json={"api_key": KEY})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "price-key-refused"
    assert (await api_client.get(ROUTE)).json()["configured"] is False
    assert await _requests(db_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [P.RATE_LIMITED, P.TIMEOUT, P.OFFLINE])
async def test_a_check_that_could_not_finish_saves_the_key_and_says_so(api_client, db_session, feed, outcome):
    db_session.add(CompanyProfile(slug="acme", display_name="Acme", is_public=True, ticker="ACME"))
    await db_session.commit()
    feed.outcome = outcome
    saved = await api_client.put(ROUTE, json={"api_key": KEY})
    assert saved.status_code == 200
    assert (saved.json()["configured"], saved.json()["key_check"]) == (True, outcome)


@pytest.mark.asyncio
async def test_replacing_a_key_stops_the_old_one_s_work_and_forgets_its_refusal(api_client, db_session, feed):
    db_session.add(DerivationState(name="prices", last_run_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                                   last_status="ok", detail={"refused": "unauthorized"}))
    await db_session.commit()
    await job_store.ring(db_session, "prices", requested_by="update_now")
    await db_session.commit()
    saved = await api_client.put(ROUTE, json={"api_key": KEY})
    assert saved.json()["refused"] is None, "the new key has not been refused by anyone"
    assert await _requests(db_session) == [("update_now", "cancelled"), ("key_saved", "queued")]
    await api_client.delete(ROUTE)
    assert await _requests(db_session) == [("update_now", "cancelled"), ("key_saved", "cancelled")]


@pytest.mark.asyncio
async def test_update_now_asks_the_prices_job(api_client, db_session):
    r = await api_client.post(f"{ROUTE}/refresh")
    assert r.status_code == 200
    assert await _requests(db_session) == [("update_now", "queued")]
