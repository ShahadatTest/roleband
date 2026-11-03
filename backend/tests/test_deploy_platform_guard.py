"""The launchd scripts refuse to run off macOS, before they touch anything.

The macOS installer runs the supervisor as one launchd item, so `deploy/install.sh`
and `deploy/uninstall.sh` are macOS-only. Unguarded, off macOS they would run until
they hit `launchctl`, after creating `data/` and `~/Library/LaunchAgents`, and,
for install, after `npm ci`, a pip install and a model download, leaving a
half-install and a `command not found` to explain it. They stop first and name
what does work on Linux.

Each script runs from a COPY in a scratch checkout, with `uname` stubbed and
every tool it would act through replaced by a recorder. That keeps a red run
safe: without the guard these scripts really do
bootstrap the supervisor and rebuild the dashboard.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ["install.sh", "uninstall.sh"]
ACTORS = ["launchctl", "npm", "sed", "curl"]


@pytest.fixture
def sandbox(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "deploy").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy2(ROOT / "deploy" / name, checkout / "deploy" / name)
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "calls.log"

    def stub(name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    for tool in ACTORS:
        # `launchctl print` answering "not loaded" keeps install.sh's unload
        # wait loop from spinning its full ten seconds per agent.
        stub(tool, f'echo "{tool} $*" >> "{record}"; [ "$1" = print ] && exit 1; exit 0')

    def run(script: str, kernel: str) -> subprocess.CompletedProcess:
        stub("uname", f"echo {kernel}")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home)}
        return subprocess.run(
            ["bash", str(checkout / "deploy" / script)],
            env=env, capture_output=True, text=True, timeout=60,
        )

    return run, record, home, checkout


@pytest.mark.parametrize("script", SCRIPTS)
def test_off_macos_a_launchd_script_stops_before_touching_anything(sandbox, script):
    run, record, home, checkout = sandbox
    proc = run(script, "Linux")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "macOS only" in proc.stderr
    assert "setup.sh" in proc.stderr, "the refusal names what works on Linux"
    assert not record.exists(), f"acted before refusing: {record.read_text()}"
    assert not (home / "Library").exists()
    assert not (checkout / "data").exists()


def test_on_macos_install_goes_past_the_guard(sandbox):
    """The control: a guard that refused everywhere would pass the test above."""
    run, record, home, checkout = sandbox
    venv_python = checkout / "backend" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)
    run("install.sh", "Darwin")
    assert record.exists() and "launchctl bootstrap" in record.read_text()
    assert (home / "Library" / "LaunchAgents").is_dir()
