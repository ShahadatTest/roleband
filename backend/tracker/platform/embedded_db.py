"""Embedded Postgres lifecycle: start or attach a server for a PGDATA directory.

L0 primitive. It takes a path and returns a live server; *which* path (and so
which database) is policy that lives in `config.py`. Imports no tracker module.

Provenance: `pixeltable-pgserver` 0.6.0 — fork of `orm011/pgserver`, PostgreSQL
License + Apache-2.0. The wheel ships PG 16.14 (`pginstall/`) and 18.4
(`pginstall18/`), pgvector 0.8.5 in both, and the full client toolchain
(`initdb`, `pg_ctl`, `psql`, `pg_dump`, `pg_restore`, `pg_upgrade`). Measured
from the wheel; re-measure on a version bump — `VERIFIED_UPSTREAM_VERSIONS` makes that
mandatory rather than aspirational: an unverified wheel version is refused at
the import seam instead of silently running on unmeasured behaviour.

Upstream behaviours this module compensates for:

* **The socket directory is not caller-selectable.** `find_suitable_socket_dir`
  uses PGDATA when the path fits the ~104-char unix-socket cap and a hashed
  directory under the user runtime path otherwise. So never hardcode a socket
  path: `postmaster.pid` is the only authority, and `uri()` reads it.
* **initdb inherits locale from the environment** — upstream passes no
  `--locale`, so an unpinned first run bakes host-dependent collation into the
  cluster permanently, changing every text ORDER BY. Pinned here at initdb
  time, the only moment it can be chosen.
* **A SIGKILLed holder leaks its PID** into `<pgdata>/.handle_pids.json`, and
  upstream stops the server only when that list drains to the caller's own PID.
  One leaked entry disables shutdown for the cluster's lifetime, so
  `_prune_dead_holders` sweeps it before attaching.
* **The wheel ships no contrib modules** — setup installs a matching prebuilt
  `pg_trgm` alongside it. `require_extensions` asserts availability with
  remediation text rather than letting a migration fail halfway.
* **The socket option is unquoted, and the start takes no server settings.**
  Outside Windows every start goes through a quoted pg_ctl option string,
  which also carries the caller's `server_settings`, before upstream attaches.
  Windows keeps upstream's start and the stock settings.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import shlex
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

logger = logging.getLogger(__name__)

# The docker container (`postgres_*` settings) runs PG 16; keep the major
# identical so a dump/restore migration has no version variable in it. The wheel defaults to
# 18 (`PGSERVER_POSTGRES_VERSION`), which we deliberately override.
DEFAULT_POSTGRES_VERSION = 16

# Matches the :5433 container's `en_US.utf8`. libc collation (the build is
# `--without-icu`), so exact ordering still varies by OS/glibc version — an
# accepted consequence of a per-install local database, documented rather than
# silently inherited.
DEFAULT_LOCALE = "en_US.UTF-8"

# Leave the server running when a process exits, as the container's
# `restart: unless-stopped` does. Upstream's default ('stop') suits ephemeral use and
# is wrong for an always-on app in two ways: every short-lived CLI would pay an
# initdb-less start plus a stop, and — because the refcount drops to zero the
# moment a process exits — a DSN resolved by one command is already dead by the
# time the next command uses it, which is exactly how shell tooling works. The
# refcount is still maintained under this mode; only the automatic stop is off,
# so shutdown is explicit (`stop_server`, called by uninstall).
DEFAULT_CLEANUP_MODE: str | None = None


class EmbeddedDbError(RuntimeError):
    """Embedded server could not be started, reached, or validated."""


class ClusterOwnedElsewhere(EmbeddedDbError):
    """The cluster was made by another kind of install, which keeps it."""


def owner_record(pgdata: Path) -> Path:
    """The file beside a cluster that names who made it. The Mac app reads it too."""
    return pgdata.parent / f"{pgdata.name}.owner.json"


def claim_cluster(pgdata: Path, owner: str) -> None:
    """Allow `owner` only a cluster it made, recording the claim before it makes one.

    A source install writes no record, so an existing cluster without one is a
    source install's, even after its registration and background item are gone.
    The record is written before initdb, so a creation that dies halfway leaves
    a cluster its maker can still open.
    """
    pgdata = Path(pgdata).expanduser()
    record = owner_record(pgdata)
    try:
        recorded = json.loads(record.read_text()).get("owner")
    except FileNotFoundError:
        recorded = None
    except (OSError, ValueError, AttributeError):
        recorded = ""
    if recorded == owner:
        return
    if recorded is not None or (pgdata / "PG_VERSION").exists():
        raise ClusterOwnedElsewhere(
            f"the database at {pgdata} was made by another installation"
            + (f" ({recorded})" if recorded else "") + " and stays in its care"
        )
    record.parent.mkdir(parents=True, exist_ok=True)
    partial = record.with_name(record.name + ".partial")
    partial.write_text(json.dumps({"owner": owner}) + "\n")
    os.replace(partial, record)


# Upstream versions whose behaviour this module was verified against. The four
# corrections in the module docstring were *measured*, not read off a README,
# and two of them hold private upstream state (`PostgresServer._lock`,
# `PostgresServer._instances`) — none of that is API, so an unverified wheel
# must fail loudly here rather than misbehave silently later.
VERIFIED_UPSTREAM_VERSIONS = ("0.6.0",)


def _upstream():
    """Import `pixeltable_pgserver` through the one door that checks the pin."""
    try:
        import pixeltable_pgserver as pgserver  # noqa: PLC0415 - optional at import time
    except ImportError as exc:  # pragma: no cover - install-time failure
        raise EmbeddedDbError(
            "pixeltable-pgserver is not installed; it is required unless "
            "ROLEBAND_DATABASE_URL points at an external Postgres."
        ) from exc
    version = metadata.version("pixeltable-pgserver")
    if version not in VERIFIED_UPSTREAM_VERSIONS:
        raise EmbeddedDbError(
            f"pixeltable-pgserver {version} has not been verified against this module "
            f"(verified: {', '.join(VERIFIED_UPSTREAM_VERSIONS)}). It depends on private "
            f"upstream API and measured behaviours (module docstring). Re-measure them, "
            f"add the version to VERIFIED_UPSTREAM_VERSIONS, and rebuild the pinned "
            f"pg_trgm bundles with `python -m scripts.package_pg_contrib`."
        )
    return pgserver


@dataclass(frozen=True)
class EmbeddedServer:
    """A running embedded server plus the facts callers need to reach it."""

    pgdata: Path
    database: str
    bin_dir: Path
    base_uri: str  # libpq URI from postmaster.pid, pointing at `database`

    def uri(self, *, driver: str = "asyncpg") -> str:
        """SQLAlchemy URL for this server (unix socket or TCP, as it runs)."""
        scheme, _, rest = self.base_uri.partition("://")
        if scheme != "postgresql":  # upstream contract changed under us
            raise EmbeddedDbError(f"unexpected URI scheme from pgserver: {self.base_uri!r}")
        # Upstream renders the trust-on-socket user as `postgres:@` — an empty
        # password. Drop exactly that so drivers do not negotiate password auth,
        # scoped to the userinfo section: a non-empty password (an upstream
        # contract change) must pass through untouched, and a blind substring
        # replace could hit one that merely contains `:@`.
        netloc, slash, tail = rest.partition("/")
        userinfo, at, hostport = netloc.rpartition("@")
        if at and userinfo.endswith(":"):
            netloc = f"{userinfo[:-1]}{at}{hostport}"
        return f"postgresql+{driver}://{netloc}{slash}{tail}"

    def dsn(self) -> str:
        """Plain libpq URI, for psql/pg_dump/pg_restore."""
        return self.base_uri

    def tool(self, name: str) -> Path:
        """Absolute path to a bundled client binary (`pg_dump`, `psql`, ...)."""
        return _tool(self.bin_dir, name)


def bundled_bin_dir(postgres_version: int = DEFAULT_POSTGRES_VERSION) -> Path:
    """Client binaries for a bundled major, without starting anything.

    Lets read-only tooling (a migration dry run, a backup that only needs
    `pg_dump`) reach the wheel's tools without initdb'ing a cluster first.
    """
    _upstream()
    from pixeltable_pgserver.utils import POSTGRES_VERSIONS  # noqa: PLC0415

    bin_dir = POSTGRES_VERSIONS.get(postgres_version)
    if bin_dir is None:
        raise EmbeddedDbError(
            f"wheel bundles no PG {postgres_version}; has {sorted(POSTGRES_VERSIONS)}"
        )
    return Path(bin_dir)


def _tool(bin_dir: Path, name: str) -> Path:
    """Absolute path to a bundled client binary, Windows suffix applied.

    The single place that knows how a tool name becomes an executable path;
    `EmbeddedServer.tool()` and `run_psql` both resolve through it.
    """
    exe = bin_dir / (f"{name}.exe" if os.name == "nt" else name)
    if not exe.exists():
        raise EmbeddedDbError(f"{name} not found in the pgserver wheel at {bin_dir}")
    return exe


def run_psql(server_dsn: str, bin_dir: Path, sql: str, *, timeout: float | None = 60.0) -> str:
    """Run one statement through the bundled psql, raising on SQL error.

    The one psql runner — app code, scripts, and tests all use this.
    `PostgresServer.psql()` shells out without ON_ERROR_STOP and so returns 0
    for a failed statement; every check in this codebase needs a real exit
    code. The timeout guards the watchdog's recovery path: a wedged postmaster
    that accepts connections but never answers would otherwise hang the
    supervisor forever — launchd will not start a second instance of a label
    that is still running. Pass `timeout=None` for statements that may
    legitimately run long (ANALYZE after a full restore).
    """
    try:
        proc = subprocess.run(
            [str(_tool(bin_dir, "psql")), server_dsn, "-v", "ON_ERROR_STOP=1", "-tAX", "-c", sql],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise EmbeddedDbError(f"psql timed out after {timeout:.0f}s running: {sql[:120]}") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise EmbeddedDbError(f"psql failed: {detail[0] if detail else 'no output'}")
    return (proc.stdout or "").strip()


@contextlib.contextmanager
def _pinned_locale(locale: str | None) -> Iterator[None]:
    """Pin initdb's locale. Only meaningful around a first-run initdb."""
    if not locale:
        yield
        return
    saved = {k: os.environ.get(k) for k in ("LC_ALL", "LC_COLLATE", "LC_CTYPE", "LANG")}
    os.environ.update({"LC_ALL": locale, "LC_COLLATE": locale, "LC_CTYPE": locale, "LANG": locale})
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def locale_available(name: str) -> bool:
    """Whether this host can set locale `name`, as initdb will try to.

    Asked in a child process: `setlocale` is process-global and not thread-safe,
    and this runs inside whatever process first touches the database.
    """
    probe = (
        "import locale, sys\n"
        "try:\n"
        "    locale.setlocale(locale.LC_ALL, sys.argv[1])\n"
        "except locale.Error:\n"
        "    sys.exit(1)\n"
    )
    return subprocess.run([sys.executable, "-c", probe, name], capture_output=True).returncode == 0


def _prune_dead_holders(pgdata: Path) -> int:
    """Drop PIDs of crashed holders from the refcount file. Returns count removed.

    Held under upstream's own interprocess lock so a concurrent start/exit
    cannot interleave with the read-modify-write.
    """
    import psutil  # noqa: PLC0415 - a pgserver dependency, not a direct one

    pgserver = _upstream()

    handle_file = pgdata / ".handle_pids.json"
    if not handle_file.exists():
        return 0

    lock = getattr(pgserver.PostgresServer, "_lock", None)
    with lock if lock is not None else contextlib.nullcontext():
        try:
            pids = json.loads(handle_file.read_text().strip() or "[]")
        except (OSError, json.JSONDecodeError):
            return 0
        live = [pid for pid in pids if psutil.pid_exists(pid)]
        if len(live) == len(pids):
            return 0
        handle_file.write_text(json.dumps(live))
        return len(pids) - len(live)


def stop_server(pgdata: Path, *, postgres_version: int = DEFAULT_POSTGRES_VERSION) -> bool:
    """Stop the server owning `pgdata`. Returns False if none was running.

    Shutdown is explicit because `DEFAULT_CLEANUP_MODE` keeps the server up
    across process exits. Uninstall calls this; nothing else needs to.
    """
    if not (pgdata / "postmaster.pid").exists():
        return False
    # False means "nothing was running". A missing/unverified wheel with a live
    # postmaster.pid is a failure to stop, not an absence — raise (via
    # `_upstream`/`bundled_bin_dir`) so uninstall reports it instead of
    # printing "was not running" over a server it left up.
    pgserver = _upstream()

    _prune_dead_holders(pgdata)
    exe = _tool(bundled_bin_dir(postgres_version), "pg_ctl")
    proc = subprocess.run(
        [str(exe), "-D", str(pgdata), "-w", "stop"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise EmbeddedDbError(f"could not stop server at {pgdata}: {(proc.stderr or '').strip()}")
    # Drop the cached handle so a later ensure_server() in this process restarts
    # rather than handing back a stopped one. Private upstream state, hence the
    # guarded access; `_upstream` has already verified the version.
    instances = getattr(pgserver.PostgresServer, "_instances", None)
    if isinstance(instances, dict):
        handle = instances.pop(pgdata.expanduser().resolve(), None)
        if handle is not None:
            # An explicit stop retires this handle as well as its cached entry.
            # Its exit callback otherwise tries to remove the same entry again.
            atexit.unregister(handle._cleanup)
            with handle._lock:
                handle.global_process_id_list.get_and_remove(os.getpid())
    return True


def _ensure_database(admin_dsn: str, bin_dir: Path, database: str) -> None:
    """Create `database` if absent, tolerating a concurrent creator.

    Concurrent callers can both observe a missing database before either
    creates it. Losing that race is success only when the database exists
    after the failed create.
    """
    exists_sql = f"SELECT 1 FROM pg_database WHERE datname='{database}'"
    if run_psql(admin_dsn, bin_dir, exists_sql) == "1":
        return
    try:
        # initdb creates superuser `postgres` and no application database.
        run_psql(admin_dsn, bin_dir, f'CREATE DATABASE "{database}"')
    except EmbeddedDbError:
        if run_psql(admin_dsn, bin_dir, exists_sql) != "1":
            raise


def require_extensions(server: EmbeddedServer, extensions: Sequence[str]) -> None:
    """Fail loudly if a required extension is not installable on this server.

    Without this check a missing prebuilt extension surfaces as a half-applied
    Alembic migration.
    """
    if not extensions:
        return
    names = ",".join(f"'{name}'" for name in extensions)
    available = set(
        run_psql(
            server.dsn(),
            server.bin_dir,
            f"SELECT name FROM pg_available_extensions WHERE name IN ({names})",
        ).split()
    )
    missing = [name for name in extensions if name not in available]
    if missing:
        raise EmbeddedDbError(
            f"embedded Postgres at {server.pgdata} is missing required extension(s): "
            f"{', '.join(missing)}. Install the matching prebuilt pg_trgm with "
            f"`python -m scripts.install_pg_contrib`. If another extension is missing, "
            f"check that the database runtime supports it."
        )


def _quoted_server(pgserver, pgdata: Path, postgres_version: int, server_settings: Mapping[str, str]):
    """Start with quoted postgres options, then use upstream's holder lifecycle.

    pg_ctl executes its -o string through a shell. Upstream quotes neither the
    socket directory nor shell syntax in it, and passes no `-c` settings. Start
    under the same lock before asking upstream to attach, without patching its
    process-global functions. A server already running keeps the settings it
    started with: nothing here restarts one.
    """
    from pixeltable_pgserver.postgres_server import PostmasterInfo, find_suitable_socket_dir, pgexec

    handle = pgserver.get_server(
        pgdata, cleanup_mode=DEFAULT_CLEANUP_MODE, postgres_version=postgres_version, start=False,
    )
    if pgdata.resolve() in pgserver.PostgresServer._instances:
        return handle
    with handle._lock:
        handle.ensure_pgdata_inited()
        info = PostmasterInfo.read_from_pgdata(handle.pgdata)
        if info is None or not info.is_running():
            socket = find_suitable_socket_dir(handle.pgdata, handle.runtime_path)
            if handle.system_user is not None and socket != handle.pgdata:
                from pixeltable_pgserver.postgres_server import ensure_prefix_permissions

                ensure_prefix_permissions(socket)
                socket.chmod(0o777)
            options = ["-D", str(handle.pgdata), "-h", "", "-k", str(socket)]
            for name, value in server_settings.items():
                options += ["-c", f"{name}={value}"]
            logger.info("starting embedded Postgres at %s with %s", handle.pgdata,
                        " ".join(f"{name}={value}" for name, value in server_settings.items()) or "stock settings")
            pgexec(
                "pg_ctl",
                # -D and -l are otherwise interpolated into pg_ctl's shell
                # command. PGDATA plus a relative log keeps both paths literal.
                ("-w", "-o", shlex.join(options), "-l", "log", "start"),
                bin_path=handle.bin_path, user=handle.system_user, timeout=10, cwd=handle.pgdata,
                env={**os.environ, "PGDATA": str(handle.pgdata)},
            )
    handle.start()
    return handle


def ensure_server(
    pgdata: Path,
    *,
    database: str,
    postgres_version: int = DEFAULT_POSTGRES_VERSION,
    locale: str | None = DEFAULT_LOCALE,
    required_extensions: Sequence[str] = (),
    server_settings: Mapping[str, str] | None = None,
) -> EmbeddedServer:
    """Start or attach the server owning `pgdata`, with `database` present.

    Idempotent and safe to call from every process: upstream refcounts holders
    in `<pgdata>/.handle_pids.json` and stops the server when the last exits.
    `server_settings` are `-c` settings for a start; attaching to a running
    server leaves its settings as they are.
    """
    pgserver = _upstream()

    pgdata = Path(pgdata).expanduser()
    pgdata.parent.mkdir(parents=True, exist_ok=True)
    first_run = not (pgdata / "PG_VERSION").exists()
    if first_run and locale and not locale_available(locale):
        # initdb would say only "invalid locale settings; check LANG and LC_*",
        # which points at the environment rather than at the pin that set it.
        # Minimal Linux images ship C, C.UTF-8 and POSIX and nothing else.
        raise EmbeddedDbError(
            f"cannot create the embedded database at {pgdata}: its collation is pinned to "
            f"{locale!r} and this system has no such locale. Install it (Debian/Ubuntu: "
            f"sudo apt-get install locales && sudo locale-gen {locale}), or choose one this "
            f"system has — `locale -a` lists them — with ROLEBAND_DB_LOCALE, e.g. "
            f"ROLEBAND_DB_LOCALE=C.UTF-8. It is chosen once, at this first start, and fixes "
            f"how text sorts for the life of the database."
        )
    _prune_dead_holders(pgdata)

    try:
        # Locale only matters on the initdb inside this call; on later calls the
        # cluster already exists and upstream skips initdb.
        with _pinned_locale(locale if first_run else None):
            if os.name != "nt":
                handle = _quoted_server(pgserver, pgdata, postgres_version, server_settings or {})
            else:
                handle = pgserver.get_server(
                    pgdata, cleanup_mode=DEFAULT_CLEANUP_MODE, postgres_version=postgres_version
                )
    except Exception as exc:
        log = pgdata / "log"
        tail = ""
        if log.exists():
            with contextlib.suppress(OSError):
                tail = "\n".join(log.read_text(errors="replace").splitlines()[-15:])
        raise EmbeddedDbError(
            f"could not start embedded Postgres at {pgdata}: {exc}"
            + (f"\n--- server log tail ---\n{tail}" if tail else "")
        ) from exc

    bin_dir = Path(handle.bin_path)
    admin_dsn = handle.get_uri()
    _ensure_database(admin_dsn, bin_dir, database)

    server = EmbeddedServer(
        pgdata=pgdata,
        database=database,
        bin_dir=bin_dir,
        base_uri=handle.get_uri(database=database),
    )
    require_extensions(server, required_extensions)
    return server
