"""Fetch tiers: the client a listing adapter gets for its company.

The tiers, in order: browser identity -> TLS fingerprint -> headless -> proxy,
**only for walled companies the user follows** (`docs/sources.md`, "Walled and
user-directed sources"). This module builds the client; it decides nothing. The tier arrives
on `CollectionAccess.tier`, which `source_policy.collection_access` sets above
`IDENTIFIED` only for a walled company the user consented to, from the
register row's recorded `fetch_tier`. There is no escalation after a block: a
refusal stays an observable failure (`TransportPolicy`), and moving a source up
a tier is a reviewed change to its register row.

Every tier is an `httpx.AsyncClient`, so pacing, retry, breaker and deadline
accounting (`platform.http.request_with_retry`) are the same on every tier and
no adapter learns which one it runs on. The TLS tier swaps only the client's
transport for a `curl_cffi` session.

Lives in `connectors/runtime`, never the SDK (`tests/test_connector_sdk.py`).
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from tracker.platform.http import make_client
from tracker.platform.safe_fetch import public_client

# FetchTier through the gate, not the register: the runtime reads the tier the
# gate released, and is not another reader of the review register.
from tracker.source_policy import CollectionAccess, CollectionPolicyDenied, FetchTier

logger = logging.getLogger(__name__)

__all__ = [
    "BROWSER_HEADERS",
    "CurlHttpxTransport",
    "FetchTierUnavailable",
    "HeadlessHttpxTransport",
    "make_tier_client",
    "unavailable_reason",
]

#: What Chrome adds beyond a User-Agent. Paired with the settings UA (a Chrome
#: 131 string), so the hints and the UA name the same browser.
BROWSER_HEADERS: Mapping[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

#: Request headers the curl impersonation profile owns. Forwarding httpx's
#: values would pair a Chrome TLS fingerprint with an `httpx` header set.
_CURL_OWNED_REQUEST = frozenset(
    {"user-agent", "accept-encoding", "connection", "host", "content-length"}
)
#: curl has already decoded the body; passing these on would make httpx decode
#: it a second time, or check a length that describes the encoded body.
_DECODED_RESPONSE = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class FetchTierUnavailable(CollectionPolicyDenied):
    """The consented tier is not in this build. A LOCAL refusal: the source was
    never asked, so it lands as `unattempted`: no evidence about the source."""


class _CurlSession(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


def _make_session() -> _CurlSession:
    from curl_cffi.requests import AsyncSession  # lazy: the SDK never pulls curl

    # Pinned to the browser the settings UA and BROWSER_HEADERS name, so every
    # tier above identified claims the same Chrome.
    # Typed as the protocol: curl's own signature narrows `method` to literals.
    session: Any = AsyncSession(impersonate="chrome131")
    return session


def _read_timeout(request: httpx.Request) -> float | None:
    timeouts = request.extensions.get("timeout") or {}
    values = [v for v in (timeouts.get("connect"), timeouts.get("read")) if v is not None]
    return max(values) if values else None


class CurlHttpxTransport(httpx.AsyncBaseTransport):
    """httpx transport over one `curl_cffi` session: the TLS-fingerprint tier.

    httpx keeps redirects and cookies (curl is told to do neither), so the
    client behaves exactly as on the identified tier. curl errors are mapped to
    httpx's retryable classes, so the one retry loop classifies them.
    """

    def __init__(self, session_factory: Callable[[], _CurlSession] | None = None) -> None:
        self._session_factory = session_factory or _make_session
        self._session: _CurlSession | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._session is None:
            self._session = self._session_factory()
        body = await request.aread()
        headers = {
            key: value
            for key, value in request.headers.multi_items()
            if key.lower() not in _CURL_OWNED_REQUEST
        }
        try:
            response = await self._session.request(
                request.method,
                str(request.url),
                headers=headers,
                data=body or None,
                timeout=_read_timeout(request),
                allow_redirects=False,
                discard_cookies=True,
            )
        except Exception as exc:
            raise _as_httpx_error(exc, request) from exc
        raw_headers = getattr(response, "headers", None) or {}
        pairs = raw_headers.multi_items() if hasattr(raw_headers, "multi_items") else raw_headers.items()
        return httpx.Response(
            response.status_code,
            headers=[(k, v) for k, v in pairs if k.lower() not in _DECODED_RESPONSE],
            content=response.content,
            request=request,
        )

    async def aclose(self) -> None:
        if self._session is not None:
            close = getattr(self._session, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            self._session = None


def _as_httpx_error(exc: Exception, request: httpx.Request) -> Exception:
    """Map a curl failure onto the httpx class `request_with_retry` expects.

    Only curl's own errors are mapped; anything else is a bug in our code and
    propagates unchanged.
    """
    try:
        from curl_cffi.requests.exceptions import RequestException, Timeout
    except ImportError:  # pragma: no cover - curl_cffi is a pinned dependency
        return exc
    if isinstance(exc, Timeout):
        return httpx.ReadTimeout(str(exc), request=request)
    if isinstance(exc, RequestException):
        return httpx.ReadError(str(exc), request=request)
    return exc


# --------------------------------------------------------------------------- #
# Headless (and headless behind a proxy)
# --------------------------------------------------------------------------- #

#: Headers a page's `fetch()` may not set (the browser owns them) or that the
#: browser's own cookie jar replaces.
_BROWSER_OWNED_REQUEST = _CURL_OWNED_REQUEST | {"cookie"}

#: Runs one request inside the page, so it leaves through Chromium's own
#: network stack with the page's cookies. Bodies cross as base64: the bridge is
#: JSON, and a posting payload is not guaranteed to be text.
_FETCH_IN_PAGE = """
async ({url, method, headers, body}) => {
  const init = {method, headers, credentials: "include", redirect: "follow"};
  if (body !== null) init.body = Uint8Array.from(atob(body), c => c.charCodeAt(0));
  const r = await fetch(url, init);
  const buf = new Uint8Array(await r.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return {status: r.status, url: r.url, headers: [...r.headers.entries()], body: btoa(bin)};
}
"""


class _Page(Protocol):
    url: str

    async def goto(self, url: str, **kwargs: Any) -> Any: ...
    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...


#: Opens (or reuses) a page whose document is on the given origin.
PageOpener = Callable[[str], Awaitable[_Page]]


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _playwright_proxy(proxy_url: str) -> dict[str, str]:
    """Playwright takes credentials apart from the server address."""
    parts = urlsplit(proxy_url)
    proxy = {"server": f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")}
    if parts.username:
        proxy["username"] = parts.username
    if parts.password:
        proxy["password"] = parts.password
    return proxy


class _ChromiumPages:
    """One headless Chromium, one context, one page per origin, opened lazily.

    The context's user agent is the browser's own with `HeadlessChrome` read as
    `Chrome`: the one header that names headless mode outright. Everything else
    is the real browser, which is the point of this tier.
    """

    def __init__(self, *, proxy_url: str | None = None) -> None:
        self._proxy_url = proxy_url
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._pages: dict[str, _Page] = {}
        self._lock = asyncio.Lock()

    async def _start(self) -> None:
        from playwright.async_api import async_playwright  # lazy: optional dependency

        self._playwright = await async_playwright().start()
        launch: dict[str, Any] = {"headless": True}
        if self._proxy_url:
            launch["proxy"] = _playwright_proxy(self._proxy_url)
        self._browser = await self._playwright.chromium.launch(**launch)
        probe = await self._browser.new_page()
        agent = str(await probe.evaluate("navigator.userAgent")).replace("HeadlessChrome", "Chrome")
        await probe.close()
        self._context = await self._browser.new_context(user_agent=agent, locale="en-US")

    async def __call__(self, origin: str) -> _Page:
        async with self._lock:
            if self._context is None:
                await self._start()
            page = self._pages.get(origin)
            if page is None:
                page = await self._context.new_page()
                self._pages[origin] = page
            return page

    async def aclose(self) -> None:
        for closable in (self._context, self._browser):
            if closable is not None:
                await closable.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._pages.clear()
        self._context = self._browser = self._playwright = None


class HeadlessHttpxTransport(httpx.AsyncBaseTransport):
    """httpx transport whose requests run as `fetch()` in a headless page.

    The page is first navigated to the request's origin, so the site's own
    scripts (a challenge included) run and set their cookies; the request then
    leaves from that document, same-origin. A root that lands on another
    origin is followed by navigating to the request URL itself. httpx keeps
    retry, pacing and breaker accounting; the browser keeps redirects and
    cookies.
    """

    def __init__(self, page_opener: PageOpener | None = None, *, proxy_url: str | None = None) -> None:
        self._owned = _ChromiumPages(proxy_url=proxy_url) if page_opener is None else None
        self._open: PageOpener = page_opener or self._owned  # type: ignore[assignment]
        self._warm: set[str] = set()

    async def _page_for(self, request: httpx.Request, timeout: float | None) -> _Page:
        url = str(request.url)
        origin = _origin(url)
        page = await self._open(origin)
        if origin not in self._warm:
            ms = None if timeout is None else timeout * 1000
            await page.goto(origin + "/", wait_until="domcontentloaded", timeout=ms)
            if _origin(page.url) != origin:
                await page.goto(url, wait_until="domcontentloaded", timeout=ms)
            self._warm.add(origin)
        return page

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        timeout = _read_timeout(request)
        body = await request.aread()
        arg = {
            "url": str(request.url),
            "method": request.method,
            "headers": {
                k: v for k, v in request.headers.multi_items() if k.lower() not in _BROWSER_OWNED_REQUEST
            },
            "body": base64.b64encode(body).decode() if body else None,
        }
        try:
            page = await self._page_for(request, timeout)
            result = await asyncio.wait_for(page.evaluate(_FETCH_IN_PAGE, arg), timeout)
        except TimeoutError as exc:
            raise httpx.ReadTimeout(f"headless: {exc or 'timed out'}", request=request) from exc
        except Exception as exc:
            raise _headless_error(exc, request) from exc
        return httpx.Response(
            result["status"],
            headers=[(k, v) for k, v in result["headers"] if k.lower() not in _DECODED_RESPONSE],
            content=base64.b64decode(result["body"]),
            request=request,
        )

    async def aclose(self) -> None:
        if self._owned is not None:
            await self._owned.aclose()


def _headless_error(exc: Exception, request: httpx.Request) -> Exception:
    """A browser that could not start is OUR missing tier (`unattempted`); a
    page that could not fetch is a network error (retried); anything else is
    a bug and propagates unchanged."""
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeout
    except ImportError:
        return exc
    if isinstance(exc, PlaywrightTimeout):
        return httpx.ReadTimeout(f"headless: {exc}", request=request)
    if isinstance(exc, PlaywrightError):
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            return FetchTierUnavailable(
                CollectionAccess(
                    "headless",
                    "the headless browser is not installed (run `playwright install chromium`)",
                )
            )
        return httpx.ReadError(f"headless: {message.splitlines()[0] if message else exc!r}", request=request)
    return exc


# --------------------------------------------------------------------------- #
# The one factory
# --------------------------------------------------------------------------- #


def _playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def unavailable_reason(tier: FetchTier, *, proxy_url: str | None = None) -> str | None:
    """Why this machine cannot fetch on `tier`, or None when it can.

    Headless and proxy need the optional `playwright` package
    (`requirements-optional.txt`); proxy also
    needs `Settings.scraper_proxy_url`. A missing one is our deployment, never
    the source, so the caller refuses locally.
    """
    if tier in (FetchTier.HEADLESS, FetchTier.PROXY) and not _playwright_installed():
        return f"fetch tier {tier.value!r} needs the optional `playwright` package, which is not installed"
    if tier is FetchTier.PROXY and not proxy_url:
        return "fetch tier 'proxy' needs `scraper_proxy_url`, which is not set"
    return None


def make_tier_client(
    access: CollectionAccess,
    *,
    headers: Mapping[str, str],
    timeout: httpx.Timeout | float,
    session_factory: Callable[[], _CurlSession] | None = None,
    page_opener: PageOpener | None = None,
    proxy_url: str | None = None,
    public_only: bool = False,
) -> httpx.AsyncClient:
    """The client for `access.tier`. Refuses a tier this machine cannot run."""
    tier = access.tier
    if public_only:
        if tier is not FetchTier.IDENTIFIED:
            raise FetchTierUnavailable(CollectionAccess(
                access.provider_key, "this fetch tier cannot pin public inventory destinations",
            ))
        client = public_client(user_agent=headers.get("User-Agent", ""), timeout=timeout)
        client.headers.update(headers)
        return client
    reason = unavailable_reason(tier, proxy_url=proxy_url)
    if reason is not None:
        raise FetchTierUnavailable(CollectionAccess(access.provider_key, f"{access.provider_key!r}: {reason}"))
    if tier is FetchTier.IDENTIFIED:
        return make_client(headers=dict(headers), timeout=timeout, follow_redirects=True, http2=True)
    # The proxy URL may carry credentials: the log names the tier only.
    logger.info("%s: fetching on tier %s (walled, consented)", access.provider_key, tier.value)
    if tier is FetchTier.BROWSER_IDENTITY:
        return make_client(
            headers={**headers, **BROWSER_HEADERS},
            timeout=timeout,
            follow_redirects=True,
            http2=True,
        )
    transport: httpx.AsyncBaseTransport
    if tier is FetchTier.TLS_FINGERPRINT:
        transport = CurlHttpxTransport(session_factory)
    else:
        transport = HeadlessHttpxTransport(
            page_opener, proxy_url=proxy_url if tier is FetchTier.PROXY else None,
        )
    return httpx.AsyncClient(
        headers=dict(headers),
        timeout=timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout),
        follow_redirects=True,
        transport=transport,
    )
