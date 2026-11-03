"""The tier switch answers an outcome; the router turns it into a status code.

Two halves, because what they must satisfy is different, so they are tested
apart:

1. **The policy** decides, with a fake spawn, and never touches HTTP. The
   orderings are the claims — the choice is committed BEFORE the spawn is
   attempted (a spawn that outruns the commit reads the old choice), and a stop
   signals the process BEFORE restoring the choice (moving it under a live
   encoder manufactures the mixed-space corpus the stop exists to prevent).
2. **The mapping** from every outcome to a status code is exhaustive. This is
   the failure the split makes possible: add an outcome, forget a branch, and
   the handler answers 200 with a body that says the opposite. Each case list
   below is asserted to cover its whole enum, so a new member fails here by name
   rather than shipping as a silent success.

What the switch does to the stored choice and the decision file is
`test_embedding_tier_choice.py`, which drives the real thing end to end.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from tracker.api.routers import intelligence as router
from tracker.db.models import AppSetting
from tracker.semantic import matching, provision
from tracker.semantic.manifest import TIER_FP32, TIER_INT8

pytestmark = pytest.mark.usefixtures("no_escape")


class _Session:
    """app_settings-backed fake: `get` serves stored rows, `execute` upserts."""

    def __init__(self, rows: dict[str, dict] | None = None):
        self.rows = dict(rows or {})
        self.steps: list[str] = []

    async def get(self, model, key):
        assert model is AppSetting
        value = self.rows.get(key)
        return AppSetting(key=key, value=value) if value is not None else None

    async def execute(self, stmt, params=None):
        compiled = stmt.compile()
        self.steps.append(f"write:{compiled.params['key']}")
        self.rows[compiled.params["key"]] = compiled.params["value"]

    async def commit(self):
        self.steps.append("commit")


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A Mac that auto-selects int8, with its decision file in the test's dir."""
    monkeypatch.setattr(provision, "DATA_DIR", tmp_path)
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr(matching.embed, "reset_model", lambda: None)
    provision.set_tier(None)
    return tmp_path


def _spawn(record: list, *, ok: bool = True):
    async def spawn() -> bool:
        record.append("spawn")
        return ok

    return spawn


# --------------------------------------------------------------------------- #
# 1. Switching
# --------------------------------------------------------------------------- #


def test_a_running_reembed_refuses_the_switch_before_anything_is_written(machine):
    session = _Session()
    spawned: list[str] = []

    outcome = asyncio.run(
        matching.switch_tier(session, TIER_FP32, reembed_running=True, spawn=_spawn(spawned))
    )

    assert outcome is matching.TierSwitch.BUSY
    assert (session.steps, spawned) == ([], [])


def test_reselecting_the_active_tier_writes_nothing_and_spawns_nothing(machine):
    """Reselecting the active tier must avoid writes and unnecessary re-embedding."""
    session = _Session()
    spawned: list[str] = []

    outcome = asyncio.run(
        matching.switch_tier(session, None, reembed_running=False, spawn=_spawn(spawned))
    )

    assert outcome is matching.TierSwitch.NOOP
    assert (session.steps, spawned) == ([], [])


def test_pinning_the_tier_auto_already_chose_records_it_but_starts_nothing(machine):
    session = _Session()
    spawned: list[str] = []

    outcome = asyncio.run(
        matching.switch_tier(session, TIER_INT8, reembed_running=False, spawn=_spawn(spawned))
    )

    assert outcome is matching.TierSwitch.CHOSEN_SAME_TIER
    assert session.steps == ["write:embedding_tier", "commit"], "the choice is still recorded"
    assert spawned == [], "nothing moved, so there is nothing to re-embed"
    assert provision.resolve_tier() == TIER_INT8


def test_a_real_switch_commits_the_choice_before_it_tries_to_spawn(machine):
    """A spawn that outran the commit would read the old choice from the shared
    row and re-embed to the tier the user just left."""
    session = _Session()
    order: list[str] = []
    session.steps = order

    outcome = asyncio.run(
        matching.switch_tier(session, TIER_FP32, reembed_running=False, spawn=_spawn(order))
    )

    assert outcome is matching.TierSwitch.STARTED
    assert order == ["write:embedding_tier", "commit", "spawn"]
    assert provision.resolve_tier() == TIER_FP32


def test_a_failed_spawn_is_reported_with_the_choice_already_committed(machine):
    """The corpus now disagrees with the choice, so the nightly pass finishes the
    work — but saying nothing would show a settled screen while nothing runs."""
    session = _Session()
    order: list[str] = []
    session.steps = order

    outcome = asyncio.run(
        matching.switch_tier(
            session, TIER_FP32, reembed_running=False, spawn=_spawn(order, ok=False)
        )
    )

    assert outcome is matching.TierSwitch.SPAWN_FAILED
    assert order == ["write:embedding_tier", "commit", "spawn"]
    assert provision.resolve_tier() == TIER_FP32, "the choice stands; only the job failed"


# --------------------------------------------------------------------------- #
# 2. Stopping
# --------------------------------------------------------------------------- #


async def _never_running() -> bool:
    return False


async def _still_running() -> bool:
    return True


def _stop(session, *, running=True, outcome="stopped", still=_never_running):
    calls: list[str] = []

    async def terminate():
        calls.append("terminate")
        return outcome, 48_311

    result = asyncio.run(
        matching.stop_switch(
            session, reembed_running=running, terminate=terminate, still_running=still
        )
    )
    return result, calls


def test_stopping_nothing_is_refused_without_signalling(machine):
    session = _Session()

    result, calls = _stop(session, running=False)

    assert result.verdict is matching.StopSwitch.NOT_RUNNING
    assert (calls, session.steps) == ([], [])


def test_a_process_that_cannot_be_signalled_leaves_the_choice_alone(machine):
    provision.set_tier(TIER_FP32)
    session = _Session({"embedding_tier": {"tier": TIER_FP32}})

    result, calls = _stop(session, outcome="error")

    assert result.verdict is matching.StopSwitch.COULD_NOT_STOP
    assert calls == ["terminate"]
    assert session.steps == [], "moving the choice under a live encoder is the mixed-space bug"
    assert provision.resolve_tier() == TIER_FP32


def test_an_embedder_we_did_not_spawn_is_never_called_a_stopped_switch(machine):
    provision.set_tier(TIER_FP32)
    session = _Session({"embedding_tier": {"tier": TIER_FP32}})

    result, _calls = _stop(session, outcome="not_running", still=_still_running)

    assert result.verdict is matching.StopSwitch.UNMANAGED
    assert session.steps == []
    assert provision.resolve_tier() == TIER_FP32


def test_a_stop_signals_first_and_only_then_restores_the_choice(machine):
    """Order is the claim: a batch landing after the choice moves back is
    harmless, because every row carries the tier that produced it."""
    provision.set_tier(TIER_FP32)
    session = _Session({"embedding_tier": {"tier": TIER_FP32}})
    order: list[str] = []
    session.steps = order

    async def terminate():
        order.append("terminate")
        return "stopped", 48_311

    result = asyncio.run(
        matching.stop_switch(
            session, reembed_running=True, terminate=terminate, still_running=_never_running
        )
    )

    assert result == matching.StopResult(matching.StopSwitch.STOPPED, "stopped")
    assert order == ["terminate", "write:embedding_tier", "commit"]
    assert provision.resolve_tier() == TIER_INT8, "back to what auto chooses"


# --------------------------------------------------------------------------- #
# 3. Resuming
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("running", "spawn_ok", "expected"),
    [
        (True, True, matching.ResumeSwitch.BUSY),
        (False, True, matching.ResumeSwitch.STARTED),
        (False, False, matching.ResumeSwitch.SPAWN_FAILED),
    ],
)
def test_resuming_reports_what_happened(machine, running, spawn_ok, expected):
    spawned: list[str] = []

    outcome = asyncio.run(matching.resume_switch(
        reembed_running=running, spawn=_spawn(spawned, ok=spawn_ok)
    ))

    assert outcome is expected
    assert spawned == ([] if running else ["spawn"])


# --------------------------------------------------------------------------- #
# 4. Every outcome is mapped, or the handler answers 200 with the opposite
# --------------------------------------------------------------------------- #

SWITCH_STATUS = {
    matching.TierSwitch.BUSY: 409,
    matching.TierSwitch.NOOP: 200,
    matching.TierSwitch.CHOSEN_SAME_TIER: 200,
    matching.TierSwitch.STARTED: 200,
    matching.TierSwitch.SPAWN_FAILED: 503,
}
STOP_STATUS = {
    matching.StopSwitch.NOT_RUNNING: 409,
    matching.StopSwitch.COULD_NOT_STOP: 503,
    matching.StopSwitch.UNMANAGED: 409,
    matching.StopSwitch.STOPPED: 200,
}
RESUME_STATUS = {
    matching.ResumeSwitch.BUSY: 409,
    matching.ResumeSwitch.SPAWN_FAILED: 503,
    matching.ResumeSwitch.STARTED: 200,
}


@pytest.fixture
def handler(monkeypatch):
    """The router with its owner and its state builder replaced."""

    async def state(_session):
        return {"matching": {"tier": TIER_INT8}}

    async def not_running(_session):
        return False

    monkeypatch.setattr(router, "_intelligence_state", state)
    monkeypatch.setattr(router, "_reembed_in_progress", not_running)
    async def no(): return False
    async def yes(): return True
    async def stopped(): return "stopped", 1

    monkeypatch.setattr(router, "_processes", lambda _session: router._Processes(
        running=no, spawn=yes, terminate=stopped
    ))
    return router


def _status_of(call) -> int:
    try:
        asyncio.run(call())
    except HTTPException as error:
        return error.status_code
    return 200


@pytest.mark.parametrize("outcome", sorted(SWITCH_STATUS, key=lambda item: item.value))
def test_every_switch_outcome_has_a_status(handler, monkeypatch, outcome):
    assert set(SWITCH_STATUS) == set(matching.TierSwitch), "a new outcome is unmapped"

    async def switch(*_args, **_kwargs):
        return outcome

    monkeypatch.setattr(matching, "switch_tier", switch)
    call = lambda: handler.put_matching_tier_ep(  # noqa: E731
        handler.MatchingTierPayload(tier=TIER_FP32), _Session()
    )
    assert _status_of(call) == SWITCH_STATUS[outcome]


@pytest.mark.parametrize("verdict", sorted(STOP_STATUS, key=lambda item: item.value))
def test_every_stop_verdict_has_a_status(handler, monkeypatch, verdict):
    assert set(STOP_STATUS) == set(matching.StopSwitch), "a new verdict is unmapped"

    async def stop(*_args, **_kwargs):
        return matching.StopResult(verdict, "stopped")

    monkeypatch.setattr(matching, "stop_switch", stop)
    assert _status_of(lambda: handler.stop_matching_switch(_Session())) == STOP_STATUS[verdict]


@pytest.mark.parametrize("outcome", sorted(RESUME_STATUS, key=lambda item: item.value))
def test_every_resume_outcome_has_a_status(handler, monkeypatch, outcome):
    assert set(RESUME_STATUS) == set(matching.ResumeSwitch), "a new outcome is unmapped"
    async def resume(**_kwargs):
        return outcome

    monkeypatch.setattr(matching, "resume_switch", resume)
    assert _status_of(lambda: handler.resume_matching_switch(_Session())) == RESUME_STATUS[outcome]
