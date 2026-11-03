"""Key conversion for raw model-profile rows, without validating away stored data."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.platform.secrets import seal
from tracker.settings_store import get_setting_dict, set_setting_dict


class ProfilesUnreadable(Exception):
    """The stored profiles no longer validate (a narrowed schema, a restored row).

    A write built on what could be read would replace every saved profile, and
    its sealed key, with nothing; the stores refuse it instead.
    """


def with_keys(value: dict, convert: Callable[[str | None], str | None]) -> dict:
    profiles = value.get("profiles")
    if not isinstance(profiles, list):
        return value
    return {
        **value,
        "profiles": [
            {**profile, "api_key": convert(profile.get("api_key"))}
            if isinstance(profile, dict) and isinstance(profile.get("api_key"), str) else profile
            for profile in profiles
        ],
    }


async def reseal_raw(session: AsyncSession, key: str) -> None:
    """The caller holds its store's write lock before reading this raw row.

    Typed validation can reject profiles with unsupported fields or values;
    resealing preserves those profiles and every unrelated field.
    """
    value = await get_setting_dict(session, key)
    if value is not None:
        await set_setting_dict(session, key, with_keys(value, seal))
