"""`setup.sh`, run for real against stub tools: what it refuses, and what it installs from.

The script is copied into a scratch root beside the repo's real version files and
dependency locks. Every external tool it calls (python, pip, alembic, node, npm,
uname) is a stub that logs its arguments, so these tests assert the script's
decisions and the exact commands it issues without installing anything.

Versions are read from `.python-version` and `.nvmrc` rather than written here,
so the tests follow the policy when it moves instead of freezing today's numbers.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from scripts.lock_dependencies import PLATFORMS

REPO = Path(__file__).resolve().parents[2]
PY_WANT = (REPO / ".python-version").read_text().strip()
NODE_MIN = int((REPO / ".nvmrc").read_text().strip())
_MAJOR, _MINOR = (int(part) for part in PY_WANT.split("."))
PY_OTHER = f"{_MAJOR}.{_MINOR + 1}"

#: What `uname -s`/`uname -m` answer on each locked platform.
UNAME = {
    "macos-arm64": ("Darwin", "arm64"),
    "linux-x86_64": ("Linux", "x86_64"),
    "linux-aarch64": ("Linux", "aarch64"),
}


@dataclass
class Host:
    os: str = "Darwin"
    arch: str = "arm64"
    python_named: str = PY_WANT  # what `python3.12` (the wanted minor) reports
    python3: str = PY_WANT
    venv: str | None = PY_WANT  # None: no backend/.venv yet
    node: str = f"{NODE_MIN}.4.0"
    npm_ci_fails: bool = False


def _stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _python_stub(version: str) -> str:
    return (
        'case "$*" in *version_info*) echo "' + version + '"; exit 0 ;; esac\n'
        'echo "$(basename "$0") $*" >> "$SETUP_LOG"\n'
    )


def run_setup(tmp_path: Path, host: Host, *args: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    root = tmp_path / "repo"
    (root / "backend" / "constraints").mkdir(parents=True)
    (root / "dashboard").mkdir()
    shutil.copy(REPO / "setup.sh", root / "setup.sh")
    for name in (".python-version", ".nvmrc"):
        shutil.copy(REPO / name, root / name)
    for lock in (REPO / "backend" / "constraints").glob("*.txt"):
        shutil.copy(lock, root / "backend" / "constraints" / lock.name)
    (root / "backend" / ".env.example").write_text("")
    (root / "dashboard" / "package-lock.json").write_text("{}")

    bin_dir = tmp_path / "bin"
    _stub(bin_dir / f"python{PY_WANT}", _python_stub(host.python_named))
    _stub(bin_dir / "python3", _python_stub(host.python3))
    _stub(bin_dir / "node", f'echo "v{host.node}"\n')
    _stub(
        bin_dir / "npm",
        'echo "npm $*" >> "$SETUP_LOG"\n'
        + ('[ "$1" = ci ] && exit 1\n' if host.npm_ci_fails else "")
        + "exit 0\n",
    )
    _stub(bin_dir / "uname", f'case "$1" in -m) echo "{host.arch}" ;; *) echo "{host.os}" ;; esac\n')
    if host.venv is not None:
        venv = root / "backend" / ".venv" / "bin"
        _stub(venv / "python", _python_stub(host.venv))
        _stub(venv / "pip", 'echo "pip $*" >> "$SETUP_LOG"\n')
        _stub(venv / "alembic", 'echo "alembic $*" >> "$SETUP_LOG"\n')

    log = tmp_path / "calls.log"
    log.touch()
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SETUP_LOG": str(log),
    }
    proc = subprocess.run(
        ["/bin/bash", str(root / "setup.sh"), *args],
        cwd=root, env=env, capture_output=True, text=True, timeout=60,
    )
    return proc, log.read_text().splitlines()


def installed_anything(calls: list[str]) -> bool:
    return any(
        call.split()[0] in {"pip", "alembic", "npm"} or " -m pip " in f" {call} " for call in calls
    )


def test_every_locked_platform_is_mapped_here():
    """A new lock needs a `uname` answer in setup.sh and in this table."""
    assert set(UNAME) == set(PLATFORMS)


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_a_supported_host_installs_both_requirement_files_against_its_lock(tmp_path, platform):
    os_name, arch = UNAME[platform]
    proc, calls = run_setup(tmp_path, Host(os=os_name, arch=arch))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    lock = tmp_path / "repo" / "backend" / "constraints" / f"{platform}.txt"
    assert (
        f"pip install --quiet -r requirements.txt -r requirements-dev.txt -c {lock}" in calls
    ), calls
    assert "alembic upgrade head" in calls
    assert [c for c in calls if c.startswith("npm ")] == ["npm ci --silent"]


def test_another_python_minor_is_refused_before_anything_is_installed(tmp_path):
    proc, calls = run_setup(tmp_path, Host(python_named=PY_OTHER, python3=PY_OTHER))

    assert proc.returncode != 0
    assert f"Python {PY_WANT} not found" in proc.stderr
    assert not installed_anything(calls), calls


def test_a_python3_of_the_right_minor_is_accepted_without_the_versioned_name(tmp_path):
    """The control for the refusal above: it is the version that is judged."""
    proc, _calls = run_setup(tmp_path, Host(python_named=PY_OTHER, python3=PY_WANT))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_an_existing_venv_on_another_python_is_refused_not_reused(tmp_path):
    proc, calls = run_setup(tmp_path, Host(venv=PY_OTHER))

    assert proc.returncode != 0
    assert f"backend/.venv runs Python {PY_OTHER}, not {PY_WANT}" in proc.stderr
    assert "mv backend/.venv backend/.venv.old" in proc.stderr
    assert not installed_anything(calls), calls


def test_a_platform_without_a_lock_is_refused_by_name(tmp_path):
    proc, calls = run_setup(tmp_path, Host(os="Darwin", arch="x86_64"))

    assert proc.returncode != 0
    assert "no dependency lock for Darwin/x86_64" in proc.stderr
    assert not installed_anything(calls), calls


def test_a_node_below_the_floor_is_refused(tmp_path):
    proc, calls = run_setup(tmp_path, Host(node=f"{NODE_MIN - 1}.20.0"))

    assert proc.returncode != 0
    assert f"older than {NODE_MIN}" in proc.stderr
    assert not installed_anything(calls), calls


def test_a_newer_node_major_is_accepted(tmp_path):
    """A floor, not a pin: a developer machine may build the dashboard on a newer major."""
    proc, _calls = run_setup(tmp_path, Host(node=f"{NODE_MIN + 1}.8.1"))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_skipping_the_dashboard_does_not_consult_node(tmp_path):
    proc, calls = run_setup(tmp_path, Host(node=f"{NODE_MIN - 1}.20.0"), "--skip-dashboard")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not [c for c in calls if c.startswith("npm ")]


RECORD_DEPS = "python -m tracker.supervisor.activation record-deps"


def test_skipping_the_dashboard_records_no_dependencies(tmp_path):
    """A record that left the dashboard out would let a supervisor run stale node modules."""
    proc, calls = run_setup(tmp_path, Host(), "--skip-dashboard")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert RECORD_DEPS not in calls, calls
    assert "installed dependencies not recorded" in proc.stdout + proc.stderr


def test_a_full_setup_records_the_installed_dependencies(tmp_path):
    """The control for the test above: the record is skipped for the flag, not always."""
    proc, calls = run_setup(tmp_path, Host())

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert RECORD_DEPS in calls, calls


def test_a_failed_npm_ci_fails_setup_and_never_rewrites_the_lock(tmp_path):
    """`npm ci || npm install` would rewrite package-lock.json and report success."""
    proc, calls = run_setup(tmp_path, Host(npm_ci_fails=True))

    assert proc.returncode != 0
    assert "npm ci failed" in proc.stderr
    assert [c for c in calls if c.startswith("npm ")] == ["npm ci --silent"], calls
    assert (tmp_path / "repo" / "dashboard" / "package-lock.json").read_text() == "{}"


def _setup_steps(action: str) -> list[tuple[str, dict]]:
    steps = []
    for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(workflow.read_text())
        for job in data.get("jobs", {}).values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith(action):
                    steps.append((workflow.name, step.get("with", {})))
    return steps


def test_ci_reads_the_same_version_files_as_setup():
    """Two statements of the toolchain drift; one file read by both cannot."""
    python_steps = _setup_steps("actions/setup-python")
    node_steps = _setup_steps("actions/setup-node")
    assert python_steps and node_steps
    for name, config in python_steps:
        assert config.get("python-version-file") == ".python-version", name
        assert "python-version" not in config, name
    for name, config in node_steps:
        assert config.get("node-version-file") == ".nvmrc", name
        assert "node-version" not in config, name


def _quickstart_commands() -> list[str]:
    """The commands the README Quickstart gives after `./setup.sh`, without
    their leading `cd`."""
    readme = (REPO / "README.md").read_text()
    quickstart = readme.split("## Quickstart", 1)[1].split("\n## ", 1)[0]
    blocks = quickstart.split("```bash\n")[1:]
    commands = []
    for block in blocks:
        for line in block.split("```", 1)[0].splitlines():
            line = line.strip()
            if line and line != "./setup.sh":
                commands.append(line.split("&& ", 1)[-1] if line.startswith("cd ") else line)
    return [command for command in commands if not command.startswith("cd ")]


def test_setup_s_last_screen_gives_the_readme_s_commands():
    """The last thing every new user reads. It names the same commands as the
    README Quickstart, so its first scrape is the README's capped one and the
    API and the dashboard start in their own shells."""
    done = (REPO / "setup.sh").read_text().split('step "Done"', 1)[1]
    commands = _quickstart_commands()
    assert "-m tracker.daily --max-list 150 --no-hydrate -v" in " ".join(commands), "the README's scrape moved"
    missing = [command for command in commands if command not in done]
    assert missing == [], f"setup.sh's closing steps differ from the README Quickstart: {missing}"
    assert "--max-list 300" not in done
