"""Listing recipe engine v1.

Public surface: the schema (the published contract), the compiler
(document -> immutable `ExecutablePlan`, rejecting unknown/unsafe/XPath), the
transform allowlist, and the deterministic runner (plan -> `RawJob`s + honest
`list_complete`).
"""

from __future__ import annotations

from tracker.connectors.recipes.compiler import (
    ExecutablePlan,
    RecipeError,
    compile_recipe,
    runtime_problems,
)
from tracker.connectors.recipes.runner import RecipeRunResult, extract_items, run_plan
from tracker.connectors.recipes.schema import (
    RECIPE_V1_SCHEMA,
    TRANSFORM_NAMES,
    TRANSPORT_MODES,
)
from tracker.connectors.recipes.transforms import TransformError, apply_transforms

__all__ = [
    "RECIPE_V1_SCHEMA",
    "TRANSFORM_NAMES",
    "TRANSPORT_MODES",
    "ExecutablePlan",
    "RecipeError",
    "RecipeRunResult",
    "TransformError",
    "apply_transforms",
    "compile_recipe",
    "extract_items",
    "run_plan",
    "runtime_problems",
]
