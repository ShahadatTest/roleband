"""Bundled recipes are seeded once and bound when followed; robots is checked on every run."""

from __future__ import annotations

import copy

import httpx
import pytest
from sqlalchemy import func, select

from tests.factories import scope_filter
from tests.test_recipe_adapter import PAGE, RECIPE
from tracker.company_store import ensure_source_bindings
from tracker.config import get_settings
from tracker.connectors import build_adapter
from tracker.connectors.listing import base
from tracker.connectors.recipes import bundled, compile_recipe
from tracker.db.models import (
    ConnectorRecipe,
    ConnectorRecipeRevision,
    SourceBinding,
    TrackedCompany,
)
from tracker.db.recipe_store import ensure_bundled_recipes
from tracker.platform.ratelimit import RateLimiter, RateLimiterPool
from tracker.source_policy import CollectionPolicyDenied
from tracker.workflows.collection import collect_source

pytestmark = pytest.mark.usefixtures("no_escape")

EMPTY_SCOPE = scope_filter(bands=(), roles=(), tracks=(), locations=(), domains=())


@pytest.fixture
def shipped(monkeypatch):
    """One bundled recipe, the synthetic `demo-careers`."""
    monkeypatch.setattr(bundled, "BUNDLED_RECIPES", {
        "demo-careers": bundled.BundledRecipe(document=copy.deepcopy(RECIPE), evidence="test"),
    })


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


def test_nothing_is_bundled_that_robots_would_refuse():
    """Valve is not here: robots disallows its page."""
    assert "valve-jobs" not in bundled.BUNDLED_RECIPES
    for entry in bundled.BUNDLED_RECIPES.values():
        compile_recipe(entry.document)


@pytest.mark.asyncio
async def test_seeding_is_idempotent_and_an_edit_becomes_the_new_default(db_session, shipped, monkeypatch):
    assert await ensure_bundled_recipes(db_session) == ["demo-careers"]
    assert await ensure_bundled_recipes(db_session) == [], "same content, nothing saved"
    recipe = await db_session.scalar(select(ConnectorRecipe).where(ConnectorRecipe.slug == "demo-careers"))
    assert recipe.status == "active" and await _count(db_session, ConnectorRecipeRevision) == 1

    edited = copy.deepcopy(RECIPE)
    edited["listing"]["item"] = "li.job"
    monkeypatch.setitem(bundled.BUNDLED_RECIPES, "demo-careers",
                        bundled.BundledRecipe(document=edited, evidence="test"))
    assert await ensure_bundled_recipes(db_session) == ["demo-careers"]
    active = await db_session.get(ConnectorRecipeRevision, recipe.default_revision_id)
    assert active.version == 2 and "validated_at" not in active.validation, "seeding never validates"


@pytest.mark.asyncio
async def test_a_followed_recipe_company_is_bound_collecting_and_closing_nothing(db_session, shipped):
    db_session.add(TrackedCompany(slug="demo", display="Demo", adapter="recipe", board_token="demo-careers",
                                  status="active", enabled=True, visible=True, source="catalog"))
    await db_session.flush()

    await ensure_source_bindings(db_session)
    await ensure_source_bindings(db_session)

    bindings = (await db_session.scalars(select(SourceBinding))).all()
    assert [(b.company_slug, b.connector_kind, b.connector_id, b.closure_capability) for b in bindings] == [
        ("demo", "recipe", "demo-careers", "none"),
    ]


def _site(monkeypatch, robots: httpx.Response):
    asked: list[str] = []

    def handle(request):
        asked.append(request.url.path)
        if request.url.path == "/robots.txt":
            return robots
        return httpx.Response(200, text=PAGE)

    monkeypatch.setattr(base, "make_tier_client",
                        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    return asked


@pytest.mark.asyncio
@pytest.mark.parametrize("robots", [
    httpx.Response(200, text="User-agent: *\nDisallow: /jobs\n"),
    httpx.Response(403),
    # Keep the retries, skip elapsed backoff: timing is test_platform.py's contract.
    httpx.Response(503, headers={"Retry-After": "0"}),
])
async def test_a_site_whose_robots_refuses_is_never_listed(monkeypatch, robots):
    asked = _site(monkeypatch, robots)
    async with build_adapter("demo", "recipe", recipe_plan=compile_recipe(RECIPE)) as adapter:
        adapter._limiter = RateLimiter(0)
        with pytest.raises(CollectionPolicyDenied, match="no consent path"):
            [job async for job in adapter.fetch()]
    # A server error is retried like any request; nothing but robots.txt is asked.
    assert set(asked) == {"/robots.txt"}, "no listing request after a refusal"
    expected_requests = get_settings().scraper_max_retries + 1 if robots.status_code == 503 else 1
    assert len(asked) == expected_requests


@pytest.mark.asyncio
async def test_a_refusal_is_policy_not_a_broken_site(monkeypatch):
    _site(monkeypatch, httpx.Response(200, text="User-agent: *\nDisallow: /jobs\n"))
    result = await collect_source("demo", {"adapter": "recipe", "recipe_plan": compile_recipe(RECIPE)},
                                  EMPTY_SCOPE, None, max_list=None, hydrate=False,
                                  limiter_pool=RateLimiterPool())
    assert result.stats["unattempted"] and not result.list_complete and not result.seen_keys


@pytest.mark.asyncio
@pytest.mark.parametrize("robots", [httpx.Response(404), httpx.Response(200, text="User-agent: *\nAllow: /\n")])
async def test_a_site_that_allows_or_serves_no_robots_is_listed(monkeypatch, robots):
    _site(monkeypatch, robots)
    async with build_adapter("demo", "recipe", recipe_plan=compile_recipe(RECIPE)) as adapter:
        jobs = [job async for job in adapter.fetch()]
    assert {job.req_id for job in jobs} == {"J1", "J2"}
