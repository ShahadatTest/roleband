"""Response contracts for the scope, settings and profile surface.

The same two strictness rules as `schemas/jobs.py`, for the same reasons:

- **A shape our code builds forbids unknown keys** (`extra="forbid"`), so a key
  a serializer adds without its model is a 500 a test catches, never output that
  silently fails to arrive.
- **A shape read from JSONB allows unknown keys and keeps them.** Here that is
  the stored persona `GET /api/profile` returns: `settings_store` hands back the
  row as written, by whichever version wrote it.

Literal types appear only where the value is a code constant: a location's
`kind` comes from the taxonomy table, and the refresh status from the handler's
three branches. Strings the database stores with no CHECK constraint (a
company's catalog status, a rule's kind) stay `str`.

Three shapes carry keys that are sometimes absent rather than null: a level's
decoder cell holds exactly one of its two keys, the refresh result carries
`reason` or `max_list` by branch, and a persona saved before the worlds axis and
the intent line lacks `domains` and `intent_statement`. Their routes use
`response_model_exclude_unset=True`, and `SkipJsonSchema[None]` marks each such
key as absent-or-valued, never `null`, in the generated client types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from tracker.api.schemas.base import Built, Stored
from tracker.api.schemas.text_class import text

# --- vocabularies --------------------------------------------------------- #
# Each is held to the source it mirrors by `tests/test_api_scope_contract.py`.

#: "city" is a city outside the fixed taxonomy, `city_<geonameid>`: listed
#: only when tracked or found by the place search.
LocationKind = Literal["metro", "country", "region", "city"]
DomainKind = Literal["function", "technology", "industry"]
ScopeRefreshStatus = Literal["started", "deferred", "already_running"]


# --- the five axes -------------------------------------------------------- #


class RoleAnswerModel(Built):
    """One kind of role and which of its roles count: "any" (every role of
    that kind, including families added later) or the families picked."""

    track: str
    roles: Literal["any"] | list[str]


class ScopeAxes(Built):
    """The five saved scope axes, each listed in taxonomy order, and the
    subjects the user is not interested in (a veto, not an axis)."""

    enabled_role_groups: list[str]
    enabled_seniority_bands: list[str]
    enabled_role_tracks: list[str]
    enabled_location_groups: list[str]
    enabled_domain_groups: list[str]
    excluded_domain_groups: list[str]
    #: Which roles of each kind. The two flat axes above are their
    #: projection, kept for readers that have not moved.
    role_answers: list[RoleAnswerModel]
    #: Places excepted inside the included ones ("the US except New York"),
    #: each strictly inside an included place.
    excluded_location_groups: list[str]
    #: Whether roles whose level isn't stated pass the level axis.
    include_unstated_level: bool


class SettingsSaveResponse(ScopeAxes):
    """`PUT /api/settings`: the axes as saved, and how many rows changed scope.

    The request's passengers (`intent_statement`, the two stage markers) are
    written to the persona and never echoed.
    """

    in_scope_changed: int
    #: Open in-scope postings a visible Board holds after the save,
    #: promoted rows included.
    on_board: int
    #: Postings a sync already read that this save put on the Board,
    #: and whether more wait for the running sync's end.
    promoted: int
    promotion_pending: bool


class ScopePreviewExample(Built):
    """One posting a save would put on the Board from an earlier scan."""

    title: str = Field(json_schema_extra=text("content"))
    company: str
    company_display: str = Field(json_schema_extra=text("content"))


class ScopePreviewResponse(Built):
    """`POST /api/scope/preview`: what saving this draft would do to the Board.
    Nothing is written."""

    #: Open in-scope postings a visible Board holds now (`on_board` before).
    on_board_now: int
    #: What the save's `on_board` would be: the open jobs the draft keeps plus
    #: the visible postings its promotion would add.
    on_board_after: int
    #: Postings from earlier scans the save would add now (its `promoted`).
    adds_now: int
    #: Those of them the Board shows (a hidden company's are added, not shown).
    adds_on_board: int
    #: Postings the draft keeps that join later: after the running scan, or
    #: beyond what one promotion admits.
    adds_later: int
    #: A scan holds the run lock, so the save promotes nothing now.
    scan_running: bool
    #: Up to three of the postings it would add, newest first.
    examples: list[ScopePreviewExample]


# --- the catalog ---------------------------------------------------------- #


class ScopeDomain(Built):
    """Named by the client from its catalog by `slug`; no English here."""

    slug: str
    selected: bool
    count: int
    # Employer-verbatim category values seen on matched postings: evidence for
    # the keyword map, not shown on the card.
    examples: list[str]
    # Display grouping only: the gate never reads it.
    kind: DomainKind


class PlaceResult(Built):
    """One place the location search offers (`GET /api/scope/places`)."""

    slug: str
    display: str = Field(json_schema_extra=text("content"))
    kind: LocationKind
    parent: str | None
    #: Where it is, in words: "Oregon, United States", "Europe".
    context: str = Field(json_schema_extra=text("content"))
    #: The alias or old name the query matched, when not the display name
    #: ("Bangalore" for Bengaluru, "Turkey" for Türkiye).
    matched_by: str | None


class UnionResult(Built):
    """A political union CLDR groups; choosing it chooses its members."""

    slug: str
    display: str = Field(json_schema_extra=text("content"))
    members: list[str]


class PlaceSearchResponse(Built):
    """`GET /api/scope/places`: taxonomy places and cities, best first, and
    any union the query names."""

    places: list[PlaceResult]
    unions: list[UnionResult]


class ScopeLocation(Built):
    slug: str
    display: str = Field(json_schema_extra=text("content"))
    default_enabled: bool
    selected: bool
    #: Introduced after the user last saved this axis: arrives off,
    #: and Settings marks it New until the next save.
    new: bool
    count: int
    kind: LocationKind
    parent: str | None
    uncovered_by: list[str]
    prominent: bool


class DecoderCell(Built):
    """How one company grades one stage: a company-wide label or per-track labels."""

    company_wide: str | SkipJsonSchema[None] = None
    per_track: dict[str, str] | SkipJsonSchema[None] = None


class ScopeLevel(Built):
    """Named by the client from its catalog by `slug`; no English here."""

    slug: str
    order: int
    default_enabled: bool
    selected: bool
    #: Introduced after the user last saved this axis: arrives off,
    #: and Settings marks it New until the next save.
    new: bool
    count: int
    decoder: dict[str, DecoderCell]


class ScopeTrack(Built):
    """Named by the client from its catalog by `slug`; no English here."""

    slug: str
    order: int
    default_enabled: bool
    selected: bool
    #: Introduced after the user last saved this axis: arrives off,
    #: and Settings marks it New until the next save.
    new: bool
    count: int
    allowed_bands: list[str]


class ScopeRoleGroup(Built):
    """Named by the client from its catalog by `slug`; no English here."""

    slug: str
    default_enabled: bool
    selected: bool
    #: Introduced after the user last saved this axis: arrives off,
    #: and Settings marks it New until the next save.
    new: bool
    enabled: bool
    total: int
    band_counts: dict[str, int]
    band_track_counts: dict[str, dict[str, int]]
    #: Every company counted here has band x track counts, or no posting at a
    #: counted level, so `band_track_counts` prices the whole group.
    joint_complete: bool


class ScopeCategory(Built):
    """Named by the client from its catalog by `slug`; no English here."""

    slug: str
    groups: list[ScopeRoleGroup]


class ScopeCatalogCompany(Built):
    slug: str
    display: str = Field(json_schema_extra=text("content"))
    #: Followed. Only a followed, scanned company can hold the joint counts
    #: back, so the Role counts card names only these.
    enabled: bool
    role_catalog_status: str
    role_catalog_scanned_at: datetime | None
    role_catalog_error: str | None


class ScopeCells(Built):
    """The joint over role x band x track x locations x domains.

    Every other count in this response is a MARGINAL — per band, per domain,
    per location — and marginals cannot be intersected. `domain_counts` in
    particular counts a multi-label posting once per domain, so they do not
    even sum. This is the one shape a client can apply the real gate to.

    Interned: `cells` is a list of six integers, `[role, band, track,
    location_set, domain_set, count]`, indexing the five dictionaries beside
    it. The dictionaries are the only place a slug is spelled out, which is
    what keeps a large catalog small.

    `location_sets[i]` is never empty — a posting with no matched location
    never reaches the catalog. `domain_sets[i]` IS empty for an unclassified
    posting, which passes the domain axis whatever the user selected; a client
    that drops the empty set re-implements the gate wrongly.

    Three states, kept apart because they have different cures. `companies`
    are counted. `missing_companies` are TRACKED but not catalogued — nothing
    is known about them yet, and onboarding one must not blank the screen,
    which is why `ready` does not consult them (`joint_counts_ready` does).
    `stale_companies` hold postings this column cannot place, from a scan that
    predates it; their next COMPLETE scan clears them. `ready` is false while
    any remain, because a partial joint is a WRONG number rather than a small
    one — but they are named, so the wait is diagnosable instead of a boolean.
    """

    ready: bool
    companies: list[str]
    missing_companies: list[str]
    stale_companies: list[str]
    #: Counted from the posting inventory with no complete scan yet: some of
    #: their roles are not counted until one. Always empty
    #: under the catalog source.
    partial_companies: list[str] = []
    roles: list[str]
    bands: list[str]
    tracks: list[str]
    location_sets: list[list[str]]
    #: The cities the joint can price: the tracked ones. Cells carry
    #: only these; a city not listed has an unknown share, never zero.
    cities: list[str]
    domain_sets: list[list[str]]
    cells: list[list[int]]
    #: Counted followed companies whose source lists only the places it was
    #: asked for, with the location groups the last scan asked. A
    #: place none of them touches is counted after the next scan, not zero.
    scanned_places: dict[str, list[str]]
    #: Listed postings at counted followed companies that the catalog could
    #: not count: no role family or no recognised place. They never reach the
    #: Board either.
    unplaced: int


class ScopeCatalogResponse(Built):
    """`GET /api/scope/catalog`: every axis a user can choose, with its inventory."""

    scope_cells: ScopeCells
    settings: ScopeAxes
    domains: list[ScopeDomain]
    unclassified_domain_count: int
    locations: list[ScopeLocation]
    levels: list[ScopeLevel]
    tracks: list[ScopeTrack]
    joint_counts_ready: bool
    #: Pre-gate postings that state no level, the `levels[].count`
    #: twin for the one count that is not a level. Cells carry them under the
    #: band "unstated".
    unstated_level_count: int
    categories: list[ScopeCategory]
    companies: list[ScopeCatalogCompany]


class ScopeRefreshRequest(BaseModel):
    """`POST /api/scope/refresh` body, optional: places the person is answering
    with and has not saved, asked for beside the saved ones."""

    locations: list[str] = []


class ScopeRefreshResponse(Built):
    """`POST /api/scope/refresh`: `status` says why nothing started (the client
    words it), `max_list` when a scan did."""

    status: ScopeRefreshStatus
    max_list: int | SkipJsonSchema[None] = None


# --- exclusion rules ------------------------------------------------------ #


class ScopeRule(Built):
    id: int
    company: str
    kind: str
    value: str
    created_at: datetime


class ScopeRuleList(Built):
    rules: list[ScopeRule]


class ScopeRuleCreateResponse(Built):
    """An existing rule answers with `created: false` and changes nothing."""

    rule: ScopeRule
    created: bool
    in_scope_changed: int
    #: Postings a sync already read that this save put on the Board,
    #: and whether more wait for the running sync's end.
    promoted: int
    promotion_pending: bool


class ScopeRuleDeleteResponse(Built):
    deleted: bool
    in_scope_changed: int
    #: Postings a sync already read that this save put on the Board,
    #: and whether more wait for the running sync's end.
    promoted: int
    promotion_pending: bool


# --- the persona ---------------------------------------------------------- #


class StoredPersonaProfile(Stored):
    """The persona: where the user is today, where they are aiming, and the
    aim sentence. The scope is not copied here."""

    experience_stage: str
    target_stage: str
    intent_statement: str | SkipJsonSchema[None] = None


class ProfileStateResponse(Built):
    """`GET /api/profile`."""

    profile: StoredPersonaProfile | None
    scope_configured: bool
    intent_statement: str


class IntentStatementResponse(Built):
    """`PUT /api/settings/intent`: the aim sentence as saved (trimmed; "" = none)."""

    intent_statement: str

