"""Response contracts for the recipe routes.

Every shape here is one our code builds, so every model forbids unknown keys.
A recipe `document` and a revision's `validation` record are JSONB we store and
hand back as they are, so they stay `dict`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from tracker.api.schemas.text_class import text


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipeSummary(_Strict):
    slug: str
    status: str
    domains: list[str]
    versions: int
    active_revision_id: int | None
    active_version: int | None
    active_validated: bool
    companies: list[str]


class RecipeList(RootModel[list[RecipeSummary]]):
    """`GET /api/connector-recipes`: every recipe, by slug."""


class RecipeRevisionRow(_Strict):
    id: int
    version: int
    checksum: str
    created_at: datetime
    created_by: str
    document: dict
    validated_at: str | None
    validation: dict


class RecipeDetail(_Strict):
    slug: str
    status: str
    active_revision_id: int | None
    companies: list[str]
    revisions: list[RecipeRevisionRow]


class SavedRevision(_Strict):
    slug: str
    revision_id: int
    version: int


class PreviewJob(_Strict):
    req_id: str
    title: str = Field(json_schema_extra=text("content"))
    url: str
    locations: list[str]
    posted_at: str | None


class RecipeCheckResult(_Strict):
    """A preview (bounded, write-free) or a validation (whole listing)."""

    passed: bool
    problems: list[str]
    errors: list[str]
    found: int
    pages: int
    list_complete: bool
    robots: dict
    jobs: list[PreviewJob]


class RecipeBindingRow(_Strict):
    company: str
    recipe: str
    binding_id: int
    revision_id: int
    closure_capability: str


class ReconciliationDecisionRow(_Strict):
    id: int
    decision: str = Field(json_schema_extra=text("code"))
    job_id: int | None
    source_key: str | None
    evidence: dict
    actor: str = Field(json_schema_extra=text("code"))
    reason: str | None = Field(json_schema_extra=text("content"))


class RecipeReconciliation(_Strict):
    company: str
    binding_id: int
    previous_binding_id: int
    status: str = Field(json_schema_extra=text("code"))
    unresolved_job_ids: list[int]
    unresolved_source_keys: list[str]
    conflicts: bool
    ready: bool
    decisions: list[ReconciliationDecisionRow]


class AdapterCapabilityRow(_Strict):
    """One registered adapter's class-level declarations
    (`connectors.listing.capability_table`), read off the class, never a run."""

    name: str = Field(json_schema_extra=text("identifier"))
    #: `board` lists the whole board; `filtered` and `windowed` list a slice.
    listing_scope: Literal["board", "filtered", "windowed"] = Field(json_schema_extra=text("code"))
    #: Where a posting's text comes from: the listing (`inline`) or one read each.
    detail: Literal["inline", "per_posting"] = Field(json_schema_extra=text("code"))
    text_from_posting: bool
    #: The board states its own total, which proves a complete listing.
    declares_total: bool
    #: The family can count a pasted board before it is followed.
    board_probe: bool
    #: The family can read one posting's page on demand.
    posting_page: bool
    #: The SDK capabilities the class requires; None when it declares none.
    transport: list[str] | None


class AdapterCapabilityTable(_Strict):
    items: list[AdapterCapabilityRow]
