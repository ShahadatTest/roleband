"""A finished run says what its turn was, from the job's own return value.

The payloads are the shapes the scheduler tick and the directory sweep really
return; a tick that found its lock held and one that read boards both exit 0.
"""

from __future__ import annotations

import json

import pytest

from tracker.platform.power import WAITING_FOR_FULL_WAKE, WAITING_FOR_MAINS
from tracker.supervisor import entries, results
from tracker.supervisor.results import summarize

#: The entries module can start the scan in-process; nothing here may.
pytestmark = pytest.mark.usefixtures("no_escape")

TICK_RAN = {
    "ran": True,
    "work": [{"binding_id": 7, "company": "stripe", "provider": "greenhouse", "mode": "reconcile"}],
    "plan_kind": "full",
    "summary": {"run_id": 2826, "status": "ok", "jobs_seen": 412},
    "usage": {"sent": 0},
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (TICK_RAN, {"kind": "ran", "links": {"scrape_run": 2826}}),
        ({"ran": False, "reason": "run in progress", "work": []}, {"kind": "busy", "reason": "busy_external"}),
        ({"ran": False, "work": [], "reason": WAITING_FOR_FULL_WAKE}, {"kind": "waiting", "reason": "waiting_for_wake"}),
        ({"ran": False, "work": [], "reason": WAITING_FOR_MAINS}, {"kind": "waiting", "reason": "waiting_for_mains"}),
        ({"ran": False, "work": [], "reason": "nothing due", "retention": {"removed": 0}}, {"kind": "nothing_due"}),
        (
            {"ran": False, "work": [], "summary": {"skipped": "run already in progress", "status": "skipped"}},
            {"kind": "busy", "reason": "busy_external"},
        ),
    ],
)
def test_a_scan_tick_s_turn_is_told_by_what_it_returned(raw, expected):
    assert summarize("scan", 0, raw) == expected


def test_a_scan_that_crashed_failed_whatever_it_printed():
    assert summarize("scan", 1, TICK_RAN)["kind"] == "failed"
    assert summarize("scan", 0, None)["kind"] == "failed", "exit 0 with no account is not a success"


def test_a_sweep_that_read_any_pass_ran_and_counts_what_it_checked():
    passes = [
        {"ran": True, "checked": 40, "recorded": 38},
        {"ran": True, "checked": 12, "recorded": 12},
        {"ran": False, "reason": "nothing due", "size": 4000},
    ]
    assert summarize("directory", 0, passes) == {"kind": "ran", "links": {"checked": 52}}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("a pass is already running", {"kind": "busy", "reason": "busy_external"}),
        ("a scan goes first", {"kind": "waiting", "reason": "yielding_to_sync"}),
        (WAITING_FOR_MAINS, {"kind": "waiting", "reason": "waiting_for_mains"}),
        ("nothing due", {"kind": "nothing_due"}),
        ("the set is not followed", {"kind": "nothing_due"}),
    ],
)
def test_a_sweep_that_read_nothing_says_why(reason, expected):
    assert summarize("directory", 0, [{"ran": False, "reason": reason}]) == expected


@pytest.mark.parametrize(
    ("job", "code", "kind"),
    [
        ("reestimate", 0, "ran"),
        ("reestimate", results.REESTIMATE_LOCKED, "busy"),
        ("reestimate", 1, "failed"),
        ("preflight", 0, "ran"),
        ("preflight", results.PREFLIGHT_REFUSED, "refused"),
        ("preflight", results.PREFLIGHT_TREE_MOVED, "refused"),
        ("preflight", results.PREFLIGHT_BUSY, "busy"),
        ("backup", 0, "ran"),
        ("backup", 1, "failed"),
        ("backup", -15, "failed"),
    ],
)
def test_a_command_s_turn_is_told_by_its_exit_code(job, code, kind):
    assert summarize(job, code, None)["kind"] == kind


def test_the_runs_retention_treats_as_no_op_exactly_the_kinds_that_did_no_work():
    from tracker.db.job_store import NO_OP_KINDS

    assert set(NO_OP_KINDS) == {results.NOTHING_DUE, results.WAITING, results.BUSY}


def test_an_entry_writes_its_return_value_for_the_run(tmp_path, monkeypatch, capsys):
    target = tmp_path / "7.raw.json"
    monkeypatch.setenv(entries.RAW_ENV, str(target))

    async def tick():
        return {"ran": False, "reason": "nothing due", "work": []}

    monkeypatch.setitem(entries.ENTRIES, "scan", tick)
    assert entries.main(["scan"]) == 0
    assert json.loads(target.read_text()) == {"ran": False, "reason": "nothing due", "work": []}
    assert '"nothing due"' in capsys.readouterr().out


def test_an_unknown_entry_is_refused():
    assert entries.main(["nope"]) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"started": ["tpl:refresh"], "waiting": None}, {"kind": "ran"}),
        ({"started": [], "waiting": WAITING_FOR_FULL_WAKE}, {"kind": "waiting", "reason": "waiting_for_wake"}),
        ({"started": [], "waiting": None}, {"kind": "nothing_due"}),
    ],
)
def test_a_plugins_due_look_says_whether_it_asked_for_anything(raw, expected):
    assert summarize("plugins_due", 0, raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"sent": 12, "outcome": "sent", "status": 200, "left_out": 0, "pruned": 3}, {"kind": "ran"}),
        ({"sent": 0, "reason": "not due"}, {"kind": "nothing_due"}),
        ({"sent": 0, "reason": "switched off by ROLEBAND_NO_USAGE"}, {"kind": "nothing_due"}),
        ({"sent": 0, "reason": WAITING_FOR_FULL_WAKE}, {"kind": "waiting", "reason": "waiting_for_wake"}),
        (
            {"sent": 0, "outcome": "retry", "status": 503, "left_out": 0, "pruned": 0},
            {"kind": "failed", "reason": "not_delivered"},
        ),
    ],
)
def test_a_usage_send_says_whether_anything_went_and_why_not(raw, expected):
    assert summarize("usage_send", 0, raw) == expected


def test_a_usage_send_that_crashed_failed():
    assert summarize("usage_send", 1, None) == {"kind": "failed"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"status": "ok", "companies": {"stripe": {"scanned": 40}, "figma": {"scanned": 12}}},
         {"kind": "ran", "links": {"companies": 2}}),
        ({"status": "yielded", "reason": "scrape took priority", "companies": {"stripe": {}}},
         {"kind": "ran", "links": {"companies": 1}}),
        ({"status": "deferred", "reason": "pipeline lock held"}, {"kind": "busy", "reason": "busy"}),
        ({"status": "surprise"}, {"kind": "failed"}),
    ],
)
def test_a_discovery_says_whether_it_read_and_how_many_companies(raw, expected):
    assert summarize("role_discovery", 0, raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"jobs": 900, "fingerprinted": 3, "embedded": 880, "intent_reembedded": True},
         {"kind": "ran", "links": {"embedded": 880}}),
        ({"ran": False, "reason": "another embedder is running"}, {"kind": "busy", "reason": "busy_external"}),
    ],
)
def test_a_reembed_says_what_it_embedded_or_who_held_the_turn(raw, expected):
    assert summarize("reembed", 0, raw) == expected


@pytest.mark.parametrize("job", ["role_discovery", "reembed"])
def test_a_discovery_or_reembed_that_crashed_failed(job):
    assert summarize(job, 1, None) == {"kind": "failed"}


def test_discovery_takes_the_request_s_arguments_and_no_other_entry_takes_any(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    async def discovery(argv):
        seen.append(list(argv))
        return {"status": "ok", "companies": {}}

    monkeypatch.setenv(entries.RAW_ENV, str(tmp_path / "raw.json"))
    monkeypatch.setitem(entries.WITH_ARGUMENTS, "role_discovery", discovery)
    assert entries.main(["role_discovery", "--company", "acme", "--max-list", "150", "-v"]) == 0
    assert entries.main(["role_discovery"]) == 0
    assert seen == [["--company", "acme", "--max-list", "150", "-v"], []]
    assert entries.main(["scan", "--company", "acme"]) == 2


@pytest.mark.asyncio
async def test_the_discovery_entry_reads_the_companies_places_and_cap_it_was_given(monkeypatch):
    from tracker.platform import ratelimit
    from tracker.workflows import discover_roles

    calls: list[dict] = []

    async def discover(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "companies": {}}

    monkeypatch.setattr(discover_roles, "discover", discover)
    monkeypatch.setattr(ratelimit, "enable_shared_pacing", lambda _path: None)
    await entries.role_discovery(["--company", "acme", "figma", "--max-list", "150", "--location", "london"])
    assert calls == [{"companies": ["acme", "figma"], "max_list": 150, "locations": ["london"]}]


@pytest.mark.asyncio
async def test_a_reembed_another_embedder_holds_is_a_turn_not_taken(monkeypatch):
    from tracker.semantic import backfill

    async def held(**_kwargs):
        raise backfill.AlreadyEmbedding("another embedder is already running")

    monkeypatch.setattr(backfill, "run", held)
    assert await entries.reembed() == {"ran": False, "reason": "another embedder is running"}


def test_a_rehearsed_turn_did_nothing_whatever_the_job():
    assert summarize("scan", 0, {"dry_run": True, "tick": TICK_RAN}) == {"kind": "nothing_due", "reason": "dry_run"}
    assert summarize("plugin_run", 0, {"dry_run": True, "argv": ["tpl"]}) == {"kind": "nothing_due", "reason": "dry_run"}
    assert summarize("scan", 1, {"dry_run": True}) == {"kind": "failed"}, "a rehearsal can still crash"


def test_a_rehearsed_scan_plans_its_tick_and_a_rehearsed_send_sends_nothing(tmp_path, monkeypatch):
    from tracker.platform.locks import run_lock
    from tracker.workflows import scheduler

    # The tick takes the real flock. A private data directory keeps a live scan
    # holding this checkout's `daily.lock` from answering in this test's place.
    monkeypatch.setattr(scheduler, "DATA_DIR", tmp_path)
    planned: list[bool] = []

    async def run_once(*, dry_run):
        planned.append(dry_run)
        return {"ran": False, "work": [], "reason": "dry_run"}

    async def flush(**_kwargs):
        raise AssertionError("a rehearsal sends nothing")

    monkeypatch.setattr(scheduler, "run_once", run_once)
    monkeypatch.setattr("tracker.usage_stats.flush.flush_if_due", flush)
    monkeypatch.setenv(entries.DRY_RUN_ENV, "1")
    monkeypatch.setenv(entries.RAW_ENV, str(tmp_path / "raw.json"))
    assert entries.main(["scan"]) == 0
    assert planned == [True]
    assert json.loads((tmp_path / "raw.json").read_text())["dry_run"] is True
    with run_lock(tmp_path / "daily.lock"):
        assert entries.main(["scan"]) == 0
    assert planned == [True], "a rehearsal waits out a held run lock like a real tick"
    assert json.loads((tmp_path / "raw.json").read_text())["tick"]["reason"] == "run in progress"
    assert entries.main(["usage_send"]) == 0
    assert json.loads((tmp_path / "raw.json").read_text()) == {"dry_run": True}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"skipped": "no_key"}, {"kind": "nothing_due", "reason": "no_key"}),
        ({"skipped": "busy"}, {"kind": "busy", "reason": "busy_external"}),
        ({"priced": 3, "failed": 0, "deferred": 0, "refused": None, "next_at": "2026-10-20T06:00:00+00:00"},
         {"kind": "ran", "next_at": "2026-10-20T06:00:00+00:00"}),
        ({"priced": 0, "failed": 0, "deferred": 9, "refused": "rate_limited", "next_at": "2026-10-19T19:00:00+00:00"},
         {"kind": "waiting", "reason": "rate_limited", "next_at": "2026-10-19T19:00:00+00:00", "deferred": 9}),
        ({"priced": 0, "failed": 1, "deferred": 4, "refused": "unauthorized", "next_at": None},
         {"kind": "refused", "reason": "key_refused", "deferred": 4}),
        ({"priced": 0, "failed": 0, "deferred": 0, "refused": None, "next_at": None}, {"kind": "nothing_due"}),
    ],
)
def test_a_price_run_says_what_it_did_and_when_it_wants_to_look_again(raw, expected):
    assert summarize("prices", 0, raw) == expected


def test_a_job_that_keeps_its_own_deadline_reads_it_from_its_last_run():
    from datetime import UTC, datetime

    from tracker.db.models import JobRun
    from tracker.supervisor.plan import DEADLINE_AFTER_FAILURE, deadline_of

    ended = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    named = JobRun(job="prices", key="prices", state="exited", ended_at=ended,
                   result={"kind": "ran", "next_at": "2026-10-19T18:00:00+00:00"})
    assert deadline_of(named) == datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
    crashed = JobRun(job="prices", key="prices", state="exited", ended_at=ended, result={"kind": "failed"})
    assert deadline_of(crashed) == ended + DEADLINE_AFTER_FAILURE
    idle = JobRun(job="prices", key="prices", state="exited", ended_at=ended, result={"kind": "nothing_due", "reason": "no_key"})
    assert deadline_of(idle) is None, "no key, no schedule: a save asks"
    live = JobRun(job="prices", key="prices", state="running", result=None)
    assert deadline_of(live) is None


def test_an_entry_logs_the_head_of_a_long_return_value_and_keeps_all_of_it(tmp_path, monkeypatch, capsys):
    target = tmp_path / "raw.json"
    monkeypatch.setenv(entries.RAW_ENV, str(target))
    work = [{"binding_id": n, "company": "acme"} for n in range(5000)]

    async def tick():
        return {"ran": False, "reason": "nothing due", "work": work}

    monkeypatch.setitem(entries.ENTRIES, "scan", tick)
    assert entries.main(["scan"]) == 0
    logged = capsys.readouterr().out
    assert len(logged) < entries.LOG_CHARS + 100
    assert len(json.loads(target.read_text())["work"]) == 5000


def test_a_preflight_another_one_held_off_is_no_verdict_on_the_tree():
    """Exit 77 is the script's busy lock: the tree is checked again, never held as failed."""
    from datetime import UTC, datetime

    from tracker.supervisor import gate

    tracker = gate.Tracker()
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    tracker.observe(gate.Reading(False, "f" * 64), now, checking=False)
    tracker.finished("f" * 64, gate.BUSY)
    assert tracker.observe(gate.Reading(False, "f" * 64), now, checking=False) is gate.Gate.UNKNOWN
    assert tracker.changed_since() == now, "it is due for another check"
    tracker.finished("f" * 64, gate.REFUSED)
    assert tracker.observe(gate.Reading(False, "f" * 64), now, checking=False) is gate.Gate.FAILED
