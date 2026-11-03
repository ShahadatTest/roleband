"""Recipe routes: draft, preview, validate, activate, bind.

Transport and wire shape only. Every write goes through a store
(`db.recipe_store` for recipes and revisions, `company_store.bind_recipe` for the
one binding a company collects through); every live read goes through
`workflows.recipe_preview`, which runs the recipe on the same pinned,
host-checked transport a scheduled run uses.

Closure authority is never a route: a recipe binding earns it only through a
run, and only while its pinned revision carries RoleBand's validation.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from tracker.api.company_errors import company_error
from tracker.api.deps import SessionDep, end_read
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.recipes import (
    AdapterCapabilityTable,
    RecipeBindingRow,
    RecipeCheckResult,
    RecipeDetail,
    RecipeList,
    RecipeReconciliation,
    RecipeSummary,
    SavedRevision,
)
from tracker.api.schemas.text_class import text
from tracker.company_store import CompanyError, bind_recipe
from tracker.connectors.listing import capability_table
from tracker.connectors.recipes import RecipeError
from tracker.db import reconciliation
from tracker.db.recipe_store import (
    activate_revision,
    get_recipe,
    get_revision,
    list_recipes,
    record_validation,
    save_draft_revision,
)
from tracker.workflows.recipe_preview import (
    RecipeCheck,
    preview_document,
    shadow_document,
    validate_document,
)

router = APIRouter()


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftPayload(_Payload):
    document: dict


class PreviewPayload(_Payload):
    document: dict


class ActivatePayload(_Payload):
    revision_id: int = Field(ge=1)


class BindPayload(_Payload):
    recipe: str = Field(min_length=2, max_length=64)


class ReconciliationReviewPayload(_Payload):
    decision: Literal["map", "new", "retire"]
    source_key: str | None = Field(default=None, max_length=256)
    job_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=2000, json_schema_extra=text("content"))


class RollbackPayload(_Payload):
    reason: str = Field(min_length=1, max_length=2000, json_schema_extra=text("content"))


def _check(check: RecipeCheck) -> dict:
    return {
        "passed": check.passed, "problems": check.problems, "errors": check.errors,
        "found": check.found, "pages": check.pages, "list_complete": check.list_complete,
        "robots": check.robots, "jobs": check.jobs,
    }


@router.get("/api/connector-recipes", response_model=RecipeList)
async def recipes_index(session: SessionDep) -> list[dict]:
    return await list_recipes(session)


@router.get("/api/connector-recipes/{slug}", response_model=RecipeDetail)
async def recipe_detail(slug: str, session: SessionDep) -> dict:
    recipe = await get_recipe(session, slug)
    if recipe is None:
        raise api_error(404, ErrorCode.RECIPE_NOT_FOUND, f"no recipe '{slug}'")
    return recipe


@router.post("/api/connector-recipes", status_code=201, response_model=SavedRevision)
async def save_recipe_draft(payload: DraftPayload, session: SessionDep) -> dict:
    """Append a draft revision; its `id` names the recipe. Never activates."""
    slug = payload.document.get("id")
    if not isinstance(slug, str):
        raise api_error(400, ErrorCode.RECIPE_INVALID, "the recipe document needs an `id`")
    try:
        revision = await save_draft_revision(
            session, slug=slug, document=payload.document, created_by="settings",
        )
    except RecipeError as exc:
        raise api_error(422, ErrorCode.RECIPE_INVALID, "; ".join(str(p) for p in exc.problems), problems=[str(p) for p in exc.problems]) from exc
    await session.commit()
    return {"slug": slug, "revision_id": revision.id, "version": revision.version}


@router.get("/api/connectors/capabilities", response_model=AdapterCapabilityTable)
async def connector_capabilities() -> dict:
    """What each registered adapter family declares it can do: prove a
    complete listing, count a pasted board, read a posting's page. Read-only."""
    return {"items": [asdict(row) for row in capability_table()]}


@router.post("/api/connectors/preview", response_model=RecipeCheckResult)
async def preview_recipe(payload: PreviewPayload) -> dict:
    """Two pages, five postings, no writes."""
    return _check(await preview_document(payload.document))


@router.post(
    "/api/connector-recipes/{slug}/revisions/{revision_id}/validate",
    response_model=RecipeCheckResult,
)
async def validate_recipe_revision(slug: str, revision_id: int, session: SessionDep) -> dict:
    """Read the whole listing live; a pass is what lets a binding earn closure."""
    revision = await get_revision(session, slug, revision_id)
    if revision is None:
        raise api_error(404, ErrorCode.RECIPE_NOT_FOUND, f"no revision {revision_id} of '{slug}'")
    await end_read(session)
    check = await validate_document(revision.document)
    await record_validation(session, revision_id=revision.id, evidence=check.evidence())
    await session.commit()
    return _check(check)


@router.post("/api/connector-recipes/{slug}/activate", response_model=RecipeSummary)
async def activate_recipe(slug: str, payload: ActivatePayload, session: SessionDep) -> dict:
    """Make a revision the default for NEW bindings. Existing bindings stay pinned."""
    revision = await get_revision(session, slug, payload.revision_id)
    if revision is None:
        raise api_error(404, ErrorCode.RECIPE_NOT_FOUND, f"no revision {payload.revision_id} of '{slug}'")
    await activate_revision(session, recipe_id=revision.recipe_id, revision_id=revision.id)
    await session.commit()
    return next(row for row in await list_recipes(session) if row["slug"] == slug)


@router.post("/api/companies/{company}/recipe", status_code=201, response_model=RecipeBindingRow)
async def bind_company_recipe(company: str, payload: BindPayload, session: SessionDep) -> dict:
    """Collect a company through a recipe's activated revision."""
    try:
        binding = await bind_recipe(session, company, payload.recipe)
    except CompanyError as exc:
        raise company_error(exc) from exc
    await session.commit()
    return {
        "company": company, "recipe": payload.recipe, "binding_id": binding.id,
        "revision_id": binding.recipe_revision_id, "closure_capability": binding.closure_capability,
    }


@router.post("/api/companies/{company}/recipe-rebind", status_code=201, response_model=RecipeReconciliation)
async def propose_recipe_rebind(company: str, payload: BindPayload, session: SessionDep) -> dict:
    """Shadow the complete listing, then save the comparison for review."""
    try:
        revision = await reconciliation.recipe_revision(session, payload.recipe)
        await end_read(session)
        check = await shadow_document(revision.document)
        result = await reconciliation.propose(session, company, recipe_slug=payload.recipe,
                                              revision_id=revision.id, jobs=check.jobs,
                                              evidence=check.evidence())
    except CompanyError as exc:
        raise company_error(exc) from exc
    await session.commit()
    return result


@router.get("/api/companies/{company}/recipe-rebind/{binding_id}", response_model=RecipeReconciliation)
async def get_recipe_rebind(company: str, binding_id: int, session: SessionDep) -> dict:
    try:
        return await reconciliation.detail(session, company, binding_id)
    except CompanyError as exc:
        raise company_error(exc) from exc


@router.post("/api/companies/{company}/recipe-rebind/{binding_id}/decisions", response_model=RecipeReconciliation)
async def review_recipe_rebind(company: str, binding_id: int, payload: ReconciliationReviewPayload, session: SessionDep) -> dict:
    try:
        result = await reconciliation.review(session, company, binding_id, **payload.model_dump())
    except CompanyError as exc:
        raise company_error(exc) from exc
    await session.commit()
    return result


@router.post("/api/companies/{company}/recipe-rebind/{binding_id}/activate", response_model=RecipeReconciliation)
async def activate_recipe_rebind(company: str, binding_id: int, session: SessionDep) -> dict:
    try:
        result = await reconciliation.activate(session, company, binding_id)
    except CompanyError as exc:
        raise company_error(exc) from exc
    await session.commit()
    return result


@router.post("/api/companies/{company}/recipe-rebind/{binding_id}/rollback", response_model=RecipeReconciliation)
async def rollback_recipe_rebind(company: str, binding_id: int, payload: RollbackPayload, session: SessionDep) -> dict:
    try:
        result = await reconciliation.rollback(session, company, binding_id, reason=payload.reason)
    except CompanyError as exc:
        raise company_error(exc) from exc
    await session.commit()
    return result
