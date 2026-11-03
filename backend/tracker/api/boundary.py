"""The loopback trust boundary.

The API authenticates nobody: one user, one machine, served on 127.0.0.1.
That model holds only while a web page the user happens to visit cannot reach
it, and a page can, two ways that CORS never sees:

1. DNS rebinding. A hostile name re-resolves to 127.0.0.1 after its page has
   loaded. The page is then SAME-origin with this API, so no CORS rule runs;
   what still differs is the Host header, which names the hostile host. A
   request is served only when its Host names this machine.
2. Cross-site simple requests. A form post, or a `no-cors` fetch, sends a POST
   with no preflight. The page never reads the answer, but the side effect
   lands, and many unsafe routes take no body at all, so "the routes take
   JSON" is no defence. An unsafe request is refused
   when the browser names a page on another host (`Origin`), and when it
   carries a content type only a no-preflight request needs.

Ports are deliberately not part of either match: an attacker controls the name
in the URL, not which port on this machine it lands on, and a second dev
server on another port is ours.

Starlette's `TrustedHostMiddleware` is not used: it covers only the first rule,
and it matches the IPv6 loopback only when the allow-list spells it `[::1]`.
One host parser here serves both rules, the Host header and `Origin` alike.

`tests/test_api_trust_boundary.py` walks every unsafe route in the frozen route
table, so a route added later is inside the boundary by default.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

#: The names a machine answers to for itself. Always trusted: configuration
#: adds names (`api_host`, `api_trusted_hosts`), it never removes these.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The request content types a page may send without a CORS preflight (the Fetch
#: standard's safelisted `Content-Type` values). The dashboard sends
#: `application/json` or no body at all (`dashboard/src/api/transport.ts` `requestJSON`), and no route
#: reads a form, so refusing these costs no legitimate client anything.
SIMPLE_CONTENT_TYPES = frozenset(
    {"application/x-www-form-urlencoded", "multipart/form-data", "text/plain"}
)


def host_name(authority: str) -> str | None:
    """The host in a Host header or URL authority, lower-cased; None if malformed.

    `[::1]:8010` -> `::1`, `localhost:5173` -> `localhost`. Anything after the
    host other than `:<digits>` makes the whole value malformed, so a name that
    merely STARTS like a loopback literal (`[::1].evil.example`) is not one.
    """
    value = authority.strip().lower()
    if value.startswith("["):
        name, bracket, rest = value[1:].partition("]")
        if not bracket:
            return None
    else:
        name, colon, port = value.partition(":")
        rest = colon + port
    if rest and not (rest.startswith(":") and rest[1:].isdigit()):
        return None
    return name.rstrip(".") or None


def _origin_host(origin: str) -> str | None:
    """The host of an `Origin` header; None for `null` and anything unparseable."""
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return host_name(parts.netloc)


class LoopbackBoundary:
    """ASGI middleware refusing what crossed the loopback. Mount it outermost."""

    def __init__(self, app: ASGIApp, *, trusted_hosts: Iterable[str] = ()) -> None:
        self.app = app
        extra = {host_name(host) for host in trusted_hosts}
        self.trusted = LOOPBACK_HOSTS | {host for host in extra if host}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        refusal = self._refusal(scope, Headers(scope=scope))
        if refusal is None:
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            status, reason = refusal
            await PlainTextResponse(reason, status_code=status)(scope, receive, send)

    def _refusal(self, scope: Scope, headers: Headers) -> tuple[int, str] | None:
        if host_name(headers.get("host", "")) not in self.trusted:
            return 400, "Invalid host header"
        if scope["type"] == "http" and scope["method"] in SAFE_METHODS:
            return None
        # A browser names the page behind every unsafe request and every
        # WebSocket handshake; a client with no page (curl, a script) sends none.
        origin = headers.get("origin")
        if origin is not None and _origin_host(origin) not in self.trusted:
            return 403, "Cross-site request refused"
        if scope["type"] == "http":
            media_type = headers.get("content-type", "").partition(";")[0].strip().lower()
            if media_type in SIMPLE_CONTENT_TYPES:
                return 415, "Unsafe requests must send JSON or no body"
        return None
