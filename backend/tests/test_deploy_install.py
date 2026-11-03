"""`deploy/install.sh` and `deploy/uninstall.sh`, run for real against recorders.

Install registers exactly one background item, `com.roleband`, rendered with the
checkout's path. Uninstall stops the jobs before it removes the item, and touches
no other label.

Each script runs from a copy of `deploy/` in a scratch checkout with HOME in
the scratch root. `launchctl`, `npm`, `curl` and `uname` are recorders, and the
venv's python records every command. Nothing reaches launchd, the network or a
database.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sandbox(tmp_path):
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT / "deploy", checkout / "deploy")
    (checkout / "data").mkdir()
    venv = checkout / "backend" / ".venv" / "bin"
    venv.mkdir(parents=True)
    home = tmp_path / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "calls.log"

    def stub(path: Path, body: str) -> None:
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    for tool in ("launchctl", "npm", "curl"):
        # `launchctl print` answering "not loaded" keeps the unload wait short.
        stub(bin_dir / tool, f'echo "{tool} $*" >> "{record}"; [ "$1" = print ] && exit 1; exit 0')
    stub(bin_dir / "uname", "echo Darwin")
    stub(venv / "python", f'''case "$1" in
  -m) echo "python $*" >> "{record}"; exit 0 ;;
  -) echo "python -" >> "{record}"; cat >/dev/null; exit 0 ;;
esac
exit 0''')

    def run(script: str, **env: str) -> subprocess.CompletedProcess:
        environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        environment |= {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home), "ROLEBAND_INSTALL_LAUNCHER": "no", **env}
        return subprocess.run(
            ["bash", str(checkout / "deploy" / script)], env=environment, capture_output=True, text=True, timeout=120,
        )

    return run, record, agents, checkout


def _calls(record: Path) -> list[str]:
    return record.read_text().splitlines() if record.exists() else []


@pytest.mark.parametrize("result", [0, 1])
def test_the_optional_launcher_runs_after_engine_registration_and_failure_keeps_the_engine(sandbox, result):
    run, record, agents, checkout = sandbox
    compiler = checkout.parent / "bin" / "xcrun"
    compiler.write_text("#!/bin/sh\nexit 0\n")
    compiler.chmod(0o755)
    launcher = checkout / "launcher" / "macos" / "install.sh"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(f'#!/bin/sh\necho "launcher install" >> "{record}"\nexit {result}\n')
    launcher.chmod(0o755)
    done = run("install.sh", ROLEBAND_INSTALL_LAUNCHER="yes")
    assert done.returncode == 0, done.stdout + done.stderr
    calls = _calls(record)
    assert calls.index("python -m tracker.supervisor.launcher register") < calls.index("launcher install")
    assert (agents / "com.roleband.plist").is_file()
    assert len([call for call in calls if call.startswith("launchctl bootstrap")]) == 1
    if result:
        assert "background engine stays installed" in done.stderr


def test_install_registers_one_item_running_the_named_launcher(sandbox):
    run, record, agents, checkout = sandbox
    done = run("install.sh")
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(p.name for p in agents.iterdir()) == ["com.roleband.plist"]
    rendered = plistlib.loads((agents / "com.roleband.plist").read_bytes())
    assert rendered["Label"] == "com.roleband"
    assert rendered["ProgramArguments"] == [f"{checkout}/deploy/roleband"]
    assert rendered["KeepAlive"] is True
    assert rendered["StandardOutPath"] == f"{checkout}/data/logs/launchd.log"
    bootstraps = [c for c in _calls(record) if c.startswith("launchctl bootstrap")]
    assert bootstraps == [f"launchctl bootstrap gui/{os.getuid()} {agents}/com.roleband.plist"]
    assert "python -m tracker.supervisor.activation record-deps" in _calls(record)
    assert "python -m tracker.supervisor maintenance off --wait 0" in _calls(record)
    calls = _calls(record)
    assert calls.index(bootstraps[0]) < calls.index("python -m tracker.supervisor.launcher register")


def test_install_installs_the_set_setup_installs_before_recording_it(sandbox):
    """The record names what is installed: the dev tools the preflight runs and the robots matcher too."""
    run, record, _agents, checkout = sandbox
    done = run("install.sh")
    assert done.returncode == 0, done.stdout + done.stderr
    calls = _calls(record)
    required = (
        f"python -m pip install -q -r {checkout}/backend/requirements.txt"
        f" -r {checkout}/backend/requirements-dev.txt -c {checkout}/backend/constraints/macos-arm64.txt"
    )
    robots = f"python -m pip install -q -e {checkout}/robots/python"
    recorded = "python -m tracker.supervisor.activation record-deps"
    assert calls.index(required) < calls.index(robots) < calls.index(recorded), calls


def test_install_without_the_backend_virtualenv_refuses_before_touching_anything(sandbox):
    run, record, agents, checkout = sandbox
    shutil.rmtree(checkout / "backend" / ".venv")
    done = run("install.sh")
    assert done.returncode == 1
    assert "run ./setup.sh first" in done.stderr
    assert list(agents.iterdir()) == []
    assert not [c for c in _calls(record) if c.split()[0] in {"launchctl", "npm", "curl"}]


def test_uninstall_stops_the_jobs_first_then_removes_only_its_item(sandbox):
    run, record, agents, checkout = sandbox
    for label in ["com.roleband", "com.example.other"]:
        (agents / f"{label}.plist").write_text("<plist/>")
    done = run("uninstall.sh")
    assert done.returncode == 0, done.stdout + done.stderr
    assert [p.name for p in agents.iterdir()] == ["com.example.other.plist"]
    calls = _calls(record)
    stop = calls.index("python -m tracker.supervisor stop --jobs")
    first_bootout = next(i for i, c in enumerate(calls) if c.startswith("launchctl bootout"))
    assert stop < first_bootout, "a bootout alone would leave the jobs running"
    unregister = calls.index("python -m tracker.supervisor.launcher unregister")
    assert first_bootout < unregister
    removed = [c.split("/")[-1] for c in calls if c.startswith("launchctl bootout")]
    assert removed == ["com.roleband"]


def test_uninstall_waits_for_bootout_before_removing_discovery(sandbox, tmp_path):
    run, record, agents, _checkout = sandbox
    (agents / "com.roleband.plist").write_text("<plist/>")
    marker = tmp_path / "unloading"
    tool = tmp_path / "bin" / "launchctl"
    tool.write_text(f'''#!/bin/sh
echo "launchctl $*" >> "{record}"
case "$1" in
  bootout) touch "{marker}"; exit 0 ;;
  print)
    if [ -f "{marker}" ]; then
      rm "{marker}"; echo "still unloading" >> "{record}"; exit 0
    fi
    echo "unloaded" >> "{record}"; exit 1 ;;
esac
exit 0
''')
    sleep = tmp_path / "bin" / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    done = run("uninstall.sh")
    assert done.returncode == 0, done.stdout + done.stderr
    calls = _calls(record)
    unregister = calls.index("python -m tracker.supervisor.launcher unregister")
    assert calls.index("still unloading") < calls.index("unloaded") < unregister
