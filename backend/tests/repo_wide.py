"""Which test modules read past backend/, and so run on every pull request.

The backend workflow runs the whole suite only for a pull request that changes a path its
`changes` job watches. A test that reads a file above backend/ can be broken by a change to
any file, so it runs on every pull request: the workflow runs `-m repo_wide` when the
watched paths are untouched. A module is repo-wide when its source names a path above
backend/, or when it imports a `tests` helper that does. Marking a module by mistake costs
only time; missing one lets a pull request skip a check it can break, which
`tests/test_ci_workflow_triggers.py` guards with the paths the code under test reads.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: A path above backend/: the repository root by depth or by name, a parent of a parent, backend's
#: parent, or a relative `..`. Each also matches some paths inside backend/; marking those costs time only.
REACHES_PAST_BACKEND = re.compile(
    r"parents\[[2-9]\]|parents\[1\]\.parent|parent\.parent|\bREPO_ROOT\b|\bBACKEND(?:_DIR)?\.parent\b"
    r"|[\"']\.\./|/\s*[\"']\.\.[\"']|\bos\.pardir\b"
)


def _helpers(source: str) -> set[Path]:
    """The `tests` modules a source imports, as files beside this one."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found |= {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}
    names = (name.split(".", 1)[1] for name in found if name.startswith("tests."))
    return {path for name in names if (path := TESTS / f"{name.replace('.', '/')}.py").is_file()}


@cache
def reaches_past_backend(module: Path) -> bool:
    # Helpers may import each other, so the walk keeps the modules it has read.
    seen: set[Path] = set()
    pending = [module]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        source = current.read_text(encoding="utf-8")
        if REACHES_PAST_BACKEND.search(source):
            return True
        pending.extend(_helpers(source))
    return False
