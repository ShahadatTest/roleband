"""Response contracts for the job browse surface: list, detail, view, favorite, dismiss,
similar postings and filter facets.

Each model states what its route serializes, key for key and in the order the
serializer writes it. Two rules decide how strict a model is.

- **A shape our code builds forbids unknown keys** (`extra="forbid"`). A Pydantic
  response model filters out whatever it does not declare, so a lenient model
  would turn a key added to a serializer into output that silently never
  arrives. Forbidden, the same drift is a 500 that a test catches.
- **A shape read from JSONB allows unknown keys and keeps them**
  (`description_sections`, `comp_sources`). The database is the writer there, and
  a row written by an older version must still render.

Literal types appear only where the value is a constant in the code building the
response, or a database CHECK constraint enforces it; `test_api_job_contract.py`
holds each vocabulary to its source. Database strings with no constraint (skill
facets, importance bands, modalities) stay `str`: an unexpected value is a
display question for the client, never a reason for the API to fail.

Keys present on only some responses of a route (the relevance envelope's
`parsed`, an intent row's `why_world`) default to None, and those routes use
`response_model_exclude_unset=True`, so a key the handler did not set stays
absent instead of arriving as `null`. `SkipJsonSchema[None]` marks a key that is
either absent or a real value, never `null`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from tracker.api.schemas.base import Built, Stored
from tracker.api.schemas.companies import SectionSource
from tracker.api.schemas.text_class import text
from tracker.schema import PostingPageOutcome

# --- vocabularies --------------------------------------------------------- #
# Each is held to the constants or the CHECK constraint it mirrors by a test.

CompProvenance = Literal["stated", "estimated"]
CompPackageState = Literal["unchecked", "none_stated", "band"]
CompSplitSource = Literal["measured", "cross_family", "heuristic"]
CompEquityBasis = Literal["measured_grant", "ratio"]
CompNoSplitReason = Literal[
    "basis_unclear", "hourly", "monthly", "period_unclear", "employee_election", "total_compensation",
    "plugin_without_split", "plugin_not_covered", "not_us_pay",
]
CompReconciliationVerdict = Literal["consistent", "stated_above_measured", "stated_below_measured"]
CompMarketVerdict = Literal["consistent", "diverges"]
OfferBonusRule = Literal["pct_of_base", "none"]
OfferEquityRule = Literal["dollar_grant_by_level", "tc_target_minus_base", "employee_election", "none"]
#: A policy fact by name, for `OfferPolicy.estimated`.
OfferPolicyFact = Literal[
    "bonus_rule", "equity_rule", "equity_vehicle", "vesting", "sign_on_bridges_vesting", "base_cap_usd", "annual_refresh"
]
PursuitStage = Literal[
    "saved", "researching", "networking", "applied", "interviewing", "offer", "rejected", "withdrawn"
]
ReviewRelevance = Literal["relevant", "irrelevant", "uncertain"]
RequirementsState = Literal["ready", "pending", "unavailable"]
MatchClass = Literal["exact", "close", "related"]
QueryKind = Literal["identifier", "exact_title", "exploratory"]
ListingBasis = Literal["employer", "sighting"]


# --- rows ----------------------------------------------------------------- #


class PostedBase(Built):
    """A posted base range, in its own currency and period, never converted."""

    min: int | None
    max: int | None
    currency: str
    period: Literal["year", "hour", "month"]


class JobRow(Built):
    """One posting as every job surface lists it (`serialize_job` without detail)."""

    id: int
    is_favorite: bool
    is_dismissed: bool
    #: The posting's company is tracked and not followed: nothing
    #: checks it any more. Only Saved, Compare and reads by id can show one.
    company_unfollowed: bool
    company: str
    req_id: str
    title: str = Field(json_schema_extra=text("content"))
    url: str
    department: str | None
    team: str | None
    locations: list[str]
    location_groups: list[str]
    domains: list[str]
    workplace_type: str
    level_band: str
    level_confidence: str
    #: What decided the band: stated | company | generic | none; None = not
    #: recorded yet. "none" is a posting that states no level, its `mid` a
    #: placeholder.
    level_basis: str | None
    family: str | None
    track: str
    comp_low: int | None
    comp_high: int | None
    comp_median: int | None
    comp_currency: str
    comp_provenance: str | None
    #: Per component: the base range is its own estimate;
    #: `comp_component` says the widest part that answers (total | base).
    comp_base_low: int | None = None
    comp_base_median: int | None = None
    comp_base_high: int | None = None
    comp_component: str | None = Field(default=None, json_schema_extra=text("code"))
    #: Who answered: a plugin id, a core source, or `builtin` (our dataset).
    comp_provider: str | None = Field(default=None, json_schema_extra=text("identifier"))
    comp_as_of: date | None = None
    #: The posting's own base range as the row writes it; null when it states
    #: none, states a total or an unclear basis, or no period the row can write.
    posted_base: PostedBase | None = None
    status: str
    in_scope: bool
    posted_at: datetime | None
    first_seen: datetime
    last_seen: datetime
    viewed_at: datetime | None
    closed_at: datetime | None
    days_open: int | None
    repost_count: int
    lineage_id: int | None
    lineage_seq: int | None
    lineage_role: str | None
    lineage_size: int | None
    lineage_days_open: int | None
    #: The earliest date either side states for THIS posting: the employer's
    #: first published date, or our first sighting. The
    #: lineage never moves it; role age is Job detail's `role_since`.
    listed_since: datetime | None
    #: Days listed from `listed_since`, to now or to closing. The age a person
    #: reads; `days_open` is our own sighting clock.
    listed_days: int | None
    #: Whose date `listed_since` is: `employer` when their first published
    #: date is earlier than our first sighting, else `sighting`.
    listed_basis: ListingBasis | None
    #: The row lights as new: open, not a repost, and listed under
    #: `NEW_LISTING_DAYS` whole days by evidence that dates it, the employer's
    #: date or a sighting where the company was already read. The New view
    #: and the header's count list exactly these rows.
    new_listing: bool
    twin_count: int
    #: Places the role is listed in when its employer lists it once per place
    #: (`lineage/place_sets.py`); null for a posting in no place set.
    place_count: int | None
    #: Postings in that place set: more than `place_count` when the role is
    #: listed again at a place; null for a posting in no set.
    place_set_size: int | None
    discloses_pay: bool


class PostingReality(Built):
    """Is this posting likely a standing one? (`analytics/posting_reality.py`).

    `level` never goes past `possible`: structural evidence alone cannot claim
    more. `met` names the criteria that fired, in `CRITERIA` order, over a
    denominator of `criteria_total`. `listings` is how many times the role has
    been listed: each posting of its lineage once, plus each return of this one
    after closing. The age is the row's own `listed_days`."""

    level: Literal["possible", "none"]
    met: list[Literal["long_open", "relisted", "redated"]]
    criteria_total: int
    listings: int


class JobListItem(JobRow):
    """A row of `GET /api/jobs`. Each ranked path adds its keys; they are absent otherwise.

    `posting_reality` is on every list row: the verdict Job detail
    serves, null for a closed posting. The Board shows a sign only at
    `possible`."""

    posting_reality: PostingReality | None

    # Intent-ranked and relevance rows. Null when the row has no rank (no
    # embedding, or an identifier match). Never rendered as a number.
    relevance: float | None = None
    # Intent-ranked rows only: the world the role serves, as a slug the
    # dashboard names.
    why_world: str | None = Field(default=None, json_schema_extra=text("code"))
    # Relevance rows only: membership evidence, "exact" first on exact rows.
    matched_via: list[str] | SkipJsonSchema[None] = None
    match_class: MatchClass | SkipJsonSchema[None] = None


class ParsedQueryEcho(Built):
    """The structured filters a search query was read as."""

    company: list[str]
    level_band: list[str]
    family: list[str]
    workplace_type: list[str]
    location_group: list[str]
    #: The money the query names, applied as bounds on the base each row shows.
    comp_min: int | None
    comp_max: int | None
    remainder: str


class JobListResponse(Built):
    """`GET /api/jobs`: one envelope, three shapes.

    Default ordering sends the first four keys. A queryless relevance sort
    ordered by the intent vector adds `ranked_by`. A relevance search adds every
    search key, `related_items` included (empty when there is no related section).
    A queryless relevance sort (Best fit) adds `placed_total`: the rows whose
    level we place come first, so the "level not placed" group starts at that
    index of the filtered set.
    """

    total: int
    limit: int
    offset: int
    items: list[JobListItem]
    ranked_by: Literal["intent"] | SkipJsonSchema[None] = None
    placed_total: int | SkipJsonSchema[None] = None
    matched: int | SkipJsonSchema[None] = None
    ranking_truncated: bool | SkipJsonSchema[None] = None
    related_items: list[JobListItem] | SkipJsonSchema[None] = None
    related_total: int | SkipJsonSchema[None] = None
    query_kind: QueryKind | SkipJsonSchema[None] = None
    parsed: ParsedQueryEcho | SkipJsonSchema[None] = None


# --- detail --------------------------------------------------------------- #


class DescriptionSection(Stored):
    key: str
    title: str = Field(json_schema_extra=text("content"))
    content: str


class DisclosedComp(Built):
    """The pay band the posting stated. The object exists once a band is
    stored or the text pass has read the posting."""

    disclosed: bool
    base_min: int | None
    base_max: int | None
    currency: str | None
    pay_basis: str | None
    pay_period: str | None
    #: The employer's own words that state the band; null when the band came
    #: from the posting page's pay field, which states numbers, not words.
    snippet: str | None
    #: True when the band was read from the posting page's structured pay
    #: field rather than the posting's text.
    from_pay_field: bool
    confidence: str | None
    bonus_pct: float | None
    #: When the text pass last read the posting; null when the band is known
    #: only from the posting page or a connector and the text is not read yet
    #:. Never a stamp written to make a band visible.
    checked_at: datetime | None


class JobPursuit(Built):
    id: int
    job_id: int
    stage: PursuitStage
    priority: int
    notes: str | None = Field(json_schema_extra=text("content"))
    next_action: str | None
    next_action_due: datetime | None
    created_at: datetime
    updated_at: datetime


class JobRelevanceReview(Built):
    domain: str | None
    relevance: ReviewRelevance
    confidence: float
    rationale: str
    tracked_worlds: list[str]
    prompt_version: str
    provider: str | None
    model_id: str | None
    reviewed_at: datetime


class CompSource(Stored):
    """One provider's estimate, from the latest observation's payload."""

    provider: str
    # `int | float`, not `float`: a float field re-emits 735000 as 735000.0.
    median: int | float | None
    low: int | float | None
    high: int | float | None
    currency: str
    source: str


class CompRange(Built):
    low: int
    high: int


class CompComponent(Built):
    kind: Literal["base", "bonus", "equity"]
    low: int
    high: int
    provenance: CompProvenance


class CompTotal(Built):
    low: int
    high: int
    provenance: CompProvenance


class CompEstimate(Built):
    """The cohort estimate; the object exists only when a median does."""

    low: int | None
    median: int
    high: int | None
    provenance: str | None


class CompBaseEstimate(Built):
    """Our estimate of the base alone, where no total is known: shown as
    "Est. base", labelled with who answers it, never read as a total."""

    low: int | None
    median: int
    high: int | None
    #: `builtin` (RoleBand's dataset), a plugin id, or a core-written source.
    provider: str | None = Field(json_schema_extra=text("identifier"))
    as_of: date | None


class CompMarketGap(Built):
    ratio: float
    verdict: CompMarketVerdict


class CompReconciliation(Built):
    measured_base: int | None
    ratio_high: float | None
    verdict: CompReconciliationVerdict | None


class OfferPolicy(Built):
    """How the company builds an offer. Unverified facts are null, never guessed."""

    verified: bool
    bonus_rule: OfferBonusRule | None
    equity_rule: OfferEquityRule | None
    vesting: str | None
    sign_on_bridges_vesting: bool
    base_cap_usd: int | None
    annual_refresh: bool | None
    #: Estimated facts above; the other known facts are employer-stated.
    estimated: list[OfferPolicyFact]
    #: Facts searched for and not found: the employer and estimated pay say nothing.
    unknown: list[OfferPolicyFact]


class JobCompPackage(Built):
    """Cash, bonus and equity for one role, and which parts the employer stated.

    Built by `analytics/comp_package.build_job_package`; docs/pay.md has
    the derivation. Every key is always present.
    """

    state: CompPackageState
    basis: str | None
    currency: str | None
    pay_period: str | None
    stated: CompRange | None
    bonus_pct: float | None
    components: list[CompComponent]
    total: CompTotal | None
    estimate: CompEstimate | None
    split_source: CompSplitSource | None
    #: Who supplied the per-level split, and the date it is as of; null with
    #: no measured split.
    split_provider: str | None = Field(json_schema_extra=text("identifier"))
    split_as_of: date | None
    equity_basis: CompEquityBasis | None
    market_gap: CompMarketGap | None
    reconciliation: CompReconciliation | None
    no_split_reason: CompNoSplitReason | None = Field(json_schema_extra=text("code"))
    snippet: str | None
    confidence: str | None
    #: Our offer policy; null while a plugin answers pay: it rides only on our
    #: figures.
    policy: OfferPolicy | None
    #: Only where no total is estimated: the base we can estimate.
    base_estimate: CompBaseEstimate | None = None


class JobLifecycleEntry(Built):
    event_type: str
    detail: dict[str, Any]
    at: datetime


class RequirementEvidence(Built):
    section_key: str | None
    section_title: str | None = Field(json_schema_extra=text("content"))
    quote: str
    start_offset: int
    end_offset: int
    modality: str


class RequirementSkill(Built):
    concept_id: int
    #: The catalog slug; the client names the skill.
    slug: str
    facet: str
    category: str
    importance_band: str
    importance_score: int
    confidence: str
    modality: str
    proficiency: str
    evidence: list[RequirementEvidence]


class RequirementQualification(Built):
    id: int
    kind: str
    display: str = Field(json_schema_extra=text("content"))
    modality: str
    #: An experience row's headline years and every number its line states
    #: ("8+ years, or 6 with a PhD": 8.0 and [8.0, 6.0]); None and [] otherwise.
    years: float | None
    years_stated: list[float]
    evidence: list[RequirementEvidence]


class JobRequirements(Built):
    state: RequirementsState
    extractor_version: str | None
    skills: list[RequirementSkill]
    qualifications: list[RequirementQualification]
    #: The largest years a REQUIRED experience row states, or None
    #: (`skills.extract.required_years`).
    required_years: float | None


class JobDetailRow(JobRow):
    """`serialize_job(detail=True)`: the row plus the posting's own text and stated pay.

    What the lineage and twin surfaces send for each posting they pair. It
    carries none of what `get_job` adds beside the serializer."""

    description_text: str | None = Field(json_schema_extra=text("content"))
    description_html: str | None
    description_sections: list[DescriptionSection]
    disclosed_comp: DisclosedComp | None


class ApplicationForm(Built):
    """What the posting's application form asks beyond name, contact and resume:
    counts only, never a question's wording. `required` employer
    questions, of which `written` need a written answer and `choices` are a
    pick; `asks_expected_pay` when one demands your expected pay."""

    required: int
    written: int
    choices: int
    asks_expected_pay: bool
    read_at: datetime | None


class PayFloorCheck(Built):
    """How the posting's stated yearly pay compares with the user's pay floor.
    `below` is the only verdict a total or unstated-basis band can
    earn; nothing is sent when the band is not yearly, not in the floor's
    currency, or there is no floor."""

    verdict: Literal["clears", "straddles", "below"]
    amount: int
    currency: str
    basis: str | None


class PostingPageResponse(Built):
    """`POST /api/jobs/{job_id}/posting-page`: read the posting's own
    page because someone opened it. `already_read` answers from storage with no
    request; `not_available` is a source with no page; `failed` stores nothing
    over an earlier read."""

    outcome: PostingPageOutcome
    application_form: ApplicationForm | None


class JobDetailResponse(JobDetailRow):
    """`GET /api/jobs/{job_id}`: the row plus everything the detail route shows.
    `posting_reality` is null for a closed posting."""

    feedback_reason: str | None = Field(json_schema_extra=text("code"))
    pursuit: JobPursuit | None
    relevance_review: JobRelevanceReview | None
    comp_sources: list[CompSource]
    comp_package: JobCompPackage
    #: Who answers this job's pay and whether it has read its company.
    pay_source: SectionSource
    lifecycle: list[JobLifecycleEntry]
    requirements: JobRequirements
    posting_reality: PostingReality | None
    #: Null until the posting's own page has been read (only where that page states its form).
    application_form: ApplicationForm | None
    #: True when opening this posting should ask for its page:
    #: the client then calls `POST /api/jobs/{id}/posting-page` once.
    application_form_readable: bool
    #: Null when there is no floor or the band cannot be compared with it.
    pay_floor_check: PayFloorCheck | None
    #: Role age: from the earliest listing start among the postings
    #: of this one's lineage, each by the headline rule, to now or to the last
    #: closing. All three null unless the lineage has two or more postings;
    #: a pending suspected link never moves them.
    role_since: datetime | None
    role_days: int | None
    role_postings: int | None


# --- listing history -------------------------------------------------------- #

ListingEventKind = Literal[
    "employer_published", "first_seen", "closed", "reopened", "redated", "edited",
    "earlier_posting", "later_posting", "last_seen",
]
LinkState = Literal["auto", "confirmed"]


class ListingAge(Built):
    """The headline listing age: the row's `listed_since`/`listed_days`/`listed_basis`."""

    since: datetime
    days: int
    basis: ListingBasis


class RoleAge(Built):
    """How long the company has been trying to fill the role, over every
    posting of the lineage (`postings`, this one included)."""

    since: datetime
    days: int
    postings: int


class ListingEvent(Built):
    """One dated fact. Every key is sent; those a kind does not use are null.

    `redated` carries `from_at`/`to_at` (the employer's old and new date);
    `edited` carries `field` and `count` (one event per changed field, `at` the
    latest); `earlier_posting`/`later_posting` carry the other posting's
    `job_id`, `req_id`, `title`, `until` (its closing, null while open) and
    `link` (`confirmed` when a person confirmed the link, else `auto`), at that
    posting's own listing start."""

    at: datetime
    kind: ListingEventKind
    from_at: datetime | None
    to_at: datetime | None
    field: str | None
    count: int | None
    job_id: int | None
    req_id: str | None
    title: str | None = Field(json_schema_extra=text("content"))
    until: datetime | None
    link: LinkState | None


class UnconfirmedPosting(Built):
    """A pending suspected link to another posting: possibly the same role,
    counted in no number until a person confirms it."""

    link_id: int
    job_id: int
    req_id: str | None
    title: str = Field(json_schema_extra=text("content"))
    listed_since: datetime


class ListingHistoryResponse(Built):
    """`GET /api/jobs/{job_id}/history`: every dated fact about a
    posting, oldest first, and the postings counted, or not, as the same role.
    `role` is null for a posting with no effective lineage."""

    headline: ListingAge
    role: RoleAge | None
    events: list[ListingEvent]
    unconfirmed: list[UnconfirmedPosting]


# --- writes --------------------------------------------------------------- #


class JobViewResponse(Built):
    job_id: int
    viewed_at: datetime


class FavoriteResponse(Built):
    job_id: int
    is_favorite: bool


class DismissResponse(Built):
    """Everything the dismiss flow needs to offer an exclusion rule, without a read."""

    job_id: int
    is_dismissed: bool
    reason: str | None = Field(json_schema_extra=text("code"))
    company: str
    department: str | None
    team: str | None


class UndismissResponse(Built):
    job_id: int
    is_dismissed: bool


# --- similar postings and facets ------------------------------------------ #

SimilarityScope = Literal["within", "cross", "all"]


class SimilarJob(JobRow):
    """A neighbour as a list row, with its similarity to the posting asked about."""

    score: float


class SimilarJobsResponse(Built):
    """`GET /api/jobs/{job_id}/similar`, most similar first. `within` is the same company."""

    scope: SimilarityScope
    items: list[SimilarJob]


class FacetOption(Built):
    """A company the board can filter on, by the name the user follows it by."""

    display: str = Field(json_schema_extra=text("content"))


class VocabFacetOption(Built):
    """A family, track or world: the key is its slug, and the client names it
    from its catalog (`dashboard/src/copy/vocab.ts`). No English here."""


class LocationFacetOption(Built):
    """`parent` is the taxonomy's own parent, which may itself not be offered.
    `display` is the place's own standard name; the client names
    RoleBand's own groupings (metros, regions) from its catalog."""

    display: str = Field(json_schema_extra=text("content"))
    parent: str | None


class FacetCounts(Built):
    """Open, in-scope, visible roles per value; a null column value is never a key."""

    company: dict[str, int]
    level_band: dict[str, int]
    level_confidence: dict[str, int]
    family: dict[str, int]
    track: dict[str, int]
    workplace_type: dict[str, int]
    location_group: dict[str, int]
    domain: dict[str, int]


class FacetsResponse(Built):
    """`GET /api/facets`: the board's filter options and their counts.

    Families and tracks list the whole taxonomy; locations only tracked groups with
    roles; worlds only those with roles, plus `unclassified` when some roles name none.
    """

    companies: dict[str, FacetOption]
    families: dict[str, VocabFacetOption]
    tracks: dict[str, VocabFacetOption]
    location_groups: dict[str, LocationFacetOption]
    domains: dict[str, VocabFacetOption]
    total: int
    counts: FacetCounts
