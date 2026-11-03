"""Normalized domain types shared across adapters, enrichment, and storage.

Every adapter converts a company's raw payload into a `RawJob`. Enrichment then
annotates it (level band/confidence, family, matched location groups, comp) before
it is persisted. Keeping this provider-agnostic is what lets the pipeline, DB, and
dashboard treat every source uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Literal


class LevelBand(str, Enum):
    """Career stages — a full-market ladder where every rung is first-class.

    Coarser than any company's ladder; `levels/ladder.walk_guide` decodes
    each stage to per-company level labels.
    """

    INTERN = "intern"  # internship / working student
    ENTRY = "entry"  # new grad / junior / associate / trainee: a first full-time rung
    MID = "mid"  # no seniority marker in the title (flagged unconfirmed)
    SENIOR = "senior"  # L5-L6 / senior IC or manager candidate
    STAFF = "staff"  # L6 / ICT5
    PRINCIPAL = "principal"  # L7-L8 / ICT6
    DIRECTOR_PLUS = "director_plus"  # director / VP / distinguished / fellow

# Ordering for sorting / comparison in the dashboard.
LEVEL_BAND_ORDER: dict[str, int] = {
    LevelBand.INTERN.value: 0,
    LevelBand.ENTRY.value: 1,
    LevelBand.MID.value: 2,
    LevelBand.SENIOR.value: 3,
    LevelBand.STAFF.value: 4,
    LevelBand.PRINCIPAL.value: 5,
    LevelBand.DIRECTOR_PLUS.value: 6,
}

#: Band values that are not bands but that a stored row, a scan tally or a
#: saved choice may carry, mapped to the band they read as: "junior" is entry,
#: since few company ladders have a second first rung. Read through
#: `parse_band`, never written.
LEGACY_BANDS: dict[str, LevelBand] = {"junior": LevelBand.ENTRY}


def parse_band(value: str | LevelBand) -> LevelBand:
    """A stored band value as today's band: a legacy value maps to the band it
    was folded into, anything else is `LevelBand(value)` (ValueError when it
    names no band)."""
    if isinstance(value, LevelBand):
        return value
    return LEGACY_BANDS.get(value) or LevelBand(value)


def band_slug(value: str) -> str:
    """A stored band slug as today's slug; an unknown one is returned unchanged
    for the caller to drop."""
    legacy = LEGACY_BANDS.get(value)
    return legacy.value if legacy else value


class LevelConfidence(str, Enum):
    CONFIRMED = "confirmed"  # title/level query authoritatively says L6+
    UNCONFIRMED = "unconfirmed"  # ambiguous (e.g. bare "Member of Technical Staff")


class LevelBasis(str, Enum):
    """What decided a posting's band. Orthogonal to confidence: a
    company rule and a generic word can both be confirmed, and only NONE means
    the posting states no level at all.

    NONE keeps `level_band` = mid so sorting and pay lookups still have a band,
    but the scope gate never reads that mid as a level: the row passes the level
    axis only when the user includes roles whose level isn't stated."""

    STATED = "stated"  # the rung the employer printed on the posting (Microsoft IC5)
    COMPANY = "company"  # the company's own title vocabulary (Amazon "Sr." = L6)
    # The posted base range is one the company pays at a known rung of this
    # family (`levels.pay_grades`): read only when the title names no rung.
    PAY_GRADE = "pay_grade"
    GENERIC = "generic"  # generic title words ("Senior", "Director", "Intern")
    # The title names a level or a role in the company's own terms that we
    # cannot place on the shared levels ("Senior Manager", "Engineering
    # Manager", "Lead", "Product Manager"): the band is a generic
    # guess kept for sorting and pay lookups, never a level the scope gate
    # reads. Shown as "level not mapped", never as "level not stated".
    UNMAPPED = "unmapped"
    NONE = "none"  # nothing read: a bare title ("Software Engineer")


#: Bases whose band the scope gate never reads as a level: the posting states
#: nothing, or states a level we cannot place. The person's "include roles
#: whose level we can't place" switch decides them.
UNPLACED_BASES = frozenset({LevelBasis.NONE, LevelBasis.UNMAPPED})
UNPLACED_BASIS_VALUES = tuple(sorted(basis.value for basis in UNPLACED_BASES))


class RoleTrack(str, Enum):
    """Cross-cutting kind of role, orthogonal to family (domain) and band (level).

    A "Director of Data Science" is MANAGEMENT + data_science + director_plus; a
    "Distinguished Engineer" is TECHNICAL despite a director+ band. Derived from the
    title, not the seniority — see tracker/enrich/track.py.
    """

    MANAGEMENT = "management"  # people/org leadership: Eng Manager, Director, VP, Head, Chief
    PRODUCT_PROGRAM = "product_program"  # Product / Program / Project management
    TECHNICAL = "technical"  # individual-contributor / hands-on (incl. Distinguished/Fellow)
    BUSINESS_CUSTOMER = "business_customer"  # sales, marketing, customer, and corporate IC roles


class WorkplaceType(str, Enum):
    ONSITE = "onsite"
    REMOTE = "remote"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobDescriptionSection:
    """Provider-neutral, display-ready section from a source job posting."""

    key: str
    title: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "title": self.title, "content": self.content}


@dataclass(frozen=True)
class SourceDisclosedComp:
    """Structured pay stated by the source API, pre-AI."""

    base_min: int | None = None
    base_max: int | None = None
    currency: str | None = None
    pay_basis: str = "unclear"  # base|total|unclear
    pay_period: str = "unclear"  # year|month|hour|unclear (pay_period.PayPeriod)
    source_snippet: str | None = None
    confidence: str = "high"
    bonus_pct: float | None = None


class AccessSurface(str, Enum):
    """HOW a fact was acquired, in five access classes (A-E).

    Recorded because "the API says so" is a different warrant from "we parsed
    the careers page", and a fact archive that cannot tell them apart cannot be
    audited later. Parsing description HTML delivered INSIDE an API response is
    content normalization, not a separate surface.
    """

    PUBLIC_API = "public_api"  # A: documented public retrieval API
    PUBLIC_FEED = "public_feed"  # B: structured public feed (sitemap, JSON-LD)
    UNDOCUMENTED_ENDPOINT = "undocumented_endpoint"  # C: careers frontend endpoint
    HTML = "html"  # D: HTML extraction
    BROWSER = "browser"  # E: browser automation


class BoardRegion(str, Enum):
    """Which regional deployment of a multi-region ATS holds a tenant's board.

    Lever runs separate data-residency deployments — `api.lever.co` and
    `api.eu.lever.co` — with **separate tenant namespaces**. A global tenant
    asked for on the EU host answers 404 `{"ok":false,"error":"Document not
    found"}`, byte-identical to what either host answers for a site name that
    does not exist anywhere.

    That identical 404 is why the region has to be carried rather than assumed.
    A wrong region is indistinguishable from a wrong board token, so an EU
    tenant fetched from the global host does not fail with a message naming the
    problem: the listing is invalidated, `scanned` is 0, and every run reads
    `failed` with no hint of the cause. Recognising an EU URL while fetching the
    global host would manufacture exactly that.

    `None` on a company means "this family has one deployment" (Greenhouse,
    Ashby, Google), which is why the stored column is nullable rather than
    defaulting to `GLOBAL` — absent and global-by-choice are different records.
    """

    GLOBAL = "global"
    EU = "eu"


class ClosureBasis(str, Enum):
    """What evidence closed a posting — the claim behind `jobs.closed_at`.

    *Availability* is not *employer outcome*: RoleBand observes that a posting
    stopped being listed, which is not the same claim as the employer having
    filled or withdrawn the role. Boards legitimately unpublish and re-publish,
    so an unrecorded closure reason is a conclusion nobody can audit later.

    One member, because one closure path exists. `close_missing` is the only
    writer of `status="closed"` in the codebase and it runs only behind
    `scan_may_close` — uncapped, error-free, `list_complete` — so absence from a
    complete listing is the meaning of the function, not one basis among
    several. Members are added when a path is, not in anticipation; evidence of
    an employer outcome would be a separate column, not a value slipped into
    this one.

    NULL is not a member and never becomes one. On an open row it means the job
    has never closed; on a closed row it means unknown: closed before a basis
    was recorded. Such rows are NOT reconstructed: inferring the basis from the
    only code path is a claim about the code, not evidence about the closure.
    """

    ABSENT_FROM_COMPLETE_LISTING = "absent_from_complete_listing"


class Arrival(str, Enum):
    """How a role came to be stored: whether our first sighting of the posting
    says when it appeared (`jobs.arrival`, `db/arrival.py`).

    A sighting dates an appearance only when the company's board had been read
    whole before it. Before that, the board was already listing, and our first
    sighting is when we started looking.

    NULL means not yet classified, and readers take the sighting at its word.
    """

    #: First seen by this role's own creation, at a company read whole before.
    NEW = "new"
    #: First seen earlier by the inventory (out of scope then, or written by a
    #: later run), at a company read whole before that sighting.
    ALREADY_LISTED = "already_listed"
    #: First seen before the company had a whole read: no date of appearance.
    FIRST_READ = "first_read"


class RetrievalState(str, Enum):
    """Why a fact group is absent — four answers, never one.

    Collapsing these is how a failed optional request erases a disclosure the
    employer really made, and how a field the employer really REMOVED goes on
    being reported from a stale row. `absent_in_successful_response` is a fact
    about the employer; `retrieval_failed` is a fact about us.
    """

    NOT_REQUESTED = "not_requested"
    RETRIEVAL_FAILED = "retrieval_failed"
    ABSENT_IN_SUCCESSFUL_RESPONSE = "absent_in_successful_response"
    PRESENT = "present"


class EmploymentType(str, Enum):
    """Normalized alongside — never instead of — the source's own word."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERN = "intern"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceLocation:
    """One place a posting is open at, structured as far as the source states it.

    `label` is always the source's own string. Country/region/locality are only
    filled from fields the source declares as such — a country is never inferred
    from a label, and a two-letter string is not assumed to be an ISO code.
    """

    label: str
    country: str | None = None
    region: str | None = None
    locality: str | None = None
    is_primary: bool = False


@dataclass(frozen=True)
class CompComponent:
    """One disclosed money component, in the source's own units.

    `interval` keeps `year`/`month`/`hour`/`one_time`/`percentage` apart because
    they are not convertible: an equity PERCENTAGE is not an equity amount, and
    an hourly figure is not an annual base. Nothing here is summed or converted.
    """

    type: str  # the source's component word, lowercased (salary, equity, bonus…)
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    interval: str | None = None
    source_text: str | None = None


@dataclass(frozen=True)
class CompTier:
    """One complete offer tier as the employer stated it.

    Employers publish several — by location, by level, by track. Tiers are kept
    whole and never merged: an invented min/max across tiers is a number no
    employer ever offered.
    """

    title: str | None = None
    components: list[CompComponent] = field(default_factory=list)
    additional_information: str | None = None


@dataclass(frozen=True)
class CompensationFacts:
    """The tiers plus the story of how we came to have (or not have) them.

    `observed_at` is when THESE tiers were read. When it is older than the
    facts' own `observed_at`, they were carried forward from an earlier
    observation because the current run had no better evidence — which is the
    difference between "still true as far as we know" and "true right now".
    """

    tiers: list[CompTier] = field(default_factory=list)
    state: RetrievalState = RetrievalState.NOT_REQUESTED
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ApplicationFormFacts:
    """How much a posting's application form asks, in COUNTS only.

    The allowlist below keeps a vendor's application questions out of storage;
    that still holds. What is kept is the size of the ask a candidate triages
    by: questions the employer added beyond the standard contact and resume
    block that must be answered, how many of those need a written answer, how
    many are a choice, and whether it demands expected pay. The wording of a
    question never enters storage. Same four retrieval states as pay.

    The form is read only from the posting page, so this group is also that
    read's cool-down record. `failed_at` is when the last read failed, kept
    beside an earlier answer the failure must not erase; `permanent` says the
    source answered that the page does not exist (404, 410), which is asked
    again only once the posting's text changes, never on a timer.
    """

    state: RetrievalState = RetrievalState.NOT_REQUESTED
    required: int = 0
    written: int = 0
    choices: int = 0
    asks_expected_pay: bool = False
    observed_at: datetime | None = None
    failed_at: datetime | None = None
    permanent: bool = False

    @classmethod
    def failed(cls, at: datetime, *, permanent: bool = False) -> ApplicationFormFacts:
        return cls(
            state=RetrievalState.RETRIEVAL_FAILED, observed_at=at, failed_at=at, permanent=permanent
        )


@dataclass(frozen=True)
class PostingPage:
    """What one read of a posting's own page adds to its listing facts."""

    application_form: ApplicationFormFacts
    compensation: CompensationFacts


#: What reading a posting page because someone opened it came to,
#: one spelling for the read, the route and its response model: `read`,
#: `already_read` (answered from storage, no request), `not_available` (no page
#: this posting may be read for) or `failed` (this read, or one recent enough
#: that the next is not yet due, failed).
PostingPageOutcome = Literal["read", "already_read", "not_available", "failed"]


#: Bumped only when the persisted shape changes in a way a reader must branch on.
SOURCE_FACTS_SCHEMA_VERSION = 1


@dataclass
class SourceJobFacts:
    """Facts the source stated about a posting, kept beside our own identity.

    This is an ALLOWLIST, not an archive: every field below is named, so a
    vendor payload's application questions, compliance metadata and internal
    flags cannot ride along into storage. It never replaces `req_id` /
    `dedupe_key`, and its dates never overwrite `first_seen` / `last_seen` —
    those are OUR observations and the source's are the source's.
    """

    provider: str
    access_surface: AccessSurface
    tenant_identity: str  # the board/tenant token, opaque and case-preserved
    posting_id: str  # the id of THIS advertisement
    source_job_id: str | None = None  # the underlying job, when the source names one
    requisition_label: str | None = None  # the employer's own requisition string
    first_published_at: datetime | None = None
    last_published_at: datetime | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    application_deadline: datetime | None = None
    employment_type_raw: str | None = None
    employment_type_normalized: EmploymentType = EmploymentType.UNKNOWN
    locations: list[SourceLocation] = field(default_factory=list)
    compensation: CompensationFacts = field(default_factory=CompensationFacts)
    application_form: ApplicationFormFacts = field(default_factory=ApplicationFormFacts)
    observed_at: datetime | None = None
    schema_version: int = SOURCE_FACTS_SCHEMA_VERSION

    def as_dict(self) -> dict:
        """Explicit serializer: the persisted shape is a contract, not a dump.

        `asdict()` would follow whatever the dataclass happens to hold today,
        so a field added for one adapter's convenience would silently enter
        every historical record.
        """
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "access_surface": self.access_surface.value,
            "tenant_identity": self.tenant_identity,
            "posting_id": self.posting_id,
            "source_job_id": self.source_job_id,
            "requisition_label": self.requisition_label,
            "first_published_at": _iso(self.first_published_at),
            "last_published_at": _iso(self.last_published_at),
            "source_created_at": _iso(self.source_created_at),
            "source_updated_at": _iso(self.source_updated_at),
            "application_deadline": _iso(self.application_deadline),
            "employment_type_raw": self.employment_type_raw,
            "employment_type_normalized": self.employment_type_normalized.value,
            "locations": [
                {
                    "label": loc.label,
                    "country": loc.country,
                    "region": loc.region,
                    "locality": loc.locality,
                    "is_primary": loc.is_primary,
                }
                for loc in self.locations
            ],
            "compensation": {
                "state": self.compensation.state.value,
                "observed_at": _iso(self.compensation.observed_at),
                "tiers": [
                    {
                        "title": tier.title,
                        "additional_information": tier.additional_information,
                        "components": [
                            {
                                "type": part.type,
                                "min": part.min,
                                "max": part.max,
                                "currency": part.currency,
                                "interval": part.interval,
                                "source_text": part.source_text,
                            }
                            for part in tier.components
                        ],
                    }
                    for tier in self.compensation.tiers
                ],
            },
            "application_form": {
                "state": self.application_form.state.value,
                "observed_at": _iso(self.application_form.observed_at),
                "required": self.application_form.required,
                "written": self.application_form.written,
                "choices": self.application_form.choices,
                "asks_expected_pay": self.application_form.asks_expected_pay,
                "failed_at": _iso(self.application_form.failed_at),
                "permanent": self.application_form.permanent,
            },
            "observed_at": _iso(self.observed_at),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SourceJobFacts:
        """Read a stored record back. The archive must have exactly one reader.

        Without it the first consumer invents its own parsing of history, and
        the round trip nothing checks is where the shape quietly drifts.
        """
        comp = data.get("compensation") or {}
        form = data.get("application_form") or {}
        return cls(
            provider=data["provider"],
            access_surface=AccessSurface(data["access_surface"]),
            tenant_identity=data["tenant_identity"],
            posting_id=data["posting_id"],
            source_job_id=data.get("source_job_id"),
            requisition_label=data.get("requisition_label"),
            first_published_at=_parse_iso(data.get("first_published_at")),
            last_published_at=_parse_iso(data.get("last_published_at")),
            source_created_at=_parse_iso(data.get("source_created_at")),
            source_updated_at=_parse_iso(data.get("source_updated_at")),
            application_deadline=_parse_iso(data.get("application_deadline")),
            employment_type_raw=data.get("employment_type_raw"),
            employment_type_normalized=EmploymentType(
                data.get("employment_type_normalized") or EmploymentType.UNKNOWN.value
            ),
            locations=[
                SourceLocation(
                    label=loc["label"],
                    country=loc.get("country"),
                    region=loc.get("region"),
                    locality=loc.get("locality"),
                    is_primary=bool(loc.get("is_primary")),
                )
                for loc in data.get("locations") or []
            ],
            compensation=CompensationFacts(
                tiers=[
                    CompTier(
                        title=tier.get("title"),
                        additional_information=tier.get("additional_information"),
                        components=[
                            CompComponent(
                                type=part["type"],
                                min=part.get("min"),
                                max=part.get("max"),
                                currency=part.get("currency"),
                                interval=part.get("interval"),
                                source_text=part.get("source_text"),
                            )
                            for part in tier.get("components") or []
                        ],
                    )
                    for tier in comp.get("tiers") or []
                ],
                state=RetrievalState(comp.get("state") or RetrievalState.NOT_REQUESTED.value),
                observed_at=_parse_iso(comp.get("observed_at")),
            ),
            # Absent in older records: not requested.
            application_form=ApplicationFormFacts(
                state=RetrievalState(form.get("state") or RetrievalState.NOT_REQUESTED.value),
                required=int(form.get("required") or 0),
                written=int(form.get("written") or 0),
                choices=int(form.get("choices") or 0),
                asks_expected_pay=bool(form.get("asks_expected_pay")),
                observed_at=_parse_iso(form.get("observed_at")),
                failed_at=_parse_iso(form.get("failed_at")),
                permanent=bool(form.get("permanent")),
            ),
            observed_at=_parse_iso(data.get("observed_at")),
            schema_version=int(data.get("schema_version") or SOURCE_FACTS_SCHEMA_VERSION),
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


#: A source's answer about a fact group, as opposed to a fact about us.
_ANSWERED = frozenset({RetrievalState.PRESENT, RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE})

#: The groups a run may not have ASKED for, and which stored states a run that
#: did not answer for one carries forward. Both answers, for both groups: "the
#: employer stated none" is as much a reading as a disclosure, and resetting it
#: to `not_requested` loses when it was read (a page read that found no pay,
#: wiped by the next listing scan). The form also carries a failure:
#: only the posting page states it, so a failed read is the page's cool-down
#: record, and a listing that never asks for the form has no news to replace
#: it with (reset, every scan would make the page owed again).
_CARRIED_FORWARD: dict[str, frozenset[RetrievalState]] = {
    "compensation": _ANSWERED,
    "application_form": _ANSWERED | {RetrievalState.RETRIEVAL_FAILED},
}


#: The source's birth dates for a posting. Unlike a disclosure they are never
#: withdrawn: a posting published on 1 July was published on 1 July. Some
#: sources state `first_published_at` only on the detail page, which a rescan
#: inside `description_refresh_days` skips, so a run that states none keeps
#: the stored date. A run that states
#: one wins, earlier or later: the earliest across re-dates is kept on
#: `jobs.first_posted_at`, and these facts say what the source
#: states now.
_BIRTH_DATES = ("first_published_at", "source_created_at")


def merge_source_facts(stored: dict | None, incoming: SourceJobFacts) -> dict:
    """The current facts for a posting, given what this run actually saw.

    Everything the run observed wins outright — a source that stops stating a
    field has changed its mind, and perpetuating the old value would report a
    disclosure the employer withdrew.

    The groups in `_CARRIED_FORWARD` are the exceptions, because they are the
    groups we may not have ASKED for. The rule, per group: when this run did not
    request it, or asked and failed, and what we stored is one of that group's
    carried states, the stored group is kept whole with the timestamp of the
    observation that read it. When this run answered (present, or absent in a
    successful response), its answer wins. One rule, kept here alone: a
    failed optional detail request must not erase a confirmed disclosure, and a
    successful response that omits the field must not be papered over with a
    stale one. A listing scan never asks for the form or for the structured pay
    only the posting page states, so without this every scan would erase what
    the posting page told us, including that it states no pay.

    `_BIRTH_DATES` are the other exception: a date this run did not state is
    kept, because no source withdraws when a posting was published.
    """
    merged = incoming.as_dict()
    if not isinstance(stored, dict):
        return merged
    for name in _BIRTH_DATES:
        if merged.get(name) is None and stored.get(name) is not None:
            merged[name] = stored[name]
    for group, carried in _CARRIED_FORWARD.items():
        answer: CompensationFacts | ApplicationFormFacts = getattr(incoming, group)
        if answer.state in _ANSWERED:
            continue
        previous = stored.get(group) or {}
        if previous.get("state") in {state.value for state in carried}:
            merged[group] = previous
    return merged


def dedupe_key_for(company: str, req_id: str) -> str:
    """The identity of one posting within one company's listing.

    A free function as well as a method because a row can name a requisition
    without being turnable into a `RawJob` — a listing that serves an id and
    nothing else still proves that req is present, and the closure pass needs
    that key in the same shape it compares everything else in.
    """
    return f"{company}:{req_id}"


@dataclass
class RawJob:
    """A single posting as observed from a company source, pre-enrichment."""

    company: str  # company slug, e.g. "google"
    req_id: str  # stable per-company requisition id
    title: str
    url: str
    locations: list[str] = field(default_factory=list)
    department: str | None = None
    team: str | None = None
    description_html: str | None = None
    description_sections: list[JobDescriptionSection] = field(default_factory=list)
    source_disclosed_comp: SourceDisclosedComp | None = None
    # The detail read looked where this source prints pay, read the page in
    # full and found `source_disclosed_comp` there or nowhere: None then means
    # the posting states no pay (`connectors.detail.structure_job_detail`).
    pay_looked: bool = False
    # Ephemeral source object consumed by the company detail connector after a
    # posting passes filters. Never persisted; avoids parsing every list result.
    detail_payload: object | None = field(default=None, repr=False)
    # False when this is only list/search fallback content. Persistence may use
    # it for a new job but must not overwrite a complete detail already stored.
    description_complete: bool = True
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN
    posted_at: datetime | None = None
    raw_level: str | None = None  # any level string the source exposes
    # What the SOURCE said about this posting, kept beside — never instead of —
    # our own identity and history. None means this adapter maps no facts yet,
    # which must leave anything already stored alone rather than erase it.
    source_facts: SourceJobFacts | None = None
    # The row we already hold for this posting, when collection holds one: its
    # earliest employer date and our first sight of it. Read only for the year
    # a pay grade is looked up in (`level_date`); never written.
    held_first_posted_at: datetime | None = None
    held_first_seen: datetime | None = None

    def dedupe_key(self) -> str:
        return dedupe_key_for(self.company, self.req_id)


#: The source our own pay estimate is stored under (`job_comp_estimate.source`):
#: a plugin's is stored under its id.
OUR_ESTIMATE_SOURCE = "roleband"


@dataclass
class EnrichedJob:
    """A `RawJob` after enrichment — what the pipeline persists."""

    raw: RawJob
    level_band: LevelBand
    level_confidence: LevelConfidence
    family: str | None  # family slug, or None if unclassified
    location_groups: list[str]  # matched location-group slugs
    track: RoleTrack = RoleTrack.TECHNICAL
    # None = not recorded (an older row); the gate reads its
    # band. Only NONE means "level not stated".
    level_basis: LevelBasis | None = None
    domains: list[str] = field(default_factory=list)  # matched domain slugs, primary first
    comp_low: int | None = None
    comp_high: int | None = None
    comp_median: int | None = None
    comp_currency: str = "USD"
    comp_provenance: str | None = None  # human-readable source note
    comp_sources: list[dict] = field(default_factory=list)  # per-provider detail
    # Per component and provenance; None = unknown.
    comp_base_low: int | None = None
    comp_base_median: int | None = None
    comp_base_high: int | None = None
    comp_component: str | None = None
    comp_provider: str | None = None
    comp_as_of: date | None = None
    # The reference fingerprint the resolver ran under; None = not estimated.
    comp_ref_fp: str | None = None
    #: Each source's estimate, side by side: source -> the estimate
    #: fields, its providers' `sources` and its `ref_fp`. Empty when estimates
    #: were deferred. `comp_*` above is the selected source's.
    estimates: dict[str, dict] = field(default_factory=dict)
    #: False when no resolver ran (a row read after its source's time bound):
    #: nothing was learned about pay, so the stored job keeps what it shows.
    estimated: bool = True
