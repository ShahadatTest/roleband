"""Stock-price providers: a pluggable network boundary for company prices.

Two implementations behind one Protocol:

- `FixturePriceProvider` — reads a checked-in synthetic JSON series: generated
  bars, not market data. Deterministic, no network, the default. This is what ships: no keyless market feed is reliable
  server-side (Stooq now gates bots with a JS proof-of-work; Yahoo's unofficial
  endpoint rate-limits real server IPs), so live data is opt-in.
- `TiingoPriceProvider` — real EOD daily bars from Tiingo. Constructed only when
  a key is configured. Its requests are metered: the refresh reserves each one
  in its ledger first (`tracker.profiles.prices`), one request per ticker. The
  key travels in the `Authorization` header, never the URL, so no request log
  can carry it.

Every request answers a `Fetched` with its outcome, so a timeout, a refusal and
a ticker the feed does not know are told apart.

`get_price_provider(settings, api_key=)` picks: Tiingo iff a key is given or
`tiingo_api_key` is set, else the fixture. Nothing in the store or API knows which
one it got.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

import httpx

from tracker.config import Settings, get_settings
from tracker.platform.http import make_client

log = logging.getLogger(__name__)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "prices.json"
FIXTURE_SOURCE = "fixture"
TIINGO_SOURCE = "tiingo"
ATTRIBUTION_TIINGO = "Price data: Tiingo"
ATTRIBUTION_FIXTURE = "Price data: offline sample (no live market feed configured)"


@dataclass(frozen=True)
class Bar:
    """One daily OHLC bar."""

    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None


@dataclass(frozen=True)
class Quote:
    """A latest quote: last close plus the move that produced it."""

    ticker: str
    price: float
    currency: str
    as_of: date
    change_abs: float | None
    change_pct: float | None


# What one request came to. A provider never answers an empty list for a failure:
# a timeout that reads as "no data" leaves a ticker looking unpriced for good.
OK = "ok"
NO_DATA = "no_data"
UNAUTHORIZED = "unauthorized"
RATE_LIMITED = "rate_limited"
TIMEOUT = "timeout"
OFFLINE = "offline"
ERROR = "error"
#: Outcomes that refuse the whole feed, not one ticker: asking again now would
#: be refused the same way.
REFUSALS = frozenset({UNAUTHORIZED, RATE_LIMITED})


@dataclass(frozen=True)
class Fetched:
    outcome: str
    bars: list[Bar] = field(default_factory=list)
    http_status: int | None = None
    bytes: int | None = None
    #: Seconds a 429 asked to wait (`Retry-After`), when it said.
    retry_after: float | None = None


def quote_from_bars(ticker: str, currency: str, bars: list[Bar]) -> Quote | None:
    """Derive the latest quote from a (chronological) bar series.

    Change is last close vs prior close. Deriving it from the bars keeps quote and
    history internally consistent, whatever the source.
    """
    if not bars:
        return None
    last = bars[-1]
    prev_close = bars[-2].close if len(bars) >= 2 else None
    change_abs = round(last.close - prev_close, 4) if prev_close is not None else None
    change_pct = (
        round((last.close - prev_close) / prev_close * 100, 4)
        if prev_close
        else None
    )
    return Quote(
        ticker=ticker,
        price=last.close,
        currency=currency,
        as_of=last.date,
        change_abs=change_abs,
        change_pct=change_pct,
    )


class PriceProvider(Protocol):
    source: str
    attribution: str
    #: Its requests count against a quota (the ledger reserves each one).
    metered: bool

    async def fetch(self, ticker: str, since: date) -> Fetched: ...


class FixturePriceProvider:
    """Serves a static offline OHLC series. Deterministic; no network."""

    source = FIXTURE_SOURCE
    attribution = ATTRIBUTION_FIXTURE
    metered = False

    def __init__(self, path: Path = FIXTURE_PATH) -> None:
        self._path = path
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            with open(self._path) as f:
                self._data = json.load(f)
        return self._data

    def _bars(self, ticker: str) -> tuple[str, list[Bar]]:
        entry = self._load().get("tickers", {}).get(ticker.upper())
        if not entry:
            return "USD", []
        currency = entry.get("currency", "USD")
        bars = [
            Bar(
                date=date.fromisoformat(b["date"]),
                open=b.get("open"),
                high=b.get("high"),
                low=b.get("low"),
                close=b["close"],
                volume=b.get("volume"),
            )
            for b in entry.get("bars", [])
        ]
        return currency, bars

    async def latest(self, ticker: str) -> Quote | None:
        currency, bars = self._bars(ticker)
        return quote_from_bars(ticker.upper(), currency, bars)

    async def history(self, ticker: str, since: date) -> list[Bar]:
        _currency, bars = self._bars(ticker)
        return [b for b in bars if b.date >= since]

    async def fetch(self, ticker: str, since: date) -> Fetched:
        bars = await self.history(ticker, since)
        return Fetched(OK if bars else NO_DATA, bars)


class TiingoPriceProvider:
    """Live EOD quotes + daily bars from Tiingo. Requires an API key."""

    source = TIINGO_SOURCE
    attribution = ATTRIBUTION_TIINGO
    metered = True
    BASE = "https://api.tiingo.com/tiingo/daily"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._client = client

    async def fetch(self, ticker: str, since: date) -> Fetched:
        params = {"startDate": since.isoformat(), "format": "json"}
        headers = {"Authorization": f"Token {self._key}"}
        url = f"{self.BASE}/{ticker.lower()}/prices"
        owns = self._client is None
        client = self._client or make_client(timeout=20.0)
        try:
            r = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("tiingo %s timed out: %s", ticker, exc)
            return Fetched(TIMEOUT)
        except httpx.TransportError as exc:
            log.warning("tiingo %s unreachable: %s", ticker, exc)
            return Fetched(OFFLINE)
        finally:
            if owns:
                await client.aclose()
        size = len(r.content)
        if r.status_code == 429:
            return Fetched(RATE_LIMITED, http_status=429, bytes=size, retry_after=_retry_after(r))
        if r.status_code in (401, 403):
            return Fetched(UNAUTHORIZED, http_status=r.status_code, bytes=size)
        if r.status_code == 404:
            return Fetched(NO_DATA, http_status=404, bytes=size)
        if r.status_code != 200:
            log.warning("tiingo %s -> %s", ticker, r.status_code)
            return Fetched(ERROR, http_status=r.status_code, bytes=size)
        try:
            rows = r.json()
        except ValueError:
            return Fetched(ERROR, http_status=200, bytes=size)
        out: list[Bar] = []
        for row in rows if isinstance(rows, list) else []:
            try:
                out.append(
                    Bar(
                        date=datetime.fromisoformat(row["date"].replace("Z", "+00:00")).date(),
                        open=row.get("open"),
                        high=row.get("high"),
                        low=row.get("low"),
                        close=row["close"],
                        volume=row.get("volume"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda b: b.date)
        return Fetched(OK if out else NO_DATA, out, http_status=200, bytes=size)


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` in seconds; an HTTP date or nonsense is no answer."""
    try:
        return max(0.0, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return None


def _today() -> date:
    return datetime.now().date()


def get_price_provider(settings: Settings | None = None, api_key: str | None = None) -> PriceProvider:
    """Tiingo when a key is given (the one saved in Settings) or configured in the
    environment, else the offline fixture."""
    settings = settings or get_settings()
    if key := api_key or settings.tiingo_api_key:
        return TiingoPriceProvider(key)
    return FixturePriceProvider()
