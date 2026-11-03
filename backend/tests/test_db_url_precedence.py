"""Database URL resolution: override > embedded > the :5433 container.

Pure settings logic, no server. The embedded branch is asserted by *not* being
taken — a test here must never start Postgres, which is also the guarantee that
`--help` and OpenAPI export stay serverless.
"""

from __future__ import annotations

import os

import pytest

from tracker.config import Settings


def _settings(**kwargs) -> Settings:
    # _env_file=None: the developer's own .env must not decide the outcome.
    return Settings(_env_file=None, **kwargs)


@pytest.fixture(autouse=True)
def _no_ambient_db_config(monkeypatch):
    """Take the ambient environment out of a test about precedence.

    `_env_file=None` above covers the developer's `.env` and stops one layer
    short: pydantic-settings still reads the process environment, and CI sets
    `ROLEBAND_DATABASE_URL` at job level to point pytest at its Postgres
    service. Every assertion here is about which source wins, so an override
    arriving from outside the test does not perturb the result, it replaces it.

    It also beats an explicit constructor argument, which is the part worth
    knowing: `database_url_override` carries `validation_alias`, so init
    contributes the field NAME while the environment contributes the ALIAS, and
    pydantic resolves the alias. `_settings(database_url_override=...)` is
    therefore not self-sufficient — hence clearing rather than passing.

    That is how a test passes locally and fails in CI; running this module
    with the variable set reproduces it.

    `ROLEBAND_PGDATA` is cleared for the same reason. It carries a
    `validation_alias` too, so the paragraph above applies to it word for word:
    `_settings(db_pgdata=...)` is not self-sufficient either, and with it set
    `TestPgdataLocation` fails BOTH ways: the override test because the ambient
    value beats the argument, and the default test because there is no default
    left to observe. Anyone running with an isolated data home sees it: a
    second checkout, an upgrade rehearsal, or a contributor told (rightly) not
    to point a rehearsal at the live cluster.
    """
    monkeypatch.delenv("ROLEBAND_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ROLEBAND_PGDATA", raising=False)


class TestOverrideWins:
    def test_override_beats_embedded_and_never_starts_a_server(self, monkeypatch):
        # Any attempt to start the embedded server here is a bug, so make it fatal.
        import tracker.platform.embedded_db as embedded

        monkeypatch.setattr(
            embedded,
            "ensure_server",
            lambda *a, **k: pytest.fail("override must not start the embedded server"),
        )
        settings = _settings(
            database_url_override="postgresql://u:p@example.internal:5432/other",
            db_embedded=True,
        )
        assert settings.database_url == "postgresql+asyncpg://u:p@example.internal:5432/other"
        assert settings.sync_database_url == "postgresql+psycopg2://u:p@example.internal:5432/other"

    def test_override_keeps_an_explicit_driver(self):
        settings = _settings(database_url_override="postgresql+asyncpg://u@h/db")
        assert settings.database_url == "postgresql+asyncpg://u@h/db"

    def test_override_reads_the_prefixed_env_var(self, monkeypatch):
        # A bare DATABASE_URL is deliberately NOT honored: Settings sets no
        # env_prefix, so it would capture any ambient shell value.
        monkeypatch.setenv("DATABASE_URL", "postgresql://ambient@host/wrong")
        monkeypatch.setenv("ROLEBAND_DATABASE_URL", "postgresql://right@host/db")
        settings = _settings()
        assert "right@host/db" in settings.database_url
        assert "ambient" not in settings.database_url


class TestExternalContainerFallback:
    def test_db_embedded_false_uses_the_postgres_fields(self):
        settings = _settings(db_embedded=False, postgres_host="localhost", postgres_port=5433)
        assert settings.database_url == (
            "postgresql+asyncpg://roleband:roleband@localhost:5433/roleband"
        )
        assert settings.sync_database_url == (
            "postgresql+psycopg2://roleband:roleband@localhost:5433/roleband"
        )


class TestImportStartsNoServer:
    """Importing app code must not start Postgres.

    The URL property starts the embedded server on access, so an import-time
    engine would boot a database from `scripts.export_openapi` (which
    `npm run gen:api` runs and whose whole point is being serverless), from
    pytest collection, and from `--help` on every CLI entrypoint.
    """

    @pytest.mark.parametrize(
        "module", ["tracker.api.app", "tracker.api.deps", "tracker.db.session"]
    )
    def test_importing_does_not_initdb(self, tmp_path, module):
        import subprocess
        import sys
        from pathlib import Path

        pgdata = tmp_path / "db"
        env = {
            **os.environ,
            "ROLEBAND_PGDATA": str(pgdata),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-1500:]
        assert not (pgdata / "PG_VERSION").exists(), f"importing {module} started a server"


class TestPgdataLocation:
    def test_env_override_is_honored(self, tmp_path):
        settings = _settings(db_pgdata=str(tmp_path / "cluster"))
        assert settings.embedded_pgdata() == tmp_path / "cluster"

    def test_default_is_user_data_not_the_checkout(self):
        # The checkout is replaced by upgrades and may sit in a synced folder;
        # the longitudinal asset must not live there.
        from tracker.platform.paths import REPO_ROOT

        pgdata = _settings().embedded_pgdata()
        assert REPO_ROOT not in pgdata.parents
        assert pgdata.name == "db"
