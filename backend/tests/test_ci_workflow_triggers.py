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
