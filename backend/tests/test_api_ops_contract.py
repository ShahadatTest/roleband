"""The operational surface's response contract.

`tracker/api/schemas/ops.py` declares what the six ops routes send. These tests
hold it to its sources:

1. **Vocabulary**: the literals are the scheduler's own constants and the
   derived `SourceOutcome`; strings read back from tables with no CHECK
   constraint stay strings.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/ops_contract_seed.py`) with the ops clock and settings pinned:
   each shape's exact keys, the freshness judgement in each roster, the run log
   as stored, the picker's per-company verdicts, every sync and cancel branch
   read back, and each refused sync leaving the database exactly as it was.
3. **Drift in both directions**: a key or a value the serializer produces
   without its model fails the response instead of reaching a client.

The scheduler's bindings query has no ORDER BY, so `overdue` and `excluded` are
compared as sets.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import CheckConstraint, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.api_errors import said
from tests.ops_contract_seed import (
    LIVE_GROUP,
    NOW,
    _binding,
    _company,
    pin_ops_environment,
    seed_ops_contract,
)
from tests.ops_contract_seed import (
    _schedule as _schedule_row,
)
from tracker.api.routers import ops as ops_router
from tracker.api.schemas import ops as contract
from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.models import (
    DerivationState,
    JobRun,
    Notification,
    ProviderPressureState,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    SyncScheduleState,
    TrackedCompany,
)
from tracker.workflows.post_passes import POST_PASSES
from tracker.workflows.schedule_status import BOARD_MISSING, UNREAD_REASONS, WAITS_FOR_USER
from tracker.workflows.scheduler import BACKOFF, PAUSED, POLICY_DENIED

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

# --------------------------------------------------------------------------- #
# 1. Vocabulary
# --------------------------------------------------------------------------- #


def test_the_literals_are_the_scheduler_constants_and_the_derived_outcome():
    assert set(get_args(contract.ExcludedBinding.model_fields["reason"].annotation)) == {
        PAUSED, POLICY_DENIED, *WAITS_FOR_USER, BOARD_MISSING,
    }
    assert set(get_args(contract.ManualSyncBlock.model_fields["reason"].annotation)) == {
        PAUSED, POLICY_DENIED, BACKOFF,
    }
    assert set(get_args(contract.UnreadBinding.model_fields["reason"].annotation)) == UNREAD_REASONS
    assert contract.SyncTarget.model_fields["last_outcome"].annotation == SourceOutcome | None


@pytest.mark.parametrize(
    ("table", "fields"),
    [
        (ScrapeRun, [(contract.RunRow, "status")]),
        (DerivationState, [(contract.DerivationEnabled, "last_status")]),
        (ProviderPressureState, [(contract.ProviderPressure, "state"), (contract.ProviderPressure, "last_outcome")]),
    ],
    ids=["run_status", "derivation_status", "provider_pressure"],
)
def test_no_constraint_bounds_the_stored_strings_the_model_leaves_open(table, fields):
    assert not [c for c in table.__table__.constraints if isinstance(c, CheckConstraint)], (
        f"a CHECK constraint now bounds {table.__tablename__}: type the field as its Literal"
    )
    for model, name in fields:
        assert model.model_fields[name].annotation in (str, str | None), f"{model.__name__}.{name}"


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


@pytest.fixture
def spawned(monkeypatch, tmp_path, no_escape) -> list[None]:
    return pin_ops_environment(monkeypatch, tmp_path)


def _fields(model) -> set[str]:
    return set(model.model_fields)


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _get(api_client, path: str) -> dict:
    response = await api_client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


async def _schedule(db_session) -> dict[str, tuple]:
    rows = await db_session.execute(
        select(
            SourceBinding.company_slug,
            SyncScheduleState.manual_requested_at,
            SyncScheduleState.next_reconcile_at,
            SyncScheduleState.manual_previous_reconcile_at,
        ).join(SourceBinding, SourceBinding.id == SyncScheduleState.binding_id)
    )
    return {row[0]: tuple(row[1:]) for row in rows}


async def _state(db_session) -> tuple:
    """Everything a sync or cancel could write."""
    runs = dict((await db_session.execute(select(ScrapeRun.id, ScrapeRun.status))).all())
    companies = sorted((await db_session.scalars(select(TrackedCompany.slug))).all())
    bindings = sorted((await db_session.scalars(select(SourceBinding.company_slug))).all())
    notifications = sorted((await db_session.scalars(select(Notification.id))).all())
    return await _schedule(db_session), runs, companies, bindings, notifications


def _assert_status_shapes(body: dict) -> None:
    assert set(body) == _fields(contract.SystemStatusResponse)
    assert set(body["scheduler"]) == _fields(contract.SchedulerStatus)
    for derivation in body["derivations"]:
        model = contract.DerivationEnabled if derivation["enabled"] else contract.DerivationDisabled
        assert set(derivation) == _fields(model), derivation["name"]
    for row in body["scheduler"]["overdue"]:
        model = contract.StaleBinding if row["reason"] == "authoritative_stale" else contract.OverdueBinding
        assert set(row) == _fields(model)
    assert all(set(r) == _fields(contract.ExcludedBinding) for r in body["scheduler"]["excluded"])
    assert all(set(r) == _fields(contract.UnreadBinding) for r in body["scheduler"]["unread"])
    assert all(set(r) == _fields(contract.ManualSyncBlock) for r in body["manual_blocked"])
    assert all(set(r) == _fields(contract.ProviderPressure) for r in body["scheduler"]["providers"])
    assert set(body["bindings_attention"]) == _fields(contract.BindingAttention)
    assert all(set(r) == _fields(contract.BindingAttentionItem) for r in body["bindings_attention"]["items"])


@pytest.mark.asyncio
async def test_health_answers_ok(api_client, spawned):
    assert await _get(api_client, "/api/health") == {"status": "ok"}


@pytest.mark.asyncio
async def test_status_before_anything_exists(api_client, spawned):
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    derivations = body.pop("derivations")
    stale = body.pop("derivations_stale")
    launcher = body.pop("launcher")
    assert launcher["product"] == "roleband"
    assert launcher["status"]["hold"] == {"kind": "attention", "reason": "supervisor_absent"}
    assert body == {
        "db": "ok", "last_success_at": None, "last_success_age_hours": None,
        "last_scan_at": None, "last_scan_age_hours": None,
        "preparation": None,
        "last_run_status": None, "last_run_started_at": None, "last_run_finished_at": None,
        "last_run_new": None, "last_run_seen": None, "running": False, "manual_sync_running": False,
        "manual_queued": [], "manual_blocked": [], "stuck_running": 0, "stale": True,
        "freshness_max_hours": 26,
        "scheduler": {
            "enabled": True, "seeded": False, "required": 0, "ever_read": 0, "fresh": 0, "overdue": [], "unread": [],
            "excluded": [],
            "last_complete_at": None, "oldest_scan_at": None, "next_due_at": None,
            "providers": [],
        },
        "bindings_attention": {
            "followed": 0, "automatic": 0, "flagged": 0, "stale": 0, "empty": 0, "outage": False,
            "held_open": 0,
            "items": [],
        },
        # Nothing installed: the core answers what it can, nothing is moving.
        "capabilities": [
            {"slot": "pay.levels", "providers": [], "builtin": True},
            {"slot": "pay.observations", "providers": [], "builtin": False},
            {"slot": "company.facts", "providers": [], "builtin": True},
            {"slot": "company.benefits", "providers": [], "builtin": True},
        ],
        "reference": {"applied_fp": None, "target_fp": None, "pending_jobs": 0, "last_change_id": None,
                      "last_change": None},
        "plugins_running": 0,
        "matching_switch": "none",
        "jobs": [],
        "supervisor": {"state": "absent", "since": None, "reason": None},
    }
    assert [d["name"] for d in derivations] == [p.name for p in POST_PASSES], "one entry per pass, in order"
    by_name = {d["name"]: d for d in derivations}
    assert by_name["prices"]["enabled"] is True, (
        "the price key may be saved in Settings, so the pass is enabled and skips itself without one"
    )
    assert by_name["lineage"] == {
        "name": "lineage", "enabled": True, "last_ok_at": None, "last_run_at": None,
        "last_status": None, "age_hours": None, "stale": True,
    }, "an enabled pass that never ran is stale"
    assert stale == [d["name"] for d in derivations if d["stale"]]


@pytest.mark.asyncio
async def test_status_names_the_followed_companies_without_a_full_scan(api_client, db_session, spawned):
    """The mixed roster: acme was scanned in full 2 hours ago;
    globex 3 days ago and failed since; initech 4 days ago and read only in
    part since; umbrella never, behind a paused provider, so it is reported
    but not scanned automatically. Nothing is held open: the seed writes no
    postings."""
    await seed_ops_contract(db_session, roster="mixed")
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    report = body["bindings_attention"]
    assert {k: v for k, v in report.items() if k != "items"} == {
        "followed": 4, "automatic": 3, "flagged": 3, "stale": 3, "empty": 0, "outage": False,
        "held_open": 0,
    }
    assert [
        (i["company"], i["provider"], i["automatic"], i["days_since_full_scan"], i["cause"], i["never_scanned"])
        for i in report["items"]
    ] == [
        ("initech", "ashby", True, 4.0, "partial", False),
        ("globex", "greenhouse", True, 3.0, "unreachable", False),
        ("umbrella", "lever", False, 30.0, "unknown", True),
    ], "scanned automatically first, longest without a full scan first; days read against the pinned clock"


@pytest.mark.asyncio
async def test_status_with_a_fresh_roster_takes_freshness_from_the_scheduler(api_client, db_session, spawned):
    seeded = await seed_ops_contract(db_session, roster="fresh")
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)

    oldest_reconcile = NOW - timedelta(hours=5)
    assert (body["last_success_at"], body["last_success_age_hours"], body["stale"]) == (
        _iso(oldest_reconcile), 5.0, False,
    ), "the oldest authoritative reconcile, not the newest run"
    assert body["scheduler"] == {
        "enabled": True, "seeded": True, "required": 2, "ever_read": 2, "fresh": 2, "overdue": [], "unread": [],
        "excluded": [{"company": "umbrella", "provider": "lever", "reason": "paused"}],
        "last_complete_at": _iso(oldest_reconcile), "oldest_scan_at": _iso(oldest_reconcile),
        "next_due_at": _iso(NOW + timedelta(hours=4)),
        "providers": [{"provider": "lever", "state": "paused", "cooldown_until": None, "last_outcome": None}],
    }, "a ready provider without a cooldown is not listed; dormant is disabled and absent"
    targeted = await db_session.get(ScrapeRun, seeded.targeted_run)
    assert (
        body["last_run_status"], body["last_run_started_at"], body["last_run_finished_at"],
        body["last_run_new"], body["last_run_seen"],
    ) == ("ok", _iso(targeted.started_at), _iso(targeted.finished_at), 1, 38)
    assert (body["running"], body["stuck_running"], body["freshness_max_hours"]) == (False, 1, 26)

    by_name = {d["name"]: d for d in body["derivations"]}
    assert by_name["lineage"] == {
        "name": "lineage", "enabled": True, "last_ok_at": _iso(NOW - timedelta(hours=3)),
        "last_run_at": _iso(NOW - timedelta(hours=3)), "last_status": "ok", "age_hours": 3.0, "stale": False,
    }
    assert (by_name["twins"]["last_status"], by_name["twins"]["age_hours"], by_name["twins"]["stale"]) == (
        "error", 50.0, True,
    ), "a recent failed run does not refresh a pass"
    assert "lineage" not in body["derivations_stale"] and "twins" in body["derivations_stale"]


@pytest.mark.asyncio
async def test_the_last_scan_is_the_newest_refreshing_run_while_a_company_is_behind(
    api_client, db_session, spawned,
):
    """globex was last read three days ago, and that keeps the status stale; the
    newest scan to read anything, a targeted one, finished under two hours ago.
    A newer run that failed read nothing, and a running one has not finished."""
    seeded = await seed_ops_contract(db_session, roster="mixed", live_run=True)
    db_session.add(ScrapeRun(started_at=NOW - timedelta(minutes=20), finished_at=NOW - timedelta(minutes=15),
                             heartbeat_at=NOW - timedelta(minutes=15), status="failed", scope="full"))
    await db_session.commit()
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    targeted = await db_session.get(ScrapeRun, seeded.targeted_run)
    assert (body["last_scan_at"], body["last_scan_age_hours"]) == (
        _iso(targeted.finished_at), round((NOW - targeted.finished_at).total_seconds() / 3600, 2),
    )
    assert (body["last_success_age_hours"], body["stale"]) == (72.0, True), "freshness is unchanged"


@pytest.mark.asyncio
async def test_status_with_overdue_bindings_names_why_and_what_is_queued(api_client, db_session, spawned):
    await seed_ops_contract(db_session, roster="mixed")
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    scheduler = body["scheduler"]

    assert (body["last_success_at"], body["last_success_age_hours"], body["stale"]) == (
        _iso(NOW - timedelta(days=3)), 72.0, True,
    ), (
        "the age is the oldest scan the shown postings rest on, never an empty one that reads "
        "'No data yet': globex's, read in full three days ago and only failed since"
    )
    assert (scheduler["seeded"], scheduler["required"], scheduler["fresh"], scheduler["last_complete_at"]) == (
        True, 3, 1, None,
    )
    assert scheduler["oldest_scan_at"] == _iso(NOW - timedelta(days=3)), (
        "globex never reconciled with authority, but its postings rest on that full read"
    )
    assert sorted(scheduler["unread"], key=lambda r: r["company"]) == [
        {"company": "globex", "reason": "read_stale", "last_read_at": _iso(NOW - timedelta(days=3))},
        {"company": "initech", "reason": "read_stale", "last_read_at": _iso(NOW - timedelta(hours=40))},
    ], "stale names the companies not read in full inside the window, and when each last was"
    assert sorted(scheduler["overdue"], key=lambda r: r["company"]) == [
        {"company": "globex", "reason": "never_reconciled"},
        {"company": "initech", "reason": "authoritative_stale", "last_reconcile_at": _iso(NOW - timedelta(hours=40))},
    ]
    assert scheduler["excluded"] == [{"company": "umbrella", "provider": "lever", "reason": "paused"}]
    assert scheduler["next_due_at"] == _iso(NOW - timedelta(minutes=10)), "the manual request made globex due"

    blocked = [
        {"provider": "ashby", "reason": "backoff", "until": _iso(NOW + timedelta(hours=3)), "companies": 1},
        {"provider": "lever", "reason": "paused", "until": None, "companies": 1},
    ]
    assert (body["manual_queued"], body["manual_blocked"]) == (["globex", "initech", "umbrella"], blocked), (
        "queued behind a ready provider is not blocked"
    )
    assert not {"manual_queued", "manual_blocked"} & set(scheduler), (
        "the queue is answered once, at the top, not again inside the scheduler"
    )
    assert scheduler["providers"] == [
        {"provider": "ashby", "state": "backoff", "cooldown_until": _iso(NOW + timedelta(hours=3)),
         "last_outcome": "blocked"},
        {"provider": "lever", "state": "paused", "cooldown_until": None, "last_outcome": None},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("last_reconcile", "read", "age", "stale", "unread", "roster", "followed"),
    [
        # A lossy full read still refreshes freshness. Otherwise the status
        # would report stale data and health would keep requesting scans
        # despite full reads.
        (NOW - timedelta(days=9), ("lossy", NOW - timedelta(hours=20)), 20.0, False, [],
         "authoritative_stale", NOW - timedelta(days=30)),
        # Its only full read validated its binding, so it could not close,
        # and the read that may close has not come. Boards like this must
        # not hold the status stale while the dispatcher works through them
        # eight a tick.
        (None, ("ok", NOW - timedelta(hours=20)), 20.0, False, [], "never_reconciled",
         NOW - timedelta(days=2)),
        # Followed two hours ago and not read in full yet (say, a board our
        # page ceiling cut). The clock runs from
        # the follow, as the coverage report's does.
        (None, None, 5.0, False, [], "never_reconciled", NOW - timedelta(hours=2)),
        # The controls. Never read at all: nothing of it is shown, and the
        # status says so rather than dating it.
        (None, None, 5.0, True,
         [{"company": "initrode", "reason": "never_read", "last_read_at": None}], "never_reconciled",
         NOW - timedelta(days=30)),
        # Read in full, but longer ago than the window: only failures since.
        (None, ("ok", NOW - timedelta(hours=31)), 31.0, True,
         [{"company": "initrode", "reason": "read_stale", "last_read_at": _iso(NOW - timedelta(hours=31))}],
         "never_reconciled", NOW - timedelta(days=30)),
    ],
    ids=["lossy-read-yesterday", "first-read-validated", "followed-today-not-read-yet", "never-read",
         "read-too-long-ago"],
)
async def test_status_ages_by_when_each_board_was_last_read_in_full(
    api_client, db_session, spawned, last_reconcile, read, age, stale, unread, roster, followed
):
    """The status age is the oldest scan the shown postings rest on,
    and a scan is a reconcile that read the whole board: `ok`, `empty` or
    `lossy`, the coverage report's own rule. Closure authority is
    a different question, and the roster keeps answering it in `overdue`.
    Built on the fresh roster: acme read 2 h ago, globex 5 h."""
    seeded = await seed_ops_contract(db_session, roster="fresh")
    db_session.add(_company("initrode", "Initrode", "oracle"))
    await db_session.flush()
    binding = _binding("initrode", "oracle")
    binding.created_at = followed
    db_session.add(binding)
    await db_session.flush()
    db_session.add(
        _schedule_row(binding.id, "oracle", last_reconcile=last_reconcile,
                      next_reconcile=NOW + timedelta(hours=3), discovery=False)
    )
    if read is not None:
        outcome, at = read
        db_session.add(
            ScrapeSourceRun(
                run_id=seeded.full_run, binding_id=binding.id, company_slug="initrode",
                provider_key="oracle", scan_mode="reconcile", outcome=outcome,
                started_at=at, finished_at=at, scanned=967, errors=[], drift=[],
            )
        )
    await db_session.commit()

    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    scheduler = body["scheduler"]

    assert (body["last_success_age_hours"], body["stale"]) == (age, stale)
    assert scheduler["unread"] == unread
    assert [row["reason"] for row in scheduler["overdue"] if row["company"] == "initrode"] == [roster], (
        "the roster still says the company cannot close: only the status age moved"
    )


async def _gone(db_session, seeded, slug: str, *, provider: str = "oracle") -> None:
    """A followed company read in full 31 h ago (stale on its own), whose read
    since then found its careers page gone: a 404 at the board root."""
    db_session.add(_company(slug, slug.title(), provider))
    await db_session.flush()
    binding = _binding(slug, provider)
    binding.created_at = NOW - timedelta(days=30)
    db_session.add(binding)
    await db_session.flush()
    db_session.add(_schedule_row(binding.id, provider, last_reconcile=None, next_reconcile=NOW + timedelta(hours=3),
                                 discovery=False))
    for run_id, outcome, at, drift in (
        (seeded.full_run, "ok", NOW - timedelta(hours=31), []),
        (seeded.targeted_run, "failed", NOW - timedelta(hours=2),
         [{"message": "non-200 job board status=404", "status": 404, "board_missing": True}]),
    ):
        db_session.add(ScrapeSourceRun(
            run_id=run_id, binding_id=binding.id, company_slug=slug, provider_key=provider,
            scan_mode="reconcile", outcome=outcome, started_at=at, finished_at=at,
            scanned=0 if outcome == "failed" else 40, errors=[], drift=drift,
        ))


@pytest.mark.asyncio
async def test_a_careers_page_gone_is_told_by_coverage_and_does_not_hold_the_status_stale(
    api_client, db_session, spawned
):
    """A board that 404s at its root stays unread, and would make the top bar
    read "Stale · 6d ago" over a roster read in full nightly. Coverage already says each careers page is gone and offers a
    fix; the status leaves them out instead of telling it again."""
    seeded = await seed_ops_contract(db_session, roster="fresh")
    await _gone(db_session, seeded, "initrode")
    await db_session.commit()

    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    scheduler = body["scheduler"]
    assert (body["stale"], scheduler["unread"]) == (False, [])
    assert {"company": "initrode", "provider": "oracle", "reason": "board_missing"} in scheduler["excluded"]
    assert any(i["company"] == "initrode" and i["cause"] == "board_missing"
               for i in body["bindings_attention"]["items"]), "Coverage still tells it"


@pytest.mark.asyncio
async def test_many_careers_pages_gone_at_once_read_as_an_outage_and_stay_stale(api_client, db_session, spawned):
    """The control: five automatic boards missing together is more likely the
    provider's answer than five companies moving (`missing_burst`), so each
    keeps the status stale like any unreachable page."""
    seeded = await seed_ops_contract(db_session, roster="fresh")
    for slug in ("initrode", "vandelay", "gringotts", "wonka", "tyrell"):
        await _gone(db_session, seeded, slug)
    await db_session.commit()

    body = await _get(api_client, "/api/status")
    assert body["stale"] is True
    assert {r["company"] for r in body["scheduler"]["unread"]} == {"initrode", "vandelay", "gringotts", "wonka",
                                                                    "tyrell"}
    assert not [r for r in body["scheduler"]["excluded"] if r["reason"] == "board_missing"]


@pytest.mark.asyncio
async def test_status_before_the_roster_is_seeded_falls_back_to_the_last_full_run(api_client, db_session, spawned):
    seeded = await seed_ops_contract(db_session, roster="unscheduled")
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)

    full = await db_session.get(ScrapeRun, seeded.full_run)
    assert (body["last_success_at"], body["last_success_age_hours"], body["stale"]) == (
        _iso(full.finished_at), 6.0, False,
    ), "the newest FULL refreshing run; the targeted retry after it covered one company"
    assert (body["scheduler"]["seeded"], body["scheduler"]["required"]) == (False, 4)
    assert {(r["company"], r["reason"]) for r in body["scheduler"]["overdue"]} == {
        ("globex", "never_reconciled"), ("initech", "authoritative_stale"), ("hooli", "not_scheduled"),
    }


@pytest.mark.asyncio
async def test_status_reports_a_live_run_as_running_and_an_orphan_as_stuck(api_client, db_session, spawned):
    seeded = await seed_ops_contract(db_session, roster="mixed", live_run=True)
    body = await _get(api_client, "/api/status")
    _assert_status_shapes(body)
    live = await db_session.get(ScrapeRun, seeded.live_run)
    assert (
        body["running"], body["last_run_status"], body["last_run_started_at"], body["last_run_finished_at"],
        body["last_run_new"], body["last_run_seen"], body["stuck_running"],
    ) == (True, "running", _iso(live.started_at), None, 2, 311, 1)


@pytest.mark.asyncio
async def test_the_run_log_is_newest_first_and_served_as_stored(api_client, db_session, spawned):
    seeded = await seed_ops_contract(db_session, roster="mixed", live_run=True)
    body = await _get(api_client, "/api/runs")
    assert set(body) == _fields(contract.RunListResponse)
    assert all(set(item) == _fields(contract.RunRow) for item in body["items"])
    assert [i["id"] for i in body["items"]] == [seeded.live_run, seeded.targeted_run, seeded.full_run, seeded.stuck_run]

    stored = {
        row.id: row
        for row in (await db_session.execute(
            select(ScrapeRun.id, ScrapeRun.per_source, ScrapeRun.drift_alerts, ScrapeRun.notes, ScrapeRun.finished_at)
        )).all()
    }
    for item in body["items"]:
        row = stored[item["id"]]
        if item["status"] == "running":
            continue  # a running run has stored no `per_source` yet; see the test below
        assert (item["per_source"], item["drift_alerts"], item["notes"]) == (row.per_source, row.drift_alerts, row.notes)
        assert item["finished_at"] == (_iso(row.finished_at) if row.finished_at else None)
    full = next(i for i in body["items"] if i["id"] == seeded.full_run)
    assert (full["status"], full["jobs_seen"], full["jobs_new"], full["jobs_closed"]) == ("partial", 1204, 12, 4)
    assert sorted(full["per_source"]) == ["acme", "globex", "piedpiper"]

    assert [i["id"] for i in (await _get(api_client, "/api/runs?limit=2"))["items"]] == [
        seeded.live_run, seeded.targeted_run,
    ]


@pytest.mark.asyncio
async def test_an_empty_run_log(api_client, spawned):
    assert await _get(api_client, "/api/runs") == {"items": []}


@pytest.mark.asyncio
async def test_the_sync_picker_judges_each_company_from_the_last_full_run(api_client, db_session, spawned):
    await seed_ops_contract(db_session, roster="unscheduled")
    body = await _get(api_client, "/api/sync/targets")
    assert set(body) == _fields(contract.SyncTargetsResponse)
    assert all(set(c) == _fields(contract.SyncTarget) for c in body["companies"])
    assert body == {
        "freshness_max_hours": 26,
        "companies": [
            {"slug": "acme", "display": "Acme", "adapter": "greenhouse", "last_sync_at": _iso(NOW - timedelta(hours=2)),
             "age_hours": 2.0, "stale": False, "last_full_scan_at": _iso(NOW - timedelta(hours=2)), "automatic": True,
             "last_outcome": "ok", "retryable": False, "coverage": None},
            # Failed in the full run: still retryable although a targeted retry succeeded since.
            {"slug": "globex", "display": "Globex", "adapter": "greenhouse",
             "last_sync_at": _iso(NOW - timedelta(hours=30)), "age_hours": 30.0, "stale": True,
             "last_full_scan_at": _iso(NOW - timedelta(days=3)), "automatic": True,
             "last_outcome": "failed", "retryable": True,
             # 3 days without a full scan, failing since. The bell rings, in these words.
             "coverage": {"cause": "unreachable", "held_open": 0, "days_since_full_scan": 3.0,
                          "rings": True, "title": "Couldn't scan Globex · 3 days",
                          "body": "Its careers page isn't answering. It hasn't had a full scan since 17 Jul, "
                                  "so new roles from Globex may be missing. This clears on its next full scan.",
                          # The same words as keys the client says.
                          "say": {"title": {"k": "notif-coverage-scan-title", "p": {"company": "Globex", "days": 3}},
                                  "body": [{"k": "notif-coverage-unreachable", "p": {}},
                                           {"k": "notif-coverage-not-scanned-since",
                                            "p": {"day": {"date": "2026-07-17"}, "company": "Globex"}}]}}},
            {"slug": "hooli", "display": "Hooli", "adapter": "greenhouse", "last_sync_at": _iso(NOW - timedelta(hours=1)),
             "age_hours": 1.0, "stale": False, "last_full_scan_at": _iso(NOW - timedelta(hours=1)), "automatic": True,
             "last_outcome": None, "retryable": False, "coverage": None},
            {"slug": "initech", "display": "Initech", "adapter": "ashby",
             "last_sync_at": _iso(NOW - timedelta(hours=40)), "age_hours": 40.0, "stale": True,
             "last_full_scan_at": _iso(NOW - timedelta(days=4)), "automatic": True,
             "last_outcome": None, "retryable": False,
             "coverage": {"cause": "partial", "held_open": 0, "days_since_full_scan": 4.0,
                          "rings": True, "title": "Couldn't scan Initech · 4 days",
                          "body": "Scans read only part of its careers page. It hasn't had a full scan since "
                                  "16 Jul, so new roles from Initech may be missing. This clears on its next full scan.",
                          "say": {"title": {"k": "notif-coverage-scan-title", "p": {"company": "Initech", "days": 4}},
                                  "body": [{"k": "notif-coverage-partial", "p": {}},
                                           {"k": "notif-coverage-not-scanned-since",
                                            "p": {"day": {"date": "2026-07-16"}, "company": "Initech"}}]}}},
            # No binding yet, but the full run recorded it: bounded by our clock, so worth another pass.
            {"slug": "piedpiper", "display": "Pied Piper", "adapter": "ashby", "last_sync_at": None,
             "age_hours": None, "stale": True, "last_full_scan_at": None, "automatic": False,
             "last_outcome": "bounded", "retryable": True, "coverage": None},
            # Never scanned, behind a paused provider: not scanned automatically, so the bell is quiet.
            {"slug": "umbrella", "display": "Umbrella", "adapter": "lever", "last_sync_at": None,
             "age_hours": None, "stale": True, "last_full_scan_at": None, "automatic": False,
             "last_outcome": None, "retryable": False, "coverage": None},
        ],
    }, "sorted by slug; dormant is disabled and never offered"


@pytest.mark.asyncio
async def test_an_empty_sync_picker(api_client, spawned):
    assert await _get(api_client, "/api/sync/targets") == {"companies": [], "freshness_max_hours": 26}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({"companies": ["acme", "nope"]}, 400, "not a scrapeable tracked company: nope"),
        ({"companies": ["dormant"]}, 400, "not a scrapeable tracked company: dormant"),
        ({"companies": ["umbrella", "acme"]}, 409, "scheduled collection is paused or policy-denied: umbrella"),
        ({"companies": [f"c{i}" for i in range(501)]}, 422, None),
    ],
    ids=["unknown", "disabled", "paused_provider", "too_many"],
)
async def test_a_refused_sync_queues_and_spawns_nothing(api_client, db_session, spawned, body, status, detail):
    await seed_ops_contract(db_session, roster="mixed")
    before = await _state(db_session)
    response = await api_client.post("/api/sync", json=body)
    assert response.status_code == status
    if detail is not None:
        assert said(response.json()) == {"detail": detail}
    assert await _state(db_session) == before
    assert spawned == []


@pytest.mark.asyncio
async def test_a_sync_during_a_live_run_attaches_to_it(api_client, db_session, spawned):
    """No second run starts: the named company is queued for the live one,
    and nothing else changes."""
    seeded = await seed_ops_contract(db_session, roster="mixed", live_run=True)
    schedule, runs, *_, notifications = await _state(db_session)
    response = await api_client.post("/api/sync", json={"companies": ["acme"]})
    assert response.status_code == 200, response.text
    live = await db_session.get(ScrapeRun, seeded.live_run)
    assert response.json() == {
        "status": "already_running", "run_id": seeded.live_run, "started_at": _iso(live.started_at), "companies": [],
        "queued": ["acme"],
    }
    assert set(response.json()) == _fields(contract.SyncAlreadyRunning)
    after, runs_after, *_, notifications_after = await _state(db_session)
    assert (runs_after, notifications_after) == (runs, notifications), "no run or notification is written"
    assert after["acme"] == (NOW, NOW, schedule["acme"][1]), "queued for the live run"
    assert {k: after[k] for k in schedule if k != "acme"} == {k: v for k, v in schedule.items() if k != "acme"}
    assert spawned == ["sync"], "the live run is told to look, no dispatcher is added"


@pytest.mark.asyncio
async def test_a_targeted_sync_queues_its_companies_and_starts_one_dispatcher(api_client, db_session, spawned):
    await seed_ops_contract(db_session, roster="mixed")
    before = await _schedule(db_session)
    response = await api_client.post("/api/sync", json={"companies": ["initech", "acme", "initech"]})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "started", "companies": ["initech", "acme"], "queued": ["acme", "initech"]}, (
        "the request de-duplicated in its own order; the queue sorted"
    )
    assert set(response.json()) == _fields(contract.SyncStarted)
    assert len(spawned) == 1

    after = await _schedule(db_session)
    assert after["acme"] == (NOW, NOW, before["acme"][1]), "due now, with its natural deadline kept to restore"
    assert after["initech"] == (NOW, NOW, before["initech"][2]), "re-queued, still restoring the first deadline"
    assert after["globex"] == before["globex"], "a company not asked for is untouched"


@pytest.mark.asyncio
async def test_a_policy_denied_provider_reads_the_same_on_both_surfaces(
    api_client, db_session, spawned
):
    """`/api/schedule` and `/api/status` must not disagree about one provider.

    `ProviderPressureState.state` is a cache `scheduler._ensure_state` rewrites
    from `collection_access` on every tick and every `/api/sync`. Until then the
    row is stale — and on a machine whose dispatcher is switched off, forever.
    Both surfaces must overlay the current policy: a denied binding cannot
    count as overdue or appear ready to run merely because its cached pressure
    row says `ready`.

    The divergence is seeded, not simulated: `meta` is in the pinned
    `sync_policy_denied_providers`, and its pressure row says `ready`.
    """
    await seed_ops_contract(db_session, roster="mixed")
    denied = _company("hooli", "Hooli", "meta")
    db_session.add(denied)
    await db_session.flush()
    binding = _binding("hooli", "meta")
    db_session.add(binding)
    await db_session.flush()
    db_session.add(
        _schedule_row(
            binding.id, "meta",
            last_reconcile=NOW - timedelta(hours=40),
            next_reconcile=NOW - timedelta(hours=16),
            discovery=False,
            manual=NOW - timedelta(minutes=10),
        )
    )
    db_session.add(
        ProviderPressureState(
            pressure_key="meta", state="ready", cooldown_until=None,
            last_started_at=None, last_finished_at=None,
            consecutive_pressure_events=0, last_outcome=None, evidence={},
        )
    )
    await db_session.commit()

    schedule = await _get(api_client, "/api/schedule")
    row = next(r for r in schedule["bindings"] if r["company"] == "hooli")
    assert (row["status"], row["provider_state"]) == ("policy_denied", "policy_denied")
    assert row["eligible_reconcile_at"] is None

    status = await _get(api_client, "/api/status")
    _assert_status_shapes(status)
    scheduler = status["scheduler"]
    assert {"company": "hooli", "provider": "meta", "reason": "policy_denied"} in scheduler[
        "excluded"
    ], "the surface that judges due work read the stale row"
    assert "hooli" not in [row["company"] for row in scheduler["overdue"]], (
        "a binding the dispatcher will refuse cannot also be overdue work"
    )
    assert {"provider": "meta", "reason": "policy_denied", "until": None, "companies": 1} in (
        status["manual_blocked"]
    ), "queued behind a denied provider is not about to run"
    assert {
        "provider": "meta", "state": "policy_denied", "cooldown_until": None, "last_outcome": None,
    } in scheduler["providers"]


@pytest.mark.asyncio
async def test_a_sync_commits_its_queue_before_it_starts_the_dispatcher(
    api_client, db_session, spawned, monkeypatch
):
    """The dispatcher child reads the queue from its OWN connection.

    Committed after the spawn, the first tick sees an unqueued roster and the
    request is a silent no-op — the user clicks Sync and nothing happens. So the
    order is the contract: another session must already see the row when the
    spawn is recorded. Two plausible breakages fail this: a commit moved after
    the spawn (the fresh session sees nothing), and a spawn moved before the
    queue (the recorded order flips).
    """
    seeded = await seed_ops_contract(db_session, roster="mixed")
    order: list[tuple] = []
    real = ops_router.queue_manual_reconciliation

    async def queue(session, companies, *, now):
        queued = await real(session, companies, now=now)
        factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
        async with factory() as elsewhere:
            visible = await elsewhere.scalar(
                select(SyncScheduleState.manual_requested_at).where(
                    SyncScheduleState.binding_id == seeded.bindings["acme"]
                )
            )
        order.append(("queued", queued, visible))
        return queued

    real_ring = ops_router.scan_requests.ring

    async def ring(session, *, requested_by):
        order.append(("rung", requested_by))
        await real_ring(session, requested_by=requested_by)

    monkeypatch.setattr(ops_router, "queue_manual_reconciliation", queue)
    monkeypatch.setattr(ops_router.scan_requests, "ring", ring)

    response = await api_client.post("/api/sync", json={"companies": ["acme"]})
    assert response.status_code == 200, response.text
    assert order == [("queued", ["acme"], NOW), ("rung", "sync")]


@pytest.mark.asyncio
async def test_a_full_sync_queues_the_scrapeable_roster(api_client, db_session, spawned):
    await seed_ops_contract(db_session, roster="fresh")
    response = await api_client.post("/api/sync")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["companies"], len(spawned)) == ("started", [], 1)

    after = await _schedule(db_session)
    assert body["queued"] == sorted(slug for slug, (requested, *_rest) in after.items() if requested == NOW)
    assert {"acme", "globex", "piedpiper"} <= set(body["queued"]), "piedpiper's binding is created by the request"
    assert not {"umbrella", "dormant"} & set(body["queued"]), "a paused provider and a disabled company are not queued"


@pytest.mark.asyncio
async def test_a_cancel_with_nothing_to_stop_changes_nothing(api_client, db_session, spawned):
    await seed_ops_contract(db_session, roster="fresh", live_run=True)
    before = await _state(db_session)
    response = await api_client.post("/api/sync/cancel")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "not_running", "pid": None, "dequeued": []}
    assert set(response.json()) == _fields(contract.SyncNotCancelled)
    assert await _state(db_session) == before, "a scheduled live run is left alone when nothing was queued"


async def _manual_scan(db_session, group: int) -> int:
    """A live scan Sync asked for, as the supervisor records it: Sync's request,
    claimed, and its run under process group `group`. No process exists; the
    supervisor that would signal it is not running here."""
    from tracker.api import scan_requests
    from tracker.db import job_store

    await job_store.ring(db_session, "scan", requested_by=scan_requests.SYNC, args={"manual": True})
    _request, run = await job_store.claim(db_session, "scan")
    await job_store.mark_running(db_session, run.id, pid=group, pgid=group, proc_started_at=None)
    await db_session.commit()
    return run.id


@pytest.mark.asyncio
async def test_a_cancel_that_only_dequeues_restores_deadlines_and_ends_no_run(api_client, db_session, spawned):
    # Dequeuing stops no process, so no run was stopped. Marking the newest
    # running run `error` would mark a scrape no cancel touched.
    await seed_ops_contract(db_session, roster="mixed", live_run=True)
    before = await _schedule(db_session)
    untouched = (await _state(db_session))[1:]
    response = await api_client.post("/api/sync/cancel")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "cancelled", "pid": None, "run_id": None, "dequeued": ["globex", "initech", "umbrella"],
    }
    assert set(response.json()) == _fields(contract.SyncCancelled)

    after = await _schedule(db_session)
    for slug in ("globex", "initech", "umbrella"):
        assert after[slug] == (None, before[slug][2], None), f"{slug}: its natural deadline restored"
    assert after["acme"] == before["acme"]
    assert (await _state(db_session))[1:] == untouched, "a cancel that signalled nothing ended or reported a run"


@pytest.mark.asyncio
async def test_a_cancel_ends_the_live_run_in_the_group_it_signalled(
    api_client, db_session, spawned, monkeypatch, tmp_path
):
    seeded = await seed_ops_contract(db_session, roster="fresh", live_run=True)
    supervised = await _manual_scan(db_session, LIVE_GROUP)
    response = await api_client.post("/api/sync/cancel")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "cancelled", "pid": LIVE_GROUP, "run_id": seeded.live_run, "dequeued": []}
    stopping = await db_session.get(JobRun, supervised)
    await db_session.refresh(stopping)
    assert stopping.cancel_reason == "sync_cancel", "the supervisor is asked to stop the scan Sync started"

    live = await db_session.get(ScrapeRun, seeded.live_run)
    await db_session.refresh(live)
    assert (live.status, live.notes, live.finished_at) == ("error", "cancelled by user", NOW)
    reported = (
        await db_session.execute(
            select(Notification.category, Notification.priority, Notification.title, Notification.body)
            .where(Notification.run_id == live.id)
        )
    ).all()
    # The person's own stop, never "Couldn't scan, nothing was updated" over
    # "Problems at: cancelled by user".
    assert [tuple(row) for row in reported] == [
        ("sync_unfinished", "low", "Scan stopped", "You stopped it before it scanned any company."),
    ]
    stuck = await db_session.get(ScrapeRun, seeded.stuck_run)
    await db_session.refresh(stuck)
    assert stuck.status == "running", "a dead process's row under the same group number is the reconciler's"


def _commit_sources(db_session, run_id: int, bindings: dict, committed: dict) -> None:
    """The `scrape_source_runs` rows a run commits as each source finishes."""
    from tracker.db.models import ScrapeSourceRun

    db_session.add_all([
        ScrapeSourceRun(run_id=run_id, binding_id=bindings[slug], company_slug=slug, provider_key="greenhouse",
                        scan_mode="reconcile", outcome=stats["outcome"], started_at=NOW, finished_at=NOW,
                        scanned=stats["scanned"], kept=stats["kept"], errors=[], drift=[], stats=stats)
        for slug, stats in committed.items()
    ])


@pytest.mark.asyncio
async def test_a_running_run_is_served_with_the_sources_it_committed(api_client, db_session, spawned):
    seeded = await seed_ops_contract(db_session, roster="fresh", live_run=True)
    committed = {"acme": {"outcome": "ok", "scanned": 40, "kept": 3, "errors": [], "list_complete": True}}
    _commit_sources(db_session, seeded.live_run, seeded.bindings, committed)
    await db_session.commit()
    body = await _get(api_client, "/api/runs")
    live = next(i for i in body["items"] if i["id"] == seeded.live_run)
    assert live["per_source"] == committed
    assert (await db_session.get(ScrapeRun, seeded.live_run)).per_source == {}, "nothing is written until it ends"


@pytest.mark.asyncio
async def test_a_cancelled_run_that_committed_sources_is_partial_and_targeted(
    api_client, db_session, spawned, monkeypatch, tmp_path
):
    # Sources persist as they finish, so a run stopped mid-sync holds
    # committed sources. `error` would say none produced usable data; `ok` or a
    # full scope would claim a refresh of companies it never reached.
    seeded = await seed_ops_contract(db_session, roster="fresh", live_run=True)
    live = await db_session.get(ScrapeRun, seeded.live_run)
    committed = {
        "acme": {"outcome": "ok", "scanned": 40, "kept": 3, "errors": [], "list_complete": True},
        "globex": {"outcome": "ok", "scanned": 12, "kept": 1, "errors": [], "list_complete": True},
    }
    _commit_sources(db_session, live.id, seeded.bindings, committed)
    live.scope = "full"
    await db_session.commit()
    await _manual_scan(db_session, LIVE_GROUP)

    response = await api_client.post("/api/sync/cancel")
    assert response.status_code == 200, response.text

    await db_session.refresh(live)
    assert (live.status, live.scope, live.notes) == ("partial", "targeted", "cancelled by user")
    assert live.per_source == committed, "a stopped run reports the sources it committed"
    stopped = (await db_session.scalars(select(Notification).where(Notification.run_id == live.id))).one()
    assert (stopped.category, stopped.title) == ("sync_unfinished", "Scan stopped")
    assert stopped.body.startswith("You stopped it after it scanned 2 companies. What it found is saved.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("live_run", "signalled"),
    [(True, 51_007), (False, LIVE_GROUP)],
    ids=["a_live_run_in_another_group", "a_dead_process_row_under_a_reused_group"],
)
async def test_a_cancel_ends_no_run_it_did_not_stop(
    api_client, db_session, spawned, monkeypatch, tmp_path, live_run, signalled
):
    # Another group: the scan Sync asked for lost the run lock to a scheduled
    # scrape, which is live. A reused group: the only row naming the stopped
    # group was left by a process that died without closing it.
    await seed_ops_contract(db_session, roster="fresh", live_run=live_run)
    await _manual_scan(db_session, signalled)
    before = await _state(db_session)
    response = await api_client.post("/api/sync/cancel")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "cancelled", "pid": signalled, "run_id": None, "dequeued": []}
    assert await _state(db_session) == before, "a cancel ended or reported a run it did not stop"


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


def _wrap(monkeypatch, name, change):
    real = getattr(ops_router, name)

    async def drifted(*args, **kwargs):
        return change(await real(*args, **kwargs))

    monkeypatch.setattr(ops_router, name, drifted)


def _drop_last_reconcile(scheduler: dict) -> dict:
    for row in scheduler["overdue"]:
        row.pop("last_reconcile_at", None)
    return scheduler


def _disabled_with_freshness(derivations: list) -> list:
    return [{**d, "enabled": False} if d["name"] == "lineage" else d for d in derivations]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("scheduler_status", lambda s: {**s, "surprise": 1}),
        ("scheduler_status", _drop_last_reconcile),
        ("derivation_status", _disabled_with_freshness),
        ("derivation_status", lambda ds: [{k: v for k, v in d.items() if k != "age_hours"} for d in ds]),
    ],
    ids=["scheduler_adds_a_key", "stale_binding_drops_its_reconcile", "disabled_pass_keeps_freshness",
         "enabled_pass_drops_a_key"],
)
async def test_status_drift_fails_the_response(api_client, db_session, spawned, monkeypatch, name, change):
    await seed_ops_contract(db_session, roster="mixed")
    _wrap(monkeypatch, name, change)
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/status")


@pytest.mark.asyncio
async def test_an_outcome_outside_the_vocabulary_fails_the_picker(api_client, db_session, spawned, monkeypatch):
    await seed_ops_contract(db_session, roster="fresh")
    monkeypatch.setattr(ops_router, "classify_source_outcome", lambda stats: SimpleNamespace(value="retired"))
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/sync/targets")


@pytest.mark.asyncio
async def test_a_run_stored_in_another_shape_fails_the_run_log(api_client, db_session, spawned):
    db_session.add(ScrapeRun(started_at=NOW, status="ok", scope="full", per_source=[], drift_alerts=[]))
    await db_session.commit()
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/runs")


@pytest.mark.asyncio
async def test_a_queue_that_answers_in_another_shape_fails_the_sync(api_client, db_session, spawned, monkeypatch):
    await seed_ops_contract(db_session, roster="fresh")

    async def queue(*_args, **_kwargs):
        return None

    monkeypatch.setattr(ops_router, "queue_manual_reconciliation", queue)
    with pytest.raises(ResponseValidationError):
        await api_client.post("/api/sync")


@pytest.mark.asyncio
async def test_a_cancel_status_outside_the_vocabulary_fails_the_cancel(api_client, db_session, spawned, monkeypatch):
    # `stopped` is the re-embed terminator's word for success: borrowed here it
    # would read as neither branch the dashboard handles.
    await seed_ops_contract(db_session, roster="fresh")

    async def stopped(_session):
        return "stopped", None

    monkeypatch.setattr(ops_router.scan_requests, "stop_manual_scan", stopped)

    async def nothing_queued(_session):
        return []

    monkeypatch.setattr(ops_router, "cancel_manual_reconciliation", nothing_queued)
    with pytest.raises(ResponseValidationError):
        await api_client.post("/api/sync/cancel")


async def _schedule_of(session, company: str) -> SyncScheduleState:
    return (await session.scalars(
        select(SyncScheduleState).join(SourceBinding, SourceBinding.id == SyncScheduleState.binding_id)
        .where(SourceBinding.company_slug == company)
    )).one()


@pytest.mark.asyncio
async def test_status_reuses_what_scans_write_for_at_most_the_window(api_client, db_session, spawned, monkeypatch):
    await seed_ops_contract(db_session, roster="mixed")
    clock = [1000.0]
    monkeypatch.setattr(ops_router, "_reuse_clock", lambda: clock[0])
    reads: list[None] = []
    real_followed = ops_router.followed_bindings

    async def counted(*args, **kwargs):
        reads.append(None)
        return await real_followed(*args, **kwargs)

    monkeypatch.setattr(ops_router, "followed_bindings", counted)

    def unread(body):
        return sorted(row["company"] for row in body["scheduler"]["unread"])

    assert unread(await _get(api_client, "/api/status")) == ["globex", "initech"]
    # A scan reads initech's board in full.
    (await _schedule_of(db_session, "initech")).last_reconcile_at = NOW
    await db_session.commit()

    clock[0] += ops_router.SCAN_BOUND_REUSE_SECONDS - 1
    assert unread(await _get(api_client, "/api/status")) == ["globex", "initech"]
    assert len(reads) == 1, "inside the window the scan-bound part is not read again"
    clock[0] += 1
    assert unread(await _get(api_client, "/api/status")) == ["globex"]
    assert len(reads) == 2


def _schedule_summary(body: dict) -> dict:
    """What the schedule says: the scheduler's part and the queue, which the
    answer carries once, at the top."""
    return {**body["scheduler"], "manual_queued": body["manual_queued"], "manual_blocked": body["manual_blocked"]}


async def _cancel_globex_request(session, monkeypatch):
    (await _schedule_of(session, "globex")).manual_requested_at = None


async def _pause_ashby(session, monkeypatch):
    (await session.get(ProviderPressureState, "ashby")).state = PAUSED


async def _unfollow_initech(session, monkeypatch):
    (await session.get(TrackedCompany, "initech")).enabled = False


async def _move_initech_board(session, monkeypatch):
    binding = (await session.scalars(select(SourceBinding).where(SourceBinding.company_slug == "initech"))).one()
    binding.status = "retired"


async def _widen_the_stale_window(session, monkeypatch):
    settings = ops_router.get_settings().model_copy(update={"sync_authoritative_stale_hours": 100})
    monkeypatch.setattr(ops_router, "get_settings", lambda: settings)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    _cancel_globex_request, _pause_ashby, _unfollow_initech, _move_initech_board, _widen_the_stale_window,
], ids=lambda change: change.__name__.strip("_"))
async def test_what_a_person_changes_shows_on_the_next_status_read(api_client, db_session, spawned, monkeypatch, change):
    await seed_ops_contract(db_session, roster="mixed")
    monkeypatch.setattr(ops_router, "_reuse_clock", lambda: 1000.0)
    before = _schedule_summary(await _get(api_client, "/api/status"))
    await change(db_session, monkeypatch)
    await db_session.commit()

    after = _schedule_summary(await _get(api_client, "/api/status"))
    ops_router.forget_scan_bound()
    fresh = _schedule_summary(await _get(api_client, "/api/status"))
    assert after != before, "the change matters to the scheduler's summary"
    assert after == fresh, "and the next read shows it inside the reuse window"
