"""The adapter-privacy contract must cover EVERY adapter, not the ones someone
remembered, and keep EVERY layer above the adapters from importing one.

`pyproject.toml`'s `forbidden_modules` list is what stops `api`, `workflows`
and friends importing a concrete adapter instead of going through the
registry. Written by hand, it drifts: an adapter shipped and never added is
importable from anywhere while `lint-imports` reports every contract kept.

A hand-maintained enumeration of a registry is a gate that stops matching what
it guards the moment the registry grows. This derives the expectation from
`ADAPTER_REGISTRY` itself, so the next adapter fails here until it is covered.
The importing side is derived the same way, from the layer rows: every package
above the adapters' row is a source, so a new service package is covered the
day it gets a row. Rows below it are held by the layers contract already.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from tracker.connectors.listing import ADAPTER_REGISTRY

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
_CONTRACT = "Concrete adapters are private to the registry"


_LAYERS = "Backend layers (strictly downward)"


def _contract(name: str) -> dict:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    for contract in data["tool"]["importlinter"]["contracts"]:
        if contract["name"] == name:
            return contract
    raise AssertionError(f"contract {name!r} is gone from pyproject.toml")


def _forbidden_modules() -> list[str]:
    return _contract(_CONTRACT)["forbidden_modules"]


def _above_the_adapters() -> list[str]:
    """Every layer member in the rows above the one `tracker.connectors` sits in."""
    members: list[str] = []
    for row in _contract(_LAYERS)["layers"]:
        names = [name.strip() for name in row.replace("|", ":").split(":")]
        if "tracker.connectors" in names:
            return members
        members.extend(names)
    raise AssertionError("no layer row names tracker.connectors")


def test_every_registered_adapter_is_private_to_the_registry() -> None:
    forbidden = set(_forbidden_modules())
    # By the class's MODULE, not its registry key: one module may hold several
    # adapters (SmartRecruiters' two routes).
    missing = sorted(
        {cls.__module__ for cls in ADAPTER_REGISTRY.values()} - forbidden
    )
    assert not missing, (
        "these adapters are in ADAPTER_REGISTRY but not in pyproject.toml's "
        f"forbidden_modules, so any layer may import them directly: {missing}"
    )


def test_the_contract_names_no_adapter_that_no_longer_exists() -> None:
    # The other direction: a deleted adapter left in the list makes
    # import-linter error on an unresolvable module rather than pass silently.
    listing = {cls.__module__ for cls in ADAPTER_REGISTRY.values()}
    stale = sorted(
        module
        for module in _forbidden_modules()
        if module.startswith("tracker.connectors.listing.")
        and module not in listing
    )
    assert not stale, f"forbidden_modules names adapters that are gone: {stale}"


def test_every_layer_above_the_adapters_is_kept_from_importing_one() -> None:
    sources = _contract(_CONTRACT)["source_modules"]
    expected = _above_the_adapters()
    assert sorted(sources) == sorted(expected), (
        "source_modules must be every package above the adapters' layer row. "
        f"Missing: {sorted(set(expected) - set(sources))}; "
        f"not in a row above: {sorted(set(sources) - set(expected))}"
    )
