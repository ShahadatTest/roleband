"""Scope settings, the governing scope catalog, and the persona profile layer.

The catalog's aggregation is `scope/catalog.py` and the stored-scope recompute
`scope/projection.py`; this module parses, saves and answers. What
each route answers with is declared in `api/schemas/scope.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.api import job_requests
from tracker.api.deps import OffBoardDep, SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.locale import LocaleSettings
from tracker.api.schemas.price_feed import PriceFeedKey, PriceFeedState
from tracker.api.schemas.retention import RetentionState, RetentionUpdate
from tracker.api.schemas.scope import (
    IntentStatementResponse,
    PlaceSearchResponse,
    ProfileStateResponse,
    RoleAnswerModel,
    ScopeAxes,
    ScopeCatalogResponse,
    ScopePreviewResponse,
    ScopeRefreshRequest,
    ScopeRefreshResponse,
    ScopeRuleCreateResponse,
    ScopeRuleDeleteResponse,
    ScopeRuleList,
    SettingsSaveResponse,
)
from tracker.api.scope_saves import promote_after_save, promotion_fields, queue_follow_up
from tracker.company_store import off_board_company_slugs
from tracker.config import get_settings
from tracker.db.inventory_store import retention_counts
from tracker.db.models import (
    AppSetting,
    CompanyScopeRule,
    TrackedCompany,
)
from tracker.db.queries.jobs import open_in_scope_count_stmt
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.levels import LEVELS
from tracker.platform.locks import advisory_unlock, try_advisory_lock
from tracker.profiles import prices as price_store
from tracker.scope.axes import AxesRequest, SavedAxes, ScopeInputError, write_scope_axes
from tracker.scope.catalog import build_scope_catalog
from tracker.scope.places import search_places
from tracker.scope.preview import preview_save
from tracker.scope.projection import recompute_saved_scope
from tracker.scope.promotion import PromotionResult
from tracker.semantic.embed import embed_query
from tracker.settings_store import (
    ENABLED_BANDS_KEY,
    ENABLED_DOMAINS_KEY,
    ENABLED_LOCATIONS_KEY,
    ENABLED_ROLES_KEY,
    ENABLED_TRACKS_KEY,
    INTENT_EMBEDDING_KEY,
    RETENTION_CHOICES,
    RETENTION_DEFAULT_DAYS,
    get_enabled_bands,
    get_enabled_domains,
    get_enabled_locations,
    get_enabled_roles,
    get_enabled_tracks,
    get_excluded_domains,
    get_excluded_locations,
    get_include_unstated_level,
    get_intent_embedding,
    get_locale,
    get_persona_profile,
    get_retention_days,
    get_retention_last,
    get_role_answers,
    has_levels,
    set_intent_embedding,
    set_locale,
    set_persona_profile,
    set_retention_days,
)
from tracker.taxonomy.domains import DOMAIN_GROUPS
from tracker.taxonomy.locations import canonical_location_slugs
from tracker.taxonomy.role_answers import (
    dump_answers,
)
from tracker.taxonomy.roles import ROLE_GROUPS
from tracker.taxonomy.tracks import TRACKS
from tracker.workflows.directory_sweep import read_follow

router = APIRouter()


@router.get(
    "/api/scope/catalog", response_model=ScopeCatalogResponse, response_model_exclude_unset=True
)
async def scope_catalog(
    session: SessionDep,
    hidden: OffBoardDep,
    cities: Annotated[list[str] | None, Query()] = None,
) -> dict:
    """`cities`: cities the Walk's draft names and has not saved, priced in
    this read (repeatable; the first 200 are read)."""
    return await build_scope_catalog(session, hidden, extra_cities=(cities or [])[:200])


# --------------------------------------------------------------------------- #
# Learned per-company exclusions. The employer's verbatim
# team/department becomes a rule ONLY by explicit user confirmation — the
# dismiss flow offers, this endpoint writes. Rules are part of what `in_scope`
# projects, so create/delete recompute it immediately, like a scope save.
# --------------------------------------------------------------------------- #


def _serialize_rule(rule: CompanyScopeRule) -> dict:
    return {
        "id": rule.id,
        "company": rule.company,
        "kind": rule.kind,
        "value": rule.value,
        "created_at": rule.created_at,
    }


class ScopeRulePayload(BaseModel):
    company: str
    kind: Literal["team", "department"]
    value: str


@router.get("/api/scope/rules", response_model=ScopeRuleList)
async def list_scope_rules(session: SessionDep) -> dict:
    rules = (
        await session.scalars(
            select(CompanyScopeRule).order_by(CompanyScopeRule.company, CompanyScopeRule.id)
        )
    ).all()
    return {"rules": [_serialize_rule(rule) for rule in rules]}


@router.post("/api/scope/rules", response_model=ScopeRuleCreateResponse)
async def create_scope_rule(payload: ScopeRulePayload, session: SessionDep) -> dict:
    value = payload.value.strip()
    if not value:
        raise api_error(422, ErrorCode.INVALID_INPUT, "rule value must be non-empty")
    if await session.get(TrackedCompany, payload.company) is None:
        raise api_error(404, ErrorCode.COMPANY_NOT_FOUND, f"unknown company: {payload.company!r}")
    existing = await session.scalar(
        select(CompanyScopeRule).where(
            CompanyScopeRule.company == payload.company,
            CompanyScopeRule.kind == payload.kind,
            func.lower(CompanyScopeRule.value) == value.lower(),
        )
    )
    if existing is not None:
        return {
            "rule": _serialize_rule(existing), "created": False, "in_scope_changed": 0,
            **promotion_fields(PromotionResult()),
        }
    rule = CompanyScopeRule(company=payload.company, kind=payload.kind, value=value)
    session.add(rule)
    await session.flush()
    in_scope_changed = await recompute_saved_scope(session)
    promotion = await promote_after_save(session)
    await session.commit()
    await queue_follow_up(session, promotion)
    return {
        "rule": _serialize_rule(rule), "created": True, "in_scope_changed": in_scope_changed,
        **promotion_fields(promotion),
    }


@router.delete("/api/scope/rules/{rule_id}", response_model=ScopeRuleDeleteResponse)
async def delete_scope_rule(rule_id: int, session: SessionDep) -> dict:
    rule = await session.get(CompanyScopeRule, rule_id)
    if rule is None:
        raise api_error(404, ErrorCode.RULE_NOT_FOUND, "rule not found")
    await session.delete(rule)
    await session.flush()
    # Recompute WITHOUT the rule: rows it excluded re-enter scope right away.
    in_scope_changed = await recompute_saved_scope(session)
    promotion = await promote_after_save(session)
    await session.commit()
    await queue_follow_up(session, promotion)
    return {"deleted": True, "in_scope_changed": in_scope_changed, **promotion_fields(promotion)}


@router.post(
    "/api/scope/refresh", response_model=ScopeRefreshResponse, response_model_exclude_unset=True
)
async def refresh_scope_catalog(
    session: SessionDep, payload: ScopeRefreshRequest | None = None
) -> dict:
    """Launch a list-only role/seniority inventory refresh.

    Sources that list only asked-for places are asked for the saved places and
    `payload.locations`, the draft's, so a place added on Where and
    not yet saved can be counted before the save. Unknown slugs are dropped.

    Unlike `/api/sync`, this runs `tracker.discover_roles`: it reads source listings
    and writes only `role_catalog` + per-company catalog status. It never writes
    jobs, observations, lifecycle events, demand metrics, or notifications.
    """
    settings = get_settings()
    locked = await try_advisory_lock(session, settings.advisory_lock_key)
    if not locked:
        return {"status": "deferred"}  # a scan holds the pipeline lock
    await advisory_unlock(session, settings.advisory_lock_key)
    # The probe above is only a courtesy check: the lock is released before the
    # discovery even starts, so it cannot prevent a pile-up of concurrent scans.
    # One request at a time is what makes repeated clicks safe.
    places = canonical_location_slugs(payload.locations) if payload else []
    if not await job_requests.ring_role_discovery(
        session, max_list=600, locations=places, requested_by="scope_refresh"
    ):
        return {"status": "already_running"}  # role discovery is queued or running
    await session.commit()
    return {"status": "started", "max_list": 600}


class SettingsPayload(BaseModel):
    enabled_role_groups: list[str]
    enabled_seniority_bands: list[str]
    # An axis a request leaves out keeps its saved value (tracks default to all
    # on first read; locations to the shipped defaults; domains to all: the
    # worlds axis narrows only by explicit choice).
    enabled_role_tracks: list[str] | None = None
    enabled_location_groups: list[str] | None = None
    enabled_domain_groups: list[str] | None = None
    # Subjects the user is not interested in (a veto). None = untouched.
    excluded_domain_groups: list[str] | None = None
    # Places excepted inside the included ones. None = untouched;
    # either way an exception outside every included place is dropped.
    excluded_location_groups: list[str] | None = None
    # Whether roles whose level isn't stated pass the level axis.
    # None = untouched.
    include_unstated_level: bool | None = None
    # Which roles of each kind. None = derive them from the flat
    # role and track fields this request carries (Welcome sends only those).
    role_answers: list[RoleAnswerModel] | None = None
    # Intent statement, carried here too so the raw
    # fine-tune path can save it without clobbering hand-tuned axes through
    # PUT /api/profile. None = untouched; "" = cleared.
    intent_statement: str | None = None
    # The persona's two stage markers, carried for the same reason as the
    # statement above: a fine-tuned install still edits its level with the
    # stage dimmer, and the stages live ONLY on the persona. Passengers, not
    # axes — sending them updates the persona's markers and nothing else about
    # it (crafts/disciplines/locations/domains stay as the user hand-tuned
    # them). Both or neither: half a pair is not a position.
    experience_stage: str | None = None
    target_stage: str | None = None


async def _save_intent_statement(session: AsyncSession, statement: str) -> str:
    """Embed the intent statement ONCE at save into the standing vector
    — queries then rank against the stored vector without
    touching the model. Skips when the text is unchanged and the stored vector
    is current, so a routine scope tweak never pays a model load. An empty
    statement clears the record."""
    statement = statement.strip()
    stored = await get_intent_embedding(session)
    if statement != (stored["statement"] if stored else ""):
        vector = (await embed_query(statement)) if statement else []
        await set_intent_embedding(session, statement, vector)
    return statement


async def _current_intent_statement(session: AsyncSession) -> str:
    """The statement as stored: the persona's copy, falling back to the
    embedding record for a profile-less (raw fine-tune only) install."""
    profile = await get_persona_profile(session)
    if profile is not None and isinstance(profile.get("intent_statement"), str):
        if profile["intent_statement"]:
            return str(profile["intent_statement"])
    row = await session.get(AppSetting, INTENT_EMBEDDING_KEY)
    if row is not None and isinstance(row.value, dict) and isinstance(
        row.value.get("statement"), str
    ):
        return str(row.value["statement"])
    return ""


class IntentStatementPayload(BaseModel):
    intent_statement: str


@router.put("/api/settings/intent", response_model=IntentStatementResponse)
async def put_intent_statement_ep(payload: IntentStatementPayload, session: SessionDep) -> dict:
    """Save the aim sentence alone (Settings > Intelligence > Fit ranking).

    A ranking signal, never a scope axis: nothing is recomputed, no role enters
    or leaves the radar. Embeds once when the text changed; "" clears both the
    stored vector and the persona copy."""
    statement = await _save_intent_statement(session, payload.intent_statement)
    profile = await get_persona_profile(session)
    if profile is not None and profile.get("intent_statement") != statement:
        await set_persona_profile(session, {**profile, "intent_statement": statement})
    await session.commit()
    return {"intent_statement": statement}


@router.get("/api/scope/places", response_model=PlaceSearchResponse)
async def search_places_ep(
    q: str = Query(min_length=1, max_length=80),
    limit: int = Query(10, ge=1, le=25),
) -> dict:
    """Every standard place a person may type: countries by their CLDR names,
    regions by their UN M49 names too, unions, and cities.
    Read-only and database-free."""
    return search_places(q, limit)


async def _board_count(session) -> int:
    """Open in-scope postings the visible Board holds (`open_in_scope_count_stmt`,
    the one spelling of that count)."""
    hidden = await off_board_company_slugs(session)
    return int(await session.scalar(open_in_scope_count_stmt(hidden)) or 0)


@router.get("/api/settings", response_model=ScopeAxes)
async def get_settings_ep(session: SessionDep) -> dict:
    roles = await get_enabled_roles(session)
    bands = await get_enabled_bands(session)
    tracks = await get_enabled_tracks(session)
    locations = await get_enabled_locations(session)
    domains = await get_enabled_domains(session)
    excluded = await get_excluded_domains(session)
    answers = await get_role_answers(session)
    excepted = await get_excluded_locations(session)
    return {
        "enabled_role_groups": [g.slug for g in ROLE_GROUPS if g.slug in roles],
        "enabled_seniority_bands": [level.slug for level in LEVELS if level.slug in bands],
        "enabled_role_tracks": [t.slug for t in TRACKS if t.slug in tracks],
        "enabled_location_groups": canonical_location_slugs(locations),
        "enabled_domain_groups": [g.slug for g in DOMAIN_GROUPS if g.slug in domains],
        "excluded_domain_groups": [g.slug for g in DOMAIN_GROUPS if g.slug in excluded],
        "role_answers": dump_answers(answers),
        "excluded_location_groups": canonical_location_slugs(excepted),
        "include_unstated_level": await get_include_unstated_level(session),
    }


async def _write_scope_axes(session: AsyncSession, payload: SettingsPayload) -> SavedAxes:
    """`scope.axes.write_scope_axes` for this endpoint's payload; a request no
    scope can be is a 422."""
    request = AxesRequest(
        enabled_role_groups=payload.enabled_role_groups,
        enabled_seniority_bands=payload.enabled_seniority_bands,
        enabled_role_tracks=payload.enabled_role_tracks,
        enabled_location_groups=payload.enabled_location_groups,
        enabled_domain_groups=payload.enabled_domain_groups,
        excluded_domain_groups=payload.excluded_domain_groups,
        excluded_location_groups=payload.excluded_location_groups,
        include_unstated_level=payload.include_unstated_level,
        role_answers=(
            [answer.model_dump() for answer in payload.role_answers]
            if payload.role_answers is not None
            else None
        ),
        experience_stage=payload.experience_stage,
        target_stage=payload.target_stage,
    )
    try:
        return await write_scope_axes(session, request)
    except ScopeInputError as exc:
        raise api_error(422, ErrorCode.SCOPE_REFUSED, str(exc)) from exc


@router.put("/api/settings", response_model=SettingsSaveResponse)
async def put_settings_ep(payload: SettingsPayload, session: SessionDep) -> dict:
    saved = await _write_scope_axes(session, payload)
    # Every persona passenger this endpoint carries, collected and written ONCE:
    # one read and one write of the persona row, whichever passengers came.
    persona_updates: dict[str, object] = {}
    if payload.intent_statement is not None:
        persona_updates["intent_statement"] = await _save_intent_statement(
            session, payload.intent_statement
        )
    if saved.stages is not None:
        persona_updates["experience_stage"], persona_updates["target_stage"] = saved.stages
    if persona_updates:
        # The persona is the levels and the aim sentence, nothing else
        # (this is the one save path; the scope lives in its own keys). The
        # first save with both levels creates it; an intent-only save on an
        # install without one keeps the embedding record, which ranking reads.
        profile = await get_persona_profile(session)
        if profile is None and saved.stages is not None:
            await set_persona_profile(session, {
                "intent_statement": await _current_intent_statement(session), **persona_updates,
            })
        elif profile is not None and any(
            profile.get(field) != value for field, value in persona_updates.items()
        ):
            await set_persona_profile(session, {**profile, **persona_updates})
    axes, keywords = saved.gate()
    in_scope_changed = await apply_saved_scope_to_jobs(session, *axes, **keywords)
    # Postings a sync already read that the saved scope now keeps,
    # before the count below so it includes them.
    promotion = await promote_after_save(session)
    # What the Board holds now: the save confirmation says this,
    # not `in_scope_changed`, which counts closed rows and every company.
    on_board = await _board_count(session)
    await session.commit()
    await queue_follow_up(session, promotion)
    if (await read_follow(session))["following"]:
        # A new radar makes every directory check stale; start reading for it
        # now rather than at the next look.
        await job_requests.ring_directory(session, requested_by="settings")
        await session.commit()
    return {
        "enabled_role_groups": saved.roles,
        "enabled_seniority_bands": saved.bands,
        "enabled_role_tracks": [t.slug for t in TRACKS if t.slug in set(saved.tracks)],
        "enabled_location_groups": canonical_location_slugs(saved.locations),
        "enabled_domain_groups": [
            g.slug for g in DOMAIN_GROUPS if g.slug in set(saved.domains)
        ],
        "excluded_domain_groups": saved.excluded_domains,
        "role_answers": dump_answers(saved.answers),
        "excluded_location_groups": saved.excepted,
        "include_unstated_level": saved.include_unstated_level,
        "in_scope_changed": in_scope_changed,
        "on_board": on_board,
        **promotion_fields(promotion),
    }


@router.post("/api/scope/preview", response_model=ScopePreviewResponse)
async def preview_scope_ep(payload: SettingsPayload, session: SessionDep) -> dict:
    """What saving this draft would do to the Board, before it happens.
    Runs the save's own scope writes in a SAVEPOINT,
    reads the Board gate and the promotion candidates there, and rolls back:
    nothing is written, and no second normalisation exists to drift."""
    hidden = await off_board_company_slugs(session)
    on_board_now = await _board_count(session)
    savepoint = await session.begin_nested()
    try:
        saved = await _write_scope_axes(session, payload)
        axes, keywords = saved.gate()
        preview = await preview_save(session, axes, keywords, hidden=hidden)
    finally:
        await savepoint.rollback()
    return {"on_board_now": on_board_now, **preview}


# --------------------------------------------------------------------------- #
# Persona profile: where the user is today and where they are aiming, plus
# the aim sentence. Saved through PUT /api/settings with the scope (one
# save path). The persona does not copy the scope, so nothing can diverge
# from it and there is no "customized" state.
# --------------------------------------------------------------------------- #


@router.get("/api/profile", response_model=ProfileStateResponse, response_model_exclude_unset=True)
async def get_profile_ep(session: SessionDep) -> dict:
    profile = await get_persona_profile(session)
    scope_keys = (
        ENABLED_ROLES_KEY, ENABLED_BANDS_KEY, ENABLED_TRACKS_KEY, ENABLED_LOCATIONS_KEY,
        ENABLED_DOMAINS_KEY,
    )
    scope_configured = any(
        [await session.get(AppSetting, key) is not None for key in scope_keys]
    )
    # Display source for the intent line: the persona's copy, falling back to
    # the embedding record for a profile-less (raw fine-tune only) install.
    intent_statement = await _current_intent_statement(session)
    return {
        # A persona holding only the aim sentence names no levels: no profile yet.
        "profile": profile if has_levels(profile) else None,
        "scope_configured": scope_configured,
        "intent_statement": intent_statement,
    }


# --- Settings > Data retention --------------------------------- #


async def _retention_state(session: AsyncSession) -> dict:
    days = await get_retention_days(session)
    counts = await retention_counts(session, now=datetime.now(UTC), windows=RETENTION_CHOICES)
    last = await get_retention_last(session)
    return {
        "days": days,
        "default_days": RETENTION_DEFAULT_DAYS,
        "choices": [{"days": d, "due": counts.due_by_days[d]} for d in RETENTION_CHOICES],
        "stored": counts.stored,
        "no_longer_listed": counts.no_longer_listed,
        "stopped_following": counts.stopped_following,
        "due": 0 if days is None else counts.due_by_days[days],
        "last_removed": last,
    }


@router.get("/api/settings/retention", response_model=RetentionState)
async def get_retention_ep(session: SessionDep) -> dict:
    """How long stored postings no scan reads are kept, and what that removes."""
    return await _retention_state(session)


@router.put("/api/settings/retention", response_model=RetentionState)
async def put_retention_ep(payload: RetentionUpdate, session: SessionDep) -> dict:
    """Save the window. Nothing is removed here: the next run, or the
    scheduler's next idle tick, removes what the new window makes due."""
    try:
        await set_retention_days(session, payload.days)
    except ValueError as exc:
        raise api_error(422, ErrorCode.INVALID_INPUT, str(exc)) from exc
    await session.commit()
    return await _retention_state(session)


# --- Settings > Plugins > Stock prices ------------------------- #


@router.get("/api/settings/price-feed", response_model=PriceFeedState)
async def get_price_feed_ep(session: SessionDep) -> dict:
    """Whether a price-feed key is set and where from, and what the prices
    pass last did. Never the key itself."""
    return await price_store.feed_status(session, get_settings())


@router.put("/api/settings/price-feed", response_model=PriceFeedState)
async def put_price_feed_ep(payload: PriceFeedKey, session: SessionDep) -> dict:
    """Save the key, after its first request: the first due ticker's bars, which
    prove the key and store a price at once. A key the feed refuses is not saved
    (409). A check that could not finish (rate limited, offline, timed out)
    saves the key and says so. Work an earlier key queued or runs is stopped;
    the prices job is then asked for the rest."""
    settings = get_settings()
    await job_requests.stop_prices(session)
    outcome = await price_store.check_key(session, settings, payload.api_key)
    if outcome == price_store.UNAUTHORIZED:
        raise api_error(409, ErrorCode.PRICE_KEY_REFUSED, "the price feed refused this key; it was not saved")
    await price_store.save_api_key(session, payload.api_key)
    await job_requests.ring_prices(session, requested_by="key_saved")
    await session.commit()
    return {**await price_store.feed_status(session, settings), "key_check": outcome}


@router.post("/api/settings/price-feed/refresh", response_model=PriceFeedState)
async def refresh_price_feed_ep(session: SessionDep) -> dict:
    """"Update now": ask the prices job for a refresh within the budget."""
    await job_requests.ring_prices(session, requested_by="update_now")
    await session.commit()
    return await price_store.feed_status(session, get_settings())


@router.delete("/api/settings/price-feed", response_model=PriceFeedState)
async def delete_price_feed_ep(session: SessionDep) -> dict:
    """Forget the saved key, stopping what it queued or runs. Prices already
    stored stay; an environment key, if any, is used from the next run."""
    await job_requests.stop_prices(session)
    await price_store.save_api_key(session, None)
    await session.commit()
    return await price_store.feed_status(session, get_settings())


@router.get("/api/settings/locale", response_model=LocaleSettings)
async def get_locale_ep(session: SessionDep) -> dict:
    """The language the dashboard speaks and the region it formats for."""
    return await get_locale(session)


@router.put("/api/settings/locale", response_model=LocaleSettings)
async def put_locale_ep(payload: LocaleSettings, session: SessionDep) -> dict:
    """Save language and region. The schema refuses anything but language
    tags (422) before this runs, and the store holds the same rule."""
    saved = await set_locale(session, payload.language, payload.region)
    await session.commit()
    return saved
