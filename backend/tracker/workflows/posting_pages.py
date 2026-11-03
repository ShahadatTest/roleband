"""Read the posting page where the listing left something out.

A listing can carry every posting's text but not its application form or its
structured pay. Those live on the posting's own page, one request each. Most
postings already state pay in their text, so the page is read in the
background only where it adds what the text lacks:

    open, on the radar, the text pass found no band, a company we collect
    (active, enabled, allowed by the source policy, a page-reading connector),
    a posting id, and the page not read since the text last changed nor
    failed within `posting_page_retry_hours` (nor answered that it does not
    exist since the text last changed).

That is the queue, as a query, drained a bounded
number per run and best effort per posting, like the description backfill.
Every other posting's form is read when someone opens it, under the
same company and posting gate minus the radar and pay conditions.

What a read stores: the form as COUNTS in `source_facts.application_form`, the
tiers in `source_facts.compensation` (each with a period from the one rule),
and, when there is exactly one tier with a known period and the text
stated no band, the posting's band in `disclosed_*`, the same columns the text
pass fills. A band read from the page carries no snippet: the page states
numbers in a field, not a sentence, and a snippet is shown as the employer's
own words (`band_from_page`). A read that moves a band an earlier read stated
records the move, as every writer of a band does (`_record_move`).

Transactions: no read holds one across a request. The rows to read are
selected, the transaction ends, the page is fetched, and the row is loaded
again under a row lock and written, one commit per posting, so a scan that
commits in between keeps its facts and no pooled connection idles in a
transaction while a source answers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.connectors import (
    ADAPTER_REGISTRY,
    BaseAdapter,
    BreakerPool,
    RateLimiterPool,
    build_adapter,
)
from tracker.db.models import Job, JobLifecycleEvent, TrackedCompany
from tracker.db.pay_band import BAND_COLUMNS, BandChange, band_snapshot
from tracker.pay_disclosure import basis_from_label, settle_band
from tracker.platform.util import parse_datetime
from tracker.schema import (
    ApplicationFormFacts,
    CompensationFacts,
    PostingPage,
    PostingPageOutcome,
    RetrievalState,
    SourceJobFacts,
)
from tracker.source_policy import collection_access

logger = logging.getLogger(__name__)

#: The sources whose posting page states a form and structured pay: every
#: connector that overrides `BaseAdapter.read_posting_page`. Derived, so a
#: connector joins the queue by implementing the read, not by being listed.
PAGE_PROVIDERS: tuple[str, ...] = tuple(
    sorted(
        name
        for name, cls in ADAPTER_REGISTRY.items()
        if cls.read_posting_page is not BaseAdapter.read_posting_page
    )
)

_READ_STATES = (
    RetrievalState.PRESENT.value,
    RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE.value,
)
_FAILED = RetrievalState.RETRIEVAL_FAILED

#: Retries for a read someone opened a posting for, against the
#: settings' 4 for a run. One retry absorbs a single transient 5xx for one
#: second of backoff; the full budget would spend many seconds and several
#: requests on a 503 while a person waits. A read that still fails is retried after the cool-down, not on
#: the next open, so a person never pays for a source's bad minute twice.
ON_OPEN_RETRIES = 1

#: A breaker is run-scoped by design (`platform/breaker.py`): a circuit that
#: opened as blocked never probes again for the rest of its run. The API
#: process has no runs, so its breakers start over after this long, which is
#: when a source that refused us is asked again.
_OPEN_BREAKER_WINDOW_SECONDS = 900.0

# --------------------------------------------------------------------------- #
# Which pages may be read
# --------------------------------------------------------------------------- #


def page_company(row: TrackedCompany | None) -> bool:
    """May this company's posting pages be read now?

    The collection gate, as the scans apply it: an active, enabled company
    (what `get_active_targets` collects), a page-reading connector, and the
    source policy's one decision (`collection_access`), which refuses
    a walled company without the user's consent and a denied provider
    always. A user-directed source would have to stay out of the
    background drain; none reads posting pages, and a test fails the day one
    does (`test_no_page_provider_is_user_directed`), since reading the register
    here would make this module a second enforcement path beside
    `source_policy` (`test_source_review`).
    """
    if row is None or row.status != "active" or not row.enabled:
        return False
    if row.adapter not in PAGE_PROVIDERS:
        return False
    if collection_access(row.adapter, company=row.slug, consent=row.consent_fingerprint).denied:
        return False
    return True


def _retry_cutoff(now: datetime | None) -> datetime:
    hours = get_settings().posting_page_retry_hours
    return (now or datetime.now(UTC)) - timedelta(hours=hours)


def _failed_at(form: dict) -> datetime | None:
    """When the last read failed. An older failure is the
    failed state alone, dated by its `observed_at`."""
    at = parse_datetime(form.get("failed_at"))
    if at is None and form.get("state") == _FAILED.value:
        at = parse_datetime(form.get("observed_at"))
    return at


def page_owed(job: Job, *, now: datetime | None = None) -> bool:
    """The posting's half of "read its page": open, a page provider's facts
    with a posting id, not cooling down after a failed read, and the form
    never read, read before the text last changed, or last failed
    (`_readable_row` in SQL).

    A failure cools down whether or not an earlier answer was kept beside it:
    with one kept, the row is still owed by its changed text, and
    without the cool-down it would take a drain slot every run. A page the source
    said does not exist cools down until the text changes again."""
    facts = job.source_facts or {}
    if job.status != "open" or facts.get("provider") not in PAGE_PROVIDERS:
        return False
    if not facts.get("posting_id"):
        return False
    form = facts.get("application_form") or {}
    failed_at = _failed_at(form)
    if failed_at is not None:
        if form.get("permanent"):
            if not (job.content_changed_at and job.content_changed_at > failed_at):
                return False
        elif failed_at > _retry_cutoff(now):
            return False
    state = form.get("state")
    if state not in _READ_STATES:
        return True
    at = parse_datetime(form.get("observed_at"))
    return bool(at and job.content_changed_at and at < job.content_changed_at)


def _failed_at_sql():
    """`_failed_at` in SQL: when the last read failed, or NULL."""
    form = Job.source_facts["application_form"]
    at = cast(form["observed_at"].astext, DateTime(timezone=True))
    return func.coalesce(
        cast(form["failed_at"].astext, DateTime(timezone=True)),
        case((form["state"].astext == _FAILED.value, at)),
    )


def _readable_row(cutoff: datetime):
    """`page_owed` in SQL, with the company row's connector the posting's."""
    form = Job.source_facts["application_form"]
    state = form["state"].astext
    at = cast(form["observed_at"].astext, DateTime(timezone=True))
    failed_at = _failed_at_sql()
    permanent = func.coalesce(form["permanent"].as_boolean(), False)
    return and_(
        Job.status == "open",
        TrackedCompany.slug == Job.company,
        Job.source_facts["provider"].astext == TrackedCompany.adapter,
        func.coalesce(Job.source_facts["posting_id"].astext, "") != "",
        or_(
            failed_at.is_(None),
            and_(permanent.is_(False), failed_at <= cutoff),
            and_(permanent.is_(True), Job.content_changed_at > failed_at),
        ),
        or_(
            state.is_(None),
            state.notin_(_READ_STATES),
            and_(
                Job.content_changed_at.isnot(None),
                at < Job.content_changed_at,
            ),
        ),
    )


def owed_page_clause(companies: Collection[str], *, now: datetime | None = None):
    """The background queue: radar postings whose text states no pay and whose
    page is owed, at the companies `page_company` admits (their slugs). Names
    `tracked_company`, so a select using it reads both tables."""
    return and_(
        Job.company.in_(list(companies)),
        _readable_row(_retry_cutoff(now)),
        Job.in_scope.is_(True),
        Job.structured_at.isnot(None),
        Job.disclosed_base_min.is_(None),
        Job.disclosed_base_max.is_(None),
    )


async def readable_on_open(session: AsyncSession, job: Job) -> bool:
    """Should opening this posting read its page?

    Any posting `page_owed` at a company `page_company` admits for a read the
    user asked for. Wider than the background queue (any pay, any scope):
    someone is looking at this posting now, so its form is worth one request
    whatever its pay. The posting's own gate goes first, so a posting that is
    not owed costs the detail read no query.
    """
    if not page_owed(job):
        return False
    return await _open_target(session, job) is not None


# --------------------------------------------------------------------------- #
# What a read stores
# --------------------------------------------------------------------------- #


def stated_band(compensation: CompensationFacts) -> dict | None:
    """The `disclosed_*` values one structured tier states, or None.

    Only a single tier with a known period is a band: several tiers are
    several offers (by zone, by level) and are never merged into an invented
    span, and an `unclear` period is not shown as a number with a unit.
    """
    if compensation.state is not RetrievalState.PRESENT or len(compensation.tiers) != 1:
        return None
    (tier,) = compensation.tiers
    if len(tier.components) != 1:
        return None
    (part,) = tier.components
    if part.interval not in ("year", "month", "hour") or part.min is None or part.max is None:
        return None
    title = (tier.title or "").strip()
    # The text parser's own markers and conditional guard: one reading of the
    # same words whether they sit in the posting or on its page.
    basis = basis_from_label(title).value
    currency = part.currency or "USD"
    return {
        # Whole units by truncation, the text pass's rounding (`pay_disclosure.
        # _explicit_amount`): "$15.65" is 15 whichever of the two read it.
        "disclosed_base_min": int(part.min),
        "disclosed_base_max": int(part.max),
        "disclosed_currency": currency,
        "disclosed_pay_basis": basis,
        "disclosed_pay_period": part.interval,
        # No snippet: the page states numbers in a field, and a snippet is
        # shown as the employer's own words. Writing one would be our text.
        "disclosed_snippet": None,
        "disclosed_confidence": "high",
    }


def page_band(job: Job) -> dict | None:
    """The band this row's posting page states, as `disclosed_*` columns.

    The one derivation both writers use: `apply_page` after a read, and the
    text pass (`extract_disclosed_comp`) when the text states no band, so a
    re-extraction restores a band only the page stated instead of erasing it.
    """
    facts = job.source_facts or {}
    if facts.get("provider") not in PAGE_PROVIDERS:
        return None
    return stated_band(SourceJobFacts.from_dict(facts).compensation)


def band_from_page(job: Job) -> bool:
    """Does the row's stated band come from the posting page's pay field?
    Recorded by whoever writes the band (`jobs.disclosed_source`)."""
    has_band = job.disclosed_base_min is not None or job.disclosed_base_max is not None
    return has_band and job.disclosed_source == "page"


def _write_band(job: Job, band: dict | None) -> BandChange:
    before = band_snapshot(job)
    for column in BAND_COLUMNS:
        setattr(job, column, (band or {}).get(column))
    job.disclosed_source = "page" if band is not None else None
    # The label beside a tier ("Annual Salary") cannot say what a range defined
    # per kind of role means; the posting and the role's family can. A bonus
    # target the posting states beside the same figures is read against that.
    settled = settle_band(
        job.disclosed_pay_basis, job.description_text, job.family, job.title,
        [job.disclosed_base_min, job.disclosed_base_max],
    )
    job.disclosed_pay_basis, job.disclosed_bonus_pct = settled.pay_basis, settled.bonus_pct
    return BandChange(before=before, after=band_snapshot(job))


def apply_page(job: Job, page: PostingPage) -> BandChange | None:
    """Write one read into the row. Returns what the read did to the band, or
    None when the band is another source's, which a page never replaces.

    A band the text stated is never replaced. A band an earlier page read
    stated follows the page: a later read's tier replaces it, and a read that
    finds no single tier removes it.
    """
    stored = job.source_facts or {}
    facts = SourceJobFacts.from_dict(stored)
    # A failed page read is a fact about us: it must not erase a form or pay
    # tiers an earlier read found (the merge rule, `merge_source_facts`). The
    # failure is still recorded beside the kept form, so it cools down.
    failure = page.application_form
    if failure.state is _FAILED and facts.application_form.state.value in _READ_STATES:
        facts.application_form = replace(
            facts.application_form,
            failed_at=failure.failed_at or failure.observed_at,
            permanent=failure.permanent,
        )
    else:
        facts.application_form = page.application_form
    if page.compensation.state is not _FAILED:
        facts.compensation = page.compensation
    job.source_facts = facts.as_dict()
    had_band = job.disclosed_base_min is not None or job.disclosed_base_max is not None
    if had_band and not band_from_page(job):
        return None
    return _write_band(job, page_band(job))


def _record_move(session: AsyncSession, job: Job, change: BandChange | None) -> None:
    """Record a read that moved a page band, as the connector and the text pass
    record theirs. Only a band an earlier page read stated can move, and the
    background queue reads only postings with no band, so a move comes from a
    read on open. That read belongs to no run: the move reaches the posting's
    history, and not the feed, which reads one run's events."""
    if change is not None and change.moved and change.had_band:
        session.add(JobLifecycleEvent(
            job_id=job.id, event_type="changed", detail={"disclosed_base": change.event_detail()},
        ))


def _failed_page(now: datetime) -> PostingPage:
    return PostingPage(
        application_form=ApplicationFormFacts.failed(now),
        compensation=CompensationFacts(state=_FAILED, observed_at=now),
    )


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Target:
    """What building the adapter needs, copied off the company row so no read
    touches the ORM (or its transaction) across a request."""

    slug: str
    adapter: str
    board_token: str | None
    board_region: str | None
    consent: str | None

    @classmethod
    def of(cls, row: TrackedCompany) -> _Target:
        assert row.adapter is not None  # `page_company` admitted it
        return cls(row.slug, row.adapter, row.board_token, row.board_region, row.consent_fingerprint)


async def _read_page(
    target: _Target,
    posting_id: str,
    *,
    limiter_pool: RateLimiterPool,
    breaker_pool: BreakerPool,
    max_retries: int | None,
) -> PostingPage | None:
    """One paced, breaker-guarded read. Never raises: an exception of ours
    (a transport error after retries, an open circuit, an unreadable body) is
    a failed retrieval, stored like a failed response so the cool-down holds."""
    try:
        adapter = build_adapter(
            target.slug,
            target.adapter,
            target.board_token,
            board_region=target.board_region,
            limiter_pool=limiter_pool,
            breaker_pool=breaker_pool,
            # The adapter re-checks the policy on entry: it must see the
            # consent the gate saw.
            consent=target.consent,
        )
        adapter.max_retries = max_retries
        async with adapter:
            return await adapter.read_posting_page(posting_id)
    except Exception as exc:  # noqa: BLE001 - one posting's read is best effort
        logger.warning("posting page read failed for %s %s: %s", target.slug, posting_id, exc)
        return _failed_page(datetime.now(UTC))


async def _open_target(session: AsyncSession, job: Job) -> _Target | None:
    row = await session.get(TrackedCompany, job.company)
    if row is None or not page_company(row):
        return None
    if (job.source_facts or {}).get("provider") != row.adapter:
        return None
    return _Target.of(row)


def _stored_outcome(job: Job) -> PostingPageOutcome:
    """What an open that sends no request answers, from the stored form."""
    state = ((job.source_facts or {}).get("application_form") or {}).get("state")
    if state in _READ_STATES:
        return "already_read"
    if state == _FAILED.value:
        return "failed"
    return "not_available"


class OpenPageReads:
    """Reading a posting's page because someone opened it, as one
    service per process: one pacer pool, one breaker pool, and one reader per
    posting, so two opens of one posting send one request.

    The process that serves opens owns the instance (the API, through
    `api.deps.get_page_reads`). This module holds no instance: a
    module global here would be process state inside the workflows layer,
    which tests would have to reach in and reset.
    """

    def __init__(self) -> None:
        # Built at the first open, after the API's startup enabled shared
        # pacing, so this pool paces against every provider-facing process's
        # use of the host, not against nothing.
        self.limiter_pool = RateLimiterPool()
        self._breaker_pool = BreakerPool()
        self._breakers_since = time.monotonic()
        self._locks: dict[int, asyncio.Lock] = {}
        self._holders: Counter[int] = Counter()

    def breaker_pool(self) -> BreakerPool:
        if time.monotonic() - self._breakers_since > _OPEN_BREAKER_WINDOW_SECONDS:
            self._breaker_pool, self._breakers_since = BreakerPool(), time.monotonic()
        return self._breaker_pool

    @asynccontextmanager
    async def _one_reader(self, job_id: int) -> AsyncIterator[None]:
        lock = self._locks.setdefault(job_id, asyncio.Lock())
        self._holders[job_id] += 1
        try:
            async with lock:
                yield
        finally:
            self._holders[job_id] -= 1
            if not self._holders[job_id]:
                del self._holders[job_id]
                self._locks.pop(job_id, None)

    async def read_one(
        self, session: AsyncSession, job_id: int
    ) -> tuple[PostingPageOutcome, dict | None] | None:
        """Read one posting's page because someone opened it.

        Returns None for an unknown posting, else what happened and the row's
        `source_facts` afterwards. A concurrent open of the same posting waits
        for this one and answers from storage. Commits its own write, and ends
        the detail read's transaction before the request.
        """
        async with self._one_reader(job_id):
            job = await session.get(Job, job_id, populate_existing=True)
            if job is None:
                return None
            target = await _open_target(session, job) if page_owed(job) else None
            facts = job.source_facts or {}
            # Nothing is written above: end the transaction, so no connection
            # sits idle in one while the source answers.
            await session.commit()
            if target is None:
                return _stored_outcome(job), facts
            page = await _read_page(
                target,
                str(facts["posting_id"]),
                limiter_pool=self.limiter_pool,
                breaker_pool=self.breaker_pool(),
                max_retries=ON_OPEN_RETRIES,
            )
            if page is None:
                return "not_available", facts
            # Loaded again under a row lock: a scan may have committed new
            # listing facts while we waited, and `apply_page` merges into what
            # is there now.
            job = await session.get(Job, job_id, with_for_update=True, populate_existing=True)
            if job is None:
                await session.rollback()
                return None
            _record_move(session, job, apply_page(job, page))
            await session.commit()
            outcome: PostingPageOutcome = "failed" if page.application_form.state is _FAILED else "read"
            return outcome, job.source_facts


async def _page_targets(session: AsyncSession) -> dict[str, _Target]:
    rows = (
        await session.scalars(select(TrackedCompany).where(TrackedCompany.adapter.in_(PAGE_PROVIDERS)))
    ).all()
    return {row.slug: _Target.of(row) for row in rows if page_company(row)}


async def read_posting_pages(
    session: AsyncSession, *, limit: int, now: datetime | None = None
) -> dict[str, int]:
    """Drain up to `limit` owed posting pages, committing each. Never raises
    for one posting. `skipped` counts rows selected but not written: a
    connector with no page after all, or a row gone before its write."""
    counts = {"read": 0, "failed": 0, "pay_found": 0, "skipped": 0}
    if limit <= 0:
        return counts
    targets = await _page_targets(session)
    if not targets:
        return counts
    rows = (
        await session.execute(
            select(Job.id, Job.company, Job.source_facts["posting_id"].astext)
            .where(owed_page_clause(targets, now=now))
            # A page never tried goes first, then failures by oldest attempt:
            # the cool-down alone is not fairness. On drains further apart than
            # it, the newest pages failing with a 503 would cool down before
            # every selection and take the whole limit each time.
            .order_by(_failed_at_sql().asc().nulls_first(), Job.first_seen.desc())
            .limit(limit)
        )
    ).all()
    # Nothing is held across the requests below (see the module docstring).
    await session.commit()
    # One pacer and one breaker per host for the whole drain, as the
    # description backfill and the scans: a streak of failures on
    # one host stops the drain asking it instead of spending every posting's
    # retries on it.
    limiter_pool, breaker_pool = RateLimiterPool(), BreakerPool()
    for job_id, company, posting_id in rows:
        page = await _read_page(
            targets[company],
            posting_id,
            limiter_pool=limiter_pool,
            breaker_pool=breaker_pool,
            max_retries=None,
        )
        if page is None:
            counts["skipped"] += 1
            continue
        job = await session.get(Job, job_id, with_for_update=True, populate_existing=True)
        if job is None:
            counts["skipped"] += 1
            await session.rollback()
            continue
        counts["failed" if page.application_form.state is _FAILED else "read"] += 1
        change = apply_page(job, page)
        if change is not None and change.gained:
            counts["pay_found"] += 1
        _record_move(session, job, change)
        await session.commit()
    return counts
