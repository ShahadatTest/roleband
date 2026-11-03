"""The background scan of every other company RoleBand can scan.

What it may do, pinned from both sides:

* read the never-read first, most-linked first, then only what is a day old;
* follow a company exactly when a posting there passes the SAME gate the
  pipeline applies — and never one that has no such posting;
* record every read, including a failure, so a broken board is not retried in a
  loop and progress can be counted;
* never touch a company that already has a row: one followed by name, or one
  the user switched off, is theirs;
* do nothing at all while the set is not followed.

The job sites are a fake adapter; the scope gate, the store and the database
are real.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from tests.barriers import until_waiting
from tests.company_contract_seed import seed_company_contract
from tests.factories import scope_for
from tests.power_answers import DARK_WAKE, ON_BATTERY, machine
from tracker import company_directory
from tracker.api.routers import companies as companies_router
from tracker.company_directory import DirectoryCompany
from tracker.config import get_settings
from tracker.db.models import DirectoryCheck, ScrapeRun, TrackedCompany
from tracker.enrich.enricher import ScopeFilter
from tracker.platform.drift import SchemaDriftDetector
from tracker.platform.power import WAITING_FOR_FULL_WAKE, WAITING_FOR_MAINS
from tracker.schema import LevelBand, RawJob, RoleTrack
from tracker.workflows import directory_sweep
from tracker.workflows.directory_sweep import (
    PassClock,
    directory_status,
    due_after,
    due_companies,
    read_follow,
    set_follow,
    sweep_once,
    sweep_passes,
)

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


pytestmark = pytest.mark.usefixtures("no_escape")


def _company(rank, slug, adapter="greenhouse"):
    return DirectoryCompany(slug=slug, display=slug.title(), named_by="board", adapter=adapter,
                            board_token=slug, board_region=None, rank=rank)


def _job(company: str, title: str, place: str = "San Francisco, CA") -> RawJob:
    return RawJob(company=company, req_id=f"{company}-{title}", title=title,
                  url=f"https://example.test/{company}", locations=[place])


FITS = "Senior Staff Software Engineer"
DOES_NOT_FIT = "Recruiting Coordinator"


# --- what is due ------------------------------------------------------------------


def test_never_read_comes_first_in_rank_order_then_the_stalest():
    companies = [_company(0, "a"), _company(1, "b"), _company(2, "c"), _company(3, "d")]
    checked = {
        "a": NOW - timedelta(hours=30),   # stale
        "b": NOW - timedelta(hours=2),    # fresh: not due
        "d": NOW - timedelta(hours=50),   # stalest
    }
    due = due_companies(companies, checked, skip=set(), now=NOW)
    assert [c.slug for c in due] == ["c", "d", "a"]


def test_a_company_with_a_row_is_never_the_scans_to_read():
    companies = [_company(0, "mine"), _company(1, "other")]
    assert [c.slug for c in due_companies(companies, {}, skip={"mine"}, now=NOW)] == ["other"]


def test_exactly_a_day_old_is_due_and_a_minute_younger_is_not():
    companies = [_company(0, "a"), _company(1, "b")]
    checked = {"a": NOW - timedelta(hours=24), "b": NOW - timedelta(hours=24) + timedelta(minutes=1)}
    assert [c.slug for c in due_companies(companies, checked, set(), NOW)] == ["a"]


def test_the_directory_cadence_is_configs_number(monkeypatch):
    """`directory_check_due_hours` owns the cadence."""
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "directory_check_due_hours", 48.0)
    companies = [_company(0, "a"), _company(1, "b")]
    checked = {"a": NOW - timedelta(hours=30), "b": NOW - timedelta(hours=48)}
    assert [c.slug for c in due_companies(companies, checked, set(), NOW)] == ["b"]


# --- one pass, end to end -------------------------------------------------------------


class _FakeAdapter:
    def __init__(self, jobs=(), error=None):
        self._jobs, self._error = list(jobs), error
        self.drift = SchemaDriftDetector("fixture")
        self.truncated = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self):
        for job in self._jobs:
            yield job
        if self._error:
            raise self._error


@pytest.fixture
def world(scratch_scope, monkeypatch):
    """Four directory companies; each board answers what the test says."""
    companies = {c.slug: c for c in [
        _company(0, "hiring"), _company(1, "quiet", adapter="ashby"),
        _company(2, "broken", adapter="lever"), _company(3, "mine"),
    ]}
    boards = {
        "hiring": _FakeAdapter([_job("hiring", DOES_NOT_FIT), _job("hiring", FITS)]),
        "quiet": _FakeAdapter([_job("quiet", DOES_NOT_FIT)]),
        "broken": _FakeAdapter([], error=RuntimeError("board answered 500")),
        "mine": _FakeAdapter([_job("mine", FITS)]),
    }
    built: list[str] = []

    def build_adapter(slug, adapter, **_kw):
        built.append(slug)
        return boards[slug]

    async def scope(_session):
        return scope_for(_job("x", FITS))

    monkeypatch.setattr(company_directory, "directory", lambda: companies)
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    monkeypatch.setattr(directory_sweep, "build_adapter", build_adapter)
    monkeypatch.setattr(directory_sweep, "load_scope_filter", scope)
    monkeypatch.setattr(directory_sweep, "network_up", _always_online)
    return {"session_scope": scratch_scope, "built": built, "boards": boards}


async def _always_online(timeout=5.0):
    return True


async def _follow(world, following=True):
    async with world["session_scope"]() as session:
        await set_follow(session, following, NOW)


async def _rows(world):
    async with world["session_scope"]() as session:
        checks = {c.slug: c for c in (await session.scalars(select(DirectoryCheck))).all()}
        tracked = {t.slug: t for t in (await session.scalars(select(TrackedCompany))).all()}
    return checks, tracked


@pytest.mark.asyncio
async def test_a_pass_follows_exactly_the_companies_with_a_role_that_fits(world):
    async with world["session_scope"]() as session:
        session.add(TrackedCompany(slug="mine", display="Mine", adapter="greenhouse",
                                   board_token="mine", status="active", enabled=False,
                                   visible=True, source="directory"))
    await _follow(world)

    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))

    checks, tracked = await _rows(world)
    assert summary["checked"] == 3 and summary["followed"] == 1 and summary["failed"] == 1
    assert "mine" not in world["built"], "a company with a row is the user's, never re-read"
    assert (checks["hiring"].outcome, checks["hiring"].scanned, checks["hiring"].roles_for_you) == ("ok", 2, 1)
    assert (checks["quiet"].outcome, checks["quiet"].roles_for_you) == ("ok", 0)
    assert checks["broken"].outcome == "failed" and "500" in checks["broken"].error
    hiring = tracked["hiring"]
    assert (hiring.source, hiring.enabled, hiring.status, hiring.adapter) == (
        "directory-set", True, "active", "greenhouse")
    assert "quiet" not in tracked and "broken" not in tracked
    assert tracked["mine"].enabled is False, "the user's own switch stays where they left it"


@pytest.mark.asyncio
async def test_nothing_is_read_while_the_set_is_not_followed(world):
    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))
    assert summary == {"ran": False, "reason": "the set is not followed"}
    assert world["built"] == []
    checks, tracked = await _rows(world)
    assert checks == {} and tracked == {}


@pytest.mark.asyncio
async def test_a_sync_the_user_started_goes_first(world):
    """The pass shares the Greenhouse, Ashby and Lever pacers with the sync, so
    beside a user's sync it halves that sync's lanes."""
    from tracker.workflows.scheduler import queue_manual_reconciliation

    await _follow(world)
    async with world["session_scope"]() as session:
        assert await queue_manual_reconciliation(session, ["anthropic"]) == ["anthropic"]

    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))

    assert summary == {"ran": False, "reason": "a scan goes first"}
    assert world["built"] == []


async def _scan_running(world, *, last_beat: timedelta = timedelta(0)) -> None:
    """A planned scan's run row, as the pipeline keeps it while it collects."""
    beat = datetime.now(UTC) - last_beat
    async with world["session_scope"]() as session:
        session.add(ScrapeRun(status="running", started_at=beat, heartbeat_at=beat))


@pytest.mark.asyncio
async def test_a_planned_scan_under_way_goes_first(world):
    """No sync the user pressed, only the plan's own full read: it shares the
    same pacers, and beside the pass its slowest lane runs out of time."""
    await _follow(world)
    await _scan_running(world)

    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))

    assert summary == {"ran": False, "reason": "a scan goes first"}
    assert world["built"] == []


@pytest.mark.asyncio
async def test_a_run_that_stopped_beating_holds_nothing(world):
    """A `running` row whose process died is an orphan, not a scan: the pass
    must not wait on it until the reconciler gets round to it."""
    await _follow(world)
    await _scan_running(world, last_beat=timedelta(hours=1))

    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))

    assert summary["ran"] is True and summary["checked"] == len(world["boards"])


@pytest.mark.asyncio
async def test_a_role_found_while_the_set_is_being_unfollowed_follows_nothing(world):
    """The switch and a check that follows a company take one lock from their
    read of the follow setting to commit. Without it the check can read
    "following", the unfollow commit, and the company the check then follows
    stay followed with the set switched off."""
    import asyncio

    await _follow(world)
    found = directory_sweep.Check("hiring", "ok", 2, 1)
    async with world["session_scope"]() as unfollowing:
        await set_follow(unfollowing, False, NOW)
        recording = asyncio.create_task(directory_sweep._record(found, NOW))
        await until_waiting(unfollowing.bind, recording)
        assert not recording.done(), "the check waits for the switch"
    assert await recording is False

    checks, tracked = await _rows(world)
    assert "hiring" not in tracked and checks == {}
    async with world["session_scope"]() as session:
        assert (await read_follow(session))["following"] is False


@pytest.mark.asyncio
async def test_a_second_pass_the_same_day_reads_nothing(world):
    await _follow(world)
    await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))
    world["built"].clear()
    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW + timedelta(hours=1)))
    assert summary["ran"] is False and world["built"] == []


@pytest.mark.asyncio
async def test_a_spent_budget_reads_nothing_more(world):
    await _follow(world)
    summary = await sweep_once(budget_seconds=0, clock=PassClock.at(NOW))
    assert summary["checked"] == 0 and world["built"] == []


def _checks_answer(monkeypatch, answer):
    """Replace one board read; record the per-company budget each read was given."""
    budgets: dict[str, list[float]] = {}

    async def check_company(company, scope, *, budget_seconds, **_kw):
        budgets.setdefault(company.slug, []).append(budget_seconds)
        return directory_sweep.Check(company.slug, *answer(company.slug))

    monkeypatch.setattr(directory_sweep, "check_company", check_company)
    return budgets


@pytest.mark.asyncio
async def test_a_read_our_backstop_cut_is_read_again_tomorrow_never_in_a_loop(world, monkeypatch):
    """Every read gets the same backstop, the source budget: there is no shorter
    first-read clock to cut a big board on a slow connection."""
    budgets = _checks_answer(monkeypatch, lambda slug: ("bounded", 3, 0, "our budget"))
    await _follow(world)

    await sweep_once(budget_seconds=600, clock=PassClock.at(NOW))
    checks, tracked = await _rows(world)
    assert {c.outcome for c in checks.values()} == {"bounded"} and tracked == {}
    async with world["session_scope"]() as session:
        # Done for the line until tomorrow's retry, like every check the scan
        # would not read again now (rather than holding it pending).
        status = await directory_status(session)
    assert status["checked"] == status["to_check"] == 4
    assert (await sweep_once(budget_seconds=600, clock=PassClock.at(NOW + timedelta(hours=1))))["ran"] is False

    # A day after the pass's own clock: the checks it wrote are stamped by the
    # instant it ran at, as due-ness is measured, never by the machine's
    # clock.
    await sweep_once(budget_seconds=600, clock=PassClock.at(NOW + due_after() + timedelta(minutes=1)))
    source_budget = get_settings().scraper_source_budget_seconds
    assert budgets["hiring"] == [source_budget, source_budget]


@pytest.mark.asyncio
async def test_a_site_refusing_us_pauses_its_lane_and_records_nothing(world, monkeypatch):
    """Once the breaker opens, every board left in that lane fails in seconds:
    read on, and a site's refusal would be recorded as thousands of boards'
    failures, each counted as read. The other lanes read on."""
    from tracker.platform.breaker import CircuitOpenError

    companies = {c.slug: c for c in [
        _company(0, "refused", adapter="ashby"), _company(1, "next-in-lane", adapter="ashby"),
        _company(2, "hiring"),
    ]}
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    world["boards"]["refused"] = _FakeAdapter([], error=CircuitOpenError("ashby", 5, blocked=True))
    world["boards"]["next-in-lane"] = _FakeAdapter([_job("next-in-lane", FITS)])
    await _follow(world)

    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))

    checks, _ = await _rows(world)
    assert set(checks) == {"hiring"}, "a refusal is no board's verdict"
    assert "next-in-lane" not in world["built"]
    assert summary["paused"] == ["ashby"] and summary["checked"] == 1


# --- one run: passes back to back ----------------------------------------------------


class _Clock:
    """The pass's monotonic clock, moved only by the reads below."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


#: The clock a test's run reads: injected, never patched into the module
#: `_reads_take` moves its monotonic half.
_TIME: dict = {}


@pytest.fixture(autouse=True)
def _no_clock_carried_over():
    """A clock `_reads_take` built is this test's alone."""
    _TIME.clear()
    yield
    _TIME.clear()


def _one_lane_of(monkeypatch, count):
    """`count` companies on one job site, so a pass reads them one after another."""
    companies = {c.slug: c for c in (_company(rank, f"co{rank}") for rank in range(count))}
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    return companies


def _reads_take(monkeypatch, seconds, *, outcome="ok", during=None):
    """Every board read costs `seconds` of the pass clock; returns the slugs read."""
    clock = _Clock()
    _TIME["clock"] = PassClock(monotonic=clock.monotonic)
    read: list[str] = []

    async def check_company(company, scope, **_kw):
        read.append(company.slug)
        clock.now += seconds
        if during is not None:
            await during(company)
        return directory_sweep.Check(company.slug, outcome, 1, 0)

    monkeypatch.setattr(directory_sweep, "check_company", check_company)
    return read


async def _run(**budgets):
    return [result async for result in sweep_passes(**budgets, clock=_TIME.pop("clock", None))]


@pytest.mark.asyncio
async def test_a_run_passes_back_to_back_until_nothing_is_due(world, monkeypatch):
    """One 540 s pass per process, with launchd starting the next process 600 s
    after an exit, would read 9 minutes in every 19. A pass's budget ends the
    pass, never the reading."""
    companies = _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 10)
    await _follow(world)

    passes = await _run(pass_seconds=25, run_seconds=3600)

    assert read == list(companies), "every due company is read in one run"
    assert [p.get("checked") for p in passes] == [3, 2, None]
    assert passes[-1] == {"ran": False, "reason": "nothing due", "size": 5}


@pytest.mark.asyncio
async def test_a_run_stops_at_its_own_budget(world, monkeypatch):
    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 10)
    await _follow(world)

    passes = await _run(pass_seconds=25, run_seconds=25)

    assert read == ["co0", "co1", "co2"] and len(passes) == 1, "the rest waits for the next run"


@pytest.mark.asyncio
async def test_a_sync_the_user_started_ends_the_run(world, monkeypatch):
    from tracker.workflows.scheduler import queue_manual_reconciliation

    async def user_starts_a_sync(company):
        if company.slug == "co0":
            async with world["session_scope"]() as session:
                await queue_manual_reconciliation(session, ["anthropic"])

    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 10, during=user_starts_a_sync)
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    assert passes[0]["interrupted"] == "a scan goes first"
    assert read == ["co0", "co1"]
    assert passes[1:] == [{"ran": False, "reason": "a scan goes first"}]


@pytest.mark.asyncio
async def test_a_scan_that_starts_mid_pass_ends_the_run(world, monkeypatch):
    async def plan_starts_a_scan(company):
        if company.slug == "co0":
            await _scan_running(world)

    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 10, during=plan_starts_a_scan)
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    assert passes[0]["interrupted"] == "a scan goes first"
    assert read == ["co0", "co1"]
    assert passes[1:] == [{"ran": False, "reason": "a scan goes first"}]


@pytest.mark.asyncio
async def test_a_run_with_the_set_unfollowed_asks_once_and_ends(world, monkeypatch):
    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 10)

    assert await _run(pass_seconds=25, run_seconds=3600) == [
        {"ran": False, "reason": "the set is not followed"}
    ]
    assert read == []


@pytest.mark.asyncio
async def test_a_pass_that_records_nothing_ends_the_run(world, monkeypatch):
    """Every site refusing us records nothing; running the pass again would
    meet the same refusal forever, so the run ends (launchd retries later)."""
    from tracker.platform.breaker import CircuitOpenError

    async def refused(company, scope, **_kw):
        raise CircuitOpenError(company.adapter, 5, blocked=True)

    monkeypatch.setattr(directory_sweep, "check_company", refused)
    await _follow(world)

    passes = await _run(pass_seconds=60, run_seconds=3600)

    checks, _ = await _rows(world)
    assert checks == {} and [p["checked"] for p in passes] == [0]


@pytest.mark.asyncio
async def test_a_breaker_opened_by_an_outage_waits_for_the_network(world, monkeypatch):
    """If every lane pauses before a read returns, the run must still probe for
    network recovery and preserve its cursors. With a working network, the
    same uniform refusal ends the run, as the control above asserts."""
    from tracker.platform.breaker import CircuitOpenError

    network = {"up": False}
    read: list[str] = []

    async def network_up(timeout=5.0):
        return network["up"]

    async def pause(seconds):
        network["up"] = True           # the connection returns while we wait

    async def check_company(company, scope, **_kw):
        read.append(company.slug)
        if not network["up"]:
            raise CircuitOpenError(company.adapter, 5, blocked=False)
        return directory_sweep.Check(company.slug, "ok", 1, 0)

    _one_lane_of(monkeypatch, 2)
    monkeypatch.setattr(directory_sweep, "network_up", network_up)
    monkeypatch.setattr(directory_sweep, "_pause", pause)
    monkeypatch.setattr(directory_sweep, "check_company", check_company)
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    checks, _ = await _rows(world)
    assert (passes[0]["offline"], passes[0]["paused"], passes[0]["checked"]) == (True, [], 0)
    assert read == ["co0", "co0", "co1"]
    assert set(checks) == {"co0", "co1"}


@pytest.mark.asyncio
async def test_once_one_lane_finds_the_network_down_no_lane_starts_a_read(world, monkeypatch):
    import asyncio

    companies = {c.slug: c for c in [
        _company(0, "g0"), _company(1, "a0", adapter="ashby"), _company(2, "g1"),
        _company(3, "a1", adapter="ashby"), _company(4, "a2", adapter="ashby"),
    ]}
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    network = {"up": True}
    read: list[str] = []

    async def network_up(timeout=5.0):
        return network["up"]

    async def check_company(company, scope, **_kw):
        read.append(company.slug)
        await asyncio.sleep(0)                 # both lanes are mid-read here
        if company.slug == "g0":
            network["up"] = False
            return directory_sweep.Check(company.slug, "failed", 0, 0, "ConnectError")
        return directory_sweep.Check(company.slug, "ok", 1, 0)

    monkeypatch.setattr(directory_sweep, "network_up", network_up)
    monkeypatch.setattr(directory_sweep, "check_company", check_company)
    await _follow(world)

    summary = await sweep_once(budget_seconds=600)

    assert summary["offline"] is True and sorted(read) == ["a0", "g0"]


@pytest.mark.asyncio
async def test_a_read_under_way_when_the_pass_ends_finishes_and_is_recorded(world, monkeypatch):
    """The pass's end stops new reads; it never cuts one, or a big board on a
    slow connection would be cut there every day."""
    _one_lane_of(monkeypatch, 3)
    read = _reads_take(monkeypatch, 400)          # one read outlasts the 60 s pass
    await _follow(world)

    first = await sweep_once(budget_seconds=60, clock=_TIME.pop("clock"))

    checks, _ = await _rows(world)
    assert read == ["co0"] and set(checks) == {"co0"} and first["checked"] == 1


@pytest.mark.asyncio
async def test_offline_records_nothing_waits_and_carries_on(world, monkeypatch):
    """A failed read while no job site answers is our network's failure, not
    the board's. It must not mark the board checked and defer it for a day."""
    network = {"up": True, "dropped": False}
    probes: list[bool] = []

    async def network_up(timeout=5.0):
        probes.append(network["up"])
        return network["up"]

    async def drop_during_co1(company):
        if company.slug == "co1" and not network["dropped"]:
            network["up"], network["dropped"] = False, True

    async def pause(seconds):
        network["up"] = True           # the connection returns while we wait

    _one_lane_of(monkeypatch, 3)
    read = _reads_take(monkeypatch, 10, outcome="failed", during=drop_during_co1)
    monkeypatch.setattr(directory_sweep, "network_up", network_up)
    monkeypatch.setattr(directory_sweep, "_pause", pause)
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    checks, _ = await _rows(world)
    assert (passes[0]["offline"], passes[0]["checked"]) == (True, 1)
    assert read == ["co0", "co1", "co1", "co2"], "the read the network cut is made again"
    assert {slug: c.outcome for slug, c in checks.items()} == {
        "co0": "failed", "co1": "failed", "co2": "failed"}, "online, a failure is the board's"
    assert probes == [True, False, False, True, True, True]


@pytest.mark.asyncio
async def test_stop_takes_effect_within_the_pass(world, monkeypatch):
    """Stop does not wait for the pass to end (up to 9 more minutes of reads)."""
    async def user_presses_stop(company):
        if company.slug == "co0":
            async with world["session_scope"]() as session:
                await set_follow(session, False, NOW)

    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 10, during=user_presses_stop)
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    assert passes[0]["interrupted"] == "the set was unfollowed" and read == ["co0", "co1"]
    assert passes[1:] == [{"ran": False, "reason": "the set is not followed"}]


@pytest.mark.asyncio
async def test_on_battery_the_scan_reads_nothing_and_says_why(world, monkeypatch):
    """Background directory reads wait for mains power so they do not drain
    the user's battery."""
    _one_lane_of(monkeypatch, 3)
    read = _reads_take(monkeypatch, 10)
    await _follow(world)
    machine(monkeypatch, batt=ON_BATTERY)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    assert read == [] and passes == [{"ran": False, "reason": WAITING_FOR_MAINS}]


@pytest.mark.asyncio
async def test_unplugging_ends_the_run_once_the_read_under_way_finishes(world, monkeypatch):
    async def unplugged(company):
        if company.slug == "co0":
            machine(monkeypatch, batt=ON_BATTERY)

    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 20, during=unplugged)
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    assert passes[0]["interrupted"] == WAITING_FOR_MAINS and read == ["co0"]
    assert passes[1:] == [{"ran": False, "reason": WAITING_FOR_MAINS}]


@pytest.mark.asyncio
async def test_after_a_sleep_the_pass_asks_before_its_next_read(world, monkeypatch):
    """A sleep stops the monotonic clock, not the wall one: a read that took
    1 s of it took a quarter of an hour on the wall when the lid shut during
    it. Asking only by the monotonic clock, the pass read on through the
    maintenance wake."""
    wall = [NOW]

    async def lid_shut(company):
        if company.slug == "co0":
            wall[0] += timedelta(minutes=15)
            machine(monkeypatch, systemstate=DARK_WAKE)

    _one_lane_of(monkeypatch, 5)
    read = _reads_take(monkeypatch, 1, during=lid_shut)
    _TIME["clock"] = dataclasses.replace(_TIME["clock"], wall=lambda: wall[0])
    await _follow(world)

    passes = await _run(pass_seconds=1000, run_seconds=3600)

    assert passes[0]["interrupted"] == WAITING_FOR_FULL_WAKE and read == ["co0"]
    assert passes[1:] == [{"ran": False, "reason": WAITING_FOR_FULL_WAKE}]


@pytest.mark.asyncio
async def test_the_register_says_the_scan_waits_for_mains_power(world, monkeypatch):
    """A progress line that stops moving on battery is said to wait, not left
    to read as a stalled scan."""
    async def waiting() -> bool:
        async with world["session_scope"]() as session:
            return (await directory_status(session))["waiting_for_power"]

    machine(monkeypatch, batt=ON_BATTERY)
    assert await waiting() is False, "not following: nothing waits"
    await _follow(world)
    assert await waiting() is True
    machine(monkeypatch)
    assert await waiting() is False


@pytest.mark.asyncio
async def test_a_find_after_stop_is_not_stored_so_following_again_reads_it(world):
    """Stored, it would keep the board current for a day with its roles
    unfollowed, and following again would not read it."""
    await _follow(world, True)
    await _follow(world, False)

    assert await directory_sweep._record(directory_sweep.Check("hiring", "ok", 3, 1), NOW) is False
    await directory_sweep._record(directory_sweep.Check("quiet", "ok", 3, 0), NOW)

    checks, tracked = await _rows(world)
    assert set(checks) == {"quiet"} and tracked == {}, "a find with no roles is stored as usual"


@pytest.mark.asyncio
async def test_each_pass_reports_its_lanes(world):
    await _follow(world)
    summary = await sweep_once(budget_seconds=60, clock=PassClock.at(NOW))
    lanes = summary["lanes"]
    assert {site: (r["checked"], r["finished"]) for site, r in lanes.items()} == {
        "greenhouse": (2, True), "ashby": (1, True), "lever": (1, True)}
    assert all(r["seconds"] >= 0 for r in lanes.values())


# --- reading only the places the radar can keep -------------------------------------


def _radar_at(*places, excepted=()):
    """Every level, kind and track of the two families on the SmartRecruiters
    fixture board, at these places: only the place axis varies."""
    return ScopeFilter(
        enabled_bands=frozenset(band.value for band in LevelBand),
        enabled_roles=frozenset({"program_management", "people_recruiting"}),
        enabled_tracks=frozenset(track.value for track in RoleTrack),
        enabled_locations=frozenset(places),
        enabled_domains=frozenset(),
        excluded_locations=frozenset(excepted),
        include_unstated_level=True,
    )


async def _read_board(monkeypatch, scope, *, hook=True, handler=None):
    """The fixture board (Roland Berger: 32 postings, Amsterdam's 19 needing one
    more-page) through `check_company` and the real adapter."""
    from tests.test_adapter_smartrecruiters import _board_handler
    from tracker.connectors import ADAPTER_REGISTRY
    from tracker.platform.breaker import BreakerPool
    from tracker.platform.ratelimit import RateLimiter, RateLimiterPool

    requests: list = []
    handler = handler or _board_handler()

    class Wired(ADAPTER_REGISTRY["smartrecruiters"]):
        async def __aenter__(self):
            await super().__aenter__()
            self._client = httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: (requests.append(r), handler(r))[1]),
                follow_redirects=True, headers=self.default_headers(),
            )
            self._limiter = RateLimiter(0)
            return self

    with monkeypatch.context() as patch:
        patch.setitem(ADAPTER_REGISTRY, "smartrecruiters", Wired)
        if not hook:
            patch.setattr(directory_sweep, "wanted_place", lambda _scope: None)
        check = await directory_sweep.check_company(
            _company(0, "roland-berger", adapter="smartrecruiters"), scope,
            limiter_pool=RateLimiterPool(), breaker_pool=BreakerPool(),
            stall_seconds=60, budget_seconds=60,
        )
    return check, [r for r in requests if r.url.path.endswith("/api/more")]


@pytest.mark.asyncio
@pytest.mark.parametrize("places,amsterdam_read", [
    (("netherlands",), True), (("europe",), True), (("belgium",), False),
    (("silicon_valley", "uk"), False), ((), False),
])
async def test_leaving_unwanted_places_unread_finds_exactly_what_a_full_read_finds(
    monkeypatch, places, amsterdam_read,
):
    """The radar keeps a posting when ANY of its places is in, so a posting at an
    unwanted place is found, if at all, through a place that is read in full."""
    full, full_more = await _read_board(monkeypatch, _radar_at(*places), hook=False)
    lean, lean_more = await _read_board(monkeypatch, _radar_at(*places))

    assert (lean.outcome, lean.roles_for_you) == (full.outcome, full.roles_for_you) == (
        "ok", {("netherlands",): 7, ("europe",): 10, ("belgium",): 3}.get(places, 0))
    assert len(full_more) == 1 and len(lean_more) == int(amsterdam_read)
    assert lean.unread_by_choice == (0 if amsterdam_read else 10)


@pytest.mark.asyncio
async def test_a_directory_read_across_a_sleep_that_finished_cleanly_still_counts(monkeypatch):
    """The directory's half of the one listing judgement: unlike
    the collector, a host suspension is not a cut here. A directory read
    closes nothing, it counts, and a read every page of which answered is a
    count. A suspended read that ALSO errored is `suspended` by the outcome
    derivation's own rule (`test_a_sleep_mid_read_is_ours_not_the_boards_failure`)."""

    class Slept:
        def __init__(self, **_kw):
            pass

        def suspended(self):
            return True

    monkeypatch.setattr(directory_sweep, "SuspensionMonitor", Slept)
    check, _ = await _read_board(monkeypatch, _radar_at("netherlands"))

    assert (check.outcome, check.roles_for_you, check.error) == ("ok", 7, None)


def _seventy_group_pages():
    """The fixture board stretched to 70 group pages, as the largest real
    boards are."""
    from tests.test_adapter_smartrecruiters import GROUPS1, INDEX, _board_handler

    base = _board_handler(index=INDEX.replace('data-groups-pages="2"', 'data-groups-pages="70"'))

    def handle(request):
        page = request.url.params.get("page")
        if request.url.path.endswith("/api/groups") and page and 1 <= int(page) < 70:
            return httpx.Response(200, text=GROUPS1)
        return base(request)

    return handle


@pytest.mark.asyncio
async def test_a_directory_read_pages_to_the_end_of_a_big_board(monkeypatch):
    """A directory read must enumerate the entire board: a fixed group-page
    ceiling would silently omit cities in the alphabetical tail."""
    from tests.test_adapter_smartrecruiters import _fetch, _wire
    from tracker.connectors import build_adapter

    check, _more = await _read_board(monkeypatch, _radar_at("europe"), handler=_seventy_group_pages())
    assert check.outcome == "ok", check.error

    # The collector keeps its own seed; it learns past it per company.
    adapter, requests = _wire(build_adapter("roland-berger", "smartrecruiters", board_token="RolandBerger"),
                              _seventy_group_pages())
    await _fetch(adapter)
    assert adapter.truncated
    assert max(int(r.url.params["page"]) for r in requests if r.url.path.endswith("/api/groups")) == 59


@pytest.mark.asyncio
async def test_a_radar_with_an_exception_reads_every_place(monkeypatch):
    """With "Europe but not Belgium" a posting's verdict depends on all its
    places, so leaving any unread could change it: nothing is left unread."""
    assert directory_sweep.wanted_place(_radar_at("europe", excepted=("belgium",))) is None
    check, more = await _read_board(monkeypatch, _radar_at("belgium", excepted=("brussels",)))
    assert len(more) == 1 and check.unread_by_choice == 0


# --- continuing a read our host cut -------------------------------------------------


def _not_looking_for_these(*places, excepted=()):
    """A radar at these places for a family the fake board has none of: every
    read of it is a zero-match read, the kind that leaves a cursor."""
    return dataclasses.replace(_radar_at(*places, excepted=excepted),
                               enabled_roles=frozenset({"software_engineering"}))


def _on_the_fake_board(monkeypatch, board, scope):
    """One SmartRecruiters company served by `board` through the real adapter
    and `check_company`; the radar is `scope`; the network is up while the
    board's connection is. Returns the radar, settable, and when the
    connection came back."""
    from tracker.connectors import ADAPTER_REGISTRY
    from tracker.connectors import build_adapter as real_build_adapter
    from tracker.platform.ratelimit import RateLimiter

    class Wired(ADAPTER_REGISTRY["smartrecruiters"]):
        max_retries = 0   # a dropped connection fails the request at once

        async def __aenter__(self):
            await super().__aenter__()
            self._client = httpx.AsyncClient(
                transport=httpx.MockTransport(board.handle), follow_redirects=True,
                headers=self.default_headers(),
            )
            self._limiter = RateLimiter(0)
            return self

    companies = {"fake": _company(0, "fake", adapter="smartrecruiters")}
    radar = {"scope": scope, "back_at": None}

    async def load_scope(_session):
        return radar["scope"]

    async def network_up(timeout=5.0):
        return not board.down

    async def pause(seconds):
        board.down, board.cut = False, None     # the connection comes back while we wait
        radar["back_at"] = datetime.now(UTC)

    monkeypatch.setitem(ADAPTER_REGISTRY, "smartrecruiters", Wired)
    monkeypatch.setattr(directory_sweep, "build_adapter", real_build_adapter)
    monkeypatch.setattr(company_directory, "directory", lambda: companies)
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    monkeypatch.setattr(directory_sweep, "load_scope_filter", load_scope)
    monkeypatch.setattr(directory_sweep, "network_up", network_up)
    monkeypatch.setattr(directory_sweep, "_pause", pause)
    return radar


async def _read_whole(board, scope):
    """The same board read once, start to end: what a read in parts must equal."""
    from tests.test_adapter_smartrecruiters import FakeBoard

    whole = FakeBoard({}, token=board.token)
    whole.groups = dict(board.groups)
    with pytest.MonkeyPatch.context() as patch:
        _on_the_fake_board(patch, whole, scope)
        return await directory_sweep.check_company(
            _company(0, "fake", adapter="smartrecruiters"), scope,
            limiter_pool=directory_sweep.RateLimiterPool(), breaker_pool=directory_sweep.BreakerPool(),
            stall_seconds=60, budget_seconds=60,
        )


@pytest.mark.asyncio
async def test_a_read_the_network_cut_continues_where_it_stopped_and_finds_what_one_read_finds(
    world, monkeypatch,
):
    """Read again from page one after an outage, a large board loses every
    request at every drop; on a connection that drops every few minutes it
    would never finish."""
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    # One posting at two places, one either side of the cut: one posting.
    board.list_also("Amsterdam, Netherlands", under="Frankfurt, Germany")
    scope = _not_looking_for_these("europe")
    radar = _on_the_fake_board(monkeypatch, board, scope)
    board.cut = _asks_group_page(2)
    await _follow(world)
    before_the_cut = datetime.now(UTC)

    passes = await _run(pass_seconds=600, run_seconds=3600)

    first_part = board.group_pages_asked().index(2) + 1
    checks, tracked = await _rows(world)
    whole = await _read_whole(board, scope)
    assert (passes[0]["offline"], passes[0]["checked"], passes[0]["cursors"]) == (True, 0, 1)
    assert (passes[1]["checked"], passes[1]["continued"], passes[1]["cursors"]) == (1, 1, 0)
    assert board.group_pages_asked()[first_part:] == [2, 1, 3, 4], "page 0 and 1 are not read again"
    check = checks["fake"]
    assert (check.outcome, check.scanned, check.roles_for_you) == ("ok", whole.scanned, 0)
    assert passes[1]["unread_by_choice"] == whole.unread_by_choice > 0
    assert before_the_cut <= check.checked_at < radar["back_at"], "dated by its first part"
    assert tracked == {}


@pytest.mark.asyncio
async def test_a_read_cut_after_its_last_page_finishes_complete_with_nothing_left_to_read(
    world, monkeypatch,
):
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    scope = _not_looking_for_these("europe")
    _on_the_fake_board(monkeypatch, board, scope)
    board.cut = _asks_group_page(4)            # the empty page that ends the board
    await _follow(world)

    passes = await _run(pass_seconds=600, run_seconds=3600)

    checks, _ = await _rows(world)
    whole = await _read_whole(board, scope)
    assert passes[1]["continued"] == 1
    assert (checks["fake"].outcome, checks["fake"].scanned) == ("ok", whole.scanned)


@pytest.mark.asyncio
async def test_a_read_cut_twice_is_dated_by_its_first_part(world, monkeypatch):
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    scope = _not_looking_for_these("europe")
    radar = _on_the_fake_board(monkeypatch, board, scope)
    first_back: list = []
    pause = directory_sweep._pause

    async def drops_again(seconds):
        await pause(seconds)
        if not first_back:
            first_back.append(radar["back_at"])
            board.cut = _asks_group_page(3)    # the continued read is cut too

    monkeypatch.setattr(directory_sweep, "_pause", drops_again)
    board.cut = _asks_group_page(2)
    await _follow(world)

    passes = await _run(pass_seconds=600, run_seconds=3600)

    checks, _ = await _rows(world)
    whole = await _read_whole(board, scope)
    assert [p.get("cursors") for p in passes[:3]] == [1, 1, 0] and passes[2]["continued"] == 1
    assert board.group_pages_asked() == [1, 2, 2, 1, 3, 3, 2, 4]
    assert checks["fake"].scanned == whole.scanned
    assert checks["fake"].checked_at < first_back[0], "the oldest part dates the check"


@pytest.mark.asyncio
async def test_a_role_found_before_the_cut_follows_the_company_at_once(world, monkeypatch):
    """The scan asks whether a board has a role for the radar; a role in the
    part read before the cut answers it. The radar keeps a posting for ANY of
    its places, so a role found on some of a posting's places is a role."""
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    _on_the_fake_board(monkeypatch, board, _radar_at("europe"))
    board.cut = _asks_group_page(2)
    await _follow(world)

    passes = await _run(pass_seconds=600, run_seconds=3600)

    checks, tracked = await _rows(world)
    assert (passes[0]["offline"], passes[0]["followed"], passes[0]["cursors"]) == (True, 1, 0)
    assert checks["fake"].outcome == "suspended" and checks["fake"].roles_for_you > 0, "ours, not the board's"
    assert tracked["fake"].source == "directory-set"
    assert board.group_pages_asked() == [1, 2], "followed: the scheduler reads it from here"


@pytest.mark.asyncio
async def test_a_new_radar_reads_a_cut_board_again_from_its_start(world, monkeypatch):
    """The part read before the cut left other places' pages unread and judged
    postings by the previous radar."""
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    radar = _on_the_fake_board(monkeypatch, board, _not_looking_for_these("europe"))
    board.cut = _asks_group_page(2)
    await _follow(world)
    first = await sweep_once(budget_seconds=600, cursors=(cursors := {}))
    board.down, board.cut = False, None
    radar["scope"] = _not_looking_for_these("united_states")
    asked = len(board.group_pages_asked())

    second = await sweep_once(budget_seconds=600, cursors=cursors)

    assert first["cursors"] == 1 and second["continued"] == 0
    assert board.group_pages_asked()[asked:] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_a_radar_with_an_exception_neither_follows_on_part_of_a_read_nor_continues_one(
    world, monkeypatch,
):
    """"Europe but not Germany" depends on every place a posting has: a part of
    the board cannot say a posting is in."""
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    _on_the_fake_board(monkeypatch, board, _radar_at("europe", excepted=("germany",)))
    board.cut = _asks_group_page(2)
    await _follow(world)

    passes = await _run(pass_seconds=600, run_seconds=3600)

    checks, _ = await _rows(world)
    assert (passes[0]["followed"], passes[0]["cursors"]) == (0, 0)
    assert board.group_pages_asked() == [1, 2, 1, 2, 3, 4], "read again whole"
    assert checks["fake"].outcome == "ok"


@pytest.mark.asyncio
async def test_a_sleep_mid_read_is_ours_not_the_boards_failure(world, monkeypatch):
    """The host sleeping lands as transport errors after it wakes, when the
    network is up again. Recorded as the board's failure, it would leave the
    board for a day."""
    from tests.test_adapter_smartrecruiters import _asks_group_page, _fake_board

    board = _fake_board()
    _on_the_fake_board(monkeypatch, board, _not_looking_for_these("europe"))

    class Slept:
        def __init__(self, **_kw):
            pass

        def suspended(self):
            return board.down

    async def network_up(timeout=5.0):
        board.down, board.cut = False, None     # awake: every host answers
        return True

    monkeypatch.setattr(directory_sweep, "SuspensionMonitor", Slept)
    monkeypatch.setattr(directory_sweep, "network_up", network_up)
    board.cut = _asks_group_page(2)
    await _follow(world)

    passes = await _run(pass_seconds=600, run_seconds=3600)

    checks, _ = await _rows(world)
    assert passes[0]["cursors"] == 1 and passes[1]["continued"] == 1
    assert checks["fake"].outcome == "ok"


def test_a_cursor_is_trusted_only_for_its_radar_its_day_and_a_company_still_the_scans():
    from tracker.connectors import ReadPosition
    from tracker.workflows.directory_sweep import Cursor, _still_trusted

    at = ReadPosition(at={"page": 1, "groups": [["Berlin, Germany", ["744000100000001"]]]},
                      listed=frozenset({"744000100000001"}))
    cursors = {
        "kept": Cursor(at, "radar-a", NOW - timedelta(hours=2)),
        "other-radar": Cursor(at, "radar-b", NOW - timedelta(hours=2)),
        "before-this-radar": Cursor(at, "radar-a", NOW - timedelta(hours=31)),
        "a-day-old": Cursor(at, "radar-a", NOW - due_after()),
        "followed-by-name": Cursor(at, "radar-a", NOW - timedelta(hours=2)),
    }

    # Each dropped cursor trips exactly one rule: the radar took over 30 h ago.
    _still_trusted(cursors, "radar-a", NOW - timedelta(hours=30), {"followed-by-name"}, NOW)

    assert set(cursors) == {"kept"}


# --- progress: when the first pass is over ---------------------------------------------


@pytest.mark.asyncio
async def test_the_line_counts_what_the_scan_holds_as_done(world, monkeypatch):
    """Counting only checks made since the switch went on, and only verdicts
    our bounds did not cut, leaves the line short for hours after the scan has
    read every company: boards read by the run before the switch-on (still
    current, so rightly skipped), and large boards a pass cut. A check counts while the scan would not
    read the board again: current at the switch-on, or made since."""
    companies = {c.slug: c for c in [
        _company(0, "read"), _company(1, "empty"), _company(2, "dead"), _company(3, "followed"),
        _company(4, "by-name"), _company(5, "cut"), _company(6, "current"),
        _company(7, "empty-last-week"), _company(8, "stale"),
    ]}
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    await _follow(world)   # since = NOW
    after = NOW + timedelta(hours=1)
    async with world["session_scope"]() as session:
        for slug, at, outcome, roles in [
            ("read", after, "ok", 0),
            ("empty", after, "empty", 0),
            ("dead", after, "failed", 0),
            ("followed", NOW - timedelta(days=3), "ok", 2),   # the set's row: never read again
            ("by-name", after, "ok", 1),                       # the user's own: not the set's
            ("cut", after, "bounded", 0),                      # our bound: read again tomorrow
            ("current", NOW - timedelta(hours=23), "ok", 0),   # read just before the switch
            ("empty-last-week", NOW - timedelta(days=6), "empty", 0),  # due like any other
            ("stale", NOW - timedelta(hours=25), "ok", 0),     # due: not done
            ("gone-from-directory", after, "ok", 0),           # dropped since: not a board to read
        ]:
            session.add(DirectoryCheck(slug=slug, checked_at=at, outcome=outcome,
                                       scanned=3, roles_for_you=roles))
        for slug, source in [
            ("followed", "directory-set"), ("by-name", "directory"),
            ("dropped", "directory-set"),      # the directory does not list it
        ]:
            session.add(TrackedCompany(slug=slug, display=slug, adapter="greenhouse", board_token=slug,
                                       status="active", enabled=True, visible=True, source=source))

    async with world["session_scope"]() as session:
        status = await directory_status(session)
    assert (status["size"], status["checked"], status["to_check"]) == (9, 6, 8)
    assert [c.slug for c in due_companies(
        companies.values(), {"current": NOW - timedelta(hours=23), "stale": NOW - timedelta(hours=25),
                             "empty-last-week": NOW - timedelta(days=6)},
        {"read", "empty", "dead", "followed", "by-name", "cut"}, NOW,
    )] == ["empty-last-week", "stale"], "exactly the companies the line does not count are due"

    async with world["session_scope"]() as session:
        for slug in ("empty-last-week", "stale"):
            check = await session.get(DirectoryCheck, slug)
            check.checked_at = after
    async with world["session_scope"]() as session:
        status = await directory_status(session)
    assert (status["checked"], status["to_check"]) == (8, 8), "the first pass is over"


@pytest.mark.asyncio
async def test_the_line_reaches_the_total_when_a_pass_finds_nothing_due(world):
    """A company read by the previous run, before the switch went on, is
    current, so no pass reads it, and the line must count it."""
    async with world["session_scope"]() as session:
        session.add(DirectoryCheck(slug="quiet", checked_at=datetime.now(UTC) - timedelta(hours=2),
                                   outcome="ok", scanned=1, roles_for_you=0))
        await set_follow(session, True, datetime.now(UTC))

    first = await sweep_once(budget_seconds=60)
    again = await sweep_once(budget_seconds=60)

    assert "quiet" not in world["built"] and first["checked"] == 3
    assert again["reason"] == "nothing due"
    async with world["session_scope"]() as session:
        status = await directory_status(session)
    assert status["checked"] == status["to_check"] == 4


@pytest.mark.asyncio
async def test_an_empty_board_is_read_again_after_a_day_like_any_other(world):
    """A board that starts hiring must not wait a week: empty boards do list
    postings again within days."""
    async with world["session_scope"]() as session:
        session.add(DirectoryCheck(slug="quiet", checked_at=datetime.now(UTC) - timedelta(hours=25),
                                   outcome="empty", scanned=0, roles_for_you=0))
        session.add(DirectoryCheck(slug="broken", checked_at=datetime.now(UTC) - timedelta(hours=23),
                                   outcome="empty", scanned=0, roles_for_you=0))
        await set_follow(session, True, datetime.now(UTC))

    await sweep_once(budget_seconds=60)

    assert "quiet" in world["built"] and "broken" not in world["built"]


# --- a new radar ---------------------------------------------------------------------


def test_the_radar_key_moves_with_what_can_admit_a_posting_and_nothing_else():
    from tracker.workflows.scope_filter import scope_fingerprint

    base = _radar_at("uk")
    assert scope_fingerprint(base) == scope_fingerprint(_radar_at("uk"))
    assert scope_fingerprint(base) != scope_fingerprint(_radar_at("uk", "silicon_valley"))
    assert scope_fingerprint(base) != scope_fingerprint(_radar_at("uk", excepted=("london",)))
    # A learned "not this team" only takes postings away: no re-read for it.
    learned = dataclasses.replace(base, company_exclusions=frozenset({("acme", "team", "sales")}))
    assert scope_fingerprint(learned) == scope_fingerprint(base)


@pytest.mark.asyncio
async def test_a_new_radar_reads_every_company_again_most_linked_first(world, monkeypatch):
    """A check made with another radar answered another question. Were a
    company read this morning to wait until tomorrow, widening the radar in
    the first hour would find nothing new for a day."""
    radar = {"scope": scope_for(_job("x", FITS))}

    async def scope(_session):
        return radar["scope"]

    monkeypatch.setattr(directory_sweep, "load_scope_filter", scope)
    async with world["session_scope"]() as session:
        await set_follow(session, True, datetime.now(UTC))
    await sweep_once(budget_seconds=60)
    assert (await sweep_once(budget_seconds=60))["reason"] == "nothing due"

    radar["scope"] = dataclasses.replace(radar["scope"], enabled_locations=frozenset({"uk"}))
    world["built"].clear()
    async with world["session_scope"]() as session:
        await directory_sweep.note_radar(session, radar["scope"], datetime.now(UTC))
        status = await directory_status(session)
    assert status["checked"] < status["to_check"], "the line starts again for the new radar"

    again = await sweep_once(budget_seconds=60)

    # Every company the scan holds is read again; the two it followed on the
    # first pass are the scheduler's now, which reads them by the new radar.
    assert sorted(world["built"]) == ["broken", "quiet"] and again["checked"] == 2
    async with world["session_scope"]() as session:
        status = await directory_status(session)
    assert status["checked"] == status["to_check"]


@pytest.mark.asyncio
async def test_the_first_radar_ever_recorded_trusts_the_checks_already_made(world):
    """Nothing older to distrust: the first pass that records a radar reads
    only what is due."""
    async with world["session_scope"]() as session:
        for slug in ("hiring", "quiet", "broken", "mine"):
            session.add(DirectoryCheck(slug=slug, checked_at=datetime.now(UTC) - timedelta(hours=1),
                                       outcome="ok", scanned=1, roles_for_you=0))
        await set_follow(session, True, datetime.now(UTC))

    assert (await sweep_once(budget_seconds=60))["reason"] == "nothing due"
    async with world["session_scope"]() as session:
        follow = await read_follow(session)
    assert follow["scope_key"] is not None and follow["scope_since"] is None


@pytest.mark.asyncio
async def test_a_switch_keeps_the_radar_its_checks_were_made_with(world):
    async with world["session_scope"]() as session:
        await set_follow(session, True, datetime.now(UTC))
    await sweep_once(budget_seconds=60)
    async with world["session_scope"]() as session:
        key = (await read_follow(session))["scope_key"]
        await set_follow(session, False, datetime.now(UTC))
        await set_follow(session, True, datetime.now(UTC))
        assert (await read_follow(session))["scope_key"] == key
    world["built"].clear()
    assert (await sweep_once(budget_seconds=60))["reason"] == "nothing due"


@pytest.mark.asyncio
async def test_saving_the_radar_starts_the_scan_only_while_the_set_is_followed(
    api_client, db_session, monkeypatch, no_escape,
):
    from tracker.api.routers import settings as settings_router

    started: list[bool] = []

    async def ring_directory(_session, *, requested_by):
        started.append(True)

    monkeypatch.setattr(settings_router.job_requests, "ring_directory", ring_directory)
    body = {
        "enabled_role_groups": [], "enabled_seniority_bands": ["staff"],
        "enabled_location_groups": ["uk"],
        "role_answers": [{"track": "technical", "roles": "any"}],
    }
    assert (await api_client.put("/api/settings", json=body)).status_code == 200
    assert started == []

    await set_follow(db_session, True, datetime.now(UTC))
    await db_session.commit()
    saved = await api_client.put("/api/settings", json={**body, "enabled_location_groups": ["united_states"]})
    assert saved.status_code == 200, saved.text
    assert started == [True]


# --- following and unfollowing the set ----------------------------------------------------------


@pytest.mark.asyncio
async def test_unfollowing_stops_the_sets_companies_and_following_again_restores_only_those(world):
    async with world["session_scope"]() as session:
        for slug, source, enabled in [
            ("hiring", "directory-set", True),
            ("mine", "directory-set", True),
            ("quiet", "directory-set", False),     # the user switched this one off
            ("by-name", "directory", True),         # followed on its own
        ]:
            session.add(TrackedCompany(slug=slug, display=slug, adapter="greenhouse", board_token=slug,
                                       status="active", enabled=enabled, visible=True, source=source))
    await _follow(world, True)
    await _follow(world, False)

    _, tracked = await _rows(world)
    assert {s for s, t in tracked.items() if t.enabled} == {"by-name"}
    async with world["session_scope"]() as session:
        assert (await read_follow(session))["stopped"] == ["hiring", "mine"]

    await _follow(world, True)
    _, tracked = await _rows(world)
    assert {s for s, t in tracked.items() if t.enabled} == {"by-name", "hiring", "mine"}
    assert tracked["quiet"].enabled is False


@pytest.mark.asyncio
async def test_following_again_restores_no_board_the_directory_no_longer_lists(world):
    """Unfollowing remembers a board, and following must not restore that
    memory without asking whether the board is still listed (Monzo's referral
    board, `referrals-only-greenhouse`, excluded from the directory). A board
    the monthly rebuild dropped, or a reviewed exclusion removed, stays
    unfollowed; its row and postings are kept."""
    async with world["session_scope"]() as session:
        for slug in ("hiring", "referrals-only-greenhouse"):
            session.add(TrackedCompany(slug=slug, display=slug, adapter="greenhouse", board_token=slug,
                                       status="active", enabled=True, visible=True, source="directory-set"))
    await _follow(world, True)
    await _follow(world, False)
    async with world["session_scope"]() as session:
        assert (await read_follow(session))["stopped"] == ["hiring", "referrals-only-greenhouse"]

    await _follow(world, True)

    _, tracked = await _rows(world)
    assert tracked["hiring"].enabled is True
    assert tracked["referrals-only-greenhouse"].enabled is False
    async with world["session_scope"]() as session:
        assert (await read_follow(session))["stopped"] == []


@pytest.mark.asyncio
async def test_the_set_never_adds_a_company_the_catalog_already_offers(world, monkeypatch):
    """`follow_with_set` resolves through the catalog first, which is a decision."""
    from tracker.company_store import follow_with_set

    monkeypatch.setattr(company_directory, "directory", lambda: {"stripe": _company(0, "stripe")})
    async with world["session_scope"]() as session:
        assert await follow_with_set(session, "stripe") is None
        assert await follow_with_set(session, "not-in-the-directory") is None


# --- over HTTP --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_register_reads_the_set_and_follows_it_in_one_switch(api_client, db_session, monkeypatch, no_escape):
    companies = {c.slug: c for c in [_company(0, "a"), _company(1, "b"), _company(2, "c")]}
    monkeypatch.setattr(company_directory, "directory", lambda: companies)
    monkeypatch.setattr(directory_sweep, "directory", lambda: companies)
    started: list[bool] = []

    async def ring_directory(_session, *, requested_by):
        started.append(True)

    monkeypatch.setattr(companies_router.job_requests, "ring_directory", ring_directory)
    await seed_company_contract(db_session)

    before = (await api_client.get("/api/companies/directory/status")).json()
    assert before == {"size": 3, "following": False, "since": None, "checked": 0,
                      "to_check": 3, "with_roles": 0, "waiting_for_power": False}

    followed = await api_client.put("/api/companies/directory/follow", json={"following": True})
    assert followed.status_code == 200, followed.text
    body = followed.json()
    assert body["following"] is True and body["since"] is not None and body["checked"] == 0
    assert started == [True], "the switch starts the scan now, not at the next tick"

    db_session.add(DirectoryCheck(slug="a", checked_at=datetime.now(UTC), outcome="ok",
                                  scanned=4, roles_for_you=1))
    db_session.add(TrackedCompany(slug="a", display="A", adapter="greenhouse", board_token="a",
                                  status="active", enabled=True, visible=True, source="directory-set"))
    await db_session.commit()
    during = (await api_client.get("/api/companies/directory/status")).json()
    assert (during["checked"], during["with_roles"], during["waiting_for_power"]) == (1, 1, False)
    machine(monkeypatch, batt=ON_BATTERY)
    unplugged = (await api_client.get("/api/companies/directory/status")).json()
    assert unplugged["waiting_for_power"] is True, "the register says the scan waits"
    machine(monkeypatch)

    stopped = (await api_client.put("/api/companies/directory/follow", json={"following": False})).json()
    assert (stopped["following"], stopped["with_roles"]) == (False, 0)
    assert started == [True], "stopping starts nothing"
    roster = (await api_client.get("/api/companies/discovery")).json()
    assert next(c for c in roster["companies"] if c["slug"] == "a")["enabled"] is False
