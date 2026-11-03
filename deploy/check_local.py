"""Run a local check profile and keep timings, logs and source identity outside the tree.

    backend/.venv/bin/python deploy/check_local.py dashboard
    backend/.venv/bin/python deploy/check_local.py backend --backend-workers 4
    backend/.venv/bin/python deploy/check_local.py ux --test tests/ux/a11y.spec.ts
    backend/.venv/bin/python deploy/check_local.py all --docker-browsers

Profiles run sequentially; `all --parallel` runs the backend and dashboard lanes at
the same time. Dashboard/UX profiles build once, then serve that build on their own
port; `--docker-browsers` builds and runs the browsers in a Linux container instead.
Backend profiles use an isolated temporary Postgres cluster. Reports describe this
invocation only and never certify unattended execution, and nothing unattended
runs this script.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: The browser image follows the locked Playwright version: its browsers are the
#: builds that version drives.
PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v{version}-noble"
DOCKER_UX_WORKERS = 12
#: Every container a run starts carries this label with the run's report
#: directory, so cleanup can remove one an interrupted run left behind.
DOCKER_LABEL = "org.roleband.check-local"


@dataclass(frozen=True)
class Step:
    name: str
    cwd: Path
    argv: Sequence[str]


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def source_files(root: Path) -> list[bytes]:
    """Tracked and untracked files git does not ignore: the source a run verifies."""
    return sorted(set(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")) - {b""})


def source_state(root: Path) -> dict:
    digest = hashlib.sha256()
    for name in source_files(root):
        path = root / os.fsdecode(name)
        digest.update(name + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(str(path.stat().st_mode & 0o777).encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b"missing")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    return {
        "head": head,
        "fingerprint": hashlib.sha256(head.encode() + digest.digest()).hexdigest(),
        "status": git(root, "status", "--porcelain").decode(),
    }


def write_snapshot(root: Path, target: Path) -> None:
    """The fingerprinted files as a tar for the container. Written here rather than
    by macOS `tar`, which adds AppleDouble `._*` members the copy generator reads."""
    with tarfile.open(target, "w") as archive:
        for name in source_files(root):
            path = root / os.fsdecode(name)
            if path.is_symlink() or path.is_file():
                archive.add(path, arcname=os.fsdecode(name), recursive=False)


def docker_browser_steps(root: Path, output: Path, python: str, workers: int,
                         tests: Sequence[str]) -> tuple[list[Step], Step]:
    """Build and both browser projects in Linux, and the cleanup for their containers.

    On macOS, WebKit's window captures accumulate in WindowServer until it aborts
    and ends the desktop session; in a Linux container there is no WindowServer.
    Only the dependency install has a network: the build and the browsers run
    without one, so no request can reach an API on the host."""
    lock = (root / "dashboard" / "package-lock.json").read_bytes()
    version = json.loads(lock)["packages"]["node_modules/@playwright/test"]["version"]
    image = PLAYWRIGHT_IMAGE.format(version=version)
    # Linux packages of their own (the bundler is native), kept per image and lockfile.
    volume = "roleband-ux-node-modules-" + hashlib.sha256(image.encode() + lock).hexdigest()[:16]
    label = f"{DOCKER_LABEL}={output}"
    run = ["docker", "run", "--rm", "--init", "--label", label, "-v", f"{output}:/out",
           "-v", f"{volume}:/work/dashboard/node_modules", "-w", "/work"]
    offline = [*run, "--network", "none", "--shm-size=2g", "-e", "CI=", "-e", "ROLEBAND_DIST_OUT=/out/dashboard-dist"]
    unpack = "tar -xf /out/source.tar && cd dashboard && "
    snapshot = Step("browser-snapshot", root, [python, "-c",
        ("import importlib.util, sys; from pathlib import Path; "
        "spec = importlib.util.spec_from_file_location('check_local', sys.argv[1]); "
        "module = importlib.util.module_from_spec(spec); sys.modules['check_local'] = module; "
        "spec.loader.exec_module(module); module.write_snapshot(Path(sys.argv[2]), Path(sys.argv[3]))"),
        str(Path(__file__).resolve()), str(root), str(output / "source.tar")])
    steps = [
        snapshot,
        Step("docker-dependencies", root, [*run, image, "sh", "-c", unpack +
             "if [ -f node_modules/.installed ]; then echo dependencies current; "
             "else npm ci --no-audit --no-fund && touch node_modules/.installed; fi"]),
        Step("docker-image", root, ["docker", "image", "inspect", "--format", "{{.Id}} {{.RepoDigests}}", image]),
        Step("docker-build", root, [*offline, image, "sh", "-c", unpack + "npm run build"]),
        Step("docker-playwright", root, [*offline, "-e", "ROLEBAND_UX_MODE=preview",
             "-e", f"ROLEBAND_UX_WORKERS={workers}", "-e", "ROLEBAND_UX_PORT=4173",
             "-e", "ROLEBAND_UX_OUTPUT_DIR=/out/playwright", "-e", "VITE_API_TARGET=http://127.0.0.1:9",
             image, "sh", "-c", unpack + 'npm run test:ux -- "$@"', "sh", *tests]),
    ]
    cleanup = Step("docker-cleanup", root, [python, "-c",
        ("import subprocess, sys; "
        "found = subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=' + sys.argv[1]], "
        "capture_output=True, text=True, check=True).stdout.split(); "
        "found and subprocess.run(['docker', 'rm', '-f', *found], check=True); "
        "print(f'removed {len(found)} container(s)')"), label])
    return steps, cleanup


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def runtime_state(root: Path) -> dict:
    installed_lock = root / "dashboard" / "node_modules" / ".package-lock.json"
    return {
        "python_packages": sorted((d.metadata["Name"] or "<unnamed>", d.version)
                                  for d in importlib.metadata.distributions()),
        "dashboard_packages": {
            name: json.loads(path.read_text())["version"]
            for name in ("vite", "vitest", "@playwright/test", "react")
            if (path := root / "dashboard" / "node_modules" / name / "package.json").is_file()
        },
        "installed_node_lock": hashlib.sha256(installed_lock.read_bytes()).hexdigest() if installed_lock.is_file() else None,
    }


def run_step(step: Step, output: Path, env: dict[str, str], running: dict[int, str]) -> dict:
    start = time.perf_counter()
    log = output / f"{step.name}.log"
    print(f"check-local: {step.name} (log: {log})", flush=True)
    user = system = 0.0
    with log.open("w") as stream:
        try:
            process = subprocess.Popen(step.argv, cwd=step.cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            stream.write(str(error))
            code = 127
        else:
            running[process.pid] = step.name
            try:
                # This child's own CPU: RUSAGE_CHILDREN would also count whatever
                # the other lane's commands finished meanwhile.
                _, status, usage = os.wait4(process.pid, 0)
            finally:
                running.pop(process.pid, None)
            process.returncode = code = os.waitstatus_to_exitcode(status)
            user, system = usage.ru_utime, usage.ru_stime
    result = {
        "name": step.name, "cwd": str(step.cwd), "argv": list(step.argv),
        "exit_code": code, "wall_seconds": time.perf_counter() - start,
        "user_seconds": user, "system_seconds": system, "log": str(log),
    }
    print(f"check-local: {step.name}: exit {code}, {result['wall_seconds']:.2f}s", flush=True)
    return result


def run_lane(lane: int, steps: Sequence[Step], output: Path, env: dict[str, str], origin: float,
             running: dict[int, str], stopping: threading.Event, results: list[dict]) -> None:
    """Run steps in order until one fails or the run is stopped."""
    for step in steps:
        if stopping.is_set():
            return
        offset = time.perf_counter() - origin
        result = {**run_step(step, output, env, running), "lane": lane, "started_seconds": offset}
        if stopping.is_set():
            result["exit_code"] = 130
        results.append(result)
        if result["exit_code"]:
            return


def stop(running: dict[int, str], lanes: Sequence[threading.Thread]) -> None:
    """Terminate every running command's process group; kill what outlives five seconds."""
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, None)):
        for pid in list(running):
            try:
                os.killpg(pid, sig)
            # macOS answers EPERM for a group whose only member has exited
            # and waits to be reaped.
            except (ProcessLookupError, PermissionError):
                pass
        deadline = None if grace is None else time.monotonic() + grace
        for lane in lanes:
            lane.join(None if deadline is None else max(0.0, deadline - time.monotonic()))


def execute(root: Path, output: Path, steps: Sequence[Step], env: dict[str, str], *,
            cleanup: Sequence[Step] = (), alongside: Sequence[Step] = ()) -> int:
    """Run `steps`, and `alongside` at the same time as a second lane. A failed
    step ends its own lane; the other lane runs on, and cleanup waits for both."""
    before = source_state(root)
    runtime_before = runtime_state(root)
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    results: list[dict] = []
    running: dict[int, str] = {}
    stopping = threading.Event()
    lanes = [threading.Thread(target=run_lane, args=(index, lane, output, env, started, running, stopping, results))
             for index, lane in enumerate((steps, alongside)) if lane]
    interrupted = False
    try:
        for lane in lanes:
            lane.start()
        for lane in lanes:
            # A bounded join, so a signal reaches this thread while lanes run.
            while lane.is_alive():
                lane.join(0.1)
    except KeyboardInterrupt:
        interrupted = True
        stopping.set()
        stop(running, lanes)
    finally:
        for step in cleanup:
            results.append({**run_step(step, output, env, running), "lane": None,
                            "started_seconds": time.perf_counter() - started})
        after = source_state(root)
        runtime_after = runtime_state(root)
        changed = before["fingerprint"] != after["fingerprint"]
        environment_changed = runtime_before != runtime_after
        code = 76 if changed or environment_changed else 130 if interrupted else next((r["exit_code"] for r in results if r["exit_code"]), 0)
        report = {
            "schema_version": 1, "checkout": str(root), "source_before": before,
            "source_after": after, "source_changed": changed, "exit_code": code,
            "runtime_before": runtime_before, "runtime_after": runtime_after,
            "environment_changed": environment_changed,
            "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
            "wall_seconds": time.perf_counter() - started,
            "machine": {"platform": platform.platform(), "cpus": os.cpu_count(), "load_average": os.getloadavg()},
            "python": {"executable": sys.executable, "version": sys.version},
            "profile": {key: env.get(key) for key in (
                "ROLEBAND_CHECK_PROFILE", "ROLEBAND_REQUIRE_INTEGRATION", "ROLEBAND_UX_MODE",
                "ROLEBAND_UX_WORKERS", "ROLEBAND_UX_PORT", "ROLEBAND_PGDATA", "ROLEBAND_CHECK_TESTS",
                "ROLEBAND_CHECK_BROWSERS",
            )},
            "lanes": len(lanes),
            "steps": results,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        if changed or environment_changed:
            print("check-local: source or installed packages changed during the run; this result does not verify the current inputs", file=sys.stderr)
        print(f"check-local: report: {output / 'report.json'}", flush=True)
    return code


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("workers must be positive")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("profile", choices=("all", "backend", "dashboard", "unit", "ux"))
    parser.add_argument("--output", type=Path, help="new report directory outside the checkout")
    parser.add_argument("--backend-workers", type=positive_integer)
    parser.add_argument("--unit-workers", type=positive_integer)
    parser.add_argument("--ux-workers", type=positive_integer)
    parser.add_argument("--ci-parity", action="store_true", help="require backend integration tests instead of allowing local skips")
    parser.add_argument("--test", action="append", default=[], help="test file/node selector; only for backend, unit or ux profiles")
    parser.add_argument("--parallel", action="store_true", help="run the backend and dashboard lanes at the same time; only for the all profile")
    parser.add_argument("--docker-browsers", action="store_true",
                        help=f"build and run both browser projects in a Linux container (default {DOCKER_UX_WORKERS} workers); "
                             "only for all, dashboard or ux profiles")
    args = parser.parse_args(argv)

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    if args.test and args.profile not in ("backend", "unit", "ux"):
        parser.error("--test is only valid for backend, unit or ux profiles")
    if args.parallel and args.profile != "all":
        parser.error("--parallel is only valid for the all profile")
    if args.docker_browsers and args.profile not in ("all", "dashboard", "ux"):
        parser.error("--docker-browsers is only valid for all, dashboard or ux profiles")
    if args.docker_browsers and shutil.which("docker") is None:
        parser.error("--docker-browsers needs the docker CLI and a running Docker engine")
    root = Path(__file__).resolve().parents[1]
    if args.output and args.output.resolve().is_relative_to(root):
        parser.error("reports must be outside the checkout")
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="roleband-check-"))
    if args.output:
        try:
            output.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            parser.error("--output must be a new directory")
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "ROLEBAND_CHECK_PROFILE": args.profile,
           "ROLEBAND_CHECK_TESTS": json.dumps(args.test)}
    if args.ci_parity:
        env["ROLEBAND_REQUIRE_INTEGRATION"] = "1"
    python = sys.executable
    backend, dashboard = root / "backend", root / "dashboard"
    steps: list[Step] = []
    dashboard_steps: list[Step] = []
    cleanup: list[Step] = []
    if args.profile in ("all", "backend", "dashboard"):
        steps.extend(Step(name, root, [python, f"backend/scripts/{script}.py"]) for name, script in (
            ("comment-hygiene", "check_comment_hygiene"), ("project-name", "check_project_name"),
        ))
    if args.profile in ("all", "backend"):
        env.update(ROLEBAND_DATABASE_URL="", ROLEBAND_PGDATA=str(output / "postgres"))
        if not args.test:
            steps.extend([
                Step("ruff", backend, [python, "-m", "ruff", "check", "tracker", "tests", "scripts", "../sdk/python", "../robots/python", "../examples"]),
                Step("imports", backend, [str(Path(python).parent / "lint-imports")]),
                Step("mypy", backend, [python, "-m", "mypy"]),
            ])
        workers = ["-n", str(args.backend_workers)] if args.backend_workers else []
        steps.append(Step("pytest", backend, [python, "-m", "pytest", *workers,
                     "--durations=30", "-rs", f"--junitxml={output / 'pytest.xml'}",
                     f"--basetemp={output / 'pytest-temp'}", *args.test]))
        cleanup.append(Step("cluster-cleanup", backend, [python, "-c",
            ("import sys; from pathlib import Path; from tracker.supervisor.residue import stop_clusters; "
            "errors = stop_clusters(Path(sys.argv[1])); print('\\n'.join(errors)); sys.exit(bool(errors))"), str(output)]))
    if args.profile in ("all", "dashboard", "unit", "ux"):
        dashboard_steps.append(Step("node-version", dashboard, ["node", "--version"]))
        dashboard_steps.append(Step("npm-version", dashboard, ["npm", "--version"]))
        if args.profile in ("all", "dashboard"):
            dashboard_steps.append(Step("dashboard-lint", dashboard, ["npm", "run", "lint"]))
        if args.profile in ("all", "dashboard", "unit"):
            workers = [f"--maxWorkers={args.unit_workers}"] if args.unit_workers else []
            dashboard_steps.append(Step("vitest", dashboard, ["npm", "run", "test:unit", "--", "--reporter=default",
                         "--reporter=json", f"--outputFile={output / 'vitest.json'}", *workers, *args.test]))
        if args.profile in ("all", "dashboard", "ux") and args.docker_browsers:
            workers_in_docker = args.ux_workers or DOCKER_UX_WORKERS
            browser_steps, docker_cleanup = docker_browser_steps(root, output, python, workers_in_docker, args.test)
            env.update(ROLEBAND_CHECK_BROWSERS="docker", ROLEBAND_UX_MODE="preview", ROLEBAND_UX_PORT="4173",
                       ROLEBAND_UX_WORKERS=str(workers_in_docker))
            dashboard_steps.extend(browser_steps)
            cleanup.append(docker_cleanup)
        elif args.profile in ("all", "dashboard", "ux"):
            env.update(ROLEBAND_DIST_OUT=str(output / "dashboard-dist"), ROLEBAND_UX_MODE="preview",
                       ROLEBAND_UX_PORT=str(available_port()), ROLEBAND_UX_OUTPUT_DIR=str(output / "playwright"),
                       VITE_API_TARGET="http://127.0.0.1:9")
            if args.ux_workers:
                env["ROLEBAND_UX_WORKERS"] = str(args.ux_workers)
            dashboard_steps.append(Step("dashboard-build", dashboard, ["npm", "run", "build"]))
            dashboard_steps.append(Step("playwright", dashboard, ["npm", "run", "test:ux", "--", *args.test]))
    if args.parallel:
        return execute(root, output, steps, env, cleanup=cleanup, alongside=dashboard_steps)
    return execute(root, output, [*steps, *dashboard_steps], env, cleanup=cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
