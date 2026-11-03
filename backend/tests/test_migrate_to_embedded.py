"""The one-time data move into the embedded server.

Exercised end to end between two embedded clusters — the migration has a source
and a target, and both are real Postgres in an ordinary test. What it
must guarantee: the copy is complete (per-table counts), the schema version
travels with it, the pgvector column survives, and the *source is never
touched* — it stays the rollback.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pixeltable_pgserver", reason="embedded Postgres wheel not installed")

from scripts.migrate_db_to_embedded import (  # noqa: E402
    MigrationError,
    _assert_target_empty,
    _libpq_url,
    migrate,
)
from tests.embedded_utils import cluster_locale, destroy, psql  # noqa: E402
from tracker.platform.embedded_db import (  # noqa: E402
    ensure_server,
    stop_server,
)

# A miniature of the real schema: the migrator inspects `jobs.embedding` and the
# alembic head, so a source without them would not exercise verification.
SOURCE_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY);
INSERT INTO alembic_version VALUES ('6abe6af0cbf9');
CREATE TABLE jobs (
  id bigserial PRIMARY KEY,
  title text NOT NULL,
  company text NOT NULL,
  embedding vector(768)
);
CREATE INDEX jobs_title_trgm ON jobs USING gin (title gin_trgm_ops);
INSERT INTO jobs (title, company, embedding)
SELECT 'Role '||g, 'anthropic',
       (SELECT ('['||string_agg('0.02', ',')||']')::vector FROM generate_series(1,768))
FROM generate_series(1,40) g;
CREATE TABLE job_observations (id bigserial PRIMARY KEY, job_id bigint NOT NULL);
INSERT INTO job_observations (job_id) SELECT (g % 40) + 1 FROM generate_series(1,120) g;
"""


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """A populated cluster standing in for the :5433 container."""
    pgdata = tmp_path_factory.mktemp("src") / "db"
    server = ensure_server(pgdata, database="roleband", required_extensions=("vector", "pg_trgm"),
                           locale=cluster_locale())
    psql(server, SOURCE_SCHEMA)
    yield server
    destroy(server.pgdata)


class TestPureHelpers:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("postgresql+asyncpg://u@h/db", "postgresql://u@h/db"),
            ("postgresql+psycopg2://u:p@h:5433/db", "postgresql://u:p@h:5433/db"),
            ("postgresql://u@h/db", "postgresql://u@h/db"),
        ],
    )
    def test_driver_suffix_is_stripped_for_libpq_tools(self, url, expected):
        assert _libpq_url(url) == expected

    def test_initialised_target_is_refused(self, tmp_path):
        pgdata = tmp_path / "db"
        pgdata.mkdir()
        (pgdata / "PG_VERSION").write_text("16\n")
        with pytest.raises(MigrationError, match="already initialised"):
            _assert_target_empty(pgdata)

    def test_empty_target_is_accepted(self, tmp_path):
        _assert_target_empty(tmp_path / "does-not-exist-yet")


class TestEndToEndCopy:
    def test_copies_every_row_and_leaves_the_source_untouched(self, source, tmp_path):
        before = {
            "jobs": psql(source, "SELECT count(*) FROM jobs"),
            "observations": psql(source, "SELECT count(*) FROM job_observations"),
            "head": psql(source, "SELECT version_num FROM alembic_version"),
        }

        target_pgdata = tmp_path / "target" / "db"
        target_pgdata.parent.mkdir(parents=True)
        rc = migrate(source.dsn(), target_pgdata, database="roleband")
        assert rc == 0

        target = ensure_server(target_pgdata, database="roleband", locale=cluster_locale())
        try:
            assert psql(target, "SELECT count(*) FROM jobs") == before["jobs"] == "40"
            assert psql(target, "SELECT count(*) FROM job_observations") == "120"
            assert psql(target, "SELECT version_num FROM alembic_version") == before["head"]
            # The vector type survived the restore, at full width.
            assert psql(target, "SELECT vector_dims(embedding) FROM jobs LIMIT 1") == "768"
            # And the trigram index came across, not just the rows.
            assert psql(
                target, "SELECT count(*) FROM pg_indexes WHERE indexdef LIKE '%gin_trgm_ops%'"
            ) == "1"

            # The source is the rollback: it must be exactly as it was.
            assert psql(source, "SELECT count(*) FROM jobs") == before["jobs"]
            assert psql(source, "SELECT count(*) FROM job_observations") == before["observations"]
            assert psql(source, "SELECT version_num FROM alembic_version") == before["head"]
        finally:
            destroy(target_pgdata)

    def test_refuses_to_migrate_into_an_existing_cluster(self, source, tmp_path):
        """The guard that stops a second run from restoring over live data."""
        target_pgdata = tmp_path / "occupied" / "db"
        target_pgdata.parent.mkdir(parents=True)
        occupied = ensure_server(target_pgdata, database="roleband", locale=cluster_locale())
        try:
            with pytest.raises(MigrationError, match="already initialised"):
                migrate(source.dsn(), occupied.pgdata, database="roleband")
        finally:
            destroy(target_pgdata)

    def test_dry_run_reports_without_creating_a_cluster(self, source, tmp_path):
        target_pgdata = tmp_path / "dry" / "db"
        target_pgdata.parent.mkdir(parents=True)
        assert migrate(source.dsn(), target_pgdata, database="roleband", dry_run=True) == 0
        assert not target_pgdata.exists()


class TestServerLifecycle:
    """Shutdown is explicit, because the server outlives the process that started it."""

    def test_stop_then_restart(self, tmp_path):
        pgdata = tmp_path / "db"
        ensure_server(pgdata, database="probe")
        try:
            assert (pgdata / "postmaster.pid").exists()

            assert stop_server(pgdata) is True
            assert not (pgdata / "postmaster.pid").exists()
            assert stop_server(pgdata) is False  # already stopped, not an error

            restarted = ensure_server(pgdata, database="probe")
            assert psql(restarted, "SELECT 1") == "1"
        finally:
            destroy(pgdata)
