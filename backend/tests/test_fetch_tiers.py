"""Fetch tiers are released only for a walled, consented company.

The tiers, in order: browser identity -> TLS fingerprint -> headless -> proxy,
only for walled companies the user follows. The contracts:

* The register records the tier; a tier above `IDENTIFIED` is refused on an
  unwalled row, so no unwalled company can ever be fetched in disguise.
* `collection_access` is the only thing that releases a tier: identified for
  every unwalled company, for every provider-level question, and (with a
  refusal) for a walled company without the user's consent.
* The adapter builds its client from that answer on entry — the one path every
  collecting workflow goes through — and a tier this build does not carry is a
  local refusal (`unattempted`), never a source failure.
* The TLS tier is an httpx transport over curl: redirects, cookies, decoding
  and retry classification behave as on the identified client.

No live requests: curl sessions are stubs.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from curl_cffi.requests.exceptions import Timeout as CurlTimeout

from tests.factories import STAFF_EM_SCOPE, NoComp
from tracker.config import get_settings
from tracker.connectors import RateLimiterPool, build_adapter
from tracker.connectors.runtime import tiers
from tracker.connectors.runtime.tiers import (
    BROWSER_HEADERS,
    CurlHttpxTransport,
    FetchTierUnavailable,
    make_tier_client,
)
from tracker.platform.http import RetryPolicy, request_with_retry
from tracker.source_policy import CollectionAccess, CollectionPolicyDenied, collection_access
from tracker.source_review import SOURCE_REVIEWS, FetchTier
from tracker.workflows.collection import collect_source

# A broken gate must fail here, never reach google.com: httpx's network
# transports are refused, and so is a real curl session.
pytestmark = pytest.mark.usefixtures("no_escape", "_no_real_curl")

GOOGLE = SOURCE_REVIEWS["google"]
CONSENT = GOOGLE.wall_fingerprint


@pytest.fixture
def _no_real_curl(monkeypatch):
    def refused():
        raise AssertionError("a test built a real curl session")

    monkeypatch.setattr(tiers, "_make_session", refused)


def _google_on(monkeypatch, tier: FetchTier) -> None:
    """Record a tier on the real walled row. The fingerprint is unchanged: it
    names the wall's evidence, and the tier is how we fetch, not what it asks."""
    monkeypatch.setitem(SOURCE_REVIEWS, "google", replace(GOOGLE, fetch_tier=tier))


# --------------------------------------------------------------------------- #
# The register
# --------------------------------------------------------------------------- #


def test_only_the_recorded_walled_route_uses_a_tier_above_identified():
    """TSMC's portal is the first recorded tier: collected on the TLS
    fingerprint, walled. Every other source is fetched as
    an identified client; a new tier is a new, deliberate entry here."""
    tiers = {key: row.fetch_tier for key, row in SOURCE_REVIEWS.items()
             if row.fetch_tier is not FetchTier.IDENTIFIED}
    assert tiers == {"avature_tls": FetchTier.TLS_FINGERPRINT}
    assert SOURCE_REVIEWS["avature_tls"].wall is not None


@pytest.mark.parametrize("tier", [t for t in FetchTier if t is not FetchTier.IDENTIFIED])
def test_an_unwalled_row_cannot_record_a_tier(tier):
    with pytest.raises(ValueError, match="needs a wall"):
        replace(SOURCE_REVIEWS["greenhouse"], fetch_tier=tier)
    # Positive control: the same tier on a walled row is a legal record.
    assert replace(SOURCE_REVIEWS["greenhouse"], refuses_identified_client=True, fetch_tier=tier)
    assert replace(GOOGLE, fetch_tier=tier)


def test_tiers_are_ordered_weakest_first():
    assert [t.value for t in sorted(FetchTier, key=lambda t: t.rank)] == [
        "identified", "browser_identity", "tls_fingerprint", "headless", "proxy",
    ]


# --------------------------------------------------------------------------- #
# The gate releases the tier
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("consent", [CONSENT, "robots:stale-sha"])
def test_a_consented_walled_company_gets_its_rows_tier(monkeypatch, consent):
    """A consent given to an earlier register still releases today's tier: the
    user is asked once per company."""
    _google_on(monkeypatch, FetchTier.TLS_FINGERPRINT)
    access = collection_access("google", company="google", consent=consent)
    assert not access.denied
    assert access.tier is FetchTier.TLS_FINGERPRINT


@pytest.mark.parametrize("consent", [None, ""])
def test_no_consent_releases_no_tier(monkeypatch, consent):
    _google_on(monkeypatch, FetchTier.TLS_FINGERPRINT)
    access = collection_access("google", company="google", consent=consent)
    assert access.denied and access.walled
    assert access.tier is FetchTier.IDENTIFIED


def test_a_provider_level_question_never_escalates(monkeypatch):
    """Consent is per company: a bare provider answer must stay identified."""
    _google_on(monkeypatch, FetchTier.TLS_FINGERPRINT)
    assert collection_access("google").tier is FetchTier.IDENTIFIED


def test_an_unwalled_company_is_identified_whatever_consent_it_carries():
    access = collection_access("greenhouse", company="anthropic", consent=CONSENT)
    assert not access.denied and access.tier is FetchTier.IDENTIFIED


# --------------------------------------------------------------------------- #
# The client each tier builds
# --------------------------------------------------------------------------- #

_HEADERS = {"User-Agent": "UA/1", "Accept": "application/json"}


@pytest.mark.asyncio
async def test_identified_and_browser_identity_are_httpx_with_different_headers():
    identified = make_tier_client(CollectionAccess("x"), headers=_HEADERS, timeout=5)
    browser = make_tier_client(
        CollectionAccess("x", tier=FetchTier.BROWSER_IDENTITY), headers=_HEADERS, timeout=5,
    )
    async with identified, browser:
        assert "sec-ch-ua" not in identified.headers
        assert identified.headers["user-agent"] == "UA/1"
        for key, value in BROWSER_HEADERS.items():
            assert browser.headers[key] == value
        assert browser.headers["user-agent"] == "UA/1", "hints pair with the configured UA"
        assert not isinstance(identified._transport, CurlHttpxTransport)
        assert not isinstance(browser._transport, CurlHttpxTransport)


@pytest.mark.asyncio
async def test_tls_fingerprint_swaps_only_the_transport():
    client = make_tier_client(
        CollectionAccess("x", tier=FetchTier.TLS_FINGERPRINT),
        headers=_HEADERS, timeout=5, session_factory=lambda: _StubSession([]),
    )
    async with client:
        assert isinstance(client._transport, CurlHttpxTransport)
        assert client.follow_redirects


@pytest.mark.parametrize("tier", [FetchTier.HEADLESS, FetchTier.PROXY])
def test_a_tier_this_machine_cannot_run_is_a_local_refusal(tier, monkeypatch):
    monkeypatch.setattr(tiers, "_playwright_installed", lambda: False)
    with pytest.raises(FetchTierUnavailable, match="playwright") as raised:
        make_tier_client(
            CollectionAccess("google", tier=tier), headers=_HEADERS, timeout=5, proxy_url="http://p:1",
        )
    assert isinstance(raised.value, CollectionPolicyDenied), "unattempted, never a source failure"


def test_the_proxy_tier_needs_a_configured_proxy(monkeypatch):
    monkeypatch.setattr(tiers, "_playwright_installed", lambda: True)
    with pytest.raises(FetchTierUnavailable, match="scraper_proxy_url"):
        make_tier_client(CollectionAccess("google", tier=FetchTier.PROXY), headers=_HEADERS, timeout=5)
    assert tiers.unavailable_reason(FetchTier.HEADLESS) is None
    assert tiers.unavailable_reason(FetchTier.PROXY, proxy_url="http://p:1") is None


def test_proxy_credentials_are_split_off_the_server_address():
    assert tiers._playwright_proxy("http://u:s3cret@proxy.test:8080") == {
        "server": "http://proxy.test:8080", "username": "u", "password": "s3cret",
    }
    assert tiers._playwright_proxy("socks5://proxy.test") == {"server": "socks5://proxy.test"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("tier", "proxied"), [(FetchTier.HEADLESS, False), (FetchTier.PROXY, True)])
async def test_headless_tiers_build_the_browser_transport(tier, proxied, monkeypatch):
    monkeypatch.setattr(tiers, "_playwright_installed", lambda: True)
    client = make_tier_client(
        CollectionAccess("x", tier=tier), headers=_HEADERS, timeout=5, proxy_url="http://u:p@proxy.test:1",
    )
    async with client:
        transport = client._transport
        assert isinstance(transport, tiers.HeadlessHttpxTransport)
        # Only the proxy tier routes through the proxy; headless goes direct.
        assert (transport._owned._proxy_url is not None) is proxied


# --------------------------------------------------------------------------- #
# The adapter builds its client from the gate's answer
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_consented_adapter_enters_on_its_tier(monkeypatch):
    _google_on(monkeypatch, FetchTier.TLS_FINGERPRINT)
    adapter = build_adapter("google", "google")
    adapter.collection_consent = CONSENT
    async with adapter:
        assert isinstance(adapter.client._transport, CurlHttpxTransport)


@pytest.mark.asyncio
async def test_an_unwalled_adapter_enters_identified(monkeypatch):
    _google_on(monkeypatch, FetchTier.TLS_FINGERPRINT)
    adapter = build_adapter("anthropic", "greenhouse")
    adapter.collection_consent = CONSENT
    async with adapter:
        assert not isinstance(adapter.client._transport, CurlHttpxTransport)
        assert "sec-ch-ua" not in adapter.client.headers


@pytest.mark.asyncio
async def test_an_unconsented_adapter_builds_no_client(monkeypatch):
    _google_on(monkeypatch, FetchTier.TLS_FINGERPRINT)
    adapter = build_adapter("google", "google")
    with pytest.raises(PermissionError, match="walled"):
        async with adapter:
            pass
    assert adapter._client is None


@pytest.mark.asyncio
async def test_the_pipeline_records_a_missing_tier_as_unattempted(monkeypatch):
    monkeypatch.setattr(tiers, "_playwright_installed", lambda: False)
    _google_on(monkeypatch, FetchTier.HEADLESS)
    result = await collect_source(
        "google", {"adapter": "google", "consent": CONSENT}, STAFF_EM_SCOPE, NoComp(),
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, consent=None, **kw: build_adapter("google", "google", consent=consent),
    )
    assert result.stats["unattempted"] is True
    assert "playwright" in result.stats["policy_reason"]
    assert not result.stats["errors"], "our missing tier is not the source's error"


# --------------------------------------------------------------------------- #
# The TLS tier behaves like httpx
# --------------------------------------------------------------------------- #


class _StubResponse:
    def __init__(self, status: int, content: bytes, headers: list[tuple[str, str]], url: str = ""):
        self.status_code = status
        self.content = content
        self.headers = httpx.Headers(headers)
        self.url = url


class _StubSession:
    """A curl session that answers from a script and records what it was sent."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []
        self.closed = False

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def close(self):
        self.closed = True


def _tls_client(session: _StubSession) -> httpx.AsyncClient:
    return make_tier_client(
        CollectionAccess("x", tier=FetchTier.TLS_FINGERPRINT),
        headers=_HEADERS, timeout=7, session_factory=lambda: session,
    )


@pytest.mark.asyncio
async def test_curl_owns_identity_headers_and_httpx_owns_redirects_and_cookies():
    session = _StubSession([
        _StubResponse(302, b"", [("location", "https://h.test/next"), ("set-cookie", "sid=abc; Path=/")]),
        _StubResponse(200, b'{"ok": true}', [("content-encoding", "gzip"), ("content-length", "3")]),
    ])
    async with _tls_client(session) as client:
        response = await client.post("https://h.test/start", json={"q": 1}, headers={"X-Csrf": "t"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}, "curl decoded the body; httpx must not decode it again"
    first, second = session.calls
    assert first["method"] == "POST" and first["data"] == b'{"q":1}'
    assert first["allow_redirects"] is False and first["discard_cookies"] is True
    sent = {k.lower() for k in first["headers"]}
    assert "user-agent" not in sent and "accept-encoding" not in sent, "the profile owns identity"
    assert first["headers"]["x-csrf"] == "t" and first["headers"]["accept"] == "application/json"
    assert first["timeout"] == 7
    # httpx followed the redirect and carried the cookie curl was told to drop.
    assert second["url"] == "https://h.test/next"
    assert second["headers"]["cookie"] == "sid=abc"
    assert session.closed


@pytest.mark.asyncio
async def test_curl_failures_are_retried_as_httpx_network_errors():
    session = _StubSession([
        CurlConnectionError("reset"),
        CurlTimeout("slow"),
        _StubResponse(200, b"done", []),
    ])
    async with _tls_client(session) as client:
        response = await request_with_retry(
            client, "GET", "https://h.test/", retry=RetryPolicy(max_retries=2, max_backoff=0),
        )
    assert response.text == "done" and len(session.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [(CurlTimeout("slow"), httpx.ReadTimeout), (CurlConnectionError("reset"), httpx.ReadError)],
)
async def test_curl_errors_map_to_httpx_classes(error, expected):
    async with _tls_client(_StubSession([error])) as client:
        with pytest.raises(expected):
            await client.get("https://h.test/")


@pytest.mark.asyncio
async def test_a_bug_in_our_code_is_not_disguised_as_a_network_error():
    async with _tls_client(_StubSession([ValueError("our bug")])) as client:
        with pytest.raises(ValueError, match="our bug"):
            await client.get("https://h.test/")


def test_settings_ua_is_the_chrome_string_the_hints_describe():
    """BROWSER_HEADERS names Chrome 131; the configured UA must be the same browser."""
    assert "Chrome/131" in get_settings().scraper_user_agent


# --------------------------------------------------------------------------- #
# The headless tier behaves like httpx
# --------------------------------------------------------------------------- #


class _StubPage:
    """A page that answers `fetch()` from a script; `lands_on` simulates a root
    that redirects to another origin."""

    def __init__(self, origin: str, script: list, lands_on: str | None = None):
        self.url = "about:blank"
        self.origin = origin
        self.lands_on = lands_on
        self.script = list(script)
        self.gotos: list[str] = []
        self.fetches: list[dict] = []

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = self.lands_on if (self.lands_on and url.endswith("/")) else url

    async def evaluate(self, expression, arg=None):
        self.fetches.append(arg)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _page_result(status=200, body=b"", headers=(), url="https://h.test/x"):
    import base64

    return {"status": status, "url": url, "headers": list(headers), "body": base64.b64encode(body).decode()}


def _headless_client(page: _StubPage) -> httpx.AsyncClient:
    async def opener(origin):
        assert origin == page.origin, "one page per origin"
        return page

    return httpx.AsyncClient(
        headers=_HEADERS, timeout=7, transport=tiers.HeadlessHttpxTransport(opener),
    )


@pytest.mark.asyncio
async def test_headless_warms_the_origin_once_and_fetches_from_the_page():
    page = _StubPage("https://h.test", [
        _page_result(body=b'{"a": 1}', headers=[("content-encoding", "br"), ("content-type", "application/json")]),
        _page_result(body=b"second"),
    ])
    async with _headless_client(page) as client:
        first = await client.post(
            "https://h.test/api?q=1", content=b"\x00\xffbin", headers={"X-Csrf": "t", "Cookie": "c=1"},
        )
        second = await client.get("https://h.test/next")
    assert first.json() == {"a": 1}, "the page decoded the body; httpx must not decode it again"
    assert second.text == "second"
    assert page.gotos == ["https://h.test/"], "warm the origin once, then fetch in the page"
    sent = page.fetches[0]
    assert sent["url"] == "https://h.test/api?q=1" and sent["method"] == "POST"
    assert tiers.base64.b64decode(sent["body"]) == b"\x00\xffbin", "bytes survive the JSON bridge"
    names = {k.lower() for k in sent["headers"]}
    assert "x-csrf" in names
    assert not names & {"user-agent", "cookie", "accept-encoding", "host"}, "the browser owns these"
    assert page.fetches[1]["body"] is None


@pytest.mark.asyncio
async def test_a_root_on_another_origin_warms_on_the_request_url_instead():
    page = _StubPage("https://h.test", [_page_result(body=b"ok")], lands_on="https://sso.other.test/login")
    async with _headless_client(page) as client:
        await client.get("https://h.test/jobs?page=1")
    assert page.gotos == ["https://h.test/", "https://h.test/jobs?page=1"]


@pytest.mark.asyncio
async def test_a_page_that_never_answers_is_a_retryable_timeout():
    class _Hang(_StubPage):
        async def evaluate(self, expression, arg=None):
            import asyncio

            await asyncio.sleep(10)

    page = _Hang("https://h.test", [])
    client = httpx.AsyncClient(
        timeout=0.05,
        transport=tiers.HeadlessHttpxTransport(lambda origin: _async(page)),
    )
    async with client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get("https://h.test/")


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_a_bug_in_the_page_bridge_is_not_disguised_as_a_network_error():
    page = _StubPage("https://h.test", [KeyError("our bug")])
    async with _headless_client(page) as client:
        with pytest.raises(KeyError, match="our bug"):
            await client.get("https://h.test/")


@pytest.mark.asyncio
async def test_the_configured_proxy_reaches_the_tier_that_needs_it(monkeypatch):
    """`scraper_proxy_url` is only ever read on this path, so nothing else can
    show that it is read at all.

    Without the wiring the setting is unreachable: the adapter builds the tier
    client with no proxy, `unavailable_reason` reports the proxy "is not set",
    and the source is refused as unattempted no matter what the operator
    configured. That refusal reads as a deployment fault and is one.
    """
    from pydantic import SecretStr

    monkeypatch.setattr(tiers, "_playwright_installed", lambda: True)
    _google_on(monkeypatch, FetchTier.PROXY)
    adapter = build_adapter("google", "google")
    adapter.collection_consent = CONSENT

    # Unset, the tier refuses. It never falls back to fetching unproxied: the
    # proxy is the identity the source is being asked to accept.
    with pytest.raises(FetchTierUnavailable, match="scraper_proxy_url"):
        async with adapter:
            pass

    monkeypatch.setattr(
        adapter.settings, "scraper_proxy_url", SecretStr("http://u:s3cret@proxy.test:8080")
    )
    async with adapter:
        transport = adapter.client._transport
        assert isinstance(transport, tiers.HeadlessHttpxTransport)
        assert transport._owned._proxy_url == "http://u:s3cret@proxy.test:8080"

    # And the secret stays a secret: the tier is named, the URL is not.
    assert "s3cret" not in repr(adapter.settings.scraper_proxy_url)
