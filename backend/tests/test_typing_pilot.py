"""The typed-boundary pilot: a narrow set that is honest, and stays that way.

What makes it look expensive is not the code: mypy follows imports by default,
so the entries in `[tool.mypy] files` drag in modules nobody put in the set and
report their errors. `follow_imports = silent` keeps the report to the set.

Four claims, because the first one alone can pass for the wrong reason:

1. the configured set type-checks clean;
2. it really checked something — a config that names nothing also "succeeds";
3. nothing in it was made green by muting rather than fixing;
4. the set may grow and may not shrink.

Never add `ignore_errors` or widen a return to `Any` to get this green. Muting
is the one change that looks identical to fixing from outside.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_PYPROJECT = _BACKEND / "pyproject.toml"

#: The recorded set. A ratchet, compared as a SUBSET: adding a module needs no
#: edit here, removing one fails by name. The checked set is recorded and
#: expanded with each extraction, never quietly narrowed.
FROZEN: frozenset[str] = frozenset(
    {
        "tracker/schema.py",
        "tracker/pay_disclosure.py",
        "tracker/source_review.py",
        "tracker/vendored.py",
        "tracker/blueprint.py",
        "tracker/api/schemas",
        "tracker/platform/paging.py",
        "tracker/platform/ratelimit.py",
        "tracker/workflows/schedule_status.py",
        "tracker/workflows/tuning.py",
        "tracker/connectors/recipes/outcome.py",
        "tracker/db/ownership.py",
        "tracker/connectors/__init__.py",
        "tracker/connectors/listing",
        "tracker/connectors/runtime",
    }
)


def _config() -> dict:
    return tomllib.loads(_PYPROJECT.read_text())["tool"]["mypy"]


def _run_mypy(*args: str, cwd: Path = _BACKEND) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mypy", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# 1-2. It passes, and it checked something
# --------------------------------------------------------------------------- #


def test_the_checked_set_type_checks_clean():
    run = _run_mypy()
    assert run.returncode == 0, (
        "the typed-boundary pilot does not pass:\n"
        + (run.stdout or run.stderr)[-3000:]
        + "\n\nFix the types. Do not add `ignore_errors` or return `Any` — a test below "
        "fails on both, because muting looks identical to fixing from outside."
    )


def test_it_actually_checked_the_files_it_names():
    """A config naming nothing reports success just as loudly.

    mypy prints the file count it checked, so the claim "clean" is only worth
    anything beside the claim "and there was something to check".
    """

    run = _run_mypy()
    assert "no issues found in" in run.stdout, run.stdout[-2000:]
    checked = int(run.stdout.split("no issues found in")[1].split()[0])
    assert checked >= len(FROZEN), (
        f"mypy checked {checked} files but the frozen set names {len(FROZEN)} entries. "
        "A path that stopped resolving makes the pilot pass by checking nothing."
    )


def test_mypy_reports_a_planted_error(tmp_path):
    """The control: the runner is wired up and would fail if there were a fault.

    Without this, every assertion above is satisfied by a mypy that cannot run —
    a missing plugin, a bad interpreter, an exit code nobody reads.
    """

    planted = tmp_path / "planted.py"
    planted.write_text("def f() -> int:\n    return 'not an int'\n")
    run = _run_mypy("--follow-imports=silent", "--no-incremental", str(planted), cwd=tmp_path)
    assert run.returncode != 0, f"mypy accepted a str returned from `-> int`: {run.stdout}"
    assert "return-value" in run.stdout or "Incompatible return" in run.stdout, run.stdout[-1000:]


# --------------------------------------------------------------------------- #
# 3. Green by fixing, not by muting
# --------------------------------------------------------------------------- #


def test_no_blanket_ignore_errors_on_our_own_modules():
    config = _config()
    assert "ignore_errors" not in config, (
        "`ignore_errors` at the top of [tool.mypy] mutes the whole pilot. Remove the "
        "module from `files` instead — a shrunken set is at least visible, and the "
        "ratchet below will say so."
    )
    muted = [
        module
        for override in config.get("overrides", [])
        if override.get("ignore_errors")
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
        if module.startswith("tracker")
    ]
    assert not muted, (
        f"these of our own modules are muted with `ignore_errors`: {muted}. An override may "
        "silence a third-party package that ships no stubs; it may not silence us."
    )


def test_overrides_only_silence_third_party_imports():
    """`ignore_missing_imports` is for packages without stubs, not for our code."""

    stray = [
        module
        for override in _config().get("overrides", [])
        if override.get("ignore_missing_imports")
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
        if module.startswith("tracker")
    ]
    assert not stray, f"`ignore_missing_imports` names our own modules: {stray}"


# --------------------------------------------------------------------------- #
# 4. The set may grow and may not shrink
# --------------------------------------------------------------------------- #


def test_the_checked_set_only_grows():
    configured = set(_config()["files"])
    dropped = sorted(FROZEN - configured)
    assert not dropped, (
        f"these modules left the typed set: {dropped}. It expands with each extraction and "
        "never narrows; if a module genuinely moved, update FROZEN in the same change and say "
        "where it went."
    )


def test_every_checked_path_exists():
    missing = sorted(p for p in _config()["files"] if not (_BACKEND / p).exists())
    assert not missing, f"[tool.mypy] files names paths that do not exist: {missing}"


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("follow_imports", "silent"),
        # Any version, as long as one is named.
        ("python_version", None),
        ("check_untyped_defs", True),
        ("disallow_incomplete_defs", True),
        ("warn_unused_ignores", True),
    ],
)
def test_the_settings_the_pilot_depends_on_are_pinned(setting, value):
    """`follow_imports = silent` is load-bearing, not tidiness.

    Dropping it does not fail loudly — it fails with errors in files nobody
    put in the set, which reads as "typing this codebase is impossible".

    The completeness flags fail quietly the other way: without them a
    parameter left unannotated is `Any`, and so is everything its body does
    with it, and a function with no annotations at all is not checked.
    """

    configured = _config().get(setting)
    if value is None:
        assert configured is not None, f"[tool.mypy] names no {setting}"
    else:
        assert configured == value, f"[tool.mypy] {setting} is {configured!r}, not {value!r}"
