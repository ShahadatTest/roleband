"""Tenant-hosted families run tenants side by side; shared hosts never do."""

from __future__ import annotations

import asyncio

import pytest

from tests.factories import scope_filter
from tracker.connectors.listing.base import SchemaDriftDetector
from tracker.provider_pacing import pacing_for
from tracker.workflows.collection import collect_sources, collector_lanes
from tracker.workflows.collection_types import RunLookups, SourceCost

EMPTY_SCOPE = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())


def _wd(host: str, site: str = "External") -> dict:
    return {"adapter": "workday", "board_token": f"{host}|{site}"}


def _members(lanes) -> list[set[str]]:
    return [{company for company, _ in queue} for queue in lanes.values()]


def test_a_shared_host_backend_is_one_stream_whatever_its_depth():
    lanes = collector_lanes({s: {"adapter": "greenhouse", "board_token": s} for s in "abcdef"})
    assert _members(lanes) == [set("abcdef")]


def test_tenant_hosts_spread_up_to_the_declared_width_and_one_host_never_splits():
    targets = {
        "snap": _wd("wd1.myworkdaysite.com", "snap|snapchat"),
        "other": _wd("wd1.myworkdaysite.com", "other|otherco"),
        **{name: _wd(f"{name}.wd5.myworkdayjobs.com") for name in ("nvidia", "adobe", "intel", "asml")},
    }
    lanes = _members(collector_lanes(targets))
    assert len(lanes) == pacing_for("workday").max_boards_in_flight
    assert any({"snap", "other"} <= lane for lane in lanes), "one host, one lane"
    assert set().union(*lanes) == set(targets) and sum(map(len, lanes)) == len(targets)


class _Waiting:
    """Holds `fetch` open until released, recording how many run at once."""

    running = 0
    peak = 0

    def __init__(self, company: str, release: asyncio.Event) -> None:
        self.company, self.release = company, release
        self.drift = SchemaDriftDetector(f"fixture:{company}")
        self.truncated = False
        self.query_observations: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        _Waiting.running += 1
        _Waiting.peak = max(_Waiting.peak, _Waiting.running)
        try:
            await asyncio.wait_for(self.release.wait(), timeout=0.2)
        except TimeoutError:
            pass
        finally:
            _Waiting.running -= 1
        if False:
            yield None


@pytest.mark.asyncio
@pytest.mark.parametrize("family,expected_peak", [("workday", 3), ("greenhouse", 1)])
async def test_only_tenant_hosted_boards_actually_overlap(family, expected_peak):
    _Waiting.running = _Waiting.peak = 0
    release = asyncio.Event()
    targets = {
        name: {"adapter": family, "board_token": f"{name}.wd5.myworkdayjobs.com|External"}
        for name in ("a", "b", "c", "d")
    }
    collections = await collect_sources(
        targets, EMPTY_SCOPE, object(), max_list=None, hydrate=False,
        max_concurrent_sources=8,
        adapter_factory=lambda company, adapter, board_token=None, **kw: _Waiting(company, release),
    )
    assert set(collections) == set(targets)
    assert _Waiting.peak == expected_peak


# --------------------------------------------------------------------------- #
# Order is the first sync's speed: long lanes first, then postings per
# second, prioritizes early results and ends the
# sync at the longest board's own time; target order is far slower.
# --------------------------------------------------------------------------- #


def _gh(name: str) -> dict:
    return {"adapter": "greenhouse", "board_token": name}


def test_a_lane_longer_than_an_even_share_starts_first():
    targets = {
        "anthropic": _gh("anthropic"), "vercel": _gh("vercel"),
        "shopify": {"adapter": "shopify", "board_token": None},
        "micron": {"adapter": "eightfold", "board_token": "careers.micron.com|micron.com|pcsx"},
    }
    costs = {
        "anthropic": SourceCost(4, 30), "vercel": SourceCost(3, 2),
        "shopify": SourceCost(5, 1), "micron": SourceCost(1776, 5),
    }
    order = [[c for c, _ in queue] for queue in collector_lanes(targets, costs, slots=2).values()]
    assert order[0] == ["micron"], "the board that decides when the run ends must not start last"
    assert order[1] == ["anthropic", "vercel"], "then the most postings per second"


def test_short_lanes_start_by_postings_found_per_second():
    targets = {"shopify": {"adapter": "shopify", "board_token": None}, "anthropic": _gh("anthropic")}
    costs = {"shopify": SourceCost(5, 1), "anthropic": SourceCost(5, 40)}
    # One slot: the run ends at the same time in any order, so the lane that
    # finds most per second goes first.
    lanes = collector_lanes(targets, costs, slots=1)
    assert list(lanes) == ["greenhouse", "shopify"]


def test_a_company_with_nothing_measured_leads_its_lane():
    """A company just followed has no cost yet: it is the one its person is
    waiting for, so it does not wait behind every measured board on its host."""
    targets = {"rich": _gh("rich"), "new": _gh("new"), "poor": _gh("poor")}
    costs = {"rich": SourceCost(5, 40), "poor": SourceCost(5, 1)}
    order = [c for queue in collector_lanes(targets, costs, slots=1).values() for c, _ in queue]
    assert order == ["new", "rich", "poor"]


@pytest.mark.asyncio
async def test_following_a_thousand_companies_reads_every_one_in_the_same_run():
    """A follow-all lands a thousand unmeasured companies beside the measured
    ones: one run reads every one of them, new ones first, whatever the
    measured work of the lane says the run should take."""
    started: list[str] = []
    release = asyncio.Event()
    release.set()
    new = [f"new{i}" for i in range(1000)]
    targets = {name: _gh(name) for name in ("old0", "old1", *new)}
    costs = {"old0": SourceCost(1, 50), "old1": SourceCost(1, 50)}

    collections = await collect_sources(
        targets, EMPTY_SCOPE, object(), max_list=None, hydrate=False,
        max_concurrent_sources=12, lookups=RunLookups(costs=costs), on_source_start=started.append,
        adapter_factory=lambda company, adapter, board_token=None, **kw: _Waiting(company, release),
    )

    assert set(collections) == set(targets)
    assert not any(c.stats.get("deferred_reason") or c.stats["errors"] for c in collections.values())
    assert started[:1000] == new and started[1000:] == ["old0", "old1"]


def test_tenant_hosts_are_spread_by_scan_time_not_by_count():
    targets = {name: _wd(f"{name}.wd5.myworkdayjobs.com") for name in ("nvidia", "adobe", "intel", "asml")}
    costs = {
        "nvidia": SourceCost(330, 22), "adobe": SourceCost(40, 3),
        "intel": SourceCost(40, 3), "asml": SourceCost(40, 3),
    }
    lanes = _members(collector_lanes(targets, costs, slots=12))
    assert {"nvidia"} in lanes, "the long tenant runs alone, not beside the ones queued behind it"
    assert set().union(*lanes) == set(targets)


def test_without_costs_every_lane_keeps_target_order():
    targets = {"shopify": {"adapter": "shopify", "board_token": None}, "anthropic": _gh("anthropic")}
    assert list(collector_lanes(targets, None, slots=1)) == ["shopify", "greenhouse"]


@pytest.mark.asyncio
async def test_the_run_admits_lanes_in_that_order():
    started: list[str] = []
    release = asyncio.Event()
    release.set()
    targets = {
        "slowco": {"adapter": "shopify", "board_token": None},
        "midco": {"adapter": "ashby", "board_token": "midco"},
        "richco": _gh("richco"),
        "longco": {"adapter": "eightfold", "board_token": "careers.longco.com|longco.com|pcsx"},
    }
    costs = {
        "slowco": SourceCost(10, 0), "midco": SourceCost(10, 5),
        "richco": SourceCost(10, 20), "longco": SourceCost(900, 4),
    }
    await collect_sources(
        targets, EMPTY_SCOPE, object(), max_list=None, hydrate=False,
        max_concurrent_sources=2, lookups=RunLookups(costs=costs),
        on_source_start=started.append,
        adapter_factory=lambda company, adapter, board_token=None, **kw: _Waiting(company, release),
    )
    assert started == ["longco", "richco", "midco", "slowco"]
