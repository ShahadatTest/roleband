"""A saturated query is a view, not a listing — so ask a narrower one.

Amazon's USA query reports `hits=10000` at every reachable offset and nothing
past it. The adapter says so (`truncated`, health-inert, closure-suppressed)
instead of claiming a complete board; that is honest but permanent — a
`truncated` run cannot produce the OK the binding needs to leave
quarantine. Refinement is the exit: split the saturated query along a facet the
source declares until every leaf fits under the window, and each leaf pages to a
real natural stop.

The claim that buys back is strong — it re-authorizes closing amazon's jobs — so
these tests pin both halves: that refinement happens when and only when the
query is saturated, and that a leaf set which does NOT cover the query it
replaced is caught rather than trusted.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.connectors.listing import amazon as amazon_module
from tracker.connectors.listing.amazon import AMAZON_LOCATION_QUERY, AmazonAdapter
from tracker.connectors.listing.base import RateLimiter

# Shrunk from the real 10,000 so a fixture can saturate it exactly as the real
# source does. `_audit_offsets()` derives from it, so the sample follows.
_WINDOW = 400


def _hit(key: str, n: int) -> dict:
    return {
        "id_icims": f"{key}-{n}",
        "title": f"Senior SDE {n}",
        "job_path": f"/en/jobs/{key}-{n}/sde",
        "normalized_location": f"City, {key}, USA",
    }


def _facet(url: httpx.URL) -> str:
    """Which shard a request is asking for."""
    if state := url.params.get("normalized_state_name[]"):
        return state
    if url.params.get("normalized_location[]"):
        return "state-less"
    return url.params.get("normalized_country_code[]") or ""


def _source(
    board: dict[str, list[dict]],
    requests: list[httpx.URL],
    *,
    fail_first: bool = False,
    fail_parent_offsets: set[int] | None = None,
):
    """amazon.jobs with a per-facet board and a real result window.

    A saturated query reports the WINDOW as its `hits` at every offset and
    serves nothing past it — the source's own behavior, and the whole reason a
    declared total cannot be trusted as a count.

    ``fail_parent_offsets`` refuses specific offsets of the *parent* (country)
    query, which is how an audit stratum goes missing without anything else
    breaking.
    """
    calls = {"n": 0}
    refused = fail_parent_offsets or set()

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        requests.append(request.url)
        if fail_first and calls["n"] == 1:
            # 404 is outside the retry set, so it surfaces to the caller at once.
            return httpx.Response(404, text="nope")
        facet = _facet(request.url)
        if facet == "USA" and int(request.url.params.get("offset") or 0) in refused:
            return httpx.Response(404, text="nope")
        rows = board.get(_facet(request.url), [])
        offset = int(request.url.params.get("offset") or 0)
        limit = int(request.url.params.get("result_limit") or 100)
        page = rows[offset : min(offset + limit, _WINDOW)] if offset < _WINDOW else []
        return httpx.Response(200, json={"hits": min(len(rows), _WINDOW), "jobs": page})

    adapter = AmazonAdapter("amazon")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


@pytest.fixture(autouse=True)
def _small_window(monkeypatch):
    monkeypatch.setattr(amazon_module, "_RESULT_WINDOW", _WINDOW)


def _states_board() -> tuple[dict[str, list[dict]], list[dict]]:
    """Three real state shards summing to 900 — well past the 400 window."""
    wa = [_hit("WA", i) for i in range(350)]
    ca = [_hit("CA", i) for i in range(300)]
    ny = [_hit("NY", i) for i in range(250)]
    everything = wa + ca + ny
    board = {
        "USA": everything,  # the country query, capped at the window by the fixture
        "Washington": wa,
        "California": ca,
        "New York": ny,
        "GBR": [_hit("GBR", i) for i in range(30)],
        "SGP": [_hit("SGP", i) for i in range(20)],
    }
    return board, everything


@pytest.mark.asyncio
async def test_saturated_country_query_is_split_into_state_leaves():
    """The point of the whole layer: 900 postings exist, the country query can
    only address 400 of them, and after refinement all 900 are collected AND the
    listing is complete — no `truncated`, so the source classifies `ok` and
    closure is re-authorized."""
    board, everything = _states_board()
    requests: list[httpx.URL] = []
    adapter = _source(board, requests)

    jobs = [job async for job in adapter.fetch()]

    assert len(jobs) == len(everything) + 50, "900 US + 30 UK + 20 SGP, deduped"
    assert len([j for j in jobs if j.req_id.startswith(("WA", "CA", "NY"))]) == 900
    assert adapter.truncated is False, "every leaf fits under the window"
    assert adapter.drift.alerts == []

    facets = {_facet(u) for u in requests}
    assert {"Washington", "California", "New York"} <= facets
    # The country query is probed and sampled, never *paged*: three audit
    # offsets and nothing else, or refinement would be re-collecting the view it
    # exists to replace.
    usa_offsets = sorted({int(u.params["offset"]) for u in requests if _facet(u) == "USA"})
    assert usa_offsets == amazon_module._audit_offsets()


@pytest.mark.asyncio
async def test_unsaturated_country_query_is_never_refined():
    """The guard against over-correcting. A country query under the window is a
    real listing; splitting it into 52 shards would multiply requests roughly
    fiftyfold to collect exactly the same postings."""
    board = {"USA": [_hit("USA", i) for i in range(150)], "GBR": [], "SGP": []}
    requests: list[httpx.URL] = []
    adapter = _source(board, requests)

    jobs = [job async for job in adapter.fetch()]

    assert len(jobs) == 150
    assert adapter.truncated is False
    assert not any(u.params.get("normalized_state_name[]") for u in requests)


@pytest.mark.asyncio
async def test_refinement_that_misses_the_parents_own_postings_is_not_a_partition():
    """The audit. If the facet stops partitioning the parent — amazon renames a
    state, adds a territory, changes what `normalized_state_name` means — the
    leaves quietly under-collect while every individual leaf still reaches a
    clean natural stop. Every signal reads `ok`, and `ok` closes jobs.

    So the leaf set is measured against postings the parent query itself showed
    us. Orphans that no shard returns mean the vocabulary is incomplete, and the
    answer is the same one saturation gets: `truncated` — OUR bound, so no drift
    alert and no health anomaly."""
    board, _ = _states_board()
    # Rows 300-399 of the country query belong to no shard at all.
    board["USA"] = board["USA"][:300] + [_hit("ORPHAN", i) for i in range(100)]
    requests: list[httpx.URL] = []
    adapter = _source(board, requests)

    jobs = [job async for job in adapter.fetch()]

    assert not any(j.req_id.startswith("ORPHAN") for j in jobs), "no leaf can reach them"
    assert adapter.truncated is True, "an incomplete partition must not read as complete"
    assert adapter.drift.alerts == [], "our vocabulary being wrong is not source drift"


@pytest.mark.asyncio
async def test_small_sample_churn_does_not_flunk_a_working_partition():
    """The tolerance the audit needs to be usable: the sample is taken minutes
    before the leaves finish, so a posting filled in between is a legitimate
    miss. A handful must not condemn a partition that works."""
    board, _ = _states_board()
    board["USA"] = board["USA"][:295] + [_hit("FILLED", i) for i in range(5)] + board["USA"][295:395]
    requests: list[httpx.URL] = []
    adapter = _source(board, requests)

    [job async for job in adapter.fetch()]

    assert adapter.truncated is False, "5 of 300 sampled is churn, not a hole"


@pytest.mark.asyncio
async def test_an_audit_that_could_not_sample_the_deep_strata_is_inconclusive():
    """The failure mode the audit's strata check exists for.

    A stratum that fails to download does not make this check harder, it makes
    it EASIER: fewer postings to account for, and the ones lost are the deep
    ones. Offset 0 is the newest stratum and the leaves find it trivially, so an
    audit reduced to offset 0 passes while proving only the easy half — of a
    refinement whose entire purpose is reaching the postings the window hid.

    Here every leaf genuinely covers everything, so the miss count is zero and
    a miss count alone would report a complete listing. It must not: two of three strata
    never arrived, so the honest answer is "collected, but unverified"."""
    board, everything = _states_board()
    requests: list[httpx.URL] = []
    adapter = _source(board, requests, fail_parent_offsets={200, 300})

    jobs = [job async for job in adapter.fetch()]

    assert len(jobs) == len(everything) + 50, "every posting is still collected"
    assert adapter.truncated is True, "an audit that did not run cannot pass"
    assert adapter.drift.alerts == [], "a failed sample of ours is not source drift"


@pytest.mark.asyncio
async def test_a_fully_sampled_audit_still_reports_a_complete_listing():
    """The other half, or the check above would just be a way to never close a
    job: when all three strata arrive and the leaves account for them, the
    source is authoritative exactly as before."""
    board, _ = _states_board()
    requests: list[httpx.URL] = []
    adapter = _source(board, requests)

    [job async for job in adapter.fetch()]

    assert adapter.truncated is False
    assert adapter._audit_landed == adapter._audit_expected == len(
        amazon_module._audit_offsets()
    )


@pytest.mark.asyncio
async def test_state_less_remote_postings_get_their_own_shard():
    """US postings carrying no state at all — `city="Virtual"` remote roles,
    so exactly the high-value ones. All 51 state
    shards are blind to them; `normalized_location[]=USA` is what reaches them."""
    board, everything = _states_board()
    remote = [_hit("VIRTUAL", i) for i in range(12)]
    board["state-less"] = remote
    board["USA"] = everything + remote
    requests: list[httpx.URL] = []
    adapter = _source(board, requests)

    jobs = [job async for job in adapter.fetch()]

    assert {j.req_id for j in jobs} >= {r["id_icims"] for r in remote}
    assert any(u.params.get("normalized_location[]") == "USA" for u in requests)


def test_no_shard_is_built_on_a_facet_the_source_ignores():
    """`city[]` is SILENTLY IGNORED — a nonsense city still returns all 10,000.
    A city shard would therefore re-collect the whole board once per shard and
    report the result as coverage, which is worse than not sharding at all."""
    params = {
        param for facets in amazon_module._REFINEMENTS.values() for _, (param, _) in facets
    }
    assert params == {"normalized_state_name[]", "normalized_location[]"}
    assert "city[]" not in params


def test_only_the_country_group_that_saturates_declares_refinements():
    """GBR and SGP are orders of magnitude under the window. Giving them facets
    would cost probes and pages to answer a question already answered."""
    assert set(amazon_module._REFINEMENTS) == {"united_states"}
    assert set(amazon_module._REFINEMENTS) <= set(AMAZON_LOCATION_QUERY)
    # 50 states + DC + the state-less shard.
    assert len(amazon_module._REFINEMENTS["united_states"]) == 52


@pytest.mark.asyncio
async def test_probe_failure_falls_back_to_the_unrefined_query():
    """A probe is an optimization, not a dependency. When it fails we cannot
    know the query is saturated, and guessing either way is worse than paging
    the whole query unrefined."""
    board = {"USA": [_hit("USA", i) for i in range(150)], "GBR": [], "SGP": []}
    requests: list[httpx.URL] = []
    adapter = _source(board, requests, fail_first=True)

    jobs = [job async for job in adapter.fetch()]

    assert len(jobs) == 150, "the group is still collected"
    assert not any(u.params.get("normalized_state_name[]") for u in requests)
    assert adapter.truncated is False
