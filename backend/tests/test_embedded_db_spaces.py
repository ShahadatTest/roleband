"""Real Postgres and psql work under app and data paths containing shell syntax."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.embedded_utils import cluster_locale
from tracker.platform.embedded_db import bundled_bin_dir, ensure_server, run_psql, stop_server


@pytest.mark.parametrize("name", ["user home", "user's home", "user $(false) home"])
def test_space_and_quoted_paths_start_query_reattach_and_stop(tmp_path, monkeypatch, name):
    from pixeltable_pgserver.utils import POSTGRES_VERSIONS

    original = bundled_bin_dir()
    runtime = tmp_path / "RoleBand Test.app" / "Postgres"
    shutil.copytree(original.parent, runtime)
    # A Linux wheel keeps the shared libraries beside the package, where bin/ finds
    # them at $ORIGIN/../../../pixeltable_pgserver.libs; a macOS wheel keeps them inside.
    libs = original.parents[2] / "pixeltable_pgserver.libs"
    if libs.is_dir():
        shutil.copytree(libs, (runtime / "bin").parents[2] / libs.name)
    monkeypatch.setitem(POSTGRES_VERSIONS, 16, runtime / "bin")
    with tempfile.TemporaryDirectory(prefix="rb-space-", dir="/tmp") as short:
        pgdata = Path(short) / name / "db"
        try:
            server = ensure_server(pgdata, database="probe", locale=cluster_locale(), required_extensions=("vector", "pg_trgm"))
            assert server.bin_dir == runtime / "bin"
            assert run_psql(server.dsn(), server.bin_dir, "SELECT 42") == "42"
            async def query():
                engine = create_async_engine(server.uri())
                try:
                    async with engine.connect() as connection:
                        assert await connection.scalar(text("SELECT 42")) == 42
                finally:
                    await engine.dispose()
            asyncio.run(query())
            assert ensure_server(pgdata, database="probe").dsn() == server.dsn()
            assert stop_server(pgdata)
            restarted = ensure_server(pgdata, database="probe")
            assert run_psql(restarted.dsn(), restarted.bin_dir, "SELECT 43") == "43"
        finally:
            stop_server(pgdata)
