"""The template, installed for real, runs end to end.

Builds the plugin's own venv (`install.build_venv`: the SDK from this checkout
and the template, under the core constraints file), then runs `refresh` with
that venv's interpreter and no extra import path: what the host will run on a
user's machine. pip needs the package index, so this is opt-in locally, like
the upgrade rehearsal, and always runs in CI.

    ROLEBAND_PLUGIN_E2E=1 .venv/bin/python -m pytest tests/test_plugin_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from tests import skip_policy
from tests.plugin_web import TEMPLATE, Web, plugin_levels, seed_plugin_companies
from tracker.platform.ratelimit import RateLimiter
from tracker.plugins import store
from tracker.plugins.host import HostConfig, run_job
from tracker.plugins.install import approval_text, install

#: Captured before `no_escape` refuses them: building the venv runs pip, and the
#: run starts the runner from it. Nothing else may start a process.
REAL_POPEN = subprocess.Popen
REAL_SPAWN = asyncio.create_subprocess_exec

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("no_escape"),
    pytest.mark.skipif(
        not (skip_policy.enforced() or os.environ.get("ROLEBAND_PLUGIN_E2E") == "1"),
        reason="the plugin end-to-end test builds a venv with pip; set ROLEBAND_PLUGIN_E2E=1 to run it "
        "locally. CI sets ROLEBAND_REQUIRE_INTEGRATION=1, where it always runs.",
    ),
]


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_the_installed_template_runs_from_its_own_venv(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)  # pip, for the venv only
    await seed_plugin_companies(db_session)
    row, _ = await install(db_session, TEMPLATE, plugins_dir=tmp_path / "plugins", venv=True)
    await store.approve(db_session, row.plugin_id, shown=approval_text(row.manifest))
    await store.set_enabled(db_session, row.plugin_id, True)
    await db_session.commit()
    home = tmp_path / "plugins" / row.plugin_id
    config = HostConfig(python=str(home / "venv" / "bin" / "python"), data_dir=home / "data",
                        client=Web().client(), limiter=RateLimiter(2.0, sleep=_no_sleep), spawn=REAL_SPAWN)
    result = await run_job(db_session, row.plugin_id, "refresh", trigger="cli", config=config)
    assert result.outcome == "clean", (result.message, result.stderr)
    assert [r.level_label for r in await plugin_levels(db_session)] == ["E3", "E4", "E5"]
