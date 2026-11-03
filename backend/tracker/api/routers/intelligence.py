"""Intelligence settings: Apple FM toggle, local/cloud model profiles, agents.

Every route declares its response in `tracker/api/schemas/intelligence.py`: the
settings, matching, self-test, fit and agent routes, and the local and cloud
model connection routes."""

from __future__ import annotations

import asyncio
import logging
import shlex
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.agents.config import AgentAccessConfig, get_agent_access, set_agent_access
from tracker.api.deps import OffBoardDep, SessionDep, end_read
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.intelligence import (
    AgentAccessResponse,
    CloudModelProfile,
    CloudModelState,
    CloudModelTestResult,
    IntelligenceFitBandResponse,
    IntelligenceFitResponse,
    IntelligenceStateResponse,
    IntelligenceTestResponse,
    LocalModelProfile,
    LocalModelState,
    LocalModelTestResult,
    LocalServerControlResponse,
    LocalServerStatus,
    MatchingStopResponse,
)
from tracker.api.schemas.text_class import text
from tracker.api.serializers.jobs import serialize_job
from tracker.cloud_llm.client import CloudLLMError
from tracker.cloud_llm.client import test_connection as test_cloud_llm_connection
from tracker.cloud_llm.models import CloudLLMProfileInput
from tracker.config import get_settings
from tracker.db.models import Job
from tracker.db.queries.jobs import apply_job_filters, row_context
from tracker.intelligence.prompts import PROMPT_VERSION
from tracker.intelligence.providers.local import LocalLLMProvider
from tracker.intelligence.registry import build_provider
from tracker.intelligence_runtime._profile_keys import ProfilesUnreadable
from tracker.intelligence_runtime.cloud_profiles import (
    create_profile as create_cloud_llm_profile,
)
from tracker.intelligence_runtime.cloud_profiles import (
    delete_profile as delete_cloud_llm_profile,
)
from tracker.intelligence_runtime.cloud_profiles import (
    get_profile as get_cloud_llm_profile,
)
from tracker.intelligence_runtime.cloud_profiles import (
    get_state as get_cloud_llm_state,
)
from tracker.intelligence_runtime.cloud_profiles import (
    update_profile as update_cloud_llm_profile,
)
from tracker.intelligence_runtime.local_profiles import (
    create_profile as create_local_llm_profile,
)
from tracker.intelligence_runtime.local_profiles import (
    delete_profile as delete_local_llm_profile,
)
from tracker.intelligence_runtime.local_profiles import (
    get_profile as get_local_llm_profile,
)
from tracker.intelligence_runtime.local_profiles import (
    get_state as get_local_llm_state,
)
from tracker.intelligence_runtime.local_profiles import (
    select_profile as select_local_llm_profile,
)
from tracker.intelligence_runtime.local_profiles import (
    set_enabled as set_local_llm_enabled,
)
from tracker.intelligence_runtime.local_profiles import (
    update_profile as update_local_llm_profile,
)
from tracker.intelligence_runtime.routing import routing_state
from tracker.intelligence_runtime.selftest import run_self_test
from tracker.intelligence_runtime.telemetry import log_ai_task
from tracker.local_llm.client import LocalLLMClient, LocalLLMError
from tracker.local_llm.models import LocalLLMProfile, LocalLLMProfileInput
from tracker.local_llm.server import binary_path as omlx_binary_path
from tracker.local_llm.server import control as control_omlx_server
from tracker.platform.paths import PACKAGED, REPO_ROOT, backend_dir
from tracker.search.fit import (
    BAND_KEYS,
    FIT_BIN_WIDTH,
    band_stmt,
    fit_bands,
    histogram_stmt,
)
from tracker.semantic import matching
from tracker.semantic.intent import build_intent_vector
from tracker.semantic.matching import matching_state
from tracker.settings_store import (
    get_ai_egress_enabled,
    get_apple_fm_enabled,
    get_intent_embedding,
    get_persona_profile,
    set_ai_egress_enabled,
    set_apple_fm_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------------------------------------------------------------------- #
# Experimental: the Apple Foundation Models integration.
#
# Nothing the app does automatically depends on this. Salary extraction is
# deterministic and reaches no provider; the routing ladder below is local/cloud
# only. What survives here is the switch plus a self-test, so the integration
# stays exercisable for whenever Apple's on-device model grows a capability
# worth routing to.
# --------------------------------------------------------------------------- #


class IntelligencePayload(BaseModel):
    enabled: bool


class EgressPayload(BaseModel):
    enabled: bool


class IntelligenceTestPayload(BaseModel):
    text: str | None = Field(None, json_schema_extra=text("content"))


class MatchingTierPayload(BaseModel):
    """Which artifact of the bundled embedding model to run.

    `None` restores auto-detection. The literal is the validator on purpose: an
    unknown tier must be a 422 at the edge, never a KeyError deep inside
    `spec.tiers` after the choice has already been committed.
    """

    tier: Literal["fp32", "int8"] | None = None


@dataclass(frozen=True)
class _Processes:
    """The three re-embed facts the matching policy needs, injected not imported.

    `tracker.api.job_requests` is L6 and `semantic.matching` is L4, so the
    policy cannot reach up for these — which is also what lets it be tested with
    a fake spawn. Bound to the request's session, and looked up at CALL time:
    a test patches `tracker.api.job_requests.ring_reembed` or `stop_reembed`.
    """

    running: Callable[[], Awaitable[bool]]
    spawn: Callable[[], Awaitable[bool]]
    terminate: Callable[[], Awaitable[tuple[str, int | None]]]


def _processes(session: AsyncSession) -> _Processes:
    from tracker.api import job_requests

    return _Processes(
        running=lambda: job_requests.pending(session, job_requests.REEMBED),
        spawn=lambda: job_requests.ring_reembed(session, requested_by="tier_switch"),
        terminate=lambda: job_requests.stop_reembed(session),
    )


async def _reembed_in_progress(session: AsyncSession) -> bool:
    """`matching.reembed_in_progress` with our own request's state supplied."""
    return await matching.reembed_in_progress(session, requested=await _processes(session).running())


async def _intelligence_state(session: AsyncSession) -> dict:
    """Experimental-integration toggle + what the device can actually do (they
    are independent: the user can have it on while the Mac/SDK still can't run
    a model).

    `enabled` / `availability` describe the EXPERIMENTAL Apple integration only.
    Salary extraction is deliberately absent from this payload — it is
    deterministic, so there is nothing for a user to configure and no host it
    can fail on."""
    enabled = await get_apple_fm_enabled(session)
    provider = build_provider(enabled)
    avail = await provider.availability()
    return {
        "matching": await matching_state(
            session, reembed_running=await _reembed_in_progress(session)
        ),
        "enabled": enabled,
        "provider": provider.name,
        "availability": {
            "state": avail.state.value,
            "ok": avail.ok,
            "detail": avail.detail,
        },
        "model_id": get_settings().intelligence_model_id,
        "prompt_version": PROMPT_VERSION,
        "routing": await routing_state(session),
    }


@contextmanager
def _profiles_writable() -> Iterator[None]:
    """A write to saved model connections that no longer validate is refused:
    built on the empty list they read as, it would delete them (`ProfilesUnreadable`)."""
    try:
        yield
    except ProfilesUnreadable as exc:
        raise api_error(
            409, ErrorCode.MODEL_PROFILES_UNREADABLE,
            "saved model connections no longer validate; nothing was changed",
        ) from exc


@router.get("/api/intelligence", response_model=IntelligenceStateResponse)
async def get_intelligence_ep(session: SessionDep) -> dict:
    return await _intelligence_state(session)


@router.put("/api/intelligence", response_model=IntelligenceStateResponse)
async def put_intelligence_ep(payload: IntelligencePayload, session: SessionDep) -> dict:
    await set_apple_fm_enabled(session, payload.enabled)
    await session.commit()
    return await _intelligence_state(session)


@router.put("/api/intelligence/egress", response_model=IntelligenceStateResponse)
async def put_ai_egress_ep(payload: EgressPayload, session: SessionDep) -> dict:
    """Allow (or stop) job text leaving this Mac.

    Its own endpoint rather than a field on the Apple FM toggle: this is the one
    consent that changes what the shipped privacy copy can truthfully say, so it
    must be impossible to flip as a side effect of saving something else.
    """
    await set_ai_egress_enabled(session, payload.enabled)
    await session.commit()
    return await _intelligence_state(session)


@router.put("/api/intelligence/matching/tier", response_model=IntelligenceStateResponse)
async def put_matching_tier_ep(payload: MatchingTierPayload, session: SessionDep) -> dict:
    """Choose which artifact of the bundled model this Mac runs, or restore auto.

    Its own endpoint, and a write that costs something: switching re-embeds the
    entire corpus, because fp32 and int8 are the same model in *nearly* the
    same space, and a corpus half in each ranks against a seam.
    So the switch is one transaction plus one detached job, in this order:
    record the choice (shared, so every checkout follows), push it to this
    checkout's decision file, drop the loaded encoder, then spawn the re-embed.

    A no-op switch does none of that. Re-selecting the active tier must not
    cost a full re-embed for zero change.
    """
    outcome = await matching.switch_tier(
        session,
        payload.tier,
        reembed_running=await _reembed_in_progress(session),
        spawn=_processes(session).spawn,
    )
    if outcome is matching.TierSwitch.BUSY:
        raise api_error(409, ErrorCode.SWITCH_RUNNING, "a re-embed is already running; wait for it to finish before switching again")
    if outcome is matching.TierSwitch.SPAWN_FAILED:
        raise api_error(503, ErrorCode.SWITCH_NOT_STARTED, "the tier was changed but the re-embed could not be started; "
                "it will complete on the next scheduled run")
    return await _intelligence_state(session)


@router.post("/api/intelligence/test", response_model=IntelligenceTestResponse)
async def test_intelligence_ep(payload: IntelligenceTestPayload, session: SessionDep) -> dict:
    """Run one extraction through the experimental Apple provider and report
    what it returned. Dry run: never writes to `jobs`, and never influences the
    disclosed bands the deterministic pass produces."""
    # The EXPERIMENTAL provider specifically, not the routing ladder: this
    # button exists to answer "can Apple's on-device model still do this?", and
    # routing it through local/cloud would silently answer a different question.
    provider = build_provider(await get_apple_fm_enabled(session))
    await end_read(session)
    result = await run_self_test(session, provider, payload.text)
    await session.commit()  # persists only the AiTaskLog row
    return result


# --------------------------------------------------------------------------- #
# Local OpenAI-compatible models — named profiles + real connection test.
# --------------------------------------------------------------------------- #


class LocalLLMSelectPayload(BaseModel):
    profile_id: str


class LocalLLMTestPayload(BaseModel):
    prompt: str | None = Field(default=None, max_length=1000)
    # Optional unsaved form state. Test it in memory; never persist it as a
    # side effect of a probe. A null key retains the saved write-only secret.
    profile: LocalLLMProfileInput | None = None


# A status probe must never hang the Settings screen. A stopped server refuses
# the loopback connection instantly; this bound only matters for the rarer
# "listening but wedged" case, where the profile's own (up to 600s) generation
# timeout would otherwise apply.
_SERVER_PROBE_TIMEOUT = 6.0


async def _local_server_status(session: AsyncSession) -> dict:
    """What the Settings screen needs to render the local-server row.

    Three independent facts, deliberately not collapsed into one flag:
    `installed` (is the oMLX CLI on this Mac), `managed` (may WE start/stop
    this particular connection), and `reachable` (is it answering right now).
    A user without oMLX gets installed=False and a usable explanation instead
    of a control that fails when pressed.
    """
    state = await get_local_llm_state(session)
    public = state.public()
    profile = next(
        (item for item in state.profiles if item.id == public["active_profile_id"]), None
    )
    binary = omlx_binary_path()
    is_omlx = profile is not None and profile.provider == "omlx"
    status = {
        "enabled": state.enabled,
        "installed": binary is not None,
        "binary": binary,
        "managed": bool(binary is not None and is_omlx),
        "profile_id": profile.id if profile is not None else None,
        "provider": profile.provider if profile is not None else None,
        "model": profile.model if profile is not None else None,
        "base_url": profile.base_url if profile is not None else None,
        "state": "not_configured",
        "reachable": False,
        "detail": "",
    }

    if profile is None:
        status["detail"] = "No local model connection is saved."
        return status
    if not is_omlx:
        status["detail"] = (
            "RoleBand can start and stop oMLX only; this connection points at "
            "another server, so run it yourself."
        )
    elif binary is None:
        status["detail"] = (
            "oMLX is not installed on this Mac. RoleBand works without it — "
            "turn local models off, or install oMLX to run one here."
        )

    await end_read(session)
    try:
        availability = await asyncio.wait_for(
            LocalLLMProvider(profile).availability(), timeout=_SERVER_PROBE_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - a status probe must never 500
        status["state"] = "server_unreachable"
        status["detail"] = status["detail"] or f"Could not reach the server: {exc}"
        return status

    status["state"] = availability.state.value
    status["reachable"] = availability.ok
    if availability.detail and not status["detail"]:
        status["detail"] = availability.detail
    return status


class LocalLLMEnabledPayload(BaseModel):
    enabled: bool


class LocalServerActionPayload(BaseModel):
    action: Literal["start", "stop", "restart"]


@router.get("/api/intelligence/local-models", response_model=LocalModelState)
async def list_local_llm_profiles(session: SessionDep) -> dict:
    return (await get_local_llm_state(session)).public()


# NOTE: the three fixed-path routes below MUST stay above
# `PUT/POST /api/intelligence/local-models/{profile_id}`. FastAPI matches in
# declaration order and `{profile_id}` is a single unconstrained segment, so a
# later "enabled" route would be swallowed by it and 404 as a missing profile.


@router.put("/api/intelligence/local-models/enabled", response_model=LocalModelState)
async def put_local_llm_enabled(
    payload: LocalLLMEnabledPayload, session: SessionDep
) -> dict:
    """Turn the local tier on or off without touching any saved profile."""
    with _profiles_writable():
        await set_local_llm_enabled(session, payload.enabled)
    await session.commit()
    return (await get_local_llm_state(session)).public()


@router.get("/api/intelligence/local-models/server", response_model=LocalServerStatus)
async def get_local_llm_server(session: SessionDep) -> dict:
    return await _local_server_status(session)


@router.post("/api/intelligence/local-models/server", response_model=LocalServerControlResponse)
async def post_local_llm_server(
    payload: LocalServerActionPayload, session: SessionDep
) -> dict:
    """Start/stop the oMLX managed server, then re-probe and report the truth.

    A CLI that exited 0 is not evidence the server answers, so the response
    carries the fresh probe rather than the command's own optimism.
    """
    status = await _local_server_status(session)
    if not status["managed"]:
        raise api_error(409, ErrorCode.SERVER_NOT_MANAGED, status["detail"] or "This server is not one RoleBand can start or stop.")
    result = await control_omlx_server(payload.action)
    return {
        **(await _local_server_status(session)),
        "action": result.action,
        "action_ok": result.ok,
        "action_detail": result.detail,
    }


@router.post("/api/intelligence/local-models", status_code=201, response_model=LocalModelProfile)
async def add_local_llm_profile(payload: LocalLLMProfileInput, session: SessionDep) -> dict:
    with _profiles_writable():
        profile = await create_local_llm_profile(session, payload)
    await session.commit()
    return profile.public()


@router.put("/api/intelligence/local-models/{profile_id}", response_model=LocalModelProfile)
async def put_local_llm_profile(
    profile_id: str, payload: LocalLLMProfileInput, session: SessionDep
) -> dict:
    with _profiles_writable():
        profile = await update_local_llm_profile(session, profile_id, payload)
    if profile is None:
        raise api_error(404, ErrorCode.LOCAL_MODEL_NOT_FOUND, "local model profile not found")
    await session.commit()
    return profile.public()


@router.delete("/api/intelligence/local-models/{profile_id}", response_model=LocalModelState)
async def remove_local_llm_profile(profile_id: str, session: SessionDep) -> dict:
    with _profiles_writable():
        deleted = await delete_local_llm_profile(session, profile_id)
    if not deleted:
        raise api_error(404, ErrorCode.LOCAL_MODEL_NOT_FOUND, "local model profile not found")
    await session.commit()
    return (await get_local_llm_state(session)).public()


@router.put("/api/intelligence/local-models/active/select", response_model=LocalModelState)
async def put_active_local_llm_profile(
    payload: LocalLLMSelectPayload, session: SessionDep
) -> dict:
    with _profiles_writable():
        profile = await select_local_llm_profile(session, payload.profile_id)
    if profile is None:
        raise api_error(404, ErrorCode.LOCAL_MODEL_NOT_FOUND, "local model profile not found")
    await session.commit()
    return (await get_local_llm_state(session)).public()


@router.post(
    "/api/intelligence/local-models/{profile_id}/test", response_model=LocalModelTestResult
)
async def test_local_llm_profile(
    profile_id: str, payload: LocalLLMTestPayload, session: SessionDep
) -> dict:
    profile = await get_local_llm_profile(session, profile_id)
    if profile is None:
        raise api_error(404, ErrorCode.LOCAL_MODEL_NOT_FOUND, "local model profile not found")
    if payload.profile is not None:
        values = payload.profile.model_dump()
        if payload.profile.api_key is None:
            values["api_key"] = profile.api_key
        profile = LocalLLMProfile(id=profile.id, **values)
    await end_read(session)
    try:
        result = await LocalLLMClient(profile).test_connection(payload.prompt)
    except LocalLLMError as exc:
        await log_ai_task(
            session,
            task_type="local_llm_test",
            provider=profile.provider,
            availability_state="unavailable",
            validation_result="invalid",
            failure_class=exc.failure_class,
            model_id=profile.model[:64],
        )
        await session.commit()
        raise api_error(exc.status_code, ErrorCode.MODEL_UNREACHABLE, str(exc)) from exc
    metrics = result["metrics"]
    await log_ai_task(
        session,
        task_type="local_llm_test",
        provider=profile.provider,
        availability_state="available",
        validation_result="ok" if result["ok"] else "invalid",
        failure_class="truncated" if result["truncated"] else None,
        latency_ms=metrics.get("wall_time_ms"),
        input_tokens=metrics.get("prompt_tokens"),
        output_tokens=metrics.get("completion_tokens"),
        model_id=profile.model[:64],
        meta={"finish_reason": result["finish_reason"]},
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# External agents — local STDIO MCP access and independent write permission.
# --------------------------------------------------------------------------- #


def _agent_connection_state(config: AgentAccessConfig) -> dict:
    python = sys.executable if PACKAGED else str(REPO_ROOT / "backend" / ".venv" / "bin" / "python")
    directory = str(backend_dir(REPO_ROOT))
    args = ["-I", str(backend_dir(REPO_ROOT) / "packaged.py"), "mcp.server"] if PACKAGED else ["-m", "tracker.mcp.server"]
    return {
        **config.model_dump(),
        "transport": "stdio",
        "command": str(python),
        "args": args,
        "cwd": directory,
        "tools": [
            {"name": "get_server_status", "access": "status"},
            {"name": "get_radar_summary", "access": "read"},
            {"name": "search_opportunities", "access": "read"},
            {"name": "get_opportunity", "access": "read"},
            # The same payload as `GET /api/jobs/{id}/history`.
            {"name": "listing_history", "access": "read"},
            {"name": "get_pursuits", "access": "read"},
            {"name": "save_opportunity", "access": "write"},
            {"name": "update_pursuit", "access": "write"},
            # Recipe authoring: three reads, one confirmed draft write.
            {"name": "get_recipe_contract", "access": "read"},
            {"name": "inspect_source", "access": "read"},
            {"name": "validate_recipe", "access": "read"},
            {"name": "save_recipe_draft", "access": "write"},
        ],
        "codex_command": shlex.join(
            ["codex", "mcp", "add", "roleband", "--", str(python), *args]
        ),
        "claude_json": {
            "mcpServers": {
                "roleband": {"command": str(python), "args": args, "cwd": directory}
            }
        },
    }


@router.get("/api/intelligence/agents", response_model=AgentAccessResponse)
async def get_agent_access_ep(session: SessionDep) -> dict:
    return _agent_connection_state(await get_agent_access(session))


@router.put("/api/intelligence/agents", response_model=AgentAccessResponse)
async def put_agent_access_ep(payload: AgentAccessConfig, session: SessionDep) -> dict:
    saved = await set_agent_access(session, payload)
    await session.commit()
    return _agent_connection_state(saved)


# --------------------------------------------------------------------------- #
# Direct cloud models — BYOK only; separate from subscription-backed MCP clients.
# --------------------------------------------------------------------------- #


@router.get("/api/intelligence/cloud-models", response_model=CloudModelState)
async def list_cloud_llm_profiles(session: SessionDep) -> dict:
    return (await get_cloud_llm_state(session)).public()


@router.post("/api/intelligence/cloud-models", status_code=201, response_model=CloudModelProfile)
async def add_cloud_llm_profile(payload: CloudLLMProfileInput, session: SessionDep) -> dict:
    with _profiles_writable():
        profile = await create_cloud_llm_profile(session, payload)
    await session.commit()
    return profile.public()


@router.put("/api/intelligence/cloud-models/{profile_id}", response_model=CloudModelProfile)
async def put_cloud_llm_profile(
    profile_id: str, payload: CloudLLMProfileInput, session: SessionDep
) -> dict:
    with _profiles_writable():
        profile = await update_cloud_llm_profile(session, profile_id, payload)
    if profile is None:
        raise api_error(404, ErrorCode.CLOUD_MODEL_NOT_FOUND, "cloud model profile not found")
    await session.commit()
    return profile.public()


@router.delete("/api/intelligence/cloud-models/{profile_id}", response_model=CloudModelState)
async def remove_cloud_llm_profile(profile_id: str, session: SessionDep) -> dict:
    with _profiles_writable():
        deleted = await delete_cloud_llm_profile(session, profile_id)
    if not deleted:
        raise api_error(404, ErrorCode.CLOUD_MODEL_NOT_FOUND, "cloud model profile not found")
    await session.commit()
    return (await get_cloud_llm_state(session)).public()


@router.post(
    "/api/intelligence/cloud-models/{profile_id}/test", response_model=CloudModelTestResult
)
async def test_cloud_llm_profile(profile_id: str, session: SessionDep) -> dict:
    profile = await get_cloud_llm_profile(session, profile_id)
    if profile is None:
        raise api_error(404, ErrorCode.CLOUD_MODEL_NOT_FOUND, "cloud model profile not found")
    # Checked before the profile is used, not inside the transport: the test
    # sends the key to the provider, which is the machine contacting a cloud
    # service. `ai_egress_enabled` is the one switch that admits that, and a
    # person who turned it off has said no to exactly this.
    if not await get_ai_egress_enabled(session):
        raise api_error(
            409, ErrorCode.AI_EGRESS_OFF, "cloud AI is turned off, so no request was sent"
        )
    await end_read(session)
    try:
        return await test_cloud_llm_connection(profile)
    except (CloudLLMError, httpx.HTTPError) as exc:
        raise api_error(502, ErrorCode.MODEL_UNREACHABLE, str(exc)) from exc


# --------------------------------------------------------------------------- #
# Fit — the ranking card's instrument (Settings > Intelligence).
#
# One read: how the ranked board is distributed against the standing intent
# vector, plus the freshness facts the card states ("ranked N new roles
# today"). The base set is EXACTLY the board's default browse base — same
# filters, same visibility — so the total here is the total the user sees on
# the board; a settings screen quoting a different number than the board it
# describes would be a lie with extra steps. The quantization and both
# statements live in `tracker/search/fit.py`.


@router.get("/api/intelligence/fit", response_model=IntelligenceFitResponse)
async def intelligence_fit(session: SessionDep, hidden: OffBoardDep) -> dict:
    params = {"status": "open", "hidden": hidden}
    total = (
        await session.scalar(
            select(func.count()).select_from(
                apply_job_filters(select(Job), params).subquery()
            )
        )
        or 0
    )

    persona = await get_persona_profile(session)
    intent_statement = str((persona or {}).get("intent_statement") or "") or None

    embedded_today = (
        await session.scalar(
            apply_job_filters(select(func.count()).select_from(Job), params).where(
                Job.embedded_at >= func.date_trunc("day", func.now())
            )
        )
        or 0
    )
    last_embedded_at = await session.scalar(
        apply_job_filters(select(func.max(Job.embedded_at)).select_from(Job), params)
    )

    stored = await get_intent_embedding(session)
    intent_vec = await build_intent_vector(session, stored["vector"] if stored else None)

    if intent_vec is None:
        return {
            "ranked": False,
            "intent_statement": intent_statement,
            "total": total,
            "unranked": None,
            "embedded_today": embedded_today,
            "last_embedded_at": last_embedded_at,
            "bin_width": FIT_BIN_WIDTH,
            "bins": [],
            "bands": [],
        }

    rows = (await session.execute(histogram_stmt(params, intent_vec))).all()
    by_bin = sorted((int(b), int(c)) for b, c in rows if b is not None)
    ranked_count = sum(c for _, c in by_bin)
    bands = fit_bands(by_bin)

    return {
        "ranked": True,
        "intent_statement": intent_statement,
        "total": total,
        "unranked": total - ranked_count,
        "embedded_today": embedded_today,
        "last_embedded_at": last_embedded_at,
        "bin_width": FIT_BIN_WIDTH,
        "bins": [
            {"fit": round(b * FIT_BIN_WIDTH, 4), "count": c} for b, c in by_bin
        ],
        "bands": bands,
    }


@router.get("/api/intelligence/fit/band/{band}", response_model=IntelligenceFitBandResponse)
async def intelligence_fit_band(
    band: str, session: SessionDep, hidden: OffBoardDep, limit: int = 3
) -> dict:
    """A band's few strongest roles, for the ranking card's preview list.

    Same browse base as `/api/intelligence/fit`; the raw score itself stays
    unrendered (dashboard `src/api/intelligence.ts` rule) — the response is ordinary job rows.
    """
    if band not in BAND_KEYS:
        raise api_error(404, ErrorCode.FIT_BAND_NOT_FOUND, "unknown fit band")
    limit = max(1, min(limit, 12))
    stored = await get_intent_embedding(session)
    intent_vec = await build_intent_vector(session, stored["vector"] if stored else None)
    if intent_vec is None:
        return {"band": band, "items": []}
    params = {"status": "open", "hidden": hidden}
    jobs = list((await session.scalars(band_stmt(params, intent_vec, band, limit))).all())
    ctx = await row_context(session, jobs, unfollowed=hidden.unfollowed, standing=False)
    return {"band": band, "items": [serialize_job(job, **ctx) for job in jobs]}


# --------------------------------------------------------------------------- #
# Stopping a switch.

@router.post("/api/intelligence/matching/stop", response_model=MatchingStopResponse)
async def stop_matching_switch(session: SessionDep) -> dict:
    """Stop the running switch AND put the choice back. One operation.

    There is deliberately no endpoint that only kills the job. The corpus is
    converted in place, so a bare stop would leave the tier pointing at the
    model the user just cancelled with most rows still on the old one — and the
    next scheduled pass would finish the switch they believed they had stopped.
    The only honest cancel is stop-and-revert.

    Order matters. The re-embed is stopped FIRST so no batch can land after the
    choice moves back; then the choice is restored in one transaction. A final
    batch that slips through during teardown is harmless either way, because
    every row carries the tier that produced it — the worst case is a handful of
    rows the next pass converts back, not a corpus split across two spaces.
    """
    processes = _processes(session)
    result = await matching.stop_switch(
        session,
        reembed_running=await _reembed_in_progress(session),
        terminate=processes.terminate,
        still_running=lambda: _reembed_in_progress(session),
    )
    if result.verdict is matching.StopSwitch.NOT_RUNNING:
        raise api_error(409, ErrorCode.NO_SWITCH_RUNNING, "no switch is running")
    if result.verdict is matching.StopSwitch.COULD_NOT_STOP:
        raise api_error(503, ErrorCode.SWITCH_NOT_STOPPED, "the matching update could not be stopped; the model choice was not changed")
    if result.verdict is matching.StopSwitch.UNMANAGED:
        raise api_error(409, ErrorCode.SWITCH_NOT_MANAGED, "the running matching update is not managed by the app and cannot be stopped here")
    return {
        "stopped": True,
        "outcome": result.outcome,
        **(await _intelligence_state(session)),
    }


@router.post("/api/intelligence/matching/resume", response_model=IntelligenceStateResponse)
async def resume_matching_switch(session: SessionDep) -> dict:
    """Finish an interrupted switch now, without touching the choice.

    Its own endpoint rather than a re-PUT of the current tier, because that
    would be a different act with two wrong side effects: it records the tier
    as a USER choice (the screen would start offering "Choose automatically" to
    someone who never chose), and it starts nothing at all — the tier is not
    moving, so the switch endpoint correctly treats it as a no-op. The work
    owed here is not a choice, it is the remainder of one already made.
    """
    outcome = await matching.resume_switch(
        reembed_running=await _reembed_in_progress(session),
        spawn=_processes(session).spawn,
    )
    if outcome is matching.ResumeSwitch.BUSY:
        raise api_error(409, ErrorCode.SWITCH_RUNNING, "a switch is already running")
    if outcome is matching.ResumeSwitch.SPAWN_FAILED:
        raise api_error(503, ErrorCode.SWITCH_NOT_STARTED, "the update could not be started; it will finish on the next scheduled run")
    return await _intelligence_state(session)
