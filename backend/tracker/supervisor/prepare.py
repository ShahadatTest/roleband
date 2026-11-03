"""Prepare an app-owned database while a schema-free loopback responder answers."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tracker import __version__
from tracker.config import get_settings
from tracker.platform import preparation
from tracker.platform.embedded_db import claim_cluster
from tracker.platform.launcher import installation_identity
from tracker.platform.paths import BACKEND_DIR, DATA_DIR, REPO_ROOT

logger = logging.getLogger(__name__)

# Bounds a hung migration. Upgrading a large database, after the dump taken before it, can take
# many minutes; the update helper in the Mac app waits this long before it rolls the update back.
PREPARE_TIMEOUT_SECONDS = 1800


def health() -> dict[str, Any]:
    settings = get_settings()
    return preparation.payload(
        DATA_DIR,
        installation_identity(
            REPO_ROOT, api_host=settings.api_host, api_port=settings.api_port, version=__version__,
        ),
    )


class PreparationServer:
    def __init__(self, host: str, port: int) -> None:
        if host != "127.0.0.1":
            raise ValueError("Preparation must bind the loopback address")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                assert isinstance(self.server, ThreadingHTTPServer)
                actual_port = self.server.server_address[1]
                if self.headers.get("Host") not in {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}:
                    self.send_error(400)
                    return
                if self.path != "/api/launcher-health":
                    self.send_error(404)
                    return
                body = health()
                content = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> PreparationServer:
        self.thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def migrate() -> None:
    import asyncio

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    from alembic import command
    from tracker.platform.backups import dump_database

    settings = get_settings()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    engine = create_engine(settings.sync_database_url)
    try:
        with engine.connect() as connection:
            current = set(MigrationContext.configure(connection).get_current_heads())
        target = set(ScriptDirectory.from_config(config).get_heads())
        # A schema that already holds data is backed up before any upgrade.
        if current and current != target:
            dump_database(settings.ensure_embedded_server(), DATA_DIR / "backups")
        if current != target:
            command.upgrade(config, "head")
    finally:
        engine.dispose()
    # Roles stored before `jobs.arrival` existed are classified before the
    # engine starts: no reader may count a first read's finds as new. A
    # preparation stopped part way resumes here.
    from tracker.workflows.arrival_backfill import backfill_arrivals

    asyncio.run(backfill_arrivals())


def run() -> None:
    settings = get_settings()
    if settings.database_url_override or not settings.db_embedded:
        raise ValueError("App preparation requires its own embedded database")
    home = Path.home()
    if (DATA_DIR / "launcher" / "installation.json").exists() or (home / "Library/LaunchAgents/com.roleband.plist").exists():
        raise ValueError("An install from source keeps its own engine")
    claim_cluster(settings.embedded_pgdata(), "app")
    preparation.update(DATA_DIR, database="creating", service="starting", reason=None)
    with PreparationServer(settings.api_host, settings.api_port):
        try:
            subprocess.run(
                [sys.executable, "-I", str(BACKEND_DIR / "packaged.py"), "prepare-database"],
                check=True, timeout=PREPARE_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001 - the responder remains available for Retry and Quit
            logger.exception("database preparation failed")
            preparation.update(DATA_DIR, database="failed", reason="database_failed")
            threading.Event().wait()
        preparation.update(DATA_DIR, database="ready")
