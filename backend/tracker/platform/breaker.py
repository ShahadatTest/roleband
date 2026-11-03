"""Per-scope circuit breaking for retryable backend pressure.

The problem this closes: a source answering 429 on every page is retried
1/2/4/8s *per page*, so hundreds of pages cost unbounded time and the run's only
ceiling is its global timeout. Backoff paces one request and never counts
the streak. A breaker does: after `threshold` consecutive failed requests on
one backend scope, further sends fail fast instead of sleeping.

Three semantics, each the fix for a defect a simpler breaker has:

* **The failure unit is the REQUEST, not the attempt.** Counted per attempt,
  `threshold=5` would equal `max_retries+1=5`, so the first request that
  exhausted its retries would open the circuit — one 429 storm on page 3 of 100
  would condemn the remaining 97 pages. A request that exhausts its retries counts
  once (`record_request_failure`); a request that recovers on a later attempt
  counts zero.
* **Half-open recovery.** An open circuit admits one probe request after
  `cooldown_seconds`; success closes it, failure re-opens it with the cooldown
  doubled. Without this, one company's bad stretch would condemn every later
  company sharing the backend scope for the rest of the run.
* **A block is not congestion.** A WAF that has decided against us answers the
  same retryable status to every attempt, instantly, with no `Retry-After` —
  backoff can never succeed, so every retry and every probe is pure cost. An
  unbroken run of failed *requests* ending in one identical status, none of
  which carried a `Retry-After`, opens the circuit as **blocked**: no probes,
  fail fast for the rest of the run. Any `Retry-After`, status change,
  transport error, or success breaks the signature — a politely throttling
  backend can never be misread as a block. Counting requests rather than
  attempts is what makes a never-retried 403 commensurable with a 429 that is
  retried five times; it also keeps the threshold independent of
  the transport's retry budget.

Deliberately run-scoped, mirroring `RateLimiterPool`: the pool lives as long as
one pipeline run, so the next run always re-probes a source that has recovered
— including a blocked one, which is why `blocked` needs no exit of its own.
Persisting open circuits across runs would be a lockout, which is a policy
decision belonging to the scheduler's provider pressure, not to a transport
primitive.

L0 by construction: this module imports nothing from `tracker`, so the
import-linter layer contract holds and any transport may depend on it.
"""

from __future__ import annotations

import time
from collections.abc import Callable

__all__ = ["BreakerPool", "CircuitBreaker", "CircuitOpenError"]

_CLOSED = "closed"
_OPEN = "open"
_HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised instead of issuing a request while a scope's circuit is open.

    Carries the scope and whether the circuit opened as a *block* (uniform
    refusal, no recovery inside this run) so the source-level error string can
    tell an operator "needs attention" from "was congested".
    """

    def __init__(self, scope: str, failures: int, *, blocked: bool = False) -> None:
        if blocked:
            message = (
                f"source blocked: {scope!r} refused {failures} consecutive requests with an "
                "identical status and no Retry-After — no further requests this run"
            )
        else:
            message = f"circuit open for {scope!r} after {failures} consecutive failed requests"
        super().__init__(message)
        self.scope = scope
        self.failures = failures
        self.blocked = blocked


class CircuitBreaker:
    """Consecutive-failure breaker for one backend scope.

    Failures reach this class only when the backend applied pressure (429/5xx,
    transport errors) or refused us outright (`RetryPolicy.refusal_statuses` —
    401/403/407/451). A 404 does not: it is a fact about one URL, and the server
    answered it normally. The transports own that classification; the breaker
    owns the streaks.

    State is a plain three-way machine (`closed` -> `open` -> `half_open`),
    consulted from a single serial collector stream per scope — that is the
    concurrency model `collect_sources` guarantees, so no locking is needed.
    """

    def __init__(
        self,
        threshold: int,
        scope: str = "default",
        *,
        cooldown_seconds: float = 60.0,
        blocked_threshold: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param threshold: consecutive *failed requests* before opening.
        :param cooldown_seconds: wait before admitting a half-open probe;
            doubles on every failed probe.
        :param blocked_threshold: consecutive failed *requests* that ended in
            one identical status with no `Retry-After` before opening as
            blocked. Counted per request, not per attempt, so the value does
            not silently depend on the transport's retry budget — and so a
            refusal that is never retried (403) is commensurable with a 429
            that is retried five times.
        :param clock: monotonic time source; injected in tests.
        """
        self._threshold = max(1, threshold)
        self._blocked_threshold = max(2, blocked_threshold)
        # A probe admitted by `check()` that never reported back would leave the
        # breaker permissive forever, since `check()` returns early in
        # half-open. Time-boxing the probe closes that hole.
        self._probe_started_at: float | None = None
        self.scope = scope
        self._cooldown = max(0.0, cooldown_seconds)
        self._clock = clock
        self._state = _CLOSED
        self._request_failures = 0
        self._opened_at: float | None = None
        self._blocked = False
        # Uniform-refusal signature: (status, consecutive count).
        self._signature_status: int | None = None
        self._signature_count = 0

    @property
    def failures(self) -> int:
        """Consecutive requests that exhausted their retries."""
        return self._request_failures

    @property
    def is_open(self) -> bool:
        return self._state != _CLOSED

    @property
    def blocked(self) -> bool:
        return self._blocked

    def record_request_failure(self, status: int | None = None) -> None:
        """One request that failed as a whole. The trip unit.

        `status` is the terminal status ONLY when the request is clean evidence
        of a uniform refusal: the caller passes `None` when the request hit a
        transport error or was told `Retry-After`, both of which mean the
        backend is talking to us rather than stonewalling. A `None` therefore
        breaks the block signature while still counting toward the trip streak.
        """
        self._request_failures += 1

        if status is None or status != self._signature_status:
            self._signature_status = status
            self._signature_count = 1 if status is not None else 0
        else:
            self._signature_count += 1

        if self._signature_count >= self._blocked_threshold:
            self._blocked = True
            self._state = _OPEN
            self._opened_at = self._clock()
            self._probe_started_at = None
            return

        if self._state == _HALF_OPEN:
            # The probe failed: back to open, and wait twice as long.
            self._cooldown *= 2
            self._state = _OPEN
            self._opened_at = self._clock()
            self._probe_started_at = None
        elif self._state == _CLOSED and self._request_failures >= self._threshold:
            self._state = _OPEN
            self._opened_at = self._clock()

    def record_success(self) -> None:
        """The backend answered normally. Note that a *refusal* status (403 and
        friends) must NOT come here — see `RetryPolicy.refusal_statuses`."""
        self._request_failures = 0
        self._signature_status = None
        self._signature_count = 0
        self._blocked = False
        self._state = _CLOSED
        self._opened_at = None
        self._probe_started_at = None

    def check(self) -> None:
        """Raise `CircuitOpenError` unless a request may be issued now.

        `half_open` admits the probe (and that probe's own retry attempts);
        `open` admits nothing until the cooldown elapses — or ever, when
        blocked: probing a WAF that has decided against us is pure cost, and
        the next run's fresh pool is the retry.
        """
        if self._state == _CLOSED:
            return
        if self._state == _HALF_OPEN:
            # A probe is in flight; its own retries must pass. But a probe that
            # never reports back (its caller unwound on a deadline rather than
            # calling record_*) would otherwise leave every later check() open.
            # Treat an over-long probe as failed rather than trusting it.
            if (
                self._probe_started_at is not None
                and self._clock() - self._probe_started_at >= self._cooldown
            ):
                self._cooldown *= 2
                self._state = _OPEN
                self._opened_at = self._clock()
                self._probe_started_at = None
                raise CircuitOpenError(self.scope, self._request_failures)
            return
        if self._blocked:
            raise CircuitOpenError(self.scope, self._signature_count, blocked=True)
        if (
            self._opened_at is not None
            and self._clock() - self._opened_at >= self._cooldown
        ):
            self._state = _HALF_OPEN
            self._probe_started_at = self._clock()
            return
        raise CircuitOpenError(self.scope, self._request_failures)


class BreakerPool:
    """Shares one breaker per backend scope for the lifetime of a run.

    Mirrors `RateLimiterPool.get` exactly, and on the same scope key: companies
    that share a pacer share the breaker that protects it, so a backend hosting
    several tracked companies is judged as one backend.
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(
        self,
        scope: str,
        threshold: int,
        *,
        cooldown_seconds: float = 60.0,
        blocked_threshold: int = 2,
    ) -> CircuitBreaker:
        breaker = self._breakers.get(scope)
        if breaker is None:
            breaker = CircuitBreaker(
                threshold,
                scope,
                cooldown_seconds=cooldown_seconds,
                blocked_threshold=blocked_threshold,
            )
            self._breakers[scope] = breaker
        return breaker
