"""Fetch a page whose URL a user supplied, and nothing else.

A pasted careers URL is the first input RoleBand fetches that neither code nor a
reviewed register chose. Its host, and every redirect it answers with, is
attacker-influenced: pointed at `127.0.0.1:8010` it reaches this machine's own
API, at `169.254.169.254` a cloud metadata service, at `192.168.x.x` the
user's router. So this fetch refuses every destination that is not a public
internet address, and it decides that at CONNECT time, on the address it then
connects to:

* the name is resolved here and EVERY address it answers with must be public
  (`ip_address.is_global`), because a resolver that answers one public and one
  private address can be steered between them;
* the connection is opened to that vetted address, not to the name — a second
  lookup is how DNS rebinding turns a checked name into an unchecked address.
  TLS still verifies the certificate against the name (httpcore passes the
  request's host as `server_hostname`, independent of the connect address);
* redirects are followed by hand, each hop re-checked for scheme, port and
  credentials, and each hop's connection re-vetted by the same backend;
* http/https on their default ports only, no userinfo, no proxy from the
  environment, a body cap and a timeout.

Product-agnostic: no tracker module is imported (platform rule).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import urljoin, urlsplit

import anyio
import httpcore
import httpx

__all__ = ["BlockedDestination", "PublicPage", "PublicOnlyBackend", "fetch_public", "public_client", "public_transport"]

DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_PORTS = {"http": 80, "https": 443}

#: `(host, port) -> addresses`. Injected in tests; the default asks the system resolver.
Resolver = Callable[[str, int], Awaitable[Iterable[str]]]


class BlockedDestination(Exception):
    """The URL, a redirect, or an address it resolved to is not public."""


@dataclass(frozen=True)
class PublicPage:
    final_url: str
    status: int
    text: str
    truncated: bool


async def _system_resolve(host: str, port: int) -> list[str]:
    try:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        # An unknown name is an ordinary network failure (httpx.ConnectError),
        # not a crash in the caller.
        raise httpcore.ConnectError(f"{host}: {exc}") from exc
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    # An IPv4-mapped IPv6 address (`::ffff:127.0.0.1`) is judged as the IPv4
    # address it carries, which is where the packets go.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Resolve, vet every address, connect to the vetted one."""

    def __init__(
        self,
        inner: httpcore.AsyncNetworkBackend | None = None,
        resolve: Resolver | None = None,
    ) -> None:
        self._inner = inner or httpcore.AnyIOBackend()
        # Looked up at call time, not bound here, so the test suite's default
        # (`tests/conftest.py`: no test resolves a name) reaches every client.
        self._resolve = resolve

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            ipaddress.ip_address(host.split("%", 1)[0])
            addresses = [host]
        except ValueError:
            resolve = self._resolve or _system_resolve
            addresses = list(await resolve(host, port))
        if not addresses:
            raise BlockedDestination(f"{host} resolved to no address")
        blocked = [a for a in addresses if not _is_public(a)]
        if blocked:
            raise BlockedDestination(f"{host} resolves to a non-public address ({blocked[0]})")
        return await self._inner.connect_tcp(
            addresses[0], port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,  # type: ignore[arg-type]
        )

    async def connect_unix_socket(self, *args: object, **kwargs: object) -> NoReturn:
        raise BlockedDestination("unix sockets are never a public destination")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def public_transport(
    backend: httpcore.AsyncNetworkBackend | None = None,
) -> httpx.AsyncHTTPTransport:
    """A transport whose every connection goes through the public-only backend.

    httpx does not expose `network_backend`, so the transport's pool is replaced
    with one that has it; `tests/test_safe_fetch.py` connects to a loopback
    address through a real client, so an httpx that stopped honouring the swap
    fails there rather than silently fetching.
    """
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(  # noqa: SLF001 - see docstring
        ssl_context=httpx.create_ssl_context(),
        network_backend=backend or PublicOnlyBackend(),
        max_connections=4,
    )
    return transport


def public_client(
    *,
    user_agent: str,
    timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
    backend: httpcore.AsyncNetworkBackend | None = None,
) -> httpx.AsyncClient:
    """Public destination pinning, also reusable by paced/deduplicating callers."""
    return httpx.AsyncClient(
        transport=public_transport(backend),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": user_agent, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"},
    )


def check_url(url: str) -> str:
    """The URL, normalised, if its shape may be fetched at all; else raise."""
    parts = urlsplit(url.strip())
    if parts.scheme not in _DEFAULT_PORTS:
        raise BlockedDestination(f"scheme {parts.scheme!r} is not fetched")
    if parts.username is not None or parts.password is not None:
        raise BlockedDestination("a URL carrying credentials is not fetched")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedDestination("malformed port") from exc
    if port not in (None, _DEFAULT_PORTS[parts.scheme]):
        raise BlockedDestination(f"port {port} is not fetched")
    if not parts.hostname:
        raise BlockedDestination("no host")
    try:
        address = ipaddress.ip_address(parts.hostname.split("%", 1)[0])
    except ValueError:
        pass  # Names are checked and pinned by PublicOnlyBackend at connect time.
    else:
        if not _is_public(str(address)):
            raise BlockedDestination("non-public address")
    return parts.geturl()


async def fetch_public(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str = "GET",
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    validate_url: Callable[[str], None] | None = None,
    # httpx's own request options, handed to `AsyncClient.stream` as given.
    **request_kwargs: Any,
) -> PublicPage:
    """Fetch `url` through a `public_client`, following redirects by hand.

    Raises `BlockedDestination` for a refused URL, hop or address, and lets
    `httpx.HTTPError` through for an ordinary network failure. A redirect turns
    the request into a GET, as browsers do for 301/302/303.
    """
    current = check_url(url)
    for _ in range(max_redirects + 1):
        if validate_url is not None:
            validate_url(current)
        async with client.stream(method, current, follow_redirects=False, **request_kwargs) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise BlockedDestination("redirect without a Location")
                current = check_url(urljoin(current, location))
                method, request_kwargs = "GET", {}
                continue
            body = bytearray()
            truncated = False
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    del body[max_bytes:]
                    truncated = True
                    break
            encoding = response.encoding or "utf-8"
            return PublicPage(
                final_url=current,
                status=response.status_code,
                text=bytes(body).decode(encoding, errors="replace"),
                truncated=truncated,
            )
    raise BlockedDestination(f"more than {max_redirects} redirects")
