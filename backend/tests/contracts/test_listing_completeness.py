"""Closure authority is earned once, in one place.

`listing_complete` defaults to TRUE: an adapter that ends a listing by saying
nothing keeps the right to conclude that a posting absent from this run is
gone, and the pipeline closes it. Every way of NOT earning that right is
therefore a rule an adapter has to remember, and answering "the board declared
no total" with silence is the answer that closes live postings.

`BaseAdapter.close_listing` is the only place the rule lives. These tests
pin the rule itself, and that every counted listing goes through it.
"""

from __future__ import annotations

import inspect

import pytest

from tracker.connectors import ADAPTER_REGISTRY, build_adapter

ADAPTER_NAMES = sorted(ADAPTER_REGISTRY)

#: Adapters that read a declared total but do not yet end on `close_listing`.
#: They page per search term, where the board's count is stated per query and
#: the union across queries is what a completeness check would have to compare
#: (windows are measured by union, never sum), so the rule needs
#: per-board evidence this suite cannot obtain offline.
#:
#: SHRINK-ONLY, like every other ratchet in this repo: an entry may be removed
#: when its adapter earns its verdict, and adding one needs the same evidence
#: the removal would.
WITHOUT_EPILOGUE: frozenset[str] = frozenset()

_TOKENS = {"workday": "example.wd1.myworkdayjobs.com|External"}


def _adapter(name: str):
    return build_adapter(f"contract-{name}", name, _TOKENS.get(name))


def _reads_a_declared_total(name: str) -> bool:
    """The adapter hands a count to the paging loop, so a count is what it
    believes sizes its board."""
    return "declared_total" in inspect.getsource(ADAPTER_REGISTRY[name])


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(n for n in ADAPTER_NAMES if ADAPTER_REGISTRY[n].declares_total))
def test_a_board_that_stops_declaring_its_total_is_not_closure_evidence(name):
    """The case that silently closed live postings.

    A board documented to state its size, and a run that finds no size, is a
    board whose shape changed under us. We do not know what we read, so we
    cannot conclude that what we did not read is gone.
    """
    adapter = _adapter(name)
    assert adapter.drift.listing_complete, "a fresh listing starts complete"

    adapter.close_listing(declared=None, unique=0)

    assert not adapter.drift.listing_complete, (
        f"{name} declares a total, met a board that stated none, and still claimed closure"
    )


#: Selected, not skipped: CI fails every skip it is not told to allow.
#: Avature sets `declares_total` per tenant; untenanted, as here, it declares one.
_UNCOUNTED = sorted(n for n in ADAPTER_NAMES if not ADAPTER_REGISTRY[n].declares_total)


@pytest.mark.parametrize("name", _UNCOUNTED)
def test_an_uncounted_board_is_not_put_in_doubt_by_the_same_rule(name):
    """The other half, and the reason this is a per-board declaration rather
    than one blanket rule: a board that never states a total ends on an empty
    page, and that IS the evidence. Reading a missing count as drift there
    would suppress closure for every source that simply does not count."""
    adapter = _adapter(name)
    assert not adapter.declares_total, f"{name} is selected as uncounted and declares a total"

    adapter.close_listing(declared=None, unique=0)

    assert adapter.drift.listing_complete


@pytest.mark.parametrize("name", sorted(ADAPTER_NAMES))
def test_fewer_unique_postings_than_declared_is_never_a_complete_listing(name):
    """For every adapter at once: pages that do not add up to the
    board never earn closure, however the shortfall is then weighed."""
    adapter = _adapter(name)

    adapter.close_listing(declared=10, unique=9)

    assert not adapter.drift.listing_complete, name


def _outcome(adapter, scanned: int):
    from tracker.connectors.recipes.outcome import classify_source_outcome

    return classify_source_outcome({
        "errors": [],
        "scanned": scanned,
        "list_complete": adapter.drift.listing_complete,
        "listing_invalidated": adapter.drift.listing_invalidated,
        "records_dropped": adapter.drift.records_dropped,
    })


def test_a_small_shortfall_is_counted_loss_not_a_broken_source():
    """A newest-first board walked for minutes can lose one posting
    mid-walk (4,826 unique of 4,827 declared): every later row shifts past
    the reader, so exactly one live row goes unread. That is bounded,
    countable loss — closure is suppressed, health is not scored."""
    from tracker.connectors.recipes.outcome import SourceOutcome

    adapter = _adapter("jibe")
    adapter.close_listing(declared=4827, unique=4826, field="totalRecords")

    assert not adapter.drift.listing_complete
    assert not adapter.drift.listing_invalidated
    assert adapter.drift.records_dropped == 1
    assert _outcome(adapter, scanned=4826) is SourceOutcome.LOSSY
    [alert] = adapter.drift.alerts
    assert (alert["message"], alert["missing"], alert["declared"], alert["unique"]) == (
        "fewer unique postings than totalRecords", 1, 4827, 4826,
    )


def test_a_large_shortfall_is_still_a_pathology():
    """The case the rule was written for: a relevance sort re-serving rows,
    883 declared and 762 unique. 14% is not a
    board moving under a long walk, and it must still score against health."""
    from tracker.connectors.recipes.outcome import SourceOutcome

    adapter = _adapter("accenture")
    adapter.close_listing(declared=883, unique=762)

    assert not adapter.drift.listing_complete
    assert adapter.drift.records_dropped == 121
    assert _outcome(adapter, scanned=762) is SourceOutcome.DEGRADED


@pytest.mark.parametrize("name", sorted(ADAPTER_NAMES))
def test_reaching_the_declared_total_earns_closure(name):
    """The rule may not fire on a listing that is whole — a false invalidation
    suppresses closure for every posting on the board."""
    adapter = _adapter(name)

    adapter.close_listing(declared=10, unique=10)
    adapter.close_listing(declared=10, unique=11)  # multi-label keys can exceed

    assert adapter.drift.listing_complete, name


def test_our_own_ceiling_is_never_evidence_against_the_source():
    """`truncated` is a bound WE imposed. It explains why we stopped reading
    and says nothing about the board, so it may not score as drift.
    A missing total is not covered by it: our ceiling cannot explain why the
    board stopped counting."""
    adapter = _adapter("jibe")
    adapter.truncated = True

    adapter.close_listing(declared=10, unique=3)
    assert adapter.drift.listing_complete, "a short read under our own cap is not drift"

    adapter.close_listing(declared=None, unique=3)
    assert not adapter.drift.listing_complete


def test_the_drift_note_still_names_the_boards_own_count():
    """Consolidating the rule may not cost the alert its diagnostic value: the
    note has to say WHICH number went missing, or an operator reading it cannot
    go and look."""
    adapter = _adapter("oracle")
    adapter.close_listing(declared=None, unique=0, field="TotalJobsCount")

    assert any("TotalJobsCount" in alert["message"] for alert in adapter.drift.alerts), (
        adapter.drift.alerts
    )


# --------------------------------------------------------------------------- #
# Every counted listing goes through it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(ADAPTER_NAMES))
def test_an_adapter_that_reads_a_declared_total_ends_on_the_shared_epilogue(name):
    """The rule being in one place is worth nothing if an adapter can quietly
    not use it."""
    if not _reads_a_declared_total(name):
        return
    source = inspect.getsource(ADAPTER_REGISTRY[name])
    uses = "close_listing(" in source

    if name in WITHOUT_EPILOGUE:
        assert not uses, f"{name} now ends on close_listing: remove it from WITHOUT_EPILOGUE"
        return
    assert uses, (
        f"{name} reads a declared total but never reaches close_listing, so it keeps "
        "closure authority no matter what the board said"
    )


def test_the_allowlist_names_only_adapters_that_still_need_it():
    """A ratchet that can name a source which does not exist — or one that
    never read a total — stops being a measurement of the remaining debt."""
    for name in WITHOUT_EPILOGUE:
        assert name in ADAPTER_REGISTRY, f"{name} is not an adapter"
        assert _reads_a_declared_total(name), f"{name} reads no declared total; drop it"
        assert not ADAPTER_REGISTRY[name].declares_total, (
            f"{name} declares a total but has no epilogue to enforce it"
        )


# --------------------------------------------------------------------------- #
# Through the real adapter, at the HTTP boundary
# --------------------------------------------------------------------------- #

#: Where each counted board states its size in the bytes it serves. The rows
#: stay the fixture's own; only the stated count grows, so the listing read is
#: short by exactly `_SHORT` against what the board says it holds.
DECLARED_TOTAL_IN_BODY: dict[str, str] = {
    "accenture": r'("total":\s*)(\d+)',
    "amazon": r'("hits":\s*)(\d+)',
    "apple": r'("totalRecords":\s*)(\d+)',
    "avature": r'(aria-label=")(\d+)(?= results?")',
    "avature_tls": r'(aria-label=")(\d+)(?= results?")',
    "eightfold": r'("count":\s*)(\d+)',
    "jibe": r'("totalCount":\s*)(\d+)',
    "kpmg": r'(data-action="count">)(\d+)',
    "microsoft": r'("count":\s*)(\d+)',
    "oracle": r'("TotalJobsCount":\s*)(\d+)',
    "smartrecruiters_api": r'("totalFound":\s*)(\d+)',
    "tiktok": r'("count":\s*)(\d+)',
    "successfactors": r'(of <b>)(\d+)',
    "workday": r'("total":\s*)(\d+)',
}
_SHORT = 7


def _inflating(adapter, pattern: str):
    """Wrap the harness transport so every served count claims `_SHORT` more."""
    import re

    import httpx

    inner = adapter._client._transport

    class Inflate(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            response = await inner.handle_async_request(request)
            body = (await response.aread()).decode()
            body = re.sub(pattern, lambda m: f"{m.group(1)}{int(m.group(2)) + _SHORT}", body)
            headers = [(k, v) for k, v in response.headers.items()
                       if k.lower() not in {"content-length", "content-encoding"}]
            return httpx.Response(response.status_code, headers=headers, content=body.encode())

    adapter._client = httpx.AsyncClient(transport=Inflate())
    return adapter


def test_every_counted_adapter_names_where_its_board_states_its_size():
    counted = {n for n in ADAPTER_NAMES if ADAPTER_REGISTRY[n].declares_total}
    assert set(DECLARED_TOTAL_IN_BODY) == counted, (
        "a counted adapter needs its DECLARED_TOTAL_IN_BODY entry, or this suite "
        "cannot prove that a board serving fewer rows than it states loses closure"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(DECLARED_TOTAL_IN_BODY))
async def test_a_real_board_short_of_its_stated_total_loses_closure(name):
    """The structural gate above passes an adapter that calls `close_listing`
    after an early `return`, for instance inside an exemption branch.
    This one runs the adapter over its own fixture with only the stated count
    raised: whatever path the adapter takes, it may not end complete."""
    from tests.contracts.conftest import MODE_NORMAL, build_harness, run_fetch

    adapter = _inflating(build_harness(name, MODE_NORMAL), DECLARED_TOTAL_IN_BODY[name])
    jobs = await run_fetch(adapter)

    assert jobs, f"{name}: the inflated fixture still serves its rows"
    assert not adapter.truncated, f"{name}: our ceiling would explain the gap instead"
    assert not adapter.drift.listing_complete, (
        f"{name} read {len(jobs)} rows under a count {_SHORT} higher and kept closure authority"
    )


# --------------------------------------------------------------------------- #
# One token, one endpoint: collection and verification agree
# --------------------------------------------------------------------------- #


def _declares_a_probe(name: str) -> bool:
    from tracker.connectors.listing.base import BoardProbe

    return isinstance(getattr(ADAPTER_REGISTRY[name], "board_probe", None), BoardProbe)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(n for n in ADAPTER_NAMES if _declares_a_probe(n)))
async def test_the_probe_names_a_host_collection_actually_reads(name):
    """The checker verifies `BoardProbe.url_for(token, region)`; collection builds
    its own URLs. If they drift apart a token passes verification for a host we
    never collect from (or the reverse), silently."""
    from urllib.parse import urlsplit

    import httpx

    from tests.contracts.conftest import MODE_NORMAL, build_harness, run_fetch
    from tracker.connectors.listing.base import BoardProbe

    adapter = build_harness(name, MODE_NORMAL)
    probe = getattr(type(adapter), "board_probe", None)
    assert isinstance(probe, BoardProbe), f"{name}: the harness built an adapter without the probe"
    client = getattr(adapter, "_client", None)
    if client is None:
        pytest.skip(f"{name} harness does not run on httpx")
    inner, hosts = client._transport, set()

    class Record(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            hosts.add(request.url.host)
            return await inner.handle_async_request(request)

    adapter._client = httpx.AsyncClient(transport=Record())
    await run_fetch(adapter)
    # The token the checker is handed is the stored one; a family with a tenant
    # map resolves an absent token exactly as its adapter does.
    tenants = getattr(probe, "tenants", None)
    token = tenants.resolve(adapter.company, adapter.board_token) if tenants else (
        adapter.board_token or adapter.company)
    probed = urlsplit(probe.url_for(token, adapter.board_region)).hostname
    assert probed in hosts, f"{name}: probe reads {probed}, collection read {sorted(hosts)}"


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["global", "eu"])
async def test_a_regional_token_is_probed_and_collected_on_the_same_regional_host(region):
    """A wrong region answers the same 404 as a wrong token."""
    from urllib.parse import urlsplit

    import httpx

    from tracker.connectors import build_adapter
    from tracker.connectors.listing.base import RateLimiter

    hosts: set[str] = set()

    def handle(request):
        hosts.add(request.url.host)
        return httpx.Response(200, json=[])

    adapter = build_adapter("acme", "lever", board_token="acme", board_region=region)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter._limiter = RateLimiter(0.0)
    async with adapter._client:
        [job async for job in adapter.fetch()]
    probed = urlsplit(type(adapter).board_probe.url_for("acme", region)).hostname
    assert hosts == {probed}
    assert adapter.pacing_scope() == f"lever:{region}"
