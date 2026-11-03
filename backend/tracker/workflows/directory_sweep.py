"""The background scan of every other company RoleBand can scan.

Following the whole directory cannot mean a followed row per directory
company: the scheduler's daily capacity is far smaller than the directory, and
the register would become the list it exists not to be. So the set is ONE
setting, and this pass does the work behind it:

1. read each directory company's board, most-linked first, one paced lane per
   job site, side by side;
2. count the postings that fit what the user's radar looks for: the same
   `annotate` + `passes_filters` gate the pipeline applies, read through
   `workflows.scope_filter` so the two cannot drift;
3. a company with at least one is FOLLOWED (`source="directory-set"`), and from
   then on the scheduler collects it like any company the user follows.

It stores no postings and closes nothing: the pipeline remains the one writer of
`jobs`, and a followed company earns closure authority the usual way.
What it keeps is `directory_checks` (when each company was read and what was
found), which is what makes it resumable, what makes a company due again a day
later, and what the register's progress line counts.

Its own process and lock (`data/directory.lock`, the supervisor's `directory`
job, `python -m tracker.workflows.directory_sweep`),
never `daily.lock`: a pass holding the scheduler's lock would delay every scan
the user starts by its whole budget. One process runs passes back to back while
companies are due: the supervisor starts the next process at the first
ten-minute mark after this one EXITS, so one pass per process would leave the
scan idle most of the time.

Each lane runs at its host's pacer (`provider_pacing`), not at the board's
speed, so the slowest-paced job site sets how long a full circle takes.
Reading only the places the radar can keep shortens the boards that page
by place.

A read our host cuts (asleep, or no job site answering) is never the board's
verdict. A role found before the cut follows the company at once; a
read that found none leaves a `Cursor`, and a later pass of the same run
continues it from the place it held instead of from page one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_directory import (
    DIRECTORY_SOURCES,
    FOLLOWED_BY_NAME,
    FOLLOWED_WITH_SET,
    DirectoryCompany,
    directory,
)
from tracker.company_store import follow_with_set, set_followed_with_set
from tracker.config import get_settings
from tracker.connectors import ReadPosition, build_adapter
from tracker.connectors.recipes.outcome import SourceOutcome, classify_source_outcome
from tracker.db.models import DirectoryCheck, ScrapeRun, SyncScheduleState, TrackedCompany
from tracker.db.queries.runs import stale_run_where
from tracker.db.session import session_scope
from tracker.enrich.classify import location_slugs_for
from tracker.enrich.enricher import ScopeFilter, annotate, passes_filters, rule_excluded
from tracker.platform import power as host_power
from tracker.platform.breaker import BreakerPool, CircuitOpenError
from tracker.platform.clock import STALLED, SourceClock, SuspensionMonitor, bound_fired
from tracker.platform.http import RetryDeadlineExceeded
from tracker.platform.locks import AlreadyRunning, advisory_xact_lock, run_lock
from tracker.platform.paging import MAX_PAGES_HARD
from tracker.platform.paths import DATA_DIR, PACING_DIR
from tracker.platform.ratelimit import RateLimiterPool, enable_shared_pacing
from tracker.platform.util import clean_location
from tracker.profiles.seed import ensure_company_profile
from tracker.schema import dedupe_key_for
from tracker.settings_store import get_setting_dict, set_setting_dict
from tracker.source_policy import CollectionPolicyDenied, collection_access
from tracker.taxonomy.place_scope import place_admits
from tracker.workflows.collection_types import empty_stats, judge_listing
from tracker.workflows.outage import network_up
from tracker.workflows.scope_filter import load_scope_filter, scope_fingerprint

log = logging.getLogger(__name__)

#: `app_settings` key: {"following": bool, "since": iso | None, "stopped": [slugs],
#: "scope_key": the radar the last pass read with, "scope_since": iso | None,
#: when that radar replaced another}.
SETTING_KEY = "directory_follow"
#: Held from reading the follow setting to commit by both of its writers: the
#: switch (`set_follow`) and a check that follows a company (`_record`).
#: Without it a follow committed between the switch's read and its commit
#: would survive the unfollow.
FOLLOW_LOCK_KEY = 91242
def due_after() -> timedelta:
    """How long after its last check a directory company is read again
    (`Settings.directory_check_due_hours`: daily)."""
    return timedelta(hours=get_settings().directory_check_due_hours)
#: A board read is judged by progress, not by a clock: it may run as
#: long as requests keep completing. The stall bound
#: (`scraper_source_stall_seconds`, nothing completed for that long) says it is
#: broken; `scraper_source_budget_seconds` is only the backstop against a board
#: that trickles forever, set well above the slowest full read. A short fixed
#: ceiling would cut a big board on a slow connection every single day.
#:
#: Every query of a directory read may page to `MAX_PAGES_HARD`: a lower page
#: ceiling hides the tail of a big board's listing (on a board ordered by
#: city, the alphabetical tail of its cities).
class _AtTheHardMaximum(dict):
    """`page_budgets` that give every query the published page maximum."""

    def get(self, key, default=None):  # noqa: ARG002 - every key, one answer
        return MAX_PAGES_HARD

    def __bool__(self) -> bool:
        # Empty as a dict, yet present: the adapter reads `page_budgets or {}`,
        # and an empty mapping would quietly bring the 60-page seed back.
        return True




async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)

#: The collector's vocabulary (`SourceOutcome`), not a second taxonomy. `ok`
#: and `empty` are a read in full; `bounded`/`truncated` are pending (our
#: bounds), `failed`/`degraded`/`blocked` are the board's, `unattempted` is
#: policy. A site refusing US is none of these: its lane pauses.
#: `suspended` is a read our host cut, asleep or offline: stored
#: only for one that found a role before the cut, never the board's verdict.
OK, FAILED, REFUSED, BOUNDED, SUSPENDED = (
    SourceOutcome.OK.value, SourceOutcome.FAILED.value,
    SourceOutcome.UNATTEMPTED.value, SourceOutcome.BOUNDED.value, SourceOutcome.SUSPENDED.value,
)
#: Not `blocked`: a breaker that opens raises out of `check_company`, and its
#: lane decides, so no check carries that outcome.
_SOURCE_FAILURES = frozenset({FAILED, SourceOutcome.DEGRADED.value})
#: A read that did not finish: the board's failure, or our backstop. Before one
#: is recorded as the board's, the network is checked.
_UNFINISHED = _SOURCE_FAILURES | {BOUNDED}


# --- the follow setting ---------------------------------------------------------


async def read_follow(session: AsyncSession) -> dict:
    stored = await get_setting_dict(session, SETTING_KEY) or {}
    return {
        "following": bool(stored.get("following")),
        "since": stored.get("since"),
        "stopped": list(stored.get("stopped") or []),
        "scope_key": stored.get("scope_key"),
        "scope_since": stored.get("scope_since"),
    }


async def set_follow(session: AsyncSession, following: bool, now: datetime) -> dict:
    """Follow or unfollow the whole set, as one decision.

    Unfollowing stops every company the set brought in and remembers which, so
    following again restores exactly those: never a company the user switched
    off on its own, and never touching one they followed by name.

    Only those the directory still lists come back: a board the
    monthly rebuild dropped, or a reviewed exclusion removed
    (`discover_board_tokens.EXCLUDED_BOARDS`), stays unfollowed, its row and
    postings kept. The set is the directory; a board outside it is not the
    set's to follow.
    """
    await advisory_xact_lock(session, FOLLOW_LOCK_KEY)
    current = await read_follow(session)
    if following == current["following"]:
        return current
    if following:
        listed = directory()
        await set_followed_with_set(
            session, True, [slug for slug in current["stopped"] if slug in listed]
        )
        value = {"following": True, "since": now.isoformat(), "stopped": []}
    else:
        stopped = await set_followed_with_set(session, False)
        value = {"following": False, "since": None, "stopped": stopped}
    # The radar the checks were made with outlives a switch: following again
    # within a day still trusts checks made with the same radar.
    value |= {"scope_key": current["scope_key"], "scope_since": current["scope_since"]}
    await set_setting_dict(session, SETTING_KEY, value)
    return value


async def note_radar(session: AsyncSession, scope: ScopeFilter, now: datetime) -> datetime | None:
    """Record the radar this pass reads with; return when it took over.

    A check made with another radar answered another question: a company it
    found nothing at may have roles for this one. So when the radar differs
    from the last pass's, every check before `now` is stale and the companies
    are read again in rank order, the likeliest first. The first
    pass ever only records it: there is nothing older to distrust.
    """
    follow = await read_follow(session)
    key = scope_fingerprint(scope)
    since = follow["scope_since"]
    if follow["scope_key"] != key:
        if follow["scope_key"] is not None:
            since = now.isoformat()
        stored = await get_setting_dict(session, SETTING_KEY) or {}
        await set_setting_dict(session, SETTING_KEY, {**stored, "scope_key": key, "scope_since": since})
    return datetime.fromisoformat(since) if since else None


# --- what is due ------------------------------------------------------------------


def due_companies(
    companies: Iterable[DirectoryCompany],
    checked: Mapping[str, datetime],
    skip: set[str],
    now: datetime,
) -> list[DirectoryCompany]:
    """Companies to read now: never read first, in rank order; then the stalest.

    `skip` is every directory slug that already has a row: followed by name,
    brought in by the set, or switched off by the user. Those are the
    pipeline's or the user's now, never this pass's.
    """
    fresh: list[DirectoryCompany] = []
    stale: list[tuple[datetime, int, DirectoryCompany]] = []
    for company in companies:
        if company.slug in skip:
            continue
        last = checked.get(company.slug)
        if last is None:
            fresh.append(company)
        elif now - last >= due_after():
            stale.append((last, company.rank, company))
    fresh.sort(key=lambda company: company.rank)
    stale.sort(key=lambda item: (item[0], item[1]))
    return fresh + [company for _, _, company in stale]


# --- reading one company ------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    slug: str
    outcome: str
    scanned: int
    roles_for_you: int
    error: str | None = None
    #: Postings left unread at places the radar cannot keep (`wanted_place`).
    unread_by_choice: int = 0
    #: How far the read got, for a board whose listing can continue
    #: (`BaseAdapter.resume_point`); None for every other board.
    position: ReadPosition | None = None
    #: True when this read continued from a cursor rather than page one.
    resumed: bool = False


@dataclass(frozen=True)
class Cursor:
    """Where a read our host cut stopped, held by the run for its next pass.

    Only a read that found no role yet leaves one: a role found before the cut
    follows the company at once. It is trusted for the radar it was made with,
    while that radar has been in force since its first part, and until that
    part would itself be due again.
    """

    position: ReadPosition
    #: `scope_fingerprint` of the radar the read was made with.
    radar: str
    #: When the read's first part began. The finished check is dated by it,
    #: so the board is due again a day after its oldest part was read.
    started: datetime


def parts_add_up(scope: ScopeFilter) -> bool:
    """Whether a board read in parts finds what one read finds.

    True when the radar keeps a posting for ANY of its places: a posting listed
    under two place groups is judged in each part on the places that part saw,
    and none of them can keep it wrongly. An exception ("US but not New York")
    makes the verdict depend on every place, so then a cut read neither follows
    on what it found nor leaves a cursor: the board is read again whole, as
    `wanted_place` reads every place.
    """
    return not scope.excluded_locations


def wanted_place(scope: ScopeFilter) -> Callable[[str], bool] | None:
    """Whether a posting at this place label could pass the radar's place axis.

    Exact for the scan's question: with no exceptions the gate admits a posting
    when ANY of its places is in (`place_admits`), so a posting at an unwanted
    place is kept only through another place, whose group is read in full. An
    exception ("US but not New York") makes the gate depend on every place a
    posting has, so then nothing is left unread (None).
    """
    if scope.excluded_locations:
        return None

    def wanted(label: str) -> bool:
        place = clean_location(label)
        return bool(place) and place_admits(
            location_slugs_for([place]), scope.enabled_locations, scope.excluded_locations,
        )

    return wanted


async def check_company(
    company: DirectoryCompany,
    scope: ScopeFilter,
    *,
    limiter_pool: RateLimiterPool,
    breaker_pool: BreakerPool,
    stall_seconds: float,
    budget_seconds: float,
    resume: Cursor | None = None,
) -> Check:
    """Count matches, preserving the collector's outcome vocabulary and bounds.

    With `resume`, a board whose listing can continue reads on from where an
    earlier read stopped, once the board confirms the place still holds; the
    counts of the part before it are added, and the outcome is the union's.
    """
    access = collection_access(company.adapter, company=company.slug)
    if access.denied or access.walled:
        return Check(company.slug, REFUSED, 0, 0, access.reason)
    clock = SourceClock(
        stall_seconds=stall_seconds,
        hard_deadline=time.monotonic() + budget_seconds,
    )
    # The host sleeping mid-read lands as transport errors after it wakes, and
    # the network is up again by then: without this the read would be recorded
    # as the board's failure and left for a day (the collector's rule).
    suspension = SuspensionMonitor(threshold_seconds=get_settings().scraper_host_suspension_seconds)
    stats = empty_stats()
    adapter = None
    seen: set[str] = set()

    def record(raw) -> None:
        key = raw.dedupe_key()
        if key in seen:
            return
        seen.add(key)
        stats["scanned"] += 1
        if passes_filters(annotate(raw), scope) and not rule_excluded(raw, scope.company_exclusions):
            stats["kept"] += 1

    def record_bound() -> None:
        if bound_fired(clock) == STALLED:
            stats["errors"].append("SourceStalled: directory source stopped making progress")
        else:
            stats["bounded"] = True

    try:
        adapter = build_adapter(
            company.slug, company.adapter,
            board_token=company.board_token, board_region=company.board_region,
            limiter_pool=limiter_pool, breaker_pool=breaker_pool, deadline=clock,
            page_budgets=_AtTheHardMaximum(),
        )
        adapter.wanted_place = wanted_place(scope)
        if resume is not None:
            adapter.resume_from = resume.position
        async with adapter:
            async for raw in adapter.fetch():
                if bound_fired(clock):
                    record_bound()
                    break
                clock.progress()
                record(raw)
    except RetryDeadlineExceeded:
        record_bound()
    except CollectionPolicyDenied as exc:
        stats["unattempted"] = True
        stats["errors"].append(str(exc))
    except CircuitOpenError:
        # The job site refusing US is no verdict on this board: the lane decides.
        raise
    except Exception as exc:  # noqa: BLE001 - contain one board's failure
        stats["errors"].append(f"{type(exc).__name__}: {exc}"[:500])
    if adapter is not None and not stats["unattempted"]:
        for raw in getattr(adapter, "drain_completed", lambda: ())():
            record(raw)
    resumed = bool(resume is not None and getattr(adapter, "resumed", False))
    before = resume.position if resume is not None and resumed else ReadPosition(at={})
    # The union of the two parts: a posting this part listed again (one listed
    # under places on either side of the cut) is one posting, not two.
    stats["scanned"] += sum(dedupe_key_for(company.slug, req_id) not in seen for req_id in before.listed)
    stats["suspended"] = suspension.suspended()
    # The collector's judgement, so a directory board is read the same way a
    # followed one is. A stall is already an error here.
    # A host suspension is not a cut: a directory read closes nothing, it
    # counts, and a suspended read that still errored is `suspended` by the
    # outcome derivation's own rule.
    stats["list_complete"] = judge_listing(stats, adapter, cut=stats["bounded"])
    drift = getattr(adapter, "drift", None)
    outcome = classify_source_outcome(stats)
    reasons = list(stats["errors"])
    if drift is not None:
        reasons.extend(str(alert["message"]) for alert in drift.alerts)
    error = None if outcome in (SourceOutcome.OK, SourceOutcome.EMPTY) else ("; ".join(reasons) or outcome.value)[:500]
    return Check(
        company.slug, outcome.value, stats["scanned"], stats["kept"], error,
        unread_by_choice=before.unread_by_choice + getattr(adapter, "unread_by_choice", 0),
        position=getattr(adapter, "resume_point", None),
        resumed=resumed,
    )


async def _record(check: Check, now: datetime) -> bool:
    """Store one check; follow the company when it found roles. True if followed.

    A read that found roles after the set was unfollowed is not stored: stored,
    it would keep the board current for a day with its find unfollowed, so
    following again would not read it.
    """
    values = {
        "slug": check.slug, "checked_at": now, "outcome": check.outcome,
        "scanned": check.scanned, "roles_for_you": check.roles_for_you, "error": check.error,
    }
    async with session_scope() as session:
        await advisory_xact_lock(session, FOLLOW_LOCK_KEY)
        following = (await read_follow(session))["following"]
        if check.roles_for_you > 0 and not following:
            return False
        await session.execute(
            pg_insert(DirectoryCheck).values(**values).on_conflict_do_update(
                index_elements=[DirectoryCheck.slug],
                set_={k: v for k, v in values.items() if k != "slug"},
            )
        )
        followed = False
        if check.roles_for_you > 0:
            row = await follow_with_set(session, check.slug)
            if row is not None:
                await ensure_company_profile(session, row.slug, row.display)
                followed = True
        await session.commit()
    return followed




#: Why a pass did not start, or stopped: a scan holds the shared pacers.
SCAN_GOES_FIRST = "a scan goes first"


async def scan_goes_first(session: AsyncSession) -> bool:
    """Whether a scan is reading, or one the user started still has companies to read.

    The pass shares the shared job sites' pacers with every scan
    (`SharedSlot`), so running beside one halves that scan's lanes on the hosts
    holding most companies, and the scan's run bound then cuts the slowest
    lane short. A planned full or quick read is the user's scan as much as one
    they started, so every live scan goes first. A `running` row that stopped
    beating is an orphan and holds nothing.
    """
    if await session.scalar(
        select(func.count()).select_from(SyncScheduleState).where(
            SyncScheduleState.manual_requested_at.is_not(None)
        )
    ):
        return True
    settings = get_settings()
    orphaned = stale_run_where(
        func.now(),
        stale_minutes=settings.stale_run_minutes,
        heartbeat_stale_seconds=settings.stale_run_heartbeat_seconds,
    )
    return bool(await session.scalar(
        select(func.count()).select_from(ScrapeRun).where(ScrapeRun.status == "running", ~orphaned)
    ))


# --- one pass ---------------------------------------------------------------------------


def _still_trusted(cursors: dict[str, Cursor], radar: str, radar_since: datetime | None,
                   held: set[str], now: datetime) -> None:
    """Drop every cursor this pass must not continue from.

    One made with another radar answered another question, and skipped other
    places' pages. One whose first part is a day old would leave the finished
    check due at once. A company with a row is not the scan's to read.
    """
    for slug, cursor in list(cursors.items()):
        if (
            cursor.radar != radar
            or (radar_since is not None and cursor.started < radar_since)
            or now - cursor.started >= due_after()
            or slug in held
        ):
            del cursors[slug]


@dataclass(frozen=True)
class PassClock:
    """The one clock a pass reads: wall time for everything stored
    or compared with what is stored (checks, cursors, due-ness), monotonic
    time for the pass's own deadlines. A test pins a pass to one instant
    (`PassClock.at`); a real pass reads the machine. Due-ness and the stamps
    on the checks a pass writes come from the same clock."""

    wall: Callable[[], datetime] = lambda: datetime.now(UTC)
    monotonic: Callable[[], float] = time.monotonic

    @classmethod
    def at(cls, now: datetime) -> PassClock:
        return cls(wall=lambda: now)


class _Pass:
    """One pass's lanes, reads and counts; every time it reads comes from
    `clock`."""

    def __init__(
        self, *, scope: ScopeFilter, radar: str, in_parts: bool, cursors: dict[str, Cursor],
        budget_seconds: float, clock: PassClock,
    ) -> None:
        self.settings = get_settings()
        self.scope, self.radar, self.in_parts = scope, radar, in_parts
        #: The run's reads our host cut, by slug: read here, left here.
        self.cursors = cursors
        self.clock = clock
        self.deadline = clock.monotonic() + budget_seconds
        self.limiter_pool, self.breaker_pool = RateLimiterPool(), BreakerPool()
        self.totals = {"checked": 0, "with_roles": 0, "followed": 0, "failed": 0,
                       "unread_by_choice": 0, "continued": 0, "restarted": 0}
        self.paused: list[str] = []
        #: Per job site: boards recorded, seconds the lane ran, and whether it read
        #: everything due to it. What a measurement of the scan reads.
        self.lanes: dict[str, dict] = {}
        self.interrupted_by: str | None = None
        self._asked_at, self._asked_wall = clock.monotonic(), clock.wall()
        #: Our host is cut off: every lane stops and the run waits.
        self.offline = False

    async def run(self, lanes: Mapping[str, list[DirectoryCompany]]) -> None:
        await asyncio.gather(*(self._lane(site, companies) for site, companies in lanes.items()))

    def summary(self, due: int) -> dict:
        return {
            "ran": True, "due": due, "interrupted": self.interrupted_by, **self.totals,
            "paused": sorted(self.paused), "lanes": self.lanes, "offline": self.offline,
            "cursors": len(self.cursors),
        }

    async def _interrupted(self) -> bool:
        # Asked at most every `directory_yield_check_seconds`, shared by every
        # lane, so Stop takes effect within that, not at the pass's end.
        if self.offline:
            return True
        now, wall = self.clock.monotonic(), self.clock.wall()
        if self.interrupted_by is None and (
            now - self._asked_at >= self.settings.directory_yield_check_seconds
            # A sleep stops the monotonic clock, not the wall one: the first
            # read after a sleep asks at once, rather than reading on through
            # a maintenance wake.
            or (wall - self._asked_wall).total_seconds() >= self.settings.directory_yield_check_seconds
        ):
            self._asked_at, self._asked_wall = now, wall
            # Shut, or unplugged: the pass ends here, reads under way finish.
            waiting = host_power.read_power().wait_reason(mains=True)
            if waiting is not None:
                self.interrupted_by = waiting
                return True
            async with session_scope() as session:
                if await scan_goes_first(session):
                    self.interrupted_by = SCAN_GOES_FIRST
                elif not (await read_follow(session))["following"]:
                    self.interrupted_by = "the set was unfollowed"
        return self.interrupted_by is not None

    async def _lane(self, site: str, companies: list[DirectoryCompany]) -> None:
        report = self.lanes[site] = {"checked": 0, "seconds": 0.0, "finished": False}
        began = self.clock.monotonic()
        try:
            await self._read_lane(companies, report)
        finally:
            report["seconds"] = round(self.clock.monotonic() - began, 1)

    async def _read_lane(self, companies: list[DirectoryCompany], report: dict) -> None:
        for company in companies:
            # The pass's end stops new reads; a read under way always finishes.
            if self.clock.monotonic() >= self.deadline or await self._interrupted():
                return
            cursor = self.cursors.get(company.slug)
            began = self.clock.wall()
            try:
                check = await check_company(
                    company, self.scope, limiter_pool=self.limiter_pool, breaker_pool=self.breaker_pool,
                    stall_seconds=self.settings.scraper_source_stall_seconds,
                    budget_seconds=self.settings.scraper_source_budget_seconds,
                    resume=cursor,
                )
            except CircuitOpenError as exc:
                if not await network_up():
                    # Nothing answers at all: the breaker opened on our outage,
                    # not on the site. Every lane stops and the run waits for
                    # the network, keeping its cursors; pausing each lane
                    # would record nothing and end the run.
                    log.warning("directory lane %s cut by our host: %s", company.adapter, exc)
                    self.offline = True
                    return
                # The site is refusing us. Reading on, the open breaker would
                # fail every board left in the lane in seconds, each recorded as
                # that board's failure. Nothing is recorded; the lane rests until the
                # next pass's fresh breaker probes the site again.
                log.warning("directory lane %s paused: %s", company.adapter, exc)
                self.paused.append(company.adapter)
                return
            if check.outcome == SUSPENDED or (
                check.outcome in _UNFINISHED and not await network_up()
            ):
                # Our host, not the board: it slept, or no job site answers at
                # all. The read is not this board's verdict, so it is not
                # recorded as one and every lane stops; the run waits for the
                # network. What the read got is kept.
                log.warning("directory read of %s cut by our host: %s", company.slug, check.error)
                self.offline = True
                await self._keep_cut_read(check, cursor, began, report)
                return
            if cursor is not None:
                self.totals["continued" if check.resumed else "restarted"] += 1
            # A continued read is dated by its first part: the board is due again
            # a day after the oldest thing the check knows.
            at = cursor.started if cursor is not None and check.resumed else self.clock.wall()
            self.cursors.pop(company.slug, None)
            self._count(check, await _record(check, at), report)
        report["finished"] = True

    async def _keep_cut_read(
        self, check: Check, cursor: Cursor | None, began: datetime, report: dict,
    ) -> None:
        """A role found before the cut follows the company now; a read that
        found none leaves a cursor for the next pass to continue from."""
        self.cursors.pop(check.slug, None)
        if not self.in_parts:
            return
        if check.roles_for_you > 0:
            self._count(check, await _record(replace(check, outcome=SUSPENDED), self.clock.wall()), report)
        elif check.position is not None:
            same_read = cursor is not None and (check.resumed or check.position == cursor.position)
            self.cursors[check.slug] = Cursor(
                check.position, self.radar, cursor.started if cursor and same_read else began,
            )

    def _count(self, check: Check, followed: bool, report: dict) -> None:
        report["checked"] += 1
        self.totals["checked"] += 1
        self.totals["with_roles"] += check.roles_for_you > 0
        self.totals["followed"] += followed
        self.totals["failed"] += check.outcome in _SOURCE_FAILURES
        self.totals["unread_by_choice"] += check.unread_by_choice


async def sweep_once(
    *, budget_seconds: float, cursors: dict[str, Cursor] | None = None, clock: PassClock | None = None,
) -> dict:
    """Read as much of the due set as fits in the budget; one lane per job site.

    `cursors` are the run's reads our host cut, by slug; a read continues from
    one and leaves one. The run holds them across its passes.
    `clock` is the pass's one clock (`PassClock`; the machine's by default).
    """
    clock = clock or PassClock()
    cursors = {} if cursors is None else cursors
    started = clock.wall()
    async with session_scope() as session:
        follow = await read_follow(session)
        if not follow["following"]:
            return {"ran": False, "reason": "the set is not followed"}
        if await scan_goes_first(session):
            return {"ran": False, "reason": SCAN_GOES_FIRST}
        # Not in a maintenance wake, where every read would cross a sleep, and
        # not on battery: about two hours of reading a day is the user's
        # battery to spend, not ours. The register says it waits.
        waiting = host_power.read_power().wait_reason(mains=True)
        if waiting is not None:
            return {"ran": False, "reason": waiting}
        scope = await load_scope_filter(session)
        radar_since = await note_radar(session, scope, started)
        attempts = (await session.execute(select(
            DirectoryCheck.slug, DirectoryCheck.checked_at, DirectoryCheck.outcome,
        ))).all()
        # A check made with an earlier radar is no check for this one.
        checked = {
            slug: at for slug, at, _ in attempts if radar_since is None or at >= radar_since
        }
        held = set((await session.scalars(select(TrackedCompany.slug))).all())
    radar = scope_fingerprint(scope)
    _still_trusted(cursors, radar, radar_since, held, started)
    listed = directory()
    due = due_companies(listed.values(), checked, held, started)
    if not due:
        return {"ran": False, "reason": "nothing due", "size": len(listed)}

    lanes: dict[str, list[DirectoryCompany]] = {}
    # A read our host cut goes first in its lane: the older its first part, the
    # sooner its cursor stops being trusted.
    for company in sorted(due, key=lambda company: company.slug not in cursors):
        lanes.setdefault(company.adapter, []).append(company)
    run = _Pass(
        scope=scope, radar=radar, in_parts=parts_add_up(scope), cursors=cursors,
        budget_seconds=budget_seconds, clock=clock,
    )
    await run.run(lanes)
    return run.summary(len(due))


async def sweep_passes(
    *, pass_seconds: float, run_seconds: float, clock: PassClock | None = None,
) -> AsyncIterator[dict]:
    """Passes back to back while companies are due, for at most `run_seconds`.

    launchd starts this process 600 s after the previous one EXITED, not 600 s
    after it started, so one short pass per process would leave the scan idle
    for more than half of every cycle.

    A pass stays the unit that reads the radar and the followed set again. The
    run ends on a pass with nothing to do (the set unfollowed, nothing due, a
    scan under way, the machine shut or on battery), on one that
    recorded nothing and was not cut by the network (so a site refusing us
    cannot spin), or at `run_seconds`; launchd
    then starts a fresh process on whatever code main holds by then. A pass
    that found the network down waits, checking every
    `directory_offline_recheck_seconds`, and the run carries on when it is back.
    A read our host cut continues in a later pass of the same run
    from where it stopped (`Cursor`): the run outlives a sleep (its
    clock is monotonic) and waits out an outage, so the cursors live in it.
    """
    clock = clock or PassClock()
    run_deadline = clock.monotonic() + run_seconds
    cursors: dict[str, Cursor] = {}
    while (left := run_deadline - clock.monotonic()) > 0:
        result = await sweep_once(budget_seconds=min(pass_seconds, left), cursors=cursors, clock=clock)
        yield result
        if result.get("offline"):
            while not await network_up():
                recheck = get_settings().directory_offline_recheck_seconds
                if clock.monotonic() + recheck >= run_deadline:
                    return
                await _pause(recheck)
            continue
        if not result["ran"] or not result["checked"]:
            return


# --- what the register shows ----------------------------------------------------------------


async def directory_status(session: AsyncSession) -> dict:
    """The set as the register draws it: size, whether followed, and progress.

    A company counts once the scan holds it as done: a check that was still
    current when the switch went on (read within `due_after()` before it) or made since,
    whatever it found, or a row the set already follows. That is the scan's own
    "not due", so the line reaches the total exactly when a pass finds nothing
    due, and stays there while later passes keep the checks current. Counting
    only checks made since the switch, or only verdicts our own bounds did not
    cut, would hold the line short of the total after the scan had read every
    company: the scan rightly skips checks current at the switch-on, and holds
    a check our own bounds cut as done.
    """
    follow = await read_follow(session)
    since = datetime.fromisoformat(follow["since"]) if follow["since"] else None
    listed = directory()
    rows = {
        slug: source for slug, source in (await session.execute(
            select(TrackedCompany.slug, TrackedCompany.source).where(
                TrackedCompany.source.in_(DIRECTORY_SOURCES)
            )
        )).all() if slug in listed
    }
    # Followed by name before the set could reach them: never the scan's to read.
    by_name = sum(source == FOLLOWED_BY_NAME for source in rows.values())
    to_check = max(0, len(listed) - by_name)
    checked = 0
    if since is not None:
        # Current at the switch-on, and made with the radar in force.
        current_after = since - due_after()
        if follow["scope_since"]:
            current_after = max(current_after, datetime.fromisoformat(follow["scope_since"]))
        read_slugs = (await session.scalars(
            select(DirectoryCheck.slug).where(
                DirectoryCheck.checked_at > current_after,
                ~select(TrackedCompany.slug).where(
                    TrackedCompany.slug == DirectoryCheck.slug
                ).exists(),
            )
        )).all()
        # A board the directory dropped since its check is no board to read:
        # counted, it would carry the line past boards still unread.
        read = sum(1 for slug in read_slugs if slug in listed)
        # The set's own rows: found with roles (or switched off by the user since).
        checked = read + sum(source == FOLLOWED_WITH_SET for source in rows.values())
    with_roles = await session.scalar(
        select(func.count()).select_from(TrackedCompany).where(
            TrackedCompany.source == FOLLOWED_WITH_SET, TrackedCompany.enabled.is_(True)
        )
    ) or 0
    # The scan waits for mains power: said, so a line that stopped
    # moving on battery is not read as a stalled scan. `pmset` off the loop.
    on_battery = follow["following"] and (await asyncio.to_thread(host_power.read_power)).on_battery
    return {
        "size": len(listed),
        "following": follow["following"],
        "since": since,
        # A company followed on its own is not the set's to check, so the first
        # pass is over when every OTHER company is done.
        "checked": min(checked, to_check),
        "to_check": to_check,
        "with_roles": with_roles,
        "waiting_for_power": on_battery,
    }


async def sweep_under_lock(*, run_seconds: float, report: Callable[[dict], None]) -> list[dict]:
    """The sweep's passes under the directory lock, each reported as it ends.
    Another sweep holding the lock is one result saying so, not a failure.
    The supervisor's `directory` entry and `main` both run this."""
    settings = get_settings()
    passes: list[dict] = []
    try:
        with run_lock(DATA_DIR / "directory.lock"):
            async for result in sweep_passes(
                pass_seconds=settings.directory_sweep_budget_seconds, run_seconds=run_seconds,
            ):
                report(result)
                passes.append(result)
    except AlreadyRunning:
        busy = {"ran": False, "reason": "a pass is already running"}
        report(busy)
        passes.append(busy)
    return passes


def main() -> None:
    enable_shared_pacing(PACING_DIR)
    parser = argparse.ArgumentParser(description="Read the due part of every other company")
    parser.add_argument("--budget", type=float, default=None,
                        help="seconds this run may read, in passes back to back")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    budget = args.budget if args.budget is not None else settings.directory_sweep_run_seconds

    def report(result: dict) -> None:
        print(json.dumps(result, indent=2, default=str), flush=True)

    asyncio.run(sweep_under_lock(run_seconds=budget, report=report))


if __name__ == "__main__":
    main()
