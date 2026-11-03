"""Validated agent/MCP configuration persisted in `app_settings`."""

from __future__ import annotations

from pydantic import BaseModel, StrictBool
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AppSetting

AGENT_ACCESS_KEY = "agent_access"


class AgentAccessConfig(BaseModel):
    enabled: StrictBool = False
    allow_writes: StrictBool = False


async def get_agent_access(session: AsyncSession) -> AgentAccessConfig:
    row = await session.get(AppSetting, AGENT_ACCESS_KEY)
    if row is None or not isinstance(row.value, dict):
        return AgentAccessConfig()
    try:
        return AgentAccessConfig.model_validate(row.value)
    except ValueError:
        return AgentAccessConfig()


async def set_agent_access(
    session: AsyncSession, config: AgentAccessConfig
) -> AgentAccessConfig:
    value = config.model_dump(mode="json")
    stmt = insert(AppSetting).values(key=AGENT_ACCESS_KEY, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppSetting.key], set_={"value": value}
    )
    await session.execute(stmt)
    return config
