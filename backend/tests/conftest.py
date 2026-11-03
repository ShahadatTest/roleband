"""Optional Postgres harness for tests that must exercise real SQL.

Most of this suite is pure and needs no database. A few behaviours cannot be
tested honestly without one -- ON CONFLICT convergence, a DELETE that retracts
stale rows, a unique index doing its job. Faking a session for those would mean
mocking the subject under test, which the testing policy forbids, so they run
against real Postgres or they do not run at all.

Isolation: a THROWAWAY database (`_DB_NAME`, per process) is created on whatever
server the settings resolve to, and dropped at session end. It never touches the
`roleband` asset. If no server is reachable the fixture SKIPS rather than fails,
so the pure suite still runs on a machine with no database.

Scope: `pytest.ini` pins the asyncio loop to function scope, so every async
fixture here is function-scoped too and each test builds its own engine --
asyncpg connections are bound to the loop that opened them, and a session-scoped
engine handed across per-function loops fails in ways that look like flakes. The
expensive part (CREATE DATABASE + schema) still happens exactly once, guarded by
a module-level flag.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.skip_policy import (  # noqa: F401 - hooks register by name in a conftest
    pytest_make_collect_report,
    pytest_runtest_makereport,
)
from tests.upgrade_rehearsal import baseline_database  # noqa: F401 - fixtures register by name in a conftest
from tracker.db.models import Base

# Derived files (the built-in pay rows) are built into a test
# cache, never the developer's ~/.roleband. Keyed by fingerprint and written
# atomically, so every worker may share it.
os.environ.setdefault("ROLEBAND_CACHE_DIR", str(Path(tempfile.gettempdir()) / "roleband-test-cache"))

#: Distinct per process so parallel runs cannot collide on one scratch database.
_DB_NAME = f"roleband_test_{os.getpid()}"

_ready = False
_unavailable: str | None = None


_resolved = False
_resolved_base: URL | None = None


def _base_url() -> URL | None:
    """The configured async URL, or None when no server is configured.

    Parsed with `make_url` rather than string surgery: the embedded server's URL
    carries its socket directory in a query parameter
    (`...@/roleband?host=/path/to/db`), so splitting on the last "/" lands
    inside the socket path and silently builds a URL for a database that is not
    there.

    Resolved ONCE per process, because resolving it is not free of side effects:
    `Settings.database_url` starts or attaches the embedded server, and that runs
    `psql` in a subprocess. Under `no_escape` a subprocess is refused, the
    `except` below reads the refusal as "no server", and every DB-backed test in
    the file SKIPS -- green, silent, and testing nothing. One resolution per
    process also makes the answer independent of which fixture happens to ask
    first.
    """
    global _resolved, _resolved_base
    if _resolved:
        return _resolved_base
    try:
        from tracker.config import get_settings

        _resolved_base = make_url(get_settings().database_url)
    except Exception:  # noqa: BLE001 - no server configured is a skip, not an error
        _resolved_base = None
    _resolved = True
    return _resolved_base


async def _ensure_database(base: URL) -> None:
    """Create the scratch database and schema once per process."""
    global _ready, _unavailable
    if _ready or _unavailable:
        return

    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{_DB_NAME}"'))
    except Exception as exc:  # noqa: BLE001 - unreachable server is a skip
        _unavailable = f"{type(exc).__name__}: {exc}"
        return
    finally:
        await admin.dispose()

    engine = create_async_engine(base.set(database=_DB_NAME))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.create_all)
            _owned_sequences.update(await _sequences_of_the_tables(conn))
    finally:
        await engine.dispose()
    _ready = True


#: Every sequence a model table's column owns, with its start value: the ones
#: `TRUNCATE ... RESTART IDENTITY` restarts.
_owned_sequences: dict[str, int] = {}


async def _sequences_of_the_tables(conn) -> dict[str, int]:
    rows = await conn.execute(text(
        "SELECT s.relname, q.seqstart, t.relname FROM pg_depend d"
        " JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'"
        " JOIN pg_sequence q ON q.seqrelid = s.oid"
        " JOIN pg_class t ON t.oid = d.refobjid"
        " WHERE d.classid = 'pg_class'::regclass AND d.refclassid = 'pg_class'::regclass"
        " AND d.deptype IN ('a', 'i')"
    ))
    return {sequence: start for sequence, start, table in rows if table in Base.metadata.tables}


async def _reset(conn) -> None:
    """Leave what `TRUNCATE <every table> RESTART IDENTITY CASCADE` leaves: every
    model table empty and every sequence they own restarted.

    TRUNCATE does catalog work for every table it names, empty or not, so only
    tables holding a committed row and sequences that moved are reset. That reading is only complete when nothing
    else can still commit: while another session on this database is inside a
    transaction, everything is truncated, and TRUNCATE waits for its locks."""
    tables = list(Base.metadata.tables)
    probes = [
        "SELECT 'busy', '' FROM pg_stat_activity WHERE datname = current_database()"
        " AND pid <> pg_backend_pid() AND backend_type = 'client backend' AND xact_start IS NOT NULL",
        *(f"(SELECT 'table', '{name}' FROM \"{name}\" LIMIT 1)" for name in tables),
        *(f"SELECT 'sequence', '{name}' FROM \"{name}\" WHERE is_called OR last_value <> {start}"
          for name, start in _owned_sequences.items()),
    ]
    found = (await conn.execute(text(" UNION ALL ".join(probes)))).all()
    if any(kind == "busy" for kind, _ in found):
        dirty = tables
    else:
        dirty = [name for kind, name in found if kind == "table"]
    # Unsorted: TRUNCATE ... CASCADE resolves order itself, and asking for a
    # topological sort only surfaces a warning about the job/job_lineage cycle.
    if dirty:
        names = ", ".join(f'"{name}"' for name in dirty)
        await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    for kind, name in found:
        if kind == "sequence":
            await conn.execute(text(f'ALTER SEQUENCE "{name}" RESTART'))


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session on an empty schema.

    Every table is emptied and its sequences restarted first (`_reset`), so a
    test never inherits another's rows and the order the suite happens to run
    in cannot change a result.
    """
    base = _base_url()
    if base is None:
        pytest.skip("no database configured")

    await _ensure_database(base)
    if _unavailable:
        pytest.skip(f"database unavailable ({_unavailable})")

    engine = create_async_engine(base.set(database=_DB_NAME))
    try:
        async with engine.begin() as conn:
            await _reset(conn)

        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def api_client(db_session) -> AsyncIterator[AsyncClient]:
    """Real ASGI routes; each request gets a fresh session on the scratch DB.

    Seed rows must be committed by the test. A later request cannot see an
    earlier handler's uncommitted ORM state, and request teardown rolls it back.
    Server process startup/lifespan is outside these HTTP behavior contracts.

    The base URL is the address the API really serves: the loopback boundary
    refuses any other Host, `testserver` included.
    """
    from tracker.api.app import app
    from tracker.api.deps import get_session
    from tracker.api.routers.ops import forget_scan_bound

    # A status read reuses its scan-bound part within one process; each test
    # starts on an empty database, so none may see another's.
    forget_scan_bound()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def request_session():
        async with factory() as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = request_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1:8010"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


class EscapeRefused(RuntimeError):
    """A test tried to act outside its process: spawn, signal, or connect."""


@pytest.fixture
def no_escape(monkeypatch):
    """Refuse every way a route under test could act on this machine or the network.

    For suites that drive routes which, were a guard broken, would REALLY run:
    start a scrape, terminate the user's running sync, bill a model call. They
    are pointed at the scratch database, but a spawned process or an outbound
    request is not. `os.kill(pid, 0)` stays allowed — a liveness probe observes
    a process, it does not act on one. In-process transports (`ASGITransport`,
    `MockTransport`) are unaffected; only the network ones are refused.
    """
    import asyncio
    import subprocess
    import urllib.request

    import httpx

    # Resolve the server BEFORE refusing anything: starting it is a subprocess,
    # and a test refused its own harness does not fail -- it skips (see
    # `_base_url`). Memoized, so the `db_session` that runs after this fixture
    # gets the answer without asking the machine again.
    _base_url()

    def refuse(what):
        def refused(*_args, **_kwargs):
            raise EscapeRefused(what)

        return refused

    async def refused_async(*_args, **_kwargs):
        raise EscapeRefused("outbound HTTP")

    real_kill = os.kill

    def kill(pid, sig):
        if sig == 0:
            return real_kill(pid, 0)
        raise EscapeRefused(f"signal {sig} to pid {pid}")

    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse("subprocess"))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", refuse("subprocess"))
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "killpg", refuse("process-group signal"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refused_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse("outbound HTTP"))
    monkeypatch.setattr(urllib.request, "urlopen", refuse("outbound HTTP"))


@pytest.fixture(autouse=True)
def _no_test_resolves_a_name(monkeypatch):
    """Adding a company by URL fetches its page, through
    `platform.safe_fetch`, which resolves the name itself. No test may reach
    DNS, so the default resolver refuses: the page fetch fails the way an
    unreachable site does and the company stays pending. Tests of the fetch
    inject their own resolver."""
    import httpcore

    from tracker.platform import safe_fetch

    async def refuse(host, _port):
        raise httpcore.ConnectError(f"tests do not resolve names ({host})")

    monkeypatch.setattr(safe_fetch, "_system_resolve", refuse)


@pytest.fixture(autouse=True)
def _no_test_probes_the_network(monkeypatch):
    """A failed read asks whether OUR network is up (`workflows.outage`)
    by opening TCP connections to five job sites. No test may: the probe answers
    "up", so a fake source's failure stays attributable to that source.
    Tests of an outage set their own answer."""
    from tracker.workflows import outage

    async def reachable(_host, _timeout):
        return True

    monkeypatch.setattr(outage, "_reach", reachable)


@pytest.fixture(autouse=True)
def _no_test_reads_the_machines_power(monkeypatch):
    """Background reads wait for a full wake, the directory scan for mains
    power (`platform.power`). No test may depend on the machine it
    runs on, or a laptop on battery would fail the directory tests: the probe
    answers a full wake on mains power. Tests of the wait set their own."""
    from tracker.platform import power

    answers = {
        "systemstate": "Current System Capabilities are: CPU Graphics Audio Network \n",
        "batt": "Now drawing from 'AC Power'\n",
    }
    monkeypatch.setattr(power, "_pmset", lambda _flag, what: answers[what])


class LiveDatabaseRefused(RuntimeError):
    """A test reached the process-wide engine: the LIVE database."""


@pytest.fixture(autouse=True)
def _no_test_reaches_the_live_database(monkeypatch):
    """Every test database is the per-process scratch one, built by
    `db_session` on its own engine; the process-wide engine
    (`tracker.db.session.get_engine`, what `session_scope` opens) is the
    configured database, which on a dev machine is the user's real one. An
    unpatched `session_scope` in code under test (the idle scheduler tick's
    reminder reconcile, say) would write to it. A test that needs
    `session_scope` takes `scratch_scope`, which points every importer's at
    the scratch database."""
    from tracker.db import session as db_session_module

    hits: list[str] = []

    def refused():
        hits.append("get_engine")
        raise LiveDatabaseRefused(
            "a test reached tracker.db.session.get_engine (the live database); "
            "take the scratch_scope fixture to point session_scope at the scratch database"
        )

    monkeypatch.setattr(db_session_module, "get_engine", refused)
    monkeypatch.setattr(db_session_module, "_session_factory", None)
    yield
    # Code that swallows errors (an idle tick's housekeeping) would hide the
    # refusal; the test fails here instead.
    assert not hits, "this test reached the live database (see LiveDatabaseRefused)"


@pytest.fixture
def scratch_scope(_no_test_reaches_the_live_database, db_session, monkeypatch):
    """Every `session_scope` opens a session on the scratch database.

    Production's `session_scope` reads `tracker.db.session._session_factory`
    when it is called, so setting that one attribute reaches every module that
    imported the name, and each keeps production's commit, rollback and
    re-raise. A per-module patch reaches only the modules its author listed,
    and a copy of the scope keeps whatever error handling it was written with.
    The guard goes first, so its reset cannot undo this. Returns
    `session_scope`, for a test that opens one itself."""
    from tracker.db import session as db_session_module

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_session_module, "_session_factory", factory)
    return db_session_module.session_scope


class CheckoutLockRefused(RuntimeError):
    """A test locked a file in the checkout's `data/`, where the live run locks are."""


#: The checkout's own data directory. Found from this file, not from
#: `paths.DATA_DIR`: tests patch that name, and modules bind it at import.
CHECKOUT_DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(autouse=True)
def _shared_pacing_does_not_leak_between_tests(monkeypatch):
    from tracker.platform import ratelimit

    monkeypatch.setattr(ratelimit, "_shared_dir", None)


@pytest.fixture(autouse=True)
def _catalog_counts_do_not_leak_between_tests():
    """A catalog read reuses its counts within one process, keyed by what the
    database holds; a fake session or a reset database can repeat a key."""
    from tracker.scope.catalog import forget_catalog_counts

    forget_catalog_counts()


@pytest.fixture(autouse=True)
def _no_test_locks_the_checkouts_data(monkeypatch):
    """The checkout's `data/` holds the supervisor's run locks (`daily.lock`
    is the scan's). A test that took one would hold up a real scan, and a real
    scan holding it would answer in the test's place. A test locks files under
    its own `tmp_path` instead. Every `fcntl.flock` of a file under the
    checkout's `data/` is refused."""
    import fcntl

    real = fcntl.flock
    hits: list[str] = []

    def flock(fd, operation):
        name = getattr(fd, "name", None)
        if isinstance(name, str) and Path(name).resolve().is_relative_to(CHECKOUT_DATA):
            hits.append(name)
            raise CheckoutLockRefused(f"a test locked {name}; give it a data directory under tmp_path")
        return real(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    yield
    # A caller that swallows errors (a tick that reports and goes on) would
    # hide the refusal; the test fails here instead.
    assert not hits, f"this test locked files in the checkout's data directory: {hits}"


@pytest.fixture(autouse=True)
def _no_test_touches_the_machines_secret_key(monkeypatch, tmp_path):
    """Saving an API key seals it with the key file in `~/.roleband`
    (`platform.secrets`), creating it on first use. No test may create, read or
    replace the user's: each gets a key file of its own under its `tmp_path`,
    and so does every process it starts."""
    from tracker.platform import secrets

    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(tmp_path / "secret.key"))


@pytest.fixture(autouse=True)
def _usage_sharing_stays_off(monkeypatch):
    """No test records or sends usage events unless it says so: the product's
    own kill switch is on everywhere (docs/architecture.md). Usage tests
    take `sharing_allowed`, which turns every switch off for that test only."""
    monkeypatch.setenv("ROLEBAND_NO_USAGE_STATS", "1")


@pytest.fixture
def sharing_allowed(monkeypatch, tmp_path):
    """Every usage-sharing kill switch off for this test: no env switch, and a
    `.env` that does not exist (the developer's own `backend/.env` is not read)."""
    from tracker.usage_stats import kill

    for name in kill.SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(kill, "ENV_FILE", tmp_path / "absent.env")


@pytest.fixture(scope="session", autouse=True)
def _embedded_servers_stop_with_the_session(tmp_path_factory):
    """Stop any throwaway embedded server a test left running.

    `ensure_server` keeps a server up after its process exits, as the app needs,
    and `pg_ctl` detaches it into a session of its own, so nothing else stops a
    test's cluster: one that outlives its test outlives the run. Each test
    destroys its own; this is the backstop for a teardown that never ran.
    Session teardown runs from `pytest_sessionfinish`, so an interrupted run is
    covered too; a killed one is not. Only this process's basetemp is searched
    (one `popen-gwN` per xdist worker), so it cannot reach another worker's
    servers, another run's, or the live cluster.
    """
    yield
    from tests.embedded_utils import stop_clusters_under

    stop_clusters_under(tmp_path_factory.getbasetemp())


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001 - pytest hook signature
    """Drop the scratch database. Best effort: a leaked test DB is noise, not damage."""
    if not _ready:
        return
    import asyncio

    async def _drop() -> None:
        base = _base_url()
        if base is None:
            return
        admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}" WITH (FORCE)'))
        finally:
            await admin.dispose()

    try:
        asyncio.run(_drop())
    except Exception:  # noqa: BLE001 - teardown must never fail the run
        pass
