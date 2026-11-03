"""Agent access, the MCP surface's shape, and pursuit write contracts.

What the tool bodies DO is `test_mcp_tools.py`; this file holds the
surface itself: the two access gates round-tripping through the settings store,
the connection block Settings copies, and that the tool list
Settings publishes is the server's own registered surface rather than a copy of
it that has drifted.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

import tracker.mcp.server as server
from tracker.agents.config import (
    AGENT_ACCESS_KEY,
    AgentAccessConfig,
    get_agent_access,
    set_agent_access,
)
from tracker.agents.pursuits import ROLE_WRITE_LOCK_NAMESPACE, PursuitUpdate, upsert_pursuit
from tracker.api.routers.intelligence import _agent_connection_state
from tracker.db.models import AppSetting, Favorite, Job, Pursuit, PursuitEvent
from tracker.mcp.server import mcp

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


class ConfigSession:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    async def get(self, model, key):
        assert model is AppSetting and key == AGENT_ACCESS_KEY
        return self.row

    async def execute(self, stmt):
        self.executed.append(stmt)


def test_agent_access_defaults_off_and_round_trips_both_gates():
    assert asyncio.run(get_agent_access(ConfigSession())) == AgentAccessConfig(
        enabled=False, allow_writes=False
    )
    damaged = ConfigSession(AppSetting(key=AGENT_ACCESS_KEY, value={"enabled": "yes"}))
    assert asyncio.run(get_agent_access(damaged)) == AgentAccessConfig()

    session = ConfigSession()
    saved = asyncio.run(set_agent_access(session, AgentAccessConfig(enabled=True, allow_writes=True)))
    assert saved.allow_writes is True
    assert session.executed[0].compile().params["value"] == {
        "enabled": True,
        "allow_writes": True,
    }


def test_agent_connection_state_is_copy_ready_and_never_contains_credentials():
    state = _agent_connection_state(AgentAccessConfig(enabled=True, allow_writes=False))

    assert state["transport"] == "stdio"
    assert state["args"] == ["-m", "tracker.mcp.server"]
    assert "codex mcp add roleband --" in state["codex_command"]
    assert state["claude_json"]["mcpServers"]["roleband"]["command"] == state["command"]
    assert {tool["access"] for tool in state["tools"]} == {"status", "read", "write"}
    assert "api_key" not in str(state).lower()


def _gated_access() -> dict[str, str]:
    """What the server ACTUALLY gates each tool with, read from its own source.

    A tool body opens with `await _access(write=True)` (a write), `await
    _access()` (a read), or neither (`get_server_status`, which must answer
    while access is off so the user can see that it is). Derived rather than
    listed, because a hand-written expectation beside a hand-written router list
    is the same duplicate twice.
    """
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    gated: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if not any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        ):
            continue
        calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_access"
        ]
        writes = any(
            keyword.arg == "write" and keyword.value.value is True
            for call in calls
            for keyword in call.keywords
        )
        gated[node.name] = "write" if writes else ("read" if calls else "status")
    return gated


def test_the_settings_tool_list_is_the_servers_own_surface():
    """`_agent_connection_state` lists the tools and their access
    class, and Settings shows that list as what the agent can do. Untied to the
    decorators, a tool added, renamed or moved between gates would change the
    server and leave the screen describing a stale surface.

    Both columns are checked. The name set alone would not notice
    `save_opportunity` being advertised as a read.
    """
    published = {tool["name"]: tool["access"] for tool in _agent_connection_state(
        AgentAccessConfig(enabled=True, allow_writes=True)
    )["tools"]}
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert set(published) == registered
    assert published == _gated_access()


def test_mcp_exposes_narrow_read_and_pursuit_write_surface():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    assert set(tools) == {
        "get_server_status",
        "get_radar_summary",
        "search_opportunities",
        "get_opportunity",
        "listing_history",
        "get_pursuits",
        "save_opportunity",
        "update_pursuit",
        # Recipe authoring: write-free except the confirmed draft.
        "get_recipe_contract",
        "inspect_source",
        "validate_recipe",
        "save_recipe_draft",
    }
    assert tools["search_opportunities"].annotations.readOnlyHint is True
    assert tools["validate_recipe"].annotations.readOnlyHint is True
    assert tools["save_recipe_draft"].annotations.readOnlyHint is False
    assert tools["update_pursuit"].annotations.readOnlyHint is False
    assert tools["update_pursuit"].annotations.destructiveHint is False


class PursuitSession:
    def __init__(self, job: Job):
        self.job = job
        self.pursuit = None
        self.favorite = None
        self.added = []
        self.locks = []

    async def execute(self, stmt, params=None):
        # The only statement the writer runs through `execute`: its lock.
        assert "pg_advisory_xact_lock" in str(stmt)
        self.locks.append(params)

    async def get(self, model, key):
        assert model is Job and key == self.job.id
        return self.job

    async def scalar(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is Pursuit:
            return self.pursuit
        if entity is Favorite:
            return self.favorite
        raise AssertionError(f"unexpected scalar entity {entity}")

    def add(self, value):
        self.added.append(value)
        if isinstance(value, Pursuit):
            value.id = 7
            value.created_at = value.updated_at = datetime.now(UTC)
            self.pursuit = value
        elif isinstance(value, Favorite):
            self.favorite = value

    async def flush(self):
        pass


def test_agent_pursuit_write_saves_job_and_appends_auditable_event():
    job = Job(
        id=101, company="openai", req_id="r1", dedupe_key="openai:r1", title="Staff PM",
        url="https://example.test/job", locations=["SF"], location_groups=["silicon_valley"],
        level_band="staff", track="product_program", status="open", in_scope=True,
        first_seen=datetime.now(UTC), last_seen=datetime.now(UTC),
    )
    session = PursuitSession(job)

    pursuit = asyncio.run(
        upsert_pursuit(
            session,
            101,
            PursuitUpdate(stage="applied", priority=1, next_action="Email recruiter"),
            actor="agent",
        )
    )

    assert pursuit.stage == "applied" and pursuit.priority == 1
    assert session.favorite.job_id == 101
    # Serialized per job across clients.
    assert {"ns": ROLE_WRITE_LOCK_NAMESPACE, "k": 101} in session.locks
    event = next(value for value in session.added if isinstance(value, PursuitEvent))
    assert event.actor == "agent" and event.event_type == "created"
    assert event.to_stage == "applied"
    assert event.detail["changed"] == ["next_action", "priority", "stage"]
