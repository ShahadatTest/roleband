"""Response contracts for the profile suggestion routes.

The same two strictness rules as `schemas/jobs.py`, for the same reasons:

- **A shape our code builds forbids unknown keys** (`extra="forbid"`): the
  suggestion row `_serialize_suggestion` builds and the three envelopes around
  it. A key the serializer adds without its model is a 500 a test catches.
- **A shape read from JSONB allows unknown keys and keeps them**: `basis` is
  stored by `post_pass:profile_inference` and returned verbatim, so a key a later
  writer adds reaches the client instead of being filtered out of the response.

Literal types appear only where the database enforces the value: `kind` and
`status` are held by `ck_profile_suggestion_kind` and
`ck_profile_suggestion_status`. `world` stays `str`: it comes from a JSONB
payload with no constraint, and a world the taxonomy has since retired is still
served, with its slug as `display`.

Every `basis` key is required: the one writer (`user_profile.inference._basis`)
sets all eight.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from tracker.api.schemas.base import Built, Stored

# Held to the table's CHECK constraints by `tests/test_api_profile_suggestions_contract.py`.
SuggestionKind = Literal["world_on", "world_off"]
SuggestionStatus = Literal["pending", "accepted", "dismissed"]


class ProfileSuggestionBasis(Stored):
    """Why inference raised the suggestion: the counts and matches behind `score`."""

    score: float
    favorited: int
    pursued: int
    dismissed_wrong_domain: int
    dismissed_other: int
    sectors: list[str]
    intent_matched: bool
    background: int


class ProfileSuggestionRow(Built):
    """One inferred adjustment, as the list and both verdicts answer with it."""

    id: int
    kind: SuggestionKind
    #: The world's slug; the dashboard names it.
    world: str
    basis: ProfileSuggestionBasis
    status: SuggestionStatus
    created_at: datetime


class ProfileSuggestionListResponse(Built):
    """`GET /api/profile/suggestions`: pending only, oldest first, then by id."""

    suggestions: list[ProfileSuggestionRow]


class ProfileSuggestionAcceptResponse(Built):
    """`POST /api/profile/suggestions/{id}/accept`: the resolved row, the worlds
    axis and the "not interested in" veto as saved (an accept can move either),
    and how many roles' `in_scope` the recompute changed."""

    suggestion: ProfileSuggestionRow
    enabled_domain_groups: list[str]
    excluded_domain_groups: list[str]
    in_scope_changed: int
    #: Postings a sync already read that this save put on the Board,
    #: and whether more wait for the running sync's end.
    promoted: int
    promotion_pending: bool


class ProfileSuggestionDismissResponse(Built):
    """`POST /api/profile/suggestions/{id}/dismiss`: the resolved row, nothing else."""

    suggestion: ProfileSuggestionRow
