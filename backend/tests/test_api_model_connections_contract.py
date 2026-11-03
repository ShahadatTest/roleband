"""The model connection routes' response contract.

`tracker/api/schemas/intelligence.py` declares what the local and cloud model
connection routes send. These tests hold it to its sources:

1. **Vocabularies**: providers and server actions against the input models and
   `local_llm.server`; a saved connection serves every stored field but its key.
2. **Local connections** over real HTTP: saved, updated, selected, switched off
   and deleted, the key write-only throughout, a refused write changing nothing.
3. **The local server**: its status as each machine leaves it, and a start or
   stop reporting the fresh probe beside what the CLI said, refused for a server
   the app does not manage.
4. **The local test**: an answer, a truncated one, an unsaved draft tested with
   the saved key and never saved, and each failure with what it logs.
5. **Cloud connections** and their test: model discovery for the OpenAI family, a
   one-token message for Anthropic, and the provider's refusals as a 502.
6. **Drift**: a builder that serves the key, drops a key or adds one fails the response.

`no_escape` guards every test and `pin_integration_machine` owns the machine: the
oMLX CLI is a recorded fake process and both model servers are in-process
transports, so no test starts a server or reaches a provider.
"""

from __future__ import annotations

import json
from typing import get_args

import pytest
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import select

import tracker.local_llm.server as omlx_server
from tests.api_errors import code_of, said
from tests.intelligence_contract_seed import (
    CLOUD_KEY,
    LOCAL_KEY,
    LOCAL_REPLY,
    OMLX_BINARY,
    PinnedMachine,
    pin_integration_machine,
    seed_cloud_connection,
    seed_local_connection,
)
from tests.lineage_contract_seed import MODEL_ID, USAGE
from tracker.api.routers import intelligence as router
from tracker.api.schemas import intelligence as contract
from tracker.api.schemas.local_models import LocalModelMetrics, LocalModelProvider
from tracker.cloud_llm.models import CloudLLMProfile, CloudLLMProfileInput
from tracker.db.models import AiTaskLog, AppSetting
from tracker.intelligence_runtime.cloud_profiles import get_state as get_cloud_state
from tracker.intelligence_runtime.local_profiles import get_state as get_local_state
from tracker.local_llm.client import LocalLLMClient
from tracker.local_llm.models import LocalLLMParameters, LocalLLMProfile, LocalLLMProfileInput
from tracker.settings_store import set_ai_egress_enabled

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

LOCAL = "/api/intelligence/local-models"
CLOUD = "/api/intelligence/cloud-models"

#: `tracker.local_llm.client._metrics` over the in-process server's `USAGE`; the
#: pinned clock advances 9.412 s between the two reads around the completion.
METRICS = {
    "wall_time_ms": 9412,
    "total_time_ms": round(USAGE["total_time"] * 1000),
    "time_to_first_token_ms": round(USAGE["time_to_first_token"] * 1000),
    "prompt_eval_ms": round(USAGE["prompt_eval_duration"] * 1000),
    "generation_ms": round(USAGE["generation_duration"] * 1000),
    "prompt_tokens": USAGE["prompt_tokens"],
    "completion_tokens": USAGE["completion_tokens"],
    "total_tokens": USAGE["total_tokens"],
    "cached_prompt_tokens": USAGE["prompt_tokens_details"]["cached_tokens"],
    "prompt_tokens_per_second": USAGE["prompt_tokens_per_second"],
    "generation_tokens_per_second": USAGE["generation_tokens_per_second"],
    "finish_reason": "stop",
    "context_window": 32768,
}

OPENAI_BODY = {
    "name": "OpenAI API", "provider": "openai", "base_url": "https://api.openai.com/v1",
    "model": "gpt-5-mini", "enabled": False, "api_key": None,
}


@pytest.fixture
def machine(monkeypatch, tmp_path, no_escape) -> PinnedMachine:
    return pin_integration_machine(monkeypatch, tmp_path)


def _fields(model) -> list[str]:
    return [field.alias or name for name, field in model.model_fields.items()]


async def _call(api_client, method: str, path: str, json=None, status: int = 200) -> dict:
    response = await api_client.request(method, path, json=json)
    assert response.status_code == status, response.text
    return response.json()


async def _saved_local_key(db_session) -> str | None:
    db_session.expire_all()
    return (await get_local_state(db_session)).profiles[0].api_key


async def _test_log(db_session) -> list[tuple]:
    rows = await db_session.execute(
        select(
            AiTaskLog.provider, AiTaskLog.validation_result, AiTaskLog.failure_class,
            AiTaskLog.latency_ms, AiTaskLog.input_tokens, AiTaskLog.output_tokens, AiTaskLog.model_id,
        )
        .where(AiTaskLog.task_type == "local_llm_test")
        .order_by(AiTaskLog.id)
    )
    return [tuple(row) for row in rows]


# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def test_each_literal_is_the_vocabulary_it_mirrors():
    assert get_args(LocalModelProvider) == get_args(LocalLLMProfileInput.model_fields["provider"].annotation)
    assert get_args(contract.CloudModelProvider) == get_args(CloudLLMProfileInput.model_fields["provider"].annotation)
    assert get_args(contract.LocalServerAction) == get_args(omlx_server.Action)
    assert get_args(contract.LocalServerAction) == get_args(
        router.LocalServerActionPayload.model_fields["action"].annotation
    )


def test_a_saved_connection_serves_every_stored_field_but_its_key():
    assert _fields(contract.LocalModelParameters) == list(LocalLLMParameters.model_fields)
    for served, stored in ((contract.LocalModelProfile, LocalLLMProfile), (contract.CloudModelProfile, CloudLLMProfile)):
        assert set(_fields(served)) == set(stored.model_fields) - {"api_key"} | {"has_api_key"}


# --------------------------------------------------------------------------- #
# 2. Local connections
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_first_connection_is_saved_active_with_its_key_write_only(api_client, db_session, machine):
    assert await _call(api_client, "GET", LOCAL) == {"enabled": True, "active_profile_id": None, "profiles": []}

    response = await api_client.post(LOCAL, json={"name": " Local Qwen ", "model": MODEL_ID, "api_key": LOCAL_KEY})
    assert response.status_code == 201, response.text
    created = response.json()
    assert list(created) == _fields(contract.LocalModelProfile)
    assert list(created["parameters"]) == _fields(contract.LocalModelParameters)
    assert created == {
        "id": created["id"],
        "name": "Local Qwen",
        "provider": "omlx",
        "base_url": "http://127.0.0.1:8000/v1",
        "model": MODEL_ID,
        "has_api_key": True,
        "parameters": LocalLLMParameters().model_dump(),
    }

    listed = await _call(api_client, "GET", LOCAL)
    assert list(listed) == _fields(contract.LocalModelState)
    assert listed == {"enabled": True, "active_profile_id": created["id"], "profiles": [created]}
    assert LOCAL_KEY not in response.text + json.dumps(listed)
    assert await _saved_local_key(db_session) == LOCAL_KEY
    assert machine.local_server.requests == []  # saving is not testing


@pytest.mark.asyncio
async def test_an_update_keeps_the_saved_key_unless_a_new_one_is_sent(api_client, db_session, machine):
    saved = await seed_local_connection(db_session)
    body = {
        "name": "Local Qwen 8B", "model": MODEL_ID, "api_key": None,
        "parameters": {**LocalLLMParameters().model_dump(), "temperature": 0.7, "seed": 42},
    }
    kept = await _call(api_client, "PUT", f"{LOCAL}/{saved.id}", body)
    assert (kept["id"], kept["name"], kept["has_api_key"]) == (saved.id, "Local Qwen 8B", True)
    assert (kept["parameters"]["temperature"], kept["parameters"]["seed"]) == (0.7, 42)
    assert await _saved_local_key(db_session) == LOCAL_KEY

    replaced = await _call(api_client, "PUT", f"{LOCAL}/{saved.id}", {**body, "api_key": "sk-rotated"})
    assert replaced == kept
    assert await _saved_local_key(db_session) == "sk-rotated"


@pytest.mark.asyncio
async def test_selecting_and_deleting_move_the_active_connection(api_client, db_session, machine):
    first = await seed_local_connection(db_session)
    second = await seed_local_connection(
        db_session, name="LM Studio", provider="openai_compatible", model="gemma-3-12b", api_key=None
    )
    assert (await _call(api_client, "GET", LOCAL))["active_profile_id"] == first.id

    selected = await _call(api_client, "PUT", f"{LOCAL}/active/select", {"profile_id": second.id})
    assert selected["active_profile_id"] == second.id
    assert [(p["id"], p["has_api_key"]) for p in selected["profiles"]] == [(first.id, True), (second.id, False)]

    remaining = await _call(api_client, "DELETE", f"{LOCAL}/{second.id}")
    assert (remaining["active_profile_id"], [p["id"] for p in remaining["profiles"]]) == (first.id, [first.id])
    assert await _call(api_client, "DELETE", f"{LOCAL}/{first.id}") == {
        "enabled": True, "active_profile_id": None, "profiles": [],
    }


@pytest.mark.asyncio
async def test_a_stored_choice_naming_no_saved_connection_serves_the_first_one(api_client, db_session, machine):
    first = await seed_local_connection(db_session)
    await seed_local_connection(db_session, name="Other", model="other-model")
    row = await db_session.get(AppSetting, "local_llm_profiles")
    await db_session.refresh(row)
    row.value = {**row.value, "active_profile_id": "deleted00000"}
    await db_session.commit()

    assert (await _call(api_client, "GET", LOCAL))["active_profile_id"] == first.id
    assert (await _call(api_client, "GET", f"{LOCAL}/server"))["profile_id"] == first.id


@pytest.mark.asyncio
async def test_switching_the_local_tier_off_keeps_every_connection(api_client, db_session, machine):
    await seed_local_connection(db_session)
    before = await _call(api_client, "GET", LOCAL)

    off = await _call(api_client, "PUT", f"{LOCAL}/enabled", {"enabled": False})
    assert off == {**before, "enabled": False}
    assert await _call(api_client, "GET", LOCAL) == off
    assert await _call(api_client, "PUT", f"{LOCAL}/enabled", {"enabled": True}) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("POST", LOCAL, {"name": "Remote", "model": "m", "base_url": "http://10.0.0.2:8000"}, 422),
        ("POST", LOCAL, {"name": "  ", "model": "m"}, 422),
        ("PUT", LOCAL + "/{saved}", {"name": "Hot", "model": "m", "parameters": {"temperature": 3}}, 422),
        ("PUT", LOCAL + "/nosuchprofile", {"name": "x", "model": "m"}, 404),
        ("PUT", LOCAL + "/active/select", {"profile_id": "nosuchprofile"}, 404),
        ("DELETE", LOCAL + "/nosuchprofile", None, 404),
    ],
    ids=["remote_address", "blank_name", "temperature_out_of_bounds", "update_missing", "select_missing", "delete_missing"],
)
async def test_a_refused_local_write_changes_nothing(api_client, db_session, machine, method, path, body, status):
    saved = await seed_local_connection(db_session)
    before = await _call(api_client, "GET", LOCAL)
    await _call(api_client, method, path.format(saved=saved.id), body, status=status)
    assert await _call(api_client, "GET", LOCAL) == before
    assert await _saved_local_key(db_session) == LOCAL_KEY


# --------------------------------------------------------------------------- #
# 3. The local server
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_with_no_connection_the_server_row_explains_itself_and_nothing_runs(api_client, machine):
    body = await _call(api_client, "GET", f"{LOCAL}/server")
    assert list(body) == _fields(contract.LocalServerStatus)
    assert body == {
        "enabled": True, "installed": True, "binary": OMLX_BINARY, "managed": False,
        "profile_id": None, "provider": None, "model": None, "base_url": None,
        "state": "not_configured", "reachable": False, "detail": "No local model connection is saved.",
    }
    refused = await _call(api_client, "POST", f"{LOCAL}/server", {"action": "start"}, status=409)
    assert said(refused) == {"detail": "No local model connection is saved."}
    assert (machine.local_server.requests, machine.omlx.runs) == ([], [])


@pytest.mark.asyncio
async def test_an_omlx_connection_is_managed_and_its_state_is_the_probes(api_client, db_session, machine):
    saved = await seed_local_connection(db_session)
    connection = {
        "enabled": True, "installed": True, "binary": OMLX_BINARY, "managed": True, "profile_id": saved.id,
        "provider": "omlx", "model": MODEL_ID, "base_url": "http://127.0.0.1:8000/v1",
    }
    up = await _call(api_client, "GET", f"{LOCAL}/server")
    assert up == {**connection, "state": "available", "reachable": True, "detail": ""}
    assert [(r.method, r.url.path) for r in machine.local_server.requests] == [("GET", "/v1/models")]

    machine.local_server.up = False
    down = await _call(api_client, "GET", f"{LOCAL}/server")
    assert down == {
        **connection, "state": "server_unreachable", "reachable": False,
        "detail": "Could not reach the local model: All connection attempts failed",
    }


@pytest.mark.asyncio
async def test_a_server_answering_without_the_saved_model_is_not_ready(api_client, db_session, machine):
    await seed_local_connection(db_session, model="gemma-3-12b")
    body = await _call(api_client, "GET", f"{LOCAL}/server")
    assert (body["state"], body["reachable"], body["detail"]) == (
        "model_not_ready", False, 'the server is not serving "gemma-3-12b"',
    )


@pytest.mark.asyncio
async def test_a_wedged_server_answers_unreachable_within_the_probe_bound(api_client, db_session, machine, monkeypatch):
    await seed_local_connection(db_session)
    monkeypatch.setattr(router, "_SERVER_PROBE_TIMEOUT", 0.05)
    machine.local_server.wedged = True
    body = await _call(api_client, "GET", f"{LOCAL}/server")
    assert (body["state"], body["reachable"]) == ("server_unreachable", False)
    assert body["detail"].startswith("Could not reach the server")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "binary", "reason"),
    [
        ("openai_compatible", OMLX_BINARY, "RoleBand can start and stop oMLX only"),
        ("omlx", None, "oMLX is not installed on this Mac"),
        ("openai_compatible", None, "RoleBand can start and stop oMLX only"),
    ],
    ids=["another_server", "omlx_not_installed", "another_server_without_omlx"],
)
async def test_a_server_the_app_does_not_manage_says_why_and_refuses_control(
    api_client, db_session, machine, provider, binary, reason
):
    await seed_local_connection(db_session, provider=provider)
    machine.omlx.binary = binary
    status = await _call(api_client, "GET", f"{LOCAL}/server")
    assert (status["installed"], status["binary"], status["managed"]) == (binary is not None, binary, False)
    assert status["detail"].startswith(reason)
    # Management is not reachability: the probe still ran and found the model.
    assert (status["state"], status["reachable"]) == ("available", True)

    refused = await _call(api_client, "POST", f"{LOCAL}/server", {"action": "start"}, status=409)
    assert said(refused) == {"detail": status["detail"]}
    assert machine.omlx.runs == []


@pytest.mark.asyncio
async def test_a_start_runs_the_cli_once_and_reports_the_fresh_probe(api_client, db_session, machine):
    await seed_local_connection(db_session)
    machine.local_server.up = False
    body = await _call(api_client, "POST", f"{LOCAL}/server", {"action": "start"})
    assert list(body) == _fields(contract.LocalServerControlResponse)
    assert machine.omlx.runs == [(OMLX_BINARY, "start")]
    assert (body["action"], body["action_ok"], body["action_detail"]) == (
        "start", True, "oMLX server started on http://127.0.0.1:8000",
    )
    assert (body["state"], body["reachable"]) == ("available", True)
    assert {k: v for k, v in body.items() if not k.startswith("action")} == await _call(
        api_client, "GET", f"{LOCAL}/server"
    )


@pytest.mark.asyncio
async def test_a_cli_that_exits_cleanly_is_not_taken_for_a_running_server(api_client, db_session, machine):
    await seed_local_connection(db_session)
    machine.local_server.up = False
    machine.omlx.brings_up = False
    body = await _call(api_client, "POST", f"{LOCAL}/server", {"action": "restart"})
    assert (body["action"], body["action_ok"]) == ("restart", True)
    assert (body["state"], body["reachable"]) == ("server_unreachable", False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "detail"),
    [("Error: no managed server is running", "Error: no managed server is running"), ("", "oMLX stop failed (exit 1).")],
    ids=["cli_explains", "cli_silent"],
)
async def test_a_failed_stop_reports_the_cli_and_the_server_still_answering(
    api_client, db_session, machine, output, detail
):
    await seed_local_connection(db_session)
    machine.omlx.exit_code, machine.omlx.output = 1, output
    body = await _call(api_client, "POST", f"{LOCAL}/server", {"action": "stop"})
    assert (body["action"], body["action_ok"], body["action_detail"]) == ("stop", False, detail)
    assert (body["state"], body["reachable"]) == ("available", True)


@pytest.mark.asyncio
async def test_an_unknown_server_action_is_refused_before_anything_runs(api_client, db_session, machine):
    await seed_local_connection(db_session)
    await _call(api_client, "POST", f"{LOCAL}/server", {"action": "reboot"}, status=422)
    assert (machine.omlx.runs, machine.local_server.requests) == ([], [])


# --------------------------------------------------------------------------- #
# 4. The local test
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_saved_connection_answers_with_the_servers_own_metrics(api_client, db_session, machine):
    saved = await seed_local_connection(db_session)
    body = await _call(api_client, "POST", f"{LOCAL}/{saved.id}/test", {})
    assert list(body) == _fields(contract.LocalModelTestResult)
    assert list(body["metrics"]) == _fields(LocalModelMetrics)
    assert body == {
        "ok": True,
        "profile_id": saved.id,
        "provider": "omlx",
        "model": MODEL_ID,
        "response": LOCAL_REPLY,
        "finish_reason": "stop",
        "truncated": False,
        "metrics": METRICS,
    }

    listing, chat = machine.local_server.requests
    assert (listing.url.path, chat.url.path) == ("/v1/models", "/v1/chat/completions")
    assert chat.headers["authorization"] == f"Bearer {LOCAL_KEY}"
    assert json.loads(chat.content)["messages"][1]["content"] == f"Reply exactly: {LOCAL_REPLY}"
    assert await _test_log(db_session) == [("omlx", "ok", None, 9412, 1830, 212, MODEL_ID)]


@pytest.mark.asyncio
async def test_a_reply_cut_off_at_max_tokens_is_not_ok(api_client, db_session, machine):
    saved = await seed_local_connection(db_session)
    machine.local_server.finish_reason = "length"
    body = await _call(api_client, "POST", f"{LOCAL}/{saved.id}/test", {"prompt": "  Count to a million.  "})
    assert (body["ok"], body["truncated"], body["finish_reason"]) == (False, True, "length")
    assert body["metrics"] == {**METRICS, "finish_reason": "length"}
    assert json.loads(machine.local_server.requests[-1].content)["messages"][1]["content"] == "Count to a million."
    assert await _test_log(db_session) == [("omlx", "invalid", "truncated", 9412, 1830, 212, MODEL_ID)]


@pytest.mark.asyncio
async def test_an_unsaved_draft_is_tested_with_the_saved_key_and_never_saved(api_client, db_session, machine):
    saved = await seed_local_connection(db_session)
    before = await _call(api_client, "GET", LOCAL)
    draft = {
        "name": "Draft", "provider": "omlx", "model": MODEL_ID, "api_key": None,
        "parameters": {**LocalLLMParameters().model_dump(), "temperature": 0.9, "enable_thinking": False},
    }
    body = await _call(api_client, "POST", f"{LOCAL}/{saved.id}/test", {"profile": draft})
    assert (body["ok"], body["profile_id"]) == (True, saved.id)

    chat = machine.local_server.requests[-1]
    sent = json.loads(chat.content)
    assert chat.headers["authorization"] == f"Bearer {LOCAL_KEY}"
    assert (sent["temperature"], sent["chat_template_kwargs"], "thinking_budget" in sent) == (
        0.9, {"enable_thinking": False}, False,
    )
    assert await _call(api_client, "GET", LOCAL) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "server_up", "status", "detail", "failure_class"),
    [
        ("gemma-3-12b", True, 400, f'Model "gemma-3-12b" is not available. Server models: {MODEL_ID}.', "model_not_found"),
        (MODEL_ID, False, 502, "Could not reach the local model: All connection attempts failed", "connection"),
    ],
    ids=["model_not_served", "server_down"],
)
async def test_a_failed_local_test_answers_the_clients_error_and_is_logged(
    api_client, db_session, machine, model, server_up, status, detail, failure_class
):
    saved = await seed_local_connection(db_session, model=model)
    machine.local_server.up = server_up
    refused = await _call(api_client, "POST", f"{LOCAL}/{saved.id}/test", {}, status=status)
    assert said(refused) == {"detail": detail}
    assert await _test_log(db_session) == [("omlx", "invalid", failure_class, None, None, None, model)]


@pytest.mark.asyncio
async def test_a_refused_local_test_reaches_no_server_and_logs_nothing(api_client, db_session, machine):
    saved = await seed_local_connection(db_session)
    missing = await _call(api_client, "POST", f"{LOCAL}/nosuchprofile/test", {}, status=404)
    assert said(missing) == {"detail": "local model profile not found"}
    await _call(api_client, "POST", f"{LOCAL}/{saved.id}/test", {"prompt": "x" * 1001}, status=422)
    assert machine.local_server.requests == []
    assert await _test_log(db_session) == []


# --------------------------------------------------------------------------- #
# 5. Cloud connections
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_cloud_connection_is_saved_off_with_its_key_write_only(api_client, db_session, machine):
    assert await _call(api_client, "GET", CLOUD) == {"profiles": []}

    response = await api_client.post(CLOUD, json={
        "name": "OpenAI", "provider": "openai", "base_url": "https://api.openai.com/v1/",
        "model": "gpt-5-mini", "api_key": CLOUD_KEY,
    })
    assert response.status_code == 201, response.text
    created = response.json()
    assert list(created) == _fields(contract.CloudModelProfile)
    assert created == {
        "id": created["id"], "name": "OpenAI", "provider": "openai", "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini", "enabled": False, "has_api_key": True,
    }

    listed = await _call(api_client, "GET", CLOUD)
    assert list(listed) == _fields(contract.CloudModelState)
    assert listed == {"profiles": [created]}
    assert CLOUD_KEY not in response.text + json.dumps(listed)
    db_session.expire_all()
    assert (await get_cloud_state(db_session)).profiles[0].api_key == CLOUD_KEY
    assert machine.cloud.requests == []  # saving is not testing


@pytest.mark.asyncio
async def test_a_cloud_update_keeps_the_key_and_a_delete_serves_what_remains(api_client, db_session, machine):
    openai = await seed_cloud_connection(db_session)
    anthropic = await seed_cloud_connection(
        db_session, name="Anthropic", provider="anthropic", base_url="https://api.anthropic.com",
        model="claude-haiku-4-5", enabled=False, api_key=None,
    )
    updated = await _call(api_client, "PUT", f"{CLOUD}/{openai.id}", OPENAI_BODY)
    assert updated == {
        "id": openai.id, "name": "OpenAI API", "provider": "openai", "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini", "enabled": False, "has_api_key": True,
    }
    listed = await _call(api_client, "GET", CLOUD)
    assert [(p["id"], p["base_url"], p["has_api_key"]) for p in listed["profiles"]] == [
        (openai.id, "https://api.openai.com/v1", True),
        (anthropic.id, "https://api.anthropic.com/v1", False),
    ]
    assert await _call(api_client, "DELETE", f"{CLOUD}/{anthropic.id}") == {"profiles": [updated]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("POST", CLOUD, {**OPENAI_BODY, "base_url": "http://api.openai.com/v1"}, 422),
        ("POST", CLOUD, {**OPENAI_BODY, "base_url": "https://192.168.1.20/v1"}, 422),
        ("POST", CLOUD, {**OPENAI_BODY, "provider": "mistral"}, 422),
        ("PUT", CLOUD + "/nosuchprofile", OPENAI_BODY, 404),
        ("DELETE", CLOUD + "/nosuchprofile", None, 404),
    ],
    ids=["plain_http", "private_address", "unknown_provider", "update_missing", "delete_missing"],
)
async def test_a_refused_cloud_write_changes_nothing(api_client, db_session, machine, method, path, body, status):
    await seed_cloud_connection(db_session)
    before = await _call(api_client, "GET", CLOUD)
    await _call(api_client, method, path, body, status=status)
    assert await _call(api_client, "GET", CLOUD) == before


@pytest.mark.asyncio
async def test_an_openai_family_test_lists_models_and_sends_no_generation(api_client, db_session, machine):
    saved = await seed_cloud_connection(db_session)
    body = await _call(api_client, "POST", f"{CLOUD}/{saved.id}/test")
    assert list(body) == _fields(contract.CloudModelTestResult)
    assert body == {
        "ok": True, "profile_id": saved.id, "provider": "openai", "model": "gpt-5-mini", "latency_ms": 9412,
    }
    [request] = machine.cloud.requests
    assert (request.method, str(request.url), request.headers["authorization"]) == (
        "GET", "https://api.openai.com/v1/models", f"Bearer {CLOUD_KEY}",
    )


@pytest.mark.asyncio
async def test_an_anthropic_test_sends_one_token_and_says_it_may_be_billed(api_client, db_session, machine):
    saved = await seed_cloud_connection(
        db_session, name="Anthropic", provider="anthropic", base_url="https://api.anthropic.com",
        model="claude-haiku-4-5",
    )
    body = await _call(api_client, "POST", f"{CLOUD}/{saved.id}/test")
    assert (body["provider"], body["model"]) == ("anthropic", "claude-haiku-4-5")
    [request] = machine.cloud.requests
    assert (request.method, str(request.url), request.headers["x-api-key"]) == (
        "POST", "https://api.anthropic.com/v1/messages", CLOUD_KEY,
    )
    assert json.loads(request.content) == {
        "model": "claude-haiku-4-5", "max_tokens": 1, "messages": [{"role": "user", "content": "Reply OK"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "detail", "reached"),
    [
        ("no_key", "API key is not configured", 0),
        ("model_not_listed", "Connected, but model 'gpt-5-mini' was not listed", 1),
        ("key_refused", "Incorrect API key provided.", 1),
        ("rate_limited", "Rate limit reached for requests", 1),
        ("unreachable", "All connection attempts failed", 1),
    ],
)
async def test_a_failed_cloud_test_is_a_502_with_the_providers_reason(
    api_client, db_session, machine, scenario, detail, reached
):
    saved = await seed_cloud_connection(db_session, api_key=None if scenario == "no_key" else CLOUD_KEY)
    if scenario == "model_not_listed":
        machine.cloud.models = ["gpt-5"]
    elif scenario == "key_refused":
        machine.cloud.key = "sk-rotated"
    elif scenario == "rate_limited":
        machine.cloud.status = 429
    elif scenario == "unreachable":
        machine.cloud.reachable = False
    refused = await _call(api_client, "POST", f"{CLOUD}/{saved.id}/test", status=502)
    assert said(refused) == {"detail": detail}
    assert len(machine.cloud.requests) == reached


@pytest.mark.asyncio
async def test_a_cloud_test_of_no_saved_connection_reaches_no_provider(api_client, machine):
    missing = await _call(api_client, "POST", f"{CLOUD}/nosuchprofile/test", status=404)
    assert said(missing) == {"detail": "cloud model profile not found"}
    assert machine.cloud.requests == []


# --------------------------------------------------------------------------- #
# 6. Drift
# --------------------------------------------------------------------------- #


def _serving_the_key(model):
    real = model.public

    def public(self) -> dict:
        return {**real(self), "api_key": self.api_key}

    return public


def _dropping(real, key):
    async def drifted(*args, **kwargs):
        return {k: v for k, v in (await real(*args, **kwargs)).items() if k != key}

    return drifted


def _adding(real):
    async def drifted(*args, **kwargs):
        return {**(await real(*args, **kwargs)), "unmodelled": True}

    return drifted


def _renaming_the_action(real):
    async def drifted(action):
        result = await real(action)
        return omlx_server.ControlResult(result.ok, "reload", result.detail)

    return drifted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", LOCAL, None),
        ("POST", LOCAL, {"name": "Second", "model": MODEL_ID, "api_key": LOCAL_KEY}),
        ("GET", CLOUD, None),
        ("PUT", CLOUD + "/{cloud}", OPENAI_BODY),
    ],
    ids=["local_state", "local_created", "cloud_state", "cloud_updated"],
)
async def test_a_connection_that_serves_its_key_fails_the_response(
    api_client, db_session, machine, monkeypatch, method, path, body
):
    await seed_local_connection(db_session)
    cloud = await seed_cloud_connection(db_session)
    monkeypatch.setattr(LocalLLMProfile, "public", _serving_the_key(LocalLLMProfile))
    monkeypatch.setattr(CloudLLMProfile, "public", _serving_the_key(CloudLLMProfile))
    with pytest.raises(ResponseValidationError):
        await api_client.request(method, path.format(cloud=cloud.id), json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner", "name", "drift", "method", "path", "body"),
    [
        (router, "_local_server_status", lambda real: _dropping(real, "detail"), "GET", LOCAL + "/server", None),
        (router, "control_omlx_server", _renaming_the_action, "POST", LOCAL + "/server", {"action": "start"}),
        (LocalLLMClient, "test_connection", _adding, "POST", LOCAL + "/{local}/test", {}),
        (router, "test_cloud_llm_connection", lambda real: _dropping(real, "latency_ms"), "POST", CLOUD + "/{cloud}/test", None),
    ],
    ids=["status_detail_dropped", "control_action_renamed", "local_test_key_added", "cloud_latency_dropped"],
)
async def test_a_builder_that_drifts_fails_the_response(
    api_client, db_session, machine, monkeypatch, owner, name, drift, method, path, body
):
    local = await seed_local_connection(db_session)
    cloud = await seed_cloud_connection(db_session)
    monkeypatch.setattr(owner, name, drift(getattr(owner, name)))
    with pytest.raises(ResponseValidationError):
        await api_client.request(method, path.format(local=local.id, cloud=cloud.id), json=body)


@pytest.mark.asyncio
async def test_a_cloud_test_with_egress_off_sends_nothing(api_client, db_session, machine):
    """The test sends the API key to the provider, which is this machine
    contacting a cloud service. A person who turned cloud AI off has refused
    exactly that, and saving a connection is not consent to reach it.
    Fail-first: the key goes out and the provider answers 200."""
    saved = await seed_cloud_connection(db_session, egress=False)
    refused = await _call(api_client, "POST", f"{CLOUD}/{saved.id}/test", status=409)
    assert code_of(refused) == "ai-egress-off"
    assert said(refused) == {"detail": "cloud AI is turned off, so no request was sent"}
    assert machine.cloud.requests == [], "a request left the machine with egress off"


@pytest.mark.asyncio
async def test_turning_egress_back_on_restores_the_test(api_client, db_session, machine):
    """The refusal is a switch, not a permanent state."""
    saved = await seed_cloud_connection(db_session, egress=False)
    await _call(api_client, "POST", f"{CLOUD}/{saved.id}/test", status=409)
    await set_ai_egress_enabled(db_session, True)
    await db_session.commit()
    body = await _call(api_client, "POST", f"{CLOUD}/{saved.id}/test")
    assert body["ok"] is True
    assert len(machine.cloud.requests) == 1
