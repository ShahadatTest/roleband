"""The user-profile surface: inferred suggestions, the pay floor and pursuits.

The pursuit routes declare their responses in `api/schemas/profile.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from tracker.agents.pursuits import (
    PursuitStage,
    PursuitUpdate,
    list_pursuits,
    public_pursuit,
    upsert_pursuit,
)
from tracker.api.deps import SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.profile import (
    PayFloorResponse,
    PursuitListResponse,
    PursuitWriteResponse,
)
from tracker.api.schemas.profile_suggestions import (
    ProfileSuggestionAcceptResponse,
    ProfileSuggestionDismissResponse,
    ProfileSuggestionListResponse,
)
from tracker.api.scope_saves import promote_after_save, promotion_fields, queue_follow_up
from tracker.db.models import ProfileSuggestion
from tracker.notifications.pursuit_due import generate_pursuit_due_notifications
from tracker.scope.projection import recompute_saved_scope
from tracker.settings_store import (
    PAY_FLOOR_MAX,
    clear_pay_floor,
    get_enabled_domains,
    get_excluded_domains,
    get_pay_floor,
    names_interests,
    set_enabled_domains,
    set_excluded_domains,
    set_pay_floor,
)
from tracker.taxonomy.domains import all_slugs as all_domain_slugs

router = APIRouter()

# --- suggestions -------------------------------------------------------------

def _serialize_suggestion(row: ProfileSuggestion) -> dict:
    world = str(row.payload.get("world", ""))
    return {
        "id": row.id,
        "kind": row.kind,
        "world": world,
        "basis": row.basis,
        "status": row.status,
        "created_at": row.created_at,
    }


@router.get("/api/profile/suggestions", response_model=ProfileSuggestionListResponse)
async def list_profile_suggestions(session: SessionDep) -> dict:
    """Pending inferred adjustments. The inference pass
    proposes; only the two verdict endpoints below resolve."""
    rows = (
        await session.scalars(
            select(ProfileSuggestion)
            .where(ProfileSuggestion.status == "pending")
            .order_by(ProfileSuggestion.created_at.asc(), ProfileSuggestion.id.asc())
        )
    ).all()
    return {"suggestions": [_serialize_suggestion(row) for row in rows]}


async def _resolve_suggestion(
    session: SessionDep, suggestion_id: int, status: str
) -> ProfileSuggestion:
    row = await session.get(ProfileSuggestion, suggestion_id)
    if row is None:
        raise api_error(404, ErrorCode.SUGGESTION_NOT_FOUND, "unknown suggestion")
    if row.status != "pending":
        raise api_error(409, ErrorCode.SUGGESTION_DECIDED, f"already {row.status}")
    row.status = status
    row.resolved_at = datetime.now(UTC)
    return row


@router.post(
    "/api/profile/suggestions/{suggestion_id}/accept",
    response_model=ProfileSuggestionAcceptResponse,
)
async def accept_profile_suggestion(suggestion_id: int, session: SessionDep) -> dict:
    """The ONLY path from an inferred suggestion to a scope effect: an explicit
    human accept. Writes through the same stores a manual worlds edit uses, so
    every downstream consumer (scope gate, facets, relevance advisory) is
    untouched machinery."""
    row = await _resolve_suggestion(session, suggestion_id, "accepted")
    world = str(row.payload.get("world", ""))
    enabled = set(await get_enabled_domains(session))
    excluded = await get_excluded_domains(session)
    if row.kind == "world_off":
        next_enabled = enabled - {world}
        if not next_enabled:
            # set_enabled_domains rewrites empty to ALL (fail-open) — accepting
            # here would silently invert the user's intent. Refuse instead.
            raise api_error(409, ErrorCode.LAST_WORLD, "cannot exclude the last tracked world")
        # Written as the walk would write it: among interests,
        # dropping one ends the interest in it; with none, it is
        # "not interested in", the veto.
        if not names_interests(enabled, excluded):
            excluded = excluded | {world}
            await set_excluded_domains(session, sorted(excluded))
    else:
        next_enabled = enabled | {world}
        # Turning a world on must also lift a "not interested in" veto on it,
        # or the accept would change nothing on the radar.
        if world in excluded:
            excluded = excluded - {world}
            await set_excluded_domains(session, sorted(excluded))
    saved_domains = await set_enabled_domains(session, sorted(next_enabled), excluded=excluded)
    in_scope_changed = await recompute_saved_scope(session)
    promotion = await promote_after_save(session)
    await session.commit()
    await queue_follow_up(session, promotion)
    return {
        "suggestion": _serialize_suggestion(row),
        "enabled_domain_groups": saved_domains,
        "excluded_domain_groups": [slug for slug in all_domain_slugs() if slug in excluded],
        "in_scope_changed": in_scope_changed,
        **promotion_fields(promotion),
    }


@router.post(
    "/api/profile/suggestions/{suggestion_id}/dismiss",
    response_model=ProfileSuggestionDismissResponse,
)
async def dismiss_profile_suggestion(suggestion_id: int, session: SessionDep) -> dict:
    """Dismissed = never re-raised for this key (the pass suppresses resolved
    dedupe keys). Nothing else changes."""
    row = await _resolve_suggestion(session, suggestion_id, "dismissed")
    await session.commit()
    return {"suggestion": _serialize_suggestion(row)}


# --- pay floor (optional, narrows nothing) ------------------------

class PayFloorInput(BaseModel):
    amount: int = Field(gt=0, le=PAY_FLOOR_MAX)
    currency: str = Field(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")


@router.get("/api/profile/pay-floor", response_model=PayFloorResponse)
async def read_pay_floor(session: SessionDep) -> dict:
    """The optional pay floor; null when unset."""
    return {"pay_floor": await get_pay_floor(session)}


@router.put("/api/profile/pay-floor", response_model=PayFloorResponse)
async def save_pay_floor(payload: PayFloorInput, session: SessionDep) -> dict:
    """Save the floor. It narrows nothing: no scope, count or Board query reads it."""
    floor = await set_pay_floor(session, payload.amount, payload.currency)
    await session.commit()
    return {"pay_floor": floor}


@router.delete("/api/profile/pay-floor", response_model=PayFloorResponse)
async def remove_pay_floor(session: SessionDep) -> dict:
    await clear_pay_floor(session)
    await session.commit()
    return {"pay_floor": None}


# --- pursuits (the HTTP twin of the MCP write tool) --------------------------

@router.get("/api/pursuits", response_model=PursuitListResponse)
async def list_pursuits_ep(
    session: SessionDep,
    stage: PursuitStage | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict:
    return {"pursuits": await list_pursuits(session, stage=stage, limit=limit)}


@router.put("/api/jobs/{job_id}/pursuit", response_model=PursuitWriteResponse)
async def set_pursuit_ep(
    job_id: int, payload: PursuitUpdate, session: SessionDep
) -> dict:
    """Create/update the pursuit for one opportunity. Same helper the MCP
    write tool uses (one transaction: current row + append-only event), actor
    recorded as `user`. There is deliberately no DELETE: `withdrawn` is a
    stage, and history is the point."""
    try:
        pursuit = await upsert_pursuit(session, job_id, payload, actor="user")
    except LookupError as err:
        raise api_error(404, ErrorCode.JOB_NOT_FOUND, str(err)) from err
    # The reminder follows the pursuit in the same transaction:
    # an owed follow-up rings and an ended one retracts without a scan.
    await generate_pursuit_due_notifications(session)
    await session.commit()
    return {"pursuit": public_pursuit(pursuit)}
