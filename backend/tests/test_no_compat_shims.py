"""Compatibility shims are prohibited, including ones absent from the name list.

A re-export left at a module's old path means two import paths for one thing,
and a newcomer copies whichever they find first. None exist under
`platform/`, `connectors/`, `taxonomy/`, `analytics/` or `workflows/`; this file
is what keeps it that way.

Two checks, because each is blind to the other's half. The retired names are
listed so a reintroduced one fails BY NAME. The structural rule catches a shim
nobody thought to list: a module under `tracker/` whose whole body is imports
is a re-export, unless it is one of the documented `python -m` entrypoints.

A third check guards the other end of the same rule. "One import
path per module" is only half of it: the path people actually type lives in a
docstring, and a module that moves tiers takes its documented command with it.
Unread, a stale `python -m` line is invisible until someone runs it. Every
command named in `tracker/` or `scripts/` source must resolve to a module that
can actually be run, and so must every command in a doc that describes the
current system: a stale command in a doc is worse than a stale docstring.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

TRACKER = Path(__file__).resolve().parents[1] / "tracker"
PYPROJECT = TRACKER.parent / "pyproject.toml"

#: Old path -> where the code lives. The value is what an import should say.
RETIRED = {
    "tracker.adapters": "tracker.connectors.listing",
    "tracker.detail_connectors": "tracker.connectors.detail",
    "tracker.pipeline": "tracker.workflows.pipeline",
    "tracker.roles": "tracker.taxonomy.roles",
    "tracker.locations": "tracker.taxonomy.locations",
    "tracker.categories": "tracker.taxonomy.categories",
    "tracker.tracks": "tracker.taxonomy.tracks",
    "tracker.role_catalog": "tracker.taxonomy.role_catalog",
    "tracker.velocity": "tracker.analytics.velocity",
    "tracker.demand": "tracker.analytics.demand",
    "tracker.comp_stats": "tracker.analytics.comp_stats",
    "tracker.comp_trends": "tracker.analytics.comp_trends",
    "tracker.comp_package": "tracker.analytics.comp_package",
    "tracker.comp_split": "tracker.analytics.comp_split",
    "tracker.comp_residual": "tracker.analytics.comp_residual",
    "tracker.util": "tracker.platform.util",
    "tracker.paths": "tracker.platform.paths",
    "tracker.runlock": "tracker.platform.locks",
    # The leveling model: one package in the vocabulary tier.
    "tracker.profiles.level_map": "tracker.levels",
    "tracker.comp_providers.reference": "tracker.levels",
    "tracker.comp_providers.offer_policy": "tracker.levels.pay",
    "tracker.taxonomy.title_profiles": "tracker.levels.titles",
    # A CLI has one
    # import path, and the documented command must name the module that has the
    # code.
    "tracker.intelligence.backfill": "tracker.workflows.backfill_disclosed_comp",
    "tracker.prices.store": "tracker.profiles.prices",
    "tracker.prices.__main__": "tracker.profiles.prices",
    # Retry has one home, beside the retry loops; the TLS tier is an httpx
    # transport under those loops.
    "tracker.connectors.runtime.retry": "tracker.platform.http",
    "tracker.connectors.runtime.curl_transport": "tracker.connectors.runtime.tiers",
    "tracker.local_llm.duplicate_review": "tracker.intelligence.duplicate_review",
}

#: Import-only modules that are NOT shims: each is a command a maintainer runs
#: by hand (`python -m tracker.daily`, `deploy/run_daily.sh`, a manual tick or
#: watchdog pass), and moving the command breaks the hand that types it.
ENTRYPOINTS = {"daily", "discover_roles", "scheduler", "watchdog"}


def _resolves(name: str) -> bool:
    """Whether `name` can supply code. A deleted package leaves its `__pycache__/`
    behind in every checkout that ever imported it (git removes the sources, not
    the ignored bytecode), and that directory imports as an EMPTY namespace
    package: `find_spec` answers, yet nothing in it can be imported, because
    Python never loads bytecode from `__pycache__` without its source. So a
    namespace package with no
    `.py` under it does not count as resolving."""
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:  # its parent package is gone too
        return False
    if spec is None:
        return False
    if spec.origin is None and spec.submodule_search_locations is not None:
        return any(any(Path(location).glob("*.py")) for location in spec.submodule_search_locations)
    return True


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _is_main_guard(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and getattr(node.test.left, "id", None) == "__name__"
    )


def _import_only(path: Path) -> bool:
    body = [n for n in ast.parse(path.read_text()).body if not _is_docstring(n)]
    return bool(body) and all(
        isinstance(n, ast.Import | ast.ImportFrom) or _is_main_guard(n) for n in body
    )


@pytest.mark.parametrize("old", sorted(RETIRED))
def test_a_retired_import_path_does_not_resolve(old):
    assert not _resolves(old), f"{old} is back; import {RETIRED[old]} instead"
    assert _resolves(RETIRED[old]), f"the canonical home {RETIRED[old]} is missing"


def test_no_module_under_tracker_is_only_a_re_export():
    shims = sorted(
        str(path.relative_to(TRACKER.parent))
        for path in TRACKER.rglob("*.py")
        if path.name != "__init__.py"
        and "__pycache__" not in path.parts
        and _import_only(path)
        and not (path.parent == TRACKER and path.stem in ENTRYPOINTS)
    )
    assert not shims, f"re-export-only modules (import the real module instead): {shims}"


def test_every_entrypoint_is_still_a_runnable_command():
    """A stale allowlist entry would exempt a future shim of the same name."""
    for stem in sorted(ENTRYPOINTS):
        path = TRACKER / f"{stem}.py"
        assert path.is_file(), f"tracker/{stem}.py is gone; drop it from ENTRYPOINTS"
        tree = ast.parse(path.read_text())
        assert any(_is_main_guard(n) for n in tree.body), f"tracker/{stem}.py has no __main__ block"


def test_no_import_contract_names_a_retired_module():
    """import-linter fails on a missing LAYER, not on every list it reads: a
    forbidden contract naming a deleted module checks nothing and passes."""
    contracts = tomllib.loads(PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    named = []
    for contract in contracts:
        for key in ("layers", "source_modules", "forbidden_modules", "modules", "ignore_imports"):
            for entry in contract.get(key, []):
                named += [part.strip() for part in entry.replace("->", ":").replace("|", ":").split(":")]
    stale = sorted(
        {name for name in named if any(name == old or name.startswith(f"{old}.") for old in RETIRED)}
    )
    assert not stale, f"import contracts still name retired modules: {stale}"


#: `python -m <dotted.path>`. The trailing lookahead rejects `\w` as well as
#: `.`, which also blocks backtracking: in prose like `python -m tracker.<module>`
#: every shorter prefix is followed by a word character, so the whole match fails
#: rather than degrading to `tracker` (or `tracke`).
_COMMAND = re.compile(r"python -m ([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?![\w.])")


#: Docs that describe the current system, so a command in them is a promise.
REPO = TRACKER.parent.parent
LIVE_DOCS = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "docs/architecture.md",
    "docs/copy.md",
    "docs/development.md",
    "docs/field-authority.md",
    "docs/mcp.md",
    "docs/pay.md",
    "docs/plugins.md",
    "docs/testing.md",
    "docs/ui.md",
)


def _documented_commands() -> dict[str, list[str]]:
    """Every `python -m` command named in tracker/ or scripts/ source, or in a live doc."""
    commands: dict[str, list[str]] = {}

    def record(text: str, where: Path) -> None:
        for match in _COMMAND.finditer(text):
            commands.setdefault(match.group(1), []).append(str(where.relative_to(REPO)))

    for root in (TRACKER, TRACKER.parent / "scripts"):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    record(node.value, path)

    for name in LIVE_DOCS:
        path = REPO / name
        if path.is_file():
            record(path.read_text(), path)
    return commands


def _why_not_runnable(name: str) -> str | None:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError) as exc:
        return f"does not import ({exc})"
    if spec is None:
        return "no such module"
    if spec.submodule_search_locations is not None:
        return None if importlib.util.find_spec(f"{name}.__main__") else "package has no __main__.py"
    if not any(_is_main_guard(node) for node in ast.parse(Path(spec.origin).read_text()).body):
        return "no `if __name__ == \"__main__\"` block"
    return None


def test_every_documented_command_names_a_module_that_can_be_run():
    """A moved module takes its documented command with it, or the docs send the
    next reader to a path that does not exist."""
    commands = _documented_commands()
    assert len(commands) > 30, f"the extractor stopped finding commands: {sorted(commands)}"
    broken = {
        name: (why, sorted(set(commands[name])))
        for name in sorted(commands)
        if (why := _why_not_runnable(name))
    }
    assert not broken, f"documented `python -m` commands that do not run: {broken}"
