"""Cloud connection persistence in the local single-user settings database.

Persistence for `tracker.cloud_llm`, the L3 implementation; the transport stays
below and saving a connection lives here.

Every write takes `CLOUD_LLM_WRITE_LOCK_KEY` before reading the whole
state, because the row is a single JSON blob.

The API key is write-only on the wire, so an edit that changes only the model
arrives with `api_key=None` and `update_profile` keeps the stored one. Treating
that as "clear it" would break a working connection the user cannot retype.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.cloud_llm.models import CloudLLMProfile, CloudLLMProfileInput, CloudLLMState
from tracker.intelligence_runtime._profile_keys import ProfilesUnreadable, reseal_raw, with_keys
from tracker.platform.locks import advisory_xact_lock
from tracker.platform.secrets import seal, unseal_or_none
from tracker.settings_store import get_setting_dict, set_setting_dict

CLOUD_LLM_KEY = "cloud_llm_profiles"
CLOUD_LLM_WRITE_LOCK_KEY = 91240


async def _read(session: AsyncSession) -> CloudLLMState:
    value = await get_setting_dict(session, CLOUD_LLM_KEY)
    if value is None:
        return CloudLLMState()
    try:
        return CloudLLMState.model_validate(with_keys(value, unseal_or_none))
    except ValueError as exc:
        raise ProfilesUnreadable(CLOUD_LLM_KEY) from exc


async def get_state(session: AsyncSession) -> CloudLLMState:
    """What can be read; a row that no longer validates reads as no profiles."""
    try:
        return await _read(session)
    except ProfilesUnreadable:
        return CloudLLMState()


async def _save(session: AsyncSession, state: CloudLLMState) -> None:
    await set_setting_dict(session, CLOUD_LLM_KEY, with_keys(state.model_dump(mode="json"), seal))


async def _locked_state(session: AsyncSession) -> CloudLLMState:
    """The state every write builds on: never the empty one an unreadable row
    reads as, which saved back would delete every profile and its key."""
    await advisory_xact_lock(session, CLOUD_LLM_WRITE_LOCK_KEY)
    return await _read(session)


async def reseal(session: AsyncSession) -> None:
    """Seal the keys of the stored row as it stands. On the raw row, not through
    `get_state`: a row that no longer validates reads as no profiles, and
    writing that back would delete them."""
    await advisory_xact_lock(session, CLOUD_LLM_WRITE_LOCK_KEY)
    await reseal_raw(session, CLOUD_LLM_KEY)


async def create_profile(session: AsyncSession, payload: CloudLLMProfileInput) -> CloudLLMProfile:
    state = await _locked_state(session)
    profile = CloudLLMProfile(id=uuid4().hex[:12], **payload.model_dump())
    state.profiles.append(profile)
    await _save(session, state)
    return profile


async def update_profile(session: AsyncSession, profile_id: str, payload: CloudLLMProfileInput) -> CloudLLMProfile | None:
    state = await _locked_state(session)
    for index, current in enumerate(state.profiles):
        if current.id != profile_id:
            continue
        values = payload.model_dump()
        if payload.api_key is None:
            values["api_key"] = current.api_key
        profile = CloudLLMProfile(id=profile_id, **values)
        state.profiles[index] = profile
        await _save(session, state)
        return profile
    return None


async def delete_profile(session: AsyncSession, profile_id: str) -> bool:
    state = await _locked_state(session)
    profiles = [item for item in state.profiles if item.id != profile_id]
    if len(profiles) == len(state.profiles):
        return False
    state.profiles = profiles
    await _save(session, state)
    return True


async def get_profile(session: AsyncSession, profile_id: str) -> CloudLLMProfile | None:
    state = await get_state(session)
    return next((item for item in state.profiles if item.id == profile_id), None)
