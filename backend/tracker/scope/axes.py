"""The scope axes a settings save writes: one normalisation for the save and
its preview.

A router is transport; the normalisation belongs to scope. `write_scope_axes` validates, normalises
and writes every axis and returns `SavedAxes`, what the re-projection reads;
it writes and never commits or locks, so the caller keeps the transaction and
the lock order. Input is `AxesRequest`, plain data, so the module
imports no web framework; a bad request is `ScopeInputError`, which the
router answers as 422.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.levels import LEVELS
from tracker.schema import band_slug
from tracker.settings_store import (
    get_enabled_domains,
    get_enabled_locations,
    get_enabled_tracks,
    get_excluded_domains,
    get_excluded_locations,
    get_include_unstated_level,
    set_enabled_bands,
    set_enabled_domains,
    set_enabled_locations,
    set_enabled_roles,
    set_enabled_tracks,
    set_excluded_domains,
    set_excluded_locations,
    set_include_unstated_level,
    set_role_answers,
)
from tracker.taxonomy.domains import DOMAIN_GROUPS
from tracker.taxonomy.place_scope import excepted_under
from tracker.taxonomy.role_answers import (
    RoleAnswer,
    answers_from_axes,
    parse_answers,
    projection,
)


class ScopeInputError(ValueError):
    """A save asked for something no scope can be: answered as 422."""


@dataclass(frozen=True)
class AxesRequest:
    """What a save asks of each axis. None = leave that axis as stored."""

    enabled_role_groups: list[str]
    enabled_seniority_bands: list[str]
    enabled_role_tracks: list[str] | None = None
    enabled_location_groups: list[str] | None = None
    enabled_domain_groups: list[str] | None = None
    excluded_domain_groups: list[str] | None = None
    excluded_location_groups: list[str] | None = None
    include_unstated_level: bool | None = None
    #: Plain dicts (`RoleAnswer` wire shape); None = derive from the flat axes.
    role_answers: list[dict] | None = None
    experience_stage: str | None = None
    target_stage: str | None = None


def derive_stage_span(experience_stage: str, target_stage: str) -> list[str]:
    """The contiguous run of stages between where the user is and where they
    are aiming (either direction), inclusive. A stored "junior" stage reads as
    Entry (`band_slug`)."""
    experience_stage, target_stage = band_slug(experience_stage), band_slug(target_stage)
    order = [level.slug for level in LEVELS]
    for field, value in (
        ("experience_stage", experience_stage),
        ("target_stage", target_stage),
    ):
        if value not in order:
            raise ScopeInputError(f"unknown {field}: {value!r}")
    lo, hi = sorted((order.index(experience_stage), order.index(target_stage)))
    return order[lo : hi + 1]


async def save_excepted_places(
    session: AsyncSession, requested: list[str] | None, included: list[str]
) -> list[str]:
    """The request's exceptions (or the saved ones), pruned to those inside
    an included place, written back."""
    current = await get_excluded_locations(session) if requested is None else requested
    return await set_excluded_locations(session, excepted_under(set(included), current))


@dataclass(frozen=True)
class SavedAxes:
    """What `write_scope_axes` stored: the scope as the re-projection reads it."""

    roles: list[str]
    bands: list[str]
    tracks: list[str]
    locations: list[str]
    domains: list[str]
    excluded_domains: list[str]
    answers: tuple[RoleAnswer, ...]
    excepted: list[str]
    #: The stage pair when the request carried one (validated), else None.
    stages: tuple[str, str] | None
    include_unstated_level: bool

    def gate(self) -> tuple[tuple[list[str], list[str], list[str], list[str], list[str]], dict]:
        """`job_scope_expr`'s arguments, as `apply_saved_scope_to_jobs` gets them."""
        return (self.roles, self.bands, self.tracks, self.locations, self.domains), {
            "excluded_domains": self.excluded_domains,
            "answers": self.answers,
            "excluded_locations": self.excepted,
            "include_unstated_level": self.include_unstated_level,
        }


async def write_scope_axes(session: AsyncSession, payload: AxesRequest) -> SavedAxes:
    """The scope half of a settings save: validate, normalise and write every
    axis. The one normalisation both the save and its preview run;
    the preview runs it in a SAVEPOINT it rolls back. Writes; never
    commits, takes no lock: the caller owns both (the save
    takes the scope projection lock before its UPDATE)."""
    saved_roles = await set_enabled_roles(session, payload.enabled_role_groups)
    # Stages present => the seniority axis IS their span, whatever the axis
    # field carries. The stage dimmer is the only seniority control the product
    # has, so a stored band set contradicting the persona is corruption rather
    # than a choice: a `["staff"]` set against a principal->director_plus
    # persona would put every principal role out of scope.
    experience_stage, target_stage = payload.experience_stage, payload.target_stage
    if (experience_stage is None) != (target_stage is None):
        raise ScopeInputError("experience_stage and target_stage travel together")
    stages = (experience_stage, target_stage) if experience_stage is not None and target_stage is not None else None
    saved_bands = await set_enabled_bands(
        session,
        derive_stage_span(*stages) if stages is not None else payload.enabled_seniority_bands,
    )
    if payload.enabled_role_tracks is None:
        saved_tracks = sorted(await get_enabled_tracks(session))
    else:
        saved_tracks = await set_enabled_tracks(session, payload.enabled_role_tracks)
    if payload.enabled_location_groups is None:
        saved_locations = sorted(await get_enabled_locations(session))
    else:
        saved_locations = await set_enabled_locations(session, payload.enabled_location_groups)
    if payload.excluded_domain_groups is None:
        saved_excluded = [g.slug for g in DOMAIN_GROUPS if g.slug in await get_excluded_domains(session)]
    else:
        saved_excluded = await set_excluded_domains(session, payload.excluded_domain_groups)
    # After the veto: the worlds set's stored form depends on it.
    if payload.enabled_domain_groups is None:
        saved_domains = sorted(await get_enabled_domains(session))
    else:
        saved_domains = await set_enabled_domains(
            session, payload.enabled_domain_groups, excluded=saved_excluded
        )
    answers = await set_role_answers(
        session,
        parse_answers(list(payload.role_answers))
        if payload.role_answers is not None
        else answers_from_axes(saved_tracks, saved_roles),
    )
    saved_tracks, saved_roles = projection(answers)
    saved_excepted = await save_excepted_places(session, payload.excluded_location_groups, saved_locations)
    include_unstated = (
        await get_include_unstated_level(session)
        if payload.include_unstated_level is None
        else await set_include_unstated_level(session, payload.include_unstated_level)
    )
    return SavedAxes(
        roles=saved_roles, bands=saved_bands, tracks=saved_tracks, locations=saved_locations,
        domains=saved_domains, excluded_domains=saved_excluded, answers=answers,
        excepted=saved_excepted, stages=stages, include_unstated_level=include_unstated,
    )
