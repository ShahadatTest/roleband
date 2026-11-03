"""A stored recipe collects a company end to end, and never grants itself closure."""

from __future__ import annotations

import copy
from dataclasses import replace

import httpx
import pytest

from tests.test_recipe_adapter import PAGE, RECIPE
from tracker.company_store import CompanyConflict, bind_recipe
from tracker.connectors.listing import base
from tracker.connectors.recipes import RecipeError, compile_recipe
from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.binding import decide_binding_activation
from tracker.db.models import (
    ConnectorRecipe,
    ConnectorRecipeRevision,
    SourceBinding,
    TrackedCompany,
)
from tracker.db.recipe_store import (
    activate_revision,
    attach_recipe_plans,
    checksum_document,
    record_validation,
    save_draft_revision,
)
from tracker.enrich.enricher import ScopeFilter
from tracker.platform.ratelimit import RateLimiterPool
from tracker.workflows import recipe_preview
from tracker.workflows.collection import collect_source

pytestmark = pytest.mark.usefixtures("no_escape")

EMPTY_SCOPE = ScopeFilter(frozenset(), frozenset(), frozenset(), frozenset(), frozenset())
ROBOTS_OK = "User-agent: *\nAllow: /\n"


def _recipe(**listing) -> dict:
    doc = copy.deepcopy(RECIPE)
    doc["listing"].update(listing)
    return doc


def _serve(monkeypatch, routes: dict[str, str | httpx.Response]):
    """Every client the recipe path builds answers from `routes`, recording URLs."""
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        value = routes.get(url, httpx.Response(404))
        return value if isinstance(value, httpx.Response) else httpx.Response(200, text=value)

    def client(*_a, **_kw):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))

    monkeypatch.setattr(base, "make_tier_client", client)
    monkeypatch.setattr(recipe_preview, "public_client", client)
    return asked


# --- the activation rule ---------------------------------------------------------


def _binding(kind: str) -> SourceBinding:
    return SourceBinding(company_slug="demo", connector_kind=kind, connector_id="demo-careers",
                         status="stable", closure_capability="none")


@pytest.mark.parametrize("validated,expected", [(False, False), (True, True)])
def test_a_recipe_earns_closure_only_through_a_validated_revision(validated, expected):
    decision = decide_binding_activation(
        binding=_binding("recipe"), outcome=SourceOutcome.OK, scan_mode="reconcile", scanned=12,
        revision_validated=validated,
    )
    assert decision.activate is expected


def test_a_validated_recipe_still_needs_a_clean_complete_reconcile():
    for outcome, mode in [(SourceOutcome.BOUNDED, "reconcile"), (SourceOutcome.OK, "discovery")]:
        assert not decide_binding_activation(
            binding=_binding("recipe"), outcome=outcome, scan_mode=mode, scanned=12,
            revision_validated=True,
        ).activate
    assert not decide_binding_activation(
        binding=_binding("plugin"), outcome=SourceOutcome.OK, scan_mode="reconcile", scanned=12,
        revision_validated=True,
    ).activate


# --- binding a company -------------------------------------------------------------


async def _active_recipe(session, doc=RECIPE):
    revision = await save_draft_revision(session, slug=doc["id"], document=doc)
    await activate_revision(session, recipe_id=revision.recipe_id, revision_id=revision.id)
    return revision


@pytest.mark.asyncio
async def test_binding_collects_from_the_start_but_closes_nothing(db_session):
    db_session.add(TrackedCompany(slug="demo", display="Demo", status="pending", enabled=True, visible=True))
    revision = await _active_recipe(db_session)

    binding = await bind_recipe(db_session, "demo", "demo-careers")

    assert (binding.connector_kind, binding.status, binding.closure_capability) == ("recipe", "stable", "none")
    assert binding.recipe_revision_id == revision.id
    row = await db_session.get(TrackedCompany, "demo")
    assert (row.adapter, row.status) == ("recipe", "active")


@pytest.mark.asyncio
async def test_an_adapter_collected_company_is_never_moved_by_a_bind(db_session):
    db_session.add(TrackedCompany(slug="acme", display="Acme", adapter="greenhouse", board_token="acme",
                                  status="active", enabled=True, visible=True))
    await db_session.flush()
    db_session.add(SourceBinding(company_slug="acme", connector_kind="adapter", connector_id="greenhouse",
                                 status="stable", closure_capability="authoritative"))
    await _active_recipe(db_session)
    with pytest.raises(CompanyConflict, match="shadow-and-reconcile"):
        await bind_recipe(db_session, "acme", "demo-careers")


@pytest.mark.asyncio
async def test_a_recipe_without_an_activated_revision_cannot_be_bound(db_session):
    db_session.add(TrackedCompany(slug="demo", display="Demo", status="pending", enabled=True, visible=True))
    await save_draft_revision(db_session, slug="demo-careers", document=RECIPE)
    with pytest.raises(CompanyConflict, match="no activated revision"):
        await bind_recipe(db_session, "demo", "demo-careers")


@pytest.mark.asyncio
async def test_a_later_activation_never_retargets_a_bound_company(db_session):
    db_session.add(TrackedCompany(slug="demo", display="Demo", status="pending", enabled=True, visible=True))
    first = await _active_recipe(db_session)
    await bind_recipe(db_session, "demo", "demo-careers")
    await _active_recipe(db_session, _recipe(item="li.job"))  # v2 becomes the default

    targets = {"demo": {"adapter": "recipe"}}
    await attach_recipe_plans(db_session, targets)
    assert targets["demo"]["recipe_plan"].item == "article.job", "still revision 1"
    rebound = await bind_recipe(db_session, "demo", "demo-careers")
    assert rebound.recipe_revision_id != first.id
    retired = await db_session.get(SourceBinding, (await db_session.execute(
        SourceBinding.__table__.select().where(SourceBinding.recipe_revision_id == first.id)
    )).first().id)
    assert retired.status == "retired"


# --- the pipeline path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_recipe_target_is_collected_through_the_real_collector(monkeypatch):
    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE})
    result = await collect_source(
        "demo", {"adapter": "recipe", "recipe_plan": compile_recipe(RECIPE)}, EMPTY_SCOPE, None,
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(),
    )
    assert {key.split(":")[-1] for key in result.seen_keys} == {"J1", "J2"}
    assert result.list_complete


@pytest.mark.asyncio
async def test_a_page_linking_off_the_declared_hosts_is_never_fetched(monkeypatch):
    page = PAGE.replace("</body>", '<a class="next" href="http://127.0.0.1:8010/jobs?p=2">n</a></body>')
    doc = _recipe()
    doc["pagination"] = {"mode": "next_link", "selector": "a.next", "max_pages": 5}
    asked = _serve(monkeypatch, {"https://careers.demo.com/jobs": page})
    result = await collect_source(
        "demo", {"adapter": "recipe", "recipe_plan": compile_recipe(doc)}, EMPTY_SCOPE, None,
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(),
    )
    assert not any("127.0.0.1" in url for url in asked)
    assert not result.list_complete


def test_each_recipe_host_has_its_own_pacer_and_can_only_slow_down():
    from tracker.connectors import build_adapter

    fast = build_adapter("demo", "recipe", recipe_plan=compile_recipe(RECIPE))
    slow_doc = copy.deepcopy(RECIPE)
    slow_doc["transport"]["delay_ms"] = 9000
    slow = build_adapter("demo", "recipe", recipe_plan=compile_recipe(slow_doc))
    assert fast.pacing_scope() == "recipe:careers.demo.com"
    assert fast.min_delay == fast.settings.scraper_min_delay_seconds
    assert slow.min_delay == 9.0


# --- preview and validation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_is_bounded_and_never_claims_completeness(monkeypatch):
    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                         "https://careers.demo.com/robots.txt": ROBOTS_OK})
    check = await recipe_preview.preview_document(RECIPE)
    assert [job["req_id"] for job in check.jobs] == ["J1", "J2"]
    assert not check.list_complete and not check.passed and check.robots["allowed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("robots", [
    "User-agent: *\nDisallow: /jobs\n",
    httpx.Response(503),
], ids=["disallowed", "unreadable"])
async def test_preview_reads_robots_first_and_fetches_nothing_it_may_not(monkeypatch, robots):
    asked = _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                                 "https://careers.demo.com/robots.txt": robots})
    check = await recipe_preview.preview_document(RECIPE)
    assert asked == ["https://careers.demo.com/robots.txt"]
    assert check.jobs == [] and check.robots["allowed"] is False and check.errors


@pytest.mark.asyncio
async def test_validation_needs_a_natural_end_and_robots_permission(monkeypatch):
    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                         "https://careers.demo.com/robots.txt": ROBOTS_OK})
    assert (await recipe_preview.validate_document(RECIPE)).passed

    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                         "https://careers.demo.com/robots.txt": "User-agent: *\nDisallow: /jobs\n"})
    refused = await recipe_preview.validate_document(RECIPE)
    assert not refused.passed and refused.robots["allowed"] is False

    capped = copy.deepcopy(RECIPE)
    capped["pagination"] = {"mode": "page_number", "param": "p", "max_pages": 1}
    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                         "https://careers.demo.com/jobs?p=1": PAGE,
                         "https://careers.demo.com/robots.txt": ROBOTS_OK})
    assert not (await recipe_preview.validate_document(capped)).passed, "our page bound is not an end"


_RESERVED = {**RECIPE, "transport": {"mode": "render"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("check", ["preview_document", "validate_document", "shadow_document"])
async def test_a_recipe_the_runtime_refuses_never_previews_validates_or_shadows(monkeypatch, check):
    """Each check runs exactly what a scheduled run would: a transport the run
    refuses is a named problem here, before any request, never a pass over httpx."""
    asked = _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                                 "https://careers.demo.com/robots.txt": ROBOTS_OK})
    result = await getattr(recipe_preview, check)(_RESERVED)
    assert asked == [] and result.found == 0 and not result.passed
    assert any(p.startswith("schema: transport/mode:") for p in result.problems)
    assert "validated_at" not in result.evidence()


@pytest.mark.asyncio
async def test_the_shared_runtime_test_guards_the_check_runner_itself(monkeypatch):
    """A plan that reaches `_run` with a reserved transport is refused by the
    same test `RecipeAdapter.fetch` uses, whatever compiled it."""
    asked = _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE})
    plan = replace(compile_recipe(RECIPE), transport_mode="render")
    result = await recipe_preview._run(plan, seconds=5.0, max_items=None)
    assert asked == [] and result.jobs == []
    assert result.problems == ["transport: mode 'render' has no runtime; a recipe runs static_http"]


@pytest.mark.asyncio
async def test_preview_shows_the_posting_date_the_recipe_reads(monkeypatch):
    dated = PAGE.replace("<h2>Staff Eng</h2>", '<h2>Staff Eng</h2><time datetime="2026-09-30">x</time>')
    _serve(monkeypatch, {"https://careers.demo.com/jobs": dated,
                         "https://careers.demo.com/robots.txt": ROBOTS_OK})
    doc = copy.deepcopy(RECIPE)
    doc["listing"]["fields"]["posted_at"] = {"css": "time", "attr": "datetime",
                                             "transforms": [{"op": "parse_date"}]}
    check = await recipe_preview.preview_document(doc)
    assert [job["posted_at"] for job in check.jobs] == ["2026-09-30T00:00:00+00:00", None]


async def _stored_binding(session, document: dict) -> ConnectorRecipeRevision:
    """A revision already in the database that the contract no longer admits,
    bound to a company: written straight to the tables, as no save path would."""
    session.add(TrackedCompany(slug="demo", display="Demo", status="pending", enabled=True, visible=True))
    recipe = ConnectorRecipe(slug="demo-careers", status="active")
    session.add(recipe)
    await session.flush()
    revision = ConnectorRecipeRevision(recipe_id=recipe.id, version=1, document=document,
                                       checksum=checksum_document(document), validation={},
                                       created_by="settings")
    session.add(revision)
    await session.flush()
    recipe.default_revision_id = revision.id
    await bind_recipe(session, "demo", "demo-careers")
    return revision


def _with_typo() -> dict:
    doc = copy.deepcopy(RECIPE)
    doc["listing"]["fields"]["locaitons"] = {"css": ".loc"}
    return doc


def _with_post() -> dict:
    doc = copy.deepcopy(RECIPE)
    doc["listing"].update({"method": "POST", "body": {"page": 1}})
    return doc


def _with_bare_suffix() -> dict:
    return {**copy.deepcopy(RECIPE), "match": {"domains": ["com"]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("document,loads,problem", [
    (_RESERVED, True, "schema: transport/mode: 'render' is not one of ['static_http']"),
    (_with_typo(), True, "schema: listing/fields: 'locaitons' is not one of"),
    (_with_post(), False, "schema: listing/method: 'POST' is not one of ['GET']"),
    (_with_bare_suffix(), False, "schema: match/domains/0: 'com' does not match"),
], ids=["reserved-transport", "unknown-field", "post", "bare-suffix"])
async def test_a_stored_revision_outside_the_contract_loads_or_is_refused_by_name(
    db_session, monkeypatch, document, loads, problem,
):
    """Loading never crashes: a revision the runtime can still run (or refuse by
    name at fetch) keeps its plan; one that cannot compile gets none, and the
    collector reports the company unattempted. Validating it again names the
    problem, and saving it as a new draft is refused."""
    await _stored_binding(db_session, document)
    targets = {"demo": {"adapter": "recipe"}}
    await attach_recipe_plans(db_session, targets)
    assert (targets["demo"]["recipe_plan"] is not None) is loads

    asked = _serve(monkeypatch, {"https://careers.demo.com/robots.txt": ROBOTS_OK,
                                 "https://careers.demo.com/jobs": PAGE})
    check = await recipe_preview.validate_document(document)
    assert asked == [] and not check.passed
    assert any(p.startswith(problem) for p in check.problems), check.problems
    with pytest.raises(RecipeError):
        await save_draft_revision(db_session, slug="demo-careers", document=document)


@pytest.mark.asyncio
async def test_a_stored_revision_with_an_unread_field_still_collects(monkeypatch, db_session):
    await _stored_binding(db_session, _with_typo())
    targets = {"demo": {"adapter": "recipe"}}
    await attach_recipe_plans(db_session, targets)
    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                         "https://careers.demo.com/robots.txt": ROBOTS_OK})
    result = await collect_source(
        "demo", targets["demo"], EMPTY_SCOPE, None,
        max_list=None, hydrate=False, limiter_pool=RateLimiterPool(),
    )
    assert {key.split(":")[-1] for key in result.seen_keys} == {"J1", "J2"}
    assert result.list_complete


@pytest.mark.asyncio
async def test_only_a_passing_validation_stamps_the_revision(db_session):
    revision = await save_draft_revision(db_session, slug="demo-careers", document=RECIPE)
    await record_validation(db_session, revision_id=revision.id,
                            evidence={"passed": False, "validated_at": "2026-09-26T00:00:00+00:00"})
    assert "validated_at" not in revision.validation
    await record_validation(db_session, revision_id=revision.id,
                            evidence={"passed": True, "validated_at": "2026-09-26T00:00:00+00:00"})
    assert revision.validation["validated_at"]


# --- over HTTP ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_routes_draft_preview_activate_and_bind(api_client, db_session, monkeypatch):
    _serve(monkeypatch, {"https://careers.demo.com/jobs": PAGE,
                         "https://careers.demo.com/robots.txt": ROBOTS_OK})
    db_session.add(TrackedCompany(slug="demo", display="Demo", status="pending", enabled=True, visible=True))
    await db_session.commit()

    bad = await api_client.post("/api/connector-recipes", json={"document": {**RECIPE, "xpath": "//a"}})
    assert bad.status_code == 422

    saved = await api_client.post("/api/connector-recipes", json={"document": RECIPE})
    assert saved.status_code == 201
    revision_id = saved.json()["revision_id"]

    preview = await api_client.post("/api/connectors/preview", json={"document": RECIPE})
    assert preview.status_code == 200 and preview.json()["found"] == 2

    unbound = await api_client.post("/api/companies/demo/recipe", json={"recipe": "demo-careers"})
    assert unbound.status_code == 409, "a draft cannot be bound"

    activated = await api_client.post("/api/connector-recipes/demo-careers/activate",
                                      json={"revision_id": revision_id})
    assert activated.status_code == 200 and activated.json()["active_revision_id"] == revision_id

    validated = await api_client.post(f"/api/connector-recipes/demo-careers/revisions/{revision_id}/validate")
    assert validated.status_code == 200 and validated.json()["passed"] is True

    bound = await api_client.post("/api/companies/demo/recipe", json={"recipe": "demo-careers"})
    assert bound.status_code == 201
    assert bound.json()["closure_capability"] == "none"

    listing = (await api_client.get("/api/connector-recipes")).json()
    assert listing == [{
        "slug": "demo-careers", "status": "active", "domains": ["careers.demo.com"], "versions": 1,
        "active_revision_id": revision_id, "active_version": 1, "active_validated": True,
        "companies": ["demo"],
    }]
