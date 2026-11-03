"""Load spreading when the roster grows.

The catalog offers far more boards than the companies that collect. Enabling them must not
become a way to find a provider's rate limit by tripping it, so three properties
are pinned here:

1. **A deeper shard is not a faster one.** Boards of one provider share a pacer
   and drain serially, so admitting more of them retires more of the roster at
   the same request rate. This is the property that makes the whole change safe.
2. **Depth cannot become monopoly.** One provider with fifty overdue tenants
   must not take every slot — the shard is filled round-robin.
3. **A provider that is really many servers is paced as many.** Workday and
   Eightfold host each tenant separately; one bucket would divide an allowance
   they never shared and let one tenant's outage open a breaker on the rest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tracker.config import get_settings
from tracker.connectors import ADAPTER_REGISTRY, build_adapter
from tracker.platform.ratelimit import RateLimiterPool
from tracker.provider_pacing import (
    DEFAULT,
    PROVIDER_PACING,
    HostScope,
    pacing_for,
)
from tracker.workflows.collection_types import ScanMode
from tracker.workflows.scheduler import DueWork, PressureView, choose_due_work

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _due(slug: str, provider: str, minutes: int, mode=ScanMode.RECONCILE) -> DueWork:
    return DueWork(
        binding_id=abs(hash((slug, provider))) % 10_000,
        company_slug=slug,
        provider_key=provider,
        mode=mode,
        due_at=T0 - timedelta(minutes=minutes),
    )


# -- the table itself --------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_every_registered_provider_declares_its_pacing(name):
    """A family with no row still runs — on `DEFAULT`, at one board a shard.
    The gate exists so that is a DECISION rather than an oversight: the number
    that decides whether we get blocked should not be reachable by forgetting.
    """
    assert name in PROVIDER_PACING, (
        f"{name}: add a ProviderPacing row with the evidence for its numbers, "
        "or state explicitly that DEFAULT is the measurement"
    )


@pytest.mark.parametrize("key,policy", sorted(PROVIDER_PACING.items()))
def test_every_pacing_number_carries_its_evidence(key, policy):
    """`evidence` is the field that separates a measurement from a guess."""
    assert policy.provider == key
    assert policy.max_boards_in_flight >= 1
    assert policy.min_delay_seconds is None or policy.min_delay_seconds > 0
    assert len(policy.evidence) > 40, f"{key}: say WHY these numbers"


def test_an_unknown_provider_gets_the_conservative_default():
    """The safe direction is slow, never blocked."""
    assert pacing_for("icims") is DEFAULT
    assert pacing_for(None) is DEFAULT
    assert DEFAULT.max_boards_in_flight == 1


# -- fairness ----------------------------------------------------------------- #


def test_a_big_family_widens_the_shard_instead_of_owning_it():
    """Fifty overdue Greenhouse tenants and one overdue Ashby board. Greedy
    due-order fill would hand every slot to Greenhouse; round-robin must serve
    the other provider on the first pass."""
    due = [_due(f"gh{i}", "greenhouse", 100 - i) for i in range(50)]
    due.append(_due("ashby-co", "ashby", 5))

    picked = choose_due_work(due, {}, now=T0, max_providers=2, max_bindings=8)

    providers = [item.provider_key for item in picked]
    assert "ashby" in providers, "the smaller provider must not be starved"
    assert providers[0] == "greenhouse", "oldest due still goes first"
    assert providers[1] == "ashby", "every provider is offered a slot before any gets a second"


def test_the_shard_respects_each_provider_declared_depth():
    """Greenhouse allows 6, Lever 3 — the shard must not exceed either."""
    due = [_due(f"gh{i}", "greenhouse", 100 - i) for i in range(20)]
    due += [_due(f"lv{i}", "lever", 90 - i) for i in range(20)]

    picked = choose_due_work(due, {}, now=T0, max_providers=2, max_bindings=40)

    counts = {p: sum(1 for i in picked if i.provider_key == p) for p in {"greenhouse", "lever"}}
    assert counts["greenhouse"] == pacing_for("greenhouse").max_boards_in_flight
    assert counts["lever"] == pacing_for("lever").max_boards_in_flight


def test_the_total_ceiling_bounds_the_tick_whatever_the_depths_sum_to():
    """`sync_scheduler_max_bindings` is the one number that holds as the roster
    grows; per-provider depth decides the MIX inside it, never the size."""
    due = [_due(f"gh{i}", "greenhouse", 100 - i) for i in range(20)]
    due += [_due(f"as{i}", "ashby", 95 - i) for i in range(20)]

    picked = choose_due_work(due, {}, now=T0, max_providers=2, max_bindings=5)

    assert len(picked) == 5
    # Round-robin under a tight ceiling still alternates rather than draining one.
    assert {i.provider_key for i in picked} == {"greenhouse", "ashby"}


def test_one_binding_per_provider_still_holds_for_an_undeclared_family():
    """One binding per provider, kept exactly where nothing was measured."""
    due = [_due(f"ic{i}", "icims", 50 - i) for i in range(5)]

    picked = choose_due_work(due, {}, now=T0, max_providers=3, max_bindings=8)

    assert len(picked) == 1


def test_a_provider_in_cooldown_contributes_nothing_however_deep_its_queue():
    """Pressure is a hard gate, not a score depth may outvote."""
    due = [_due(f"gh{i}", "greenhouse", 100 - i) for i in range(10)]
    due.append(_due("ashby-co", "ashby", 1))
    pressure = {"greenhouse": PressureView("backoff", T0 + timedelta(minutes=30))}

    picked = choose_due_work(due, pressure, now=T0, max_providers=3, max_bindings=8)

    assert [i.company_slug for i in picked] == ["ashby-co"]


def test_a_shard_still_carries_one_mode():
    """One pipeline invocation has one authority/hydration policy, and a deeper
    shard must not be the thing that mixes them."""
    due = [_due("a", "greenhouse", 90), _due("b", "ashby", 80, ScanMode.DISCOVERY),
           _due("c", "greenhouse", 70)]

    picked = choose_due_work(due, {}, now=T0, max_providers=3, max_bindings=8)

    assert {i.mode for i in picked} == {ScanMode.RECONCILE}
    assert [i.company_slug for i in picked] == ["a", "c"]


def test_discovery_can_fill_a_shard_when_nothing_is_due_for_reconciliation():
    due = [_due(f"gh{i}", "greenhouse", 50 - i, ScanMode.DISCOVERY) for i in range(4)]

    picked = choose_due_work(due, {}, now=T0, max_providers=2, max_bindings=8)

    assert len(picked) == 4
    assert {i.mode for i in picked} == {ScanMode.DISCOVERY}


# -- rate safety -------------------------------------------------------------- #


def test_more_boards_of_one_provider_do_not_multiply_its_request_rate():
    """The property the whole change rests on. Six Greenhouse boards in a shard
    must share ONE pacer, so the provider sees a longer queue and not a burst.
    Proven on the object identity, because that is what actually serialises."""
    pool = RateLimiterPool()
    adapters = [
        build_adapter(f"co{i}", "greenhouse", board_token=f"t{i}", limiter_pool=pool)
        for i in range(6)
    ]

    limiters = {id(a._limiter) for a in adapters}
    assert len(limiters) == 1, "six boards, one pacer — otherwise depth IS a burst"


@pytest.mark.parametrize("provider", ["workday", "eightfold"])
def test_a_tenant_hosted_family_paces_each_tenant_separately(provider):
    """These serve every tenant from the tenant's own deployment, so one bucket
    would divide an allowance the tenants never shared — and one tenant's
    outage would open a breaker on hosts answering fine (the per-region
    argument applied to per-tenant hosting)."""
    assert pacing_for(provider).host_scope is HostScope.PER_TENANT
    pool = RateLimiterPool()
    a = build_adapter("one", provider, board_token="host-a|site", limiter_pool=pool)
    b = build_adapter("two", provider, board_token="host-b|site", limiter_pool=pool)

    assert a.pacing_scope() != b.pacing_scope()
    assert id(a._limiter) != id(b._limiter)


@pytest.mark.parametrize("provider", ["greenhouse", "ashby", "workable"])
def test_a_shared_host_family_keeps_one_bucket_for_every_tenant(provider):
    """The other direction, and the one that protects the provider: these answer
    every tenant from one API host, so tenants must NOT pace independently."""
    assert pacing_for(provider).host_scope is HostScope.SHARED
    pool = RateLimiterPool()
    a = build_adapter("one", provider, board_token="alpha", limiter_pool=pool)
    b = build_adapter("two", provider, board_token="beta", limiter_pool=pool)

    assert a.pacing_scope() == b.pacing_scope() == provider
    assert id(a._limiter) == id(b._limiter)


def test_lever_regions_still_outrank_the_family_bucket():
    """The region override must survive: two Lever regions are two hosts even
    though the family is SHARED-host, and the adapter's own `pacing_scope` is
    what knows that."""
    pool = RateLimiterPool()
    glob = build_adapter("a", "lever", board_region="global", limiter_pool=pool)
    eu = build_adapter("b", "lever", board_region="eu", limiter_pool=pool)

    assert glob.pacing_scope() != eu.pacing_scope()
    assert id(glob._limiter) != id(eu._limiter)


def test_an_adapter_declared_delay_outranks_the_provider_table():
    """microsoft's 3.0s is a property of that connector, not of a family, so the
    class attribute stays the most specific source."""
    assert ADAPTER_REGISTRY["microsoft"].min_delay == 3.0
    adapter = build_adapter("microsoft", "microsoft")

    assert adapter._limiter._min_delay == 3.0


def test_the_directory_hosts_pace_at_their_rows_and_workable_keeps_the_default():
    """Four shared hosts pace at their measured spacing, through the table,
    which must reach the pacer. Workable is the host that refused us (a long
    run of reads answered 429), so it keeps the global default until its limit
    is measured, whatever a table-wide edit does."""
    pool = RateLimiterPool()
    delays = {
        provider: build_adapter("x", provider, board_token="t", limiter_pool=pool)._limiter._min_delay
        for provider in ("greenhouse", "ashby", "lever", "smartrecruiters", "workable")
    }

    assert delays == {
        "greenhouse": 1.0, "ashby": 1.0, "lever": 1.0, "smartrecruiters": 0.6,
        "workable": get_settings().scraper_min_delay_seconds,
    }
    assert delays["workable"] >= 2.0
