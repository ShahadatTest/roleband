"""Followed companies RoleBand has not scanned in full lately.

Closure keeps no company health: a failed scan starts each posting's absence
count again, so nothing holds a company's postings that a person needs to
release. What a person can lose is coverage: a company they follow whose
careers page no scan has read in full for days. This report is built from scan
runs only, and answers per followed company:

- **When was it last read in full.** `last_full_scan_at` is the newest
  reconcile that read the whole board: `ok`, `empty`, or `lossy` (a rounding
  error of rows lost; incomplete for closure, but the page was read).
  None when no scan ever has; the clock then runs from when the binding was
  made, so a company followed today is not stale.
- **Is that too long.** `stale` once `stale_after`
  (`Settings.coverage_stale_after_days`, passed in by the caller) has passed.
- **Why.** Read off the newest reconcile since then that did not read the
  board in full (`cause_of`): unreachable, empty, read only in part, or gone
  from its address.
- **Is the board gone.** A newest reconcile whose board root answered 404 or
  410 (`outcome.board_missing`) flags the company however fresh, like an empty
  board: the company moved its careers page, and no number of days changes
  that.
- **Is the board empty.** A board whose newest reconcile
  proved it lists nothing is flagged however fresh, with `empty_since` (the
  first run of the current empty streak) and `listed_before` (the rows the
  newest scan that read any found).
- **Is it scanned automatically.** Some providers are scanned only when the
  user asks, a walled company only with consent, and nothing behind a paused
  or denied provider; `automatic` says so, from a predicate
  the caller passes plus the provider's state, and the Coverage notification
  rings only for those.

Scope: the ACTIVE binding of each FOLLOWED company (`is_followed`), chosen as
`db.binding.get_active_binding` chooses it. An unfollowed company is scanned by
nobody and costs nobody anything. `unattempted` runs are no evidence.

Like `schedule_status.py`, nothing here reads the clock or the settings.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, get_args

from sqlalchemy import DateTime, and_, case, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.models import (
    Job,
    ProviderPressureState,
    ScrapeSourceRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.db.queries.companies import is_followed

#: Outcomes of a scan that read the whole board. `lossy` counts: it lost under
#: 1% of rows, so the page was read even though closure cannot use it.
FULL_SCAN_OUTCOMES: Final = (
    SourceOutcome.OK.value,
    SourceOutcome.EMPTY.value,
    SourceOutcome.LOSSY.value,
)

#: One notice instead of one per company once at least this many followed,
#: automatically scanned companies are stale together AND they are at least
#: half of them: many companies going stale at once is our scheduler being
#: down, not each source on its own.
OUTAGE_MIN = 5

#: `/api/status` is polled; the counts cover every flagged company and the
#: list carries the ones most worth reading first.
MAX_ITEMS = 50

#: Why a stale company was not read in full, declared once. The API schema
#: serves this alias and the notification copy keys on the constants.
Cause = Literal["empty_listing", "board_missing", "unreachable", "unreadable", "partial", "unknown"]

CAUSE_EMPTY_LISTING: Final[Cause] = "empty_listing"
#: The board's own address answered that no such board exists: the company
#: moved its careers page or stopped using this one.
CAUSE_BOARD_MISSING: Final[Cause] = "board_missing"
CAUSE_UNREACHABLE: Final[Cause] = "unreachable"
#: The page answered and nothing could be read from it: a maintenance page, a
#: payload missing its array.
CAUSE_UNREADABLE: Final[Cause] = "unreadable"
#: Read, but not in full: our own bound, a lost page, a degraded walk.
CAUSE_PARTIAL: Final[Cause] = "partial"
#: No scan since the last full one left any record.
CAUSE_UNKNOWN: Final[Cause] = "unknown"
CAUSES: Final[tuple[Cause, ...]] = get_args(Cause)

#: The outcome a board proven empty records.
EMPTY_OUTCOME: Final = SourceOutcome.EMPTY.value

#: Provider states the scheduler never dispatches (`schedule_status.
#: BLOCKED_PROVIDER_STATES`, asserted equal in the tests): a company behind one
#: is not scanned automatically, however long it goes.
EXCLUDED_PROVIDER_STATES: Final = ("policy_denied", "paused")

#: Whether a followed company is scanned without the user asking:
#: `(provider, company, consent fingerprint) -> bool`.
Automatic = Callable[[str, str, str | None], bool]


@dataclass(frozen=True)
class FollowedBinding:
    """One followed company's active binding and what its runs say.

    `binding_id` is the notification's identity (`notifications/coverage.py`)
    and is not served: a binding is not a thing the user can act on."""

    binding_id: int
    company_slug: str
    display: str
    provider: str
    connector_kind: str
    automatic: bool
    created_at: datetime
    last_full_scan_at: datetime | None
    last_attempted_at: datetime | None
    held_open: int
    cause_outcome: str | None = None
    cause_at: datetime | None = None
    cause_scanned: int | None = None
    cause_errors: Sequence[str] = ()
    cause_drift: Sequence[Mapping] = ()
    #: First run of the current empty streak; None unless the newest reconcile
    #: proved the board empty.
    empty_since: datetime | None = None
    #: Rows the newest scan that read any found; None if none ever did.
    listed_before: int | None = None


def _error_status(row: Mapping) -> bool:
    """A drift alert recording an HTTP answer outside 2xx: the page did not answer."""
    status = row.get("status") if isinstance(row, Mapping) else None
    return isinstance(status, int) and not 200 <= status < 300


def cause_of(
    outcome: str | None, scanned: int | None, errors: Sequence[str], drift: Sequence[Mapping]
) -> Cause:
    """Why the newest scan since the last full one did not read the board.

    An error, or a page that answered 404, 429 or 503 (recorded as drift, e.g.
    a "non-200 search"), is unreachable. A page that answered and gave no rows
    is unreadable (a "non-JSON jobs response", a body with no `jobs` array).
    Anything else read part of the board: a lost page, our own time or page
    ceiling, a host that slept. Calling those
    unreachable would say the company's page is down when it answered.
    """
    if outcome is None:
        return CAUSE_UNKNOWN
    if outcome == EMPTY_OUTCOME:
        return CAUSE_EMPTY_LISTING
    if outcome == SourceOutcome.FAILED.value and any(
        isinstance(row, Mapping) and row.get("board_missing") for row in drift
    ):
        return CAUSE_BOARD_MISSING
    if errors or any(_error_status(row) for row in drift):
        return CAUSE_UNREACHABLE
    if outcome == SourceOutcome.FAILED.value or not scanned:
        return CAUSE_UNREADABLE
    return CAUSE_PARTIAL


def _message(errors: Sequence[str], drift: Sequence[Mapping]) -> str | None:
    """The first thing the source run recorded about itself, verbatim."""
    for error in errors:
        if error:
            return str(error)
    for row in drift:
        message = row.get("message") if isinstance(row, Mapping) else None
        if message:
            return str(message)
    return None


def _days(now: datetime, since: datetime | None) -> float | None:
    return round((now - since).total_seconds() / 86400.0, 1) if since is not None else None


def is_stale(row: FollowedBinding, now: datetime, *, stale_after: timedelta) -> bool:
    """No full scan for `stale_after`, counted from the binding's creation when
    there never was one. `stale_after` is `Settings.coverage_stale_after_days`,
    read by the caller: this projection reads no settings and no clock of its
    own."""
    return now - (row.last_full_scan_at or row.created_at) >= stale_after


def attention_item(row: FollowedBinding, now: datetime, *, stale_after: timedelta) -> dict:
    empty = row.empty_since is not None
    return {
        "company": row.company_slug,
        "display": row.display,
        "provider": row.provider,
        "connector_kind": row.connector_kind,
        "automatic": row.automatic,
        "last_full_scan_at": row.last_full_scan_at,
        "days_since_full_scan": _days(now, row.last_full_scan_at or row.created_at),
        "never_scanned": row.last_full_scan_at is None,
        "stale": is_stale(row, now, stale_after=stale_after),
        "last_attempted_at": row.last_attempted_at,
        "held_open": row.held_open,
        "cause": CAUSE_EMPTY_LISTING if empty else cause_of(
            row.cause_outcome, row.cause_scanned, row.cause_errors, row.cause_drift
        ),
        "cause_outcome": row.cause_outcome,
        "cause_at": row.cause_at,
        "cause_message": _message(row.cause_errors, row.cause_drift),
        "empty_since": row.empty_since,
        "days_empty": _days(now, row.empty_since),
        "listed_before": row.listed_before,
    }


def flagged(item: dict) -> bool:
    return bool(item["stale"]) or item["empty_since"] is not None or item["cause"] == CAUSE_BOARD_MISSING


def _burst(followed: Iterable[tuple[str, bool, bool]]) -> bool:
    """From (provider, automatic, missing) per followed company: whether one
    provider answers "no such board" for `OUTAGE_MIN` or more of the boards it
    serves automatically, and for at least half of them, as `is_outage` reads
    an outage. A provider that fails answers so for most of its boards at once;
    companies that move do so a few at a time, spread over providers, and a
    count over the whole roster would grow past any fixed number with it."""
    automatic: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    for provider, is_automatic, is_missing in followed:
        if is_automatic:
            automatic[provider] += 1
            missing[provider] += is_missing
    return any(n >= OUTAGE_MIN and 2 * n >= automatic[p] for p, n in missing.items())


def missing_burst(items: Iterable[dict]) -> bool:
    """Whether so many of one provider's boards went missing together (`_burst`)
    that it is more likely the provider's answer than each company moving: then
    none rings at once, and each waits to go stale like any unreachable page,
    where the outage notice gathers them. `items` is every followed company's
    item, not only the flagged ones: the share needs the whole roster."""
    return _burst((i["provider"], i["automatic"], i["cause"] == CAUSE_BOARD_MISSING) for i in items)


def boards_gone(rows: Iterable[FollowedBinding]) -> frozenset[int]:
    """The bindings whose careers page is gone from its address, the company's
    fact: Coverage tells it, so the status's freshness leaves them
    out rather than telling it again, stale, for as long as nobody acts.

    Not during a `missing_burst`: that many of one provider's boards missing
    together is more likely the provider's answer than each company moving, and
    then each keeps the badge stale like any unreachable page."""
    rows = list(rows)
    gone = {
        row.binding_id for row in rows
        if row.empty_since is None
        and cause_of(row.cause_outcome, row.cause_scanned, row.cause_errors, row.cause_drift) == CAUSE_BOARD_MISSING
    }
    if _burst((row.provider, row.automatic, row.binding_id in gone) for row in rows):
        return frozenset()
    return frozenset(gone)


def is_outage(items: Iterable[dict], automatic_followed: int) -> bool:
    """Whether the stale, automatically scanned companies are an outage of ours
    rather than each company's own trouble: `OUTAGE_MIN` or more, and at least
    half of every followed company RoleBand scans on its own."""
    stale = sum(1 for i in items if i["automatic"] and i["stale"] and i["empty_since"] is None)
    return stale >= OUTAGE_MIN and 2 * stale >= automatic_followed


def binding_attention(
    rows: Iterable[FollowedBinding],
    now: datetime,
    *,
    stale_after: timedelta,
    max_items: int = MAX_ITEMS,
) -> dict:
    """The report: counts over every followed company, the flagged ones listed.

    Listed first: the automatically scanned (the bell rings for these), then
    the longest without a full scan, then by name so the order is stable.
    """
    rows = list(rows)
    automatic = sum(1 for r in rows if r.automatic)
    items = [
        i for i in (attention_item(r, now, stale_after=stale_after) for r in rows) if flagged(i)
    ]
    items.sort(key=lambda i: (
        not i["automatic"], -(i["days_since_full_scan"] or 0.0), i["company"],
    ))
    return {
        "followed": len(rows),
        "automatic": automatic,
        "flagged": len(items),
        "stale": sum(i["stale"] for i in items),
        "empty": sum(i["empty_since"] is not None for i in items),
        "outage": is_outage(items, automatic),
        "held_open": sum(i["held_open"] for i in items),
        "items": items[:max_items],
    }


#: Older than any run: the gap bound of a binding never scanned in full.
_BEFORE_ANY_RUN: Final = datetime(1970, 1, 1, tzinfo=UTC)


async def followed_bindings(session: AsyncSession, *, automatic: Automatic) -> list[FollowedBinding]:
    """Every followed company's ACTIVE binding with what its runs say, in one
    query, ordered by company."""
    # `get_active_binding`'s choice, per company: not retired, a stable binding
    # over any other, then the newest. Aliased so the subquery ranks every
    # binding rather than correlating to the outer row.
    ranked = aliased(SourceBinding)
    active = (
        select(ranked.id)
        .where(ranked.status != "retired")
        .distinct(ranked.company_slug)
        .order_by(ranked.company_slug, (ranked.status == "stable").desc(), ranked.id.desc())
    )

    def reconciles(run):
        return (
            run.binding_id == SourceBinding.id,
            run.scan_mode == "reconcile",
            # A deferred company left no evidence.
            run.outcome != SourceOutcome.UNATTEMPTED.value,
        )

    full, attempt, cause_run, cause_full, newest, other, streak, read = (
        aliased(ScrapeSourceRun) for _ in range(8)
    )
    last_full = (
        select(func.max(full.finished_at))
        .where(*reconciles(full), full.outcome.in_(FULL_SCAN_OUTCOMES))
        .scalar_subquery()
    )
    last_attempt = select(func.max(attempt.started_at)).where(*reconciles(attempt)).scalar_subquery()
    # The gap: runs that finished after the binding's last full scan, which
    # is exactly "no full scan finished at or after it". One bound per
    # binding, correlated to it explicitly (the lateral's own select has no
    # `source_bindings` in its FROM, so auto-correlation would read every
    # binding's runs), and one comparison, so the (binding_id, finished_at)
    # index starts the scan at the bound. A NOT EXISTS anti-join of every
    # non-full run against every full scan of its binding costs far more as
    # runs accumulate (`scripts.bench_status_cost` measures it).
    # A binding with no full scan has every run in the gap.
    full_before = (
        select(func.max(cause_full.finished_at))
        .where(
            cause_full.binding_id == SourceBinding.id,
            cause_full.scan_mode == "reconcile",
            cause_full.outcome.in_(FULL_SCAN_OUTCOMES),
        )
        .correlate(SourceBinding)
        .scalar_subquery()
    )
    cause = (
        select(
            cause_run.outcome.label("outcome"),
            cause_run.started_at.label("started_at"),
            cause_run.scanned.label("scanned"),
            cause_run.errors.label("errors"),
            cause_run.drift.label("drift"),
        )
        .where(
            *reconciles(cause_run),
            cause_run.outcome.not_in(FULL_SCAN_OUTCOMES),
            cause_run.finished_at > func.coalesce(full_before, literal(_BEFORE_ANY_RUN, DateTime(timezone=True))),
        )
        .order_by(cause_run.started_at.desc(), cause_run.id.desc())
        .limit(1)
        .lateral("cause")
    )
    latest = (
        select(newest.outcome.label("outcome"))
        .where(*reconciles(newest))
        .order_by(newest.started_at.desc(), newest.id.desc())
        .limit(1)
        .lateral("latest")
    )
    # The empty streak: empty reconciles since the newest one that was not.
    # Correlated to the streak run's own binding: nested two levels down,
    # `reconciles(other)` would correlate to nothing and read every binding's
    # runs, so any other company's later scan would end the streak (and
    # `empty_since` read NULL).
    last_not_empty = (
        select(func.max(other.started_at))
        .where(
            other.binding_id == streak.binding_id,
            other.scan_mode == "reconcile",
            other.outcome != SourceOutcome.UNATTEMPTED.value,
            other.outcome != EMPTY_OUTCOME,
        )
        .scalar_subquery()
    )
    empty_since = (
        select(func.min(streak.started_at))
        .where(
            *reconciles(streak),
            streak.outcome == EMPTY_OUTCOME,
            or_(last_not_empty.is_(None), streak.started_at > last_not_empty),
        )
        .scalar_subquery()
    )
    listed_before = (
        select(read.scanned)
        .where(read.binding_id == SourceBinding.id, read.scanned > 0)
        .order_by(read.started_at.desc(), read.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    is_empty = func.coalesce(latest.c.outcome == EMPTY_OUTCOME, False)
    held_open = (
        select(func.count())
        .select_from(Job)
        .where(Job.company == SourceBinding.company_slug, Job.status == "open")
        .scalar_subquery()
    )
    stmt = (
        select(
            SourceBinding.id,
            SourceBinding.company_slug,
            TrackedCompany.display,
            TrackedCompany.adapter,
            SourceBinding.connector_kind,
            TrackedCompany.consent_fingerprint,
            SourceBinding.created_at,
            last_full,
            last_attempt,
            held_open,
            cause.c.outcome,
            cause.c.started_at,
            cause.c.scanned,
            cause.c.errors,
            cause.c.drift,
            case((is_empty, empty_since), else_=None),
            listed_before,
            ProviderPressureState.state,
        )
        .select_from(SourceBinding)
        .join(TrackedCompany, and_(TrackedCompany.slug == SourceBinding.company_slug, is_followed()))
        .outerjoin(ProviderPressureState, ProviderPressureState.pressure_key == TrackedCompany.adapter)
        .outerjoin(cause, true())
        .outerjoin(latest, true())
        .where(SourceBinding.id.in_(active))
        .order_by(SourceBinding.company_slug)
    )
    return [
        FollowedBinding(
            binding_id=r[0],
            company_slug=r[1],
            display=r[2] or r[1],
            provider=r[3] or "",
            connector_kind=r[4],
            automatic=(
                bool(r[3])
                and r[17] not in EXCLUDED_PROVIDER_STATES
                and automatic(r[3], r[1], r[5])
            ),
            created_at=r[6],
            last_full_scan_at=r[7],
            last_attempted_at=r[8],
            held_open=int(r[9] or 0),
            cause_outcome=r[10],
            cause_at=r[11],
            cause_scanned=r[12],
            cause_errors=list(r[13] or []),
            cause_drift=list(r[14] or []),
            empty_since=r[15],
            listed_before=r[16],
        )
        for r in (await session.execute(stmt)).all()
    ]
