"""Connector SDK contracts.

The contract: existing connector contracts pass unchanged; failure,
cancellation, drift, and closure eligibility match baseline; no external
connector imports private runtime modules.

`tests/contracts/test_listing_connectors.py` covers the first half (it drives
every adapter through shared fixtures). This file covers the SDK
itself: the boundary, redaction, capability negotiation, retry centralization,
and the import rule.
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

from tracker.connectors.listing.ashby import AshbyAdapter
from tracker.connectors.listing.base import BaseAdapter
from tracker.connectors.runtime.httpx_transport import HttpxTransport, to_fetch_response
from tracker.connectors.runtime.tiers import CurlHttpxTransport
from tracker.connectors.sdk import (
    CONNECTOR_API_VERSION,
    Capabilities,
    CapabilityError,
    FetchRequest,
    FetchResponse,
    TransportPolicy,
    negotiate,
    redact_meta,
)
from tracker.platform.http import (
    RetryPolicy,
    backoff_for_status,
    backoff_for_transport_error,
    request_with_retry,
)
from tracker.platform.ratelimit import RateLimiter
from tracker.schema import RawJob

CONNECTORS_ROOT = Path(__file__).resolve().parents[1] / "tracker" / "connectors"


# --------------------------------------------------------------------------- #
# Boundary: no transport object escapes the SDK
# --------------------------------------------------------------------------- #


def test_fetch_response_carries_bytes_not_a_transport_object():
    raw = httpx.Response(200, json={"jobs": []}, request=httpx.Request("GET", "https://x/y"))
    mapped = to_fetch_response(raw)

    assert isinstance(mapped, FetchResponse)
    assert mapped.status == 200
    assert mapped.json() == {"jobs": []}
    # The httpx object must not be reachable from any field.
    assert not any(isinstance(v, httpx.Response) for v in vars(mapped).values())


def test_fetch_response_text_and_json_round_trip():
    resp = FetchResponse(
        status=200, final_url="https://x", headers={}, content=b'{"a": 1}'
    )
    assert resp.text() == '{"a": 1}'
    assert resp.json() == {"a": 1}
    assert resp.ok


def test_non_2xx_is_not_ok():
    assert not FetchResponse(status=503, final_url="u", headers={}, content=b"").ok


# --------------------------------------------------------------------------- #
# Credential redaction: meta['proxy'] is redacted by construction
# --------------------------------------------------------------------------- #


def test_proxy_and_credentials_are_redacted_by_construction():
    resp = FetchResponse(
        status=200,
        final_url="https://x",
        headers={},
        content=b"",
        meta={
            "proxy": "http://user:secret@proxy.internal:8080",
            "Authorization": "Bearer sk-live-123",
            "cookie": "session=abc",
            "http_version": "HTTP/2",
        },
    )
    blob = repr(resp)
    assert "secret" not in blob
    assert "sk-live-123" not in blob
    assert "session=abc" not in blob
    # Non-credential metadata survives.
    assert resp.meta["http_version"] == "HTTP/2"
    assert resp.meta["proxy"] == "[redacted]"


def test_redaction_is_case_insensitive_and_survives_empty():
    assert redact_meta({"PROXY": "http://p"})["PROXY"] == "[redacted]"
    assert redact_meta(None) == {}


# --------------------------------------------------------------------------- #
# Capability negotiation
# --------------------------------------------------------------------------- #


def test_negotiate_accepts_when_runtime_provides_everything():
    provided = Capabilities(stream=True, post=True)
    assert negotiate(provided=provided, required=Capabilities(stream=True, post=False))


def test_negotiate_rejects_missing_capability_by_name():
    with pytest.raises(CapabilityError, match="render"):
        negotiate(
            provided=Capabilities(render=False),
            required=Capabilities(render=True),
            connector_name="needs-browser",
        )


def test_negotiate_rejects_api_version_mismatch():
    with pytest.raises(CapabilityError, match="CONNECTOR_API_VERSION"):
        negotiate(
            provided=Capabilities(),
            required=Capabilities(),
            connector_api_version=CONNECTOR_API_VERSION + 1,
        )


def test_additive_capability_does_not_require_version_bump():
    """A runtime gaining `render` must still serve a connector that predates it."""
    old_connector_needs = Capabilities(stream=True, post=True, render=False)
    new_runtime = Capabilities(stream=True, post=True, render=True)
    assert negotiate(provided=new_runtime, required=old_connector_needs)


def test_the_httpx_transport_offers_streaming():
    assert HttpxTransport(lambda: None).capabilities.stream is True


_BOARD = "https://board.example.test/jobs"


class _OneRequest(BaseAdapter):
    """Reads its board in one request through `self.context`, as a new adapter does."""

    name = "one-request"
    posted_date = "none"

    async def fetch(self) -> AsyncIterator[RawJob]:
        await self.context.fetch(FetchRequest(url=_BOARD))
        return
        yield  # an async generator that yields nothing


class _NeedsRender(_OneRequest):
    required_capabilities = Capabilities(stream=False, post=False, render=True)


class _NeedsStreamAndPost(_OneRequest):
    required_capabilities = Capabilities(stream=True, post=True)


def _offline(cls: type[_OneRequest], sent: list[httpx.URL]) -> _OneRequest:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url)
        return httpx.Response(200, json={"jobs": []})

    adapter = cls("acme")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


@pytest.mark.asyncio
async def test_an_adapter_needing_what_its_transport_lacks_fails_before_any_request():
    """The base builds every adapter's context on the httpx transport, which
    cannot render. Negotiation names the gap before a request leaves."""
    sent: list[httpx.URL] = []
    adapter = _offline(_NeedsRender, sent)
    async with adapter._client:
        with pytest.raises(CapabilityError, match="one-request: runtime lacks capability render"):
            [job async for job in adapter.fetch()]
    assert sent == []


@pytest.mark.asyncio
async def test_an_adapter_needing_only_what_its_transport_has_fetches():
    sent: list[httpx.URL] = []
    adapter = _offline(_NeedsStreamAndPost, sent)
    async with adapter._client:
        assert [job async for job in adapter.fetch()] == []
    assert [str(url) for url in sent] == [_BOARD]
    assert adapter.context.capabilities == HttpxTransport.capabilities


# --------------------------------------------------------------------------- #
# Centralized retry accounting (one policy, every transport)
# --------------------------------------------------------------------------- #


def test_retry_after_digits_win_over_exponential_backoff():
    retry = RetryPolicy()
    assert backoff_for_status(httpx.Headers({"Retry-After": "7"}), attempt=3, retry=retry) == 7.0


def test_retry_after_header_is_case_insensitive():
    assert backoff_for_status(httpx.Headers({"retry-after": "2"}), attempt=0, retry=RetryPolicy()) == 2.0


def test_non_digit_retry_after_falls_back_to_exponential():
    """HTTP-date form is not guessed at -- it falls back rather than mis-parsing."""
    retry = RetryPolicy()
    assert backoff_for_status(
        httpx.Headers({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), attempt=2, retry=retry
    ) == 4.0


def test_retry_after_is_read_stripped_and_an_empty_one_is_no_answer():
    retry = RetryPolicy()
    assert backoff_for_status(httpx.Headers({"Retry-After": " 3 "}), attempt=0, retry=retry) == 3.0
    assert backoff_for_status(httpx.Headers({"Retry-After": ""}), attempt=2, retry=retry) == 4.0


def test_backoff_is_capped():
    retry = RetryPolicy(max_backoff=5.0)
    assert backoff_for_transport_error(attempt=10, retry=retry) == 5.0
    assert backoff_for_status(httpx.Headers({"Retry-After": "3600"}), attempt=0, retry=retry) == 5.0


# --------------------------------------------------------------------------- #
# Transports over a mocked network
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_httpx_transport_sends_query_and_maps_response():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"jobs": [1, 2]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        transport = HttpxTransport(lambda: client, limiter=RateLimiter(0.0))
        resp = await transport.send(
            FetchRequest(url="https://boards/jobs", query={"content": "true"})
        )
    finally:
        await client.aclose()

    assert resp.status == 200
    assert resp.json() == {"jobs": [1, 2]}
    assert resp.transport == TransportPolicy.STATIC_HTTP.value
    assert "content=true" in seen["url"]


@pytest.mark.asyncio
async def test_httpx_transport_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        transport = HttpxTransport(lambda: client, limiter=RateLimiter(0.0))
        resp = await transport.send(FetchRequest(url="https://x"))
    finally:
        await client.aclose()

    assert calls["n"] == 2
    assert resp.status == 200


@pytest.mark.asyncio
async def test_httpx_transport_late_binds_the_client():
    """The contract suite swaps `_client` after construction; a captured client
    would silently keep using the old transport."""
    holder: dict = {"client": None}
    transport = HttpxTransport(lambda: holder["client"], limiter=RateLimiter(0.0))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"late": True}))
    )
    holder["client"] = client
    try:
        resp = await transport.send(FetchRequest(url="https://x"))
    finally:
        await client.aclose()

    assert resp.json() == {"late": True}


class _SessionStub:
    """curl_cffi AsyncSession stand-in, mirroring the contract-suite stub."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def request(self, method, url, **_kwargs):
        self.calls += 1
        return self._responses.pop(0)


def _tls_client(session) -> httpx.AsyncClient:
    """The TLS tier's client: httpx over a (stub) curl session."""
    return httpx.AsyncClient(transport=CurlHttpxTransport(lambda: session))


@pytest.mark.asyncio
async def test_the_tls_tier_honors_retry_after(monkeypatch):
    """The curl-backed tier honours Retry-After like every other."""
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("asyncio.sleep", record_wait)
    stub = _SessionStub(
        [
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(200, text="<html/>"),
        ]
    )
    async with _tls_client(stub) as client:
        resp = await request_with_retry(client, "GET", "https://m", retry=RetryPolicy())

    assert stub.calls == 2
    assert resp.status_code == 200
    assert resp.text == "<html/>"
    assert waits == [5.0]  # the header's wait, not the exponential 1s


@pytest.mark.asyncio
async def test_the_tls_tier_gives_up_after_max_retries():
    stub = _SessionStub([httpx.Response(503) for _ in range(4)])
    async with _tls_client(stub) as client:
        resp = await request_with_retry(
            client, "GET", "https://m", retry=RetryPolicy(max_retries=2, max_backoff=0.0)
        )

    assert resp.status_code == 503
    assert stub.calls == 3  # initial + 2 retries, then surfaced as failure


@pytest.mark.asyncio
async def test_the_tls_tier_retries_curl_errors_then_raises():
    class Boom:
        def __init__(self):
            self.calls = 0

        async def request(self, *_a, **_k):
            self.calls += 1
            raise CurlConnectionError("curl exploded")

    stub = Boom()
    async with _tls_client(stub) as client:
        with pytest.raises(httpx.ReadError, match="curl exploded"):
            await request_with_retry(
                client, "GET", "https://m", retry=RetryPolicy(max_retries=1, max_backoff=0.0)
            )
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_cancellation_propagates_and_does_not_become_a_retry():
    """Gate: cancellation behavior matches baseline -- a cancelled scrape must
    abort, not be read as a curl error and retried."""

    class Hang:
        def __init__(self):
            self.calls = 0

        async def request(self, *_a, **_k):
            self.calls += 1
            raise asyncio.CancelledError()

    stub = Hang()
    async with _tls_client(stub) as client:
        with pytest.raises(asyncio.CancelledError):
            await request_with_retry(client, "GET", "https://m", retry=RetryPolicy(max_backoff=0.0))
    assert stub.calls == 1


@pytest.mark.parametrize(("override", "attempts"), [(0, 1), (None, 4)], ids=["override", "settings"])
@pytest.mark.asyncio
async def test_ashby_streams_its_board_on_the_adapters_retry_budget(override, attempts):
    """Ashby opens its board as a stream, outside `self.request`, and still
    retries as `_retry_policy()` says: `max_retries` when set, else the settings."""
    sent: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url)
        return httpx.Response(429, headers={"Retry-After": "0"})

    adapter = AshbyAdapter("acme", board_token="acme")
    adapter.settings = adapter.settings.model_copy(update={"scraper_max_retries": 3})
    adapter.max_retries = override
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    async with adapter._client:
        assert [job async for job in adapter.fetch()] == []

    assert len(sent) == attempts
    assert adapter.drift.listing_invalidated


# --------------------------------------------------------------------------- #
# No connector imports private runtime modules
# --------------------------------------------------------------------------- #


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_listing_connectors_do_not_import_private_runtime():
    """`connectors.runtime` is private; connectors get a context instead.

    `listing/base.py` is the sanctioned bridge that constructs the runtime, and
    `meta.py` owns a non-httpx transport. Every other connector must stay on
    the SDK surface, enforced structurally rather than by review.
    """
    allowed = {"base.py", "meta.py"}
    offenders: list[str] = []
    for module in sorted((CONNECTORS_ROOT / "listing").glob("*.py")):
        if module.name in allowed:
            continue
        private = {
            name
            for name in _module_imports(module)
            if name.startswith("tracker.connectors.runtime")
        }
        if private:
            offenders.append(f"{module.name}: {sorted(private)}")
    assert not offenders, (
        "connectors must import tracker.connectors.sdk, not the private runtime:\n"
        + "\n".join(offenders)
    )


def test_sdk_package_does_not_import_the_runtime():
    """The public SDK must not depend on its implementation, or the boundary is
    decorative: a connector importing only the SDK would still drag in httpx
    and curl_cffi transports."""
    offenders: list[str] = []
    for module in sorted((CONNECTORS_ROOT / "sdk").glob("*.py")):
        private = {
            name
            for name in _module_imports(module)
            if name.startswith("tracker.connectors.runtime")
        }
        if private:
            offenders.append(f"sdk/{module.name}: {sorted(private)}")
    assert not offenders, "SDK must not import its runtime:\n" + "\n".join(offenders)


def test_sdk_does_not_import_scrapling_or_transport_libraries():
    """No Scrapling type crosses the SDK boundary, and no Scrapling
    dependency enters the backend venv."""
    banned = ("scrapling", "playwright", "curl_cffi")
    offenders: list[str] = []
    for module in sorted((CONNECTORS_ROOT / "sdk").glob("*.py")):
        for name in _module_imports(module):
            if name.split(".")[0] in banned:
                offenders.append(f"sdk/{module.name}: {name}")
    assert not offenders, "SDK imports a transport library:\n" + "\n".join(offenders)
