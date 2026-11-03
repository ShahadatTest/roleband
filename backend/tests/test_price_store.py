"""Price store: read serialization, and the refresh's request budget.

- read helpers coerce Decimal columns to float and shape the JSON the API returns;
- a refresh asks the feed once per ticker however many companies share it, never
  again within `REFRESH_AFTER`, only for the days after the newest real bar;
- every request is reserved in the ledger and committed before it is sent, and
  the hour, the New York day and the month's symbols are counted from it;
- a 429 is waited out, a timeout asked once more, an unreachable feed or a
  refused key stops the run; followed companies go first, and a failing ticker
  waits a doubling backoff;
- a stale newest close writes no quote, a listing the feed does not carry is not
  asked for, and the feed's answer records no identity claim;
- the key saved in Settings wins over the environment and is never read back.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from tracker.db.models import (
    CompanyFact,
    CompanyPrice,
    CompanyPriceBar,
    CompanyProfile,
    PriceFeedRequest,
    TrackedCompany,
)
from tracker.prices import provider as P
from tracker.prices.provider import Bar, Fetched
from tracker.profiles import prices as store


def _run(coro):
    return asyncio.run(coro)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)

    def all(self):
        return self._rows


class FakeSession:
    """Returns queued results for execute(); records nothing else."""

    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        return self._results.pop(0)


def test_latest_price_map_serializes_decimals_to_float():
    row = CompanyPrice(
        company_slug="google",
        ticker="GOOG",
        price=Decimal("213.95"),
        currency="USD",
        change_abs=Decimal("-1.03"),
        change_pct=-0.48,
        as_of=date(2026, 7, 13),
        source="fixture",
    )
    out = _run(store.latest_price_map(FakeSession([_Result([row])])))
    assert out["google"] == {
        "ticker": "GOOG",
        "price": 213.95,
        "currency": "USD",
        "change_abs": -1.03,
        "change_pct": -0.48,
        "as_of": "2026-07-13",
    }
    assert isinstance(out["google"]["price"], float)


def test_latest_price_map_handles_null_change():
    row = CompanyPrice(
        company_slug="x",
        ticker="X",
        price=Decimal("10"),
        currency="USD",
        change_abs=None,
        change_pct=None,
        as_of=date(2026, 7, 13),
        source="fixture",
    )
    out = _run(store.latest_price_map(FakeSession([_Result([row])])))
    assert out["x"]["change_abs"] is None and out["x"]["change_pct"] is None


def test_price_history_serializes_and_orders_are_preserved():
    bars = [
        CompanyPriceBar(
            company_slug="google",
            date=date(2026, 7, 12),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=1234,
            source="fixture",
        )
    ]
    out = _run(store.price_history(FakeSession([_Result(bars)]), "google", date(2026, 1, 1)))
    assert out == [
        {
            "date": "2026-07-12",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1234,
        }
    ]


NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
TODAY = NOW.date()
FREE = store.Limits(hourly=50, daily=1000, monthly_symbols=500)


class _Feed:
    """A metered feed that answers fixed bars, or the outcomes it is scripted
    with, and records every request."""

    source = "tiingo"
    attribution = "test"
    metered = True

    def __init__(self, newest=TODAY, script=None, on_fetch=None):
        self.asked: list[tuple[str, date]] = []
        self._newest = newest
        self._script = dict(script or {})
        self._on_fetch = on_fetch

    async def fetch(self, ticker, since):
        self.asked.append((ticker, since))
        if self._on_fetch is not None:
            await self._on_fetch(ticker)
        outcomes = self._script.get(ticker)
        if outcomes:
            scripted = outcomes.pop(0)
            if isinstance(scripted, Fetched):
                return scripted
            return Fetched(scripted)
        prior = self._newest - timedelta(days=1)
        return Fetched(P.OK, [Bar(prior, 99.0, 101.0, 98.0, 100.0, 10), Bar(self._newest, 100.0, 103.0, 99.0, 102.0, 12)])


async def _no_sleep(_seconds):
    return None


async def _refresh(db, feed, **kwargs):
    kwargs = {"key": "tk_test", "limits": FREE, "checkpoint": db.commit, "now": NOW, "sleep": _no_sleep, **kwargs}
    return await store.refresh_prices(db, feed, **kwargs)


async def _listed(db, slug, ticker, *, followed=False):
    db.add(CompanyProfile(slug=slug, display_name=slug.title(), is_public=True, ticker=ticker))
    if followed:
        db.add(TrackedCompany(slug=slug, display=slug.title(), adapter="greenhouse", enabled=True, status="active"))
    await db.commit()


async def _fetched(db, slug, ticker, ago):
    db.add(CompanyPrice(company_slug=slug, ticker=ticker, price=Decimal("1"), currency="USD",
                        as_of=TODAY, source="tiingo", fetched_at=NOW - ago))
    await db.commit()


async def _spent(db, symbol, at, outcome=P.OK, purpose="bars"):
    db.add(PriceFeedRequest(provider="tiingo", key_fingerprint="x", purpose=purpose, symbol=symbol,
                            requested_at=at, finished_at=at, outcome=outcome))
    await db.commit()


async def _ledger(db) -> list[PriceFeedRequest]:
    db.expire_all()
    return list(await db.scalars(select(PriceFeedRequest).order_by(PriceFeedRequest.id)))


@pytest.mark.asyncio
async def test_one_request_per_ticker_however_many_companies_share_it(db_session):
    await _listed(db_session, "acme", "ACME")
    await _listed(db_session, "acme-labs", "ACME")
    feed = _Feed()
    out = await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["ACME"]
    quotes = (await db_session.execute(select(CompanyPrice.company_slug, CompanyPrice.price))).all()
    assert sorted((s, float(p)) for s, p in quotes) == [("acme", 102.0), ("acme-labs", 102.0)]
    assert out["tickers"]["ACME"]["quote"] is True


@pytest.mark.asyncio
async def test_every_request_is_reserved_and_committed_before_it_is_sent_failures_included(db_session):
    """Seen from another connection while the request is in flight: a process
    that dies mid-request still leaves it counted."""
    engine = db_session.bind
    seen: dict[str, int] = {}

    async def committed_row(ticker):
        async with engine.connect() as other:
            seen[ticker] = await other.scalar(
                text("SELECT count(*) FROM price_feed_requests WHERE symbol = :s AND outcome = 'pending'"),
                {"s": ticker},
            )

    await _listed(db_session, "good", "GOOD")
    await _listed(db_session, "bad", "BADD")
    feed = _Feed(script={"BADD": [P.ERROR]}, on_fetch=committed_row)
    await _refresh(db_session, feed)
    assert seen == {"GOOD": 1, "BADD": 1}
    outcomes = sorted((row.symbol, row.outcome) for row in await _ledger(db_session))
    assert outcomes == [("BADD", P.ERROR), ("GOOD", P.OK)]
    assert all(row.key_fingerprint == store.key_fingerprint("tk_test") != "tk_test" for row in await _ledger(db_session))


@pytest.mark.asyncio
async def test_the_hour_is_counted_from_the_ledger_and_the_next_slot_named(db_session):
    """Failures count: the old ledger, quotes' fetched_at, missed them."""
    for slug, ticker in (("a", "AAAA"), ("b", "BBBB"), ("c", "CCCC")):
        await _listed(db_session, slug, ticker)
    await _spent(db_session, "ZZZZ", NOW - timedelta(minutes=50), outcome=P.TIMEOUT)
    await _spent(db_session, "ZZZZ", NOW - timedelta(minutes=70), outcome=P.OK)
    feed = _Feed()
    out = await _refresh(db_session, feed, limits=store.Limits(hourly=2, daily=1000, monthly_symbols=500))
    assert len(feed.asked) == 1, "one of the hour's two went to a timeout ten minutes ago"
    assert out["deferred"] == 2
    assert out["next_at"] == NOW - timedelta(minutes=50) + timedelta(hours=1)


@pytest.mark.asyncio
async def test_the_day_is_counted_from_midnight_in_new_york(db_session):
    await _listed(db_session, "a", "AAAA")
    # New York's day began at 04:00 UTC: 03:30 UTC was still the day before there.
    await _spent(db_session, "ZZZZ", datetime(2026, 10, 12, 3, 30, tzinfo=UTC))
    await _spent(db_session, "YYYY", datetime(2026, 10, 12, 4, 30, tzinfo=UTC))
    limits = store.Limits(hourly=50, daily=1, monthly_symbols=500)
    out = await _refresh(db_session, _Feed(), limits=limits)
    assert out["deferred"] == 1
    assert out["next_at"] == datetime(2026, 10, 13, 4, 0, tzinfo=UTC), "New York midnight, in UTC"
    out = await _refresh(db_session, _Feed(), limits=store.Limits(hourly=50, daily=2, monthly_symbols=500))
    assert out["deferred"] == 0


@pytest.mark.asyncio
async def test_a_new_symbol_waits_for_the_month_once_its_symbols_are_spent(db_session):
    await _listed(db_session, "known", "KNWN")
    await _listed(db_session, "new", "NEWW")
    await _spent(db_session, "KNWN", NOW - store.REFRESH_AFTER - timedelta(hours=1))
    await _fetched(db_session, "known", "KNWN", store.REFRESH_AFTER + timedelta(hours=1))
    feed = _Feed()
    out = await _refresh(db_session, feed, limits=store.Limits(hourly=50, daily=1000, monthly_symbols=1))
    assert [t for t, _ in feed.asked] == [], "the never-fetched symbol goes first, and the month has no room for it"
    assert out["next_at"] == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_429_stops_the_run_and_nothing_is_sent_before_its_wait(db_session):
    for slug, ticker in (("a", "AAAA"), ("b", "BBBB"), ("c", "CCCC")):
        await _listed(db_session, slug, ticker)
    limited = Fetched(P.RATE_LIMITED, http_status=429, retry_after=600)
    feed = _Feed(script={"BBBB": [limited]})
    out = await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["AAAA", "BBBB"]
    assert (out["refused"], out["retry_at"]) == (P.RATE_LIMITED, NOW + timedelta(seconds=600))
    assert out["deferred"] == 1

    again = _Feed()
    out = await _refresh(db_session, again, retry_at=NOW + timedelta(seconds=600), now=NOW + timedelta(minutes=5))
    assert again.asked == [], "nothing before the wait is over"
    assert out["next_at"] == NOW + timedelta(seconds=600)
    out = await _refresh(db_session, again, retry_at=NOW + timedelta(seconds=600), now=NOW + timedelta(minutes=11))
    assert again.asked, "and the run resumes after it"


@pytest.mark.asyncio
async def test_a_429_without_a_wait_waits_an_hour(db_session):
    await _listed(db_session, "a", "AAAA")
    out = await _refresh(db_session, _Feed(script={"AAAA": [P.RATE_LIMITED]}))
    assert out["retry_at"] == NOW + store.RATE_LIMIT_WAIT


@pytest.mark.asyncio
async def test_a_timeout_is_retried_once_as_its_own_request_and_recorded_as_a_timeout(db_session):
    await _listed(db_session, "slow", "SLOW")
    await _listed(db_session, "never", "NEVR")
    feed = _Feed(script={"SLOW": [P.TIMEOUT], "NEVR": [P.TIMEOUT, P.TIMEOUT]})
    out = await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked].count("SLOW") == 2
    assert out["tickers"]["SLOW"]["quote"] is True, "the retry got the bars"
    assert out["tickers"]["NEVR"]["outcome"] == P.TIMEOUT
    rows = [(row.symbol, row.purpose, row.outcome) for row in await _ledger(db_session)]
    assert ("NEVR", "bars", P.TIMEOUT) in rows and ("NEVR", "retry", P.TIMEOUT) in rows
    assert (await db_session.execute(select(CompanyPrice).where(CompanyPrice.ticker == "NEVR"))).first() is None


@pytest.mark.asyncio
async def test_an_unreachable_feed_stops_the_run_without_retrying(db_session):
    for slug, ticker in (("a", "AAAA"), ("b", "BBBB")):
        await _listed(db_session, slug, ticker)
    feed = _Feed(script={"AAAA": [P.OFFLINE]})
    out = await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["AAAA"]
    assert out["deferred"] == 1


@pytest.mark.asyncio
async def test_a_refused_key_stops_the_run_and_says_so(db_session):
    for slug, ticker in (("a", "AAAA"), ("b", "BBBB")):
        await _listed(db_session, slug, ticker)
    out = await _refresh(db_session, _Feed(script={"AAAA": [P.UNAUTHORIZED]}))
    assert out["refused"] == P.UNAUTHORIZED
    assert out["deferred"] == 1


@pytest.mark.asyncio
async def test_followed_companies_go_first_never_fetched_before_stale(db_session):
    await _listed(db_session, "other-new", "ONEW")
    await _listed(db_session, "other-old", "OOLD")
    await _fetched(db_session, "other-old", "OOLD", timedelta(days=3))
    await _listed(db_session, "mine-old", "MOLD", followed=True)
    await _fetched(db_session, "mine-old", "MOLD", timedelta(days=1))
    await _listed(db_session, "mine-new", "MNEW", followed=True)
    feed = _Feed()
    await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["MNEW", "MOLD", "ONEW", "OOLD"]


@pytest.mark.asyncio
async def test_a_failing_ticker_waits_a_doubling_backoff_instead_of_going_first(db_session):
    await _listed(db_session, "flaky", "FLKY")
    await _listed(db_session, "fine", "FINE")
    await _spent(db_session, "FLKY", NOW - timedelta(minutes=90), outcome=P.ERROR)
    await _spent(db_session, "FLKY", NOW - timedelta(minutes=30), outcome=P.NO_DATA)
    feed = _Feed()
    out = await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["FINE"], "two failures: two hours from the last"
    assert out["next_at"] == NOW - timedelta(minutes=30) + timedelta(hours=2)
    feed = _Feed()
    await _refresh(db_session, feed, now=NOW + timedelta(minutes=91))
    assert [t for t, _ in feed.asked] == ["FLKY"]


@pytest.mark.asyncio
async def test_a_ticker_fetched_within_the_window_is_not_asked_again(db_session):
    await _listed(db_session, "fresh", "FRSH")
    await _listed(db_session, "old", "OLDD")
    await _fetched(db_session, "fresh", "FRSH", timedelta(hours=2))
    await _fetched(db_session, "old", "OLDD", store.REFRESH_AFTER + timedelta(minutes=1))
    feed = _Feed()
    out = await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["OLDD"]
    assert out["due"] == 1
    assert out["next_at"] == NOW - timedelta(hours=2) + store.REFRESH_AFTER, "when FRSH falls due"


@pytest.mark.asyncio
async def test_only_the_days_after_the_newest_real_bar_are_read(db_session):
    """The offline sample's bars never stand in for real ones (they were credited
    to the real feed once)."""
    await _listed(db_session, "known", "KNWN")
    await _fetched(db_session, "known", "KNWN", timedelta(days=2))
    db_session.add(CompanyPriceBar(company_slug="known", date=date(2026, 10, 9), close=Decimal("90"), source="tiingo"))
    await _listed(db_session, "sampled", "SMPL")
    db_session.add(CompanyPriceBar(company_slug="sampled", date=date(2026, 10, 9), close=Decimal("5"), source="fixture"))
    await db_session.commit()
    feed = _Feed()
    await _refresh(db_session, feed)
    since = dict(feed.asked)
    assert since["KNWN"] == date(2026, 10, 9) - store.OVERLAP
    assert since["SMPL"] == TODAY - timedelta(days=store.HISTORY_DAYS)


@pytest.mark.asyncio
async def test_a_stale_close_writes_no_quote_and_is_named(db_session):
    await _listed(db_session, "gone", "GONE")
    feed = _Feed(newest=TODAY - store.STALE_AFTER - timedelta(days=1))
    out = await _refresh(db_session, feed)
    assert out["stale"] == ["GONE"]
    assert (await db_session.execute(select(CompanyPrice))).first() is None
    assert (await db_session.execute(select(CompanyPriceBar))).first() is not None, "bars are history, kept"


@pytest.mark.asyncio
async def test_a_listing_the_feed_does_not_carry_is_not_asked(db_session):
    # The atlas lists Nintendo as 7974 on the Tokyo Stock Exchange.
    await _listed(db_session, "nintendo", "7974")
    await _listed(db_session, "acme", "ACME")
    feed = _Feed()
    await _refresh(db_session, feed)
    assert [t for t, _ in feed.asked] == ["ACME"]


@pytest.mark.asyncio
async def test_the_feed_records_no_identity_claim(db_session):
    await _listed(db_session, "acme", "ACME")
    await _refresh(db_session, _Feed())
    assert (await db_session.execute(select(CompanyFact))).first() is None


@pytest.mark.asyncio
async def test_the_ledger_keeps_a_month_and_some(db_session):
    await _listed(db_session, "acme", "ACME")
    await _spent(db_session, "OLDD", NOW - timedelta(days=store.LEDGER_DAYS + 1))
    await _spent(db_session, "KEEP", NOW - timedelta(days=store.LEDGER_DAYS - 1))
    await _refresh(db_session, _Feed())
    assert {row.symbol for row in await _ledger(db_session)} == {"KEEP", "ACME"}


@pytest.mark.asyncio
async def test_a_second_writer_finds_the_prices_lock_held_and_sends_nothing(db_session):
    await _listed(db_session, "acme", "ACME")
    await store.save_api_key(db_session, "tk_test")
    await db_session.commit()
    settings = type("S", (), {"tiingo_api_key": None, "price_feed_hourly_limit": 50,
                              "price_feed_daily_limit": 1000, "price_feed_monthly_symbols": 500})()
    async with db_session.bind.connect() as other:
        assert await other.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": store.PRICES_LOCK_KEY})
        try:
            assert await store.run_refresh(db_session, settings) == {"skipped": "busy"}
        finally:
            await other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": store.PRICES_LOCK_KEY})
    assert await _ledger(db_session) == []


@pytest.mark.asyncio
async def test_the_saved_key_wins_and_is_never_read_back(db_session):
    env = type("S", (), {"tiingo_api_key": "env-key"})()
    assert await store.api_key(db_session, env) == ("env-key", "environment")
    await store.save_api_key(db_session, "saved-key")
    await db_session.commit()
    assert await store.api_key(db_session, env) == ("saved-key", "settings")
    status = await store.feed_status(db_session, env)
    assert status["configured"] is True and status["origin"] == "settings"
    assert "saved-key" not in repr(status) and "env-key" not in repr(status)
    await store.save_api_key(db_session, None)
    await db_session.commit()
    assert await store.api_key(db_session, env) == ("env-key", "environment")
    none = type("S", (), {"tiingo_api_key": None})()
    assert await store.api_key(db_session, none) == (None, None)
