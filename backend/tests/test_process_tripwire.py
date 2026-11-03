"""No test may start a process, kill one, or spend money.

`no_escape` (`conftest.py`) refuses every one of those. Two holes sit under
that:

1. **It is opt-in with nothing asking.** A suite that drives a spawning route
   and forgets the fixture runs the real thing: `POST /api/sync` launches a full
   scrape detached, `POST /api/sync/cancel` signals the process group of
   whatever sync the user has running, `PUT /api/intelligence/matching/tier`
   re-embeds the corpus, and a cloud client bills the account. The failure mode
   is not a red test -- it is a scrape the developer did not ask for.
2. **Nothing else proves the fixture refuses anything.** Without a test that
   asserts `EscapeRefused`, a patch target that moves (`httpx` internals, an
   `asyncio` spelling) would silently disarm the guard while every suite that
   "uses" it stays green.

So this file is the tripwire's own gate. It scans the suite for modules that can
reach an escape surface and requires each to carry the fixture for EVERY test in
it (module-level `pytestmark`, not one fixture that some tests happen to
request), and it asserts the refusals and the two deliberate carve-outs.

**The surface list is derived, not declared.** `SPAWNS` is checked against a live
scan of `tracker/` for the primitives, so a new `Popen` anywhere in the backend
fails this file until it is classified; `REACHING` is computed as the modules
that import one. Outbound HTTP is not itself a surface -- `platform.http` and
every connector make requests, tests mock the transport, and treating egress as
a surface would mark the whole suite. `cloud_llm.client` is named separately
because a real call there costs the user money.

Two criteria, because neither sees the other's case: a module that imports
the supervisor's runner need never make a request, and a module that posts to `/api/sync`
through `api_client` imports nothing at all.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from tests.conftest import EscapeRefused
from tracker.config import get_settings

BACKEND = Path(__file__).resolve().parents[1]
TRACKER = BACKEND / "tracker"
TESTS = Path(__file__).resolve().parent

FIXTURE = "no_escape"

#: This file obeys its own rule: it names a patch target into the runner below,
#: so the scanner reports it without this line.
pytestmark = pytest.mark.usefixtures("no_escape")

#: The primitives that act on this machine. Outbound HTTP is deliberately absent
#: (see the module docstring). `os.kill` counts: a signal to one process acts on
#: it as surely as one to its group.
_PRIMITIVE = re.compile(r"\bPopen\b|\bkillpg\b|\bos\.kill\b|create_subprocess_(?:exec|shell)")

#: Frozen: every module that can start or signal a process. Exact in both
#: directions -- a new spawner must join it, and a module that stops spawning
#: must leave.
SPAWNS = frozenset(
    {
        "tracker.local_llm.server",
        # The plugin host starts the SDK runner, and only that.
        "tracker.plugins.host",
        # SIGTERM to a live plugin host on disable, pause and uninstall.
        "tracker.plugins.runtime",
        # The supervisor starts every job as a new session and signals its group
        # to stop it.
        "tracker.supervisor.runner",
        # The trampoline each job starts through: the job's command, and
        # caffeinate beside it.
        "tracker.supervisor.child",
        # The API as the supervisor's child: stopped with SIGTERM, then SIGKILL.
        "tracker.supervisor.api",
    }
)

#: Not a process, but the other irreversible act: a request here is billed to the
#: user's account (the egress switch stands in front of it).
BILLS = frozenset({"tracker.cloud_llm.client"})

#: Not a process either, but a request that cannot be taken back: an event sent
#: here lands in the project's real PostHog project, on every developer's and
#: CI's behalf alike (docs/architecture.md).
PUBLISHES = frozenset({"tracker.usage_stats.sender"})

#: Frozen: the modules that reach a spawner by importing it. Computed live from
#: the import graph, so this is the expectation, not the input.
REACHING = frozenset(
    {
        "tracker.api.routers.intelligence",
        # Sync also starts the due plugin work through the plugin runtime.
        "tracker.api.routers.ops",
        "tracker.intelligence.providers.cloud",
        # The daily usage-sharing send posts through the sender.
        "tracker.usage_stats.flush",
        # Settings > Plugins: Refresh now, and the re-estimate after a change.
        "tracker.api.routers.plugins",
        # What a user's decision does, for the API and the CLI alike: Start
        # spawns a run, disable, pause and uninstall signal one.
        "tracker.plugins.lifecycle",
        # The plugin command line: its `run` is the host process, and its
        # decisions go through the lifecycle.
        "tracker.plugins.cli",
        # The supervisor's loop: launches, stops and adopts through the runner.
        "tracker.supervisor.dispatch",
        # The jobs that run in-process: they write their result beside the
        # trampoline's, and health probes whether a scan's group still lives.
        "tracker.supervisor.entries",
        # The supervisor's service loop tends the API child and stops it.
        "tracker.supervisor.service",
        # `python -m tracker.supervisor`: runs the service, and `stop --jobs`
        # stops the runs a dead supervisor left.
        "tracker.supervisor.__main__",
    }
)

#: Composition roots: they name no primitive and spawn nothing themselves, they
#: only mount the routers that do. Every test reaches them (`api_client` imports
#: `api.app`), so marking them would mark the suite and measure nothing. The
#: route criterion below is what covers a test that drives a spawning route
#: through them without importing anything.
COMPOSITION = frozenset({"tracker.api.app", "tracker.api.routers"})

_UNSAFE_METHODS = ("post", "put", "patch", "delete")


# --------------------------------------------------------------------------- #
# Reading the backend: which modules can escape
# --------------------------------------------------------------------------- #


def _module_name(path: Path, root: Path, package: str) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((package, *parts)) if package else ".".join(parts)


@dataclass(frozen=True)
class Reference:
    """One name a file uses, and whether it was written as a string.

    The distinction is the whole rule: an IMPORT of a surface is a reference to
    it, but a string is one only when it points INSIDE the surface. A gate that
    lists `"tracker.cloud_llm.client"` in a frozen probe table is not calling
    it; `"tracker.supervisor.runner.launch"` is a patch target and is.
    """

    name: str
    literal: bool

    def touches(self, surface: str) -> bool:
        if self.literal:
            return self.name.startswith(f"{surface}.")
        return self.name == surface or self.name.startswith(f"{surface}.")


def _references(path: Path) -> set[Reference]:
    """Every module or dotted path this file names -- import or string literal.

    String literals are read because the shipped lookup-site rule patches by
    name: a test can reach a spawner only through a string such as
    `"tracker.supervisor.runner.launch"`, when the code under test imports it
    lazily.
    """
    references: set[Reference] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            references |= {Reference(alias.name, False) for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            references.add(Reference(node.module, False))
            references |= {
                Reference(f"{node.module}.{alias.name}", False) for alias in node.names
            }
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "." in node.value:
                references.add(Reference(node.value, True))
    return references


def _spawning_modules() -> set[str]:
    return {
        _module_name(path, TRACKER, "tracker")
        for path in TRACKER.rglob("*.py")
        if _PRIMITIVE.search(path.read_text(encoding="utf-8"))
    }


def _importers_of(surfaces: frozenset[str]) -> set[str]:
    found = set()
    for path in TRACKER.rglob("*.py"):
        name = _module_name(path, TRACKER, "tracker")
        if name in surfaces:
            continue
        if _touches(_references(path), surfaces):
            found.add(name)
    return found


def _touches(references: set[Reference], surfaces: frozenset[str]) -> list[str]:
    return sorted(
        {
            surface
            for surface in surfaces
            for reference in references
            if reference.touches(surface)
        }
    )


SURFACES = (SPAWNS | BILLS | PUBLISHES | REACHING) - COMPOSITION


# --------------------------------------------------------------------------- #
# Reading the backend: which routes spawn
# --------------------------------------------------------------------------- #


def _referenced_names(node: ast.AST) -> set[str]:
    """Every bare name and attribute this function mentions.

    Mentions, not calls: a handler can reach a spawner by handing it on rather
    than calling it (`_processes()` in `routers/intelligence.py` packs the three
    process functions into a dataclass), and a closure that only followed calls
    would not see `PUT /api/intelligence/matching/tier`.
    Over-approximating is the safe direction for a tripwire.
    """
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _spawning_routes() -> dict[str, set[str]]:
    """`{path: {METHOD, ...}}` for every unsafe route whose handler can escape.

    Derived by closure inside each router module: start from the names it takes
    from a spawn surface and the local functions that hold a primitive, then add
    any function that calls one, to a fixed point. A hand-listed set of routes
    would stop matching the day a handler is renamed.
    """
    routes: dict[str, set[str]] = {}
    for path in (TRACKER / "api" / "routers").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        escaping = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module in SPAWNS | BILLS | PUBLISHES:
                    # `from tracker.plugins.runtime import spawn_run`
                    escaping |= {alias.asname or alias.name for alias in node.names}
                # `from tracker.plugins import runtime` — the module itself is the name.
                escaping |= {
                    alias.asname or alias.name
                    for alias in node.names
                    if f"{node.module}.{alias.name}" in SPAWNS | BILLS | PUBLISHES
                }
            elif isinstance(node, ast.Import):
                escaping |= {
                    (alias.asname or alias.name).rsplit(".", 1)[-1]
                    for alias in node.names
                    if alias.name in SPAWNS | BILLS | PUBLISHES
                }
        escaping |= {
            name
            for name, node in functions.items()
            if _PRIMITIVE.search(ast.unparse(node))
        }
        while True:
            grown = {
                name
                for name, node in functions.items()
                if name not in escaping and _referenced_names(node) & escaping
            }
            if not grown:
                break
            escaping |= grown
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name not in escaping:
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.lower()
                if method not in _UNSAFE_METHODS or not decorator.args:
                    continue
                first = decorator.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    routes.setdefault(first.value, set()).add(method.upper())
    return routes


def _route_pattern(route: str) -> re.Pattern[str]:
    """`/api/companies/{slug}` matches the literal a test writes for one company."""
    parts = [re.escape(part) for part in re.split(r"\{[^}]*\}", route)]
    return re.compile("^" + "[^/]+".join(parts) + "$")


# --------------------------------------------------------------------------- #
# Reading the suite: who opts in
# --------------------------------------------------------------------------- #


def _module_fixtures(tree: ast.Module) -> set[str]:
    """Fixture names a module-level `pytestmark` applies to every test in it."""
    applied: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            continue
        for sub in ast.walk(node.value):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "usefixtures"
            ):
                applied |= {
                    argument.value
                    for argument in sub.args
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                }
    return applied


def _unsafe_calls(tree: ast.Module) -> set[tuple[str, str]]:
    """`{(METHOD, path)}` for every `.post("/api/...")`-shaped call in a module."""
    calls = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr.lower() not in _UNSAFE_METHODS or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            calls.add((node.func.attr.upper(), first.value))
        elif isinstance(first, ast.JoinedStr):
            # An f-string: each interpolation stands in as one path segment, so
            # `f"/api/companies/{slug}"` still matches `/api/companies/{slug}`.
            spelled = "".join(
                part.value
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
                else "_"
                for part in first.values
            )
            calls.add((node.func.attr.upper(), spelled))
    return calls


def _helpers(directory: Path) -> dict[str, Path]:
    """The suite's own helper modules -- the `*_contract_seed.py` files.

    `conftest.py` is excluded on purpose: it PROVIDES the fixture and imports
    `api.app` for `api_client`, so counting it would put every test module in
    scope and the gate would say nothing.
    """
    return {
        path.stem: path
        for path in directory.rglob("*.py")
        if not path.stem.startswith("test_") and path.name != "conftest.py"
    }


def _closure(
    path: Path, helpers: dict[str, Path], seen: set[Path] | None = None
) -> set[Reference]:
    seen = set() if seen is None else seen
    if path in seen:
        return set()
    seen.add(path)
    references = _references(path)
    for reference in list(references):
        helper = helpers.get(reference.name.rsplit(".", 1)[-1])
        if helper is not None and helper not in seen:
            references |= _closure(helper, helpers, seen)
    return references


def _offenders(directory: Path, routes: dict[str, set[str]]) -> dict[str, list[str]]:
    """`{module: [reasons]}` for every test module that can escape and does not opt in."""
    patterns = [
        (methods, route, _route_pattern(route)) for route, methods in routes.items()
    ]
    helpers = _helpers(directory)
    offenders: dict[str, list[str]] = {}
    for path in sorted(directory.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if FIXTURE in _module_fixtures(tree):
            continue
        reasons = [
            f"reaches {surface}" for surface in _touches(_closure(path, helpers), SURFACES)
        ]
        reasons += sorted(
            f"calls {method} {route}"
            for methods, route, pattern in patterns
            for method, called in _unsafe_calls(tree)
            if method in methods and pattern.match(called)
        )
        if reasons:
            offenders[str(path.relative_to(directory))] = reasons
    return offenders


# --------------------------------------------------------------------------- #
# 1. The surface list is what it claims to be
# --------------------------------------------------------------------------- #


def test_every_module_that_can_spawn_a_process_is_named():
    assert _spawning_modules() == set(SPAWNS), (
        "a module gained or lost a process primitive; classify it (and mark the "
        "suites that reach it) rather than editing SPAWNS blind"
    )


def test_every_module_that_imports_a_spawner_is_named():
    assert _importers_of(SPAWNS | BILLS | PUBLISHES) - COMPOSITION == set(REACHING)


def test_the_composition_roots_hold_no_primitive_of_their_own():
    """The exemption is only safe while these modules merely mount routers."""
    assert not set(COMPOSITION) & _spawning_modules()


def test_the_spawning_routes_are_the_ones_the_routers_declare():
    routes = _spawning_routes()
    assert routes["/api/sync"] == {"POST"}
    # Cancel asks the supervisor to stop the scan; it signals nothing itself.
    assert "/api/sync/cancel" not in routes, routes
    # Adding a company and refreshing the scope ask the supervisor for a scan
    # and a discovery; they start nothing themselves.
    assert "/api/companies" not in routes, routes
    # The core fetches no outside pay source: a plugin's refresh is its own route.
    assert not any(route.startswith("/api/integrations") for route in routes), routes
    # A tier switch asks the supervisor for the re-embed; it starts nothing.
    assert "/api/intelligence/matching/tier" not in routes, routes
    assert "/api/scope/refresh" not in routes, routes
    assert not any(route.startswith("/api/jobs") for route in routes), routes


# --------------------------------------------------------------------------- #
# 2. The suite opts in
# --------------------------------------------------------------------------- #


def test_every_test_module_that_can_escape_refuses_to():
    offenders = _offenders(TESTS, _spawning_routes())
    assert not offenders, (
        "these modules can start a process, signal one, or bill the account, and "
        f"do not carry `pytestmark = pytest.mark.usefixtures({FIXTURE!r})`: "
        + "; ".join(f"{name} ({', '.join(reasons)})" for name, reasons in offenders.items())
    )


# --------------------------------------------------------------------------- #
# 3. The scanner catches what it claims (planted controls)
# --------------------------------------------------------------------------- #

_PLANTED = {
    "test_importer.py": "from tracker.supervisor.runner import launch\n",
    "test_patcher.py": 'P = "tracker.supervisor.runner.launch"\n',
    "test_poster.py": 'def test_x(api_client):\n    api_client.post("/api/sync")\n',
    "test_via_helper.py": "from helper_seed import thing\n",
    "test_marked.py": (
        "import pytest\n"
        'pytestmark = pytest.mark.usefixtures("no_escape")\n'
        "from tracker.supervisor.runner import launch\n"
    ),
    "test_marked_in_a_list.py": (
        "import pytest\n"
        'pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_escape")]\n'
        'P = "tracker.supervisor.runner.launch"\n'
    ),
    "test_bare_name.py": 'PROBE = "tracker.supervisor.runner"\n',
    "test_reader.py": 'def test_x(api_client):\n    api_client.get("/api/status")\n',
    "test_other_route.py": 'def test_x(api_client):\n    api_client.post("/api/jobs/1/view")\n',
}

#: What each planted module must be reported for, or `None` for "must be clear".
_VERDICTS = {
    "test_importer.py": "reaches tracker.supervisor.runner",
    "test_patcher.py": "reaches tracker.supervisor.runner",
    "test_poster.py": "calls POST /api/sync",
    "test_via_helper.py": "reaches tracker.api.routers.ops",
    "test_marked.py": None,
    "test_marked_in_a_list.py": None,
    # The deliberate rule: a bare module name is a mention, not a call site.
    "test_bare_name.py": None,
    # Reading process state is allowed; `no_escape` keeps `kill(pid, 0)` working.
    "test_reader.py": None,
    "test_other_route.py": None,
}


@pytest.fixture(scope="module")
def planted(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("tripwire_planted")
    (root / "helper_seed.py").write_text(
        "from tracker.api.routers import ops\n\nthing = ops\n", encoding="utf-8"
    )
    for name, body in _PLANTED.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


@pytest.mark.parametrize(("name", "reason"), sorted(_VERDICTS.items()), ids=lambda v: str(v))
def test_the_scanner_reports_a_planted_module_exactly_when_it_should(planted, name, reason):
    offenders = _offenders(planted, _spawning_routes())
    if reason is None:
        assert name not in offenders, offenders
    else:
        assert offenders.get(name) and reason in offenders[name], offenders


# --------------------------------------------------------------------------- #
# 4. The fixture refuses (and still allows the two carve-outs)
# --------------------------------------------------------------------------- #


def test_starting_a_process_is_refused(no_escape):
    with pytest.raises(EscapeRefused):
        subprocess.Popen(["/bin/echo", "escaped"])


def test_starting_an_async_process_is_refused(no_escape):
    async def spawn():
        await asyncio.create_subprocess_exec("/bin/echo", "escaped")

    with pytest.raises(EscapeRefused):
        asyncio.run(spawn())


#: A pid no process holds. Named so the refusal, not a lucky `ProcessLookupError`,
#: is what these two tests observe -- and so a broken guard cannot signal anything
#: real, this run included.
ABSENT_PID = 2**30


def test_signalling_a_process_is_refused(no_escape):
    with pytest.raises(EscapeRefused):
        os.kill(ABSENT_PID, 15)


def test_signalling_a_process_group_is_refused(no_escape):
    with pytest.raises(EscapeRefused):
        os.killpg(ABSENT_PID, 15)


def test_an_outbound_request_is_refused(no_escape):
    with pytest.raises(EscapeRefused), httpx.Client() as client:
        client.get("http://127.0.0.1:9/")


def test_an_outbound_async_request_is_refused(no_escape):
    async def fetch():
        async with httpx.AsyncClient() as client:
            await client.get("http://127.0.0.1:9/")

    with pytest.raises(EscapeRefused):
        asyncio.run(fetch())


def test_an_outbound_urllib_request_is_refused(no_escape):
    with pytest.raises(EscapeRefused):
        urllib.request.urlopen("http://127.0.0.1:9/")


def test_observing_a_process_is_still_allowed(no_escape):
    """`kill(pid, 0)` asks whether a process exists; the liveness probes need it."""
    assert os.kill(os.getpid(), 0) is None


def test_an_in_process_transport_is_still_allowed(no_escape):
    """The suite's own fakes: `MockTransport` and `ASGITransport` never leave."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        assert client.get("http://127.0.0.1:9/").json() == {"ok": True}


# --------------------------------------------------------------------------- #
# 5. The refusals must not cost a module its database
# --------------------------------------------------------------------------- #


def test_resolving_the_embedded_server_is_the_hazard_the_memo_exists_for(no_escape, tmp_path):
    """The refusals really do stop the harness from starting its own database.

    This is the control for the memo in `_base_url`: without it, `db_session`
    resolves the URL AFTER this fixture patched `subprocess`, the refusal is
    swallowed as "no server configured", and the file skips instead of failing.

    Asked of an empty cluster directory of its own, not the configured server:
    CI names its database by URL, so the configured one is never embedded there,
    and asking it would skip in every CI run. The wheel is installed in CI,
    so the start it refuses is a real one, and a broken refusal initialises a
    scratch cluster instead of attaching to the shared one.
    """
    pgdata = tmp_path / "db"
    settings = get_settings().model_copy(
        update={"database_url_override": None, "db_embedded": True, "db_pgdata": str(pgdata)}
    )

    with pytest.raises(Exception) as raised:  # noqa: B017 - the cause is the claim
        settings.ensure_embedded_server()
    assert not (pgdata / "PG_VERSION").exists(), "the refused start still made a cluster"

    causes = []
    error: BaseException | None = raised.value
    while error is not None:
        causes.append(type(error))
        error = error.__cause__
    assert EscapeRefused in causes, causes


def test_the_refusals_cannot_take_a_module_s_database_away(no_escape):
    """The invariant the memo keeps: unless `_base_url` resolves once per
    process and `no_escape` warms it first, every DB-backed test in a marked
    module turns into a silent skip."""
    harness = importlib.import_module("tests.conftest")
    assert harness._resolved, (
        "`no_escape` must resolve the server before it installs the refusals, or "
        "every DB-backed test in a module that carries it skips"
    )
    assert harness._base_url() == harness._resolved_base
