"""The local tier's on/off switch and oMLX server control.

Two user-visible promises are pinned here: RoleBand works for someone who does
not have oMLX (the tier can be switched off without deleting the profile, and
nothing tries to reach a server that isn't there), and a control we offer is
one we can actually perform (never claim to start a server we don't manage).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tracker.api.routers import intelligence as intel_router
from tracker.intelligence_runtime import local_profiles as store
from tracker.intelligence_runtime import routing
from tracker.local_llm import server
from tracker.local_llm.models import LocalLLMProfile, LocalLLMState

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


def _profile(provider: str = "omlx") -> LocalLLMProfile:
    return LocalLLMProfile(
        id="localprofile1",
        name="Local Qwen",
        provider=provider,
        base_url="http://127.0.0.1:8000/v1",
        model="Qwen3.5-9B-MLX-4bit",
        api_key=None,
    )


# --------------------------------------------------------------------------- #
# The switch
# --------------------------------------------------------------------------- #


def test_local_tier_defaults_to_enabled_so_existing_installs_keep_their_model():
    assert LocalLLMState().enabled is True
    assert LocalLLMState(profiles=[_profile()]).public()["enabled"] is True


def test_set_enabled_round_trips_without_touching_profiles(monkeypatch):
    state = LocalLLMState(active_profile_id="localprofile1", profiles=[_profile()])
    saved = []

    async def fake_state(_):
        return state

    async def fake_save(_, value):
        saved.append(value)

    async def fake_lock(*_):
        return None

    monkeypatch.setattr(store, "_read", fake_state)
    monkeypatch.setattr(store, "_save", fake_save)
    monkeypatch.setattr(store, "advisory_xact_lock", fake_lock)

    assert asyncio.run(store.set_enabled(object(), False)) is False
    # Switching the local tier off preserves its profile so it can be
    # enabled again without reconstructing the configuration.
    assert saved[-1].profiles[0].model == "Qwen3.5-9B-MLX-4bit"
    assert saved[-1].active_profile_id == "localprofile1"
    assert saved[-1].enabled is False


@pytest.mark.parametrize("enabled,expected_tiers", [(True, 1), (False, 0)])
def test_registry_offers_the_local_tier_only_when_switched_on(
    monkeypatch, enabled, expected_tiers
):
    async def fake_measure(session, *, task_type):
        return {}

    async def fake_egress(_):
        return False

    async def fake_cloud(_):
        return SimpleNamespace(profiles=[])

    async def fake_active(_):
        return _profile()

    async def fake_enabled(_):
        return enabled

    monkeypatch.setattr(routing, "measure_tiers", fake_measure)
    monkeypatch.setattr(routing, "get_ai_egress_enabled", fake_egress)
    monkeypatch.setattr(routing, "get_cloud_state", fake_cloud)
    monkeypatch.setattr(routing, "get_active_local_profile", fake_active)
    monkeypatch.setattr(routing, "get_local_enabled", fake_enabled)

    tiers = asyncio.run(routing.build_tiers(object(), task_type="disclosed_comp"))
    assert len(tiers) == expected_tiers


def test_switched_off_with_nothing_else_configured_reports_turned_off(monkeypatch):
    """The no-backend path must stay a clean, explainable no-op — that is what
    lets a user without oMLX run the app at all."""

    async def no_tiers(session, *, task_type):
        return []

    monkeypatch.setattr(routing, "build_tiers", no_tiers)
    provider = asyncio.run(routing.resolve_provider(object(), task_type="disclosed_comp"))
    availability = asyncio.run(provider.availability())
    assert availability.ok is False
    assert provider.name == "null"


# --------------------------------------------------------------------------- #
# Server control
# --------------------------------------------------------------------------- #


def test_control_without_the_binary_is_a_reported_state_not_an_exception(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: None)
    result = asyncio.run(server.control("start"))
    assert result.ok is False
    assert "not installed" in result.detail.lower()


def test_control_refuses_an_unsupported_action(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: "/opt/homebrew/bin/omlx")
    result = asyncio.run(server.control("launch"))  # type: ignore[arg-type]
    assert result.ok is False


def test_control_runs_a_fixed_argv_with_no_shell(monkeypatch):
    """Injection surface pin: the command is the resolved binary plus a literal
    action, and nothing a profile holds can reach it."""
    seen = {}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return (b"oMLX server running on port 8000", b"")

    async def fake_exec(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(server.shutil, "which", lambda _: "/opt/homebrew/bin/omlx")
    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", fake_exec)

    result = asyncio.run(server.control("start"))
    assert result.ok is True
    assert seen["args"] == ("/opt/homebrew/bin/omlx", "start")
    assert "shell" not in seen["kwargs"]


def test_control_reports_a_nonzero_exit_as_failure(monkeypatch):
    class _Proc:
        returncode = 1

        async def communicate(self):
            return (b"port already in use", b"")

    async def fake_exec(*args, **kwargs):
        return _Proc()

    monkeypatch.setattr(server.shutil, "which", lambda _: "/opt/homebrew/bin/omlx")
    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", fake_exec)

    result = asyncio.run(server.control("stop"))
    assert result.ok is False
    assert "port already in use" in result.detail


# --------------------------------------------------------------------------- #
# Status endpoint
# --------------------------------------------------------------------------- #


class _Session:
    new = dirty = deleted = ()

    async def commit(self):
        pass


def _status(monkeypatch, *, state: LocalLLMState, binary: str | None, reachable: bool):
    async def fake_state(_):
        return state

    class _Avail:
        def __init__(self):
            self.state = SimpleNamespace(value="available" if reachable else "server_unreachable")
            self.ok = reachable
            self.detail = None

    class _Provider:
        def __init__(self, profile):
            self.profile = profile

        async def availability(self):
            return _Avail()

    monkeypatch.setattr(intel_router, "get_local_llm_state", fake_state)
    monkeypatch.setattr(intel_router, "omlx_binary_path", lambda: binary)
    monkeypatch.setattr(intel_router, "LocalLLMProvider", _Provider)
    return asyncio.run(intel_router._local_server_status(_Session()))


def test_status_without_omlx_installed_explains_the_app_still_works(monkeypatch):
    status = _status(
        monkeypatch,
        state=LocalLLMState(active_profile_id="localprofile1", profiles=[_profile()]),
        binary=None,
        reachable=False,
    )
    assert status["installed"] is False
    assert status["managed"] is False  # we must not offer Start we cannot run
    assert "works without it" in status["detail"]


def test_status_for_a_non_omlx_server_is_unmanaged(monkeypatch):
    status = _status(
        monkeypatch,
        state=LocalLLMState(
            active_profile_id="localprofile1", profiles=[_profile("openai_compatible")]
        ),
        binary="/opt/homebrew/bin/omlx",
        reachable=True,
    )
    assert status["installed"] is True
    assert status["managed"] is False
    assert "oMLX" in status["detail"]
    # Reachability is still reported — it is running, just not ours to stop.
    assert status["reachable"] is True


def test_status_with_no_profile_is_not_configured(monkeypatch):
    status = _status(monkeypatch, state=LocalLLMState(), binary=None, reachable=False)
    assert status["state"] == "not_configured"
    assert status["managed"] is False
    assert status["model"] is None


def test_status_reports_managed_and_reachable_when_running(monkeypatch):
    status = _status(
        monkeypatch,
        state=LocalLLMState(active_profile_id="localprofile1", profiles=[_profile()]),
        binary="/opt/homebrew/bin/omlx",
        reachable=True,
    )
    assert (status["installed"], status["managed"], status["reachable"]) == (True, True, True)
    assert status["model"] == "Qwen3.5-9B-MLX-4bit"
    assert status["enabled"] is True


def test_status_probe_failure_never_raises(monkeypatch):
    async def fake_state(_):
        return LocalLLMState(active_profile_id="localprofile1", profiles=[_profile()])

    class _Provider:
        def __init__(self, profile):
            pass

        async def availability(self):
            raise RuntimeError("socket exploded")

    monkeypatch.setattr(intel_router, "get_local_llm_state", fake_state)
    monkeypatch.setattr(intel_router, "omlx_binary_path", lambda: "/opt/homebrew/bin/omlx")
    monkeypatch.setattr(intel_router, "LocalLLMProvider", _Provider)

    status = asyncio.run(intel_router._local_server_status(_Session()))
    assert status["reachable"] is False
    assert status["state"] == "server_unreachable"


def test_analyze_endpoint_refuses_while_local_models_are_switched_off(monkeypatch):
    """An explicit user action on the local model must SAY it is off, not
    quietly run the model the user turned off."""
    from fastapi import HTTPException

    from tracker.api.routers import lineage as lineage_router

    async def off(_):
        return False

    monkeypatch.setattr(lineage_router, "get_local_llm_enabled", off)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            lineage_router._analyze_relationship_candidate(
                _Session(), link=object(), prior=object(), newer=object(),
                proposal_kind="duplicate",
            )
        )
    assert excinfo.value.status_code == 409
    assert "turned off" in excinfo.value.detail["message"]
