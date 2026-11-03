"""Private connector runtime.

Transport implementations, the fetch tiers, and the concrete
`ConnectorContext`. Retry and backoff are `tracker.platform.http`'s, shared by
every transport here. **Connectors must not import from this package** -- they
import `tracker.connectors.sdk` and receive a context. The import rule is
asserted by `tests/test_connector_sdk.py`.
"""

from __future__ import annotations

from tracker.connectors.runtime.context import RuntimeContext
from tracker.connectors.runtime.httpx_transport import HttpxTransport, to_fetch_response

__all__ = [
    "HttpxTransport",
    "RuntimeContext",
    "to_fetch_response",
]
