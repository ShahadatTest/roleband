"""User-controllable settings persisted in the `app_settings` table.

One row per setting key: the scope axes (defaults from the taxonomy's
`default_enabled` flags), the role answers, the persona, the schedule plan, the
AI switches and the active prompt version per AI task, data retention, the pay
floor, and language and region. A getter falls back to the shipped default
when its row is absent or malformed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import (
    all_location_group_slugs,
    default_enabled_location_groups,
    get_settings,
)
from tracker.db.models import AppSetting
from tracker.levels import INCLUDE_UNSTATED_LEVEL_DEFAULT, all_band_slugs, default_enabled_bands
from tracker.pay_disclosure import MAX_COMP
from tracker.platform.language_tags import is_locale_tag
from tracker.platform.locks import advisory_xact_lock
from tracker.schema import band_slug
from tracker.taxonomy import slug_history
from tracker.taxonomy.domains import all_slugs as all_domain_slugs
from tracker.taxonomy.locations import canonical_location_slugs
from tracker.taxonomy.role_answers import (
    RoleAnswer,
    answers_from_axes,
    dump_answers,
    parse_answers,
    projection,
)
from tracker.taxonomy.roles import all_slugs, default_enabled_slugs
from tracker.taxonomy.tracks import all_track_slugs, default_enabled_tracks

ENABLED_ROLES_KEY = "enabled_role_groups"
ENABLED_BANDS_KEY = "enabled_seniority_bands"
ENABLED_TRACKS_KEY = "enabled_role_tracks"
ENABLED_LOCATIONS_KEY = "enabled_location_groups"
ENABLED_DOMAINS_KEY = "enabled_domain_groups"
# Subjects the user is NOT interested in: a veto, apart from the worlds axis.
EXCLUDED_DOMAINS_KEY = "excluded_domain_groups"
# Places excepted inside the included ones ("the US except New York").
EXCLUDED_LOCATIONS_KEY = "excluded_location_groups"
# Which roles of each kind: one answer per track (see taxonomy/role_answers).
ROLE_ANSWERS_KEY = "role_answers"
# Whether roles whose level isn't stated pass the level axis.
INCLUDE_UNSTATED_LEVEL_KEY = "include_unstated_level"
PERSONA_PROFILE_KEY = "persona_profile"
INTENT_EMBEDDING_KEY = "intent_embedding"
PROMPT_VERSIONS_KEY = "intelligence_prompt_versions"
EMBED_PASS_KEY = "embed_pass_measurements"
#: When the similarity table was last rebuilt in full, and last refreshed
#: (`semantic.similarity`).
SIMILARITY_FULL_KEY = "similarity_refresh"
APPLE_FM_KEY = "apple_fm"
AI_EGRESS_KEY = "ai_egress"
#: The schedule plan's choices: `SchedulePlanSettings`.
SCHEDULE_PLAN_KEY = "schedule_plan"

# NOTE: per-company enable/visibility state lives on the `tracked_company` rows
# (built-ins are seeded via `company_store.ensure_builtins`), not here, so
# built-in and user-added companies share one code path.


#: The opt-in axes and their `slug_history` names. Each is stored as
#: what the user switched ON, so a NEW category arrives off, a RENAMED one is
#: read through its heirs, and a save records the list the user saw.
_AXIS_OF_KEY = {
    ENABLED_ROLES_KEY: "roles",
    ENABLED_BANDS_KEY: "bands",
    ENABLED_TRACKS_KEY: "tracks",
    ENABLED_LOCATIONS_KEY: "locations",
}


async def forget_cached_settings(session: AsyncSession) -> None:
    """Make the next read of each setting ask the database.

    Every getter here reads through `session.get`, which answers from the
    session's identity map. `set_setting_dict` keeps that map honest for this
    session's own writes; a long-lived session (the run's writer, which keeps
    objects across commits) would still read the scope it loaded at the start
    of the run, whatever another session saved since. Flushed first:
    expiring drops a change not yet written, and a save reads its own scope
    back right after setting it."""
    await session.flush()
    for obj in list(session.identity_map.values()):
        if isinstance(obj, AppSetting):
            session.expire(obj)


async def _get_enabled_slugs(
    session: AsyncSession,
    *,
    key: str,
    valid_order: list[str],
    defaults: list[str],
) -> set[str]:
    """Read one taxonomy axis, falling back only when its shape is invalid.

    JSON values are operator-controlled persistence, so validate every element
    before set membership. A valid empty list intentionally means "disable this
    axis"; a missing/malformed list restores the shipped defaults. A stored slug
    the taxonomy has since renamed or split is read as its heirs, so the user
    keeps what they had on.
    """
    row = await session.get(AppSetting, key)
    return _enabled_from(row.value if row is not None else None, key, valid_order, defaults)


def _enabled_from(value: object, key: str, valid_order: list[str], defaults: list[str]) -> set[str]:
    if not isinstance(value, dict):
        return set(defaults)
    slugs = value.get("slugs")
    if not isinstance(slugs, list):
        return set(defaults)
    valid = set(valid_order)
    return {slug for slug in slug_history.carry_forward(_AXIS_OF_KEY[key], slugs) if slug in valid}


def _new_from(value: object, key: str, valid_order: list[str]) -> set[str]:
    if not isinstance(value, dict) or not isinstance(value.get("slugs"), list):
        return set()
    axis = _AXIS_OF_KEY[key]
    stored = value.get("seen")
    seen = stored if isinstance(stored, list) else slug_history.baseline(axis)
    return set(valid_order) - slug_history.carry_forward(axis, seen)


async def _set_enabled_slugs(
    session: AsyncSession,
    *,
    key: str,
    requested_slugs: list[str],
    valid_order: list[str],
    seen: list[str] | None = None,
) -> list[str]:
    """Canonicalize and upsert one taxonomy axis.

    `seen` is every category the user was choosing among: what the scope
    catalog stops calling new. It defaults to `valid_order`; the
    location axis passes the taxonomy alone, since a city is chosen by
    search and is never a category that can be "new".
    """
    requested = {slug for slug in requested_slugs if isinstance(slug, str)}
    enabled = [slug for slug in valid_order if slug in requested]
    value = {"slugs": enabled, "seen": list(valid_order if seen is None else seen)}
    await set_setting_dict(session, key, value)
    return enabled


async def _get_visible_slugs(
    session: AsyncSession, *, key: str, valid_order: list[str]
) -> set[str]:
    """Read an axis stored as what the user HID, not what they enabled.

    The difference is what happens to a slug nobody has decided about yet.
    An enabled-set says "these are on", so a world added later is
    absent from every stored answer and arrives OFF for every existing
    install — invisible, and switched off by a choice nobody made. A hidden-set
    says "these are off", so a new world arrives ON, which is the only default
    that can be honestly attributed to the user: they have said nothing about
    it, and the axis defaults to all.

    The `{"slugs": [...]}` shape is read as an enabled set: a row written
    before the migration that converted them, or a worlds set that names
    interests, where a later subject SHOULD arrive off.
    """
    row = await session.get(AppSetting, key)
    valid = set(valid_order)
    if row is None or not isinstance(row.value, dict):
        return valid
    hidden = row.value.get("hidden")
    if isinstance(hidden, list):
        return valid - {slug for slug in hidden if isinstance(slug, str)}
    slugs = row.value.get("slugs")
    if isinstance(slugs, list):
        return {slug for slug in slugs if isinstance(slug, str) and slug in valid}
    return valid


async def _set_visible_slugs(
    session: AsyncSession, *, key: str, requested_slugs: list[str], valid_order: list[str]
) -> list[str]:
    """Store the complement: everything valid the request left out."""
    requested = {slug for slug in requested_slugs if isinstance(slug, str)}
    visible = [slug for slug in valid_order if slug in requested]
    value = {"hidden": [slug for slug in valid_order if slug not in requested]}
    await set_setting_dict(session, key, value)
    return visible


async def get_enabled_domains(session: AsyncSession) -> set[str]:
    """The domain (worlds) axis. Defaults to ALL domains, and an empty stored
    set reads as all: with the gate's fail-open-unknown rule, an
    empty include-set would block every classified row while passing every
    unclassified one — an inverse filter no user can ask for. `set` refuses to
    persist empty for the same reason; this read-side guard makes the axis
    self-healing if bad state arrives some other way."""
    enabled = await _get_visible_slugs(
        session, key=ENABLED_DOMAINS_KEY, valid_order=all_domain_slugs()
    )
    return enabled or set(all_domain_slugs())


def names_interests(enabled: Iterable[str], excluded: Iterable[str]) -> bool:
    """Whether the worlds set says "interested in these".

    It does when some subject is neither on nor vetoed. With only "not
    interested in" lines, the worlds set is everything the veto leaves, and a
    subject added later belongs in it; with interest lines, it is those
    interests, and a later subject nobody named does not."""
    covered = set(enabled) | set(excluded)
    return any(slug not in covered for slug in all_domain_slugs())


async def set_enabled_domains(
    session: AsyncSession, slugs: list[str], *, excluded: Iterable[str] = ()
) -> list[str]:
    """Store the worlds set in the form that carries its intent.
    Interests are stored as the enabled set, so a subject added to
    the taxonomy later arrives OFF, outside "interested only in AI". Anything
    else is stored as what is hidden, so a later subject arrives ON:
    nobody said no to it. `excluded` is the veto list saved beside it."""
    requested = [slug for slug in slugs if isinstance(slug, str)]
    valid_order = all_domain_slugs()
    valid = set(valid_order)
    if not any(slug in valid for slug in requested):
        # Refuse empty: persisting an empty worlds axis is never what
        # the user meant — it reads back as "all", so store that truthfully.
        requested = valid_order
    if names_interests(requested, excluded):
        return await _set_enabled_slugs(
            session,
            key=ENABLED_DOMAINS_KEY,
            requested_slugs=requested,
            valid_order=valid_order,
        )
    return await _set_visible_slugs(
        session,
        key=ENABLED_DOMAINS_KEY,
        requested_slugs=requested,
        valid_order=valid_order,
    )


async def get_excluded_domains(session: AsyncSession) -> set[str]:
    """Subjects the user said they are NOT interested in: a veto.

    Separate from the worlds axis because the two mean different things. The
    worlds axis keeps a role when ANY of its subjects is on, so "not
    interested in advertising" stored there would keep every advertising role
    that is also about something else. An
    excluded subject drops a role whatever else it is about. Stored as the
    excluded list itself, so a subject added to the taxonomy later arrives
    not excluded: nobody said no to it. Unknown slugs are dropped on read.
    """
    row = await session.get(AppSetting, EXCLUDED_DOMAINS_KEY)
    return _excluded_from(row.value if row is not None else None)


def _excluded_from(value: object) -> set[str]:
    slugs = value.get("slugs") if isinstance(value, dict) else None
    if not isinstance(slugs, list):
        return set()
    valid = set(all_domain_slugs())
    return {slug for slug in slugs if isinstance(slug, str) and slug in valid}


async def set_excluded_domains(session: AsyncSession, slugs: list[str]) -> list[str]:
    requested = {slug for slug in slugs if isinstance(slug, str)}
    excluded = [slug for slug in all_domain_slugs() if slug in requested]
    await set_setting_dict(session, EXCLUDED_DOMAINS_KEY, {"slugs": excluded})
    return excluded


def _excepted_places(value: object) -> set[str]:
    slugs = value.get("slugs") if isinstance(value, dict) else None
    if not isinstance(slugs, list):
        return set()
    return set(canonical_location_slugs([slug for slug in slugs if isinstance(slug, str)]))


async def get_excluded_locations(session: AsyncSession) -> set[str]:
    """Places excepted inside the included ones: "the US except New
    York" is `united_states` on the location axis and `new_york` here. Read
    per place by `taxonomy.place_scope`, never as a veto on the whole posting:
    a New York or Austin role stays. Unknown slugs are dropped on read."""
    row = await session.get(AppSetting, EXCLUDED_LOCATIONS_KEY)
    return _excepted_places(row.value if row is not None else None)


async def set_excluded_locations(session: AsyncSession, slugs: list[str]) -> list[str]:
    excepted = canonical_location_slugs([slug for slug in slugs if isinstance(slug, str)])
    await set_setting_dict(session, EXCLUDED_LOCATIONS_KEY, {"slugs": excepted})
    return excepted


def _answers_from(value: object) -> tuple[RoleAnswer, ...] | None:
    """The saved answers, or None when none are saved: the caller then reads
    them off the two flat axes, and reads those only in that case."""
    if isinstance(value, dict) and isinstance(value.get("answers"), list):
        return parse_answers(value["answers"])
    return None


async def get_role_answers(session: AsyncSession) -> tuple[RoleAnswer, ...]:
    """The saved answers; an install that has none reads them off its two
    flat axes (tracks x families), so every install has answers to gate by."""
    row = await session.get(AppSetting, ROLE_ANSWERS_KEY)
    saved = _answers_from(row.value if row is not None else None)
    if saved is not None:
        return saved
    return answers_from_axes(await get_enabled_tracks(session), await get_enabled_roles(session))


async def set_role_answers(session: AsyncSession, answers: tuple[RoleAnswer, ...]) -> tuple[RoleAnswer, ...]:
    """Save the answers, and the two flat axes they project to, so a reader
    that still reads tracks and families sees the same choice."""
    await set_setting_dict(session, ROLE_ANSWERS_KEY, {"answers": dump_answers(answers)})
    tracks, families = projection(answers)
    await set_enabled_tracks(session, tracks)
    await set_enabled_roles(session, families)
    return answers


async def get_enabled_roles(session: AsyncSession) -> set[str]:
    return await _get_enabled_slugs(
        session,
        key=ENABLED_ROLES_KEY,
        valid_order=all_slugs(),
        defaults=default_enabled_slugs(),
    )


async def set_enabled_roles(session: AsyncSession, slugs: list[str]) -> list[str]:
    return await _set_enabled_slugs(
        session,
        key=ENABLED_ROLES_KEY,
        requested_slugs=slugs,
        valid_order=all_slugs(),
    )


async def get_enabled_bands(session: AsyncSession) -> set[str]:
    return await _get_enabled_slugs(
        session,
        key=ENABLED_BANDS_KEY,
        valid_order=all_band_slugs(),
        defaults=default_enabled_bands(),
    )


async def set_enabled_bands(session: AsyncSession, slugs: list[str]) -> list[str]:
    return await _set_enabled_slugs(
        session,
        key=ENABLED_BANDS_KEY,
        requested_slugs=slugs,
        valid_order=all_band_slugs(),
    )


async def get_enabled_tracks(session: AsyncSession) -> set[str]:
    return await _get_enabled_slugs(
        session,
        key=ENABLED_TRACKS_KEY,
        valid_order=all_track_slugs(),
        defaults=default_enabled_tracks(),
    )


async def set_enabled_tracks(session: AsyncSession, slugs: list[str]) -> list[str]:
    return await _set_enabled_slugs(
        session,
        key=ENABLED_TRACKS_KEY,
        requested_slugs=slugs,
        valid_order=all_track_slugs(),
    )


def _location_order(value: object) -> list[str]:
    """The location axis's valid slugs for a stored value: the taxonomy, then
    the GeoNames cities (`city_<geonameid>`) it holds that still name
    a place. A city is not in the fixed list, so it is valid by lookup."""
    stored = value.get("slugs") if isinstance(value, dict) else None
    return canonical_location_slugs([*all_location_group_slugs(), *(stored if isinstance(stored, list) else [])])


async def get_enabled_locations(session: AsyncSession) -> set[str]:
    row = await session.get(AppSetting, ENABLED_LOCATIONS_KEY)
    value = row.value if row is not None else None
    return _enabled_from(value, ENABLED_LOCATIONS_KEY, _location_order(value), default_enabled_location_groups())


async def set_enabled_locations(session: AsyncSession, slugs: list[str]) -> list[str]:
    return await _set_enabled_slugs(
        session,
        key=ENABLED_LOCATIONS_KEY,
        requested_slugs=slugs,
        valid_order=canonical_location_slugs([*all_location_group_slugs(), *slugs]),
        seen=all_location_group_slugs(),
    )


async def new_slugs(session: AsyncSession, key: str, valid_order: list[str]) -> set[str]:
    """Categories on this axis the user has not been shown.

    Nothing is new to a user who never saved the axis: they are on the shipped
    defaults, not a choice a later category could have been left out of. A
    setting saved before `seen` was recorded saw the frozen baseline. A renamed
    category the user saw under its old name is not new under its heirs.
    """
    row = await session.get(AppSetting, key)
    return _new_from(row.value if row is not None else None, key, valid_order)


@dataclass(frozen=True)
class OptInAxis:
    """One opt-in axis as the scope catalog needs it: what is on, what is new."""

    enabled: set[str]
    new: set[str]


@dataclass(frozen=True)
class ScopeSettingsRead:
    """What the scope catalog reads in one query: the four opt-in axes, the
    role answers, the excluded subjects and the excepted places."""

    axes: dict[str, OptInAxis]
    answers: tuple[RoleAnswer, ...]
    excluded: set[str]
    excepted_places: set[str]
    include_unstated_level: bool = INCLUDE_UNSTATED_LEVEL_DEFAULT


async def read_opt_in_axes(session: AsyncSession) -> ScopeSettingsRead:
    """Roles, bands, tracks and locations in ONE query, keyed by setting key.

    The scope catalog needs both halves of every axis; four `session.get`
    calls each for "on" and "new" would be eight round trips for four rows,
    and an absent row is never cached, so it would be re-queried each time.
    """
    specs = {
        ENABLED_ROLES_KEY: (all_slugs(), default_enabled_slugs()),
        ENABLED_BANDS_KEY: (all_band_slugs(), default_enabled_bands()),
        ENABLED_TRACKS_KEY: (all_track_slugs(), default_enabled_tracks()),
        ENABLED_LOCATIONS_KEY: (all_location_group_slugs(), default_enabled_location_groups()),
    }
    rows = await session.execute(
        select(AppSetting.key, AppSetting.value).where(
            AppSetting.key.in_([
                *specs, ROLE_ANSWERS_KEY, EXCLUDED_DOMAINS_KEY, EXCLUDED_LOCATIONS_KEY,
                INCLUDE_UNSTATED_LEVEL_KEY,
            ])
        )
    )
    values = {key: value for key, value in rows.all()}
    axes = {
        key: OptInAxis(
            # Cities are valid "on" (by lookup), never "new".
            enabled=_enabled_from(
                values.get(key), key,
                _location_order(values.get(key)) if key == ENABLED_LOCATIONS_KEY else valid, defaults,
            ),
            new=_new_from(values.get(key), key, valid),
        )
        for key, (valid, defaults) in specs.items()
    }
    # The answers and the excluded subjects ride the same read: no extra
    # round trip for the scope catalog.
    answers = _answers_from(values.get(ROLE_ANSWERS_KEY))
    if answers is None:
        answers = answers_from_axes(axes[ENABLED_TRACKS_KEY].enabled, axes[ENABLED_ROLES_KEY].enabled)
    return ScopeSettingsRead(
        axes=axes, answers=answers, excluded=_excluded_from(values.get(EXCLUDED_DOMAINS_KEY)),
        excepted_places=_excepted_places(values.get(EXCLUDED_LOCATIONS_KEY)),
        include_unstated_level=_include_unstated_from(values.get(INCLUDE_UNSTATED_LEVEL_KEY)),
    )


def _include_unstated_from(value: object) -> bool:
    """The stored switch, or the default when it was never set."""
    if isinstance(value, dict) and isinstance(value.get("enabled"), bool):
        return value["enabled"]
    return INCLUDE_UNSTATED_LEVEL_DEFAULT


async def get_include_unstated_level(session: AsyncSession) -> bool:
    row = await session.get(AppSetting, INCLUDE_UNSTATED_LEVEL_KEY)
    return _include_unstated_from(row.value if row is not None else None)


async def set_include_unstated_level(session: AsyncSession, enabled: bool) -> bool:
    enabled = bool(enabled)
    await set_setting_dict(session, INCLUDE_UNSTATED_LEVEL_KEY, {"enabled": enabled})
    return enabled


#: How often the schedule plan repeats its quick scan while the computer is
#: on. The choices the Schedule screen offers, and the default.
SCHEDULE_REPEAT_CHOICES = (2, 3, 6, 12)
SCHEDULE_REPEAT_DEFAULT = 6
#: Every day, Monday = 0: a new setup scans every day.
SCHEDULE_DAYS_DEFAULT = (0, 1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class SchedulePlanSettings:
    """The user's choices for the schedule plan, all optional.

    `ready_by_minute`: the daily full scan should be finished by this local
    minute (None = by the usual start the plan learned, if any). `days`: the
    weekdays planned scans run on. `paused_until`: no planned scan before this.
    `mains_only`: planned scans wait for mains power. `timezone`: the zone the
    times and days were chosen in (None = the machine's own).
    `repeat_anchor_minute`: the quick scans run at fixed clock times, this
    minute plus whole repeats (set by dragging one on the dial); None = every
    `repeat_hours` from the last scan."""

    repeat_hours: int = SCHEDULE_REPEAT_DEFAULT
    repeat_anchor_minute: int | None = None
    ready_by_minute: int | None = None
    days: tuple[int, ...] = SCHEDULE_DAYS_DEFAULT
    paused_until: datetime | None = None
    mains_only: bool = False
    timezone: str | None = None


def _schedule_plan_from(value: object) -> SchedulePlanSettings:
    """The stored choices, each falling back to its default when missing or invalid."""
    if not isinstance(value, dict):
        return SchedulePlanSettings()
    repeat = value.get("repeat_hours")
    ready = value.get("ready_by_minute")
    anchor = value.get("repeat_anchor_minute")
    days = value.get("days")
    paused: datetime | None = None
    if isinstance(value.get("paused_until"), str):
        try:
            paused = datetime.fromisoformat(value["paused_until"])
        except ValueError:
            paused = None
    valid_days = (
        tuple(sorted({day for day in days if isinstance(day, int) and 0 <= day <= 6}))
        if isinstance(days, list) else ()
    )
    return SchedulePlanSettings(
        repeat_hours=int(repeat) if repeat in SCHEDULE_REPEAT_CHOICES else SCHEDULE_REPEAT_DEFAULT,
        repeat_anchor_minute=anchor if isinstance(anchor, int) and 0 <= anchor < 24 * 60 else None,
        ready_by_minute=ready if isinstance(ready, int) and 0 <= ready < 24 * 60 else None,
        days=valid_days or SCHEDULE_DAYS_DEFAULT,
        paused_until=paused if paused is not None and paused.tzinfo is not None else None,
        mains_only=value.get("mains_only") is True,
        timezone=value["timezone"] if isinstance(value.get("timezone"), str) else None,
    )


async def get_schedule_plan_settings(session: AsyncSession) -> SchedulePlanSettings:
    row = await session.get(AppSetting, SCHEDULE_PLAN_KEY)
    return _schedule_plan_from(row.value if row is not None else None)


async def set_schedule_plan_settings(
    session: AsyncSession, plan: SchedulePlanSettings
) -> SchedulePlanSettings:
    if plan.repeat_hours not in SCHEDULE_REPEAT_CHOICES:
        raise ValueError(f"repeat must be one of {SCHEDULE_REPEAT_CHOICES}")
    if not plan.days or any(not 0 <= day <= 6 for day in plan.days):
        raise ValueError("days must name at least one weekday, 0..6")
    value = {
        "repeat_hours": plan.repeat_hours,
        "repeat_anchor_minute": plan.repeat_anchor_minute,
        "ready_by_minute": plan.ready_by_minute,
        "days": sorted(set(plan.days)),
        "paused_until": plan.paused_until.isoformat() if plan.paused_until else None,
        "mains_only": plan.mains_only,
        "timezone": plan.timezone,
    }
    await set_setting_dict(session, SCHEDULE_PLAN_KEY, value)
    return _schedule_plan_from(value)


#: Held from the read to the end of the transaction by every save that changes
#: only some of the schedule plan's choices.
SCHEDULE_PLAN_LOCK_KEY = 91250


async def update_schedule_plan_settings(session: AsyncSession, **changes: Any) -> SchedulePlanSettings:
    """Change the named choices and keep every other one as stored.

    The plan is one JSON row, so two saves of different choices that both read
    it before either commits would each write the other's choice back as it
    was. The lock orders them: the second reads the row the first committed.
    An advisory lock rather than a row lock, because the row may not exist yet.
    The read goes past the identity map for the same reason it waits: it must
    be the committed row. Raises ValueError as `set_schedule_plan_settings` does."""
    await advisory_xact_lock(session, SCHEDULE_PLAN_LOCK_KEY)
    row = await session.get(AppSetting, SCHEDULE_PLAN_KEY, populate_existing=True)
    current = _schedule_plan_from(row.value if row is not None else None)
    return await set_schedule_plan_settings(session, replace(current, **changes))


#: What the persona holds: the two levels and the aim sentence. The scope
#: lives only in its own keys, never copied here, so the two cannot drift
#: apart.
PERSONA_FIELDS = ("experience_stage", "target_stage", "intent_statement")


def _persona(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    persona = {field: value[field] for field in PERSONA_FIELDS if field in value}
    # A stored "junior" level reads as Entry.
    for field in ("experience_stage", "target_stage"):
        if isinstance(persona.get(field), str):
            persona[field] = band_slug(persona[field])
    return persona


def has_levels(persona: dict | None) -> bool:
    """Whether a persona names both levels (what `GET /api/profile` calls a
    profile); one holding only the aim sentence is still read for ranking."""
    return persona is not None and all(
        isinstance(persona.get(field), str) for field in ("experience_stage", "target_stage")
    )


async def get_persona_profile(session: AsyncSession) -> dict | None:
    """The user's levels and aim sentence as stored, or None if never saved.
    Keys an older writer left (the scope copy) are not read."""
    row = await session.get(AppSetting, PERSONA_PROFILE_KEY)
    return _persona(row.value if row is not None else None)


async def set_persona_profile(session: AsyncSession, profile: dict) -> dict:
    profile = {field: profile[field] for field in PERSONA_FIELDS if field in profile}
    return await set_setting_dict(session, PERSONA_PROFILE_KEY, profile)


def _active_tier() -> str | None:
    """The artifact tier the encoder would load right now, or None if unknowable.

    Imported lazily and failure-tolerant on purpose: a settings read must not
    depend on the model layer being importable or on the decision file existing
    — an unreadable tier degrades to "cannot distinguish", which the caller
    treats as a match rather than throwing away a usable vector.
    """
    try:
        from tracker.semantic import provision

        return provision.resolve_tier()
    except Exception:  # noqa: BLE001 — observational only; never blocks a settings read
        return None


async def get_intent_embedding(session: AsyncSession) -> dict | None:
    """The stored intent-statement embedding, or None when absent/unusable.

    Value shape: {"statement": str, "model": str, "tier": str, "vector": [...]}.
    The vector is only served when it was produced by the CURRENT embedding
    model AND tier — `jobs.embedding` re-embeds on either change, and a
    statement vector from the old one would live in a different space. A stale
    record reads as absent (the statement itself still round-trips via the
    persona profile); the tier-switch re-embed recomputes it, and any profile
    save re-embeds it under the current pair.

    A record with no `tier` is older and was produced at whatever the
    machine auto-detected — still the active tier unless the user has since
    switched, in which case the re-embed rewrote it. So a missing tier matches
    rather than reading as stale: gating strictly would silently drop intent
    ranking for every existing user at upgrade.
    """
    row = await session.get(AppSetting, INTENT_EMBEDDING_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    statement = row.value.get("statement")
    model = row.value.get("model")
    tier = row.value.get("tier")
    vector = row.value.get("vector")
    if not (isinstance(statement, str) and statement.strip()):
        return None
    if model != get_settings().embedding_model:
        return None
    if tier is not None and tier != _active_tier():
        return None
    if not (
        isinstance(vector, list)
        and vector
        and all(isinstance(x, (int, float)) for x in vector)
    ):
        return None
    return {"statement": statement, "model": model, "vector": [float(x) for x in vector]}


async def set_intent_embedding(
    session: AsyncSession, statement: str, vector: list[float]
) -> None:
    """Persist the statement's embedding (computed once at profile save).

    An empty statement clears the record — the user removed their intent line,
    and a vector for removed text must not keep ranking.
    """
    statement = statement.strip()
    value: dict = (
        {
            "statement": statement,
            "model": get_settings().embedding_model,
            "tier": _active_tier(),
            "vector": vector,
        }
        if statement and vector
        else {}
    )
    await set_setting_dict(session, INTENT_EMBEDDING_KEY, value)


async def get_apple_fm_enabled(session: AsyncSession) -> bool:
    """Whether the user has enabled the on-device AI integration.

    The DB row is the source of truth once the user has toggled it; the
    `apple_fm_enabled` env setting only supplies the initial default. Enabling it
    does not guarantee the model runs — the device/SDK must also be available.
    """
    row = await session.get(AppSetting, APPLE_FM_KEY)
    if row is None or not isinstance(row.value, dict):
        return get_settings().apple_fm_enabled
    value = row.value.get("enabled")
    return bool(value) if isinstance(value, bool) else get_settings().apple_fm_enabled


async def set_apple_fm_enabled(session: AsyncSession, enabled: bool) -> bool:
    enabled = bool(enabled)
    await set_setting_dict(session, APPLE_FM_KEY, {"enabled": enabled})
    return enabled


async def get_ai_egress_enabled(session: AsyncSession) -> bool:
    """Whether the user has allowed job text to leave this Mac.

    Separate from `apple_fm_enabled` and from any cloud profile's own `enabled`
    flag on purpose: saving a BYOK profile, and permitting the product to send
    scraped postings to it during normal work, are different consents. A saved
    profile stays usable for the explicit Test button either way; only this
    switch admits a cloud tier into the routing ladder.
    """
    row = await session.get(AppSetting, AI_EGRESS_KEY)
    if row is None or not isinstance(row.value, dict):
        return get_settings().ai_egress_enabled
    value = row.value.get("enabled")
    return bool(value) if isinstance(value, bool) else get_settings().ai_egress_enabled


async def set_ai_egress_enabled(session: AsyncSession, enabled: bool) -> bool:
    enabled = bool(enabled)
    await set_setting_dict(session, AI_EGRESS_KEY, {"enabled": enabled})
    return enabled


async def get_active_prompt_version(session: AsyncSession, task: str, default: str) -> str:
    """Active prompt version for an AI `task`. Falls back to the code default.

    Bumping this (or the code default) makes the extraction gate treat every job
    as stale, forcing a clean re-run under the new prompt.
    """
    row = await session.get(AppSetting, PROMPT_VERSIONS_KEY)
    if row is None or not isinstance(row.value, dict):
        return default
    version = row.value.get(task)
    return version if isinstance(version, str) and version else default


async def get_setting_dict(session: AsyncSession, key: str) -> dict | None:
    """A raw dict-valued app_setting, or None when absent/malformed."""
    row = await session.get(AppSetting, key)
    if row is None or not isinstance(row.value, dict):
        return None
    return dict(row.value)


async def set_setting_dict(session: AsyncSession, key: str, value: dict) -> dict:
    """Upsert one setting; every setter in this module writes through here.

    The row comes back through RETURNING with `populate_existing`, so an
    `AppSetting` this session already holds for the key takes the new value.
    A bare upsert would leave that instance, and every `session.get` after it
    in this session, on the old one."""
    stmt = insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    stmt = stmt.returning(AppSetting).execution_options(populate_existing=True)
    (await session.execute(stmt)).scalar_one()
    return value


async def delete_setting(session: AsyncSession, key: str) -> None:
    row = await session.get(AppSetting, key)
    if row is not None:
        await session.delete(row)


async def get_embed_measurements(session: AsyncSession) -> dict:
    """Per-tier record of how fast this computer actually embeds.

    Shape: {tier: {"rows": int, "seconds": float, "peak_rss_bytes": int|null}}.
    Written by a completed embed pass, read to estimate how long a switch will
    take. Never hardcode a duration: one measured on one corpus and one machine
    is wrong on every other, and the whole point of the figure is that the user
    can trust it.
    """
    row = await session.get(AppSetting, EMBED_PASS_KEY)
    return row.value if row and isinstance(row.value, dict) else {}


def _when(raw: object) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


async def get_similarity_marks(session: AsyncSession) -> tuple[datetime | None, datetime | None]:
    """When the neighbour table was last rebuilt over the whole corpus, and
    when it was last refreshed at all."""
    row = await session.get(AppSetting, SIMILARITY_FULL_KEY)
    value = row.value if row and isinstance(row.value, dict) else {}
    return _when(value.get("full_at")), _when(value.get("refreshed_at"))


async def record_similarity_refresh(session: AsyncSession, at: datetime, *, full: bool) -> None:
    full_at, _ = await get_similarity_marks(session)
    value = {"full_at": (at if full else full_at or at).isoformat(), "refreshed_at": at.isoformat()}
    await set_setting_dict(session, SIMILARITY_FULL_KEY, value)


async def record_embed_measurement(
    session: AsyncSession,
    *,
    tier: str,
    rows: int,
    seconds: float,
    peak_rss_bytes: int | None = None,
) -> None:
    """Record one completed pass. Only passes big enough to mean something.

    A 3-row incremental pass is dominated by model load and would produce a
    rate an order of magnitude off; estimating a full-corpus switch from it would
    be worse than showing no number at all.
    """
    if rows < _MIN_MEASURED_ROWS or seconds <= 0:
        return
    current = await get_embed_measurements(session)
    current[tier] = {
        "rows": int(rows),
        "seconds": round(float(seconds), 2),
        "peak_rss_bytes": int(peak_rss_bytes) if peak_rss_bytes else None,
    }
    await set_setting_dict(session, EMBED_PASS_KEY, current)


#: Below this a pass is mostly model-load overhead, not throughput.
_MIN_MEASURED_ROWS = 50


# --- data retention --------------------------------------------- #

#: How long a stored posting no scan reads is kept: `{"days": int}` or
#: `{"days": null}` (Never). Settings > Data retention.
RETENTION_KEY = "data_retention"
#: The last run that removed anything: `{"at": iso, "removed": int, "more": bool}`.
#: Written only when a run removed rows, so it names the last removal, not the
#: last check (the pass's own freshness is `derivation_state`).
RETENTION_LAST_KEY = "data_retention_last"
#: The only values the user can pick. A fixed list: no typed number, so no
#: 0-day accident and nothing to validate in the UI.
RETENTION_CHOICES: tuple[int, ...] = (7, 14, 30, 60, 90, 180, 365)
RETENTION_DEFAULT_DAYS = 60


def _retention_choice(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in RETENTION_CHOICES


async def get_retention_days(session: AsyncSession) -> int | None:
    """The saved window in days, None for Never. Unset or malformed reads as
    the default: a stored value outside the choices never widens what a run
    removes."""
    stored = await get_setting_dict(session, RETENTION_KEY)
    if stored is None or "days" not in stored:
        return RETENTION_DEFAULT_DAYS
    days = stored["days"]
    if days is None:
        return None
    return days if _retention_choice(days) else RETENTION_DEFAULT_DAYS


async def set_retention_days(session: AsyncSession, days: int | None) -> int | None:
    """Save the window; raises ValueError for a value outside the choices."""
    if days is not None and not _retention_choice(days):
        raise ValueError(f"retention days must be one of {RETENTION_CHOICES} or null, got {days!r}")
    await set_setting_dict(session, RETENTION_KEY, {"days": days})
    return days


async def get_retention_last(session: AsyncSession) -> dict | None:
    return await get_setting_dict(session, RETENTION_LAST_KEY)


async def record_retention_removal(
    session: AsyncSession, *, at: str, removed: int, more: bool,
) -> None:
    if removed > 0:
        await set_setting_dict(
            session, RETENTION_LAST_KEY, {"at": at, "removed": int(removed), "more": bool(more)},
        )


# --- pay floor -------------------------------------------------- #

#: The lowest yearly base pay the user would consider: `{"amount": int,
#: "currency": "USD"}`, or unset. An OPTIONAL answer offered on the Profile
#: Summary, never a Walk question: disclosed pay exists only in some postings
#: and some countries. Its own key, not the persona, which holds the levels
#: and the aim only. It never narrows scope: it is a fit input, read by Job
#: detail's pay panel.
PAY_FLOOR_KEY = "pay_floor"
PAY_FLOOR_MAX = MAX_COMP  # the band parser's own ceiling, imported so the two cannot drift


def _pay_floor(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    amount, currency = value.get("amount"), value.get("currency")
    if not isinstance(amount, int) or isinstance(amount, bool) or not 0 < amount <= PAY_FLOOR_MAX:
        return None
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        return None
    return {"amount": amount, "currency": currency.upper()}


async def get_pay_floor(session: AsyncSession) -> dict | None:
    """The saved floor, or None when unset or unreadable (an unreadable value
    is no floor: it must never start judging postings on its own)."""
    return _pay_floor(await get_setting_dict(session, PAY_FLOOR_KEY))


async def set_pay_floor(session: AsyncSession, amount: int, currency: str) -> dict:
    """Save the floor; raises ValueError for an amount or currency it cannot hold."""
    floor = _pay_floor({"amount": amount, "currency": currency})
    if floor is None:
        raise ValueError(f"pay floor must be 1..{PAY_FLOOR_MAX} in a 3-letter currency")
    await set_setting_dict(session, PAY_FLOOR_KEY, floor)
    return floor


async def clear_pay_floor(session: AsyncSession) -> None:
    await delete_setting(session, PAY_FLOOR_KEY)



# --- language and region (docs/copy.md) ------ #

#: `{"language": "en", "region": null}`. Language picks the dashboard's copy
#: catalog; region picks number and date formats, null following the reader's
#: operating system. Stored here, not only in the browser, because the backend
#: writes text too (banners, AI answers) and needs to know the language.
LOCALE_KEY = "locale"
LOCALE_DEFAULT_LANGUAGE = "en"


async def get_locale(session: AsyncSession) -> dict:
    """The saved language and region. Unset or malformed reads as English and
    the system region: a bad stored value never reaches the dashboard."""
    stored = await get_setting_dict(session, LOCALE_KEY) or {}
    language = stored.get("language")
    region = stored.get("region")
    return {
        "language": language if is_locale_tag(language) else LOCALE_DEFAULT_LANGUAGE,
        "region": region if is_locale_tag(region) else None,
    }


async def set_locale(session: AsyncSession, language: str, region: str | None) -> dict:
    """Save both; raises ValueError for a value that is not a language tag."""
    if not is_locale_tag(language) or (region is not None and not is_locale_tag(region)):
        raise ValueError(f"not a language tag: language={language!r} region={region!r}")
    await set_setting_dict(session, LOCALE_KEY, {"language": language, "region": region})
    return {"language": language, "region": region}
