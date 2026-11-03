"""The local runner records real command outcomes and refuses a moving source tree."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "check_local.py"
spec = importlib.util.spec_from_file_location("check_local", SCRIPT)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "source.py").write_text("value = 1\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
    for args in (["init", "-q"], ["add", "source.py"], ["commit", "-qm", "fixture"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True)
    output = tmp_path / "reports"
    output.mkdir()
    return root, output


def test_failed_command_stops_the_profile_but_runs_cleanup(checkout):
    root, output = checkout
    steps = [runner.Step("fails", root, [sys.executable, "-c", "print('contract failed'); raise SystemExit(7)"]),
             runner.Step("never", root, [sys.executable, "-c", "raise AssertionError('must not run')"])]
    cleanup = runner.Step("cleanup", root, [sys.executable, "-c", "print('cleaned')"])
    assert runner.execute(root, output, steps, dict(os.environ), cleanup=[cleanup]) == 7
    report = json.loads((output / "report.json").read_text())
    assert [s["name"] for s in report["steps"]] == ["fails", "cleanup"]
    assert report["steps"][0]["wall_seconds"] > 0
    assert "contract failed" in (output / "fails.log").read_text()
    assert "cleaned" in (output / "cleanup.log").read_text()
    assert not report["source_changed"]


@pytest.mark.parametrize("path", ["source.py", "new-test.py"])
def test_a_passing_command_cannot_verify_changed_or_new_source(checkout, path):
    root, output = checkout
    step = runner.Step("changes", root, [sys.executable, "-c",
                       "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('changed')", path])
    assert runner.execute(root, output, [step], dict(os.environ)) == 76
    report = json.loads((output / "report.json").read_text())
    assert report["source_changed"]
    assert report["steps"][0]["exit_code"] == 0
    assert report["source_before"]["fingerprint"] != report["source_after"]["fingerprint"]


def test_unavailable_command_has_a_failed_report(checkout):
    root, output = checkout
    assert runner.execute(root, output, [runner.Step("missing", root, [str(root / "absent")])], dict(os.environ)) == 127
    assert json.loads((output / "report.json").read_text())["exit_code"] == 127


def test_a_passing_command_cannot_verify_changed_installed_packages(checkout):
    root, output = checkout
    (root / ".gitignore").write_text("node_modules/\n")
    package = root / "dashboard" / "node_modules" / "vitest" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"1.0.0"}')
    step = runner.Step("changes-runtime", root, [sys.executable, "-c",
                       "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('{\"version\":\"2.0.0\"}')", str(package)])
    assert runner.execute(root, output, [step], dict(os.environ)) == 76
    report = json.loads((output / "report.json").read_text())
    assert report["source_changed"] is False
    assert report["environment_changed"] is True


def test_clean_execution_keeps_the_exact_source_identity_and_command(checkout):
    root, output = checkout
    step = runner.Step("passing", root, [sys.executable, "-c", "print('verified')"])
    assert runner.execute(root, output, [step], dict(os.environ)) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["source_before"] == report["source_after"]
    assert report["steps"][0]["argv"] == list(step.argv)
    assert report["checkout"] == str(root)
    assert report["wall_seconds"] >= report["steps"][0]["wall_seconds"]


@pytest.fixture
def cli_tools(checkout, tmp_path):
    root, _ = checkout
    (root / "deploy").mkdir()
    (root / "dashboard").mkdir()
    shutil.copy(SCRIPT, root / "deploy" / "check_local.py")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    tool = f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys, time
if "--version" in sys.argv:
    print("v24.0.0" if pathlib.Path(sys.argv[0]).name == "node" else "11.0.0")
else:
    with open(os.environ["CHECK_CALLS"], "a") as stream:
        keys = ["ROLEBAND_UX_MODE", "ROLEBAND_UX_WORKERS", "ROLEBAND_DIST_OUT", "ROLEBAND_UX_OUTPUT_DIR", "ROLEBAND_UX_PORT", "VITE_API_TARGET"]
        stream.write(json.dumps({"tool": pathlib.Path(sys.argv[0]).name, "argv": sys.argv[1:],
                                 "env": {key: os.environ.get(key) for key in keys}}) + "\\n")
    if sys.argv[1:3] == ["ps", "-aq"]:
        print(os.environ.get("CHECK_LEFTOVER", ""))
    if os.environ.get("CHECK_HOLD"):
        pathlib.Path(os.environ["CHECK_READY"]).write_text(str(os.getpid()))
        time.sleep(60)
'''
    for name in ("node", "npm", "docker"):
        path = binaries / name
        path.write_text(tool)
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
           "CHECK_CALLS": str(tmp_path / "calls.jsonl"), "CHECK_READY": str(tmp_path / "ready")}
    return root, env


def test_cli_gives_browser_runs_their_own_build_port_and_reports(cli_tools, tmp_path):
    root, env = cli_tools
    output = tmp_path / "run"
    done = subprocess.run([sys.executable, str(root / "deploy" / "check_local.py"), "ux",
                           "--output", str(output), "--ux-workers", "6", "--test", "tests/ux/a11y.spec.ts"],
                          env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stdout + done.stderr
    calls = [json.loads(line) for line in Path(env["CHECK_CALLS"]).read_text().splitlines()]
    assert calls[0]["argv"] == ["run", "build"]
    assert calls[1]["argv"] == ["run", "test:ux", "--", "tests/ux/a11y.spec.ts"]
    browser_env = calls[1]["env"]
    assert browser_env["ROLEBAND_UX_MODE"] == "preview"
    assert browser_env["ROLEBAND_UX_WORKERS"] == "6"
    assert browser_env["ROLEBAND_DIST_OUT"] == str(output / "dashboard-dist")
    assert browser_env["ROLEBAND_UX_OUTPUT_DIR"] == str(output / "playwright")
    assert 0 < int(browser_env["ROLEBAND_UX_PORT"]) < 65536
    assert browser_env["VITE_API_TARGET"] == "http://127.0.0.1:9"


def test_cli_termination_stops_its_detached_child_and_records_cancellation(cli_tools, tmp_path):
    root, env = cli_tools
    output = tmp_path / "run"
    process = subprocess.Popen([sys.executable, str(root / "deploy" / "check_local.py"), "unit", "--output", str(output)],
                               env={**env, "CHECK_HOLD": "1"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    child_pid = None
    try:
        deadline = time.monotonic() + 10
        ready = Path(env["CHECK_READY"])
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "the child never started"
        child_pid = int(ready.read_text())
        process.send_signal(signal.SIGTERM)
        stdout, _ = process.communicate(timeout=10)
        assert process.returncode == 130, stdout.decode()
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        report = json.loads((output / "report.json").read_text())
        assert report["exit_code"] == 130
        assert report["source_changed"] is False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def _waits_for(mine: Path, theirs: Path) -> list[str]:
    """A step that passes only while the other lane's step is running too."""
    return [sys.executable, "-c",
            "import pathlib, sys, time\n"
            "pathlib.Path(sys.argv[1]).touch()\n"
            "deadline = time.monotonic() + 10\n"
            "while not pathlib.Path(sys.argv[2]).exists():\n"
            "    if time.monotonic() > deadline: sys.exit('the other lane never ran alongside')\n"
            "    time.sleep(0.01)\n", str(mine), str(theirs)]


def test_a_second_lane_runs_at_the_same_time_and_cleanup_waits_for_both(checkout, tmp_path):
    root, output = checkout
    backend, dashboard = tmp_path / "backend-started", tmp_path / "dashboard-started"
    lane = [runner.Step("backend", root, _waits_for(backend, dashboard))]
    alongside = [runner.Step("dashboard", root, _waits_for(dashboard, backend))]
    cleanup = runner.Step("cleanup", root, [sys.executable, "-c", "print('cleaned')"])
    assert runner.execute(root, output, lane, dict(os.environ), cleanup=[cleanup], alongside=alongside) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["lanes"] == 2
    assert sorted((s["name"], s["lane"]) for s in report["steps"][:2]) == [("backend", 0), ("dashboard", 1)]
    assert report["steps"][-1]["name"] == "cleanup"
    finished = max(s["started_seconds"] + s["wall_seconds"] for s in report["steps"][:2])
    assert report["steps"][-1]["started_seconds"] >= finished


def test_a_failed_lane_stops_itself_while_the_other_lane_finishes(checkout):
    root, output = checkout
    lane = [runner.Step("fails", root, [sys.executable, "-c", "raise SystemExit(3)"]),
            runner.Step("never", root, [sys.executable, "-c", "raise AssertionError('must not run')"])]
    alongside = [runner.Step("slow", root, [sys.executable, "-c", "import time; time.sleep(0.5)"]),
                 runner.Step("after-slow", root, [sys.executable, "-c", "print('ran')"])]
    assert runner.execute(root, output, lane, dict(os.environ), alongside=alongside) == 3
    names = [s["name"] for s in json.loads((output / "report.json").read_text())["steps"]]
    assert sorted(names) == ["after-slow", "fails", "slow"]


def test_each_step_reports_its_own_cpu_while_the_lanes_overlap(checkout):
    root, output = checkout
    burn = [sys.executable, "-c", "import time\nwhile time.process_time() < 0.6: pass"]
    idle = [sys.executable, "-c", "import time; time.sleep(1.5)"]
    assert runner.execute(root, output, [runner.Step("idle", root, idle)], dict(os.environ),
                          alongside=[runner.Step("burn", root, burn)]) == 0
    steps = {s["name"]: s for s in json.loads((output / "report.json").read_text())["steps"]}
    assert steps["burn"]["user_seconds"] + steps["burn"]["system_seconds"] >= 0.5
    assert steps["idle"]["user_seconds"] + steps["idle"]["system_seconds"] < 0.3, "the burner's CPU is not the sleeper's"


def test_termination_stops_both_lanes_children(checkout, tmp_path):
    root, output = checkout
    ready = [tmp_path / "first", tmp_path / "second"]
    hold = "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    script = (
        "import os, signal, sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "import check_local as runner\n"
        "def interrupted(*_): raise KeyboardInterrupt\n"
        "signal.signal(signal.SIGTERM, interrupted)\n"
        "root, output = runner.Path(sys.argv[1]), runner.Path(sys.argv[2])\n"
        f"hold = {hold!r}\n"
        "step = lambda name, path: runner.Step(name, root, [sys.executable, '-c', hold, path])\n"
        "sys.exit(runner.execute(root, output, [step('first', sys.argv[3])], dict(os.environ),"
        " alongside=[step('second', sys.argv[4])]))\n"
    )
    process = subprocess.Popen([sys.executable, "-c", script, str(root), str(output), *map(str, ready)])
    pids: list[int] = []
    try:
        deadline = time.monotonic() + 10
        while not all(path.exists() and path.read_text() for path in ready) and time.monotonic() < deadline:
            time.sleep(0.01)
        pids = [int(path.read_text()) for path in ready]
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 130
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        report = json.loads((output / "report.json").read_text())
        assert sorted((s["name"], s["exit_code"]) for s in report["steps"]) == [("first", 130), ("second", 130)]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for pid in pids:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_cli_parallel_is_only_for_the_complete_profile(cli_tools, tmp_path):
    root, env = cli_tools
    done = subprocess.run([sys.executable, str(root / "deploy" / "check_local.py"), "dashboard", "--parallel",
                           "--output", str(tmp_path / "run")], env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 2
    assert "--parallel is only valid for the all profile" in done.stderr


def _docker_checkout(root: Path) -> None:
    """A dashboard whose lockfile pins Playwright, with an untracked source file and
    ignored packages the snapshot must leave out."""
    (root / ".gitignore").write_text("node_modules/\n__pycache__/\n")
    lock = {"packages": {"node_modules/@playwright/test": {"version": "1.64.1"}}}
    (root / "dashboard" / "package-lock.json").write_text(json.dumps(lock))
    (root / "dashboard" / "untracked.ts").write_text("export const value = 1;\n")
    (root / "dashboard" / "node_modules" / "vite").mkdir(parents=True)
    (root / "dashboard" / "node_modules" / "vite" / "index.js").write_text("ignored\n")


def _docker_runs(env: dict[str, str]) -> list[list[str]]:
    calls = [json.loads(line) for line in Path(env["CHECK_CALLS"]).read_text().splitlines()]
    return [call["argv"] for call in calls if call["tool"] == "docker" and call["argv"][0] == "run"]


def test_docker_browsers_build_and_test_in_a_container_without_network(cli_tools, tmp_path):
    root, env = cli_tools
    _docker_checkout(root)
    output = tmp_path / "run"
    done = subprocess.run([sys.executable, str(root / "deploy" / "check_local.py"), "ux", "--docker-browsers",
                           "--output", str(output), "--test", "tests/ux/a11y.spec.ts"],
                          env={**env, "CHECK_LEFTOVER": "leftover1"}, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stdout + done.stderr
    calls = [json.loads(line) for line in Path(env["CHECK_CALLS"]).read_text().splitlines()]
    assert not [c for c in calls if c["tool"] == "npm"], "the host neither builds nor runs browsers"

    dependencies, build, browsers = _docker_runs(env)
    image = "mcr.microsoft.com/playwright:v1.64.1-noble"
    assert image in dependencies and image in build and image in browsers
    assert "--network" not in dependencies, "only the install reaches the registry"
    for offline in (build, browsers):
        assert offline[offline.index("--network") + 1] == "none"
    packages = {run[i + 1] for run in (dependencies, build, browsers) for i, arg in enumerate(run)
                if arg == "-v" and run[i + 1].endswith(":/work/dashboard/node_modules")}
    assert len(packages) == 1 and packages.pop().startswith("roleband-ux-node-modules-"), "one Linux install"
    label = f"{runner.DOCKER_LABEL}={output.resolve()}"
    assert all(run[run.index("--label") + 1] == label for run in (dependencies, build, browsers))
    assert "ROLEBAND_UX_WORKERS=12" in browsers and "VITE_API_TARGET=http://127.0.0.1:9" in browsers
    assert browsers[-1] == "tests/ux/a11y.spec.ts"

    with tarfile.open(output / "source.tar") as archive:
        members = set(archive.getnames())
    assert {"source.py", "deploy/check_local.py", "dashboard/package-lock.json", "dashboard/untracked.ts"} <= members
    assert not [name for name in members if "node_modules" in name or Path(name).name.startswith("._")]

    assert ["rm", "-f", "leftover1"] in [c["argv"] for c in calls if c["tool"] == "docker"]
    report = json.loads((output / "report.json").read_text())
    assert report["profile"]["ROLEBAND_CHECK_BROWSERS"] == "docker"
    assert report["profile"]["ROLEBAND_UX_WORKERS"] == "12"
    assert [s["name"] for s in report["steps"]][-1] == "docker-cleanup"


def test_docker_browsers_take_an_explicit_worker_budget(cli_tools, tmp_path):
    root, env = cli_tools
    _docker_checkout(root)
    done = subprocess.run([sys.executable, str(root / "deploy" / "check_local.py"), "ux", "--docker-browsers",
                           "--ux-workers", "6", "--output", str(tmp_path / "run")],
                          env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ROLEBAND_UX_WORKERS=6" in _docker_runs(env)[-1]


@pytest.mark.parametrize("profile", ["backend", "unit"])
def test_docker_browsers_are_refused_where_no_browser_runs(cli_tools, tmp_path, profile):
    root, env = cli_tools
    done = subprocess.run([sys.executable, str(root / "deploy" / "check_local.py"), profile, "--docker-browsers",
                           "--output", str(tmp_path / "run")], env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 2
    assert "--docker-browsers is only valid for all, dashboard or ux profiles" in done.stderr


def test_docker_browsers_without_docker_are_refused(cli_tools, tmp_path):
    root, env = cli_tools
    alone = tmp_path / "no-docker"
    alone.mkdir()
    for name in ("node", "npm", "git"):
        (alone / name).symlink_to(shutil.which(name, path=env["PATH"]))
    done = subprocess.run([sys.executable, str(root / "deploy" / "check_local.py"), "ux", "--docker-browsers",
                           "--output", str(tmp_path / "run")], env={**env, "PATH": str(alone)},
                          capture_output=True, text=True, timeout=20)
    assert done.returncode == 2
    assert "--docker-browsers needs the docker CLI" in done.stderr


def test_nothing_unattended_runs_the_local_runner():
    """The supervisor's preflight and the launchd scripts never call this runner,
    so its Docker mode cannot become a dependency of unattended execution."""
    root = SCRIPT.parents[1]
    unattended = [*sorted((root / "deploy").glob("*.sh")), root / "deploy" / "roleband", root / "setup.sh",
                  *sorted((root / "backend" / "tracker").rglob("*.py"))]
    assert len(unattended) > 10
    assert [path for path in unattended if "check_local" in path.read_text()] == []
