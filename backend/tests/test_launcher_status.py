"""Shared projection cases and the HTTP identity used before browser opening."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tracker.api.schemas.ops import LauncherPresentation, LauncherScan
from tracker.db.models import JobStatus, ScrapeRun
from tracker.semantic import embed, provision
from tracker.workflows.launcher_status import project_status

CASES = json.loads((Path(__file__).resolve().parents[2] / "launcher/contracts/status-cases.json").read_text())
pytestmark = pytest.mark.usefixtures("no_escape")


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda case: case["name"])
def test_shared_status_contract(case):
    result = project_status(case["facts"], now=datetime.fromisoformat(CASES["now"]),
                            model=case["model"], reembed_executing=case["reembed_executing"])
    wire = LauncherPresentation.model_validate(result).model_dump(mode="json")
    assert {key: wire[key] for key in case["expected"]} == case["expected"]
    assert wire["observed_at"] == CASES["now"]
    assert wire == case["wire"]
    if wire["activity"] == "idle":
        assert wire["activity_since"] is None


@pytest.mark.asyncio
async def test_http_identity_uses_configured_port_and_preserves_hold_with_pending_work(api_client, monkeypatch):
    import tracker.api.routers.ops as ops

    settings = ops.get_settings().model_copy(update={"api_host": "127.0.0.1", "api_port": 58221})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    body = response.json()
    launcher = body["launcher"]
    assert launcher["product"] == "roleband" and launcher["format"] == 1
    assert len(launcher["instance"]) == 24
    assert launcher["api_origin"] == "http://127.0.0.1:58221"
    assert launcher["status"]["hold"] == {"kind": "attention", "reason": "supervisor_absent"}
    assert launcher["status"]["activity"] == "idle"


async def _launcher_status(api_client, monkeypatch, **settings_update):
    import tracker.api.routers.ops as ops

    settings = ops.get_settings().model_copy(update={"api_host": "127.0.0.1", "api_port": 58221, **settings_update})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    return response.json()["launcher"]["status"]


@pytest.mark.asyncio
async def test_http_status_reads_real_rows_for_holds_last_scan_and_model(api_client, db_session, monkeypatch, tmp_path):
    # An empty models folder, whatever this machine has downloaded.
    monkeypatch.setattr(provision, "models_dir", lambda: tmp_path / "models")
    now = datetime.now(UTC)
    finished = now - timedelta(hours=2)
    db_session.add_all([
        JobStatus(key="supervisor", job="supervisor", state="running", since=now - timedelta(hours=1)),
        # Idle jobs keep their last run's reason; neither is a hold now.
        JobStatus(key="scan", job="scan", state="idle", since=now, detail={"last": {"kind": "busy", "reason": "busy_external"}}),
        JobStatus(key="reestimate", job="reestimate", state="idle", since=now,
                  detail={"last": {"kind": "refused", "reason": "preflight_failed"}}),
        ScrapeRun(started_at=finished - timedelta(minutes=20), finished_at=finished, status="partial", scope="full"),
        ScrapeRun(started_at=now - timedelta(minutes=5), heartbeat_at=now, status="running", scope="full"),
    ])
    await db_session.commit()

    status = await _launcher_status(api_client, monkeypatch, search_semantic_enabled=False)
    assert status["hold"] is None
    assert status["activity"] == "scanning"
    assert status["model"] == "unused"
    # The live run has no finish yet: the last scan is the newest finished one.
    assert datetime.fromisoformat(status["last_scan_at"]) == finished
    assert status["last_scan_outcome"] == "partial"

    status = await _launcher_status(api_client, monkeypatch, search_semantic_enabled=True)
    assert status["model"] == "missing"
    assert status["hold"] == {"kind": "attention", "reason": "model_missing"}

    db_session.add(JobStatus(key="reestimate:wait", job="reestimate", state="waiting", reason="waiting_for_mains", since=now))
    await db_session.commit()
    status = await _launcher_status(api_client, monkeypatch, search_semantic_enabled=False)
    assert status["hold"] == {"kind": "waiting", "reason": "waiting_for_mains"}


@pytest.mark.asyncio
async def test_remote_bind_configuration_keeps_existing_status_available_without_local_discovery(api_client, monkeypatch):
    import tracker.api.routers.ops as ops

    settings = ops.get_settings().model_copy(update={"api_host": "192.168.1.2"})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    assert response.json()["launcher"] is None
    assert response.json()["db"] == "ok"


@pytest.mark.asyncio
async def test_warming_is_live_execution_and_resets_after_failure(monkeypatch):
    from tracker.db import session

    @asynccontextmanager
    async def unavailable():
        raise OSError("test database unavailable")
        yield

    started, release = threading.Event(), threading.Event()
    calls = []

    def download(*args):
        calls.append(embed.model_warming())
        started.set()
        assert release.wait(5)
        raise OSError("download failed")

    monkeypatch.setattr(session, "session_scope", unavailable)
    monkeypatch.setattr(provision, "ensure_artifacts", download)
    task = asyncio.create_task(embed.warm_model())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert embed.model_warming()
        await embed.warm_model()
        assert calls == [True]
    finally:
        release.set()
        await task
    assert not embed.model_warming()


_NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
_OFF = {"scheduling": "off", "paused_until": None, "next_scan_at": None}


def _progress(*rows, **counts):
    return {"phase": "collecting", "percent": 38, "companies_total": 12, "opportunities_pending": 214, "opportunities_recorded": 498,
            **counts, "companies": list(rows)}


def test_scan_picture_shows_the_five_longest_running_companies_by_their_names():
    from tracker.workflows.launcher_status import project_scan

    rows = [{"slug": f"c{n}", "state": "scraping", "since_ms": 1_700_000_000_000 + n * 1000} for n in range(7)]
    rows += [
        {"slug": "early", "state": "recorded", "since_ms": 1_600_000_000_000},
        {"slug": "waiting", "state": "queued", "since_ms": None},
        {"slug": "broken", "state": "scraping", "since_ms": "soon"},
        "not a row",
    ]
    scan = project_scan(progress=_progress(*reversed(rows[:7]), *rows[7:]), names={"c0": "Nvidia", "c1": ""},
                        last_finished=None, stopped_note="cancelled by user", schedule=_OFF, now=_NOW)
    assert [company["name"] for company in scan["in_flight"]] == ["Nvidia", "c1", "c2", "c3", "c4"]
    assert scan["in_flight"][0]["since"] == datetime.fromtimestamp(1_700_000_000, UTC)
    assert (scan["phase"], scan["percent"], scan["companies_total"], scan["roles_pending"], scan["roles_recorded"]) == (
        "collecting", 38, 12, 214, 498)
    assert scan["last_companies"] is None and scan["last_stopped"] is False

    odd = project_scan(progress=_progress(percent=140, opportunities_pending=-3, companies_total=True), names={},
                       last_finished=None, stopped_note="cancelled by user", schedule=_OFF, now=_NOW)
    assert (odd["percent"], odd["roles_pending"], odd["companies_total"], odd["in_flight"]) == (100, None, None, [])
    garbled = project_scan(progress={"companies": 5, "percent": "38", "phase": "tidying"}, names={}, last_finished=None,
                           stopped_note="cancelled by user", schedule=_OFF, now=_NOW)
    assert (garbled["in_flight"], garbled["percent"], garbled["phase"]) == ([], None, None)


def test_scan_picture_says_when_every_company_is_read_and_the_scan_is_finishing():
    from tracker.workflows.launcher_status import project_scan

    # After the last company is written the run keeps going through its after-scan passes,
    # with nothing in flight and the company-weighted percent already at 100.
    done = [{"slug": f"c{n}", "state": "recorded", "since_ms": 1_700_000_000_000} for n in range(3)]
    for stage in ("persisting", "finishing"):
        scan = project_scan(progress=_progress(*done, phase=stage, percent=100, opportunities_pending=0),
                            names={}, last_finished=None, stopped_note="cancelled by user", schedule=_OFF, now=_NOW)
        assert (scan["phase"], scan["percent"], scan["in_flight"]) == (stage, 100, [])
        assert LauncherScan.model_validate(scan).model_dump(mode="json")["phase"] == stage


def test_scan_picture_without_a_live_scan_names_the_last_one_and_whether_the_person_stopped_it():
    from tracker.workflows.launcher_status import project_scan

    plan = {"scheduling": "plan", "paused_until": None, "next_scan_at": datetime(2026, 10, 31, 15, tzinfo=UTC)}
    finished = {"companies": 3, "new_roles": 18, "jobs_seen": 712, "notes": None}
    scan = project_scan(progress=None, names={}, last_finished=finished, stopped_note="cancelled by user",
                        schedule=plan, now=_NOW)
    wire = LauncherScan.model_validate(scan).model_dump(mode="json")
    assert wire == {"phase": None, "percent": None, "companies_total": None, "in_flight": [], "roles_pending": None,
                    "roles_recorded": None, "last_companies": 3, "last_new_roles": 18, "last_postings": 712,
                    "last_stopped": False, "next_scan_at": "2026-10-31T15:00:00Z", "scheduling": "plan",
                    "paused_until": None}
    stopped = project_scan(progress=None, names={}, last_finished={**finished, "notes": "cancelled by user"},
                           stopped_note="cancelled by user", schedule=_OFF, now=_NOW)
    assert stopped["last_stopped"] is True and stopped["next_scan_at"] is None


def test_a_next_scan_already_due_reads_now_never_a_time_before_it():
    from tracker.workflows.launcher_status import project_scan

    # The status keeps its schedule read for a while, so a run due when it was read is
    # in the past by the time a later read projects it.
    due = {"scheduling": "plan", "paused_until": None, "next_scan_at": _NOW - timedelta(seconds=20)}
    scan = project_scan(progress=None, names={}, last_finished=None, stopped_note="cancelled by user",
                        schedule=due, now=_NOW)
    assert scan["next_scan_at"] == _NOW
    paused = {"scheduling": "plan", "paused_until": _NOW + timedelta(hours=3),
              "next_scan_at": _NOW + timedelta(hours=3)}
    scan = project_scan(progress=None, names={}, last_finished=None, stopped_note="cancelled by user",
                        schedule=paused, now=_NOW)
    assert (scan["scheduling"], scan["paused_until"], scan["next_scan_at"]) == (
        "plan", _NOW + timedelta(hours=3), _NOW + timedelta(hours=3))


@pytest.mark.asyncio
async def test_http_scan_picture_reads_the_live_carrier_and_the_last_finished_run(api_client, db_session, monkeypatch):
    from sqlalchemy import select

    from tests.factories import make_company
    from tracker.connectors.recipes.outcome import STOPPED_BY_USER_NOTE
    from tracker.db.models import Notification

    now = datetime.now(UTC)
    started_ms = int((now - timedelta(seconds=148)).timestamp() * 1000)
    finished = ScrapeRun(started_at=now - timedelta(hours=3), finished_at=now - timedelta(hours=2), status="partial",
                         scope="full", jobs_new=7, jobs_seen=301, per_source={"nvidia": {}, "apple": {}},
                         notes=STOPPED_BY_USER_NOTE)
    live = ScrapeRun(started_at=now - timedelta(minutes=3), heartbeat_at=now, status="running", scope="full")
    db_session.add_all([finished, live, make_company("nvidia", "Nvidia")])
    await db_session.commit()

    status = await _launcher_status(api_client, monkeypatch)
    assert status["activity"] == "scanning"
    launcher = (await api_client.get("/api/status")).json()["launcher"]
    assert launcher["scan"]["in_flight"] == [] and launcher["scan"]["percent"] is None
    # The run's own count of inserted postings is not what the New board lists: no role
    # it counted is on the board, so the picture says none.
    assert (launcher["scan"]["last_companies"], launcher["scan"]["last_new_roles"],
            launcher["scan"]["last_postings"], launcher["scan"]["last_stopped"]) == (2, 0, 301, True)

    db_session.add(Notification(
        created_at=now, priority="low", category="sync_started", title="Scanning", body=None, job_id=None,
        run_id=live.id, source_type="run", source_id=live.id,
        meta={"progress": _progress({"slug": "nvidia", "state": "scraping", "since_ms": started_ms},
                                    {"slug": "unlisted", "state": "scraping", "since_ms": started_ms + 5000})},
    ))
    await db_session.commit()
    scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    assert [company["name"] for company in scan["in_flight"]] == ["Nvidia", "unlisted"]
    assert abs(datetime.fromisoformat(scan["in_flight"][0]["since"]).timestamp() * 1000 - started_ms) < 1
    assert (scan["phase"], scan["percent"], scan["roles_pending"], scan["roles_recorded"]) == ("collecting", 38, 214, 498)

    # Every company written, the after-scan passes still running: the picture says so.
    notice = (await db_session.scalars(select(Notification).where(Notification.run_id == live.id))).one()
    notice.meta = {"progress": _progress({"slug": "nvidia", "state": "recorded", "since_ms": started_ms},
                                         phase="finishing", percent=100, opportunities_pending=0)}
    await db_session.commit()
    scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    assert (scan["phase"], scan["percent"], scan["in_flight"], scan["roles_recorded"]) == ("finishing", 100, [], 498)

    live.status, live.finished_at = "ok", now
    await db_session.commit()
    scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    assert scan["percent"] is None and scan["phase"] is None and scan["in_flight"] == []
    assert scan["last_stopped"] is False


@contextmanager
def _fetched_values():
    """Every value a request's statements bring back from the database, loaded ORM
    attributes included."""
    from sqlalchemy import event, inspect
    from sqlalchemy.orm import Session

    values: list = []

    def record(state):
        result = state.invoke_statement().freeze()
        for row in result().all():
            for value in row:
                mapped = inspect(value, raiseerr=False)
                values.extend(mapped.dict.values() if mapped is not None else [value])
        return result()

    event.listen(Session, "do_orm_execute", record)
    try:
        yield values
    finally:
        event.remove(Session, "do_orm_execute", record)


@pytest.mark.asyncio
async def test_a_status_poll_during_a_scan_reads_neither_the_whole_carrier_nor_the_last_runs_per_source(
    api_client, db_session,
):
    from tests.factories import make_company
    from tracker.db.models import Notification

    now = datetime.now(UTC)
    started_ms = int((now - timedelta(seconds=90)).timestamp() * 1000)
    touched = [{"slug": f"touched-{n}", "state": "recorded", "outcome": "ok", "scanned": 40, "since_ms": started_ms}
               for n in range(600)]
    finished = ScrapeRun(started_at=now - timedelta(hours=3), finished_at=now - timedelta(hours=2), status="ok",
                         scope="full", jobs_new=0, jobs_seen=900,
                         per_source={f"read-{n}": {"new": 0, "errors": []} for n in range(450)})
    live = ScrapeRun(started_at=now - timedelta(minutes=3), heartbeat_at=now, status="running", scope="full")
    db_session.add_all([finished, live, make_company("nvidia", "Nvidia")])
    await db_session.flush()
    db_session.add(Notification(
        created_at=now, priority="low", category="sync_started", title="Scanning", body=None, job_id=None,
        run_id=live.id, source_type="run", source_id=live.id,
        meta={"sources": [row["slug"] for row in touched],
              "progress": _progress(*touched, {"slug": "nvidia", "state": "scraping", "since_ms": started_ms})},
    ))
    await db_session.commit()

    with _fetched_values() as values:
        scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    assert [company["name"] for company in scan["in_flight"]] == ["Nvidia"]
    assert (scan["percent"], scan["last_companies"], scan["last_postings"]) == (38, 450, 900)
    fetched = json.dumps(values, default=str)
    assert "touched-" not in fetched
    assert "read-" not in fetched


@pytest.mark.parametrize("progress", [
    _progress({"slug": "nvidia", "state": "scraping", "since_ms": 1_700_000_000_000},
              5, "nvidia", None, ["nvidia"], {"slug": "apple", "state": "recorded", "since_ms": 1_600_000_000_000},
              {"slug": "apple", "state": "scraping", "since_ms": "soon"}, {"state": "scraping", "since_ms": 1}),
    {**_progress(), "companies": {"slug": "nvidia", "state": "scraping", "since_ms": 1_700_000_000_000}},
    {"companies": [{"slug": "nvidia", "state": "scraping", "since_ms": 1_700_000_000_000}], "percent": "38"},
    [{"slug": "nvidia", "state": "scraping", "since_ms": 1_700_000_000_000}],
    "scanning",
], ids=["odd-rows", "companies-not-a-list", "counts-only-partly-there", "progress-a-list", "progress-a-string"])
@pytest.mark.asyncio
async def test_the_scan_picture_reads_a_malformed_carrier_as_the_projection_does(api_client, db_session, progress):
    from tests.factories import make_company
    from tracker.db.models import Notification
    from tracker.workflows.launcher_status import project_scan

    now = datetime.now(UTC)
    live = ScrapeRun(started_at=now - timedelta(minutes=3), heartbeat_at=now, status="running", scope="full")
    db_session.add_all([live, make_company("nvidia", "Nvidia")])
    await db_session.flush()
    db_session.add(Notification(
        created_at=now, priority="low", category="sync_started", title="Scanning", body=None, job_id=None,
        run_id=live.id, source_type="run", source_id=live.id, meta={"progress": progress},
    ))
    await db_session.commit()

    served = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    projected = project_scan(progress=progress, names={"nvidia": "Nvidia"}, last_finished=None,
                             stopped_note="", schedule=_OFF, now=now)
    projected = LauncherScan.model_validate(projected).model_dump(mode="json")
    for key in ("percent", "companies_total", "in_flight", "roles_pending", "roles_recorded"):
        assert served[key] == projected[key], key


async def _pinned_launcher(api_client, monkeypatch, tmp_path, **settings_update) -> dict:
    import tracker.api.routers.ops as ops
    import tracker.workflows.scheduler as scheduler
    from tests.ops_contract_seed import pin_ops_environment

    pin_ops_environment(monkeypatch, tmp_path)
    settings = ops.get_settings().model_copy(update={"api_host": "127.0.0.1", "api_port": 58221, **settings_update})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_next_scan_is_the_plans_next_run_never_a_stale_company_deadline(
    api_client, db_session, monkeypatch, tmp_path
):
    from sqlalchemy import update

    from tests.ops_contract_seed import NOW, seed_ops_contract
    from tracker.db.models import SchedulePlanRun, SyncScheduleState

    seeded = await seed_ops_contract(db_session, roster="fresh")
    # The plan read the whole roster an hour ago; Acme's own deadline stayed two days behind.
    await db_session.execute(update(SyncScheduleState).where(SyncScheduleState.binding_id == seeded.bindings["acme"])
                             .values(next_reconcile_at=NOW - timedelta(days=2),
                                     next_discovery_at=NOW - timedelta(days=2)))
    db_session.add(SchedulePlanRun(kind="full", started_at=NOW - timedelta(hours=1, minutes=20),
                                   finished_at=NOW - timedelta(hours=1), companies=3, roster=3, outcome="ok"))
    await db_session.commit()

    body = await _pinned_launcher(api_client, monkeypatch, tmp_path)
    scan = body["launcher"]["scan"]
    assert datetime.fromisoformat(body["scheduler"]["next_due_at"]) < NOW - timedelta(days=1)
    plan = (await api_client.get("/api/schedule", params={"tz": "UTC"})).json()["plan"]
    planned = next(run["at"] for run in plan["upcoming"] if not run["running"])
    assert datetime.fromisoformat(scan["next_scan_at"]) == datetime.fromisoformat(planned) > NOW
    assert (scan["scheduling"], scan["paused_until"]) == ("plan", None)

    # A pause shows on the very next read, and the next scan waits for its end.
    paused = await api_client.put("/api/schedule/plan", json={"pause": "3h"}, params={"tz": "UTC"})
    assert paused.status_code == 200, paused.text
    scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    assert datetime.fromisoformat(scan["paused_until"]) == NOW + timedelta(hours=3)
    assert datetime.fromisoformat(scan["next_scan_at"]) >= NOW + timedelta(hours=3)


@pytest.mark.asyncio
async def test_scheduling_reads_the_scheduler_switch_and_each_companys_own_timer_without_the_plan(
    api_client, db_session, monkeypatch, tmp_path
):
    from sqlalchemy import update

    from tests.ops_contract_seed import NOW, seed_ops_contract
    from tracker.db.models import SyncScheduleState

    seeded = await seed_ops_contract(db_session, roster="fresh")
    await db_session.execute(update(SyncScheduleState).where(SyncScheduleState.binding_id == seeded.bindings["acme"])
                             .values(next_reconcile_at=NOW - timedelta(days=2)))
    await db_session.commit()

    # Without the plan each company keeps its own timer, and an overdue one is due now.
    scan = (await _pinned_launcher(api_client, monkeypatch, tmp_path,
                                   sync_schedule_plan_enabled=False))["launcher"]["scan"]
    assert (scan["scheduling"], scan["paused_until"]) == ("timers", None)
    assert datetime.fromisoformat(scan["next_scan_at"]) == NOW

    scan = (await _pinned_launcher(api_client, monkeypatch, tmp_path,
                                   sync_scheduler_enabled=False))["launcher"]["scan"]
    assert (scan["scheduling"], scan["paused_until"], scan["next_scan_at"]) == ("off", None, None)


@pytest.mark.asyncio
async def test_new_roles_are_the_roles_the_new_board_lists_from_the_last_scan(api_client, db_session):
    from tests.factories import make_company, make_job
    from tracker.db.models import JobLifecycleEvent

    now = datetime.now(UTC)

    async def run(started: datetime, *opened: tuple[str, str, dict]) -> ScrapeRun:
        row = ScrapeRun(started_at=started, finished_at=started + timedelta(minutes=5), status="ok", scope="full",
                        jobs_new=len(opened), jobs_seen=len(opened), per_source={"google": {}, "hiddenco": {}})
        db_session.add(row)
        await db_session.flush()
        for company, req_id, over in opened:
            job = make_job(req_id, company=company, first_seen=started, last_seen=started, **over)
            db_session.add(job)
            await db_session.flush()
            db_session.add(JobLifecycleEvent(job_id=job.id, run_id=row.id, event_type="opened", created_at=started))
        await db_session.commit()
        return row

    db_session.add(make_company("hiddenco", "Hidden Co", visible=False))
    # Each company's first read reads a board that was already listing.
    await run(now - timedelta(minutes=30), ("google", "listed", {"arrival": "first_read"}),
              ("hiddenco", "h1", {"arrival": "first_read"}))
    scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    assert scan["last_new_roles"] == 0

    await run(now, ("google", "fresh", {"arrival": "new"}),
              ("google", "outside", {"in_scope": False, "arrival": "new"}), ("hiddenco", "h2", {"arrival": "new"}))
    scan = (await api_client.get("/api/status")).json()["launcher"]["scan"]
    lens = (await api_client.get("/api/jobs", params={"limit": 100, "new_today_only": "true"})).json()
    assert scan["last_new_roles"] == lens["total"] == 1


SCAN_CASES = json.loads((Path(__file__).resolve().parents[2] / "launcher/contracts/scan-cases.json").read_text())


@pytest.mark.parametrize("case", SCAN_CASES["cases"], ids=lambda case: case["name"])
def test_shared_scan_cases_are_exactly_what_the_schema_serves(case):
    assert LauncherScan.model_validate(case["wire"]).model_dump(mode="json") == case["wire"]
