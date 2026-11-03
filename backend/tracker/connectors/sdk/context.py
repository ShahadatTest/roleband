"""Connector-facing protocols.

`ConnectorContext` is the entire surface a connector may touch. It hands over
fetching, pacing and drift recording -- and nothing else. No DB session, no
pipeline object, no settings mutation, no transport handle.

These are `typing.Protocol`s: a connector depends on the shape, not on a
concrete runtime class, so the runtime can be swapped (and faked in tests)
without touching connector code.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from tracker.connectors.sdk.types import (
    FetchRequest,
    FetchResponse,
    FetchStream,
    ListingResult,
)
from tracker.connectors.sdk.version import Capabilities

__all__ = ["ConnectorContext", "DriftSink", "ListingConnector", "Transport"]


@runtime_checkable
class DriftSink(Protocol):
    """Source-drift recording. Drift belongs in the run record, not in logs."""

    def require(self, condition: bool, message: str, **context) -> None: ...

    def note(self, message: str, **context) -> None: ...

    def invalidate_listing(self, message: str, **context) -> None:
        """Mark the listing incomplete, so it cannot authorize closure."""

    def drop_record(self, message: str, **context) -> None:
        """Record one unusable item inside an otherwise-served listing.

        Suppresses closure like `invalidate_listing`, but keeps the loss
        countable so a handful of bad rows is not read as a broken source.
        """


@runtime_checkable
class Transport(Protocol):
    """One transport mode. Implementations live in `connectors.runtime`."""

    name: str
    capabilities: Capabilities

    async def send(self, request: FetchRequest) -> FetchResponse: ...

    def open_stream(
        self, request: FetchRequest
    ) -> AbstractAsyncContextManager[FetchStream]: ...


@runtime_checkable
class ConnectorContext(Protocol):
    """Everything a connector is allowed to reach."""

    capabilities: Capabilities
    drift: DriftSink
    run_id: int | None

    async def fetch(self, request: FetchRequest) -> FetchResponse: ...

    def stream(self, request: FetchRequest) -> AbstractAsyncContextManager[FetchStream]: ...

    async def pace(self) -> None:
        """Wait out the source's politeness budget."""


@runtime_checkable
class ListingConnector(Protocol):
    """The listing shape a connector built on the SDK implements.

    Adapters built on `BaseAdapter` expose `fetch()`/`hydrate()` instead;
    `collect` and `as_listing_result` bridge the two.
    """

    name: str
    connector_api_version: int
    required_capabilities: Capabilities

    async def list(self, context: ConnectorContext, company: str) -> ListingResult: ...

    async def hydrate(self, context: ConnectorContext, raw_job) -> object: ...


def as_listing_result(jobs: Sequence, *, list_complete: bool, **diagnostics) -> ListingResult:
    """Small helper so connectors do not hand-build the frozen dataclass."""
    return ListingResult(
        jobs=tuple(jobs), list_complete=list_complete, diagnostics=dict(diagnostics)
    )


async def collect(iterator: AsyncIterator) -> list:
    """Drain an async iterator (adapter `fetch()`) into a list."""
    return [item async for item in iterator]
