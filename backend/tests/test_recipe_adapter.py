"""Generic recipe connector + health-outcome classifier.

Proves a stored recipe runs through the REAL adapter lifecycle (BaseAdapter async
context manager, shared pacer, drift detector) over the connector SDK context —
one class, any recipe — and that a run maps to the right health outcome. The
closure-safety wiring is the key assertion: an incomplete recipe run marks the
same drift detector the pipeline's closure gate reads.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from tracker.connectors.listing.recipe_adapter import RecipeAdapter
from tracker.connectors.recipes import compile_recipe
from tracker.platform.ratelimit import RateLimiter

RECIPE = {
    "format_version": 1,
    "kind": "job_listing",
    "id": "demo-careers",
    "match": {"domains": ["careers.demo.com"]},
    "transport": {"mode": "static_http"},
    "listing": {
        "start_url": "https://careers.demo.com/jobs",
        "response": "html",
        "item": "article.job",
        "fields": {
            "req_id": {"attr": "data-id", "required": True},
            "title": {"css": "h2", "text": True, "required": True},
            "url": {"css": "a", "attr": "href", "absolute": True, "required": True},
        },
    },
    "validation": {"empty_state_selector": "div.no-jobs"},
}

PAGE = (
    "<html><body>"
    '<article class="job" data-id="J1"><h2>Staff Eng</h2><a href="/j/1">a</a></article>'
    '<article class="job" data-id="J2"><h2>Senior SRE</h2><a href="/j/2">a</a></article>'
    "</body></html>"
)


def _wire(adapter: RecipeAdapter, handler) -> RecipeAdapter:
    """Inject a mock transport the same way the contract suite does."""
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


async def _run(adapter: RecipeAdapter):
    try:
        return [job async for job in adapter.fetch()]
    finally:
        if adapter._client is not None:
            await adapter._client.aclose()


# --------------------------------------------------------------------------- #
# RecipeAdapter end-to-end through the real lifecycle
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_recipe_adapter_yields_rawjobs_from_a_recipe():
    plan = compile_recipe(RECIPE)
    adapter = _wire(RecipeAdapter("demo", plan), lambda _r: httpx.Response(200, text=PAGE))
    jobs = await _run(adapter)

    assert [j.req_id for j in jobs] == ["J1", "J2"]
    assert jobs[0].company == "demo"
    assert jobs[0].url == "https://careers.demo.com/j/1"  # absolute resolved
    assert adapter.drift.listing_complete  # complete run
    assert adapter.last_result.list_complete


@pytest.mark.asyncio
async def test_incomplete_recipe_run_marks_drift_so_closure_is_suppressed():
    """The whole point: recipe incompleteness flows into the SAME drift the
    pipeline's closure gate reads."""
    plan = compile_recipe(RECIPE)
    # 404 -> run incomplete (non-retryable, so no backoff sleeps in-test; the
    # retry path itself is covered in test_connector_sdk).
    adapter = _wire(RecipeAdapter("demo", plan), lambda _r: httpx.Response(404, text=""))
    jobs = await _run(adapter)

    assert jobs == []
    assert not adapter.drift.listing_complete  # closure suppressed downstream
    assert not adapter.last_result.list_complete


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["static_impersonate", "render"])
async def test_recipe_adapter_refuses_a_reserved_transport_before_any_request(mode):
    """A stored revision may still name a reserved transport (it loads, as
    `test_recipe_dispatch` shows): the run refuses it by name without sending
    anything over plain httpx, robots.txt included."""
    plan = replace(compile_recipe(RECIPE), transport_mode=mode)
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, text=PAGE)

    adapter = _wire(RecipeAdapter("demo", plan), handler)
    jobs = await _run(adapter)

    assert jobs == [] and asked == []
    assert not adapter.drift.listing_complete  # fail loud, don't scrape wrong


# --------------------------------------------------------------------------- #
# Structural empty-state sentinel detection in the runner
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_runner_detects_the_empty_state_sentinel():
    from tracker.connectors.recipes import run_plan
    from tracker.connectors.sdk import FetchResponse

    plan = compile_recipe(RECIPE)
    empty_page = '<html><body><div class="no-jobs">No open roles</div></body></html>'

    class Ctx:
        async def fetch(self, req):
            return FetchResponse(status=200, final_url=req.url, headers={}, content=empty_page.encode())

    result = await run_plan(plan, Ctx(), "demo")
    assert result.jobs == []
    assert result.list_complete
    assert result.diagnostics["structural_empty"] is True


@pytest.mark.asyncio
async def test_runner_reports_no_sentinel_when_absent():
    from tracker.connectors.recipes import run_plan
    from tracker.connectors.sdk import FetchResponse

    plan = compile_recipe(RECIPE)
    blank = "<html><body></body></html>"  # empty, but no no-jobs marker

    class Ctx:
        async def fetch(self, req):
            return FetchResponse(status=200, final_url=req.url, headers={}, content=blank.encode())

    result = await run_plan(plan, Ctx(), "demo")
    assert result.diagnostics["structural_empty"] is False
