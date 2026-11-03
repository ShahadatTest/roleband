"""`AGENTS.md` names the gate commands, and `docs/testing.md` owns them.

The agent instructions repeat the most-used commands of the change-scoped gate so
an agent sees them without following a link. A command named there must be one
the gate table in `docs/testing.md` still lists, or the two documents disagree
and an agent runs a check the gate does not list.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENTS = REPO / "AGENTS.md"
TESTING = REPO / "docs" / "testing.md"


def gate_commands(text: str) -> list[str]:
    """The backticked commands in the paragraph that names the gate."""
    start = text.index("change-scoped gate")
    end = text.index("This file owns", start)
    return [c for c in re.findall(r"`([^`]+)`", text[start:end]) if c not in {"backend/", "dashboard/"}]


def gate_table(text: str) -> str:
    start = text.index("## Change-scoped gate")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def missing(agents: str, testing: str) -> list[str]:
    table = gate_table(testing)
    return [c for c in gate_commands(agents) if c not in table]


def test_agents_names_the_gate():
    assert len(gate_commands(AGENTS.read_text())) >= 6


def test_every_gate_command_in_agents_is_in_the_testing_table():
    assert missing(AGENTS.read_text(), TESTING.read_text()) == []


def test_a_command_the_table_dropped_is_named():
    agents = AGENTS.read_text().replace("`.venv/bin/mypy`", "`.venv/bin/pyright`")
    assert missing(agents, TESTING.read_text()) == [".venv/bin/pyright"]
