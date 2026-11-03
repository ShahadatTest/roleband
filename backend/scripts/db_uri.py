"""Resolve the live database connection for shell scripts.

Backup, restore, and any other shell tooling must target the same database the
app targets. The socket directory is chosen by the pgserver wheel and is not a
path we can hardcode, so scripts ask here instead
of rebuilding a URL from settings.

    .venv/bin/python -m scripts.db_uri dsn        # libpq URI (psql, pg_dump)
    .venv/bin/python -m scripts.db_uri database   # the database name the app reads
    .venv/bin/python -m scripts.db_uri sync-url   # SQLAlchemy psycopg2 URL
    .venv/bin/python -m scripts.db_uri bin-dir    # bundled client binaries

`dsn` accepts `--database NAME` to point at a different database on the same
server — restore drills need a scratch target, and rewriting the URL in shell
is error-prone (a libpq URI's `?host=` makes `?` a glob metacharacter in bash
pattern substitution).

`database` is the name in the `dsn` the app connects with. A restore asks it
whether a target is the live database: `$ROLEBAND_POSTGRES_DB` in a shell is not
what the background app reads (it reads `backend/.env`), so a script that
trusted it would take the live database for a scratch one and drop it.

Starts the embedded server if it is not already running, exactly like the app.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse, urlunparse

from tracker.config import get_settings


def _with_database(dsn: str, database: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{database}"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.db_uri",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("what", choices=("dsn", "database", "url", "sync-url", "bin-dir"))
    parser.add_argument(
        "--database",
        help="dsn only: same server, a different database (restore drills)",
    )
    return parser


def main(argv: list[str]) -> int:
    parser = _parser()
    args = parser.parse_args(argv[1:])
    if args.database and args.what != "dsn":
        # Refuse rather than silently ignore: a restore drill that typed
        # `bin-dir --database x` should hear about it, not get a default.
        parser.error("--database applies only to dsn")

    settings = get_settings()

    if args.what in {"url", "sync-url"}:
        print(settings.database_url if args.what == "url" else settings.sync_database_url)
        return 0

    if args.what == "bin-dir":
        # Always the bundled tools: they are the only Postgres client binaries
        # this host is guaranteed to have, and they match the embedded server.
        # Reported without starting anything, so a backup can ask cheaply.
        from tracker.platform.embedded_db import bundled_bin_dir

        print(bundled_bin_dir())
        return 0

    # dsn, database
    if settings.database_url_override or not settings.db_embedded:
        # libpq form of whatever external server is configured.
        url = settings.database_url_override or settings.sync_database_url
        scheme, _, rest = url.partition("://")
        dsn = f"{scheme.split('+')[0]}://{rest}"
    else:
        dsn = settings.ensure_embedded_server().dsn()
    if args.what == "database":
        print(urlparse(dsn).path.lstrip("/"))
        return 0
    print(_with_database(dsn, args.database) if args.database else dsn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
