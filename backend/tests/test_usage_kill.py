"""The environment can only turn usage sharing off (docs/architecture.md).

Each switch is checked on its own, from the environment and from `backend/.env`
(launchd agents read only that), and a "false" spelling never counts as on.
Whether a switch beats a stored consent end to end is `test_usage_consent`'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tracker.usage_stats.kill import PRODUCT_SWITCH, SWITCHES, blocked_by

pytestmark = pytest.mark.usefixtures("no_escape")


@pytest.mark.parametrize("name", SWITCHES)
@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "on"])
def test_each_switch_turns_sharing_off(tmp_path: Path, name: str, value: str) -> None:
    assert blocked_by({name: value}, tmp_path / "none.env") == name


@pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "off"])
def test_a_false_spelling_is_not_a_switch(tmp_path: Path, value: str) -> None:
    assert blocked_by({name: value for name in SWITCHES}, tmp_path / "none.env") is None


def test_nothing_set_lets_sharing_proceed(tmp_path: Path) -> None:
    assert blocked_by({}, tmp_path / "none.env") is None


def test_the_env_file_counts_for_agents_launchd_starts(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f'ROLEBAND_PGDATA=/x\n{PRODUCT_SWITCH}="1"\n')
    assert blocked_by({}, env_file) == PRODUCT_SWITCH
    env_file.write_text("DO_NOT_TRACK=0\n")
    assert blocked_by({}, env_file) is None
