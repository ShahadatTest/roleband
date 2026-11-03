"""Response contracts for the AI settings, model connection, matching and fit routes.

`GET`/`PUT /api/intelligence`, `PUT /api/intelligence/egress`, the three matching
routes (`tier`, `stop`, `resume`), the experimental self-test, the fit instrument
and its band preview, and agent access; the saved local and cloud model
connections, the local server's status and control, and both connection tests.

- **An API key is write-only.** A saved connection is served with `has_api_key`
  and never the key; the profile models forbid unknown keys, so a builder that
  starts serving the secret fails the response instead of leaking it.

- **Every shape here is one our code builds**, so every model forbids unknown
  keys, declared in handler order. The self-test's `raw` is the exception in
  kind, not in rule: it is what the provider returned, served as it came.
- **A key set that differs by branch is a union.** The matching state omits
  `estimate_seconds`, in a different key order, when the configured embedding
  model has no pinned manifest; the self-test answers four key sets (provider
  unavailable, no pay signal, model failed, model answered), which `ok` and
  `prefiltered` tell apart. The self-test route answers the named `RootModel`
  `IntelligenceTestResponse`, since the route table counts only a named model.
- **Literals where our code owns the vocabulary**: availability states and
  provider origins (the enums in `intelligence.provider`, held by the contract
  test), the embedding tiers (`semantic.provision.TIERS`), the provisioning
  status, `chosen_by`, `job_phase`, fit band keys, the stop outcomes a switch
  can end with, and agent tool access. Route reasons, failure classes and
  attempt outcomes stay `str`: `policy.RouteReason` is documented as a vocabulary
  that gains values.
- Counts, byte sizes and durations are integers the handlers compute. The fit
  bin edge is a rounded float.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, RootModel

from tracker.api.schemas.base import Built
from tracker.api.schemas.jobs import JobRow
from tracker.api.schemas.local_models import LocalModelMetrics, LocalModelProvider
from tracker.api.schemas.text_class import text
from tracker.local_llm.models import LocalLLMParameters
from tracker.pay_disclosure import DisclosedComp

# Held to `CloudLLMProfileInput.provider` and to `local_llm.server.Action` by
# `tests/test_api_model_connections_contract.py`.
CloudModelProvider = Literal["openai", "anthropic", "openai_compatible"]
LocalServerAction = Literal["start", "stop", "restart"]

# Held to `AvailabilityState`, `ProviderOrigin`, `provision.TIERS` and the fit
# band edges by `tests/test_api_intelligence_contract.py`.
AvailabilityStateName = Literal[
    "available",
    "disabled_by_flag",
    "sdk_absent",
    "apple_intelligence_disabled",
    "device_ineligible",
    "model_not_ready",
    "not_configured",
    "server_unreachable",
    "egress_not_permitted",
]
ProviderOriginName = Literal["none", "on_device", "this_mac", "cloud"]
MatchingTierName = Literal["fp32", "int8"]
FitBandKey = Literal["strong", "good", "some", "weak"]
#: What a stop can have ended: the switch it signalled, or one that had already exited.
SwitchStopOutcome = Literal["stopped", "not_running"]
AgentToolAccess = Literal["status", "read", "write"]


# --------------------------------------------------------------------------- #
# The shared state: `GET`/`PUT /api/intelligence`, egress, tier, resume
# --------------------------------------------------------------------------- #


class ProviderAvailability(Built):
    """Why a provider can or cannot run: `state` is the code the dashboard says;
    `detail` is the engineering reason, never shown."""

    state: AvailabilityStateName
    ok: bool
    detail: str | None = Field(json_schema_extra=text("diagnostic"))


class RoutingTier(Built):
    """One rung of the routed-task ladder as configured, never probed."""

    provider: str
    origin: ProviderOriginName
    model_id: str | None
    blocked_reason: str | None = Field(json_schema_extra=text("code"))


class IntelligenceRouting(Built):
    egress_enabled: bool
    tiers: list[RoutingTier]


class MatchingTierOption(Built):
    """An artifact of the bundled model the user may switch to, priced for this machine."""

    tier: MatchingTierName
    total_bytes: int
    recommended: bool
    installed: bool
    switch_seconds: int | None


class MatchingState(Built):
    """Provisioning of the bundled embedding model, and the corpus measured against it."""

    status: Literal["ready", "downloading", "missing"]
    tier: MatchingTierName
    model_id: str
    downloaded_bytes: int
    total_bytes: int
    chosen_by: Literal["user", "auto"]
    detected_ram_bytes: int | None
    #: Total RAM at or above which the automatic choice takes the big model;
    #: below it, the small one (`provision.TIER_RAM_THRESHOLD`).
    ram_threshold_bytes: int
    tiers: list[MatchingTierOption]
    reembedding: bool
    corpus_embedded: int
    corpus_total: int
    stale_count: int
    other_tier_count: int
    job_phase: Literal["downloading", "converting", "none"]
    estimate_seconds: int | None


class MatchingUnpinned(Built):
    """The configured embedding model has no pinned manifest: nothing can be
    provisioned, so the handler answers fixed values and no estimate."""

    status: Literal["missing"]
    tier: None
    model_id: str
    downloaded_bytes: int
    total_bytes: int
    chosen_by: Literal["auto"]
    detected_ram_bytes: None
    ram_threshold_bytes: int
    tiers: list[MatchingTierOption]
    reembedding: Literal[False]
    stale_count: int
    other_tier_count: int
    job_phase: Literal["none"]
    corpus_embedded: int
    corpus_total: int


class IntelligenceStateResponse(Built):
    """The Settings > AI state. `enabled` and `availability` describe the
    experimental Apple integration only; `routing` is the local/cloud ladder."""

    matching: MatchingState | MatchingUnpinned
    enabled: bool
    provider: str
    availability: ProviderAvailability
    model_id: str
    prompt_version: str
    routing: IntelligenceRouting


class _SwitchStopped(Built):
    stopped: Literal[True]
    outcome: SwitchStopOutcome


class MatchingStopResponse(IntelligenceStateResponse, _SwitchStopped):
    """`POST /api/intelligence/matching/stop`: what the stop ended, then the
    state after the choice went back. Pydantic takes the last base's fields
    first, which is the order the handler writes."""


# --------------------------------------------------------------------------- #
# The experimental self-test: `POST /api/intelligence/test`
# --------------------------------------------------------------------------- #


class ExpectedBand(Built):
    """What the built-in sample posting states; null for text the user supplied."""

    base_min: int
    base_max: int
    currency: str


class RouteAttemptRecord(Built):
    """`RouteAttempt.redacted()`: a tier tried, by name and outcome class only."""

    provider: str
    origin: ProviderOriginName
    outcome: str
    reason: str = Field(json_schema_extra=text("code"))
    latency_ms: int | None
    failure_class: str | None


class ExtractedDisclosedComp(DisclosedComp):
    """What survived grounding and bounds validation, as `model_dump(mode="json")`
    writes it. Subclassed so the bounds are defined once. The dump always writes
    every key, so a default does not make one optional on the wire."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class _SelfTestBase(Built):
    availability: ProviderAvailability
    used_sample: bool
    prompt_version: str
    model_id: str
    expected: ExpectedBand | None


class SelfTestUnavailable(_SelfTestBase):
    """The provider cannot run; nothing was asked of a model."""

    ok: Literal[False]


class SelfTestPrefiltered(_SelfTestBase):
    """The text states no pay, so no model call was made, as in the real pass."""

    ok: Literal[True]
    prefiltered: Literal[True]
    raw: None
    extracted: None


class SelfTestModelFailed(_SelfTestBase):
    """A model was asked and returned nothing usable."""

    ok: Literal[False]
    failure_class: str | None
    latency_ms: int | None
    origin: ProviderOriginName
    left_device: bool
    answered_by: str | None
    route_reason: str | None = Field(json_schema_extra=text("code"))
    route_attempts: list[RouteAttemptRecord]


class SelfTestAnswered(_SelfTestBase):
    """A model answered. `raw` is what it returned, served as it came;
    `extracted` is what would have been stored."""

    ok: Literal[True]
    prefiltered: Literal[False]
    latency_ms: int | None
    origin: ProviderOriginName
    left_device: bool
    answered_by: str | None
    route_reason: str | None = Field(json_schema_extra=text("code"))
    route_attempts: list[RouteAttemptRecord]
    input_tokens: int | None
    output_tokens: int | None
    truncated: bool
    raw: dict[str, Any]
    extracted: ExtractedDisclosedComp
    grounded: bool
    rejected_ungrounded: bool


class IntelligenceTestResponse(
    RootModel[SelfTestUnavailable | SelfTestPrefiltered | SelfTestModelFailed | SelfTestAnswered]
):
    """`POST /api/intelligence/test`: one of the four outcomes, never raised."""


# --------------------------------------------------------------------------- #
# The fit instrument: `GET /api/intelligence/fit` and its band preview
# --------------------------------------------------------------------------- #


class IntelligenceFitBin(Built):
    """One non-empty histogram bin; `fit` is its lower edge."""

    fit: float
    count: int


class IntelligenceFitBand(Built):
    """One presentational band. `lower_edge` is the lowest fit it holds, the
    line the screen draws under it; null for weak, which is open below."""

    key: FitBandKey
    count: int
    lower_edge: float | None


class IntelligenceFitResponse(Built):
    """How the board's browse base distributes against the standing intent.
    Unranked (no intent vector): `unranked` null, no bins and no bands.
    `bin_width` is the fit each bin spans upward from its `fit`."""

    ranked: bool
    intent_statement: str | None
    total: int
    unranked: int | None
    embedded_today: int
    last_embedded_at: datetime | None
    bin_width: float
    bins: list[IntelligenceFitBin]
    bands: list[IntelligenceFitBand]


class IntelligenceFitBandResponse(Built):
    """A band's strongest open roles, best fit first, as ordinary list rows."""

    band: FitBandKey
    items: list[JobRow]


# --------------------------------------------------------------------------- #
# External agents: `GET`/`PUT /api/intelligence/agents`
# --------------------------------------------------------------------------- #


class AgentTool(Built):
    name: str = Field(json_schema_extra=text("code"))
    access: AgentToolAccess


class McpServerCommand(Built):
    command: str
    args: list[str]
    cwd: str


class ClaudeMcpServers(Built):
    roleband: McpServerCommand


class ClaudeDesktopConfig(Built):
    """The `claude_desktop_config.json` fragment, served under its own key names."""

    mcp_servers: ClaudeMcpServers = Field(alias="mcpServers")


class AgentAccessResponse(Built):
    """Both gates as saved, and what a client needs to connect over STDIO."""

    enabled: bool
    allow_writes: bool
    transport: Literal["stdio"]
    command: str
    args: list[str]
    cwd: str
    tools: list[AgentTool]
    codex_command: str
    claude_json: ClaudeDesktopConfig


# --------------------------------------------------------------------------- #
# Local model connections: `/api/intelligence/local-models`, its server and test
# --------------------------------------------------------------------------- #


class LocalModelParameters(LocalLLMParameters):
    """The saved generation controls, as `model_dump` writes them. Subclassed so
    the bounds are defined once. The dump always writes every key, so a default
    does not make one optional on the wire; float fields go out as floats, since
    the store re-validates every connection it saves and reads."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class LocalModelProfile(Built):
    """`LocalLLMProfile.public()`: a saved connection. `has_api_key` says whether
    a key is saved; the key itself is write-only."""

    id: str
    name: str = Field(json_schema_extra=text("content"))
    provider: LocalModelProvider
    base_url: str
    model: str
    has_api_key: bool
    parameters: LocalModelParameters


class LocalModelState(Built):
    """`LocalLLMState.public()`: the local tier's switch and every saved connection.
    `active_profile_id` is the first saved connection when the stored choice names
    none, and null with none saved."""

    enabled: bool
    active_profile_id: str | None
    profiles: list[LocalModelProfile]


class LocalServerStatus(Built):
    """The local-server row, as three facts kept apart: `installed` (the oMLX CLI
    is on this Mac), `managed` (the app may start and stop this connection) and
    `reachable` (it answers now). `state` is the probe's availability, or
    `not_configured` with nothing saved."""

    enabled: bool
    installed: bool
    binary: str | None
    managed: bool
    profile_id: str | None
    provider: LocalModelProvider | None
    model: str | None
    base_url: str | None
    state: AvailabilityStateName
    reachable: bool
    detail: str = Field(json_schema_extra=text("diagnostic"))


class LocalServerControlResponse(LocalServerStatus):
    """`POST .../local-models/server`: the probe taken after the command, then what
    the command reported. A CLI that exited 0 is not evidence the server answers."""

    action: LocalServerAction
    action_ok: bool
    action_detail: str = Field(json_schema_extra=text("diagnostic"))


class LocalModelTestResult(Built):
    """`POST .../local-models/{profile_id}/test`: one completion. `model` is the one
    the server says answered; a reply cut off at `max_tokens` is not `ok`."""

    ok: bool
    profile_id: str
    provider: LocalModelProvider
    model: str
    response: str
    finish_reason: str | None = Field(json_schema_extra=text("code"))
    truncated: bool
    metrics: LocalModelMetrics


# --------------------------------------------------------------------------- #
# Cloud model connections: `/api/intelligence/cloud-models` and its test
# --------------------------------------------------------------------------- #


class CloudModelProfile(Built):
    """`CloudLLMProfile.public()`: a saved BYOK connection; the key is write-only."""

    id: str
    name: str = Field(json_schema_extra=text("content"))
    provider: CloudModelProvider
    base_url: str
    model: str
    enabled: bool
    has_api_key: bool


class CloudModelState(Built):
    profiles: list[CloudModelProfile]


class CloudModelTestResult(Built):
    """`POST .../cloud-models/{profile_id}/test`: an authenticated check that
    succeeded. Every failure is an HTTP error, so `ok` is always true."""

    ok: Literal[True]
    profile_id: str
    provider: CloudModelProvider
    model: str
    latency_ms: int
