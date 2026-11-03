"""Stable connector SDK value types.

The hard rule this module exists to enforce: **no transport object crosses the
SDK boundary**. Connectors see `FetchRequest`/`FetchResponse`/`FetchStream` and
never an `httpx.Response`, a `curl_cffi` response, a Scrapling `Response`, a DB
session, or a pipeline object. That is what lets the transport under a connector
change (httpx -> curl impersonation -> render service) without touching it.

`FetchResponse` carries bytes and has no `select()`: parsing belongs to
`connectors.extract`, outside the SDK contract.
"""

from __future__ import annotations

import json as _json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "FetchRequest",
    "FetchResponse",
    "FetchStream",
    "ListingResult",
    "TransportPolicy",
    "redact_meta",
]

#: Keys whose values are credential-bearing and must never reach a log, an API
#: response, a recipe document, or a stored diagnostic.
_REDACTED_KEYS = frozenset({"proxy", "proxy_url", "authorization", "cookie", "token"})
_REDACTED = "[redacted]"


def redact_meta(meta: Mapping[str, object] | None) -> dict[str, object]:
    """Strip credential-bearing values by construction.

    Proxy values are never stored in recipe JSON, returned by the API or logged.
    Redaction lives here rather than at each call site so a new transport cannot
    forget it -- `FetchResponse` runs every `meta` through this in `__post_init__`.
    """
    if not meta:
        return {}
    return {
        key: (_REDACTED if key.lower() in _REDACTED_KEYS else value)
        for key, value in meta.items()
    }


class TransportPolicy(str, Enum):
    """Per-source transport selection.

    No automatic escalation between modes: a block is an observable failure, not
    permission to increase evasion. Moving a source to a stronger mode is an
    explicit, recorded per-source decision.
    """

    STATIC_HTTP = "static_http"
    STATIC_IMPERSONATE = "static_impersonate"
    STREAM_HTTP = "stream_http"
    RENDER = "render"


@dataclass(frozen=True)
class FetchRequest:
    """One transport-neutral request."""

    url: str
    method: str = "GET"
    headers: Mapping[str, str] | None = None
    query: Mapping[str, object] | None = None
    body: object | None = None
    json_body: object | None = None
    timeout: float | None = None
    transport_policy: TransportPolicy = TransportPolicy.STATIC_HTTP
    source_key: str | None = None


@dataclass(frozen=True)
class FetchResponse:
    """Buffered response. Carries bytes, never a live transport object."""

    status: int
    final_url: str
    headers: Mapping[str, str]
    content: bytes
    elapsed_ms: int = 0
    attempts: int = 1
    transport: str = TransportPolicy.STATIC_HTTP.value
    meta: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Frozen dataclass: redact through object.__setattr__ so no construction
        # path can hand back an unredacted meta.
        object.__setattr__(self, "meta", redact_meta(self.meta))

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self, encoding: str = "utf-8") -> str:
        return self.content.decode(encoding, errors="replace")

    def json(self) -> object:
        return _json.loads(self.content)


@dataclass
class FetchStream:
    """Streaming response: explicit capability, never implicit.

    Held open by the transport's context manager; `iter_bytes` is valid only
    inside that scope.
    """

    status: int
    final_url: str
    headers: Mapping[str, str]
    iter_bytes: AsyncIterator[bytes]
    transport: str = TransportPolicy.STREAM_HTTP.value

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass(frozen=True)
class ListingResult:
    """Outcome of one listing pass.

    `list_complete` is closure evidence and nothing else: it means the source
    served a complete, uncapped, error-free listing. Capped, deferred, timed-out
    and drifted passes are incomplete and must never authorize closure by
    absence.
    """

    jobs: tuple
    list_complete: bool
    diagnostics: Mapping[str, object] = field(default_factory=dict)
