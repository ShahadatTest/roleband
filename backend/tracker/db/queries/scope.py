"""The scope gate as SQL: which held postings the user's saved scope admits.

`job_scope_expr` is the one expression every reader and writer of `in_scope`
builds from (the projection writer `db.repo.apply_saved_scope_to_jobs`, the
scope preview and promotion, the joint inventory, the scope filter), with its
pieces: the place clause, the level key, and the learned per-company
exclusions. Pure builders and one read; the write lives with the writers.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, case, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import CompanyScopeRule, Job
from tracker.levels import INCLUDE_UNSTATED_LEVEL_DEFAULT, UNSTATED_LEVEL
from tracker.schema import UNPLACED_BASIS_VALUES, LevelBasis
from tracker.taxonomy.place_scope import place_witnesses
from tracker.taxonomy.role_answers import RoleAnswer
from tracker.taxonomy.tracks import allowed_bands_for


def _place_clause(included: list[str], excepted: list[str], model=Job):
    """The location part of the gate. With no exceptions, a plain overlap;
    with them, `place_witnesses`' finite form of `place_admits`:
    a row holding a witness place and none of that place's blockers."""
    groups = model.location_groups
    if not excepted:
        return groups.op("&&")(included)
    plain = sorted(place for place, blockers in place_witnesses(included, excepted) if not blockers)
    guarded = [(place, sorted(blockers)) for place, blockers in place_witnesses(included, excepted) if blockers]
    return or_(
        false(),
        *([groups.op("&&")(plain)] if plain else []),
        *[
            and_(
                groups.op("@>")([place]),
                not_(func.coalesce(groups.op("&&")(blockers), false())),
            )
            for place, blockers in guarded
        ],
    )


def unplaced_level_expr(model=Job):
    """SQL for `basis in UNPLACED_BASES`: the row states no level, or one we
    cannot place. A NULL basis (not recorded) reads as `generic`, so it is
    never unplaced, and the expression is never NULL (a NULL would leave
    `in_scope` NULL)."""
    return func.coalesce(model.level_basis, LevelBasis.GENERIC.value).in_(UNPLACED_BASIS_VALUES)


def level_key_expr(model=Job):
    """SQL for the level a row is counted under: its band, or `unstated` when
    the row states no level or one we cannot place. Every grouping by level
    reads this, never `level_band`: an unplaced row's band is a sort default
    (`mid`) or a role-word guess, so grouped by band a bare title is counted
    as Mid-level."""
    return case((unplaced_level_expr(model), UNSTATED_LEVEL), else_=model.level_band)


def job_scope_expr(
    enabled_roles: set[str] | list[str],
    enabled_bands: set[str] | list[str],
    enabled_tracks: set[str] | list[str],
    enabled_locations: set[str] | list[str],
    enabled_domains: set[str] | list[str],
    exclusions: frozenset[tuple[str, str, str]] = frozenset(),
    *,
    excluded_domains: set[str] | list[str],
    answers: Sequence[RoleAnswer] | None = None,
    excluded_locations: set[str] | list[str] = (),
    include_unstated_level: bool = INCLUDE_UNSTATED_LEVEL_DEFAULT,
    model=Job,
):
    """SQL expression for the persisted user scope over already-enriched jobs.

    `model` is the table the gate reads: `Job`, or `PostingInventory`, whose
    classification columns carry the same names, types and NULL semantics.
    One gate for both, never a second one written by hand.

    Locations use array overlap (`&&`) against the stored matches: rows keep every
    matched group, the enabled set is a pure read-time filter. Any empty axis
    matches nothing, same as `passes_filters()`.

    The domain axis is the exception in both empty directions, and
    must mirror `passes_filters` exactly: an empty enabled set adds no clause
    at all ("no domain narrowing"), and an unclassified row, `domains` NULL
    (never classified) or `{}` (classified, honestly unknown),
    always passes. Fail-open is what makes the axis safe for title-only
    companies the lexicon knows nothing about.

    A row whose level is not stated (`level_basis` 'none') is never
    judged by its stored `mid`: it passes every level check (the flat bands
    and each answer's range) exactly when `include_unstated_level` holds, as
    `passes_filters` does. A NULL basis reads as `generic` through
    `unplaced_level_expr`'s COALESCE, never a bare `=`, which would make the
    clause NULL and write a NULL `in_scope`.
    """
    unstated = unplaced_level_expr(model)

    def level_in(allowed: list[str]):
        if include_unstated_level:
            return or_(unstated, model.level_band.in_(allowed))
        return and_(not_(unstated), model.level_band.in_(allowed))

    def family_in(families: list[str]):
        # A posting whose family is unknown matches no family. Compared bare,
        # `family IN (...)` is NULL for it, which makes the clause NULL
        # wherever the rest admits the posting, and the recompute would write
        # NULL into `in_scope`. The guard first, so the clause is FALSE.
        return and_(model.family.isnot(None), model.family.in_(families))

    roles = sorted(set(enabled_roles))
    bands = sorted(set(enabled_bands))
    tracks = sorted(set(enabled_tracks))
    locations = sorted(set(enabled_locations))
    domains = sorted(set(enabled_domains))
    if answers is not None:
        # Which roles of each kind: an OR over the answers, each
        # holding its own families and its track's level range. `false()`
        # first, so no answers admits nothing (a bare `or_()` renders as no
        # clause at all and would admit everything).
        role_clause = or_(false(), *[
            and_(
                model.track == answer.track,
                model.family.isnot(None) if answer.families is None else family_in(sorted(answer.families)),
                level_in(allowed_bands_for(answer.track)),
            )
            for answer in answers
        ])
        if not answers or not bands or not locations:
            return false()
    else:
        if not roles or not tracks:
            return false()
        role_clause = and_(family_in(roles), model.track.in_(tracks))
    if not bands or not locations:
        return false()
    expr = and_(
        level_in(bands),
        role_clause,
        _place_clause(locations, sorted(set(excluded_locations)), model),
    )
    if domains:
        expr = and_(
            expr,
            or_(
                model.domains.is_(None),
                func.coalesce(func.cardinality(model.domains), 0) == 0,
                model.domains.op("&&")(domains),
            ),
        )
    excluded = sorted(set(excluded_domains))
    if excluded:
        # A veto: any excluded subject on the row drops it. NULL domains
        # (never classified) overlap nothing; coalesce keeps the clause TRUE there,
        # or the NOT would write a NULL `in_scope`.
        expr = and_(
            expr,
            not_(func.coalesce(model.domains.op("&&")(excluded), false())),
        )
    if exclusions:
        expr = and_(expr, not_(scope_exclusion_expr(exclusions, model)))
    return expr


def scope_exclusion_expr(exclusions, model=Job):
    """SQL for the learned per-company exclusions (company_scope_rules).

    `exclusions` is (company, kind, value) triples, kind "team"|"department".
    Mirrors `enricher.rule_excluded` exactly: case-insensitive EXACT match on
    the employer's verbatim field, never a substring, because this expression
    and that function are the same gate on two surfaces, and any drift between
    them makes a saved rule lie on one of them.

    A missing field has nothing to match: `rule_excluded` skips a posting whose
    team or department is absent or empty, and so does this. Compared bare,
    `lower(trim(NULL))` is NULL, which would make the whole scope expression
    NULL for such a posting, and the recompute would write NULL into
    `jobs.in_scope`, a NOT NULL column, failing the save. The two guards come
    first so the clause is FALSE, never NULL, whatever the column holds.
    """
    matches = []
    for company, kind, value in sorted(set(exclusions)):
        column = model.team if kind == "team" else model.department
        matches.append(
            and_(
                model.company == company,
                column.is_not(None),
                column != "",
                func.lower(func.trim(column)) == value.strip().lower(),
            )
        )
    return or_(*matches) if matches else false()


async def load_scope_exclusions(session: AsyncSession) -> frozenset[tuple[str, str, str]]:
    """The learned exclusion rules as matcher-ready (company, kind, lowered value)."""
    rows = (await session.scalars(select(CompanyScopeRule))).all()
    return frozenset(
        (row.company, row.kind, row.value.strip().lower()) for row in rows
    )
