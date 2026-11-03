"""The composition root composes. It re-exports nothing and rebinds nothing.

A root that copies attributes set on it into the router and helper modules
holding the same object lets a test monkeypatch the root and reach a handler's
real lookup site by accident: a patch changes code the test never named, and a
helper's owner cannot be found by reading its import. Tests patch where a name
is looked up (docs/testing.md).
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

import tracker.api.app as app_module
from tracker.api.routers import settings as settings_router

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


def test_the_app_module_is_an_ordinary_module():
    assert type(sys.modules["tracker.api.app"]) is types.ModuleType


def test_setting_a_name_on_the_composition_root_reaches_no_router(monkeypatch):
    """Setting a root attribute must not change a router's lookup site."""
    original = settings_router.apply_saved_scope_to_jobs
    monkeypatch.setattr(app_module, "apply_saved_scope_to_jobs", object(), raising=False)
    assert settings_router.apply_saved_scope_to_jobs is original


#: Empty, and kept as the ratchet: a router reaching into another router fails
#: by name, with no existing row to hide among.
KNOWN_CROSS_ROUTER_IMPORTS: dict[str, list[str]] = {}


def test_no_router_reaches_into_another_router():
    """A wire shape two surfaces send is not a route helper.

    Routers importing a serializer from another router make that router the
    accidental owner of everyone's shape: its clock pin becomes the one other
    contracts depend on, and finding the serializer means knowing which router
    had it first. Shared shapes live in `api/serializers/`; shared reads live in
    `db/queries/`. This is the ratchet that keeps it that way.
    """
    routers = Path(app_module.__file__).parent / "routers"
    offenders: dict[str, list[str]] = {}
    for path in sorted(routers.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reaches = sorted(
            f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("tracker.api.routers.")
            and node.module != f"tracker.api.routers.{path.stem}"
            for alias in node.names
        )
        if reaches:
            offenders[path.name] = reaches
    assert offenders == KNOWN_CROSS_ROUTER_IMPORTS, (
        "this set shrinks only: move the shared name to an owner both surfaces "
        "may import, do not add a row here"
    )
