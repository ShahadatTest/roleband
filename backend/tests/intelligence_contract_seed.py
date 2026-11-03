"""Realistic rows and a pinned machine for the AI settings contract.

The intelligence routes read the machine as much as the database: which model
files are on disk, how much RAM there is, whether a re-embed process is alive,
whether Apple's on-device model can run, whether the oMLX CLI is installed and
what a model server answers. `pin_integration_machine` pins exactly those
boundaries and nothing above them:

- the provisioning decision file lives in the test's directory and RAM is fixed,
  so `resolve_tier`, `read_decision` and `set_tier` run for real;
- `provision_state` and `is_present` answer from the scenario, sized from the
  real manifest, because the real ones stat 600 MB artifacts;
- the re-embed PID check, spawn, terminate and encoder reset are recorded, while
  the advisory-lock probe runs against the scratch database (`hold_reembed_lock`
  takes the lock the way a hand-run backfill does);
- the experimental provider is the real `NullProvider` when the switch is off and
  a scripted `ScriptedAppleProvider` when it is on;
- `which omlx` answers from the scenario and the CLI is a recorded fake process,
  so `local_llm.server.control` runs for real without starting anything;
- the HTTP clients `local_llm.client` and `cloud_llm.client` build are handed
  in-process transports: the loopback server is `lineage_contract_seed.model_server`,
  the provider API a script that checks the key it was sent. `LocalLLMClient`,
  `LocalLLMProvider` and `test_connection` run for real, on a fixed clock.

The seeds use the real stores: local and cloud profiles, `record_embed_measurement`,
`set_intent_embedding` and `log_ai_task`. Only the model-connection seeds carry an
API key, and it is not a real one.
"""

from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import tracker.cloud_llm.client as cloud_client
import tracker.local_llm.client as local_client
import tracker.local_llm.server as omlx_server
from tests.factories import make_job
from tests.lineage_contract_seed import MODEL_ID, _Ticker, model_server
from tracker.api.routers import intelligence as intelligence_router
from tracker.cloud_llm.models import CloudLLMProfile, CloudLLMProfileInput
from tracker.config import get_settings
from tracker.db.models import AppSetting
from tracker.intelligence import registry
from tracker.intelligence.provider import (
    Availability,
    AvailabilityState,
    GenerationResult,
    ProviderOrigin,
)
from tracker.intelligence_runtime.cloud_profiles import create_profile as create_cloud_profile
from tracker.intelligence_runtime.local_profiles import create_profile as create_local_profile
from tracker.intelligence_runtime.local_profiles import select_profile, set_enabled
from tracker.intelligence_runtime.telemetry import log_ai_task
from tracker.local_llm.models import LocalLLMParameters, LocalLLMProfile, LocalLLMProfileInput
from tracker.semantic import provision
from tracker.settings_store import (
    PERSONA_PROFILE_KEY,
    record_embed_measurement,
    set_ai_egress_enabled,
    set_intent_embedding,
)

RAM_32_GIB = 32 * 2**30
INTENT_STATEMENT = "leadership in AI/frontier tech"

OMLX_BINARY = "/opt/homebrew/bin/omlx"
#: What the in-process loopback server says when asked to confirm the connection.
LOCAL_REPLY = "RoleBand local model connection is ready."
LOCAL_KEY = "sk-local-contract-not-a-real-key"
CLOUD_KEY = "sk-cloud-contract-not-a-real-key"


class ScriptedAppleProvider:
    """Apple's on-device model as a script: an availability and one generation."""

    name = "apple_fm"
    origin = ProviderOrigin.ON_DEVICE

    def __init__(self) -> None:
        self.state = AvailabilityState.AVAILABLE
        self.detail: str | None = None
        self.result: GenerationResult | None = None
        self.prompts: list[str] = []

    async def availability(self) -> Availability:
        return Availability(self.state, self.detail)

    async def count_tokens(self, text: str) -> int:
        return max(1, len((text or "").split()))

    async def generate(self, *, instructions, prompt, schema, budget_tokens, validate=None):
        self.prompts.append(prompt)
        assert self.result is not None, "the scenario did not script a generation"
        return self.result


@dataclass
class ScriptedOmlx:
    """The oMLX CLI: where `which` finds it, and what one run prints and exits with."""

    binary: str | None = OMLX_BINARY
    exit_code: int = 0
    output: str = "oMLX server started on http://127.0.0.1:8000"
    brings_up: bool = True  # a start that exits 0 leaves the loopback server answering
    runs: list[tuple[str, ...]] = field(default_factory=list)


@dataclass
class ScriptedLocalServer:
    """The loopback OpenAI-compatible server, which lists `MODEL_ID` only."""

    up: bool = True
    wedged: bool = False  # listening, but never answers
    reply: str = LOCAL_REPLY
    finish_reason: str = "stop"
    requests: list[httpx.Request] = field(default_factory=list)


@dataclass
class ScriptedCloud:
    """A provider's API: the key it accepts, the models it lists, a forced failure."""

    key: str = CLOUD_KEY
    models: list[str] = field(default_factory=lambda: ["gpt-5-mini"])
    status: int | None = None
    error: str = "Rate limit reached for requests"
    reachable: bool = True
    requests: list[httpx.Request] = field(default_factory=list)


@dataclass
class PinnedMachine:
    """What the routes see of this Mac. Tests set the scenario fields."""

    data_dir: Path
    ram_bytes: int | None = RAM_32_GIB
    provision_status: str = "ready"  # ready | downloading | missing
    downloaded_fraction: float = 0.4
    installed: set[str] = field(default_factory=lambda: {"fp32"})
    reembedding: bool = False  # the re-embed WE spawned is alive
    spawn_ok: bool = True
    terminate_outcome: str = "stopped"
    spawns: int = 0
    terminations: int = 0
    resets: int = 0
    apple: ScriptedAppleProvider = field(default_factory=ScriptedAppleProvider)
    omlx: ScriptedOmlx = field(default_factory=ScriptedOmlx)
    local_server: ScriptedLocalServer = field(default_factory=ScriptedLocalServer)
    cloud: ScriptedCloud = field(default_factory=ScriptedCloud)


class _OmlxRun:
    """One `omlx <action>` process: exits as scripted, and moves the server with it."""

    def __init__(self, machine: PinnedMachine, action: str) -> None:
        self._machine = machine
        self._action = action
        self.returncode: int | None = None

    async def communicate(self):
        omlx, server = self._machine.omlx, self._machine.local_server
        self.returncode = omlx.exit_code
        if self.returncode == 0 and self._action in ("start", "restart"):
            server.up = omlx.brings_up
        elif self.returncode == 0 and self._action == "stop":
            server.up = False
        return omlx.output.encode(), None

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int | None:
        return self.returncode


def pin_integration_machine(monkeypatch, tmp_path: Path) -> PinnedMachine:
    """Pin the intelligence routes to a machine the test owns. Apply after `no_escape`."""
    import tracker.semantic.embed as embed
    from tracker.api import job_requests

    machine = PinnedMachine(data_dir=tmp_path)

    def provision_state(spec, tier):
        total = spec.tiers[tier].size + spec.tokenizer.size
        done = {
            "ready": total,
            "downloading": int(total * machine.downloaded_fraction),
            "missing": 0,
        }[machine.provision_status]
        return provision.ProvisionState(machine.provision_status, tier, done, total)

    async def spawn(_session, *, requested_by) -> bool:
        machine.spawns += 1
        if machine.spawn_ok:
            machine.reembedding = True
        return machine.spawn_ok

    async def terminate(_session, **_kwargs):
        machine.terminations += 1
        # Stopped, or found already gone: either way nothing of ours is live.
        if machine.terminate_outcome in ("stopped", "not_running"):
            machine.reembedding = False
        return machine.terminate_outcome, 48_311

    real_pending = job_requests.pending

    async def pending(session, job):
        if job == job_requests.REEMBED:
            return machine.reembedding
        return await real_pending(session, job)

    real_build_provider = registry.build_provider

    monkeypatch.setattr(provision, "DATA_DIR", tmp_path)
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: machine.ram_bytes)
    monkeypatch.setattr(provision, "provision_state", provision_state)
    monkeypatch.setattr(provision, "is_present", lambda spec, tier: tier in machine.installed)
    monkeypatch.setattr(job_requests, "pending", pending)
    monkeypatch.setattr(job_requests, "ring_reembed", spawn)
    monkeypatch.setattr(job_requests, "stop_reembed", terminate)
    monkeypatch.setattr(embed, "reset_model", lambda: setattr(machine, "resets", machine.resets + 1))
    monkeypatch.setattr(
        intelligence_router,
        "build_provider",
        lambda enabled: machine.apple if enabled else real_build_provider(False),
    )
    _pin_model_connections(monkeypatch, machine)
    return machine


def _pin_model_connections(monkeypatch, machine: PinnedMachine) -> None:
    refuse_process = asyncio.create_subprocess_exec  # `no_escape`'s refusal

    async def create_subprocess_exec(program, *args, **kwargs):
        if machine.omlx.binary is None or program != machine.omlx.binary:
            return refuse_process(program, *args, **kwargs)
        machine.omlx.runs.append((program, *args))
        return _OmlxRun(machine, args[0])

    async def loopback(request: httpx.Request) -> httpx.Response:
        server = machine.local_server
        server.requests.append(request)
        if server.wedged:
            await asyncio.sleep(3600)
        if not server.up:
            raise httpx.ConnectError("All connection attempts failed", request=request)
        return model_server(server.reply, finish_reason=server.finish_reason).handler(request)

    def provider_api(request: httpx.Request) -> httpx.Response:
        cloud = machine.cloud
        cloud.requests.append(request)
        if not cloud.reachable:
            raise httpx.ConnectError("All connection attempts failed", request=request)
        sent = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
        if sent != cloud.key:
            return httpx.Response(401, json={"error": {"message": "Incorrect API key provided."}})
        if cloud.status is not None:
            return httpx.Response(cloud.status, json={"error": {"message": cloud.error}})
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": m, "object": "model"} for m in cloud.models]})
        if request.method == "POST" and request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "OK"}],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            )
        return httpx.Response(404, json={"error": {"message": "not found"}})

    loopback_transport = httpx.MockTransport(loopback)
    provider_transport = httpx.MockTransport(provider_api)

    monkeypatch.setattr(
        omlx_server,
        "shutil",
        SimpleNamespace(which=lambda name: machine.omlx.binary if name == omlx_server.BINARY else None),
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(
        local_client, "make_client", lambda **kw: httpx.AsyncClient(transport=loopback_transport, **kw)
    )
    monkeypatch.setattr(local_client, "time", _Ticker())
    monkeypatch.setattr(
        cloud_client, "make_client", lambda **kw: httpx.AsyncClient(transport=provider_transport, **kw)
    )
    monkeypatch.setattr(cloud_client, "perf_counter", _Ticker().monotonic)


@asynccontextmanager
async def hold_reembed_lock(engine: AsyncEngine):
    """Hold the re-embed advisory lock on a connection of its own, as a hand-run backfill does."""
    key = get_settings().reembed_lock_key
    async with engine.connect() as holder:
        await holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        try:
            yield
        finally:
            await holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


@dataclass(frozen=True)
class SeededRouting:
    local_model: str
    cloud_model: str


async def seed_routing(session: AsyncSession) -> SeededRouting:
    """A local oMLX profile switched on, one enabled and one disabled cloud profile,
    and a week of recorded extraction attempts for each tier."""
    local = await create_local_profile(
        session,
        LocalLLMProfileInput(name="Local Qwen", provider="omlx", model="Qwen3-30B-A3B-4bit"),
    )
    await select_profile(session, local.id)
    await set_enabled(session, True)
    await create_cloud_profile(
        session,
        CloudLLMProfileInput(
            name="OpenAI", provider="openai", base_url="https://api.openai.com/v1",
            model="gpt-5-mini", enabled=True,
        ),
    )
    await create_cloud_profile(
        session,
        CloudLLMProfileInput(
            name="Anthropic", provider="anthropic", base_url="https://api.anthropic.com",
            model="claude-haiku-4-5", enabled=False,
        ),
    )
    for provider, result, latency in (
        ("omlx", "ok", 900),
        ("omlx", "ok", 1300),
        ("omlx", "ok", 1100),
        ("omlx", "invalid", 2400),
        ("omlx", "skipped", None),  # no model was asked: never measured
        ("cloud_openai", "ok", 700),
    ):
        await log_ai_task(
            session,
            task_type="disclosed_comp",
            provider=provider,
            availability_state="available" if result != "skipped" else "not_configured",
            validation_result=result,
            failure_class="validation" if result == "invalid" else None,
            latency_ms=latency,
        )
    await session.commit()
    return SeededRouting(local_model=local.model, cloud_model="gpt-5-mini")


async def seed_local_connection(
    session: AsyncSession,
    *,
    name: str = "Local Qwen",
    provider: str = "omlx",
    model: str = MODEL_ID,
    api_key: str | None = LOCAL_KEY,
    parameters: LocalLLMParameters | None = None,
) -> LocalLLMProfile:
    """A saved local connection through the store. The first one saved is the active one."""
    profile = await create_local_profile(
        session,
        LocalLLMProfileInput(
            name=name, provider=provider, model=model, api_key=api_key,
            parameters=parameters or LocalLLMParameters(),
        ),
    )
    await session.commit()
    return profile


async def seed_cloud_connection(
    session: AsyncSession,
    *,
    name: str = "OpenAI",
    provider: str = "openai",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-5-mini",
    enabled: bool = True,
    api_key: str | None = CLOUD_KEY,
    egress: bool = True,
) -> CloudLLMProfile:
    """A saved cloud connection through the store.

    `egress` is the switch that admits a cloud request at all: saving a
    connection does not, and the test endpoint refuses while it is off. On by
    default here because every caller but the refusal test is exercising a
    request that is allowed to leave.
    """
    if egress:
        await set_ai_egress_enabled(session, True)
    profile = await create_cloud_profile(
        session,
        CloudLLMProfileInput(
            name=name, provider=provider, base_url=base_url, model=model, enabled=enabled, api_key=api_key,
        ),
    )
    await session.commit()
    return profile


async def seed_embed_measurement(session: AsyncSession) -> None:
    """One completed fp32 pass on this machine: 4,114 roles in 745 seconds."""
    await record_embed_measurement(session, tier="fp32", rows=4114, seconds=745.0)
    await session.commit()


def _unit(fit: float, dim: int) -> list[float]:
    """A unit vector whose cosine against the first axis is exactly `fit`."""
    return [fit, math.sqrt(1 - fit * fit)] + [0.0] * (dim - 2)


@dataclass(frozen=True)
class SeededFit:
    """Job ids by role in the fit base, and the newest embed time among them."""

    strong: list[int]
    good: list[int]
    some: list[int]
    weak: list[int]
    unembedded: int
    closed: int
    out_of_scope: int
    last_embedded_at: datetime


async def seed_fit(session: AsyncSession, *, today: datetime) -> SeededFit:
    """An intent statement and an open, in-scope board spread across every band.

    Fits avoid band edges and bin edges, so pgvector's float arithmetic cannot
    move a row across one. Two rows share a bin (0.553 and 0.556) and two share
    the strong band from different bins. A closed and an out-of-scope row are
    embedded but outside the base; one open row has no embedding yet.
    """
    dim = get_settings().embedding_dim
    tier = provision.resolve_tier()
    session.add(AppSetting(key=PERSONA_PROFILE_KEY, value={"intent_statement": INTENT_STATEMENT}))
    await set_intent_embedding(session, INTENT_STATEMENT, [1.0] + [0.0] * (dim - 1))

    older = today - timedelta(days=3)
    spread = [
        ("strong-a", 0.751, today, {}),
        ("strong-b", 0.613, older, {}),
        ("good-a", 0.553, today, {}),
        ("good-b", 0.556, older, {}),
        ("some-a", 0.451, older, {}),
        ("weak-a", 0.301, older, {}),
        ("closed", 0.771, older, {"status": "closed"}),
        ("out-of-scope", 0.711, older, {"in_scope": False}),
    ]
    rows = {
        key: make_job(f"fit-{key}", embedding=_unit(fit, dim), embedded_at=at, embedded_tier=tier, **over)
        for key, fit, at, over in spread
    }
    rows["unembedded"] = make_job("fit-unembedded")
    session.add_all(rows.values())
    await session.commit()
    return SeededFit(
        strong=[rows["strong-a"].id, rows["strong-b"].id],
        good=[rows["good-b"].id, rows["good-a"].id],
        some=[rows["some-a"].id],
        weak=[rows["weak-a"].id],
        unembedded=rows["unembedded"].id,
        closed=rows["closed"].id,
        out_of_scope=rows["out-of-scope"].id,
        last_embedded_at=today,
    )
