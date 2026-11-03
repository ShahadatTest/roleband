"""Every MCP tool a connected app can call has a line on the consent card.

The assistant card in Settings > Intelligence is the only place a user is told
what a connected app may read, fetch and change before they let it connect
(`dashboard/src/features/intelligence/AssistantsCard.tsx`, its words in
`dashboard/src/copy/en/ai.ftl`). Each tool names the card message that covers
it. A new tool, or a tool whose read-only hint changes, fails here until its row
says which line tells the user about it, and that line is on the card.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from tracker.mcp.server import mcp

DASHBOARD = Path(__file__).resolve().parents[2] / "dashboard"
CATALOG = DASHBOARD / "src/copy/en/ai.ftl"
CARD = DASHBOARD / "src/features/intelligence/AssistantsCard.tsx"

ROLES = "ai-assistants-card-shares-role-titles-companies-locations-and-link"
AGE = "ai-assistants-card-shares-pay-level-and-how-long-the-role-has-been"
POSTING = "ai-assistants-card-shares-the-full-posting-when-they-open-one"
PROGRESS = "ai-assistants-card-shares-your-progress-on-roles-stage-priority-no"
PAGES = "ai-assistants-card-shares-public-pages-it-asks-roleband-to-open"
WRITES = "ai-assistants-card-stage-notes-next-action-audited"

#: tool -> (whether it writes, the card message that covers it). None: the tool
#: returns no user data (whether access is on; the recipe schema).
COVERED_BY: dict[str, tuple[bool, str | None]] = {
    "get_server_status": (False, None),
    "get_recipe_contract": (False, None),
    "get_radar_summary": (False, PROGRESS),
    "search_opportunities": (False, ROLES),
    "get_opportunity": (False, POSTING),
    "listing_history": (False, AGE),
    "get_pursuits": (False, PROGRESS),
    "inspect_source": (False, PAGES),
    "validate_recipe": (False, PAGES),
    "save_opportunity": (True, WRITES),
    "update_pursuit": (True, WRITES),
    "save_recipe_draft": (True, WRITES),
}


def _generated_name(message_id: str) -> str:
    """The function `gen:copy` exports for a message id."""
    head, *rest = message_id.split("-")
    return head + "".join(part.capitalize() for part in rest)


def _tools() -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def test_every_tool_is_covered_by_the_table():
    assert sorted(_tools()) == sorted(COVERED_BY)


@pytest.mark.parametrize("name", sorted(COVERED_BY))
def test_a_tool_s_read_only_hint_matches_its_row(name):
    writes, _ = COVERED_BY[name]
    assert _tools()[name].annotations.readOnlyHint is (not writes)


@pytest.mark.parametrize("message_id", sorted({m for _, m in COVERED_BY.values() if m}))
def test_each_covering_line_is_in_the_catalog_and_on_the_card(message_id):
    assert re.search(rf"^{re.escape(message_id)} = ", CATALOG.read_text(), re.M), message_id
    assert _generated_name(message_id) in CARD.read_text(), f"{message_id} is not shown on the card"


def test_a_line_that_is_not_on_the_card_is_caught():
    absent = "ai-assistants-card-shares-a-thing-the-card-never-says"
    assert _generated_name(absent) not in CARD.read_text()
