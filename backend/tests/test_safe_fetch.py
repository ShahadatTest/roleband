"""A user-supplied URL may reach the public internet and nothing else.

Every case runs through the real `public_client` (real httpx client, real
httpcore pool) with the network replaced at the lowest level — the resolver and
the backend the guard wraps — so a guard that is bypassed fails here rather
than fetching. No test touches the network.
"""

from __future__ import annotations

import pytest

from tests.fake_network import RecordingBackend, scripted_resolver
from tracker.platform.safe_fetch import (
    BlockedDestination,
    PublicOnlyBackend,
    check_url,
    fetch_public,
    public_client,
)

PUBLIC = "93.184.216.34"


def _http(status: str, headers: dict[str, str] | None = None, body: bytes = b"") -> list[bytes]:
    head = f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    return [(head + "\r\n").encode(), body]


def _client(backend) -> object:
    return public_client(user_agent="test", backend=backend)


@pytest.mark.asyncio
async def test_the_real_client_refuses_this_machine():
    """No injected backend: the default guard, inside a real client. If httpx
    stopped honouring the pool swap this would try to connect and raise a
    ConnectError instead — and the API on :8010 would be one redirect away."""
    async with public_client(user_agent="test") as client:
        with pytest.raises(BlockedDestination):
            await fetch_public(client, "http://127.0.0.1/")


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "100.64.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1",
    "224.0.0.1",
])
async def test_a_name_that_resolves_to_a_non_public_address_is_refused(address):
    resolve, _ = scripted_resolver({"careers.example.com": [address]})
    backend = RecordingBackend(_http("200 OK", body=b"never served"))
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        with pytest.raises(BlockedDestination):
            await fetch_public(client, "https://careers.example.com/jobs")
    assert backend.connected == []


@pytest.mark.asyncio
async def test_one_private_answer_among_public_ones_is_refused():
    resolve, _ = scripted_resolver({"careers.example.com": [PUBLIC, "10.0.0.5"]})
    backend = RecordingBackend(_http("200 OK"))
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        with pytest.raises(BlockedDestination):
            await fetch_public(client, "http://careers.example.com/")
    assert backend.connected == []


@pytest.mark.asyncio
async def test_the_connection_goes_to_the_vetted_address_not_the_name():
    """DNS rebinding: a name checked public and then re-resolved private. The
    guard connects to the address it checked, so there is no second lookup."""
    resolve, calls = scripted_resolver({"careers.example.com": [PUBLIC]})
    backend = RecordingBackend(_http("200 OK", {"Content-Type": "text/html"}, b"<html>jobs</html>"))
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        page = await fetch_public(client, "http://careers.example.com/careers")

    assert backend.connected == [PUBLIC]
    assert calls == ["careers.example.com"]
    assert (page.status, page.text, page.final_url) == (200, "<html>jobs</html>", "http://careers.example.com/careers")


@pytest.mark.asyncio
async def test_a_redirect_to_an_internal_host_is_refused_at_the_hop():
    resolve, _ = scripted_resolver({"careers.example.com": [PUBLIC], "internal.example.com": ["10.1.2.3"]})
    backend = RecordingBackend(_http("302 Found", {"Location": "http://internal.example.com/admin"}))
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        with pytest.raises(BlockedDestination):
            await fetch_public(client, "http://careers.example.com/")
    assert backend.connected == [PUBLIC]


@pytest.mark.asyncio
async def test_a_redirect_to_the_local_api_port_is_refused_before_connecting():
    resolve, _ = scripted_resolver({"careers.example.com": [PUBLIC]})
    backend = RecordingBackend(_http("301 Moved", {"Location": "http://127.0.0.1:8010/api/companies"}))
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        with pytest.raises(BlockedDestination):
            await fetch_public(client, "http://careers.example.com/")
    assert backend.connected == [PUBLIC]


@pytest.mark.asyncio
async def test_a_public_redirect_is_followed_and_reported():
    resolve, _ = scripted_resolver({"careers.example.com": [PUBLIC], "jobs.example.com": [PUBLIC]})
    backend = RecordingBackend(
        _http("302 Found", {"Location": "https://jobs.example.com/en/careers"}),
        _http("200 OK", {"Content-Type": "text/html"}, b"ok"),
    )
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        page = await fetch_public(client, "http://careers.example.com/")
    assert page.final_url == "https://jobs.example.com/en/careers"
    assert page.text == "ok"


@pytest.mark.asyncio
async def test_the_body_is_capped():
    resolve, _ = scripted_resolver({"careers.example.com": [PUBLIC]})
    backend = RecordingBackend(_http("200 OK", {"Content-Type": "text/html"}, b"x" * 5000))
    async with _client(PublicOnlyBackend(inner=backend, resolve=resolve)) as client:
        page = await fetch_public(client, "http://careers.example.com/", max_bytes=1000)
    assert page.truncated and len(page.text) == 1000


@pytest.mark.parametrize("url", [
    "ftp://careers.example.com/",
    "file:///etc/passwd",
    "https://user:pass@careers.example.com/",
    "https://careers.example.com:8443/",
    "http://careers.example.com:8010/",
    "https:///nohost",
    "javascript:alert(1)",
])
def test_a_url_shape_that_is_never_fetched(url):
    with pytest.raises(BlockedDestination):
        check_url(url)


def test_default_ports_are_allowed():
    assert check_url("https://careers.example.com:443/jobs") == "https://careers.example.com:443/jobs"
    assert check_url("http://careers.example.com/jobs") == "http://careers.example.com/jobs"
