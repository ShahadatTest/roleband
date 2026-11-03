"""A path-filtered workflow's filter covers every file its own steps read.

A workflow with `paths:` runs only when a changed file matches. When a step reads
a file the filter does not name, a change to that file alone schedules nothing,
and the check never runs: contract-drift diffing `dashboard/openapi.json`
without watching it, or watching neither its own exporter script nor the
dependency manifests that shape the schema.

The inputs are DERIVED from each workflow's steps rather than listed here: the
version files a setup action reads, `-r`/`-c` files, the module a `python -m`
runs and the first-party modules it imports directly, the manifests `npm ci` and
`npm run` read, and the paths `git diff --exit-code` compares. A step that starts
reading a new file fails this test until the filter names it. Cache keys are not
inputs — a stale cache changes speed, not the verdict — and deeper imports are a
workflow's own documented choice (contract-drift watches `backend/tracker/**`).
"""

from __future__ import annotations

import ast
import importlib.util
import posixpath
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
EVENTS = ("push", "pull_request")


def glob_regex(pattern: str) -> re.Pattern[str]:
    """GitHub's filter glob: `**` crosses `/`, `*` and `?` do not."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def covered(path: str, patterns: list[str]) -> bool:
    if any(p.startswith("!") for p in patterns):
        raise NotImplementedError("negated filters are not used here; teach this test first")
    return any(glob_regex(p).fullmatch(path) for p in patterns)


def path_filters(data: dict) -> dict[str, list[str]]:
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    on = data.get("on", data.get(True)) or {}
    if not isinstance(on, dict):
        return {}
    return {
        event: list(on[event]["paths"])
        for event in EVENTS
        if isinstance(on.get(event), dict) and "paths" in on[event]
    }


def _join(*parts: str) -> str:
    return posixpath.normpath(posixpath.join(*parts))


def _module_file(wd: str, dotted: str) -> str | None:
    """The repo file a dotted module name resolves to from `wd`, if first-party."""
    base = _join(wd, *dotted.split("."))
    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        if (REPO / candidate).is_file():
            return candidate
    return None


def _direct_imports(module_file: str, wd: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse((REPO / module_file).read_text())):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # `from a.b import c` may name module a/b/c.py or attribute c of a/b.
            names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        found |= {path for name in names if (path := _module_file(wd, name))}
    return found


def command_inputs(tokens: list[str], wd: str) -> set[str]:
    found: set[str] = set()
    for i, token in enumerate(tokens[:-1]):
        nxt = tokens[i + 1]
        if token in ("-r", "-c", "--requirement", "--constraint"):
            found.add(_join(wd, nxt))
        if token == "-m" and (module_file := _module_file(wd, nxt)):
            found.add(module_file)
            found |= _direct_imports(module_file, wd)
    if tokens[:2] == ["npm", "ci"]:
        found |= {_join(wd, "package.json"), _join(wd, "package-lock.json")}
    if tokens[:2] == ["npm", "run"]:
        found.add(_join(wd, "package.json"))
    if tokens[:3] == ["git", "diff", "--exit-code"]:
        found |= {_join(wd, arg) for arg in tokens[3:] if not arg.startswith("-")}
    return found


def step_inputs(name: str, data: dict) -> set[str]:
    inputs = {f".github/workflows/{name}"}
    for job in (data.get("jobs") or {}).values():
        default_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
        for step in job.get("steps") or []:
            config = step.get("with") or {}
            for key in ("python-version-file", "node-version-file"):
                if key in config:
                    inputs.add(config[key])
            wd = step.get("working-directory", default_wd)
            for line in str(step.get("run") or "").splitlines():
                try:
                    tokens = shlex.split(line, comments=True)
                except ValueError:
                    continue
                inputs |= command_inputs(tokens, wd)
    return {posixpath.normpath(p) for p in inputs}


def uncovered(name: str, data: dict) -> dict[str, list[str]]:
    inputs = step_inputs(name, data)
    return {
        event: sorted(p for p in inputs if not covered(p, patterns))
        for event, patterns in path_filters(data).items()
    }


def _filtered_workflows() -> list[str]:
    return sorted(
        wf.name for wf in WORKFLOWS.glob("*.yml") if path_filters(yaml.safe_load(wf.read_text()))
    )


@pytest.mark.parametrize("name", _filtered_workflows())
def test_every_file_a_step_reads_can_trigger_its_workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    missing = {event: paths for event, paths in uncovered(name, data).items() if paths}
    assert not missing, (
        f"{name}: a change to these files alone would not run the workflow that reads them: "
        f"{missing}. Add them to its `paths:` filter for every event."
    )


def test_contract_drift_inputs_are_derived_not_assumed():
    """The deriver must find the inputs that matter, or the test above is vacuous."""
    data = yaml.safe_load((WORKFLOWS / "contract-drift.yml").read_text())
    inputs = step_inputs("contract-drift.yml", data)
    for expected in (
        "dashboard/openapi.json",
        "dashboard/src/api.gen.ts",
        "backend/scripts/export_openapi.py",
        "backend/tracker/api/app.py",
        "backend/requirements.txt",
        "backend/constraints/linux-x86_64.txt",
        "dashboard/package-lock.json",
        ".python-version",
        ".nvmrc",
    ):
        assert expected in inputs, expected


def test_a_step_reading_an_unwatched_file_is_reported():
    """The control: a filter that forgets what its step reads must be caught."""
    data = {
        True: {"pull_request": {"paths": ["backend/tracker/**"]}},
        "jobs": {"j": {"steps": [{"run": "git diff --exit-code dashboard/openapi.json"}]}},
    }
    assert uncovered("demo.yml", data) == {
        "pull_request": [".github/workflows/demo.yml", "dashboard/openapi.json"]
    }


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("backend/tracker/api/app.py", "backend/**", True),
        ("backend/tracker/api/app.py", "backend/*", False),
        ("backend/requirements.txt", "backend/*", True),
        ("dashboard/openapi.json", "dashboard/src/**", False),
        (".nvmrc", ".nvmrc", True),
    ],
)
def test_github_glob_semantics(path, pattern, expected):
    assert covered(path, [pattern]) is expected



#: The workflows a pull request is judged by. They take no `paths:` filter: a
#: required check from a filtered workflow sits pending forever on a change the
#: filter skips, and a re-cut of the repository must run every one of them.
GATES = ("backend.yml", "contract-drift.yml", "dashboard.yml", "hygiene.yml", "mac-launcher.yml")


def triggers(data: dict) -> dict:
    on = data.get("on", data.get(True)) or {}
    return on if isinstance(on, dict) else {event: None for event in on}


@pytest.mark.parametrize("name", GATES)
def test_a_gate_workflow_runs_on_every_change(name):
    assert path_filters(yaml.safe_load((WORKFLOWS / name).read_text())) == {}


@pytest.mark.parametrize("name", sorted(wf.name for wf in WORKFLOWS.glob("*.yml")))
def test_every_workflow_can_be_run_by_hand(name):
    assert "workflow_dispatch" in triggers(yaml.safe_load((WORKFLOWS / name).read_text()))


def check_names(data: dict) -> list[str]:
    """The names GitHub gives a workflow's check runs, before any matrix suffix."""
    return [job.get("name", job_id) for job_id, job in (data.get("jobs") or {}).items()]


def shared_check_names(workflows: dict[str, dict]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for name, data in workflows.items():
        for check in check_names(data):
            owners.setdefault(check, []).append(name)
    return {check: names for check, names in owners.items() if len(names) > 1}


def test_no_two_gate_jobs_report_under_one_check_name():
    # Branch protection requires checks by name, so a name two gates share would let
    # one workflow's result stand in for the other's.
    gates = {name: yaml.safe_load((WORKFLOWS / name).read_text()) for name in GATES}
    assert shared_check_names(gates) == {}


def test_a_check_name_two_gates_share_is_reported():
    """The control for the test above."""
    gates = {
        "a.yml": {"jobs": {"checks": {}}},
        "b.yml": {"jobs": {"checks": {}, "lint": {"name": "b-lint"}}},
        "c.yml": {"jobs": {"build": {"name": "checks"}}},
    }
    assert shared_check_names(gates) == {"checks": ["a.yml", "b.yml", "c.yml"]}


def test_the_trigger_rules_see_a_filter_and_a_missing_manual_run():
    """The controls for the two tests above."""
    filtered = {True: {"push": {"branches": ["main"], "paths": ["docs/**"]}, "pull_request": None}}
    assert path_filters(filtered) == {"push": ["docs/**"]}
    assert "workflow_dispatch" not in triggers(filtered)
    assert "workflow_dispatch" in triggers({True: ["push", "workflow_dispatch"]})


# The Mac workflow is a gate, so it filters inside itself: its `changes` job lists the paths
# each tier watches, and `launcher/macos/Tools/ci_changes.py` decides with GitHub's globs.


def _mac_tiers() -> tuple[dict, list[str], list[str]]:
    data = yaml.safe_load((WORKFLOWS / "mac-launcher.yml").read_text())
    decide = next(step for step in data["jobs"]["changes"]["steps"] if step.get("id") == "decide")
    env = decide["env"]
    return data, _lines(env["NATIVE_PATHS"]), _lines(env["BUNDLE_PATHS"])


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _job_inputs(data: dict, job: str) -> set[str]:
    return step_inputs("mac-launcher.yml", {"jobs": {job: data["jobs"][job]}})


@pytest.mark.parametrize("job", ["build", "bundle"])
def test_each_mac_tier_watches_every_file_its_steps_read(job):
    data, native, bundle = _mac_tiers()
    watched = native if job == "build" else native + bundle
    missing = sorted(p for p in _job_inputs(data, job) if not covered(p, watched))
    assert not missing, f"mac-launcher `{job}` reads files its tier does not watch: {missing}"


def test_the_mac_tier_inputs_are_derived_not_assumed():
    """The control: the deriver finds what the tiers read, so the test above is not vacuous."""
    data, native, _ = _mac_tiers()
    build, bundle = _job_inputs(data, "build"), _job_inputs(data, "bundle")
    for expected in (".nvmrc", ".python-version", "dashboard/package-lock.json",
                     "launcher/macos/packaging-requirements.txt"):
        assert expected in build and expected in bundle, expected
    assert not covered("launcher/macos/packaging-requirements.txt", [p for p in native if p != "launcher/**"])


def test_the_build_tier_watches_the_backend_files_the_runtime_lock_check_reads():
    """`build` runs the launcher tool tests, and one holds `runtime-lock.txt` to the backend's
    macOS pins. Those reads sit inside Python, out of the step deriver's sight."""
    source = (REPO / "launcher" / "macos" / "Tools" / "bundle.py").read_text()
    body = source.split("def check_runtime_lock(", 1)[1].split("\ndef ", 1)[0]
    read = re.findall(r"root / '(backend/[^']+)'", body)
    assert read, "the runtime lock check reads no backend file"
    _, native, _ = _mac_tiers()
    assert not [path for path in read if not covered(path, native)]


def test_the_decision_script_reads_globs_as_this_test_does():
    spec = importlib.util.spec_from_file_location(
        "ci_changes", REPO / "launcher" / "macos" / "Tools" / "ci_changes.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    _, native, bundle = _mac_tiers()
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True)
    for path in tracked.stdout.split():
        assert script.matches(path, native + bundle) == covered(path, native + bundle), path


# The backend and dashboard gates filter the same way with one tier each (`TIER`, `PATHS`),
# which only a pull request can skip. Their inputs are what the jobs' steps read, plus what
# the code they test reads outside its own directory: the backend's code under test names
# repository files off the repository root, and the dashboard reaches files with `../`.
# The backend suite's own tests that read past backend/ run on every pull request
# (tests/repo_wide.py), so only the code they test needs watching.

ROOT_NAMES = {"REPO_ROOT"}
#: Paths the code names that no checkout run reads, each with the reason.
NOT_READ_IN_A_CHECKOUT = {
    ("backend/tracker/platform/paths.py", "dashboard"): "the installed app's layout; a checkout serves dashboard/dist",
}


def _gate_tier(name: str) -> tuple[dict, list[str]]:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    decide = next(step for step in data["jobs"]["changes"]["steps"] if step.get("id") == "decide")
    return data, _lines(decide["env"]["PATHS"])


def _tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True)
    return out.stdout.split()


def tracked_under(paths: set[str], tracked: list[str]) -> set[str]:
    """Each path as the tracked files it names: itself, or every file below a directory."""
    return {f for f in tracked for p in paths if f == p or f.startswith(p.rstrip("/") + "/")}


def _launched(tokens: list[str], wd: str) -> set[str]:
    """What a step hands its tools: a script it runs, a package it installs, what ruff lints."""
    found: set[str] = set()
    if len(tokens) > 1 and tokens[0] in ("python", "python3", "node") and not tokens[1].startswith("-"):
        found.add(_join(wd, tokens[1]))
    if tokens[:3] == ["pip", "install", "-e"]:
        found |= {_join(wd, arg) for arg in tokens[3:]}
    if tokens[:2] == ["ruff", "check"]:
        found |= {_join(wd, arg) for arg in tokens[2:] if not arg.startswith("-")}
    return found


def workflow_inputs(name: str, data: dict) -> set[str]:
    inputs = step_inputs(name, data)
    for job in data["jobs"].values():
        default_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
        for step in job.get("steps") or []:
            wd = step.get("working-directory", default_wd)
            for line in str(step.get("run") or "").splitlines():
                try:
                    inputs |= _launched(shlex.split(line, comments=True), wd)
                except ValueError:
                    continue
    return inputs


def _path_of(node: ast.expr, module: Path, names: dict[str, Path]) -> Path | None:
    """The path an expression names, as far as its constant parts go."""
    if isinstance(node, ast.Name):
        return module if node.id == "__file__" else names.get(node.id)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) == 1:
            return _path_of(node.args[0], module, names)
        if isinstance(node.func, ast.Name) and node.func.id == "backend_dir":
            return REPO / "backend"
        if isinstance(node.func, ast.Attribute) and node.func.attr == "resolve":
            return _path_of(node.func.value, module, names)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _path_of(node.value, module, names)
        return base.parent if base else None
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents" and isinstance(node.slice, ast.Constant)):
        base = _path_of(node.value.value, module, names)
        return base.parents[node.slice.value] if base else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = _path_of(node.left, module, names)
        if base and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            return base / node.right.value
        return base
    return None


def named_paths(module: Path, source: str) -> set[str]:
    """Repository paths a module builds with `/` from the repository root, outside backend/.

    A chain stops at its first part that is not a constant, so `ROOT / "docs" / name` names
    `docs`, the whole directory. A module-level name only joined onto later is a base, not a read.
    """
    tree = ast.parse(source)
    names = {name: REPO for name in ROOT_NAMES}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if (value := _path_of(node.value, module, names)) is not None:
                names[node.targets[0].id] = value
    divs = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)]
    lefts = {id(n.left) for n in divs}
    bases = {n.left.id for n in divs if isinstance(n.left, ast.Name)}
    base_values = {
        id(n.value) for n in tree.body
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id in bases
    }
    found: set[str] = set()
    for node in divs:
        if id(node) in lefts or id(node) in base_values:
            continue
        path = _path_of(node, module, names)
        if path and path.is_relative_to(REPO) and not path.is_relative_to(REPO / "backend"):
            found.add(path.relative_to(REPO).as_posix())
    return found


def backend_code_reads(tracked: list[str]) -> set[str]:
    found: set[str] = set()
    for relative in tracked:
        if not relative.startswith("backend/") or relative.startswith("backend/tests/") or not relative.endswith(".py"):
            continue
        module = REPO / relative
        found |= {
            path for path in named_paths(module, module.read_text(encoding="utf-8"))
            if (relative, path) not in NOT_READ_IN_A_CHECKOUT
        }
    return found


#: A `../` path in dashboard source, from the first part past the `../` steps.
RELATIVE = re.compile(r"""["'`](?:\.\./)+([^"'`$\s]+)""")


def reached_from(source: str, tops: set[str]) -> set[str]:
    """Paths outside dashboard/ that a dashboard file names through `../`.

    The base a `../` path starts from is not known here, so any whose first part is a
    top-level entry of the repository other than dashboard/ counts. A path built from bare
    `..` steps names no entry and is not seen.
    """
    return {
        path.rstrip("/") for path in RELATIVE.findall(source)
        if path.split("/", 1)[0] in tops and path.split("/", 1)[0] != "dashboard"
    }


def dashboard_code_reads(tracked: list[str]) -> set[str]:
    tops = {path.split("/", 1)[0] for path in tracked}
    found: set[str] = set()
    for path in tracked:
        if path.startswith("dashboard/") and (REPO / path).suffix in {
            ".ts", ".tsx", ".js", ".mjs", ".mts", ".cjs", ".json", ".jsonc", ".html",
        }:
            found |= reached_from((REPO / path).read_text(encoding="utf-8"), tops)
    return found


def tier_inputs(name: str, tracked: list[str]) -> set[str]:
    data, _ = _gate_tier(name)
    code = backend_code_reads(tracked) if name == "backend.yml" else dashboard_code_reads(tracked)
    return tracked_under(workflow_inputs(name, data) | code, tracked)


def unwatched(inputs: set[str], paths: list[str]) -> list[str]:
    return sorted(p for p in inputs if not covered(p, paths))


@pytest.mark.parametrize("name", ["backend.yml", "dashboard.yml"])
def test_each_gate_tier_watches_every_file_it_reads(name):
    _, paths = _gate_tier(name)
    missing = unwatched(tier_inputs(name, _tracked()), paths)
    assert not missing, f"{name}: a pull request changing only these would skip the jobs that read them: {missing}"


def test_the_gate_tier_inputs_are_derived_not_assumed():
    """The control: the deriver finds what each tier reads, so the test above is not vacuous."""
    tracked = _tracked()
    backend, dashboard = tier_inputs("backend.yml", tracked), tier_inputs("dashboard.yml", tracked)
    for expected in (".python-version", ".github/workflows/backend.yml", "backend/requirements.txt",
                     "launcher/macos/Tools/ci_changes.py", "launcher/macos/test-transport.py",
                     "sdk/python/pyproject.toml", "robots/python/pyproject.toml",
                     "dashboard/csp-policy.json", "CHANGELOG.md", "docs/sources.md"):
        assert expected in backend, expected
    for expected in (".nvmrc", "dashboard/package-lock.json", "launcher/macos/Tools/ci_changes.py",
                     "backend/tests/fixtures/notification_keys.json", "backend/tracker/skills/catalog.yaml",
                     "launcher/contracts/status-cases.json"):
        assert expected in dashboard, expected
    _, paths = _gate_tier("backend.yml")
    assert unwatched(backend, [p for p in paths if p != "dashboard/csp-policy.json"]) == ["dashboard/csp-policy.json"]


def test_the_code_readers_see_a_path_built_from_the_root_or_reached_with_dots():
    """The controls for the two code readers."""
    module = REPO / "backend" / "scripts" / "demo.py"
    source = (
        'ROOT = Path(__file__).resolve().parents[2]\n'
        'DOCS = ROOT / "docs"\n'
        'GUIDE = DOCS / "testing.md"\n'
        'POLICY = REPO_ROOT / "dashboard" / "csp-policy.json"\n'
        'def page(name):\n'
        '    return ROOT / "docs" / name\n'
        'LOCAL = Path(__file__).parent / "fixtures" / "x.json"\n'
    )
    assert named_paths(module, source) == {"docs/testing.md", "dashboard/csp-policy.json", "docs"}
    tops = {"backend", "launcher", "dashboard", "docs"}
    source = (
        'import data from "../../../../backend/tests/fixtures/a.json";\n'
        'const tracker = join(src, "../../backend/tracker");\n'
        'import { x } from "../../api/client";\n'
        'import { y } from "../dashboard/src/z";\n'
    )
    assert reached_from(source, tops) == {"backend/tests/fixtures/a.json", "backend/tracker"}


@pytest.mark.parametrize("name", ["backend.yml", "dashboard.yml"])
def test_the_gate_decision_reads_globs_as_this_test_does(name):
    spec = importlib.util.spec_from_file_location(
        "ci_changes", REPO / "launcher" / "macos" / "Tools" / "ci_changes.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    _, paths = _gate_tier(name)
    for path in _tracked():
        assert script.matches(path, paths) == covered(path, paths), path


def matrix_jobs_skipped_whole(data: dict) -> list[str]:
    """Matrix jobs whose `if:` depends on a tier: skipped whole, they report one unsuffixed check."""
    return sorted(
        job_id for job_id, job in (data.get("jobs") or {}).items()
        if "matrix" in (job.get("strategy") or {}) and "needs.changes.outputs" in str(job.get("if", ""))
    )


@pytest.mark.parametrize("name", GATES)
def test_no_matrix_job_is_skipped_whole(name):
    assert matrix_jobs_skipped_whole(yaml.safe_load((WORKFLOWS / name).read_text())) == []


def test_a_matrix_job_skipped_whole_is_reported():
    """The control for the test above."""
    data = {"jobs": {
        "ux": {"if": "needs.changes.outputs.dashboard == 'true'", "strategy": {"matrix": {"shard": [1, 2]}}},
        "steps": {"if": "${{ !cancelled() }}", "strategy": {"matrix": {"shard": [1, 2]}}},
        "lint": {"if": "needs.changes.outputs.dashboard == 'true'"},
    }}
    assert matrix_jobs_skipped_whole(data) == ["ux"]


@pytest.mark.parametrize("name", ["backend.yml", "dashboard.yml"])
def test_a_failed_decision_runs_the_gate(name):
    """A job after `changes` runs when the decision fails, and reads an empty answer as yes."""
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    for job_id, job in data["jobs"].items():
        if job.get("needs") == "changes":
            assert "!cancelled()" in job["if"], job_id
            assert "== 'true'" not in job["if"], job_id


def test_the_backend_runs_its_repo_wide_tests_whatever_changed():
    data = yaml.safe_load((WORKFLOWS / "backend.yml").read_text())
    pytest_steps = {
        step["if"]: step["run"] for step in data["jobs"]["checks"]["steps"] if "pytest" in str(step.get("run", ""))
    }
    assert pytest_steps.keys() == {"env.WHOLE_SUITE == 'true'", "env.WHOLE_SUITE != 'true'"}
    assert "repo_wide" not in pytest_steps["env.WHOLE_SUITE == 'true'"]
    assert "-m repo_wide" in pytest_steps["env.WHOLE_SUITE != 'true'"]


def shard_gaps(job: dict) -> list[str]:
    """How a sharded job's matrix and its `--shard INDEX/TOTAL` runs disagree."""
    shards = sorted((job.get("strategy") or {}).get("matrix", {}).get("shard") or [])
    gaps = []
    for step in job.get("steps") or []:
        run = str(step.get("run") or "")
        if "pytest" not in run:
            continue
        found = re.search(r"--shard=\$\{\{ matrix\.shard \}\}/(\d+)\b", run)
        if not found:
            gaps.append(f"{step.get('name')}: runs the whole selection on every shard")
        elif shards != list(range(1, int(found.group(1)) + 1)):
            gaps.append(f"{step.get('name')}: cuts {found.group(1)} shards, the matrix runs {shards}")
    return gaps


def test_the_backend_shards_together_run_the_whole_suite():
    """Too few shards for the cut leaves files unrun with every check green; one
    pytest step without the cut runs the suite on each shard."""
    data = yaml.safe_load((WORKFLOWS / "backend.yml").read_text())
    assert shard_gaps(data["jobs"]["checks"]) == []


def test_a_shard_cut_the_matrix_does_not_match_is_reported():
    job = {
        "strategy": {"matrix": {"shard": [1, 2]}},
        "steps": [
            {"name": "three", "run": "python -m pytest --shard=${{ matrix.shard }}/3"},
            {"name": "whole", "run": "python -m pytest -m repo_wide"},
            {"name": "two", "run": "python -m pytest --shard=${{ matrix.shard }}/2"},
            {"name": "lint", "run": "ruff check tracker"},
        ],
    }
    assert shard_gaps(job) == [
        "three: cuts 3 shards, the matrix runs [1, 2]",
        "whole: runs the whole selection on every shard",
    ]


def test_the_required_backend_check_passes_only_when_every_shard_did():
    """The ruleset requires `backend`; the shards report under their own names, so
    the one job named `backend` has to stand for all of them, even when one fails."""
    jobs = yaml.safe_load((WORKFLOWS / "backend.yml").read_text())["jobs"]
    named = [job for job in jobs.values() if job.get("name") == "backend"]
    assert len(named) == 1
    result = named[0]
    assert result["needs"] == "checks"
    assert "!cancelled()" in result["if"]
    step = result["steps"][-1]
    assert step["env"]["SHARDS"] == "${{ needs.checks.result }}"
    assert 'test "$SHARDS" = success' in step["run"]
