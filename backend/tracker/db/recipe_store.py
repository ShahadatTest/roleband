"""Recipe persistence: append-only revisions + activation.

Enforces the invariants a bare table cannot: a document is compiled before it is
stored (an uncompilable recipe never reaches the DB), every edit is a NEW
revision keyed by a content checksum, and activation only ever changes the
*default* revision — it never retargets an existing stable binding (moving a
binding to a new revision is a rebind).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.connectors.extract import extractor_fingerprint
from tracker.connectors.extract.version import validation_is_current
from tracker.connectors.recipes import ExecutablePlan, compile_recipe
from tracker.db.models import ConnectorRecipe, ConnectorRecipeRevision, SourceBinding

if TYPE_CHECKING:
    # `company_store` imports this module to seed the bundled recipes.
    from tracker.company_store import ScanTarget

__all__ = [
    "activate_revision",
    "attach_recipe_plans",
    "ensure_bundled_recipes",
    "get_recipe",
    "get_revision",
    "list_recipes",
    "record_validation",
    "checksum_document",
    "compile_binding_plan",
    "save_draft_revision",
]


async def compile_binding_plan(
    session: AsyncSession, binding: SourceBinding
) -> ExecutablePlan | None:
    """Compile the recipe revision a binding is pinned to, into a runnable plan.

    Returns None when the binding is not recipe-backed (e.g. an adapter
    binding) or its pinned revision is missing. Compiling from the *pinned*
    revision, not the recipe's current default, is what keeps a stable binding on
    its validated document even after the recipe is edited. The revision is
    compiled as stored (`stored=True`): one that names a reserved transport or a
    field the runner does not read still loads. The adapter refuses the
    transport by name; the runner skips the field.
    """
    if binding.connector_kind != "recipe" or binding.recipe_revision_id is None:
        return None
    revision = (
        await session.execute(
            select(ConnectorRecipeRevision).where(
                ConnectorRecipeRevision.id == binding.recipe_revision_id
            )
        )
    ).scalars().first()
    if revision is None:
        return None
    return compile_recipe(revision.document, stored=True)


def checksum_document(document: dict) -> str:
    """Stable content hash. Canonical JSON so key order never changes the hash."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


#: The two-int lock namespace for appending a recipe's revisions, keyed by
#: `hashtext(slug)`.
RECIPE_DRAFT_LOCK_NAMESPACE = 91245


async def save_draft_revision(
    session: AsyncSession,
    *,
    slug: str,
    document: dict,
    created_by: str = "system",
    provenance: dict | None = None,
) -> ConnectorRecipeRevision:
    """Compile, then append a revision. Never mutates an existing revision.

    Raises `RecipeError` if the document does not compile — an invalid recipe is
    rejected at the boundary rather than stored and discovered at run time.
    """
    compile_recipe(document)  # raises RecipeError; never store an uncompilable doc

    # One draft of a recipe at a time: HTTP and the MCP agent both
    # land here, and without the lock each read-then-insert (the slug, then
    # `last + 1`) lets two concurrent drafts collide on a unique key, the valid
    # one failing.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:slug))"),
        {"ns": RECIPE_DRAFT_LOCK_NAMESPACE, "slug": slug},
    )
    recipe = (
        await session.execute(select(ConnectorRecipe).where(ConnectorRecipe.slug == slug))
    ).scalars().first()
    if recipe is None:
        recipe = ConnectorRecipe(
            slug=slug,
            kind=document.get("kind", "job_listing"),
            format_version=document.get("format_version", 1),
            status="draft",
            provenance=provenance or {},
        )
        session.add(recipe)
        await session.flush()

    last = (
        await session.execute(
            select(ConnectorRecipeRevision)
            .where(ConnectorRecipeRevision.recipe_id == recipe.id)
            .order_by(ConnectorRecipeRevision.version.desc())
        )
    ).scalars().first()
    next_version = (last.version + 1) if last else 1

    revision = ConnectorRecipeRevision(
        recipe_id=recipe.id,
        version=next_version,
        document=document,
        checksum=checksum_document(document),
        validation={},  # empty until a validate action runs
        created_by=created_by,
    )
    session.add(revision)
    await session.flush()
    return revision


async def activate_revision(
    session: AsyncSession, *, recipe_id: int, revision_id: int
) -> ConnectorRecipe:
    """Make a validated revision the default for NEW/proposed bindings.

    Records the extractor fingerprint on the revision's validation record and
    flips the recipe to `active`. Existing stable bindings stay pinned to
    whatever revision they already reference — activation never retargets them.
    """
    recipe = (await session.execute(
        select(ConnectorRecipe).where(ConnectorRecipe.id == recipe_id)
    )).scalars().first()
    if recipe is None:
        raise ValueError(f"no recipe {recipe_id}")
    revision = (await session.execute(
        select(ConnectorRecipeRevision).where(
            ConnectorRecipeRevision.id == revision_id,
            ConnectorRecipeRevision.recipe_id == recipe_id,
        )
    )).scalars().first()
    if revision is None:
        raise ValueError(f"no revision {revision_id} for recipe {recipe_id}")

    if not revision.validation:
        revision.validation = extractor_fingerprint()
    recipe.default_revision_id = revision.id
    recipe.status = "active"
    await session.flush()
    return recipe


async def record_validation(
    session: AsyncSession, *, revision_id: int, evidence: dict
) -> ConnectorRecipeRevision:
    """Store RoleBand's own validation of a revision.

    `evidence` is what `workflows.recipe_preview.validate_document` measured;
    only a PASSING run is stamped `validated_at`, which is the single fact
    `decide_binding_activation` reads before a recipe binding may earn closure.
    A failing run is recorded too (an author sees why) but grants nothing.
    """
    revision = await session.get(ConnectorRecipeRevision, revision_id)
    if revision is None:
        raise ValueError(f"no revision {revision_id}")
    record = {**extractor_fingerprint(), **evidence}
    if not evidence.get("passed"):
        record.pop("validated_at", None)
    revision.validation = record
    await session.flush()
    return revision


async def attach_recipe_plans(session: AsyncSession, targets: dict[str, ScanTarget]) -> None:
    """Give each recipe-bound target its pinned, compiled plan (`cfg["recipe_plan"]`).

    A target whose binding or revision is missing, or whose document does not
    compile, gets none; `build_adapter` then refuses it by name rather than
    running something else.
    """
    for slug, cfg in targets.items():
        if cfg.get("adapter") != "recipe":
            continue
        binding = await session.scalar(
            select(SourceBinding).where(
                SourceBinding.company_slug == slug, SourceBinding.status == "stable",
                SourceBinding.connector_kind == "recipe",
            )
        )
        try:
            cfg["recipe_plan"] = await compile_binding_plan(session, binding) if binding else None
        except ValueError:
            cfg["recipe_plan"] = None


def _revision_row(revision: ConnectorRecipeRevision) -> dict:
    validation = revision.validation or {}
    return {
        "id": revision.id, "version": revision.version, "checksum": revision.checksum,
        "created_at": revision.created_at, "created_by": revision.created_by,
        "document": revision.document,
        "validated_at": validation.get("validated_at"),
        "validation": validation,
    }


async def _companies_using(session: AsyncSession, slug: str) -> list[str]:
    return sorted((await session.scalars(
        select(SourceBinding.company_slug).where(
            SourceBinding.connector_kind == "recipe", SourceBinding.connector_id == slug,
            SourceBinding.status != "retired",
        )
    )).all())


async def list_recipes(session: AsyncSession) -> list[dict]:
    """Every recipe: status, active revision, whether it is validated, who uses it."""
    out: list[dict] = []
    for recipe in (await session.scalars(select(ConnectorRecipe).order_by(ConnectorRecipe.slug))).all():
        revisions = (await session.scalars(
            select(ConnectorRecipeRevision).where(ConnectorRecipeRevision.recipe_id == recipe.id)
        )).all()
        active = next((r for r in revisions if r.id == recipe.default_revision_id), None)
        latest = max(revisions, key=lambda r: r.version, default=None)
        document = (active or latest).document if (active or latest) else {}
        out.append({
            "slug": recipe.slug, "status": recipe.status,
            "domains": list((document.get("match") or {}).get("domains") or []),
            "versions": len(revisions),
            "active_revision_id": recipe.default_revision_id,
            "active_version": active.version if active else None,
            "active_validated": bool(active and validation_is_current(active.validation)),
            "companies": await _companies_using(session, recipe.slug),
        })
    return out


async def get_recipe(session: AsyncSession, slug: str) -> dict | None:
    recipe = await session.scalar(select(ConnectorRecipe).where(ConnectorRecipe.slug == slug))
    if recipe is None:
        return None
    revisions = (await session.scalars(
        select(ConnectorRecipeRevision).where(ConnectorRecipeRevision.recipe_id == recipe.id)
        .order_by(ConnectorRecipeRevision.version.desc())
    )).all()
    return {
        "slug": recipe.slug, "status": recipe.status,
        "active_revision_id": recipe.default_revision_id,
        "companies": await _companies_using(session, recipe.slug),
        "revisions": [_revision_row(r) for r in revisions],
    }


async def get_revision(session: AsyncSession, slug: str, revision_id: int) -> ConnectorRecipeRevision | None:
    return await session.scalar(
        select(ConnectorRecipeRevision).join(
            ConnectorRecipe, ConnectorRecipe.id == ConnectorRecipeRevision.recipe_id
        ).where(ConnectorRecipe.slug == slug, ConnectorRecipeRevision.id == revision_id)
    )


async def ensure_bundled_recipes(session: AsyncSession) -> list[str]:
    """Seed the recipes RoleBand ships (`connectors.recipes.bundled`).

    Idempotent on content: a bundled document whose checksum is already the
    recipe's ACTIVE revision is left alone; an edited one becomes a new
    revision and the new default. Existing bindings stay pinned (activation
    never retargets them). Never validates: that is a live whole-page check.
    Returns the slugs it saved.
    """
    from tracker.connectors.recipes.bundled import BUNDLED_RECIPES

    saved: list[str] = []
    for slug, bundled in BUNDLED_RECIPES.items():
        checksum = checksum_document(bundled.document)
        recipe = await session.scalar(select(ConnectorRecipe).where(ConnectorRecipe.slug == slug))
        if recipe is not None and recipe.default_revision_id is not None:
            active = await session.get(ConnectorRecipeRevision, recipe.default_revision_id)
            if active is not None and active.checksum == checksum:
                continue
        revision = await save_draft_revision(
            session, slug=slug, document=bundled.document, created_by="bundled",
            provenance={"bundled": True, "evidence": bundled.evidence},
        )
        await activate_revision(session, recipe_id=revision.recipe_id, revision_id=revision.id)
        saved.append(slug)
    return saved
