"""Persist daily bars and the latest quote for listed companies, the key the
user saved for the price feed, the ledger of every request made to it, and the
refresh that spends that budget.

The refresh runs as the supervisor's `prices` job (on a key save, on "Update
now", and when the job's own result says the next ticker falls due), and by hand
as that job's entry: `python -m tracker.supervisor.entries prices`. Without a key
it does nothing, so the offline sample never lands on its own.

Store and command live together because they must. Targets are
resolved from `CompanyProfile`: a company is priced iff it resolves `is_public`
true and has a `ticker` (our dataset's), on an exchange the feed
carries. The feed answers a price and nothing else: it records no identity claim.

The request budget: Tiingo's free tier allows 50 requests an hour, 1,000 a day
and 500 symbols a month (settings, with those defaults). Every request is
reserved in `price_feed_requests` before it is sent, failures included, and the
budget is counted from those rows. A ticker is asked once per `REFRESH_AFTER`, in
ONE request that reads only the days after its newest stored bar.

Prices are upserted, not appended: the latest quote is a cache, and each daily bar
is corrected in place on re-fetch. The daily bars are the longitudinal record (one
row per company per day): only spending quota could rebuild them, so nothing
deletes them.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tracker.config import Settings, get_settings
from tracker.db.models import (
    AppSetting,
    CompanyPrice,
    CompanyPriceBar,
    CompanyProfile,
    DerivationState,
    PriceFeedRequest,
    TrackedCompany,
)
from tracker.db.queries.companies import is_followed
from tracker.levels.identity import priced
from tracker.platform.secrets import seal, unseal_or_none
from tracker.platform.util import describe_exception
from tracker.prices.provider import (
    ATTRIBUTION_FIXTURE,
    ATTRIBUTION_TIINGO,
    ERROR,
    FIXTURE_SOURCE,
    NO_DATA,
    OFFLINE,
    OK,
    RATE_LIMITED,
    REFUSALS,
    TIINGO_SOURCE,
    TIMEOUT,
    UNAUTHORIZED,
    Bar,
    Fetched,
    PriceProvider,
    Quote,
    get_price_provider,
    quote_from_bars,
)

log = logging.getLogger(__name__)

#: The pipeline pass that runs `refresh_prices` (`workflows.post_passes`).
PRICES_PASS = "prices"
#: `app_settings` row holding the key the user saved in Settings.
PRICE_FEED_KEY = "price_feed"
#: A ticker fetched this recently is not asked again: a daily close moves once a day.
REFRESH_AFTER = timedelta(hours=12)
#: A newest close older than this means the symbol stopped trading under the
#: ticker (renamed, delisted): its quote is not written, and the run names it.
STALE_AFTER = timedelta(days=7)
#: Bars re-read behind the newest stored one: the move needs a prior close, and a
#: corrected bar replaces its first print.
OVERLAP = timedelta(days=7)

# How far back to keep bars. Covers the widest chart range (1y) with headroom.
HISTORY_DAYS = 400


async def priced_targets(
    session: AsyncSession, slugs: list[str] | None = None
) -> dict[str, list[str]]:
    """{ticker: [slug, ...]} for every company we price: its resolved profile says
    listed and names a ticker, on an exchange the feed carries (`levels.identity.
    priced`: Nintendo's 7974 on Tokyo keeps its ticker and is not asked for)."""
    q = select(CompanyProfile.slug, CompanyProfile.ticker).where(
        CompanyProfile.is_public.is_(True),
        CompanyProfile.ticker.isnot(None),
    )
    if slugs:
        q = q.where(CompanyProfile.slug.in_(slugs))
    out: dict[str, list[str]] = {}
    for slug, ticker in (await session.execute(q)).all():
        if ticker and priced(ticker):
            out.setdefault(ticker, []).append(slug)
    return out


async def upsert_quote(
    session: AsyncSession, slug: str, quote: Quote, source: str
) -> None:
    values = {
        "company_slug": slug,
        "ticker": quote.ticker,
        "price": quote.price,
        "currency": quote.currency,
        "change_abs": quote.change_abs,
        "change_pct": quote.change_pct,
        "as_of": quote.as_of,
        "source": source,
        "fetched_at": datetime.now(UTC),
    }
    stmt = pg_insert(CompanyPrice).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[CompanyPrice.company_slug],
        set_={k: v for k, v in values.items() if k != "company_slug"},
    )
    await session.execute(stmt)


async def upsert_history(
    session: AsyncSession, slug: str, bars: list[Bar], source: str
) -> int:
    now = datetime.now(UTC)
    written = 0
    for b in bars:
        values = {
            "company_slug": slug,
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "source": source,
            "fetched_at": now,
        }
        stmt = pg_insert(CompanyPriceBar).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_company_price_bar",
            set_={
                k: v
                for k, v in values.items()
                if k not in ("company_slug", "date")
            },
        )
        await session.execute(stmt)
        written += 1
    return written


async def _newest_bars(session: AsyncSession, slugs: list[str], source: str) -> dict[str, date]:
    """slug -> its newest stored bar's date from `source`; a slug with none is
    absent. By source: the offline sample's bars never stand in for real ones,
    so a first real fetch reads the whole window."""
    if not slugs:
        return {}
    rows = await session.execute(
        select(CompanyPriceBar.company_slug, func.max(CompanyPriceBar.date))
        .where(CompanyPriceBar.company_slug.in_(slugs), CompanyPriceBar.source == source)
        .group_by(CompanyPriceBar.company_slug)
    )
    return {slug: newest for slug, newest in rows.all()}


# --- the request ledger --------------------------------------------------------

#: Taken for a whole refresh by every writer of prices (the supervisor's job, the
#: CLI, a key check), so there is one writer, and one counter of the budget.
PRICES_LOCK_KEY = 91248
#: The provider's day and month run on New York time.
MARKET_ZONE = ZoneInfo("America/New_York")
#: A 429 that names no wait is waited out this long.
RATE_LIMIT_WAIT = timedelta(hours=1)
#: A ticker whose last request failed waits this long, doubling per failure.
FAILURE_BACKOFF = timedelta(hours=1)
FAILURE_BACKOFF_MAX = timedelta(hours=24)
#: A timed-out request is asked once more, this much later.
TIMEOUT_RETRY_SECONDS = 5.0
#: Ledger rows are kept this long: past the month the symbol count reads.
LEDGER_DAYS = 35

_FAILED = frozenset({NO_DATA, TIMEOUT, OFFLINE, ERROR, RATE_LIMITED, UNAUTHORIZED})


@dataclass(frozen=True)
class Limits:
    hourly: int
    daily: int
    monthly_symbols: int

    @classmethod
    def of(cls, settings: Settings) -> Limits:
        return cls(
            settings.price_feed_hourly_limit, settings.price_feed_daily_limit,
            settings.price_feed_monthly_symbols,
        )


def key_fingerprint(key: str) -> str:
    """Which key made a request, never the key: a hash prefix."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


@dataclass
class Budget:
    """What the provider's limits leave, as the ledger counts them: every
    request reserved, failures and refusals included. One budget per
    installation, whichever key spends it."""

    limits: Limits
    hour: list[datetime]
    day: int
    symbols: set[str]
    now: datetime

    def allows(self, symbol: str) -> bool:
        return (
            len(self.hour) < self.limits.hourly
            and self.day < self.limits.daily
            and (symbol in self.symbols or len(self.symbols) < self.limits.monthly_symbols)
        )

    def spend(self, symbol: str) -> None:
        self.hour.append(self.now)
        self.day += 1
        self.symbols.add(symbol)

    def next_slot(self, symbol: str | None = None) -> datetime | None:
        """When a request for `symbol` could next be sent; None if now."""
        if symbol is not None and self.allows(symbol):
            return None
        local = self.now.astimezone(MARKET_ZONE)
        waits = []
        if len(self.hour) >= self.limits.hourly:
            waits.append(sorted(self.hour)[len(self.hour) - self.limits.hourly] + timedelta(hours=1))
        if self.day >= self.limits.daily:
            tomorrow = datetime.combine(local.date() + timedelta(days=1), time(), tzinfo=MARKET_ZONE)
            waits.append(tomorrow.astimezone(UTC))
        if symbol is not None and symbol not in self.symbols and len(self.symbols) >= self.limits.monthly_symbols:
            first = local.date().replace(day=1)
            following = (first + timedelta(days=32)).replace(day=1)
            waits.append(datetime.combine(following, time(), tzinfo=MARKET_ZONE).astimezone(UTC))
        return max(waits) if waits else None


async def read_budget(session: AsyncSession, now: datetime, limits: Limits) -> Budget:
    local = now.astimezone(MARKET_ZONE)
    midnight = datetime.combine(local.date(), time(), tzinfo=MARKET_ZONE).astimezone(UTC)
    month = datetime.combine(local.date().replace(day=1), time(), tzinfo=MARKET_ZONE).astimezone(UTC)
    hour = list(
        (await session.scalars(
            select(PriceFeedRequest.requested_at).where(PriceFeedRequest.requested_at > now - timedelta(hours=1))
        )).all()
    )
    day = await session.scalar(
        select(func.count()).select_from(PriceFeedRequest).where(PriceFeedRequest.requested_at >= midnight)
    )
    symbols = set(
        (await session.scalars(
            select(PriceFeedRequest.symbol).where(PriceFeedRequest.requested_at >= month).distinct()
        )).all()
    )
    return Budget(limits, hour, int(day or 0), symbols, now)


async def reserve(
    session: AsyncSession, *, provider: str, key: str, purpose: str, symbol: str, now: datetime
) -> PriceFeedRequest:
    """The ledger row for a request about to be sent; the caller commits it
    before sending, so a crash mid-request still counts it."""
    row = PriceFeedRequest(
        provider=provider, key_fingerprint=key_fingerprint(key), purpose=purpose, symbol=symbol,
        requested_at=now,
    )
    session.add(row)
    await session.flush()
    return row


def settle(row: PriceFeedRequest, fetched: Fetched) -> None:
    row.outcome = fetched.outcome
    row.http_status = fetched.http_status
    row.bytes = fetched.bytes
    row.finished_at = datetime.now(UTC)


async def prune_ledger(session: AsyncSession, now: datetime) -> None:
    await session.execute(
        delete(PriceFeedRequest).where(PriceFeedRequest.requested_at < now - timedelta(days=LEDGER_DAYS))
    )


@dataclass(frozen=True)
class History:
    """One symbol's requests, as the ledger and the stored quotes remember them."""

    #: When the feed last answered it with bars.
    fetched: datetime | None
    #: Failures since then, and when the latest was asked.
    failures: int
    failed_at: datetime | None

    def due_at(self) -> datetime | None:
        """When it should next be asked; None for a symbol never asked."""
        if self.failures:
            assert self.failed_at is not None
            wait = min(FAILURE_BACKOFF * 2 ** (self.failures - 1), FAILURE_BACKOFF_MAX)
            return self.failed_at + wait
        return self.fetched + REFRESH_AFTER if self.fetched is not None else None


async def _histories(session: AsyncSession, source: str, tickers: list[str]) -> dict[str, History]:
    quoted: dict[str, datetime] = {
        ticker: at
        for ticker, at in (await session.execute(
            select(CompanyPrice.ticker, func.max(CompanyPrice.fetched_at))
            .where(CompanyPrice.source == source, CompanyPrice.ticker.in_(tickers))
            .group_by(CompanyPrice.ticker)
        )).all()
    }
    rows = (await session.execute(
        select(PriceFeedRequest.symbol, PriceFeedRequest.outcome, PriceFeedRequest.requested_at)
        .where(PriceFeedRequest.provider == source, PriceFeedRequest.symbol.in_(tickers))
        .order_by(PriceFeedRequest.requested_at)
    )).all()
    out: dict[str, History] = {}
    for ticker in tickers:
        fetched, failures, failed_at = quoted.get(ticker), 0, None
        for symbol, outcome, at in rows:
            if symbol != ticker or outcome == "pending":
                continue
            if outcome == OK:
                fetched, failures, failed_at = max(filter(None, (fetched, at))), 0, None
            elif outcome in _FAILED:
                failures, failed_at = failures + 1, at
        out[ticker] = History(fetched, failures, failed_at)
    return out


async def _followed(session: AsyncSession, slugs: list[str]) -> set[str]:
    rows = await session.scalars(
        select(TrackedCompany.slug).where(TrackedCompany.slug.in_(slugs), is_followed())
    )
    return set(rows.all())


def order_tickers(
    targets: dict[str, list[str]], histories: dict[str, History], followed: set[str], now: datetime
) -> list[str]:
    """The due tickers, in the order they are asked: followed companies' never
    fetched ones, then followed stale ones, then the rest the same way, each
    group the longest waiting first. A ticker in its failure backoff is not due,
    so a failing ticker no longer goes first on every run."""
    rank: list[tuple[int, datetime, str]] = []
    for ticker, slugs in targets.items():
        history = histories.get(ticker, History(None, 0, None))
        due_at = history.due_at()
        if due_at is not None and due_at > now:
            continue
        group = (0 if any(slug in followed for slug in slugs) else 2) + (0 if history.fetched is None else 1)
        rank.append((group, history.fetched or datetime.min.replace(tzinfo=UTC), ticker))
    return [ticker for _group, _at, ticker in sorted(rank)]


def _since(targets: list[str], newest: dict[str, date], today: date) -> date:
    known = [newest[s] for s in targets if s in newest]
    return (min(known) - OVERLAP) if len(known) == len(targets) else today - timedelta(days=HISTORY_DAYS)


Checkpoint = Callable[[], Awaitable[None]]


async def _ask(
    session: AsyncSession, provider: PriceProvider, *, key: str, ticker: str, since: date,
    purpose: str, checkpoint: Checkpoint, now: datetime,
) -> Fetched:
    """One request: reserved and committed first, sent, then its outcome settled."""
    row = None
    if provider.metered:
        row = await reserve(session, provider=provider.source, key=key, purpose=purpose, symbol=ticker, now=now)
        await checkpoint()
    fetched = await provider.fetch(ticker, since)
    if row is not None:
        settle(row, fetched)
    return fetched


async def refresh_ticker(
    session: AsyncSession,
    provider: PriceProvider,
    ticker: str,
    slugs: list[str],
    bars: list[Bar],
    today: date,
) -> dict:
    """Write one ticker's bars to every company that trades under it, and its
    quote unless the newest close is stale. The feed's word is a price, never
    identity: no claim is recorded (a quote only proves the symbol trades, and a
    market claim would outrank our dataset)."""
    stats: dict = {"ticker": ticker, "bars": 0, "quote": False}
    quote = quote_from_bars(ticker.upper(), "USD", bars)
    stale = quote is not None and today - quote.as_of > STALE_AFTER
    for slug in slugs:
        stats["bars"] = await upsert_history(session, slug, bars, provider.source)
        if quote is not None and not stale:
            await upsert_quote(session, slug, quote, provider.source)
    stats["quote"] = quote is not None and not stale
    if stale:
        stats["stale"] = quote.as_of.isoformat() if quote else None
    return stats


async def _no_commit() -> None:
    return None


async def refresh_prices(
    session: AsyncSession,
    provider: PriceProvider,
    slugs: list[str] | None = None,
    *,
    key: str = "",
    limits: Limits | None = None,
    checkpoint: Checkpoint | None = None,
    retry_at: datetime | None = None,
    now: datetime | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict:
    """Refresh every priced ticker that is due, serially, within the budget.

    Commits nothing itself: `checkpoint` is the caller's commit, called once a
    request is reserved (so it counts even if the process dies mid-request)
    and once a ticker's rows are written (one ticker's failure rolls nothing of
    another back). A 429 stops the run until `retry_at` (its `Retry-After`, else
    an hour); a timeout is asked once more as its own reserved request; an
    unreachable feed stops the run; a refused key stops it and says so.

    Returns {"tickers": {ticker: stats}, "due", "deferred", "stale", "refused",
    "retry_at", "next_at"}: `next_at` is when the job should look again."""
    now = now or datetime.now(UTC)
    today = now.date()
    commit = checkpoint or _no_commit
    limits = limits or Limits.of(get_settings())
    targets = await priced_targets(session, slugs)
    histories = await _histories(session, provider.source, list(targets))
    followed = await _followed(session, [s for group in targets.values() for s in group])
    due = order_tickers(targets, histories, followed, now)
    out: dict = {"tickers": {}, "due": len(due), "deferred": 0, "stale": [], "refused": None,
                 "retry_at": None, "next_at": None}
    if retry_at is not None and retry_at > now:
        out.update(deferred=len(due), refused=RATE_LIMITED, retry_at=retry_at, next_at=retry_at)
        return out
    budget = await read_budget(session, now, limits) if provider.metered else None
    newest = await _newest_bars(session, [s for t in due for s in targets[t]], provider.source)
    for index, ticker in enumerate(due):
        if budget is not None and not budget.allows(ticker):
            out["deferred"] = len(due) - index
            out["next_at"] = budget.next_slot(ticker)
            break
        since = _since(targets[ticker], newest, today)
        fetched = await _ask(session, provider, key=key, ticker=ticker, since=since, purpose="bars",
                             checkpoint=commit, now=now)
        if budget is not None:
            budget.spend(ticker)
        if fetched.outcome == TIMEOUT and (budget is None or budget.allows(ticker)):
            await commit()
            await sleep(TIMEOUT_RETRY_SECONDS)
            fetched = await _ask(session, provider, key=key, ticker=ticker, since=since, purpose="retry",
                                 checkpoint=commit, now=datetime.now(UTC) if checkpoint else now)
            if budget is not None:
                budget.spend(ticker)
        stats: dict = {"ticker": ticker, "outcome": fetched.outcome}
        if fetched.outcome == OK:
            try:
                stats.update(await refresh_ticker(session, provider, ticker, targets[ticker], fetched.bars, today))
                await commit()
            except Exception as exc:  # noqa: BLE001 - contain per ticker
                error = describe_exception(exc)
                log.error("price refresh failed for %s: %s", ticker, error, exc_info=True)
                await session.rollback()
                stats = {"ticker": ticker, "outcome": ERROR, "error": error}
        else:
            stats["error"] = fetched.outcome
            await commit()
        out["tickers"][ticker] = stats
        if "stale" in stats:
            out["stale"].append(ticker)
            log.warning("%s: newest close %s is over a week old; renamed or delisted?", ticker, stats["stale"])
        if fetched.outcome in REFUSALS or fetched.outcome == OFFLINE:
            out["deferred"] = len(due) - index - 1
            if fetched.outcome == RATE_LIMITED:
                wait = timedelta(seconds=fetched.retry_after) if fetched.retry_after else RATE_LIMIT_WAIT
                out["retry_at"] = out["next_at"] = now + wait
                out["refused"] = RATE_LIMITED
            elif fetched.outcome == UNAUTHORIZED:
                out["refused"] = UNAUTHORIZED
            log.warning("price feed stopped at %s: %s; the rest wait", ticker, fetched.outcome)
            break
    if out["next_at"] is None and out["refused"] is None:
        out["next_at"] = _next_due(targets, await _histories(session, provider.source, list(targets)), now)
    if provider.metered:
        await prune_ledger(session, now)
        await commit()
    return out


def _next_due(targets: dict[str, list[str]], histories: dict[str, History], now: datetime) -> datetime | None:
    """The soonest a ticker falls due again (its refresh window or its backoff)."""
    moments = [h.due_at() for t in targets if (h := histories.get(t)) is not None]
    later = [m for m in moments if m is not None and m > now]
    return min(later) if later else None


def run_summary(result: dict) -> dict:
    """What a run did, for its derivation row, the Settings card and the job."""
    tickers = result["tickers"].values()
    return {
        "priced": sum(1 for t in tickers if t.get("quote")),
        "failed": sum(1 for t in tickers if "error" in t),
        "due": result["due"],
        "deferred": result["deferred"],
        "stale": result["stale"],
        "refused": result["refused"],
        "retry_at": _stamp(result.get("retry_at")),
        "next_at": _stamp(result.get("next_at")),
    }


def _stamp(at: object) -> object:
    return at.isoformat() if isinstance(at, datetime) else at


async def run_refresh(session: AsyncSession, settings: Settings, slugs: list[str] | None = None) -> dict:
    """The whole refresh, as the job and the CLI run it: the prices lock for the
    run, the saved key, a commit per reserved request and per ticker. A run that
    finds the lock held does nothing and says so."""
    key, _origin = await api_key(session, settings)
    if key is None:
        return {"skipped": "no_key"}
    provider = get_price_provider(settings, api_key=key)
    state = await session.get(DerivationState, PRICES_PASS)
    detail = state.detail if state is not None and isinstance(state.detail, dict) else {}
    retry_at = _parse_at(detail.get("retry_at"))
    async with _engine(session).connect() as holder:
        locked = await holder.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": PRICES_LOCK_KEY})
        await holder.commit()
        if not locked:
            return {"skipped": "busy"}
        try:
            result = await refresh_prices(
                session, provider, slugs, key=key, limits=Limits.of(settings),
                checkpoint=session.commit, retry_at=retry_at,
            )
        finally:
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": PRICES_LOCK_KEY})
            await holder.commit()
    return run_summary(result)


def _engine(session: AsyncSession) -> AsyncEngine:
    """The engine behind a session, for the lock's own connection: a session
    lock taken on the session's connection would go back to the pool with it."""
    bind = session.bind
    return bind if isinstance(bind, AsyncEngine) else bind.engine


def _parse_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


#: A key check that sent nothing: no priced company, no budget left, or the
#: prices lock still held by a run that is stopping.
UNCHECKED = "unchecked"


async def check_key(
    session: AsyncSession, settings: Settings, key: str, *, wait_seconds: float = 5.0,
    now: datetime | None = None, provider: PriceProvider | None = None,
) -> str:
    """The first request a new key makes, and its outcome.

    Not a probe: it asks for the first due ticker's bars, as the refresh would,
    so it proves the key and stores a price in one request. Reserved in the
    ledger like every other request, under the prices lock (waiting up to
    `wait_seconds` for a run being stopped to let go of it)."""
    now = now or datetime.now(UTC)
    provider = provider or get_price_provider(settings, api_key=key)
    async with _engine(session).connect() as holder:
        waited = 0.0
        while not await holder.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": PRICES_LOCK_KEY}):
            if waited >= wait_seconds:
                await holder.commit()
                return UNCHECKED
            await asyncio.sleep(0.25)
            waited += 0.25
        await holder.commit()
        try:
            targets = await priced_targets(session)
            histories = await _histories(session, provider.source, list(targets))
            followed = await _followed(session, [s for group in targets.values() for s in group])
            order = order_tickers(targets, histories, followed, now) or sorted(targets)
            if not order:
                return UNCHECKED
            ticker = order[0]
            budget = await read_budget(session, now, Limits.of(settings))
            if provider.metered and not budget.allows(ticker):
                return UNCHECKED
            newest = await _newest_bars(session, targets[ticker], provider.source)
            fetched = await _ask(
                session, provider, key=key, ticker=ticker, since=_since(targets[ticker], newest, now.date()),
                purpose="check", checkpoint=session.commit, now=now,
            )
            if fetched.outcome == OK:
                await refresh_ticker(session, provider, ticker, targets[ticker], fetched.bars, now.date())
            await session.commit()
            return fetched.outcome
        finally:
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": PRICES_LOCK_KEY})
            await holder.commit()


# --- the key the user saved in Settings ----------------------------------------


async def saved_api_key(session: AsyncSession) -> str | None:
    row = await session.get(AppSetting, PRICE_FEED_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    key = unseal_or_none(value.get("api_key")) if isinstance(value.get("api_key"), str) else None
    return key or None


async def save_api_key(session: AsyncSession, key: str | None) -> None:
    """Write the key, sealed (`platform.secrets`), or clear it with None.
    Write-only: no read returns it. `saved_at` lets the card drop what an
    earlier key's last run said."""
    value = {"api_key": seal(key), "saved_at": datetime.now(UTC).isoformat()} if key else {}
    stmt = pg_insert(AppSetting).values(key=PRICE_FEED_KEY, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    await session.execute(stmt)


async def reseal_api_key(session: AsyncSession) -> None:
    """Seal a key saved before sealing existed, keeping its `saved_at`: the card
    reads that to tell what an earlier key's run said, and resealing is not a
    new key."""
    row = await session.get(AppSetting, PRICE_FEED_KEY)
    if row is None or not isinstance(row.value, dict) or not isinstance(row.value.get("api_key"), str):
        return
    value = {**row.value, "api_key": seal(row.value["api_key"])}
    stmt = pg_insert(AppSetting).values(key=PRICE_FEED_KEY, value=value)
    await session.execute(stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value}))


async def api_key(session: AsyncSession, settings: Settings) -> tuple[str | None, str | None]:
    """(key, where it came from): the one saved in Settings wins over the
    environment's `ROLEBAND_TIINGO_API_KEY`; (None, None) when neither has one."""
    if key := await saved_api_key(session):
        return key, "settings"
    if settings.tiingo_api_key:
        return settings.tiingo_api_key, "environment"
    return None, None


async def feed_status(session: AsyncSession, settings: Settings) -> dict:
    """The Settings card: whether a key is set and where from, how many companies
    have a live price and the newest close, and what the last run said."""
    _key, origin = await api_key(session, settings)
    priced_count, newest = (
        await session.execute(
            select(func.count(CompanyPrice.company_slug), func.max(CompanyPrice.as_of)).where(
                CompanyPrice.source == TIINGO_SOURCE
            )
        )
    ).one()
    state = await session.get(DerivationState, PRICES_PASS)
    detail = state.detail if state is not None and isinstance(state.detail, dict) else {}
    row = await session.get(AppSetting, PRICE_FEED_KEY)
    saved_at = _parse_at(row.value.get("saved_at")) if row is not None and isinstance(row.value, dict) else None
    current = state is not None and (saved_at is None or (state.last_run_at and state.last_run_at >= saved_at))
    return {
        "configured": origin is not None,
        "origin": origin,
        "priced": int(priced_count or 0),
        "as_of": newest,
        "last_run_at": state.last_run_at if state is not None else None,
        # What the last run said belongs to the key it ran with: a key saved
        # since then has not been refused by anyone yet.
        "refused": detail.get("refused") if current else None,
        "waiting": int(detail.get("deferred") or 0) if current else 0,
        "next_at": _parse_at(detail.get("next_at")) if current else None,
    }


#: Who to credit for the prices a chart shows, by the source its stored bars carry.
ATTRIBUTIONS = {TIINGO_SOURCE: ATTRIBUTION_TIINGO, FIXTURE_SOURCE: ATTRIBUTION_FIXTURE}


async def shown_attribution(session: AsyncSession, slug: str) -> str | None:
    """The credit for a company's stored prices, from its newest bar's source; None
    when it has none. Never the configured provider's: with no key that is the
    offline sample, which would be credited under a chart that shows nothing."""
    source = (
        await session.execute(
            select(CompanyPriceBar.source)
            .where(CompanyPriceBar.company_slug == slug)
            .order_by(CompanyPriceBar.date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ATTRIBUTIONS.get(source) if source else None


# --- read helpers (API) ---------------------------------------------------


async def latest_price_map(
    session: AsyncSession, slugs: list[str] | None = None
) -> dict[str, dict]:
    """{slug: {price, change_abs, change_pct, currency, as_of, ticker}} for the summary."""
    q = select(CompanyPrice)
    if slugs:
        q = q.where(CompanyPrice.company_slug.in_(slugs))
    rows = (await session.execute(q)).scalars().all()
    return {
        r.company_slug: {
            "ticker": r.ticker,
            "price": float(r.price),
            "currency": r.currency,
            "change_abs": float(r.change_abs) if r.change_abs is not None else None,
            "change_pct": r.change_pct,
            "as_of": r.as_of.isoformat(),
        }
        for r in rows
    }


async def price_history(
    session: AsyncSession, slug: str, since: date
) -> list[dict]:
    """Ascending daily bars for one company since `since`."""
    rows = (
        await session.execute(
            select(CompanyPriceBar)
            .where(
                CompanyPriceBar.company_slug == slug,
                CompanyPriceBar.date >= since,
            )
            .order_by(CompanyPriceBar.date.asc())
        )
    ).scalars().all()
    return [
        {
            "date": r.date.isoformat(),
            "open": float(r.open) if r.open is not None else None,
            "high": float(r.high) if r.high is not None else None,
            "low": float(r.low) if r.low is not None else None,
            "close": float(r.close),
            "volume": r.volume,
        }
        for r in rows
    ]
