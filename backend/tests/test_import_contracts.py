"""The layer contract is enforced, complete, and shrinking.

`lint-imports` can report every contract kept while three holes sit underneath
that verdict:

1. **Membership is optional.** With `exhaustive = false`, a module named in no
   layer row is unconstrained: it may import anything and be imported by
   anything, and the report still says KEPT.
2. **The allowlist can grow.** `ignore_imports` is a ratchet ("shrink only,
   never add") in prose only. Adding a line to it is the easiest way to make a
   layering violation disappear.
3. **Nothing proves the rules fire.** A contract that names a module which
   moved, or a delimiter that means the opposite of what the comment claims,
   checks nothing and reports KEPT (the adapter list drifts the same way, see
   `test_import_contract_registry.py`).

The obvious fix -- `exhaustive = true` -- is not available. It requires
`containers`, which rewrites every layer name into tail form (`api` rather than
`tracker.api`), and `test_no_compat_shims.py::test_no_import_contract_names_a_retired_module`
matches retired names by their `tracker.`-prefixed spelling. Turning the flag on
would silently blind that gate. So membership is asserted here instead, where
the assertion is visible and the failure names the module.

The third check is the one that makes the other two worth anything. It builds a
skeleton package **from the live contract text** -- every module the contracts
name, and nothing else -- plants one import into it, and runs the real linter
over it in a subprocess. A contract that stopped constraining anything cannot
survive its planted edge. The L4 sibling case is the positive control: that row
is deliberately `:` (siblings MAY import), so it must pass, which is what
distinguishes "the rules fire" from "everything fails".
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
TRACKER = BACKEND / "tracker"
PYPROJECT = BACKEND / "pyproject.toml"

LAYERS = "Backend layers (strictly downward)"
ADAPTERS = "Concrete adapters are private to the registry"
CONNECTORS = "Listing and detail connectors are independent"
TRANSPORTS = "API and MCP are independent transports"

#: Permanent exemptions, not debt: `ARTIFACT_CHECKS` in `tracker/blueprint.py`
#: deliberately reaches upward and is exercised at test time
#: (docs/architecture.md). This set is exact in both directions --
#: losing one means the blueprint changed shape and the contract should say so.
PERMANENT = frozenset(
    {
        "tracker.blueprint -> tracker.connectors",
    }
)

#: Debt: real layering violations. The set stays, empty, because it IS the
#: ratchet -- an edge that comes back fails by name, with no existing debt to
#: hide among.
DEBT: frozenset[str] = frozenset()

#: The one connector exemption plus the same blueprint exemption. Frozen for the same reason as the layers allowlist.
CONNECTOR_IGNORES = frozenset(
    {
        "tracker.connectors.listing.apple -> tracker.connectors.detail",
        "tracker.blueprint -> tracker.connectors",
    }
)

ALLOWED_IGNORES = {
    LAYERS: PERMANENT | DEBT,
    ADAPTERS: frozenset(),
    CONNECTORS: CONNECTOR_IGNORES,
    TRANSPORTS: frozenset(),
}


# --------------------------------------------------------------------------- #
# Reading the live configuration
# --------------------------------------------------------------------------- #


def _contracts() -> list[dict]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"][
        "contracts"
    ]


def _contract(name: str) -> dict:
    for contract in _contracts():
        if contract["name"] == name:
            return contract
    raise AssertionError(f"contract {name!r} is gone from pyproject.toml")


def _layer_members() -> list[str]:
    """Every module named in a layer row, one row's siblings flattened out.

    Both delimiters are split: `:` (siblings may import each other) and `|`
    (they may not) describe the row's internal rule, not its membership.
    """
    members: list[str] = []
    for row in _contract(LAYERS)["layers"]:
        members += [part.strip() for part in row.replace("|", ":").split(":")]
    return members


def _tracker_roots() -> set[str]:
    """Top-level importable names under `tracker/`, as the contracts spell them."""
    roots = set()
    for path in TRACKER.iterdir():
        if path.name == "__pycache__":
            continue
        if path.is_dir() and (path / "__init__.py").is_file():
            roots.add(f"tracker.{path.name}")
        elif path.suffix == ".py" and path.name != "__init__.py":
            roots.add(f"tracker.{path.stem}")
    return roots


# Pure, so the checks below can be run against a fabricated layout as a control.
def _unplaced(roots: set[str], members: set[str]) -> list[str]:
    return sorted(roots - members)


def _phantom(roots: set[str], members: set[str]) -> list[str]:
    return sorted(members - roots)


def _added(live: set[str], allowed: frozenset[str]) -> list[str]:
    return sorted(live - allowed)


# --------------------------------------------------------------------------- #
# 1. Membership
# --------------------------------------------------------------------------- #


def test_every_module_under_tracker_is_placed_in_a_layer():
    unplaced = _unplaced(_tracker_roots(), set(_layer_members()))
    assert not unplaced, (
        "these are importable roots under tracker/ that no layer row names, so the layers "
        f"contract does not constrain them in either direction: {unplaced}. Add each to the "
        "row for its tier in pyproject.toml (docs/architecture.md)."
    )


def test_no_layer_names_a_module_that_does_not_exist():
    """A row naming a moved module checks nothing; import-linter only errors on
    a missing module when it is a layer, and not for every list it reads."""
    phantom = _phantom(_tracker_roots(), set(_layer_members()))
    assert not phantom, f"layer rows name modules that are not under tracker/: {phantom}"


def test_no_module_is_named_in_two_layers():
    members = _layer_members()
    twice = sorted({name for name in members if members.count(name) > 1})
    assert not twice, f"named in more than one layer row, so its tier is ambiguous: {twice}"


def test_the_membership_check_notices_a_root_that_was_never_placed():
    """Negative control. `test_every_module_under_tracker_is_placed_in_a_layer`
    passing has to mean the rows cover the tree, not that the comparison is
    vacuous -- an empty answer from a broken reader looks identical."""
    roots = _tracker_roots()
    members = set(_layer_members())
    # Measured as a delta, so this stays a control on the reader rather than a
    # second copy of the membership assertion above.
    seen = set(_unplaced(roots, members))
    assert set(_unplaced(roots | {"tracker.not_a_real_package"}, members)) - seen == {
        "tracker.not_a_real_package"
    }
    known = set(_phantom(roots, members))
    assert set(_phantom(roots, members | {"tracker.also_not_real"})) - known == {
        "tracker.also_not_real"
    }


# --------------------------------------------------------------------------- #
# 2. The allowlist ratchet
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(ALLOWED_IGNORES))
def test_no_contract_gained_an_ignored_import(name):
    added = _added(set(_contract(name).get("ignore_imports", [])), ALLOWED_IGNORES[name])
    assert not added, (
        f"{name} gained ignored imports: {added}. ignore_imports is a ratchet -- it shrinks "
        "when a slice moves the code, and never grows to silence a new violation. If the "
        "exemption is genuinely permanent, say so here and in pyproject.toml."
    )


def test_the_permanent_exemptions_are_exactly_the_blueprint_reaches():
    """Unlike the debt, these are not expected to leave: losing one means
    `ARTIFACT_CHECKS` changed shape and the contract should have been updated."""
    live = set(_contract(LAYERS).get("ignore_imports", []))
    assert live & PERMANENT == PERMANENT, (
        f"permanent blueprint exemptions are missing from pyproject.toml: "
        f"{sorted(PERMANENT - live)}"
    )


def test_the_debt_allowlist_has_only_shrunk():
    live = set(_contract(LAYERS).get("ignore_imports", [])) - PERMANENT
    assert live <= DEBT, f"new layering debt was added: {sorted(live - DEBT)}"


def test_the_debt_allowlist_names_no_edge_that_is_already_gone():
    """The other direction, and it is not cosmetic. The shrink rule above is
    `live <= DEBT`, so a slice that drops an entry from `pyproject.toml` and
    forgets this file leaves a name here guarding nothing, unnoticed until
    someone needs the set empty. A stale allowlist is the drift this file
    exists to catch."""
    live = set(_contract(LAYERS).get("ignore_imports", []))
    assert not DEBT - live, (
        f"DEBT names edges pyproject.toml no longer has: {sorted(DEBT - live)}"
    )


def test_the_ratchet_notices_a_new_entry():
    """Fail-first control on a parsed copy: the comparison above has to be able
    to see an addition."""
    live = set(_contract(LAYERS).get("ignore_imports", []))
    assert _added(live | {"tracker.config -> tracker.db"}, PERMANENT | DEBT) == [
        "tracker.config -> tracker.db"
    ]
    assert _added(live, PERMANENT | DEBT) == []


# --------------------------------------------------------------------------- #
# 3. Efficacy: the contracts fire on a skeleton built from their own text
# --------------------------------------------------------------------------- #

_RUNNER = """
import sys
from importlinter.cli import lint_imports
sys.exit(lint_imports(config_filename="pyproject.toml", no_cache=True))
"""


@dataclass(frozen=True)
class Planted:
    """One import written into the skeleton, and the verdict it must produce."""

    id: str
    importer: str | None
    imported: str | None
    ignore: str | None
    broken: str | None


CASES = [
    # Positive control. The L4 row is `:` on purpose (same-layer imports are
    # allowed in L4) and holds many importing pairs. If this one
    # fails, the skeleton is rejecting everything and proves nothing.
    Planted("l4-siblings-may-import", "tracker.enrich", "tracker.db", None, None),
    Planted("upward-import-is-refused", "tracker.taxonomy", "tracker.db", None, LAYERS),
    Planted("l3-siblings-are-independent", "tracker.connectors", "tracker.prices", None, LAYERS),
    Planted(
        "a-concrete-adapter-is-private",
        "tracker.api",
        "tracker.connectors.listing.amazon",
        None,
        ADAPTERS,
    ),
    Planted("the-two-transports-stay-apart", "tracker.api", "tracker.mcp", None, TRANSPORTS),
    Planted("an-unmatched-ignore-is-an-error", None, None, "tracker.api -> tracker.db", None),
]


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        assert all(isinstance(item, str) for item in value), value
        return "[" + ", ".join(f'"{item}"' for item in value) + "]"
    raise AssertionError(f"unexpected contract value {value!r}")


@pytest.fixture(scope="module")
def skeleton(tmp_path_factory) -> Path:
    """An empty package tree holding exactly the modules the live contracts name.

    Generated rather than written out: a hand-listed skeleton stops matching the
    contracts the moment a row changes, which is the failure mode this whole
    file exists to catch.
    """
    root = tmp_path_factory.mktemp("import_contract_skeleton")
    named: set[str] = set()
    for contract in _contracts():
        for row in contract.get("layers", []):
            named |= {part.strip() for part in row.replace("|", ":").split(":")}
        for key in ("source_modules", "forbidden_modules", "modules"):
            named |= set(contract.get(key, []))
    assert "tracker.api" in named, named

    for name in sorted(named):
        directory = root
        for part in name.split("."):
            directory = directory / part
            directory.mkdir(exist_ok=True)
            (directory / "__init__.py").touch()
    return root


def _write_config(skeleton: Path, ignore: str | None) -> None:
    lines = ["[tool.importlinter]", 'root_packages = ["tracker"]', ""]
    for contract in _contracts():
        lines.append("[[tool.importlinter.contracts]]")
        for key, value in contract.items():
            # Dropped wholesale: the skeleton has no real edges, so every live
            # exemption would be unmatched, and an unmatched ignore is an error.
            if key == "ignore_imports":
                continue
            lines.append(f"{key} = {_toml_value(value)}")
        if ignore and contract["name"] == LAYERS:
            lines.append(f"ignore_imports = {_toml_value([ignore])}")
        lines.append("")
    (skeleton / "pyproject.toml").write_text("\n".join(lines), encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_a_planted_edge_produces_the_verdict_the_contract_promises(skeleton, case):
    for path in skeleton.rglob("__init__.py"):
        path.write_text("", encoding="utf-8")
    if case.importer:
        target = skeleton.joinpath(*case.importer.split(".")) / "__init__.py"
        target.write_text(f"import {case.imported}\n", encoding="utf-8")
    _write_config(skeleton, case.ignore)

    result = subprocess.run(
        [sys.executable, "-c", _RUNNER],
        cwd=skeleton,
        capture_output=True,
        text=True,
    )
    report = result.stdout + result.stderr

    if case.ignore:
        assert result.returncode != 0, report
        assert "No matches for ignored import" in report, report
        return

    # The linter finds its graph on sys.path, and the real `tracker` is
    # installed in this interpreter. If cwd ever stopped winning, the run would
    # silently grade the actual codebase instead of the skeleton.
    analyzed = re.search(r"Analyzed (\d+) files", report)
    assert analyzed and int(analyzed.group(1)) < 200, (
        f"the linter analyzed the real tracker package, not the skeleton: {report}"
    )

    if case.broken is None:
        assert result.returncode == 0, report
        assert "0 broken" in report, report
    else:
        assert result.returncode != 0, report
        assert f"{case.broken} BROKEN" in report, report
        assert report.count("BROKEN") == 1, (
            f"the planted edge was meant to break {case.broken} alone: {report}"
        )


# --------------------------------------------------------------------------- #
# 4. Tier purity at runtime
# --------------------------------------------------------------------------- #

_TIER_PROBE = """
import importlib, json, sys
importlib.import_module(sys.argv[1])
print(json.dumps(sorted({
    ".".join(name.split(".")[:2]) for name in sys.modules if name.startswith("tracker.")
})))
"""

#: (module, roots it must NOT pull in, roots it MUST pull in).
#: The second column is the claim; the third is that row's positive control.
TIER_PROBES = [
    # The vocabulary tier tallies postings and states its own input as a
    # Protocol, so nothing about the catalog's shape needs a service tier.
    ("tracker.taxonomy.role_catalog", ("tracker.db", "tracker.enrich"), ()),
    # The writer that owns the persistence. Without this row an
    # empty answer above would be indistinguishable from a blind probe.
    ("tracker.scope.catalog_store", (), ("tracker.db",)),
    # `api/routers/statistics.py` and `scripts/report_equity_residuals.py`
    # import this for `TASK` alone. It loads `tracker.intelligence` and nothing
    # else; the pass that needs the store is next door.
    ("tracker.intelligence.extract", ("tracker.db", "tracker.settings_store"), ()),
    ("tracker.intelligence_runtime.disclosed_comp", (), ("tracker.db", "tracker.settings_store")),
    # The price provider is an L3 implementation. Its store is in the service
    # tier, and a provider must not follow it up.
    ("tracker.prices.provider", ("tracker.db", "tracker.profiles"), ()),
    ("tracker.profiles.prices", (), ("tracker.db", "tracker.prices")),
    # The pay-band vocabulary. Two callers with nothing else in common (the L3
    # detail parsers and the L4 pass), so it must carry no tier with it. It
    # imports no tracker module at all; the model contract next door is the
    # control, and it loads this.
    ("tracker.pay_disclosure", ("tracker.intelligence", "tracker.db"), ()),
    ("tracker.intelligence.schema", ("tracker.db",), ("tracker.pay_disclosure",)),
    # The registry CONSTRUCTS a backend; choosing one needs saved profiles
    # and the egress switch, so it is service work next door.
    ("tracker.intelligence.registry", ("tracker.db", "tracker.settings_store"), ()),
    ("tracker.intelligence_runtime.routing", (), ("tracker.settings_store",)),
    # The two model transports are L3 implementations; persisting a profile is
    # store work, so neither may reach the database.
    ("tracker.local_llm.client", ("tracker.db",), ()),
    ("tracker.cloud_llm.client", ("tracker.db",), ()),
    ("tracker.intelligence_runtime.local_profiles", (), ("tracker.db", "tracker.local_llm")),
    ("tracker.intelligence_runtime.cloud_profiles", (), ("tracker.db", "tracker.cloud_llm")),
    # Grading a logged row is pure and stays in the seam;
    # writing and reading the rows is the store's job, next door.
    ("tracker.intelligence.telemetry", ("tracker.db",), ()),
    ("tracker.intelligence_runtime.telemetry", (), ("tracker.db",)),
]


@pytest.mark.parametrize(("module", "forbidden", "required"), TIER_PROBES, ids=lambda v: str(v))
def test_a_module_pulls_in_no_tier_it_has_no_business_loading(module, forbidden, required):
    """import-linter reads source, so a module imported by string is invisible to
    it. This asks the interpreter what actually loaded."""
    result = subprocess.run(
        [sys.executable, "-c", _TIER_PROBE, module],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = set(json.loads(result.stdout.strip().splitlines()[-1]))
    assert not loaded & set(forbidden), (
        f"importing {module} loaded {sorted(loaded & set(forbidden))}"
    )
    assert set(required) <= loaded, (
        f"importing {module} did not load {sorted(set(required) - loaded)}, so this row "
        "is not the control it claims to be"
    )


_MODULE_PROBE = """
import importlib, json, sys
importlib.import_module(sys.argv[1])
print(json.dumps(sorted(name for name in sys.modules if name.startswith("tracker."))))
"""


@pytest.mark.parametrize(
    ("module", "loads_writer"),
    [
        ("tracker.db.queries.jobs", False),
        ("tracker.db.queries.scope", False),
        # The control: the projection applies the saved scope, so it loads the writer.
        ("tracker.scope.projection", True),
    ],
)
def test_a_read_owner_never_loads_the_scan_writer(module, loads_writer):
    """The read owners build from the scope gate (`db.queries.scope`), never from
    `db.repo`, the writer that applies it. Inside one layer, so only the loaded
    modules can say it."""
    result = subprocess.run(
        [sys.executable, "-c", _MODULE_PROBE, module], cwd=BACKEND, capture_output=True, text=True, check=True,
    )
    loaded = set(json.loads(result.stdout.strip().splitlines()[-1]))
    assert ("tracker.db.repo" in loaded) is loads_writer, f"importing {module}: tracker.db.repo loaded = {not loads_writer}"

