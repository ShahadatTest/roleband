"""The AI settings, matching, self-test, fit and agent routes' response contract.

`tracker/api/schemas/intelligence.py` declares what these routes send. These
tests hold it to its sources:

1. **Vocabularies**: each Literal against the enum, tuple or table it mirrors.
2. **The state** over real HTTP on a machine `pin_integration_machine` owns:
   provisioning as each scenario leaves it, the corpus measured against the active
   tier, the routing ladder built from saved profiles and recorded attempts, the
   egress and Apple switches read back, and the unpinned-model branch.
3. **Matching writes**: a switch recorded in the database and the decision file
   and started once; a no-op, a pin of the auto value, a refusal while running and
   an unknown tier each starting nothing; a stop that goes back, one that cannot
   signal, one over an embedder the app does not manage, and one that finds the
   job already gone; a resume that leaves the choice alone.
4. **The self-test** through a scripted provider: each of the four outcomes with
   exactly its keys, what it logs, and that it is a dry run.
5. **Fit**: the histogram over the board's browse base, bands that partition it,
   and each band's preview best first, clamped and refused.
6. **Agents**: both gates saved and read back, a rejected save changing nothing.
7. **Drift**: a key a builder adds or drops fails the response.

`no_escape` guards every test: a tier switch and a resume would otherwise start
a real re-embed, and the self-test would reach a real model.
"""

from __future__ import annotations

from datetime import timedelta
from typing import get_args

import pytest
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel, RootModel
from sqlalchemy import func, select

from tests.api_errors import said
from tests.intelligence_contract_seed import (
    INTENT_STATEMENT,
    RAM_32_GIB,
    PinnedMachine,
    hold_reembed_lock,
    pin_integration_machine,
    seed_embed_measurement,
    seed_fit,
    seed_routing,
)
from tracker.api.routers import intelligence as router
from tracker.api.schemas import intelligence as contract
from tracker.api.schemas.jobs import JobRow
from tracker.config import get_settings
from tracker.db.models import AiTaskLog, Job
from tracker.intelligence.prompts import PROMPT_VERSION
from tracker.intelligence.provider import (
    AvailabilityState,
    GenerationResult,
    ProviderOrigin,
    RouteAttempt,
)
from tracker.intelligence_runtime.selftest import EXPECTED_HINT, SAMPLE_POSTING, TEST_TASK
from tracker.pay_disclosure import DisclosedComp
from tracker.platform.paths import REPO_ROOT
from tracker.search import fit
from tracker.semantic import matching as matching_policy
from tracker.semantic import provision
from tracker.semantic.manifest import spec_for
from tracker.settings_store import set_intent_embedding

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

GROUNDED_FIELDS = {
    "disclosed": True,
    "base_min": 180000,
    "base_max": 240000,
    "currency": "USD",
    "pay_basis": "base",
    "pay_period": "year",
    "source_snippet": "$180,000—$240,000 USD",
    "confidence": "high",
}


@pytest.fixture
def machine(monkeypatch, tmp_path, no_escape) -> PinnedMachine:
    return pin_integration_machine(monkeypatch, tmp_path)


def _fields(model) -> list[str]:
    return [field.alias or name for name, field in model.model_fields.items()]


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _call(api_client, method: str, path: str, json=None, status: int = 200) -> dict:
    response = await api_client.request(method, path, json=json)
    assert response.status_code == status, response.text
    return response.json()


async def _state(api_client) -> dict:
    return await _call(api_client, "GET", "/api/intelligence")


def _sizes(tier: str) -> int:
    spec = spec_for(get_settings().embedding_model)
    return spec.tiers[tier].size + spec.tokenizer.size


def _answer(fields: dict, *, origin=ProviderOrigin.ON_DEVICE, reason="primary") -> GenerationResult:
    return GenerationResult(
        fields=fields,
        availability_state=AvailabilityState.AVAILABLE,
        latency_ms=1100,
        input_tokens=412,
        output_tokens=58,
        provider_name="apple_fm",
        model_id="apple-fm-on-device",
        origin=origin,
        route_reason=reason,
        attempts=[RouteAttempt("apple_fm", origin, "ok", reason, 1100)],
    )


async def _self_test_rows(db_session) -> list[tuple[str, str | None]]:
    rows = await db_session.execute(
        select(AiTaskLog.validation_result, AiTaskLog.failure_class)
        .where(AiTaskLog.task_type == TEST_TASK)
        .order_by(AiTaskLog.id)
    )
    return [tuple(row) for row in rows]


# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def test_each_literal_is_the_vocabulary_it_mirrors():
    assert set(get_args(contract.AvailabilityStateName)) == {s.value for s in AvailabilityState}
    assert set(get_args(contract.ProviderOriginName)) == {o.value for o in ProviderOrigin}
    assert set(get_args(contract.MatchingTierName)) == set(provision.TIERS)
    assert set(get_args(contract.FitBandKey)) == fit.BAND_KEYS
    assert set(contract.ExtractedDisclosedComp.model_fields) == set(DisclosedComp.model_fields)


def test_every_shape_forbids_a_key_its_model_does_not_name():
    built = [
        model
        for model in vars(contract).values()
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__module__ == contract.__name__
        and not issubclass(model, RootModel)
    ]
    assert len(built) >= 25
    assert all(model.model_config.get("extra") == "forbid" for model in built), [
        model.__name__ for model in built if model.model_config.get("extra") != "forbid"
    ]


# --------------------------------------------------------------------------- #
# 2. The state
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_fresh_machine_decides_its_tier_from_ram_and_says_who_decided(api_client, machine):
    body = await _state(api_client)
    assert list(body) == _fields(contract.IntelligenceStateResponse)
    assert list(body["matching"]) == _fields(contract.MatchingState)
    assert body["matching"] == {
        "status": "ready",
        "tier": "fp32",
        "model_id": get_settings().embedding_model,
        "downloaded_bytes": _sizes("fp32"),
        "total_bytes": _sizes("fp32"),
        "chosen_by": "auto",
        "detected_ram_bytes": RAM_32_GIB,
        "ram_threshold_bytes": provision.TIER_RAM_THRESHOLD,
        "tiers": [
            {"tier": "fp32", "total_bytes": _sizes("fp32"), "recommended": True, "installed": True,
             "switch_seconds": None},
            {"tier": "int8", "total_bytes": _sizes("int8"), "recommended": False, "installed": False,
             "switch_seconds": None},
        ],
        "reembedding": False,
        "corpus_embedded": 0,
        "corpus_total": 0,
        "stale_count": 0,
        "other_tier_count": 0,
        "job_phase": "none",
        "estimate_seconds": None,
    }
    assert provision.read_decision() == {"tier": "fp32", "detected_ram_bytes": RAM_32_GIB, "chosen_by": "auto"}
    assert {k: body[k] for k in ("enabled", "provider", "availability", "model_id", "prompt_version", "routing")} == {
        "enabled": False,
        "provider": "null",
        "availability": {
            "state": "disabled_by_flag",
            "ok": False,
            "detail": "integration is turned off",
        },
        "model_id": get_settings().intelligence_model_id,
        "prompt_version": PROMPT_VERSION,
        "routing": {"egress_enabled": False, "tiers": []},
    }


@pytest.mark.asyncio
async def test_undetectable_ram_recommends_nothing_and_takes_the_fail_safe_tier(api_client, machine):
    machine.ram_bytes = None
    matching = (await _state(api_client))["matching"]
    assert (matching["tier"], matching["detected_ram_bytes"]) == ("int8", None)
    assert [option["recommended"] for option in matching["tiers"]] == [False, False]


@pytest.mark.asyncio
async def test_the_routing_ladder_is_built_from_saved_profiles_and_reads_no_task_log(
    api_client, db_session, machine
):
    """Settings polls this read while a model downloads: it shows the ladder as
    configured, and the task log (recorded attempts included) is not read."""
    from sqlalchemy import event

    seeded = await seed_routing(db_session)
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        routing = (await _state(api_client))["routing"]
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert not [sql for sql in statements if "ai_task_log" in sql]
    assert list(routing) == _fields(contract.IntelligenceRouting)
    assert all(list(tier) == _fields(contract.RoutingTier) for tier in routing["tiers"])
    assert routing == {
        "egress_enabled": False,
        "tiers": [
            {"provider": "omlx", "origin": "this_mac", "model_id": seeded.local_model, "blocked_reason": None},
            {"provider": "cloud_openai", "origin": "cloud", "model_id": seeded.cloud_model,
             "blocked_reason": "egress_blocked"},
        ],
    }, "local first; a disabled cloud profile is absent"

    opened = await _call(api_client, "PUT", "/api/intelligence/egress", {"enabled": True})
    assert opened["routing"]["egress_enabled"] is True
    assert [tier["blocked_reason"] for tier in opened["routing"]["tiers"]] == [None, None]
    assert (await _state(api_client))["routing"] == opened["routing"]


@pytest.mark.asyncio
async def test_the_apple_switch_is_saved_and_the_provider_reports_what_it_can_do(api_client, machine):
    machine.apple.state = AvailabilityState.MODEL_NOT_READY
    machine.apple.detail = "model assets are downloading"
    body = await _call(api_client, "PUT", "/api/intelligence", {"enabled": True})
    assert (body["enabled"], body["provider"]) == (True, "apple_fm")
    assert body["availability"] == {
        "state": "model_not_ready",
        "ok": False,
        "detail": "model assets are downloading",
    }
    assert (await _state(api_client))["enabled"] is True
    off = await _call(api_client, "PUT", "/api/intelligence", {"enabled": False})
    assert (off["enabled"], off["availability"]["state"]) == (False, "disabled_by_flag")


@pytest.mark.asyncio
async def test_provisioning_and_the_job_phase_are_named_not_inferred(api_client, db_session, machine):
    machine.provision_status = "downloading"
    downloading = (await _state(api_client))["matching"]
    assert (downloading["status"], downloading["job_phase"]) == ("downloading", "downloading")
    assert downloading["downloaded_bytes"] == int(_sizes("fp32") * machine.downloaded_fraction)

    machine.provision_status = "ready"
    machine.reembedding = True
    converting = (await _state(api_client))["matching"]
    assert (converting["reembedding"], converting["job_phase"]) == (True, "converting")

    machine.reembedding = False
    async with hold_reembed_lock(db_session.bind):
        hand_run = (await _state(api_client))["matching"]
    assert (hand_run["reembedding"], hand_run["job_phase"]) == (True, "converting"), (
        "a backfill the app did not spawn still holds the lock"
    )

    machine.provision_status = "missing"
    missing = (await _state(api_client))["matching"]
    assert (missing["status"], missing["downloaded_bytes"], missing["job_phase"]) == ("missing", 0, "none")


@pytest.mark.asyncio
async def test_corpus_progress_is_counted_and_durations_come_from_this_machine(api_client, db_session, machine):
    await seed_fit(db_session, today=await db_session.scalar(select(func.now())))
    await seed_embed_measurement(db_session)
    rows = await db_session.scalar(select(func.count()).select_from(Job))
    matching = (await _state(api_client))["matching"]
    rate = 4114 / 745.0
    assert (matching["corpus_embedded"], matching["corpus_total"], matching["stale_count"]) == (rows - 1, rows, 1)
    assert matching["estimate_seconds"] == int(1 / rate)
    assert [option["switch_seconds"] for option in matching["tiers"]] == [
        int(rows / rate),
        int(rows / (rate * matching_policy.INT8_RATE_RATIO)),
    ], "the whole corpus at each tier's rate; int8 scaled from the fp32 measurement"


@pytest.mark.asyncio
async def test_only_rows_on_the_other_model_make_a_switch_interrupted(api_client, db_session, machine):
    await seed_fit(db_session, today=await db_session.scalar(select(func.now())))
    first_scan = (await _state(api_client))["matching"]
    # The seed's unembedded row is a scan's backlog, as on a fresh install: work
    # owed, but no switch ever ran.
    assert (first_scan["stale_count"], first_scan["other_tier_count"], first_scan["job_phase"]) == (1, 0, "none")

    other = next(option["tier"] for option in first_scan["tiers"] if option["tier"] != first_scan["tier"])
    moved = (await db_session.scalars(select(Job).where(Job.embedded_tier.is_not(None)).order_by(Job.id).limit(2))).all()
    for job in moved:
        job.embedded_tier = other
    await db_session.commit()
    paused = (await _state(api_client))["matching"]
    assert (paused["stale_count"], paused["other_tier_count"]) == (3, 2)


@pytest.mark.asyncio
async def test_an_unpinned_embedding_model_answers_the_fixed_branch_without_an_estimate(
    api_client, machine, monkeypatch
):
    settings = get_settings().model_copy(update={"embedding_model": "acme/unpinned-embedder"})
    # Both, because the matching projection reads the settings for itself and
    # the router reads them for the rest of the payload.
    for module in (router, matching_policy):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    matching = (await _state(api_client))["matching"]
    assert list(matching) == _fields(contract.MatchingUnpinned)
    assert matching == {
        "status": "missing", "tier": None, "model_id": "acme/unpinned-embedder", "downloaded_bytes": 0,
        "total_bytes": 0, "chosen_by": "auto", "detected_ram_bytes": None,
        "ram_threshold_bytes": provision.TIER_RAM_THRESHOLD, "tiers": [],
        "reembedding": False, "stale_count": 0, "other_tier_count": 0, "job_phase": "none",
        "corpus_embedded": 0, "corpus_total": 0,
    }


# --------------------------------------------------------------------------- #
# 3. Matching writes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_switch_is_recorded_everywhere_and_started_once(api_client, machine):
    await _state(api_client)
    body = await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "int8"})
    assert list(body) == _fields(contract.IntelligenceStateResponse)
    assert {k: body["matching"][k] for k in ("tier", "chosen_by", "reembedding", "job_phase")} == {
        "tier": "int8", "chosen_by": "user", "reembedding": True, "job_phase": "converting",
    }
    assert (machine.spawns, machine.resets) == (1, 1)
    assert provision.read_decision() == {"tier": "int8", "detected_ram_bytes": RAM_32_GIB, "chosen_by": "user"}
    assert (await _state(api_client))["matching"] == body["matching"]


@pytest.mark.asyncio
async def test_a_switch_that_moves_nothing_starts_nothing(api_client, machine):
    await _state(api_client)
    pinned = await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "fp32"})
    assert (pinned["matching"]["tier"], pinned["matching"]["chosen_by"]) == ("fp32", "user")
    again = await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "fp32"})
    auto = await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": None})
    assert again["matching"] == pinned["matching"]
    assert (auto["matching"]["tier"], auto["matching"]["chosen_by"]) == ("fp32", "auto")
    assert (machine.spawns, machine.resets) == (0, 0), "pinning, re-selecting and restoring the auto tier move no rows"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "tier", "status", "detail"),
    [
        ("running", "int8", 409, "a re-embed is already running; wait for it to finish before switching again"),
        ("unknown", "fp16", 422, None),
    ],
)
async def test_a_refused_switch_changes_nothing(api_client, machine, scenario, tier, status, detail):
    before = await _state(api_client)
    machine.reembedding = scenario == "running"
    refused = await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": tier}, status=status)
    if detail is not None:
        assert said(refused) == {"detail": detail}
    machine.reembedding = False
    assert (await _state(api_client))["matching"] == before["matching"]
    assert (machine.spawns, provision.read_decision()["chosen_by"]) == (0, "auto")


@pytest.mark.asyncio
async def test_a_switch_that_cannot_start_says_so_and_keeps_the_choice(api_client, machine):
    await _state(api_client)
    machine.spawn_ok = False
    refused = await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "int8"}, status=503)
    assert "could not be started" in said(refused)["detail"]
    matching = (await _state(api_client))["matching"]
    assert {k: matching[k] for k in ("tier", "chosen_by", "reembedding")} == {
        "tier": "int8", "chosen_by": "user", "reembedding": False,
    }, "the choice was committed before the spawn; the next scheduled pass finishes it"


@pytest.mark.asyncio
async def test_a_stop_ends_the_switch_and_goes_back_to_the_automatic_tier(api_client, machine):
    await _state(api_client)
    await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "int8"})
    stopped = await _call(api_client, "POST", "/api/intelligence/matching/stop")
    assert list(stopped) == _fields(contract.MatchingStopResponse)
    assert list(stopped)[:2] == ["stopped", "outcome"]
    assert (stopped["stopped"], stopped["outcome"]) == (True, "stopped")
    assert {k: stopped["matching"][k] for k in ("tier", "chosen_by", "reembedding", "job_phase")} == {
        "tier": "fp32", "chosen_by": "auto", "reembedding": False, "job_phase": "none",
    }
    assert (machine.terminations, machine.resets) == (1, 2)
    assert {k: v for k, v in stopped.items() if k not in ("stopped", "outcome")} == await _state(api_client)


@pytest.mark.asyncio
async def test_a_stop_over_a_job_that_already_exited_reports_it_and_still_goes_back(api_client, machine):
    await _state(api_client)
    await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "int8"})
    machine.terminate_outcome = "not_running"
    stopped = await _call(api_client, "POST", "/api/intelligence/matching/stop")
    assert (stopped["outcome"], stopped["matching"]["tier"], stopped["matching"]["chosen_by"]) == (
        "not_running", "fp32", "auto"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "status", "detail"),
    [
        ("idle", 409, "no switch is running"),
        ("cannot_signal", 503, "the matching update could not be stopped; the model choice was not changed"),
        ("unmanaged", 409, "the running matching update is not managed by the app and cannot be stopped here"),
    ],
)
async def test_a_refused_stop_leaves_the_choice_where_it_was(api_client, db_session, machine, scenario, status, detail):
    await _state(api_client)
    if scenario != "idle":
        await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "int8"})
    before = provision.read_decision()
    if scenario == "cannot_signal":
        machine.terminate_outcome = "error"
    if scenario == "unmanaged":
        machine.reembedding = False
        machine.terminate_outcome = "not_running"
        async with hold_reembed_lock(db_session.bind):
            refused = await _call(api_client, "POST", "/api/intelligence/matching/stop", status=status)
    else:
        refused = await _call(api_client, "POST", "/api/intelligence/matching/stop", status=status)
    assert said(refused) == {"detail": detail}
    assert provision.read_decision() == before
    assert machine.resets == (0 if scenario == "idle" else 1), "only the switch itself reset the encoder"


@pytest.mark.asyncio
async def test_a_resume_finishes_the_owed_work_without_touching_the_choice(api_client, machine):
    await _call(api_client, "PUT", "/api/intelligence/matching/tier", {"tier": "int8"})
    machine.reembedding = False
    busy_refusal = None
    resumed = await _call(api_client, "POST", "/api/intelligence/matching/resume")
    assert list(resumed) == _fields(contract.IntelligenceStateResponse)
    assert {k: resumed["matching"][k] for k in ("tier", "chosen_by", "reembedding")} == {
        "tier": "int8", "chosen_by": "user", "reembedding": True,
    }
    busy_refusal = await _call(api_client, "POST", "/api/intelligence/matching/resume", status=409)
    assert said(busy_refusal) == {"detail": "a switch is already running"}
    machine.reembedding = False
    machine.spawn_ok = False
    failed = await _call(api_client, "POST", "/api/intelligence/matching/resume", status=503)
    assert said(failed) == {"detail": "the update could not be started; it will finish on the next scheduled run"}
    assert machine.spawns == 3 and provision.read_decision()["chosen_by"] == "user"


# --------------------------------------------------------------------------- #
# 4. The self-test
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_switched_off_integration_answers_unavailable_and_logs_a_skip(api_client, db_session, machine):
    body = await _call(api_client, "POST", "/api/intelligence/test", {})
    assert list(body) == _fields(contract.SelfTestUnavailable)
    assert body == {
        "availability": {"state": "disabled_by_flag", "ok": False,
                         "detail": "integration is turned off"},
        "used_sample": True,
        "prompt_version": PROMPT_VERSION,
        "model_id": get_settings().intelligence_model_id,
        "expected": EXPECTED_HINT,
        "ok": False,
    }
    assert await _self_test_rows(db_session) == [("skipped", "unavailable")]


@pytest.mark.asyncio
async def test_text_with_no_pay_is_prefiltered_without_asking_the_model(api_client, db_session, machine):
    await _call(api_client, "PUT", "/api/intelligence", {"enabled": True})
    body = await _call(api_client, "POST", "/api/intelligence/test", {"text": "Staff engineer. Kubernetes."})
    assert list(body) == _fields(contract.SelfTestPrefiltered)
    assert (body["ok"], body["prefiltered"], body["used_sample"], body["expected"], body["raw"], body["extracted"]) == (
        True, True, False, None, None, None
    )
    assert machine.apple.prompts == [] and await _self_test_rows(db_session) == []


@pytest.mark.asyncio
async def test_a_model_failure_names_its_class_and_where_it_ran(api_client, db_session, machine):
    await _call(api_client, "PUT", "/api/intelligence", {"enabled": True})
    machine.apple.result = GenerationResult(
        fields=None, availability_state=AvailabilityState.AVAILABLE, latency_ms=30000, failure_class="timeout",
        provider_name="apple_fm", origin=ProviderOrigin.ON_DEVICE, route_reason="primary",
        attempts=[RouteAttempt("apple_fm", ProviderOrigin.ON_DEVICE, "failed", "primary", 30000, "timeout")],
    )
    body = await _call(api_client, "POST", "/api/intelligence/test", {})
    assert list(body) == _fields(contract.SelfTestModelFailed)
    assert {k: body[k] for k in _fields(contract.SelfTestModelFailed)[5:]} == {
        "ok": False,
        "failure_class": "timeout",
        "latency_ms": 30000,
        "origin": "on_device",
        "left_device": False,
        "answered_by": "apple_fm",
        "route_reason": "primary",
        "route_attempts": [{"provider": "apple_fm", "origin": "on_device", "outcome": "failed",
                            "reason": "primary", "latency_ms": 30000, "failure_class": "timeout"}],
    }
    assert await _self_test_rows(db_session) == [("invalid", "timeout")]


@pytest.mark.asyncio
async def test_a_grounded_answer_serves_the_raw_output_and_what_would_be_stored(api_client, db_session, machine):
    await _call(api_client, "PUT", "/api/intelligence", {"enabled": True})
    machine.apple.result = _answer(dict(GROUNDED_FIELDS))
    body = await _call(api_client, "POST", "/api/intelligence/test", {})
    assert list(body) == _fields(contract.SelfTestAnswered)
    assert list(body["extracted"]) == _fields(contract.ExtractedDisclosedComp)
    assert body["raw"] == GROUNDED_FIELDS and list(body["raw"]) == list(GROUNDED_FIELDS), "served as it came"
    assert body["extracted"] == DisclosedComp.model_validate(body["extracted"]).model_dump(mode="json")
    assert {k: body["extracted"][k] for k in ("disclosed", "base_min", "base_max", "currency")} == {
        "disclosed": True, "base_min": 180000, "base_max": 240000, "currency": "USD",
    }
    assert "$180,000—$240,000 USD" in body["extracted"]["source_snippet"], "sliced from the posting, not the model"
    assert (body["ok"], body["prefiltered"], body["grounded"], body["rejected_ungrounded"], body["truncated"]) == (
        True, False, True, False, False
    )
    assert (body["input_tokens"], body["output_tokens"]) == (412, 58)
    assert machine.apple.prompts and SAMPLE_POSTING.split("\n")[0] in machine.apple.prompts[0]
    assert await _self_test_rows(db_session) == [("ok", None)]
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0, "a dry run writes no job"


@pytest.mark.asyncio
async def test_a_band_the_posting_does_not_state_is_rejected(api_client, db_session, machine):
    await _call(api_client, "PUT", "/api/intelligence", {"enabled": True})
    machine.apple.result = _answer({**GROUNDED_FIELDS, "base_min": 310000, "base_max": 400000,
                                    "source_snippet": "$310,000-$400,000"})
    body = await _call(api_client, "POST", "/api/intelligence/test", {"text": SAMPLE_POSTING})
    assert list(body) == _fields(contract.SelfTestAnswered)
    assert (body["used_sample"], body["expected"], body["grounded"], body["rejected_ungrounded"]) == (
        False, None, False, True
    )
    assert body["extracted"]["disclosed"] is False and body["raw"]["base_min"] == 310000
    assert await _self_test_rows(db_session) == [("invalid", "validation")]


# --------------------------------------------------------------------------- #
# 5. Fit
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_without_an_intent_the_board_is_counted_but_not_ranked(api_client, db_session, machine):
    today = await db_session.scalar(select(func.now()))
    seeded = await seed_fit(db_session, today=today)
    await set_intent_embedding(db_session, "", [])
    await db_session.commit()
    body = await _call(api_client, "GET", "/api/intelligence/fit")
    assert list(body) == _fields(contract.IntelligenceFitResponse)
    assert body == {
        "ranked": False, "intent_statement": INTENT_STATEMENT, "total": 7, "unranked": None,
        "embedded_today": 2, "last_embedded_at": _iso(seeded.last_embedded_at), "bin_width": fit.FIT_BIN_WIDTH,
        "bins": [], "bands": [],
    }
    for band in ("strong", "weak"):
        assert await _call(api_client, "GET", f"/api/intelligence/fit/band/{band}") == {"band": band, "items": []}


@pytest.mark.asyncio
async def test_the_histogram_ranks_the_browse_base_and_the_bands_partition_it(api_client, db_session, machine):
    today = await db_session.scalar(select(func.now()))
    seeded = await seed_fit(db_session, today=today)
    body = await _call(api_client, "GET", "/api/intelligence/fit")
    assert all(list(item) == _fields(contract.IntelligenceFitBin) for item in body["bins"])
    assert all(list(item) == _fields(contract.IntelligenceFitBand) for item in body["bands"])
    assert body == {
        "ranked": True,
        "intent_statement": INTENT_STATEMENT,
        "total": 7,
        "unranked": 1,
        "embedded_today": 2,
        "last_embedded_at": _iso(seeded.last_embedded_at - timedelta(0)),
        "bin_width": fit.FIT_BIN_WIDTH,
        "bins": [{"fit": 0.3, "count": 1}, {"fit": 0.44, "count": 1}, {"fit": 0.54, "count": 2},
                 {"fit": 0.6, "count": 1}, {"fit": 0.74, "count": 1}],
        # Keys and lower edges; the dashboard names each band and draws it there.
        "bands": [{"key": "strong", "count": 2, "lower_edge": 0.6}, {"key": "good", "count": 2, "lower_edge": 0.5},
                  {"key": "some", "count": 1, "lower_edge": 0.42}, {"key": "weak", "count": 1, "lower_edge": None}],
    }, "a closed and an out-of-scope row are embedded and still outside the base"
    assert sum(b["count"] for b in body["bands"]) == sum(b["count"] for b in body["bins"]) == body["total"] - body["unranked"]


@pytest.mark.asyncio
async def test_each_band_previews_its_strongest_open_roles_best_first(api_client, db_session, machine):
    seeded = await seed_fit(db_session, today=await db_session.scalar(select(func.now())))
    expected = {"strong": seeded.strong, "good": seeded.good, "some": seeded.some, "weak": seeded.weak}
    for band, ids in expected.items():
        body = await _call(api_client, "GET", f"/api/intelligence/fit/band/{band}?limit=12")
        assert list(body) == _fields(contract.IntelligenceFitBandResponse)
        assert [item["id"] for item in body["items"]] == ids
        assert all(list(item) == _fields(JobRow) for item in body["items"])
    first = await _call(api_client, "GET", "/api/intelligence/fit/band/strong?limit=1")
    clamped_low = await _call(api_client, "GET", "/api/intelligence/fit/band/strong?limit=0")
    assert [item["id"] for item in first["items"]] == [item["id"] for item in clamped_low["items"]] == seeded.strong[:1]
    refused = await _call(api_client, "GET", "/api/intelligence/fit/band/excellent", status=404)
    assert said(refused) == {"detail": "unknown fit band"}


# --------------------------------------------------------------------------- #
# 6. Agents
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_agent_access_is_off_until_saved_and_copy_ready_from_the_start(api_client, machine):
    body = await _call(api_client, "GET", "/api/intelligence/agents")
    python = str(REPO_ROOT / "backend" / ".venv" / "bin" / "python")
    cwd = str(REPO_ROOT / "backend")
    assert list(body) == _fields(contract.AgentAccessResponse)
    assert body == {
        "enabled": False,
        "allow_writes": False,
        "transport": "stdio",
        "command": python,
        "args": ["-m", "tracker.mcp.server"],
        "cwd": cwd,
        "tools": [
            {"name": "get_server_status", "access": "status"},
            {"name": "get_radar_summary", "access": "read"},
            {"name": "search_opportunities", "access": "read"},
            {"name": "get_opportunity", "access": "read"},
            {"name": "listing_history", "access": "read"},
            {"name": "get_pursuits", "access": "read"},
            {"name": "save_opportunity", "access": "write"},
            {"name": "update_pursuit", "access": "write"},
            {"name": "get_recipe_contract", "access": "read"},
            {"name": "inspect_source", "access": "read"},
            {"name": "validate_recipe", "access": "read"},
            {"name": "save_recipe_draft", "access": "write"},
        ],
        "codex_command": f"codex mcp add roleband -- {python} -m tracker.mcp.server",
        "claude_json": {"mcpServers": {"roleband": {"command": python, "args": ["-m", "tracker.mcp.server"],
                                                   "cwd": cwd}}},
    }


@pytest.mark.asyncio
async def test_both_agent_gates_are_saved_and_a_rejected_save_changes_neither(api_client, machine):
    saved = await _call(api_client, "PUT", "/api/intelligence/agents", {"enabled": True, "allow_writes": True})
    assert (saved["enabled"], saved["allow_writes"]) == (True, True)
    await _call(api_client, "PUT", "/api/intelligence/agents", {"enabled": "yes", "allow_writes": False}, status=422)
    read = await _call(api_client, "GET", "/api/intelligence/agents")
    assert read == saved


# --------------------------------------------------------------------------- #
# 7. Drift
# --------------------------------------------------------------------------- #


def _add_key(builder):
    async def drifted(*args, **kwargs):
        return {**(await builder(*args, **kwargs)), "unmodelled": True}

    return drifted


def _drop_key(builder, key):
    async def drifted(*args, **kwargs):
        return {k: v for k, v in (await builder(*args, **kwargs)).items() if k != key}

    return drifted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "drift", "method", "path", "body"),
    [
        ("routing_state", _add_key, "GET", "/api/intelligence", None),
        ("matching_state", lambda real: _drop_key(real, "estimate_seconds"), "GET", "/api/intelligence", None),
        ("_intelligence_state", _add_key, "POST", "/api/intelligence/matching/stop", None),
        ("run_self_test", _add_key, "POST", "/api/intelligence/test", {}),
    ],
    ids=["routing_key_added", "estimate_dropped", "stop_state_key_added", "self_test_key_added"],
)
async def test_a_builder_that_drifts_fails_the_response(api_client, machine, monkeypatch, name, drift, method, path, body):
    if name == "_intelligence_state":
        machine.reembedding = True
    monkeypatch.setattr(router, name, drift(getattr(router, name)))
    with pytest.raises(ResponseValidationError):
        await api_client.request(method, path, json=body)


@pytest.mark.asyncio
async def test_agent_and_fit_builders_that_drift_fail_the_response(api_client, db_session, machine, monkeypatch):
    real_agents = router._agent_connection_state
    monkeypatch.setattr(router, "_agent_connection_state", lambda config: {**real_agents(config), "token": "x"})
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/intelligence/agents")

    await seed_fit(db_session, today=await db_session.scalar(select(func.now())))
    real_bands = router.fit_bands
    monkeypatch.setattr(
        router, "fit_bands", lambda by_bin: [{**band, "key": band["key"].upper()} for band in real_bands(by_bin)]
    )
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/intelligence/fit")
