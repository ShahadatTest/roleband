"""Response contracts for the tracked-company surface and company profiles.

The rule `schemas/jobs.py` and `schemas/scope.py` state: a shape our code builds
forbids unknown keys, so a key a serializer adds without its model is a 500 a test
catches, never output that silently fails to arrive. Every shape here is built by
our code; none is read back from JSONB.

Literal types appear only where the value is a code constant: a discovery
company's `connector_state` is one of the labels `company_discovery` defines. A
company's `status`, `source` and catalog status are database strings with no
CHECK constraint, and stay `str`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from tracker.api.schemas.base import Built, Stored
from tracker.api.schemas.text_class import text
from tracker.schema import BoardRegion

# Held to `company_discovery.CONNECTOR_STATES` and `_PARKED` by
# `tests/test_api_company_contract.py`; the dashboard names each.
ConnectorState = Literal["live", "ready", "family", "active", "planned", "parked"]
ParkedReason = Literal["bot_protected", "robots_disallow", "prohibits_collection"]


class TrackedCompanyRow(Built):
    """One tracked company, as the roster and every company write answer with it."""

    slug: str
    display: str = Field(json_schema_extra=text("content"))
    adapter: str | None
    board_token: str | None
    careers_url: str | None
    status: str
    enabled: bool
    visible: bool
    source: str
    builtin: bool
    job_count: int
    role_catalog_status: str
    role_catalog_scanned_at: datetime | None
    role_catalog_error: str | None
    #: A pending company whose careers page named a known board family: the
    #: family, and why it stayed pending. Null otherwise.
    detected_family: str | None = Field(json_schema_extra=text("identifier"))
    pending_reason: Literal["policy_refused", "board_silent"] | None = Field(json_schema_extra=text("code"))


class MovedBoard(Built):
    """A careers page a company's roles moved to, verified to answer.

    `roles` is what it lists now (None when its family is not counted here);
    `shared` how many of those RoleBand read at the company before. `found_by`:
    `page` the company's own careers page names it, `name` guessed from the
    company's name and its roles overlap, `address` the person gave it."""

    adapter: str
    board_token: str
    board_region: BoardRegion | None
    roles: int | None
    shared: int
    found_by: Literal["page", "name", "address"]


class BoardSearchResponse(Built):
    """`POST /api/companies/{slug}/board/find`: the page found, or null."""

    candidate: MovedBoard | None


class CompanyListResponse(Built):
    """`GET /api/companies`."""

    companies: list[TrackedCompanyRow]


class DiscoverySector(Built):
    """A sector by slug; the dashboard names it."""

    slug: str
    company_count: int
    ready_count: int
    selected_count: int


class DiscoveryCompany(Built):
    """A company in the explorer: a catalog entry merged with its tracked row, if any.

    `status` is null for a company that is not tracked; `careers_url` is null only
    for a tracked company added outside the catalog without one.
    """

    slug: str
    display: str = Field(json_schema_extra=text("content"))
    careers_url: str | None
    sectors: list[str]
    aliases: list[str]
    connector_state: ConnectorState
    #: Why a `parked` company cannot be collected; null for every other state.
    parked_reason: ParkedReason | None = Field(json_schema_extra=text("code"))
    selectable: bool
    tracked: bool
    enabled: bool
    visible: bool
    builtin: bool
    #: On the curated list (`company_discovery.is_curated`): followed by a fresh
    #: install, and never touched by "Include other companies".
    curated: bool
    #: Why collecting this company needs the user's consent: its
    #: source's robots.txt disallows our route (`robots`) or its host refuses an
    #: identified client (`bot_wall`). Null for the unwalled majority.
    wall: Literal["robots", "bot_wall"] | None
    #: The user consented to collecting this walled company; asked once, never
    #: again. A walled company that is followed but not consented is not scanned.
    consented: bool
    #: A company from the directory of every other company RoleBand can scan,
    #: followed by name or brought in by the whole-set follow. The
    #: register draws these under "Not in a sector", apart from URL additions.
    directory: bool
    status: str | None
    #: A pending company whose careers page named a known board family: the
    #: family, and why it waits. Null otherwise.
    detected_family: str | None = Field(default=None, json_schema_extra=text("identifier"))
    pending_reason: Literal["policy_refused", "board_silent"] | None = Field(default=None, json_schema_extra=text("code"))


class DirectoryMatch(Built):
    """One directory company whose name matches the search."""

    slug: str
    display: str = Field(json_schema_extra=text("content"))
    #: "board": the board states this name; "address": read off its address.
    named_by: Literal["board", "address"]
    tracked: bool
    enabled: bool


class CompanyDirectorySearchResponse(Built):
    """`GET /api/companies/directory`: the best matches, never the whole set."""

    #: Companies in the directory at all, whatever the query.
    size: int
    #: Companies matching the query; `matches` holds at most the first 20.
    match_count: int
    matches: list[DirectoryMatch]


class CompanyDirectoryStatus(Built):
    """`GET /api/companies/directory/status`: the whole set, as one followable thing."""

    #: Companies in the directory.
    size: int
    #: The user follows the whole set.
    following: bool
    #: When the current follow began; null while not following.
    since: datetime | None
    #: Companies the background scan has read since `since` ...
    checked: int
    #: ... out of this many: every directory company not followed on its own.
    to_check: int
    #: Companies the set followed because they have roles for you, still followed.
    with_roles: int
    #: Following, and the scan waits because the machine is on battery.
    waiting_for_power: bool


class CompanyDiscoveryResponse(Built):
    """`GET /api/companies/discovery`, and what `PUT /api/companies/selection` answers
    with once it has re-read the roster."""

    sectors: list[DiscoverySector]
    companies: list[DiscoveryCompany]


class CompanyOpenCountsResponse(Built):
    """`GET /api/companies/open-counts`: a company with no open in-scope role is
    absent from `counts`. `not_counted`: followed companies the Profile's count
    leaves out, `missing` (no catalog yet; from the posting inventory: never
    read), `stale` (a catalog from before the joint, cleared by the company's
    next complete scan; from the posting inventory: read before, but not within
    the freshness window), or `partial` (counted from the posting inventory,
    with no complete scan yet).
    `last_read`: when each inventory-`stale` company was last read, so the
    screen can say so; empty under the catalog source. Postings in a
    followed company's last scan that no answer can keep, absent when none:
    `unplaced`, no place we could read; `unsorted`, a place but no
    role family."""

    counts: dict[str, int]
    not_counted: dict[str, Literal["missing", "stale", "partial"]]
    unplaced: dict[str, int]
    unsorted: dict[str, int]
    last_read: dict[str, datetime]


class CompanyNamesResponse(Built):
    """`GET /api/companies/names`: every catalog and tracked company's name by
    slug, read once by the dashboard before it renders so no screen prints a
    slug. A slug absent here is a directory company the install does not track."""

    names: dict[str, str]


# --------------------------------------------------------------------------- #
# Company profiles: `/api/company-profiles*` and the card
#
# A profile's values are RESOLVED from source claims (`profiles/resolve.py`), so
# each shown field carries its provenance. Shapes the handlers build forbid
# unknown keys. A conflict is read back from `company_profile.field_meta` (JSONB)
# as the resolver stored it, so it admits a key its model does not name and its
# keys are declared in the order Postgres serves a JSONB object: shorter keys
# first. `observed_at` inside provenance is the ISO string the store wrote, not a
# datetime this layer formats. A claim's value is whatever JSON a source asserted.
# --------------------------------------------------------------------------- #

# Held to `profiles.resolve` and the handlers by `tests/test_api_company_profiles_contract.py`.
DataHealth = Literal["ok", "stale", "conflict", "missing"]
Freshness = Literal["fresh", "aging", "stale"]
ReviewReason = Literal["conflict", "stale", "missing"]
ShownProfileField = Literal[
    "is_public",
    "ticker",
    "headcount",
    "hq_city",
    "website",
    "equity_vehicle",
    "vesting_schedule",
]
PriceRange = Literal["1m", "3m", "6m", "1y"]
#: A resolved profile column: a boolean, a count or money in whole dollars, or text.
ProfileValue = bool | int | str | None


class CompanyProfileSummary(Built):
    """One row of the profile list: identity, data health and the latest quote."""

    slug: str
    display_name: str = Field(json_schema_extra=text("content"))
    logo_url: str | None
    brand_color: str | None
    #: Listed or not, from our sources; null = not known.
    is_public: bool | None
    ticker: str | None
    equity_vehicle: str | None
    headcount: int | None
    data_health: DataHealth
    conflict_fields: list[str]
    mapped_levels: int
    #: The sectors the company is listed in, in `company_discovery.SECTORS`
    #: order; empty for a company outside every sector.
    sectors: list[str] = Field(json_schema_extra=text("code"))
    #: In the level atlas's offer facts (`levels.pay.PAY_POLICIES`): RoleBand
    #: researched how this company levels and pays.
    in_dataset: bool
    price: float | None
    change_pct: float | None
    currency: str | None
    price_as_of: str | None


class CompanyProfileListResponse(Built):
    """`GET /api/company-profiles`: visible companies by slug."""

    items: list[CompanyProfileSummary]
    #: Every sector slug in `company_discovery.SECTORS` order, so the list can
    #: group by sector the way Settings does without a second request.
    sectors: list[str] = Field(json_schema_extra=text("code"))
    #: The plugins whose data the list shows must be credited; null when only
    #: RoleBand's own data answers.
    attribution: str | None = Field(json_schema_extra=text("content"))


class ProfileFieldConflict(Stored):
    """Another source asserting a materially different value, as resolution stored it."""

    value: JsonValue
    source: str
    observed_at: str


class ProfileFieldCandidate(Built):
    """One source's latest claim about a field, offered as a choice."""

    source: str
    rank: int
    value: JsonValue
    observed_at: str


class ProfileFieldDetail(Built):
    """A resolved field and how far to trust it. Unasserted: every provenance key null."""

    value: ProfileValue
    source: str | None
    observed_at: str | None
    freshness: Freshness | None
    is_manual: bool
    conflicts: list[ProfileFieldConflict]
    candidates: list[ProfileFieldCandidate]
    #: False while a plugin answers the field: a pin would be ours.
    editable: bool
    #: The plugin answering this field, or null: ours. Only company
    #: size ever switches; a plugin that has not read the company shows no value.
    answered_by: str | None = Field(json_schema_extra=text("identifier"))


class CompanyProfileFields(Built):
    """The seven fields the profile shows, always all of them. No benefits total:
    a summed perk value is a total nobody measured, and Benefits shows
    each perk instead."""

    is_public: ProfileFieldDetail
    ticker: ProfileFieldDetail
    headcount: ProfileFieldDetail
    hq_city: ProfileFieldDetail
    website: ProfileFieldDetail
    equity_vehicle: ProfileFieldDetail
    vesting_schedule: ProfileFieldDetail


class ProfileReviewItem(Built):
    """One field needing a human, with the best-trusted value on offer."""

    field: ShownProfileField
    reason: ReviewReason = Field(json_schema_extra=text("code"))
    current: ProfileValue
    suggestion: ProfileFieldCandidate | None
    candidates: list[ProfileFieldCandidate]


class CompanyLevelBase(Built):
    """One band of our own per-level base pay (atlas `level_base.csv`),
    the reference family, while no pay plugin answers. A total requires known
    base, bonus and stock."""

    band: str = Field(json_schema_extra=text("code"))
    base_usd: int
    #: The company's bonus target as a share of base: 0 for a no-bonus company,
    #: null when its policy is not known (never 0).
    bonus_ratio: float | None
    bonus_usd: int | None
    #: Its base is below the band under it in this ladder (thin or mixed evidence).
    below_lower: bool
    #: Estimated annualised stock where our dataset holds it, or 0 where
    #: the company's policy grants none; null is unknown, never 0.
    stock_usd: int | None
    #: base + bonus + stock, only when all three are known.
    total_usd: int | None


class CompanyCompRung(Built):
    """One rung of the reference ladder. Amounts are whole units of `currency`,
    as its publisher stated them and never converted; shares are fractions."""

    level_label: str = Field(json_schema_extra=text("content"))
    band: str | None
    #: ISO 4217. Every amount on this rung is in it.
    currency: str = Field(json_schema_extra=text("code"))
    tc_median: int | None
    base_amount: int | None
    stock_amount: int | None
    bonus_amount: int | None
    base_pct: float | None
    stock_pct: float | None
    bonus_pct: float | None
    source: str
    source_url: str | None


class CompanyBenefitWording(Built):
    """Another record's words for the same benefit."""

    # `text` is declared last: the field's name shadows the helper in the class body.
    kind: Literal["dataset", "employer", "provider"]
    country: str | None = Field(json_schema_extra=text("code"))
    text: str = Field(json_schema_extra=text("content"))


class CompanyBenefitItem(Built):
    """One benefit on the profile, from the provider's rows or RoleBand's
    dataset records for it, led by its best wording. `benefit_type` is the taxonomy code the
    dashboard names; `name` is a provider's own label, kept where no alias maps
    it. `value_usd` is a per-perk estimate from the dataset record, never part of a total."""

    name: str | None = Field(json_schema_extra=text("content"))
    benefit_type: str | None = Field(json_schema_extra=text("code"))
    value_usd: int | None
    value_text: str | None = Field(json_schema_extra=text("content"))
    description: str | None = Field(json_schema_extra=text("content"))
    source: str = Field(json_schema_extra=text("identifier"))
    #: Who answers: a plugin id, a legacy source, or `builtin` (RoleBand's dataset).
    provider: str = Field(json_schema_extra=text("identifier"))
    builtin: bool
    #: dataset | employer | provider: a dataset record, an employer's own
    #: words, or a provider's row.
    kind: Literal["dataset", "employer", "provider"]
    #: The country the record applies to; null = unknown scope, never global.
    country: str | None = Field(json_schema_extra=text("code"))
    #: Someone reviewed this record against its evidence. False for every
    #: provider row.
    reviewed: bool
    #: How many times the company's job postings name this benefit (capture
    #: blocks, not independent sources); 0 for a provider row.
    mentions: int
    #: Every other distinct wording of this benefit, the row's own words first:
    #: one row per benefit.
    wordings: list[CompanyBenefitWording]


class CompanyBenefitNote(Built):
    """An employer sentence several benefits share, said once on the profile
    instead of under each benefit it names."""

    mentions: int
    benefit_types: list[str] = Field(json_schema_extra=text("code"))
    text: str = Field(json_schema_extra=text("content"))  # last: see CompanyBenefitWording


class CompanyBenefitGroup(Built):
    #: A taxonomy category code, or `other` for labels no alias maps.
    category: str = Field(json_schema_extra=text("code"))
    items: list[CompanyBenefitItem]


#: An offer fact the profile states on its own row (`levels.pay.PROFILE_OFFER_FACTS`).
ProfileOfferFact = Literal["equity_rule", "bonus_rule", "annual_refresh", "sign_on_bridges_vesting", "base_cap_usd"]


class CompanyOfferFact(Built):
    """One fact about how the company builds an offer, from the level atlas."""

    fact: ProfileOfferFact = Field(json_schema_extra=text("code"))
    #: A rule code (`equity_rule`, `bonus_rule`), a yes/no, or whole USD
    #: (`base_cap_usd`); null when searched for and not found.
    value: str | int | bool | None = Field(json_schema_extra=text("code"))
    #: Who states it; null with the value.
    stated_by: Literal["employer", "estimated"] | None


class CompanyOfferPolicy(Built):
    """How the company builds an offer (`levels.pay.profile_offer`)."""

    #: When the atlas last checked this company's facts.
    verified_on: str | None
    facts: list[CompanyOfferFact]
    #: Shown profile fields the atlas searched for and found nothing.
    unknown_fields: list[Literal["vesting_schedule", "equity_vehicle"]]


class CompanyLocationRow(Built):
    """A city with open in-scope roles. `country` is null for a city no country claims."""

    city: str
    open_count: int
    groups: list[str]
    country: str | None
    is_hq: bool


class SectionSource(Built):
    """Who answers one kind of data for one company: our data, or one
    plugin; a profile's parts and a job's pay."""

    #: The plugin answering it, or null: RoleBand's own data.
    plugin: str | None = Field(json_schema_extra=text("identifier"))
    #: The plugin's name; null when ours answers.
    plugin_name: str | None = Field(json_schema_extra=text("content"))
    #: The plugin has read this company whole. Always true when ours answers;
    #: false means "not covered by the plugin yet", never ours in its place.
    covered: bool


class ProfileSources(Built):
    """The one source answering each switching part of the profile."""

    pay: SectionSource
    benefits: SectionSource
    company_size: SectionSource


class CompanyProfileDetailResponse(Built):
    """`GET /api/company-profiles/{slug}`."""

    slug: str
    display_name: str = Field(json_schema_extra=text("content"))
    logo_url: str | None
    brand_color: str | None
    data_health: DataHealth
    needs_review: list[ProfileReviewItem]
    fields: CompanyProfileFields
    comp_levels: list[CompanyCompRung]
    #: Our base pay per band; empty while a pay plugin answers (one source).
    level_base: list[CompanyLevelBase]
    benefits: list[CompanyBenefitGroup]
    #: Sentences several benefits share, each once; empty while a plugin answers.
    benefit_notes: list[CompanyBenefitNote]
    #: Null when the atlas has not researched this company.
    offer_policy: CompanyOfferPolicy | None
    comp_notes: str | None = Field(json_schema_extra=text("content"))
    #: As the Board counts them: 0 when the company is hidden or not followed.
    open_roles: int
    #: A tracked company the user does not follow; False for one
    #: the user follows, or that is not tracked at all.
    unfollowed: bool
    locations: list[CompanyLocationRow]
    #: The credit every plugin answering this profile requires; null when only
    #: RoleBand's own data answers.
    attribution: str | None = Field(json_schema_extra=text("content"))
    #: A name for each source the dashboard's catalog cannot name: a plugin's
    #: own, and the ones it adopts. Keyed by `source`.
    source_names: dict[str, str] = Field(json_schema_extra=text("content"))
    #: Who answers the ladder, the benefits and company size.
    sources: ProfileSources


class ProfileHealth(Built):
    """`profiles.resolve.company_health`: the badge and the required fields behind it."""

    status: DataHealth
    missing: list[str]
    conflicts: list[str]
    stale: list[str]
    needs_review: list[str]


class CompanyProfileFieldWrite(Built):
    """`PATCH /api/company-profiles/{slug}` and `DELETE .../manual/{field}`: the health after re-resolving."""

    slug: str
    field: str
    health: ProfileHealth


class CompanyClaim(Built):
    """One claim as recorded: every source's word, newest first within a field."""

    field: str
    value: JsonValue
    source: str
    rank: int
    observed_at: datetime


class CompanyClaimsResponse(Built):
    """`GET /api/company-profiles/{slug}/claims`: empty, not 404, for an unknown slug."""

    slug: str
    claims: list[CompanyClaim]


class PriceQuote(Built):
    """`profiles.prices.latest_price_map`: the latest cached quote. `as_of` is a market date."""

    ticker: str
    price: float
    currency: str
    change_abs: float | None
    change_pct: float | None
    as_of: str


class PriceBarRow(Built):
    """One daily bar, oldest first."""

    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None


class CompanyPricesResponse(Built):
    """`GET /api/company-profiles/{slug}/prices`: an unknown `range` answers `3m`."""

    slug: str
    range: PriceRange
    currency: str
    latest: PriceQuote | None
    bars: list[PriceBarRow]
    #: Who to credit for the bars shown; null when there are none.
    attribution: str | None = Field(json_schema_extra=text("content"))
    #: A price key is set (Settings or the environment): an empty chart is waiting
    #: for the next scan, not for the user.
    feed_configured: bool


class CompanyCardResponse(Built):
    """`GET /api/companies/{slug}/card`: the chip's hover card, with or without a profile."""

    slug: str
    display_name: str = Field(json_schema_extra=text("content"))
    logo_url: str | None
    brand_color: str | None
    ticker: str | None
    is_public: bool
    has_profile: bool
    #: As the Board counts them: 0 when the company is hidden or not followed.
    open_roles: int
    #: A tracked company the user does not follow.
    unfollowed: bool
    top_cities: list[str]
    price: float | None
    change_pct: float | None
    currency: str | None
    price_as_of: str | None
