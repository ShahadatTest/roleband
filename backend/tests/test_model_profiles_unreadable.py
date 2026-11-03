"""A model-profile row that no longer validates is never replaced by a write.

Saved cloud and local connections are one JSON row each, their API keys sealed
inside. When a release narrows what a profile may hold (a provider dropped from
the list), or a restore brings back an older row, reading it shows no profiles,
and a write built on that empty list would delete every saved profile and its
key. Writes refuse instead, the row stays as it was, and the API says why.
"""

from __future__ import annotations

import pytest

from tracker.cloud_llm.models import CloudLLMProfileInput
from tracker.intelligence_runtime import cloud_profiles, local_profiles
from tracker.intelligence_runtime._profile_keys import ProfilesUnreadable
from tracker.local_llm.models import LocalLLMProfileInput
from tracker.platform.secrets import seal
from tracker.settings_store import get_setting_dict, set_setting_dict

pytestmark = pytest.mark.asyncio


def _stale(provider: str, base_url: str = "https://api.example.test/v1") -> dict:
    """A row a later release can no longer read: its provider was dropped."""
    return {"profiles": [{
        "id": "workprofile1", "name": "Work", "provider": provider, "base_url": base_url,
        "model": "large", "enabled": True, "api_key": seal("sk-the-only-copy"),
    }]}


CLOUD_INPUT = CloudLLMProfileInput(name="New", provider="anthropic", base_url="https://api.anthropic.com",
                                   model="claude", api_key="sk-new")
LOCAL_INPUT = LocalLLMProfileInput(name="New", model="qwen")
WRITES = {
    "cloud create": (cloud_profiles, lambda s: cloud_profiles.create_profile(s, CLOUD_INPUT)),
    "cloud update": (cloud_profiles, lambda s: cloud_profiles.update_profile(s, "workprofile1", CLOUD_INPUT)),
    "cloud delete": (cloud_profiles, lambda s: cloud_profiles.delete_profile(s, "other")),
    "local create": (local_profiles, lambda s: local_profiles.create_profile(s, LOCAL_INPUT)),
    "local select": (local_profiles, lambda s: local_profiles.select_profile(s, "workprofile1")),
    "local enable": (local_profiles, lambda s: local_profiles.set_enabled(s, True)),
}


def _key(store) -> str:
    return cloud_profiles.CLOUD_LLM_KEY if store is cloud_profiles else local_profiles.LOCAL_LLM_KEY


@pytest.mark.parametrize("name", sorted(WRITES))
async def test_a_write_refuses_and_leaves_the_stored_row_as_it_was(db_session, name):
    store, write = WRITES[name]
    stored = _stale("retired-provider")
    await set_setting_dict(db_session, _key(store), stored)
    await db_session.commit()

    with pytest.raises(ProfilesUnreadable):
        await write(db_session)
    await db_session.rollback()

    assert await get_setting_dict(db_session, _key(store)) == stored
    assert (await store.get_state(db_session)).profiles == [], "reading still shows nothing it cannot read"


async def test_the_api_names_the_refusal_and_changes_nothing(api_client, db_session):
    stored = _stale("retired-provider")
    await set_setting_dict(db_session, cloud_profiles.CLOUD_LLM_KEY, stored)
    await db_session.commit()

    response = await api_client.post("/api/intelligence/cloud-models", json=CLOUD_INPUT.model_dump())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "model-profiles-unreadable"
    assert await get_setting_dict(db_session, cloud_profiles.CLOUD_LLM_KEY) == stored
    assert (await api_client.get("/api/intelligence/cloud-models")).status_code == 200


async def test_a_readable_row_still_takes_writes(db_session):
    await set_setting_dict(db_session, cloud_profiles.CLOUD_LLM_KEY, _stale("anthropic", "https://api.anthropic.com"))
    await db_session.commit()

    await cloud_profiles.create_profile(db_session, CLOUD_INPUT)

    assert [p.name for p in (await cloud_profiles.get_state(db_session)).profiles] == ["Work", "New"]
