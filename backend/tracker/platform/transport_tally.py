"""What one source's reads cost: completed requests, retries, response bytes,
and the latest moment a provider asked us to stay away (`Retry-After`).

The shared retry loops (`platform.http.request_with_retry` and
`stream_with_retry`, which every fetch tier runs under) report here; the
collection of one source opens a tally around its reads (`tally_transport`) and
copies it into the source's stats. A context variable carries it, so a detail
fetch the adapter runs in a task of its own counts toward the same source, and
a read outside any collection (a plugin's fetch, a CLI probe) counts nowhere.

Only counts, sizes and the time are kept: never a header value beyond
`Retry-After`, a cookie, a token or a body.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any


@dataclass
class TransportTally:
    requests: int = 0
    retries: int = 0
    bytes_received: int = 0
    retry_after_until: datetime | None = None

    def stats(self) -> dict[str, Any]:
        """The source's stats keys. A source whose reads never reached a shared
        transport records None for each count: unknown, never zero."""
        counted = self.requests > 0 or self.retries > 0
        return {
            "requests": self.requests if counted else None,
            "retries": self.retries if counted else None,
            "bytes_received": self.bytes_received if counted else None,
            "retry_after_until": self.retry_after_until.isoformat() if self.retry_after_until else None,
        }


_current: ContextVar[TransportTally | None] = ContextVar("transport_tally", default=None)


@contextmanager
def tally_transport() -> Iterator[TransportTally]:
    """Count the reads made inside this block, and in the tasks it starts."""
    tally = TransportTally()
    token = _current.set(tally)
    try:
        yield tally
    finally:
        _current.reset(token)


def retry_after_seconds(value: str | None, now: datetime) -> float | None:
    """`Retry-After` in seconds from `now`: the delta-seconds form or the
    HTTP-date form; None for anything else. A date already past is 0."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def _header(headers: Mapping[str, str] | Any, name: str) -> str | None:
    if headers is None:
        return None
    return headers.get(name) or headers.get(name.lower())


def note_response(nbytes: int | None, headers: Mapping[str, str] | Any = None) -> None:
    """One completed request: its body size and any `Retry-After` it carried."""
    tally = _current.get()
    if tally is None:
        return
    tally.requests += 1
    tally.bytes_received += max(0, int(nbytes or 0))
    now = datetime.now(UTC)
    seconds = retry_after_seconds(_header(headers, "Retry-After"), now)
    if seconds is not None:
        until = now + timedelta(seconds=seconds)
        if tally.retry_after_until is None or until > tally.retry_after_until:
            tally.retry_after_until = until


def note_retry() -> None:
    """One more attempt at a request that already failed once."""
    tally = _current.get()
    if tally is not None:
        tally.retries += 1


def note_bytes(nbytes: int | None) -> None:
    """Body bytes of a streamed response, counted once it is read."""
    tally = _current.get()
    if tally is not None:
        tally.bytes_received += max(0, int(nbytes or 0))
