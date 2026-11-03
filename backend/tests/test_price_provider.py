"""Price providers: the fixture series, quote derivation, and the key-gated factory.

The fixture provider is what ships by default (no live market feed is reliable
server-side), so its behavior is a contract: a quote is the last close, the move is
last-vs-prior close, and history is filtered ascending from `since`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from tracker.prices import provider as P
from tracker.prices.provider import (
    Bar,
    FixturePriceProvider,
    Quote,
    TiingoPriceProvider,
    get_price_provider,
    quote_from_bars,
)

FIXTURE = FixturePriceProvider()


def _run(coro):
    return asyncio.run(coro)


def test_quote_is_last_close_with_move_from_prior_close():
    q = _run(FIXTURE.latest("GOOG"))
    assert q is not None
    assert isinstance(q, Quote)
    hist = _run(FIXTURE.history("GOOG", date(2000, 1, 1)))
    assert q.price == hist[-1].close
    # Change is last close minus prior close, sign preserved.
    expected = round(hist[-1].close - hist[-2].close, 4)
    assert q.change_abs == expected
    assert (q.change_pct or 0) > 0 if expected > 0 else (q.change_pct or 0) <= 0


def test_history_is_filtered_from_since_and_ascending():
    bars = _run(FIXTURE.history("AAPL", date(2026, 6, 1)))
    assert bars, "expected bars in the window"
    assert all(b.date >= date(2026, 6, 1) for b in bars)
    assert [b.date for b in bars] == sorted(b.date for b in bars)


def test_history_since_after_all_data_is_empty_not_error():
    assert _run(FIXTURE.history("AAPL", date(2999, 1, 1))) == []


def test_unknown_ticker_yields_no_quote_and_no_bars():
    assert _run(FIXTURE.latest("ZZZZ")) is None
    assert _run(FIXTURE.history("ZZZZ", date(2000, 1, 1))) == []


def test_latest_is_case_insensitive_on_ticker():
    assert _run(FIXTURE.latest("goog")) is not None


def test_quote_from_single_bar_has_no_change():
    one = [Bar(date(2026, 7, 13), 10.0, 11.0, 9.0, 10.5, 100)]
    q = quote_from_bars("X", "USD", one)
    assert q is not None
    assert q.price == 10.5
    assert q.change_abs is None and q.change_pct is None


def testquote_from_bars_computes_negative_move():
    bars = [
        Bar(date(2026, 7, 10), 10.0, 11.0, 9.0, 10.0, 100),
        Bar(date(2026, 7, 13), 10.0, 10.2, 9.0, 9.0, 100),
    ]
    q = quote_from_bars("X", "USD", bars)
    assert q.price == 9.0
    assert q.change_abs == -1.0
    assert q.change_pct == -10.0


def test_quote_from_empty_bars_is_none():
    assert quote_from_bars("X", "USD", []) is None


def test_factory_defaults_to_fixture_without_key():
    settings = type("S", (), {"tiingo_api_key": None})()
    assert isinstance(get_price_provider(settings), FixturePriceProvider)


def test_factory_uses_tiingo_when_key_present():
    settings = type("S", (), {"tiingo_api_key": "secret"})()
    prov = get_price_provider(settings)
    assert isinstance(prov, TiingoPriceProvider)
    assert prov.source == P.TIINGO_SOURCE


def test_fixture_covers_the_tracked_public_tickers():
    """The offline series must include the tickers our public companies resolve to,
    or the dashboard shows blank prices for them."""
    data = json.loads(Path(P.FIXTURE_PATH).read_text())
    tickers = set(data["tickers"])
    # Representative resolved tickers (google->GOOG, twitch->AMZN, etc.).
    for t in ("GOOG", "AAPL", "NFLX", "COIN", "RDDT", "ABNB", "FIG", "AMZN"):
        assert t in tickers, f"fixture missing {t}"
    # Every entry is a non-empty, well-formed OHLC series.
    for name, entry in data["tickers"].items():
        bars = entry["bars"]
        assert bars, f"{name} has no bars"
        assert all({"date", "open", "high", "low", "close"} <= set(b) for b in bars)


def test_a_key_saved_in_settings_picks_tiingo_over_no_environment_key():
    settings = type("S", (), {"tiingo_api_key": None})()
    assert isinstance(get_price_provider(settings, api_key="saved"), TiingoPriceProvider)


def _tiingo(status, body=b"[]", headers=None):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, content=body, headers=headers or {})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TiingoPriceProvider("tk_secret", client=client), seen


def _failing(error: Exception):
    def handler(request):
        raise error

    return TiingoPriceProvider("tk_secret", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


ONE_BAR = b'[{"date": "2026-10-09T00:00:00.000Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 5}]'


def test_the_key_travels_in_the_header_never_the_url():
    """A request URL is what a request log prints."""
    prov, seen = _tiingo(200, ONE_BAR)
    fetched = _run(prov.fetch("XYZ", date(2026, 10, 1)))
    assert fetched.outcome == P.OK
    assert [b.close for b in fetched.bars] == [2]
    assert (fetched.http_status, fetched.bytes) == (200, len(ONE_BAR))
    assert "tk_secret" not in str(seen[0].url)
    assert seen[0].headers["Authorization"] == "Token tk_secret"


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (429, b"", P.RATE_LIMITED),
        (401, b"", P.UNAUTHORIZED),
        (403, b"", P.UNAUTHORIZED),
        (404, b"", P.NO_DATA),
        (500, b"", P.ERROR),
        (200, b"not json", P.ERROR),
        (200, b"[]", P.NO_DATA),
    ],
)
def test_every_answer_is_told_apart_never_an_empty_list(status, body, outcome):
    prov, _seen = _tiingo(status, body)
    fetched = _run(prov.fetch("XYZ", date(2026, 10, 1)))
    assert fetched.outcome == outcome
    assert fetched.bars == []


def test_a_rate_limit_says_how_long_to_wait_when_the_feed_does():
    prov, _seen = _tiingo(429, headers={"Retry-After": "120"})
    assert _run(prov.fetch("XYZ", date(2026, 10, 1))).retry_after == 120.0
    prov, _seen = _tiingo(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert _run(prov.fetch("XYZ", date(2026, 10, 1))).retry_after is None


def test_a_timeout_is_a_timeout_and_an_unreachable_feed_is_offline():
    timed_out = _failing(httpx.ReadTimeout("slow"))
    assert _run(timed_out.fetch("XYZ", date(2026, 10, 1))).outcome == P.TIMEOUT
    offline = _failing(httpx.ConnectError("no route"))
    assert _run(offline.fetch("XYZ", date(2026, 10, 1))).outcome == P.OFFLINE


def test_only_the_live_feed_is_metered():
    assert TiingoPriceProvider("k").metered is True
    assert FixturePriceProvider().metered is False
    assert _run(FIXTURE.fetch("GOOG", date(2000, 1, 1))).outcome == P.OK
    assert _run(FIXTURE.fetch("ZZZZ", date(2000, 1, 1))).outcome == P.NO_DATA
