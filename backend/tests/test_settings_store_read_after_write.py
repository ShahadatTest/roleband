"""A setting read after a write in the same session is the value just written.

Every getter in `settings_store` reads through `session.get`, which answers
from the session's identity map, and sessions keep objects across commits
(`expire_on_commit=False`). A session that already holds a setting's row (a
route that read it before saving, the run's writer that loaded the scope at
its start) keeps that instance in the map, so an upsert that does not update it
leaves every later read in that session on the old value. The tests hold the
row the way such a session does; without the hold, a row nobody references
leaves the map on its own and the old value would never be served.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tracker import settings_store as store
from tracker.db.models import AppSetting


async def _repeat_hours(session: AsyncSession) -> int:
    return (await store.get_schedule_plan_settings(session)).repeat_hours


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "write", "read", "first", "second"),
    [
        (
            store.LOCALE_KEY,
            lambda s, v: store.set_locale(s, *v),
            store.get_locale,
            ("en", None),
            ("sv", "SE"),
        ),
        (
            store.INCLUDE_UNSTATED_LEVEL_KEY,
            store.set_include_unstated_level,
            store.get_include_unstated_level,
            True,
            False,
        ),
        (
            store.EXCLUDED_DOMAINS_KEY,
            store.set_excluded_domains,
            store.get_excluded_domains,
            ["advertising"],
            ["ai_ml", "advertising"],
        ),
        (
            store.ENABLED_BANDS_KEY,
            store.set_enabled_bands,
            store.get_enabled_bands,
            ["staff"],
            ["staff", "principal"],
        ),
        (
            store.SCHEDULE_PLAN_KEY,
            lambda s, v: store.set_schedule_plan_settings(s, store.SchedulePlanSettings(repeat_hours=v)),
            _repeat_hours,
            3,
            12,
        ),
    ],
    ids=["locale", "unstated_level", "excluded_subjects", "bands", "schedule_plan"],
)
async def test_get_set_get_in_one_session_returns_the_new_value(
    db_session: AsyncSession,
    key: str,
    write: Callable[[AsyncSession, Any], Awaitable[Any]],
    read: Callable[[AsyncSession], Awaitable[Any]],
    first: Any,
    second: Any,
) -> None:
    await write(db_session, first)
    await db_session.commit()
    held = await db_session.get(AppSetting, key)
    assert held is not None

    before = await read(db_session)
    await write(db_session, second)
    after = await read(db_session)

    assert after != before, "the read after the write must not be the value before it"
    await db_session.commit()
    async with async_sessionmaker(db_session.bind, expire_on_commit=False)() as fresh:
        assert after == await read(fresh), "and it is the value a fresh session reads"
    assert held.value == (await db_session.get(AppSetting, key)).value


@pytest.mark.asyncio
async def test_a_settings_put_answers_the_value_it_just_saved(api_client, db_session) -> None:
    """`PUT /api/settings/retention` saves, commits, and answers from a read of
    the same setting. The request's session holds the row from before the
    save, as it does whenever something earlier in the request read it."""
    from tracker.api.app import app
    from tracker.api.deps import get_session

    await store.set_retention_days(db_session, 30)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    held_at_start: list[object] = []

    async def holding_session():
        async with factory() as session:
            held = await session.get(AppSetting, store.RETENTION_KEY)
            assert held is not None
            held_at_start.append(dict(held.value))
            yield session

    app.dependency_overrides[get_session] = holding_session
    response = await api_client.put("/api/settings/retention", json={"days": 90})

    assert held_at_start == [{"days": 30}], "the request's session held the row from before the save"
    assert response.status_code == 200, response.text
    assert response.json()["days"] == 90
    assert (await api_client.get("/api/settings/retention")).json()["days"] == 90
