"""A failed read during a network outage is suspended, not a source failure.

* No anomaly, backoff or closure follows an outage.
* The same failure with a working network remains attributable to the source.
* Successful reads and explicit refusals need no outage probe.
* The rest of the affected lane is deferred; other lanes judge independently
  because a filtered job site does not prove every careers page unreachable.

Sources are fakes; `outage.network_up` supplies the probe answer per test.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest

from tests.factories import scope_filter
from tracker.connectors.listing.base import SchemaDriftDetector
from tracker.connectors.recipes.outcome import (
    RESETS_ABSENCE,
    SourceOutcome,
    classify_source_outcome,
)
from tracker.platform.breaker import CircuitOpenError
from tracker.schema import RawJob
from tracker.workflows import directory_sweep, outage
from tracker.workflows.collection import collect_sources
from tracker.workflows.collection_types import OFFLINE_ERROR, empty_stats
from tracker.workflows.scheduler import pressure_transition

EMPTY_SCOPE = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())


class _Source:
    """A listing that serves one posting, or raises `error` before any."""

    def __init__(self, company: str, error: Exception | None = None) -> None:
        self.company, self.error = company, error
        self.drift = SchemaDriftDetector(f"fixture:{company}")
        self.truncated = False
        self.query_observations: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        if self.error is not None:
            raise self.error
        yield RawJob(company=self.company, req_id="1", title="Staff Engineer",
                     url=f"https://example.test/{self.company}/1", locations=["Berlin, Germany"])


def _network(monkeypatch, up: bool) -> list[bool]:
    """The probe answers `up`; returns each answer it gave."""
    asked: list[bool] = []

    async def network_up(timeout: float = 5.0) -> bool:
        asked.append(up)
        return up

    monkeypatch.setattr(outage, "network_up", network_up)
    return asked


def _dropped(request_host: str = "boards-api.greenhouse.io") -> httpx.ConnectError:
    return httpx.ConnectError(
        "[Errno 8] nodename nor servname provided", request=httpx.Request("GET", f"https://{request_host}/")
    )


async def _collect(targets: dict, failing: dict[str, Exception]) -> tuple[dict, list[str]]:
    built: list[str] = []

    def factory(company, adapter, board_token=None, **_kw):
        built.append(company)
        return _Source(company, failing.get(company))

    collections = await collect_sources(
        targets, EMPTY_SCOPE, object(), max_list=None, hydrate=False,
        max_concurrent_sources=8, adapter_factory=factory,
    )
    return collections, built


def _outcome(collection) -> SourceOutcome:
    return classify_source_outcome({**collection.stats, "list_complete": collection.list_complete})


def _gh(name: str) -> dict:
    return {"adapter": "greenhouse", "board_token": name}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("up", "outcome", "resets", "pressure"),
    [
        # Ours: no posting's count is reset, and the provider is not backed off.
        (False, SourceOutcome.SUSPENDED, False, "ready"),
        # The control: the network answers, so the failure is the source's.
        (True, SourceOutcome.FAILED, True, "backoff"),
    ],
)
async def test_a_read_that_fails_while_no_job_site_answers_is_ours(monkeypatch, up, outcome, resets, pressure):
    asked = _network(monkeypatch, up)

    collections, _ = await _collect({"acme": _gh("acme")}, {"acme": _dropped()})

    acme = collections["acme"]
    assert asked == [up], "asked once, about the failed read"
    assert _outcome(acme) is outcome
    assert bool(acme.stats.get("offline")) is not up
    assert not acme.list_complete, "closure is never authorized by a failed read"
    assert (outcome in RESETS_ABSENCE) is resets
    transition = pressure_transition(
        outcome, now=datetime.now(UTC), consecutive_events=0, backoff_seconds=900, blocked_cooldown_seconds=3600,
    )
    assert transition.state == pressure


@pytest.mark.asyncio
async def test_a_read_that_did_not_fail_never_asks(monkeypatch):
    asked = _network(monkeypatch, False)

    collections, _ = await _collect({"acme": _gh("acme")}, {})

    assert _outcome(collections["acme"]) is SourceOutcome.OK and asked == []


@pytest.mark.asyncio
async def test_a_site_refusing_us_is_the_sites_and_never_asks(monkeypatch):
    """A uniform refusal is answered requests: the network is up by definition."""
    asked = _network(monkeypatch, False)

    collections, _ = await _collect(
        {"acme": _gh("acme")}, {"acme": CircuitOpenError("greenhouse", 5, blocked=True)},
    )

    assert _outcome(collections["acme"]) is SourceOutcome.BLOCKED and asked == []


@pytest.mark.asyncio
async def test_the_rest_of_the_lane_waits_and_other_lanes_read_on(monkeypatch):
    """One host per shared lane: the companies behind a read the outage cut
    would fail the same way, so they wait for the next tick. Another lane
    judges for itself: a network that filters job sites still lets a careers
    page through, and one lane's verdict must not stop it."""
    _network(monkeypatch, False)
    targets = {
        "acme": _gh("acme"), "beta": _gh("beta"), "gamma": _gh("gamma"),
        "delta": {"adapter": "ashby", "board_token": "delta"},
        "eps": {"adapter": "ashby", "board_token": "eps"},
    }

    collections, built = await _collect(targets, {"acme": _dropped()})

    assert _outcome(collections["acme"]) is SourceOutcome.SUSPENDED
    for company in ("beta", "gamma"):
        stats = collections[company].stats
        assert company not in built, "never started"
        assert _outcome(collections[company]) is SourceOutcome.UNATTEMPTED
        assert stats["offline"] and stats["errors"] == [OFFLINE_ERROR] and stats["deferred_reason"]
    assert {_outcome(collections[c]) for c in ("delta", "eps")} == {SourceOutcome.OK}


@pytest.mark.asyncio
async def test_while_the_network_answers_a_failure_stops_nothing(monkeypatch):
    _network(monkeypatch, True)

    collections, built = await _collect(
        {"acme": _gh("acme"), "beta": _gh("beta")}, {"acme": _dropped()},
    )

    assert built == ["acme", "beta"]
    assert (_outcome(collections["acme"]), _outcome(collections["beta"])) == (
        SourceOutcome.FAILED, SourceOutcome.OK)


def test_offline_never_masks_a_read_that_completed():
    """The flag explains errors; a complete, error-free listing stays `ok`."""
    stats = {**empty_stats(), "scanned": 10, "offline": True, "list_complete": True}
    assert classify_source_outcome(stats) is SourceOutcome.OK
    assert classify_source_outcome({**stats, "errors": ["ConnectError"], "list_complete": False}) is (
        SourceOutcome.SUSPENDED)


@pytest.mark.asyncio
async def test_the_probe_answers_at_the_first_host_that_accepts(monkeypatch):
    """A host that hangs must not hold up the answer, or every failed read
    would wait out the slowest of five connection timeouts."""
    async def reach(host, timeout):
        if host == outage.PROBE_HOSTS[2]:
            return True
        await asyncio.sleep(10)
        return False

    monkeypatch.setattr(outage, "_reach", reach)
    began = time.monotonic()

    assert await outage.network_up() is True
    assert time.monotonic() - began < 1


@pytest.mark.asyncio
async def test_the_probe_says_down_only_when_no_host_accepts(monkeypatch):
    async def reach(host, timeout):
        return False

    monkeypatch.setattr(outage, "_reach", reach)

    assert await outage.network_up() is False


def test_the_directory_scan_and_the_collector_ask_the_same_probe():
    assert directory_sweep.network_up is outage.network_up
