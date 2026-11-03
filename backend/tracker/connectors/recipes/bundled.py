"""Recipes RoleBand ships, reviewed like catalog entries.

A recipe is data, so a company whose only readable listing is its own careers
page ships as a document here instead of a new adapter class. Each entry is
seeded into the recipe tables by `db.recipe_store.ensure_bundled_recipes`
(saved and activated, idempotent on content) and named by a `CATALOG` row
`{"adapter": "recipe", "board_token": <recipe id>}`; following the company then
binds it to the pinned revision like any other company.

Seeding never validates: closure authority still needs RoleBand's own
whole-page check (`workflows.recipe_preview.validate_document`), run from
Settings > Recipes, so a bundled recipe collects from the start and closes
nothing until then.

Every entry records its measurement: what the page states, what the recipe
declares that the page does not, and the robots evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BUNDLED_RECIPES", "BundledRecipe"]


@dataclass(frozen=True)
class BundledRecipe:
    document: dict
    evidence: str


#: A recipe has no consent path, so a page whose robots.txt disallows its
#: listing route cannot ship here however readable it is. An entry must record
#: that robots allows its start URL; `RecipeAdapter.robots_allows` re-checks on
#: every run regardless.
BUNDLED_RECIPES: dict[str, BundledRecipe] = {}
