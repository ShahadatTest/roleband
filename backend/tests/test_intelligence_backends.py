"""The two non-Apple backends on the seam, plus the single egress gate.

Transport is mocked at httpx, so these exercise the real client code (payload
shape, error classification, metric extraction) without a network. The registry
tests assert the property the shipped privacy copy rests on: there is exactly
one switch that can put a cloud tier into a chain.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tracker.cloud_llm.client import CloudLLMClient
from tracker.cloud_llm.models import CloudLLMProfile, CloudLLMState
from tracker.intelligence.policy import RouteReason
from tracker.intelligence.provider import (
    AvailabilityState,
    IntelligenceProvider,
    NullProvider,
    ProviderOrigin,
)
from tracker.intelligence.providers.cloud import CloudLLMProvider
from tracker.intelligence.providers.local import LocalLLMProvider
from tracker.intelligence.router import RouterProvider
from tracker.intelligence.structured import json_instruction, parse_json_object
from tracker.intelligence_runtime import routing
from tracker.local_llm.client import LocalLLMClient
from tracker.local_llm.models import LocalLLMParameters, LocalLLMProfile
from tracker.pay_disclosure import DisclosedComp

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

MODEL = "Ornith-1.0-35B-5bit-mlx"


def _local_profile() -> LocalLLMProfile:
    return LocalLLMProfile(
        id="profile12345",
        name="Local",
        provider="omlx",
        base_url="http://127.0.0.1:8000/v1",
        model=MODEL,
        api_key=None,
        parameters=LocalLLMParameters(enable_thinking=False, max_tokens=512),
    )


def _cloud_profile(**overrides) -> CloudLLMProfile:
    values = dict(
        id="cloudprofile1",
        name="Cloud",
        provider="openai",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        enabled=True,
        api_key="k",
    )
    values.update(overrides)
    return CloudLLMProfile(**values)


def _local_provider(handler) -> LocalLLMProvider:
    profile = _local_profile()
    client = LocalLLMClient(
        profile, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return LocalLLMProvider(profile, client=client)


def _cloud_provider(handler, **overrides) -> CloudLLMProvider:
    profile = _cloud_profile(**overrides)
    client = CloudLLMClient(
        profile, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return CloudLLMProvider(profile, client=client)


def _generate(provider):
    return asyncio.run(
        provider.generate(
            instructions="Extract pay.", prompt="body", schema=DisclosedComp, budget_tokens=8192
        )
    )


def _chat_response(content: str, *, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": MODEL,
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        },
    )


def _models_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 262144}]})


# --------------------------------------------------------------------------- #
# Both adapters satisfy the Protocol the callers depend on
# --------------------------------------------------------------------------- #


def test_every_backend_satisfies_the_provider_protocol():
    def handler(_):
        return _models_response()

    for provider in (
        _local_provider(handler),
        _cloud_provider(handler),
        NullProvider(),
        RouterProvider([]),
    ):
        assert isinstance(provider, IntelligenceProvider)
        assert isinstance(provider.origin, ProviderOrigin)
        assert isinstance(provider.name, str) and provider.name


# --------------------------------------------------------------------------- #
# Local (oMLX) adapter
# --------------------------------------------------------------------------- #


def test_local_generate_returns_parsed_fields_and_oMLX_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return _chat_response('{"disclosed": true, "base_min": 180000}')

    res = _generate(_local_provider(handler))
    assert res.fields == {"disclosed": True, "base_min": 180000}
    assert res.origin is ProviderOrigin.THIS_MAC
    assert res.provider_name == "omlx"
    assert (res.input_tokens, res.output_tokens) == (120, 40)


def test_local_truncated_turn_fails_closed_instead_of_parsing_a_partial_object():
    # A JSON object cut mid-value can still decode into something plausible.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return _chat_response('{"disclosed": true, "base_min": 18', finish_reason="length")

    res = _generate(_local_provider(handler))
    assert res.fields is None
    assert res.failure_class == "truncated"


def test_local_prose_wrapped_json_is_still_recovered():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return _chat_response('Here you go:\n{"disclosed": false}')

    assert _generate(_local_provider(handler)).fields == {"disclosed": False}


def test_local_unparseable_turn_is_a_validation_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return _models_response()
        return _chat_response("I could not determine the salary.")

    res = _generate(_local_provider(handler))
    assert (res.fields, res.failure_class) == (None, "validation")


def test_local_unreachable_server_is_an_availability_state_not_an_exception():
    def handler(_):
        raise httpx.ConnectError("refused")

    avail = asyncio.run(_local_provider(handler).availability())
    assert avail.state is AvailabilityState.SERVER_UNREACHABLE
    assert avail.ok is False


def test_local_server_serving_a_different_model_is_not_available():
    def handler(_):
        return httpx.Response(200, json={"data": [{"id": "some-other-model"}]})

    avail = asyncio.run(_local_provider(handler).availability())
    assert avail.state is AvailabilityState.MODEL_NOT_READY


# --------------------------------------------------------------------------- #
# Cloud adapter
# --------------------------------------------------------------------------- #


def test_cloud_openai_generate_parses_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer k"
        return _chat_response('{"disclosed": true}')

    res = _generate(_cloud_provider(handler))
    assert res.fields == {"disclosed": True}
    assert res.origin is ProviderOrigin.CLOUD
    assert res.provider_name == "cloud_openai"


def test_cloud_anthropic_max_tokens_normalizes_onto_truncated():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/messages")
        assert request.headers["x-api-key"] == "k"
        return httpx.Response(
            200,
            json={
                "model": "claude-test",
                "content": [{"type": "text", "text": '{"disclosed": tr'}],
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    res = _generate(_cloud_provider(handler, provider="anthropic"))
    assert res.failure_class == "truncated"
    assert res.fields is None


def test_cloud_rate_limit_is_classified_so_the_router_can_escalate():
    def handler(_):
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    res = _generate(_cloud_provider(handler))
    assert res.failure_class == "rate_limited"


def test_cloud_availability_makes_no_network_request():
    def handler(_):  # pragma: no cover - must never run
        raise AssertionError("availability() must not reach the network")

    provider = _cloud_provider(handler)
    assert asyncio.run(provider.availability()).ok is True
    disabled = _cloud_provider(handler, enabled=False)
    assert asyncio.run(disabled.availability()).state is AvailabilityState.NOT_CONFIGURED


# --------------------------------------------------------------------------- #
# Structured-output helper (shared by both chat backends)
# --------------------------------------------------------------------------- #


def test_json_instruction_is_derived_from_the_validator_schema():
    text = json_instruction(DisclosedComp)
    assert "disclosed" in text and "source_snippet" in text
    # Enum-ish fields must carry their allowed values, or the model invents them.
    assert "year" in text and "hour" in text


@pytest.mark.parametrize(
    "content,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure!\n{"a": 1}', {"a": 1}),
        ("[1, 2]", None),
        ("no json here", None),
        ("", None),
    ],
)
def test_parse_json_object_recovers_or_refuses(content, expected):
    assert parse_json_object(content) == expected


# --------------------------------------------------------------------------- #
# The egress gate — the single door to off-device inference
# --------------------------------------------------------------------------- #


def _wire_registry(
    monkeypatch, *, local, cloud_profiles, egress, local_enabled=True
):
    async def fake_measure(_session, *, task_type):
        return {}

    async def fake_local(_session):
        return _local_profile() if local else None

    # The local tier's own on/off switch, independent of whether a profile is
    # saved: "no server configured" and "I turned it off" are different states.
    async def fake_local_enabled(_session):
        return local_enabled

    async def fake_cloud_state(_session):
        return CloudLLMState(profiles=cloud_profiles)

    async def fake_egress(_session):
        return egress

    monkeypatch.setattr(routing, "measure_tiers", fake_measure)
    monkeypatch.setattr(routing, "get_active_local_profile", fake_local)
    monkeypatch.setattr(routing, "get_local_enabled", fake_local_enabled)
    monkeypatch.setattr(routing, "get_cloud_state", fake_cloud_state)
    monkeypatch.setattr(routing, "get_ai_egress_enabled", fake_egress)


def test_cloud_tier_is_blocked_without_the_egress_opt_in(monkeypatch):
    _wire_registry(
        monkeypatch, local=True, cloud_profiles=[_cloud_profile()], egress=False
    )
    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    cloud = [t for t in tiers if t.provider.origin is ProviderOrigin.CLOUD]
    assert len(cloud) == 1
    assert cloud[0].blocked_reason == RouteReason.EGRESS_BLOCKED


def test_cloud_tier_unblocks_only_when_the_user_opts_in(monkeypatch):
    _wire_registry(
        monkeypatch, local=True, cloud_profiles=[_cloud_profile()], egress=True
    )
    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    cloud = [t for t in tiers if t.provider.origin is ProviderOrigin.CLOUD]
    assert cloud[0].blocked_reason is None


def test_a_disabled_cloud_profile_never_enters_the_ladder_even_with_egress_on(monkeypatch):
    _wire_registry(
        monkeypatch,
        local=True,
        cloud_profiles=[_cloud_profile(enabled=False)],
        egress=True,
    )
    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    assert not [t for t in tiers if t.provider.origin is ProviderOrigin.CLOUD]


def test_cloud_only_and_egress_off_resolves_to_a_null_provider_with_the_reason(monkeypatch):
    _wire_registry(
        monkeypatch, local=False, cloud_profiles=[_cloud_profile()], egress=False
    )
    provider = asyncio.run(routing.resolve_provider(object()))
    assert isinstance(provider, NullProvider)
    state = asyncio.run(provider.availability()).state
    assert state is AvailabilityState.EGRESS_NOT_PERMITTED


def test_routing_turned_off_in_config_reaches_no_backend_at_all(monkeypatch):
    """The outermost switch, checked BEFORE any tier is assembled: with routing
    off, a fully configured local backend is still not reached, and the reason
    the user sees says so rather than "nothing configured"."""
    _wire_registry(monkeypatch, local=True, cloud_profiles=[_cloud_profile()], egress=True)
    monkeypatch.setattr(
        routing.get_settings(), "intelligence_routing_enabled", False, raising=True
    )
    provider = asyncio.run(routing.resolve_provider(object()))
    assert isinstance(provider, NullProvider)
    assert asyncio.run(provider.availability()).state is AvailabilityState.DISABLED_BY_FLAG


def test_a_lone_backend_is_handed_back_directly_and_not_wrapped_in_a_router(monkeypatch):
    """With one tier there is no ladder to escalate, and telemetry must record the
    provider that actually ran rather than "router"."""
    _wire_registry(monkeypatch, local=True, cloud_profiles=[], egress=False)
    provider = asyncio.run(routing.resolve_provider(object(), task_type="disclosed_comp"))
    assert not isinstance(provider, RouterProvider)
    assert provider.origin is ProviderOrigin.THIS_MAC

    # Two tiers must still route, or the assertion above would pass for a build
    # that never wraps anything.
    _wire_registry(monkeypatch, local=True, cloud_profiles=[_cloud_profile()], egress=True)
    assert isinstance(
        asyncio.run(routing.resolve_provider(object(), task_type="disclosed_comp")),
        RouterProvider,
    )


@pytest.mark.parametrize("egress", [False, True])
def test_with_egress_off_the_cloud_transport_sees_no_request_even_on_fallthrough(
    monkeypatch, egress
):
    """The tests above pin a LABEL (`blocked_reason`); the privacy copy — "nothing
    leaves this computer" — promises an absence of traffic. This pins the absence
    at the transport: the local tier is down, so the router walks on
    down the ladder, and the cloud transport must receive nothing. The `True`
    case is the control — the same ladder with egress on DOES reach it — without
    which a router that never walked past a failed tier would pass as private.
    """
    cloud_requests: list[str] = []

    def local_down(_request):
        return httpx.Response(503, json={"error": "server is loading"})

    def cloud(request):
        cloud_requests.append(f"{request.method} {request.url.path}")
        return _chat_response('{"min_base": null}')

    _wire_registry(monkeypatch, local=True, cloud_profiles=[_cloud_profile()], egress=egress)
    monkeypatch.setattr(routing, "LocalLLMProvider", lambda _profile: _local_provider(local_down))
    monkeypatch.setattr(routing, "CloudLLMProvider", lambda _profile: _cloud_provider(cloud))

    provider = asyncio.run(routing.resolve_provider(object(), task_type="disclosed_comp"))
    result = _generate(provider)

    if egress:
        assert cloud_requests, "control: with egress on, the fallthrough must reach the cloud"
    else:
        assert cloud_requests == []
        assert result.fields is None


def test_ladder_order_is_apple_then_local_then_cloud(monkeypatch):
    _wire_registry(
        monkeypatch, local=True, cloud_profiles=[_cloud_profile()], egress=True
    )
    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    assert [t.provider.origin for t in tiers] == [
        ProviderOrigin.THIS_MAC,
        ProviderOrigin.CLOUD,
    ]


def test_apple_fm_is_never_in_the_routing_ladder(monkeypatch):
    """Apple FM is available on one OS, on recent hardware, behind a
    user setting — so no automatic path may reach it. Enabling the experimental
    integration must not put it back into the ladder, on any configuration.
    """
    import tracker.settings_store as store

    async def apple_on(_session):
        return True

    monkeypatch.setattr(store, "get_apple_fm_enabled", apple_on)

    for local, cloud in ((True, [_cloud_profile()]), (False, []), (True, [])):
        _wire_registry(monkeypatch, local=local, cloud_profiles=cloud, egress=True)
        tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
        assert ProviderOrigin.ON_DEVICE not in [t.provider.origin for t in tiers]


def test_with_only_apple_enabled_routed_work_has_no_backend(monkeypatch):
    """The other half of the same guarantee: turning the experimental
    integration on must not make routed tasks think a backend exists."""
    _wire_registry(monkeypatch, local=False, cloud_profiles=[], egress=False)
    provider = asyncio.run(routing.resolve_provider(object()))
    assert provider.name == "null"
    assert asyncio.run(provider.availability()).state is AvailabilityState.NOT_CONFIGURED


def test_the_local_switch_removes_the_tier_without_removing_the_profile(monkeypatch):
    """A saved profile plus the switch off means NO local tier — which is what
    lets someone who does not run a model server use the app normally."""
    _wire_registry(
        monkeypatch, local=True, cloud_profiles=[], egress=False,
        local_enabled=False,
    )
    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    assert tiers == []

    # Same configuration with the switch on: the tier is back, unchanged.
    _wire_registry(
        monkeypatch, local=True, cloud_profiles=[], egress=False,
        local_enabled=True,
    )
    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    assert [tier.provider.origin for tier in tiers] == [ProviderOrigin.THIS_MAC]
