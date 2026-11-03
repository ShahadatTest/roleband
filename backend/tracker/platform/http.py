"""Shared async HTTP: uniform client construction + paced retry/backoff.

One place for ``httpx.AsyncClient`` setup. Call sites keep their exact
semantics by passing timeout/headers/redirect policy explicitly —
``make_client`` defaults mirror httpx defaults except for the timeout, which
must be chosen deliberately.

One place for retry, too. Every fetch tier is an httpx transport under
``request_with_retry`` or ``stream_with_retry``, and both loops take each
decision (retry or not, how long to wait, what a ``Retry-After`` means, what
the breaker records) from ``_Attempts`` and the backoff functions, so no
transport has its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from tracker.platform.breaker import CircuitBreaker
from tracker.platform.clock import SourceClock, deadline_of
from tracker.platform.ratelimit import RateLimiter
from tracker.platform.transport_tally import note_bytes, note_response, note_retry

logger = logging.getLogger(__name__)

#: Adapter-grade default: patient reads, bounded connects.
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=15.0)

#: Transport failures worth another attempt: the request never got an answer,
#: and nothing about the failure says the next attempt would fare the same.
#:
#: Named by *base class* on purpose. Listing `ConnectError`, `ReadTimeout` and
#: `RemoteProtocolError` reads like the full set and is not: `ReadError` is a
#: sibling of `ConnectError` under `NetworkError`, not a subclass, and
#: `ConnectTimeout` sits under `TimeoutException` rather than under
#: `ConnectError`.
#:
#: One physical event can arrive as either class. A server that caps an HTTP/2
#: connection's streams sends GOAWAY, which surfaces as `RemoteProtocolError`,
#: or, observed as a socket EOF, as `ReadError`. Retryability must not depend
#: on which of two names httpcore happens to raise.
#:
#: Excluded, and deliberately: `ProxyError`, `UnsupportedProtocol`,
#: `LocalProtocolError` and `InvalidURL` are all faults in the request we built
#: or the environment we run in. Retrying those is just the same mistake again.
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.TimeoutException,  # Connect/Read/Write/Pool timeouts
    httpx.NetworkError,  # Connect/Read/Write/Close errors
    httpx.RemoteProtocolError,
)


def make_client(
    *,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    follow_redirects: bool = False,
    http2: bool = False,
) -> httpx.AsyncClient:
    """Uniform ``httpx.AsyncClient`` construction for all tracker HTTP."""
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout),
        follow_redirects=follow_redirects,
        http2=http2,
    )


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff on retryable statuses/transport errors.

    ``Retry-After`` (integer seconds) is honored on retryable statuses.
    Backoff is ``min(2**attempt, max_backoff)`` seconds otherwise.
    """

    max_retries: int = 3
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)
    max_backoff: float = 30.0
    #: Statuses that mean "the backend is refusing us", not "try again" and not
    #: "here is your answer". Never retried — a second identical request will be
    #: refused identically — but they must not read as success either: 403 is
    #: the most common WAF block, and treated as a normal answer it would leave
    #: a 403-blocking source invisible to the breaker.
    refusal_statuses: tuple[int, ...] = (401, 403, 407, 451)


def _retry_after(headers: httpx.Headers) -> str:
    """The ``Retry-After`` value, stripped, or ``""`` when there is none.

    The one reading of the header for both of its uses: the wait, and whether
    the backend told us when to come back (which keeps the request out of the
    breaker's block signature). An empty value names no time, so it counts
    as no header for both.
    """
    return (headers.get("Retry-After") or "").strip()


def backoff_for_transport_error(attempt: int, retry: RetryPolicy) -> float:
    """Seconds to wait after a transport failure: exponential, capped."""
    return min(2**attempt, retry.max_backoff)


def backoff_for_status(headers: httpx.Headers, attempt: int, retry: RetryPolicy) -> float:
    """Seconds to wait after a retryable status.

    An integer ``Retry-After`` wins over exponential backoff. The HTTP-date form
    falls back to exponential rather than guessing a clock.

    ``Retry-After`` is capped at ``max_backoff``: an uncapped header is a remote
    party choosing how long *our* process blocks, and a ``Retry-After: 3600``
    is a literal one-hour sleep on any path without a deadline. Capping keeps
    the signal (back off now) without ceding the bound.
    """
    retry_after = _retry_after(headers)
    if retry_after.isdigit():
        return min(float(retry_after), retry.max_backoff)
    return backoff_for_transport_error(attempt, retry)


class RetryDeadlineExceeded(Exception):
    """A retry was still due, but the caller's deadline left no room to sleep.

    Distinct from a cancellation: raising lets the *caller* unwind normally and
    keep whatever it has already collected. ``asyncio.wait_for`` cancels the
    coroutine and discards its return value even when the inner code suppresses
    the cancel, so a slow source cut that way would take its partial data down
    with it.
    """


def deadline_allows(deadline: float | SourceClock | None, backoff: float) -> bool:
    """Whether sleeping ``backoff`` seconds still fits inside ``deadline``.

    ``deadline`` is a ``time.monotonic()`` timestamp, a `SourceClock` whose
    effective deadline slides as the source makes progress, or ``None`` for
    unbounded. Resolving here keeps every consult point agnostic about which
    form it was handed.
    """
    if isinstance(deadline, SourceClock):
        # Ask the clock, not the wall: its time source is injectable, so reading
        # `time.monotonic()` here would compare two different timelines.
        return deadline.allows(backoff)
    if deadline is None:
        return True
    return time.monotonic() + backoff <= deadline


def _note_progress(deadline: float | SourceClock | None) -> None:
    """Record completed work against a sliding deadline; no-op otherwise.

    Called after a response arrives and after any *deliberate* wait (pacing,
    backoff). Time we chose to spend is not silence — without this a source
    politely obeying ``Retry-After`` would be judged dead for good behavior.
    """
    if isinstance(deadline, SourceClock):
        deadline.progress()


def _clip_timeout(
    deadline: float | SourceClock | None, timeout: httpx.Timeout | None
) -> httpx.Timeout | None:
    """Shrink a request timeout so one ``await`` cannot outlive the deadline.

    The cooperative deadline check runs *between* awaits, so it can never
    interrupt a request already in flight. Left unclipped, a 30s read against a
    90s stall window lets a hung source hold the slot well past its bound.
    """
    if isinstance(deadline, SourceClock):
        remaining = deadline.remaining()
    else:
        resolved = deadline_of(deadline)
        if resolved is None:
            return timeout
        remaining = max(0.0, resolved - time.monotonic())
    base = timeout or DEFAULT_TIMEOUT
    return httpx.Timeout(
        min(base.read or remaining, remaining),
        connect=min(base.connect or remaining, remaining),
        write=min(base.write or remaining, remaining),
        pool=min(base.pool or remaining, remaining),
    )


def _body_size(resp: httpx.Response) -> int:
    """Bytes the response body took on the wire, or its decoded length when
    the transport did not count them (a mocked response); 0 for a streamed
    body the caller never read."""
    if resp.num_bytes_downloaded:
        return resp.num_bytes_downloaded
    try:
        return len(resp.content)
    except httpx.ResponseNotRead:
        return 0


class _Attempts:
    """One request's retry decisions, for both retry loops.

    Each attempt's outcome comes here: the answer is the seconds to wait before
    the next attempt, or ``None`` when the request is over, by which point the
    breaker has recorded it. The loops keep only what differs between them:
    sending, sleeping, and closing a stream.
    """

    def __init__(self, retry: RetryPolicy, breaker: CircuitBreaker | None) -> None:
        self._retry = retry
        self._breaker = breaker
        self._attempt = 0
        # Set when something during THIS request proves the backend is
        # responsive (a transport error, or a Retry-After); it downgrades the
        # terminal status from block evidence to a plain failure.
        self._signature_broken = False

    def after_transport_error(self) -> float | None:
        """The wait before retrying, or ``None`` when the error should propagate."""
        # The backend never answered, so this request can never be evidence
        # of a uniform refusal.
        self._signature_broken = True
        if self._attempt >= self._retry.max_retries:
            if self._breaker is not None:
                self._breaker.record_request_failure()
            return None
        backoff = backoff_for_transport_error(self._attempt, self._retry)
        self._attempt += 1
        return backoff

    def after_response(self, resp: httpx.Response) -> float | None:
        """The wait before retrying, or ``None`` when ``resp`` is the answer."""
        if _retry_after(resp.headers):
            # A backend that tells us WHEN to come back is pacing us, not
            # stonewalling. That disqualifies the whole request as block
            # evidence, however many identical statuses follow.
            self._signature_broken = True
        retryable = resp.status_code in self._retry.retry_statuses
        if retryable and self._attempt < self._retry.max_retries:
            backoff = backoff_for_status(resp.headers, self._attempt, self._retry)
            self._attempt += 1
            return backoff
        if self._breaker is not None:
            if retryable or resp.status_code in self._retry.refusal_statuses:
                # Retryable-and-exhausted, or refused outright. Either way the
                # request failed; the status is block evidence only if nothing
                # during the request disqualified it.
                self._breaker.record_request_failure(
                    None if self._signature_broken else resp.status_code
                )
            else:
                self._breaker.record_success()
        return None


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry: RetryPolicy,
    limiter: RateLimiter | None = None,
    breaker: CircuitBreaker | None = None,
    deadline: float | SourceClock | None = None,
    log_name: str = "http",
    **kwargs,
) -> httpx.Response:
    """Paced request with exponential backoff on retryable failures.

    The limiter (when given) paces every attempt, transport errors and
    retryable statuses back off exponentially, ``Retry-After`` digits win.

    Two bounds are optional and both fail fast rather than sleeping:
    ``breaker`` refuses to send once its scope has failed ``threshold``
    *requests* in a row, and ``deadline`` (a ``time.monotonic()`` timestamp)
    stops retrying once a backoff would run past it. The breaker's unit is the
    REQUEST: a retryable status that exhausts ``max_retries`` counts once, even
    though that response is still returned to the caller; otherwise a source
    that 429s every page would reset nothing and trip nothing. A refusal status
    is never retried but counts the same way, since a 403 WAF is refusing us
    just as surely as a 429 one. If anything during the request (a transport
    error, a ``Retry-After``) proves the backend is responsive, the terminal
    status is passed as ``None`` and cannot accumulate toward a block.

    When ``deadline`` is a `SourceClock`, this loop also feeds it: a received
    response and every deliberate wait count as progress, so the sliding stall
    bound measures silence rather than work. Only *completed* responses count —
    issuing a request does not — so a source failing every attempt still stalls.
    """
    attempts = _Attempts(retry, breaker)
    while True:
        if breaker is not None:
            breaker.check()
        if not deadline_allows(deadline, 0):
            raise RetryDeadlineExceeded(f"{log_name}: deadline reached before request")
        if limiter is not None:
            await limiter.wait()
            # Pacing is time we chose to spend; it must not read as silence.
            _note_progress(deadline)
        try:
            resp = await client.request(
                method, url, **{**kwargs, "timeout": _clip_timeout(deadline, kwargs.get("timeout"))}
            )
            note_response(_body_size(resp), resp.headers)
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            backoff = attempts.after_transport_error()
            if backoff is None:
                raise
            if not deadline_allows(deadline, backoff):
                raise RetryDeadlineExceeded(
                    f"{log_name}: transport error, no time left to retry ({exc})"
                ) from exc
            logger.warning("%s transport error (%s); retry in %ss", log_name, exc, backoff)
            await asyncio.sleep(backoff)
            _note_progress(deadline)
            note_retry()
            continue

        backoff = attempts.after_response(resp)
        if backoff is None:
            # A response in hand is the progress signal, breaker or not: keying
            # it on `record_success` would skip every path that passes no breaker.
            _note_progress(deadline)
            return resp
        if not deadline_allows(deadline, backoff):
            raise RetryDeadlineExceeded(
                f"{log_name}: got {resp.status_code}, no time left to back off"
            )
        logger.warning("%s got %s; backing off %ss", log_name, resp.status_code, backoff)
        await asyncio.sleep(backoff)
        _note_progress(deadline)
        note_retry()


@asynccontextmanager
async def stream_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry: RetryPolicy,
    limiter: RateLimiter | None = None,
    breaker: CircuitBreaker | None = None,
    deadline: float | SourceClock | None = None,
    log_name: str = "http",
    **kwargs,
) -> AsyncIterator[httpx.Response]:
    """``request_with_retry`` for streamed downloads.

    Retry/backoff applies to opening the stream (status line + headers,
    ``Retry-After`` honored); once a non-retryable status arrives the response
    is yielded with its body still streamable, and closed on exit. ``breaker``
    and ``deadline`` behave exactly as in ``request_with_retry``: both loops
    take every retry and breaker decision from the same ``_Attempts``.
    """
    attempts = _Attempts(retry, breaker)
    while True:
        if breaker is not None:
            breaker.check()
        if not deadline_allows(deadline, 0):
            raise RetryDeadlineExceeded(f"{log_name}: deadline reached before request")
        if limiter is not None:
            await limiter.wait()
            _note_progress(deadline)
        stream_cm = client.stream(
            method, url, **{**kwargs, "timeout": _clip_timeout(deadline, kwargs.get("timeout"))}
        )
        try:
            resp = await stream_cm.__aenter__()
            note_response(0, resp.headers)
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            backoff = attempts.after_transport_error()
            if backoff is None:
                raise
            if not deadline_allows(deadline, backoff):
                raise RetryDeadlineExceeded(
                    f"{log_name}: transport error, no time left to retry ({exc})"
                ) from exc
            logger.warning("%s transport error (%s); retry in %ss", log_name, exc, backoff)
            await asyncio.sleep(backoff)
            _note_progress(deadline)
            note_retry()
            continue

        backoff = attempts.after_response(resp)
        if backoff is None:
            _note_progress(deadline)
            try:
                yield resp
                return
            finally:
                note_bytes(_body_size(resp))
                await stream_cm.__aexit__(None, None, None)
        await stream_cm.__aexit__(None, None, None)
        if not deadline_allows(deadline, backoff):
            raise RetryDeadlineExceeded(
                f"{log_name}: got {resp.status_code}, no time left to back off"
            )
        logger.warning("%s got %s; backing off %ss", log_name, resp.status_code, backoff)
        await asyncio.sleep(backoff)
        _note_progress(deadline)
        note_retry()
