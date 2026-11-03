"""`app_settings.local_llm_profiles` persistence; one row, multiple named profiles.

Persistence for `tracker.local_llm`, which is the L3 implementation: the oMLX
client, the models and the server control. Saving a profile is store work, so it
lives here in the service tier while the transport stays below.

Every write takes `LOCAL_LLM_WRITE_LOCK_KEY` before reading the whole
state. The row is a single JSON blob, so a read-modify-write that does not
serialize loses concurrent edits.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.intelligence_runtime._profile_keys import ProfilesUnreadable, reseal_raw, with_keys
from tracker.local_llm.models import LocalLLMProfile, LocalLLMProfileInput, LocalLLMState
from tracker.platform.locks import advisory_xact_lock
from tracker.platform.secrets import seal, unseal_or_none
from tracker.settings_store import get_setting_dict, set_setting_dict

LOCAL_LLM_KEY = "local_llm_profiles"
LOCAL_LLM_WRITE_LOCK_KEY = 91239


async def _read(session: AsyncSession) -> LocalLLMState:
    value = await get_setting_dict(session, LOCAL_LLM_KEY)
    if value is None:
        return LocalLLMState()
    try:
        return LocalLLMState.model_validate(with_keys(value, unseal_or_none))
    except ValueError as exc:
        raise ProfilesUnreadable(LOCAL_LLM_KEY) from exc


async def get_state(session: AsyncSession) -> LocalLLMState:
    """What can be read; a row that no longer validates reads as no profiles."""
    try:
        return await _read(session)
    except ProfilesUnreadable:
        return LocalLLMState()


async def _save(session: AsyncSession, state: LocalLLMState) -> None:
    await set_setting_dict(session, LOCAL_LLM_KEY, with_keys(state.model_dump(mode="json"), seal))


async def _locked_state(session: AsyncSession) -> LocalLLMState:
    """The state every write builds on: never the empty one an unreadable row
    reads as, which saved back would delete every profile and its key."""
    await advisory_xact_lock(session, LOCAL_LLM_WRITE_LOCK_KEY)
    return await _read(session)


async def reseal(session: AsyncSession) -> None:
    """Seal the keys of the stored row as it stands. On the raw row, not through
    `get_state`: a row that no longer validates reads as no profiles, and
    writing that back would delete them."""
    await advisory_xact_lock(session, LOCAL_LLM_WRITE_LOCK_KEY)
    await reseal_raw(session, LOCAL_LLM_KEY)


async def create_profile(
    session: AsyncSession, payload: LocalLLMProfileInput
) -> LocalLLMProfile:
    state = await _locked_state(session)
    profile = LocalLLMProfile(id=uuid4().hex[:12], **payload.model_dump())
    state.profiles.append(profile)
    if state.active_profile_id is None:
        state.active_profile_id = profile.id
    await _save(session, state)
    return profile


async def update_profile(
    session: AsyncSession, profile_id: str, payload: LocalLLMProfileInput
) -> LocalLLMProfile | None:
    state = await _locked_state(session)
    for index, current in enumerate(state.profiles):
        if current.id != profile_id:
            continue
        values = payload.model_dump()
        if payload.api_key is None:
            values["api_key"] = current.api_key
        profile = LocalLLMProfile(id=profile_id, **values)
        state.profiles[index] = profile
        await _save(session, state)
        return profile
    return None


async def delete_profile(session: AsyncSession, profile_id: str) -> bool:
    state = await _locked_state(session)
    kept = [profile for profile in state.profiles if profile.id != profile_id]
    if len(kept) == len(state.profiles):
        return False
    state.profiles = kept
    if state.active_profile_id == profile_id:
        state.active_profile_id = kept[0].id if kept else None
    await _save(session, state)
    return True


async def select_profile(session: AsyncSession, profile_id: str) -> LocalLLMProfile | None:
    state = await _locked_state(session)
    profile = next((item for item in state.profiles if item.id == profile_id), None)
    if profile is None:
        return None
    state.active_profile_id = profile_id
    await _save(session, state)
    return profile


async def set_enabled(session: AsyncSession, enabled: bool) -> bool:
    """Turn the whole local tier on or off, keeping every saved profile.

    Deliberately separate from `select_profile`: "which server do I use" and
    "do I use one at all" are different questions, and answering the second
    must not mean deleting the profile.
    """
    state = await _locked_state(session)
    state.enabled = bool(enabled)
    await _save(session, state)
    return state.enabled


async def get_enabled(session: AsyncSession) -> bool:
    return (await get_state(session)).enabled


async def get_profile(session: AsyncSession, profile_id: str) -> LocalLLMProfile | None:
    state = await get_state(session)
    return next((item for item in state.profiles if item.id == profile_id), None)


async def get_active_profile(session: AsyncSession) -> LocalLLMProfile | None:
    state = await get_state(session)
    if state.active_profile_id:
        selected = next(
            (item for item in state.profiles if item.id == state.active_profile_id), None
        )
        if selected is not None:
            return selected
    return state.profiles[0] if state.profiles else None
