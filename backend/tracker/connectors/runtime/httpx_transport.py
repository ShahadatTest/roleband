"""Default transport: httpx, buffered + streaming.

Wraps the `platform.http` primitives rather than reimplementing them, so
pacing/backoff/`Retry-After` semantics are the same ones every adapter's own
client runs. This module adds the *boundary*: mapping `httpx.Response` into
`FetchResponse` so no httpx object escapes into connector code.

The client is late-bound through a callable. That is load-bearing, not style:
the contract suite assigns `adapter._client` after construction, and adapters
build their real client inside `__aenter__`. A captured client would break both.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from urllib.parse import urljoin

import httpx

from tracker.connectors.sdk.types import (
    FetchRequest,
    FetchResponse,
    FetchStream,
    TransportPolicy,
)
from tracker.connectors.sdk.version import Capabilities
from tracker.platform.breaker import CircuitBreaker
from tracker.platform.clock import SourceClock
from tracker.platform.http import RetryPolicy, request_with_retry, stream_with_retry
from tracker.platform.ratelimit import RateLimiter
from tracker.platform.safe_fetch import BlockedDestination
from tracker.source_policy import CollectionAccess, collection_access

__all__ = ["HttpxTransport", "to_fetch_response"]


def to_fetch_response(
    response: httpx.Response,
    *,
    transport: str = TransportPolicy.STATIC_HTTP.value,
    elapsed_ms: int = 0,
    attempts: int = 1,
) -> FetchResponse:
    """Map an httpx response into the SDK envelope.

    `meta` goes through `FetchResponse.__post_init__` redaction, so a proxy or
    auth value present on the request can never surface here.
    """
    return FetchResponse(
        status=response.status_code,
        final_url=str(response.url),
        headers=dict(response.headers),
        content=response.content,
        elapsed_ms=elapsed_ms,
        attempts=attempts,
        transport=transport,
        meta={"http_version": response.http_version},
    )


class HttpxTransport:
    """`Transport` over httpx. Buffered and streaming."""

    name = TransportPolicy.STATIC_HTTP.value
    capabilities = Capabilities(stream=True, post=True, impersonate=False, render=False)

    def __init__(
        self,
        client_provider: Callable[[], httpx.AsyncClient],
        *,
        limiter: RateLimiter | None = None,
        breaker: CircuitBreaker | None = None,
        deadline: float | SourceClock | None = None,
        retry: RetryPolicy | None = None,
        log_name: str = "http",
        access: CollectionAccess | None = None,
        validate_url: Callable[[str], None] | None = None,
    ) -> None:
        self._client_provider = client_provider
        self._limiter = limiter
        self._breaker = breaker
        self._deadline = deadline
        self._retry = retry or RetryPolicy()
        self._log_name = log_name
        self._access = access if access is not None else collection_access(log_name)
        self._validate_url = validate_url

    def _kwargs(self, request: FetchRequest) -> dict:
        kwargs: dict = {}
        if request.headers:
            kwargs["headers"] = dict(request.headers)
        if request.query:
            kwargs["params"] = dict(request.query)
        if request.json_body is not None:
            kwargs["json"] = request.json_body
        elif request.body is not None:
            kwargs["content"] = request.body
        if request.timeout is not None:
            kwargs["timeout"] = request.timeout
        return kwargs

    async def send(self, request: FetchRequest) -> FetchResponse:
        self._access.require()
        started = time.monotonic()
        if self._validate_url is not None:
            response = await self._guarded_request(request)
        else:
            response = await self._request(request.method, request.url, **self._kwargs(request))
        return to_fetch_response(
            response,
            transport=self.name,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        return await request_with_retry(
            self._client_provider(),
            method,
            url,
            retry=self._retry,
            limiter=self._limiter,
            breaker=self._breaker,
            deadline=self._deadline,
            log_name=self._log_name,
            **kwargs,
        )

    async def _guarded_request(self, request: FetchRequest) -> httpx.Response:
        """Sitemap reads: validate every hop before it reaches the pinned client."""
        if request.method != "GET":
            raise BlockedDestination("guarded inventory supports GET only")
        url, kwargs = request.url, self._kwargs(request)
        for _ in range(6):
            assert self._validate_url is not None
            self._validate_url(url)
            response = await self._request("GET", url, follow_redirects=False, **kwargs)
            if not response.is_redirect:
                return response
            location = response.headers.get("location")
            if not location:
                raise BlockedDestination("redirect without a Location")
            url, kwargs = urljoin(str(response.url), location), {}
        raise BlockedDestination("more than 5 redirects")

    @asynccontextmanager
    async def open_stream(self, request: FetchRequest) -> AsyncIterator[FetchStream]:
        self._access.require()
        if self._validate_url is not None:
            raise BlockedDestination("guarded inventory does not support streaming")
        async with stream_with_retry(
            self._client_provider(),
            request.method,
            request.url,
            retry=self._retry,
            limiter=self._limiter,
            breaker=self._breaker,
            deadline=self._deadline,
            log_name=self._log_name,
            **self._kwargs(request),
        ) as response:
            yield FetchStream(
                status=response.status_code,
                final_url=str(response.url),
                headers=dict(response.headers),
                iter_bytes=response.aiter_bytes(),
                transport=TransportPolicy.STREAM_HTTP.value,
            )
