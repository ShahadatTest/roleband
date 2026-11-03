"""Greenhouse public board API, one board per tenant.

    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Returns {"jobs": [...]} where each job carries HTML `content`, a `location.name`
free-text string, `departments`/`offices`, and `updated_at`/`first_published`.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from tracker.connectors.extract.payload import text_of
from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.connectors.sdk import Capabilities, FetchRequest
from tracker.levels.ladder import printed_field
from tracker.pay_period import decide_period, period_words, size_classes
from tracker.platform.util import clean_location, parse_datetime
from tracker.schema import (
    AccessSurface,
    ApplicationFormFacts,
    CompComponent,
    CompensationFacts,
    CompTier,
    PostingPage,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
    WorkplaceType,
)

# Company slug -> Greenhouse board token.
BOARD_TOKENS = {"anthropic": "anthropic"}
_TENANTS = TenantMap(BOARD_TOKENS)


#: Board root. `/jobs` is the listing the adapter fetches; the root itself
#: answers `{"name": ...}`, an identity claim the other public board families
#: do not make, so a 200 from the wrong tenant is detectable here.
_BOARD_ROOT = "https://boards-api.greenhouse.io/v1/boards/{token}"


#: A Greenhouse `location.name` that states a work arrangement, not a place
#: ("Hybrid", "Distributed", "In-Office"); such a posting carries its real
#: places in `offices`.
_ARRANGEMENTS = {
    "hybrid": WorkplaceType.HYBRID,
    "distributed": WorkplaceType.REMOTE,
    "remote": WorkplaceType.REMOTE,
    "in-office": WorkplaceType.ONSITE,
    "in office": WorkplaceType.ONSITE,
    "on-site": WorkplaceType.ONSITE,
    "onsite": WorkplaceType.ONSITE,
}


def printed_rung(job: dict, field: str | None) -> str | None:
    """The rung the employer prints in its public custom field `field`
    (`metadata`), or None. A field naming two rungs (Waymo
    ["5", "6"]) is kept whole, ascending and "/"-joined like a printed dual
    rung (`stated_level`), so the LOWER one bands it."""
    if not field:
        return None
    for item in job.get("metadata") or []:
        if not isinstance(item, dict) or item.get("name") != field:
            continue
        value = item.get("value")
        values = value if isinstance(value, list) else [value]
        codes = [str(v).strip() for v in values if v not in (None, "") and str(v).strip()]
        if not codes:
            return None
        return "/".join(sorted(dict.fromkeys(codes), key=lambda c: (re.sub(r"\D", "", c).zfill(4), c)))
    return None


def work_arrangement(name: object) -> WorkplaceType | None:
    """The arrangement a location string states, or None if it names anything
    else. "Distributed; Hybrid" and "Hybrid or Remote" are arrangements too: a
    remote option reads remote (those roles are remote-eligible), otherwise
    hybrid, otherwise on-site. "Remote - US" names a place and is None."""
    if not isinstance(name, str) or not name.strip():
        return None
    parts = [p.strip().lower() for p in re.split(r";|/|\bor\b|,", name) if p.strip()]
    kinds = [_ARRANGEMENTS.get(part) for part in parts]
    if not kinds or any(kind is None for kind in kinds):
        return None
    for preferred in (WorkplaceType.REMOTE, WorkplaceType.HYBRID):
        if preferred in kinds:
            return preferred
    return WorkplaceType.ONSITE


# --------------------------------------------------------------------------- #
# The posting page: `GET /v1/boards/{token}/jobs/{id}` with
# `questions=true` and `pay_transparency=true`. The listing carries neither, so
# this costs one request per posting and is asked only where it is worth it.
# --------------------------------------------------------------------------- #

#: Every Greenhouse form carries the same contact block under fixed field names
#: (`first_name`, `email`, `resume`, `cover_letter`, ...); a question the
#: EMPLOYER added is named `question_<id>`.
#: Structural, so no label wording decides what counts as "beyond the resume".
_EMPLOYER_QUESTION = "question_"
_CHOICE_TYPES = frozenset({"multi_value_single_select", "multi_value_multi_select"})
#: A field the applicant types into. Not only the text box: Figma's required
#: "Do you have experience managing direct reports? If yes, please elaborate in
#: 1-2 sentences" is a one-line `input_text`, and so is its "From where do you
#: intend to work?". Both are answers written for this employer.
_TYPED_TYPES = frozenset({"textarea", "input_text"})

#: The typed employer question that is pasted, not written: a link to a
#: profile the applicant already has (DoorDash's "LinkedIn Profile",
#: Coinbase's "Linkedin Profile URL"). Read from the label, like
#: the expected-pay question, because Greenhouse gives a link no type of its own.
_LINK_RE = re.compile(
    r"\blinked\s?in\b|\bgit\s?hub\b|\burl\b|\bwebsite\b|\bportfolio\b", re.IGNORECASE
)

#: The one thing read from a label: does the form demand expected pay? As in
#: "What are your salary expectations?", "What is your desired base salary?",
#: "What are your compensation requirements?".
_EXPECTED_PAY_RE = re.compile(
    r"\b(?:salary|compensation|pay)\s+(?:expectations?|requirements?)\b"
    r"|\bdesired\s+(?:annual\s+)?(?:base\s+)?(?:salary|compensation|pay)\b"
    r"|\bexpected\s+(?:salary|compensation|pay)\b",
    re.IGNORECASE,
)


def application_form(questions: object, observed_at: datetime) -> ApplicationFormFacts:
    """How much the form asks, as counts: required employer questions, and of
    those how many are a choice and how many need a written answer. Written is
    any typed answer (a text box or a one-line field) with no file upload
    alternative, except a link to a profile and the expected-pay question,
    which the row names on its own. The wording is not kept."""
    if not isinstance(questions, list):
        return ApplicationFormFacts(
            state=RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE, observed_at=observed_at
        )
    required = written = choices = 0
    asks_pay = False
    for question in questions:
        if not isinstance(question, dict) or not question.get("required"):
            continue
        fields = [f for f in question.get("fields") or [] if isinstance(f, dict)]
        if not any(str(f.get("name") or "").startswith(_EMPLOYER_QUESTION) for f in fields):
            continue
        types = {f.get("type") for f in fields}
        label = str(question.get("label") or "")
        asks_for_pay = bool(_EXPECTED_PAY_RE.search(label))
        required += 1
        if types and types <= _CHOICE_TYPES:
            choices += 1
        elif (
            types & _TYPED_TYPES
            and "input_file" not in types
            and not asks_for_pay
            and not _LINK_RE.search(label)
        ):
            written += 1
        asks_pay = asks_pay or asks_for_pay
    return ApplicationFormFacts(
        state=RetrievalState.PRESENT,
        required=required,
        written=written,
        choices=choices,
        asks_expected_pay=asks_pay,
        observed_at=observed_at,
    )


def pay_tiers(ranges: object, observed_at: datetime) -> CompensationFacts:
    """Greenhouse's structured pay, one tier per range, each with a period.

    The field carries an amount in cents and a free-text title, never a period:
    an hourly "$15.65" and an annual "$222,800" differ only by
    size and by the title's words. Both go through the one period rule
    as a structured field, so size may decide alone; a tier that is
    no pay at any size is dropped. Tiers are kept whole, never merged.
    """
    if not isinstance(ranges, list):
        return CompensationFacts(
            state=RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE, observed_at=observed_at
        )
    tiers: list[CompTier] = []
    for item in ranges:
        if not isinstance(item, dict):
            continue
        low, high = item.get("min_cents"), item.get("max_cents")
        low = low / 100 if isinstance(low, (int, float)) else None
        high = high / 100 if isinstance(high, (int, float)) else None
        currency = item.get("currency_type") if isinstance(item.get("currency_type"), str) else None
        title = text_of(item.get("title"))
        # The title's words, a day or a week included ("Daily rate" reads
        # `unclear`, never `hour` by size); size alone only with no word.
        period = decide_period(
            size_classes(low, high, currency), period_words(title or ""), structured=True
        )
        if period is None:
            continue
        tiers.append(CompTier(title=title, components=[CompComponent(
            type="pay", min=low, max=high, currency=currency, interval=period.value,
            source_text=title,
        )]))
    return CompensationFacts(
        tiers=tiers,
        state=RetrievalState.PRESENT if tiers else RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE,
        observed_at=observed_at,
    )


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"
    posted_date = "published"  # `first_published`; never `updated_at`
    board_probe = BoardProbe(
        jobs_url=f"{_BOARD_ROOT}/jobs",
        tenants=_TENANTS,
        identity_url=_BOARD_ROOT,
    )
    #: One buffered GET of a JSON board; no streaming, no
    #: render, no POST. Declaring the minimum is what makes negotiation useful.
    required_capabilities = Capabilities(
        stream=False, post=False, impersonate=False, render=False
    )

    def _board_token(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token)

    async def read_posting_page(self, posting_id: str) -> PostingPage | None:
        """One paced request for the posting's form and structured pay."""
        token = self._board_token()
        resp = await self.context.fetch(FetchRequest(
            url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{posting_id}",
            query={"questions": "true", "pay_transparency": "true"},
            source_key=self.company,
        ))
        now = datetime.now(UTC)
        if resp.status != 200:
            # A fact about us (or a posting gone since the scan), never a
            # statement that the employer asks nothing. A 404 or 410 is the
            # board saying the page does not exist: asking again on a timer
            # gets the same answer.
            return PostingPage(
                application_form=ApplicationFormFacts.failed(now, permanent=resp.status in (404, 410)),
                compensation=CompensationFacts(state=RetrievalState.RETRIEVAL_FAILED, observed_at=now),
            )
        data = resp.json()
        if not isinstance(data, dict):
            data = {}
        return PostingPage(
            application_form=application_form(data.get("questions"), now),
            compensation=pay_tiers(data.get("pay_input_ranges"), now),
        )

    async def fetch(self) -> AsyncIterator[RawJob]:
        # This connector reaches its source through the ConnectorContext instead
        # of `self.get`, so no httpx object appears in connector code.
        token = self._board_token()
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        resp = await self.context.fetch(
            FetchRequest(url=url, query={"content": "true"}, source_key=self.company)
        )
        if resp.status != 200:
            self.drift.board_missing("non-200 job list", status=resp.status)
            return
        data = resp.json()
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            self.drift.invalidate_listing("missing 'jobs' array in payload")
            return
        if not jobs:
            # An unknown token answers 404, so a present, empty array is the
            # board itself saying it lists nothing.
            self.drift.board_empty("jobs array present and empty")
            return

        for job in jobs:
            req_id = str(job.get("id") or job.get("internal_job_id") or "")
            title = job.get("title")
            if not req_id or not title:
                # One unusable row, not a broken listing — see `drop_record`.
                self.drift.drop_record(
                    "job missing id/title", keys=list(job.keys())[:8]
                )
                continue

            loc = job.get("location") or {}
            locations = [clean_location(loc.get("name"))] if loc.get("name") else []
            offices = job.get("offices") or []
            for office in offices:
                name = clean_location(office.get("name") or office.get("location"))
                if name and name not in locations:
                    locations.append(name)
            workplace = work_arrangement(loc.get("name"))
            if workplace is not None and len(locations) > 1:
                # The board's location field says HOW, and its offices say
                # WHERE: keep the arrangement out of the places.
                # Only when an office names a place — a posting left with no
                # place at all is invisible.
                locations = locations[1:]

            departments = job.get("departments") or []
            dept = departments[0].get("name") if departments else None

            yield RawJob(
                company=self.company,
                req_id=req_id,
                title=title,
                url=job.get("absolute_url") or "",
                locations=[loc for loc in locations if loc],
                department=dept,
                raw_level=printed_rung(job, printed_field(self.company)),
                description_html=job.get("content"),
                detail_payload=job,
                workplace_type=workplace or WorkplaceType.UNKNOWN,
                # `first_published` only: `updated_at` moves on every
                # body edit, and an update time is never a posting date. A job
                # without it is dated by our first sighting instead.
                posted_at=parse_datetime(job.get("first_published")),
                source_facts=self._facts(job, req_id, token, loc, offices),
            )

    def _facts(
        self, job: dict, req_id: str, token: str, primary: dict, offices: list
    ) -> SourceJobFacts:
        """Three Greenhouse identifiers, and only one of them is the posting.

        `id` is THIS advertisement, `internal_job_id` the underlying job, and
        `requisition_id` the employer's own label. They are not interchangeable:
        one internal job can carry several live postings. Rekeying to the
        internal id would collapse those into one row
        and take the favourites, observations and lineage of the rest with them,
        so `req_id` stays `id` and the others are recorded as evidence only.

        `first_published` and `updated_at` are BOTH kept, with their own
        meanings; `posted_at` reads `first_published` alone.
        """
        locations: list[SourceLocation] = []
        primary_name = clean_location(primary.get("name")) if primary else None
        if primary_name:
            locations.append(SourceLocation(label=primary_name, is_primary=True))
        for office in offices or []:
            name = clean_location(office.get("name") or office.get("location"))
            if name and all(name != known.label for known in locations):
                locations.append(SourceLocation(label=name))

        return SourceJobFacts(
            provider=self.name,
            access_surface=AccessSurface.PUBLIC_API,
            tenant_identity=token,
            posting_id=req_id,
            source_job_id=_identifier(job.get("internal_job_id")),
            requisition_label=_identifier(job.get("requisition_id")),
            first_published_at=parse_datetime(job.get("first_published")),
            source_updated_at=parse_datetime(job.get("updated_at")),
            application_deadline=parse_datetime(job.get("application_deadline")),
            locations=locations,
            # Pay lives behind `?pay_transparency=true` on the DETAIL route,
            # which the listing does not call. Not asking is its own answer
            # and must not read as "the employer disclosed nothing".
            compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
            observed_at=datetime.now(UTC),
        )


def _identifier(value: object) -> str | None:
    """An identifier as opaque text, never a number; 0 and "" name nothing,
    as they do for the posting's own `id` in `fetch`.

    A 0 kept as "0" would read as one employer job shared by every posting
    that carries it (`lineage.place_sets` compares these values across
    postings).
    """
    return text_of(value) if value != 0 else None
