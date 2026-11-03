"""Response contracts for repost lineage and twins.

The stack a posting belongs to, the twins it is related to, the two review
queues, a human verdict on either kind of proposal, the local model's advice on
one, and the manual twin link and rejection writes.

Every shape here is built by our code, so every model forbids unknown keys: a
key the serializer adds without its model is a 500 a test catches, never output
that silently fails to arrive. One exception: a twin proposal's stored
`description_diff` is served exactly as stored, because a typed model would
re-emit its keys in declaration order instead of JSONB's.

**A shape whose keys differ by branch is a union, never optional keys.** A
posting in no lineage answers three keys and a stack answers eight, so
`GET /api/jobs/{id}/lineage` answers their union as a named `RootModel`. A
duplicate proposal and a twin proposal differ by key set too
(`title_similarity`, `description_diff`), so they are two models, each carrying
its `proposal_kind`. The review queues answer a full list or, with
`detail=false`, a summary list whose postings are list rows, again as a
named union.

**A diff names only what moved.** `build_member_diff` writes a key per field that
changed and nothing else, so `PostingDiff` declares each as absent-or-a-change
and the routes that send one use `response_model_exclude_unset=True`: an
unchanged field stays absent instead of arriving as `null`.

Literal types only for vocabularies the handler itself writes in the request: a
verdict's resulting `status`, the fixed `status`/`decision` of the manual
writes, and `proposal_kind`. Link `status`, `confidence`, `relation` and
`method` are read back from tables no CHECK constraint bounds, and `decision` is
read from evidence JSONB, so they stay `str`.

Fields are declared in the order the handlers build them, so every response
keeps its key order byte for byte.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, RootModel
from pydantic.json_schema import SkipJsonSchema

from tracker.api.schemas.base import Built
from tracker.api.schemas.jobs import JobDetailRow, JobRow
from tracker.api.schemas.local_models import LocalModelMetrics, LocalModelProvider
from tracker.api.schemas.text_class import text
from tracker.intelligence.duplicate_review import DuplicateAssessment

#: The status a verdict leaves on the link it was given for.
VerdictStatus = Literal["confirmed", "rejected", "pending"]


# --------------------------------------------------------------------------- #
# Proposals and what moved between two postings
# --------------------------------------------------------------------------- #


class ReasonSaid(Built):
    """One reason a detector paired two postings, as a code the dashboard
    words (`lineage/reasons.py` lists the codes and their parameters)."""

    code: Literal[
        "same_title", "titles_alike", "descriptions_alike", "listed_at_once",
        "same_department", "department_unknown", "passages_differ",
    ] = Field(json_schema_extra=text("code"))
    params: dict[str, int]


class DuplicateProposal(Built):
    """A `job_lineage_link` row: the newer posting may be the older one again."""

    proposal_kind: Literal["duplicate"]
    id: int
    job_id: int
    prior_job_id: int
    relation: str
    method: str
    confidence: str
    status: str
    score: float | None
    gap_days: int | None
    #: The detector's own English, for diagnostics; a reader is told `said`.
    reasons: list[str] = Field(json_schema_extra=text("diagnostic"))
    said: list[ReasonSaid]
    decision: str | None
    decision_changes: int
    reviewed_at: datetime | None


class TwinProposal(Built):
    """A `job_twin_link` row in the duplicate queue's shape: `job_id` is the pair's
    higher id, `prior_job_id` the lower."""

    proposal_kind: Literal["twin"]
    id: int
    job_id: int
    prior_job_id: int
    relation: Literal["twin"]
    method: str
    confidence: str
    status: str
    score: float | None
    gap_days: None
    title_similarity: float | None
    reasons: list[str] = Field(json_schema_extra=text("diagnostic"))
    said: list[ReasonSaid]
    decision: str | None
    decision_changes: int
    reviewed_at: datetime | None
    description_diff: dict[str, Any] | None


class TextChange(Built):
    from_: str = Field(alias="from")
    to: str


class OptionalTextChange(Built):
    from_: str | None = Field(alias="from")
    to: str | None


class BandChange(Built):
    """A stated base band as `[min, max]`, either end unknown; null when none was stated."""

    from_: list[int | None] | None = Field(alias="from")
    to: list[int | None] | None
    currency: str | None


class LocationChange(Built):
    added: list[str]
    removed: list[str]


class AmountChange(Built):
    from_: int | None = Field(alias="from")
    to: int | None
    currency: str | None


class PostingDiff(Built):
    """`build_member_diff`: one key per field that differs, absent otherwise."""

    title: TextChange | SkipJsonSchema[None] = None
    level_band: TextChange | SkipJsonSchema[None] = None
    disclosed_band: BandChange | SkipJsonSchema[None] = None
    pay_basis: OptionalTextChange | SkipJsonSchema[None] = None
    locations: LocationChange | SkipJsonSchema[None] = None
    comp_median: AmountChange | SkipJsonSchema[None] = None


class DescriptionPassage(Built):
    section_key: str
    section_title: str = Field(json_schema_extra=text("content"))
    text: str = Field(json_schema_extra=text("content"))


class DescriptionDiff(Built):
    """`compare_descriptions(...).evidence()` for the pair as it stands now."""

    comparable: bool
    equivalent: bool
    shared_count: int
    left_only_count: int
    right_only_count: int
    difference_ratio: float
    token_similarity: float
    left_only: list[DescriptionPassage]
    right_only: list[DescriptionPassage]


# --------------------------------------------------------------------------- #
# GET /api/jobs/{job_id}/lineage
# --------------------------------------------------------------------------- #


class LineageMember(Built):
    """One posting of the role, in stack order. `link` is its inbound proposal, if
    any; `diff_vs_prev` is set only when an effective link ties it to the posting
    before it."""

    seq: int | None
    role: str | None
    job: JobDetailRow
    link: DuplicateProposal | None
    diff_vs_prev: PostingDiff | None


class LineageStack(Built):
    """A posting that belongs to a lineage: the whole stack, oldest first."""

    lineage_id: int
    root_job_id: int
    company: str
    size: int
    open_members: int
    first_seen: datetime
    last_seen: datetime
    members: list[LineageMember]


class NoLineage(Built):
    """A posting that stands alone. `members` is always empty."""

    lineage_id: None
    size: Literal[1]
    members: list[LineageMember]


class JobLineageResponse(RootModel[LineageStack | NoLineage]):
    """`GET /api/jobs/{job_id}/lineage`: the stack, or a standalone posting."""


# --------------------------------------------------------------------------- #
# Review queues and verdicts
# --------------------------------------------------------------------------- #


class DuplicateReviewItem(Built):
    link: DuplicateProposal
    job: JobDetailRow
    prior: JobDetailRow
    diff: PostingDiff


class TwinReviewItem(Built):
    link: TwinProposal
    job: JobDetailRow
    prior: JobDetailRow
    diff: PostingDiff
    description_diff: DescriptionDiff


class DuplicateReviewList(Built):
    """`GET /api/lineage/review`. `total` counts the lens; `items` skips a proposal
    whose posting is gone."""

    total: int
    limit: int
    offset: int
    items: list[DuplicateReviewItem]


class TwinReviewList(Built):
    """`GET /api/twins/review`, in the duplicate queue's shape."""

    total: int
    limit: int
    offset: int
    items: list[TwinReviewItem]


class DuplicateReviewSummaryItem(Built):
    """A duplicate review item in the summary form (`detail=false`): each
    posting as a list row, without its description or stated-pay object."""

    link: DuplicateProposal
    job: JobRow
    prior: JobRow
    diff: PostingDiff


class TwinReviewSummaryItem(Built):
    """A twin review item in the summary form: list rows, and no description
    diff, so nothing compares the two descriptions."""

    link: TwinProposal
    job: JobRow
    prior: JobRow
    diff: PostingDiff


class DuplicateReviewSummaryList(Built):
    """`GET /api/lineage/review?detail=false`, as `DuplicateReviewList` counts and pages it."""

    total: int
    limit: int
    offset: int
    items: list[DuplicateReviewSummaryItem]


class TwinReviewSummaryList(Built):
    """`GET /api/twins/review?detail=false`, as `TwinReviewList` counts and pages it."""

    total: int
    limit: int
    offset: int
    items: list[TwinReviewSummaryItem]


class DuplicateReviewResponse(RootModel[DuplicateReviewList | DuplicateReviewSummaryList]):
    """`GET /api/lineage/review`: full items, or the summary form with `detail=false`."""


class TwinReviewResponse(RootModel[TwinReviewList | TwinReviewSummaryList]):
    """`GET /api/twins/review`: full items, or the summary form with `detail=false`."""


class KeptDecision(Built):
    """A row a withdrawn verdict had changed and a person has decided again
    since: Undo leaves it as decided. `link` names its kind."""

    link: Literal["twin", "duplicate"]
    id: int


class DuplicateVerdictResult(Built):
    """`POST /api/lineage/links/{link_id}/review`. `twin_link_id` names the twin a
    `twin` verdict confirmed; `lineages` counts the rebuilt projection; `kept`
    names what withdrawing the previous verdict left alone, empty when nothing."""

    id: int
    status: VerdictStatus
    reviewed_at: datetime | None
    lineages: int
    decision: str | None
    twin_link_id: int | None
    kept: list[KeptDecision]


class TwinVerdictResult(Built):
    """`POST /api/twins/links/{link_id}/review`. `kept` as on a duplicate verdict."""

    id: int
    status: VerdictStatus
    decision: str | None
    reviewed_at: datetime | None
    lineages: int
    kept: list[KeptDecision]


class TwinLinkCreated(Built):
    """`POST /api/twins/links`: a human-confirmed twin, new or re-confirmed."""

    id: int
    status: Literal["confirmed"]
    decision: Literal["twin"]


# --------------------------------------------------------------------------- #
# GET /api/jobs/{job_id}/twins
# --------------------------------------------------------------------------- #


class TwinMember(Built):
    """The asked-for posting first, then its confirmed twin component by id. `link`
    is set only for a direct twin."""

    job: JobDetailRow
    direct: bool
    link: TwinProposal | None


class JobTwinsResponse(Built):
    job_id: int
    size: int
    direct_count: int
    members: list[TwinMember]


# --------------------------------------------------------------------------- #
# The local model's advice
# --------------------------------------------------------------------------- #


class DuplicateAssessmentBody(DuplicateAssessment):
    """The validated verdict `assess_duplicate` returns, with its own bounds."""

    model_config = ConfigDict(extra="forbid")


class RelationshipAssessment(Built):
    """`POST /api/{lineage,twins}/links/{link_id}/analyze`: advisory only; the
    human verdict is untouched."""

    profile_id: str
    provider: LocalModelProvider
    model: str
    prompt_version: str
    assessment: DuplicateAssessmentBody
    metrics: LocalModelMetrics


# --------------------------------------------------------------------------- #
# Manual lineage writes
# --------------------------------------------------------------------------- #


class LineageLinkRejected(Built):
    """`DELETE /api/lineage/links/{link_id}`: a soft delete, kept as a negative label."""

    id: int
    status: Literal["rejected"]
    lineages: int


# --------------------------------------------------------------------------- #
# Place sets: one role listed once per place
# --------------------------------------------------------------------------- #


class PlaceSetStatedPay(Built):
    """The pay band a posting states, as the posting states it: a set's
    postings may state different bands for different places."""

    low: int | None
    high: int | None
    currency: str | None = Field(json_schema_extra=text("code"))
    period: str | None = Field(json_schema_extra=text("code"))


class PlaceSetMember(Built):
    """A posting of the set, earliest first, the asked-for one included."""

    job: JobRow
    is_this: bool
    #: `place`: the first posting of the role at its place; `relisted`: the
    #: role listed again at a place an earlier member holds.
    relation: Literal["place", "relisted"]
    #: At the asked-for posting's own place (never true of that posting).
    same_place: bool
    #: The base band the posting states; null when it states none.
    stated_pay: PlaceSetStatedPay | None


class PlaceSetInfo(Built):
    id: int
    size: int
    #: Every place the role is listed in, each once, earliest posting first.
    places: list[str]
    #: The employer's own requisition label when every member carries the same one.
    employer_label: str | None = Field(json_schema_extra=text("content"))
    rule_version: str
    members: list[PlaceSetMember]


class JobPlaceSetResponse(Built):
    """`GET /api/jobs/{id}/place-set`. `place_set` is null for a posting in no
    set; `rejected` says a person split this posting out ("Different roles")."""

    job_id: int
    place_set: PlaceSetInfo | None
    rejected: bool
    rejected_at: datetime | None
