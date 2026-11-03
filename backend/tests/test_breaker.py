"""Per-scope circuit breaking.

The failure this exists to stop: a source answers 429 to every job page, each
page burns 1/2/4/8s of backoff, and nothing counts the streak, so a single
throttled source consumes the run's entire 3600s budget.

Three semantics pinned here:

* the failure unit is the REQUEST — under a per-attempt unit, `threshold=5`
  equals `max_retries+1`, so the first request that exhausts its retries
  opens the circuit and one 429 storm on page 3 of 100 condemns the
  remaining 97 pages;
* an open circuit admits a half-open probe after a cooldown, so one company's
  bad stretch does not condemn every later company on the same backend;
* a WAF-style uniform refusal (identical status, no Retry-After, across two
  full requests) opens the circuit as `blocked` — no probes, because backoff
  against a WAF that has decided can never succeed.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from tracker.connectors.runtime.tiers import CurlHttpxTransport
from tracker.platform.breaker import BreakerPool, CircuitBreaker, CircuitOpenError
from tracker.platform.http import RetryPolicy, request_with_retry, stream_with_retry


class CountingSession:
    """Records every request actually issued, and answers a fixed status."""

    def __init__(self, status: int = 429, headers: dict | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.calls: list[str] = []

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append(url)
        return SimpleNamespace(
            status_code=self.status,
            headers=self.headers,
            content=b"",
            url=url,
        )


def _curl_client(session: CountingSession) -> httpx.AsyncClient:
    """The TLS tier's client: httpx over a (stub) curl session."""
    return httpx.AsyncClient(transport=CurlHttpxTransport(lambda: session))


class TlsTier:
    """`request_with_retry` over the TLS tier, one request per `send`."""

    def __init__(self, session: CountingSession, *, breaker: CircuitBreaker, retry: RetryPolicy) -> None:
        self._client = _curl_client(session)
        self._breaker = breaker
        self._retry = retry

    async def send(self, url: str = "https://example.test/job/1") -> httpx.Response:
        return await request_with_retry(
            self._client, "GET", url, retry=self._retry, breaker=self._breaker
        )


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _exhausted_request(breaker: CircuitBreaker, *, status: int | None = 429) -> None:
    """One request that failed as a whole.

    `status=None` is what a transport carrying a transport error or a
    `Retry-After` passes: still a failed request, but not block evidence.
    """
    breaker.record_request_failure(status)


# -- the primitive: request unit -------------------------------------------- #


def test_breaker_opens_only_after_threshold_exhausted_requests():
    breaker = CircuitBreaker(threshold=3, scope="acme")

    # status=None: each request was paced by a Retry-After, i.e. congestion.
    _exhausted_request(breaker, status=None)
    _exhausted_request(breaker, status=None)
    assert breaker.is_open is False

    _exhausted_request(breaker, status=None)
    assert breaker.is_open is True
    assert breaker.blocked is False  # ordinary congestion, not a block


def test_a_request_that_recovers_on_a_later_attempt_contributes_nothing():
    """The request unit: retries inside one request are invisible to the
    streak. Under a per-attempt unit, four failed attempts plus one more
    would already have opened the circuit."""
    breaker = CircuitBreaker(threshold=5, scope="acme")

    breaker.record_success()  # the request as a whole succeeded

    assert breaker.failures == 0
    assert breaker.is_open is False


def test_success_resets_the_streak_so_intermittent_pressure_never_trips_it():
    breaker = CircuitBreaker(threshold=3, scope="acme")

    for _ in range(2):
        _exhausted_request(breaker, status=None)
    breaker.record_success()
    for _ in range(2):
        _exhausted_request(breaker, status=None)

    # 4 failed requests total, but never 3 in a row.
    assert breaker.is_open is False


def test_check_raises_once_open_and_names_the_scope():
    breaker = CircuitBreaker(threshold=1, scope="meta")
    breaker.check()  # closed: no raise

    _exhausted_request(breaker)
    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.check()

    assert excinfo.value.scope == "meta"
    assert excinfo.value.blocked is False
    assert "meta" in str(excinfo.value)


# -- half-open recovery ------------------------------------------------------ #


def test_cooldown_admits_one_probe_and_a_success_closes_the_circuit():
    clock = _Clock()
    breaker = CircuitBreaker(threshold=1, scope="acme", cooldown_seconds=60, clock=clock)
    _exhausted_request(breaker, status=None)

    with pytest.raises(CircuitOpenError):
        breaker.check()  # still cooling down

    clock.now = 61.0
    breaker.check()  # the probe is admitted, no raise
    breaker.record_success()

    assert breaker.is_open is False
    assert breaker.failures == 0


def test_failed_probe_reopens_with_a_doubled_cooldown():
    clock = _Clock()
    breaker = CircuitBreaker(threshold=1, scope="acme", cooldown_seconds=60, clock=clock)
    _exhausted_request(breaker, status=None)

    clock.now = 61.0
    breaker.check()  # probe admitted
    _exhausted_request(breaker, status=None)  # probe failed

    # Reopened: the old cooldown is not enough any more...
    clock.now = 61.0 + 60.0
    with pytest.raises(CircuitOpenError):
        breaker.check()
    # ...the doubled one is.
    clock.now = 61.0 + 120.0
    breaker.check()


def test_probe_retry_attempts_are_admitted_while_half_open():
    """The probe request's own retry attempts must not be refused mid-flight —
    check() is called at the top of every attempt, not once per request."""
    clock = _Clock()
    breaker = CircuitBreaker(threshold=1, scope="acme", cooldown_seconds=10, clock=clock)
    _exhausted_request(breaker, status=None)

    clock.now = 11.0
    breaker.check()  # probe attempt 1
    clock.now = 12.0
    breaker.check()  # probe attempt 2 — still admitted, still inside the probe
    breaker.record_success()

    assert breaker.is_open is False


# -- blocked: a WAF is not congestion ---------------------------------------- #


def test_uniform_refusal_across_two_requests_opens_as_blocked():
    """Identical immediate refusals without Retry-After across two full requests
    indicate a block rather than congestion."""
    breaker = CircuitBreaker(threshold=5, scope="meta", blocked_threshold=3)

    for _ in range(2):
        _exhausted_request(breaker)
    assert breaker.blocked is False

    _exhausted_request(breaker)
    assert breaker.blocked is True
    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.check()
    assert excinfo.value.blocked is True
    assert "blocked" in str(excinfo.value)


def test_blocked_admits_no_probe_no_matter_how_long_the_cooldown():
    clock = _Clock()
    breaker = CircuitBreaker(
        threshold=5, scope="meta", cooldown_seconds=1, blocked_threshold=2, clock=clock
    )
    _exhausted_request(breaker)
    _exhausted_request(breaker)

    clock.now = 10_000.0
    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.check()
    assert excinfo.value.blocked is True


@pytest.mark.parametrize(
    "breaking_signal",
    [
        pytest.param(lambda b: b.record_request_failure(None), id="retry-after-or-transport-error"),
        pytest.param(lambda b: b.record_request_failure(503), id="status-change"),
        pytest.param(lambda b: b.record_success(), id="success"),
    ],
)
def test_any_non_uniform_signal_breaks_the_blocked_signature(breaking_signal):
    """A politely throttling backend can never be misread as a block."""
    breaker = CircuitBreaker(threshold=50, scope="acme", blocked_threshold=4)

    for _ in range(3):
        _exhausted_request(breaker)
    breaking_signal(breaker)
    for _ in range(3):
        _exhausted_request(breaker)

    assert breaker.blocked is False


def test_a_new_pool_reprobes_so_even_blocked_is_never_a_lockout():
    scope = "meta"
    old_pool = BreakerPool()
    tripped = old_pool.get(scope, 5, blocked_threshold=2)
    _exhausted_request(tripped)
    _exhausted_request(tripped)
    assert tripped.blocked is True

    # Breaker state is run-scoped: the next run builds a new pool.
    fresh = BreakerPool().get(scope, 5, blocked_threshold=2)
    assert fresh.is_open is False
    fresh.check()


def test_pool_shares_one_breaker_per_scope_and_isolates_others():
    pool = BreakerPool()

    first = pool.get("greenhouse", 5)
    second = pool.get("greenhouse", 5)
    other = pool.get("ashby", 5)

    # Companies on one backend must share a breaker: pressure that backend
    # applies to one of them is evidence about all of them.
    assert first is second
    assert other is not first


# -- wired into a transport ------------------------------------------------- #


@pytest.mark.asyncio
async def test_transport_stops_issuing_requests_once_the_circuit_opens():
    """The assertion that matters: no further bytes go to a source saying stop."""
    session = CountingSession(status=429, headers={"Retry-After": "0"})
    breaker = CircuitBreaker(threshold=3, scope="meta")
    transport = TlsTier(
        session,
        breaker=breaker,
        retry=RetryPolicy(max_retries=2, max_backoff=0),
    )

    # Three sends, each exhausting its retries -> 3 request failures.
    for n in range(3):
        await transport.send(f"https://example.test/job/{n}")
    assert breaker.failures == 3
    assert breaker.is_open is True

    issued_before = len(session.calls)
    with pytest.raises(CircuitOpenError):
        await transport.send("https://example.test/job/next")

    assert len(session.calls) == issued_before  # nothing was sent


@pytest.mark.asyncio
async def test_one_exhausted_request_is_one_failure_not_a_tripped_circuit():
    """The request unit through a real transport: one request that burns all
    its retries must count ONCE — under a per-attempt unit its 3 attempts land
    3 failures and a threshold-3 breaker is already open, which is how a
    single 429 storm kills a 100-page source."""
    session = CountingSession(status=429, headers={"Retry-After": "0"})
    breaker = CircuitBreaker(threshold=3, scope="meta")
    transport = TlsTier(
        session,
        breaker=breaker,
        retry=RetryPolicy(max_retries=2, max_backoff=0),
    )

    await transport.send()

    assert len(session.calls) == 3  # initial + 2 retries
    assert breaker.failures == 1
    assert breaker.is_open is False  # the next page still gets its chance


@pytest.mark.asyncio
async def test_uniform_429s_without_retry_after_block_the_source_mid_backoff():
    """Identical immediate 429s without Retry-After must open a blocked circuit.
    Remaining requests are refused without further backoff or network traffic."""
    session = CountingSession(status=429)  # no Retry-After header
    breaker = CircuitBreaker(threshold=5, scope="meta", blocked_threshold=2)
    transport = TlsTier(
        session,
        breaker=breaker,
        retry=RetryPolicy(max_retries=4, max_backoff=0),
    )

    await transport.send()                              # request 1 gives up
    await transport.send("https://example.test/job/2")  # request 2 -> blocked
    assert breaker.blocked is True

    issued_before = len(session.calls)
    with pytest.raises(CircuitOpenError) as excinfo:
        await transport.send("https://example.test/job/3")
    assert excinfo.value.blocked is True
    assert len(session.calls) == issued_before  # nothing further touched the network


@pytest.mark.asyncio
async def test_a_good_response_resets_the_streak_through_the_transport():
    session = CountingSession(status=200)
    breaker = CircuitBreaker(threshold=2, scope="acme")
    _exhausted_request(breaker)
    transport = TlsTier(session, breaker=breaker, retry=RetryPolicy())

    response = await transport.send()

    assert response.status_code == 200
    assert breaker.failures == 0


@pytest.mark.asyncio
async def test_a_non_retryable_error_status_does_not_trip_the_breaker():
    """A 404 is a fact about one URL, not the backend refusing us."""
    session = CountingSession(status=404)
    breaker = CircuitBreaker(threshold=1, scope="acme")
    transport = TlsTier(session, breaker=breaker, retry=RetryPolicy())

    await transport.send()
    await transport.send("https://example.test/job/2")

    assert breaker.is_open is False
    assert len(session.calls) == 2


# -- a refusal is not a success ----------------------------------- #


@pytest.mark.asyncio
async def test_a_403_wall_trips_the_breaker_instead_of_reading_as_success():
    """403 is the most common WAF block, and it is not in `retry_statuses`.

    A non-retryable status that fell through to `record_success()` would let
    a source that answers 403 to everything take request
    after request with the breaker sitting at zero.
    """
    session = CountingSession(status=403)
    breaker = CircuitBreaker(threshold=5, scope="tesla", blocked_threshold=2)
    transport = TlsTier(
        session, breaker=breaker, retry=RetryPolicy(max_retries=4, max_backoff=0)
    )

    await transport.send()
    await transport.send("https://example.test/job/2")

    # Never retried (a second identical 403 would be refused identically), so
    # two requests are two attempts — and two identical refusals are a block.
    assert session.calls == ["https://example.test/job/1", "https://example.test/job/2"]
    assert breaker.blocked is True

    issued_before = len(session.calls)
    with pytest.raises(CircuitOpenError):
        await transport.send("https://example.test/job/3")
    assert len(session.calls) == issued_before


@pytest.mark.asyncio
async def test_an_interleaved_404_no_longer_erases_all_accumulated_pressure():
    """A 404 is a normal answer, so it still resets the streak — but it must
    not be the only thing standing between us and a blocked source.

    If every 404 cleared both the trip streak and the block signature, a
    source alternating 429/404 could issue request after request with the
    breaker never leaving zero. The 429 requests accumulate on their own.
    """
    session = CountingSession(status=429)
    breaker = CircuitBreaker(threshold=5, scope="meta", blocked_threshold=2)
    transport = TlsTier(
        session, breaker=breaker, retry=RetryPolicy(max_retries=1, max_backoff=0)
    )

    await transport.send()
    session.status = 404  # one stale sitemap entry
    await transport.send("https://example.test/job/2")
    assert breaker.failures == 0  # the 404 legitimately cleared the streak

    session.status = 429
    await transport.send("https://example.test/job/3")
    await transport.send("https://example.test/job/4")
    assert breaker.blocked is True  # two clean 429 requests are still a block


# -- one reading of Retry-After on every path -------------------------------- #


def _answering(path: str, status: int, headers: dict[str, str]) -> httpx.AsyncClient:
    if path == "curl":
        return _curl_client(CountingSession(status=status, headers=headers))
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, headers=headers))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["httpx", "curl"])
@pytest.mark.parametrize("loop", ["buffered", "streamed"])
@pytest.mark.parametrize(
    ("retry_after", "blocks", "wait"),
    [
        pytest.param("", True, 1.0, id="empty"),
        pytest.param("  ", True, 1.0, id="blank"),
        pytest.param("3", False, 3.0, id="seconds"),
        pytest.param(" 3 ", False, 3.0, id="padded-seconds"),
    ],
)
async def test_an_empty_retry_after_is_no_retry_after_on_every_path(
    path, loop, retry_after, blocks, wait, monkeypatch
):
    """An empty `Retry-After` names no time to come back: it neither sets the
    wait (exponential backoff applies) nor marks the backend as pacing us, so
    identical 429s carrying one are a block. A value does both. The httpx tiers
    and the curl-backed TLS tier, buffered or streamed, read it the same way."""
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("asyncio.sleep", record_wait)
    breaker = CircuitBreaker(threshold=5, scope="acme", blocked_threshold=2)
    retry = RetryPolicy(max_retries=1, max_backoff=30)

    async with _answering(path, 429, {"Retry-After": retry_after}) as client:
        for n in range(2):
            url = f"https://example.test/job/{n}"
            if loop == "buffered":
                response = await request_with_retry(client, "GET", url, retry=retry, breaker=breaker)
                assert response.status_code == 429
            else:
                async with stream_with_retry(client, "GET", url, retry=retry, breaker=breaker) as response:
                    assert response.status_code == 429

    assert waits == [wait, wait]  # one retry per request
    assert breaker.failures == 2
    assert breaker.blocked is blocks


def test_a_stalled_probe_cannot_leave_the_breaker_permanently_permissive():
    """`check()` returns early in half-open so the probe's retries pass. If the
    probe then unwinds without reporting (its caller raised on a deadline), the
    breaker would admit everything forever. The probe is time-boxed instead."""
    clock = _Clock()
    breaker = CircuitBreaker(threshold=1, scope="acme", cooldown_seconds=30, clock=clock)
    _exhausted_request(breaker, status=None)

    clock.now = 31.0
    breaker.check()  # probe admitted, and then nothing is ever recorded

    clock.now = 31.0 + 30.0
    with pytest.raises(CircuitOpenError):
        breaker.check()  # the abandoned probe counts as failed, not as open season
