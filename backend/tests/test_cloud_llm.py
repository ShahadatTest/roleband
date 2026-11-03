"""Cloud profiles enforce HTTPS/private-host boundaries and redact credentials."""

import asyncio

import pytest

from tracker.cloud_llm.models import CloudLLMProfile, CloudLLMProfileInput
from tracker.intelligence_runtime import cloud_profiles as store


def test_cloud_profile_rejects_insecure_and_private_destinations():
    base = dict(name="Provider", provider="openai", model="model", enabled=False)
    with pytest.raises(ValueError, match="https"):
        CloudLLMProfileInput(**base, base_url="http://api.example.com/v1")
    with pytest.raises(ValueError, match="localhost"):
        CloudLLMProfileInput(**base, base_url="https://localhost/v1")
    with pytest.raises(ValueError, match="private IP"):
        CloudLLMProfileInput(**base, base_url="https://127.0.0.1/v1")


def test_cloud_profile_public_shape_is_write_only_for_key():
    profile = CloudLLMProfile(
        id="profile12345",
        name="OpenAI",
        provider="openai",
        base_url="https://api.openai.com/v1/",
        model="gpt-test",
        enabled=True,
        api_key="super-secret",
    )

    assert profile.base_url == "https://api.openai.com/v1"
    assert profile.public()["has_api_key"] is True
    assert "api_key" not in profile.public()
    assert "super-secret" not in str(profile.public())


def test_cloud_profile_update_serializes_before_reading_whole_state(monkeypatch):
    current = CloudLLMProfile(
        id="profile12345",
        name="OpenAI",
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-test",
        enabled=False,
        api_key="secret",
    )
    state = store.CloudLLMState(profiles=[current])
    events = []

    async def fake_lock(_, key):
        events.append(("lock", key))

    async def fake_state(_):
        events.append(("read", None))
        return state

    async def fake_save(_, __):
        events.append(("save", None))

    monkeypatch.setattr(store, "advisory_xact_lock", fake_lock, raising=False)
    monkeypatch.setattr(store, "_read", fake_state)
    monkeypatch.setattr(store, "_save", fake_save)
    payload = CloudLLMProfileInput(
        name=current.name,
        provider=current.provider,
        base_url=current.base_url,
        model=current.model,
        enabled=True,
        api_key=None,
    )

    updated = asyncio.run(store.update_profile(object(), current.id, payload))

    assert events[0] == ("lock", store.CLOUD_LLM_WRITE_LOCK_KEY)
    assert events[1][0] == "read"
    # The key is write-only on the wire (see the `public()` test above), so an
    # edit that changes only the model arrives with `api_key=None`. Treating that
    # as "clear it" would silently break a working connection, and the user has
    # no way to retype a key they cannot read back.
    assert updated is not None
    assert updated.api_key == "secret"
    assert updated.enabled is True
