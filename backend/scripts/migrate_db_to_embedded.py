"""Copy an existing RoleBand database into the embedded server, then verify it.

The only step in the embedded-DB cutover that touches the longitudinal asset,
so it is copy-then-verify and never in-place:

* the source is opened **read-only** — `pg_dump` and nothing else;
* the target must be an empty PGDATA, or the run refuses to start;
* the source database and its Docker volume are left completely untouched, and
  stay the rollback until deleted by hand. This script never deletes them.

    .venv/bin/python -m scripts.migrate_db_to_embedded --source-url URL [--pgdata PATH]
    .venv/bin/python -m scripts.migrate_db_to_embedded --dry-run

Default source is the :5433 container from `postgres_*` settings; default
target is the configured embedded PGDATA.

Verification is the point, not the copy. Row counts are compared per table
across every table in the schema, the Alembic head must match, and the pgvector
column is spot-checked for dimensionality — a restore that silently dropped the
`vector` type would otherwise look like a success.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from tracker.config import REQUIRED_EXTENSIONS, get_settings
from tracker.platform.embedded_db import (
    DEFAULT_POSTGRES_VERSION,
    EmbeddedDbError,
    EmbeddedServer,
    bundled_bin_dir,
    ensure_server,
    run_psql,
)


class MigrationError(RuntimeError):
    """Migration refused or failed verification. The source is unchanged."""


def _libpq_url(url: str) -> str:
    """Strip a SQLAlchemy driver suffix: pg_dump speaks libpq, not `+asyncpg`."""
    scheme, _, rest = url.partition("://")
    return f"{scheme.split('+')[0]}://{rest}"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _psql(server_dsn: str, bin_dir: Path, sql: str) -> str:
    """The shared runner, without a timeout: this is an interactive operator
    tool, statements like the verification counts and ANALYZE legitimately
    scale with the database, and Ctrl-C is the bound."""
    return run_psql(server_dsn, bin_dir, sql, timeout=None)


def _server_major(dsn: str, bin_dir: Path) -> int:
    return int(_psql(dsn, bin_dir, "SHOW server_version").split(".")[0])


def _table_counts(dsn: str, bin_dir: Path) -> dict[str, int]:
    """Exact row count per public table. Slower than the planner estimate, and
    the only thing that can prove the copy is complete."""
    names = _psql(
        dsn,
        bin_dir,
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
    ).split()
    if not names:
        return {}
    union = " UNION ALL ".join(
        f"SELECT '{name}' AS t, count(*) AS n FROM \"{name}\"" for name in names
    )
    counts: dict[str, int] = {}
    for line in _psql(dsn, bin_dir, f"SELECT t||' '||n FROM ({union}) s ORDER BY t").splitlines():
        table, _, count = line.partition(" ")
        if table:
            counts[table] = int(count)
    return counts


def _assert_target_empty(pgdata: Path) -> None:
    if (pgdata / "PG_VERSION").exists():
        raise MigrationError(
            f"target PGDATA already initialised: {pgdata}. Refusing to migrate into an "
            f"existing cluster — move it aside or pass --pgdata for a fresh path."
        )


def migrate(
    source_url: str,
    pgdata: Path,
    *,
    database: str,
    dry_run: bool = False,
) -> int:
    source_dsn = _libpq_url(source_url)
    host = urlparse(source_dsn).hostname or "?"
    print(f"source : {host} ({source_dsn.split('@')[-1]})")
    print(f"target : {pgdata}")

    # A dry run must start nothing, so it borrows the wheel's client binaries
    # directly; a real run starts the target first, which guarantees the dump
    # tool and the restore target are the same build.
    server: EmbeddedServer | None = None
    if dry_run:
        bin_dir = bundled_bin_dir()
    else:
        _assert_target_empty(pgdata)
        server = ensure_server(
            pgdata, database=database, required_extensions=REQUIRED_EXTENSIONS
        )
        bin_dir = server.bin_dir

    src_major = _server_major(source_dsn, bin_dir)
    # On a dry run nothing is started; the target major is the wheel's pinned
    # one — `bundled_bin_dir()` above selected its install tree by exactly
    # this number, so shelling out to pg_config would only re-derive it.
    dst_major = (
        _server_major(server.dsn(), bin_dir) if server is not None else DEFAULT_POSTGRES_VERSION
    )
    print(f"majors : source PG {src_major} -> embedded PG {dst_major}")
    if dst_major < src_major:
        # pg_dump cannot read a server newer than itself.
        raise MigrationError(
            f"embedded PG {dst_major} is older than source PG {src_major}; "
            f"pin a newer wheel major before migrating."
        )

    source_counts = _table_counts(source_dsn, bin_dir)
    source_head = _psql(source_dsn, bin_dir, "SELECT version_num FROM alembic_version")
    total = sum(source_counts.values())
    print(f"source : {len(source_counts)} tables, {total:,} rows, alembic head {source_head}")

    if dry_run:
        print("\ndry run: nothing copied.")
        return 0

    dump = pgdata.parent / "roleband-migration.dump"
    print(f"\ndumping to {dump} ...")
    proc = _run([str(server.tool("pg_dump")), source_dsn, "-Fc", "-f", str(dump)])
    if proc.returncode != 0:
        raise MigrationError(f"pg_dump failed: {(proc.stderr or '').strip()[-500:]}")
    print(f"dump   : {dump.stat().st_size / 1e6:.1f} MB")

    print("restoring ...")
    # --no-owner/--no-privileges: the dump is owned by role `roleband`, which does
    # not exist on an embedded cluster (initdb creates only `postgres`).
    restore = _run(
        [
            str(server.tool("pg_restore")),
            "--no-owner",
            "--no-privileges",
            "--dbname",
            server.dsn(),
            str(dump),
        ]
    )
    if restore.returncode != 0:
        # pg_restore exits non-zero on ignorable notices; only a row-count
        # mismatch below decides whether this actually failed.
        print(f"  pg_restore warnings:\n{(restore.stderr or '').strip()[-800:]}", file=sys.stderr)

    print("verifying ...")
    failures: list[str] = []

    target_counts = _table_counts(server.dsn(), bin_dir)
    for table, expected in sorted(source_counts.items()):
        got = target_counts.get(table)
        if got != expected:
            failures.append(f"{table}: {expected} rows in source, {got} in target")
    missing = set(source_counts) - set(target_counts)
    if missing:
        failures.append(f"tables absent from target: {', '.join(sorted(missing))}")

    target_head = _psql(server.dsn(), bin_dir, "SELECT version_num FROM alembic_version")
    if target_head != source_head:
        failures.append(f"alembic head {target_head} != source {source_head}")

    dims = _psql(
        server.dsn(),
        bin_dir,
        "SELECT coalesce(max(vector_dims(embedding))::text,'none') FROM jobs "
        "WHERE embedding IS NOT NULL",
    )
    if dims not in {"768", "none"}:
        failures.append(f"jobs.embedding has {dims} dims, expected 768")

    for extension in REQUIRED_EXTENSIONS:
        installed = _psql(
            server.dsn(), bin_dir, f"SELECT count(*) FROM pg_extension WHERE extname='{extension}'"
        )
        if installed != "1":
            failures.append(f"extension {extension} not present after restore")

    if failures:
        raise MigrationError(
            "verification FAILED — the source database is untouched:\n  "
            + "\n  ".join(failures)
        )

    print("analyzing ...")
    _psql(server.dsn(), bin_dir, "ANALYZE")

    print(
        f"\nOK: {len(source_counts)} tables, {total:,} rows, head {target_head}, "
        f"embedding dims {dims}."
    )
    print(f"The source database is unchanged and remains the rollback. Dump kept at {dump}.")
    return 0


def main(argv: list[str]) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-url",
        default=(
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        ),
        help="libpq URL of the database to copy from (default: the :5433 container)",
    )
    parser.add_argument("--pgdata", type=Path, default=None, help="target PGDATA")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be copied; touches neither database",
    )
    args = parser.parse_args(argv[1:])

    pgdata = args.pgdata or settings.embedded_pgdata()
    try:
        return migrate(
            args.source_url, pgdata, database=settings.postgres_db, dry_run=args.dry_run
        )
    except (MigrationError, EmbeddedDbError) as exc:
        print(f"\nmigration aborted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
