"""Concrete `ConnectorContext`.

Binds one transport + one pacer + one drift sink into the single object a
connector is allowed to touch. Capability negotiation happens here, at
construction, so a connector that needs streaming against an impersonated
transport fails loudly at load instead of raising `NotImplementedError`
mid-listing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from tracker.connectors.sdk.context import DriftSink, Transport
from tracker.connectors.sdk.types import FetchRequest, FetchResponse, FetchStream
from tracker.connectors.sdk.version import Capabilities, negotiate
from tracker.platform.ratelimit import RateLimiter
from tracker.source_policy import CollectionAccess, collection_access

__all__ = ["RuntimeContext"]


class RuntimeContext:
    """Runtime-side implementation of the `ConnectorContext` protocol."""

    def __init__(
        self,
        *,
        transport: Transport,
        drift: DriftSink,
        limiter: RateLimiter | None = None,
        run_id: int | None = None,
        required_capabilities: Capabilities | None = None,
        connector_name: str = "connector",
        access: CollectionAccess | None = None,
    ) -> None:
        self._transport = transport
        self._access = access if access is not None else collection_access(connector_name)
        self._limiter = limiter
        self.drift = drift
        self.run_id = run_id
        self.capabilities = (
            negotiate(
                provided=transport.capabilities,
                required=required_capabilities,
                connector_name=connector_name,
            )
            if required_capabilities is not None
            else transport.capabilities
        )

    @property
    def transport_name(self) -> str:
        return self._transport.name

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self._access.require()
        return await self._transport.send(request)

    @asynccontextmanager
    async def stream(self, request: FetchRequest) -> AsyncIterator[FetchStream]:
        self._access.require()
        if not self.capabilities.stream:
            raise NotImplementedError(f"{self._transport.name} does not provide streaming")
        async with self._transport.open_stream(request) as stream:
            yield stream

    async def pace(self) -> None:
        """Explicit politeness wait.

        Transports already pace every attempt; this is for connectors that do
        non-fetch work between requests and still owe the source a delay.
        """
        if self._limiter is not None:
            await self._limiter.wait()
