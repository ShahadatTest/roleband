"""Public connector SDK: the stable contracts a connector is written against.

This package is the contributor-facing surface. Connectors import from
`tracker.connectors.sdk` and nothing deeper: `connectors.runtime` is private
implementation, and `tests/test_connector_sdk.py` asserts no connector reaches
into it.
"""

from __future__ import annotations

from tracker.connectors.sdk.context import (
    ConnectorContext,
    DriftSink,
    ListingConnector,
    Transport,
    as_listing_result,
    collect,
)
from tracker.connectors.sdk.types import (
    FetchRequest,
    FetchResponse,
    FetchStream,
    ListingResult,
    TransportPolicy,
    redact_meta,
)
from tracker.connectors.sdk.version import (
    CONNECTOR_API_VERSION,
    Capabilities,
    CapabilityError,
    negotiate,
)

__all__ = [
    "CONNECTOR_API_VERSION",
    "Capabilities",
    "CapabilityError",
    "ConnectorContext",
    "DriftSink",
    "FetchRequest",
    "FetchResponse",
    "FetchStream",
    "ListingConnector",
    "ListingResult",
    "Transport",
    "TransportPolicy",
    "as_listing_result",
    "collect",
    "negotiate",
    "redact_meta",
]
