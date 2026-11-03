"""The embedded server, and the Postgres feature surface the schema stands on.

Two jobs:

1. Pin the lifecycle behaviours `platform/embedded_db.py` exists to correct —
   pinned locale, stale-holder pruning, URI derivation, extension assertion.
2. Assert, against a *real* server, the dialect features the codebase depends
   on: pgvector HNSW at 768 dims, pg_trgm fuzzy search, JSONB containment,
   ARRAY operators, tsvector websearch, ON CONFLICT upsert, advisory locks.

An embedded server makes (2) ordinary tests rather than invariants exercised
only by running the app.

Skipped only when the wheel is absent (a broken environment). A *missing
extension* is a failure, never a skip: the prebuilt `pg_trgm` must be installed
alongside the database runtime.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pixeltable_pgserver", reason="embedded Postgres wheel not installed")

from tests.embedded_utils import cluster_locale, destroy  # noqa: E402
from tests.embedded_utils import psql as sql
from tracker.platform.database_presets import LARGE, STANDARD  # noqa: E402
from tracker.platform.embedded_db import (  # noqa: E402
    DEFAULT_POSTGRES_VERSION,
    EmbeddedDbError,
    EmbeddedServer,
    _prune_dead_holders,
    ensure_server,
    require_extensions,
    stop_server,
)

REQUIRED = ("vector", "pg_trgm")


@pytest.fixture(scope="module")
def server(tmp_path_factory) -> EmbeddedServer:
    """One throwaway cluster for the module; initdb is the expensive part."""
    pgdata = tmp_path_factory.mktemp("pg") / "db"
    srv = ensure_server(pgdata, database="probe", required_extensions=REQUIRED, locale=cluster_locale())
    yield srv
    destroy(srv.pgdata)


class TestLifecycle:
    def test_required_extensions_are_installable(self, server):
        installed = sql(
            server,
            "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
            " SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension"
            " WHERE extname IN ('vector','pg_trgm')",
        )
        assert installed.splitlines()[-1] == "pg_trgm,vector"

    def test_missing_extension_is_named_in_the_error(self, server):
        with pytest.raises(EmbeddedDbError) as exc:
            require_extensions(server, ("definitely_not_an_extension",))
        assert "definitely_not_an_extension" in str(exc.value)
        assert "install_pg_contrib" in str(exc.value)

    def test_locale_is_pinned_not_inherited(self, tmp_path, monkeypatch):
        # Upstream passes no --locale, so without pinning the cluster would bake
        # in whatever the ambient environment happened to be, permanently.
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")
        srv = ensure_server(tmp_path / "loc", database="probe", locale="en_US.UTF-8")
        try:
            collation = sql(
                srv, "SELECT datcollate FROM pg_database WHERE datname=current_database()"
            )
            assert collation == "en_US.UTF-8"
        finally:
            destroy(srv.pgdata)

    def test_attach_is_idempotent_and_reuses_the_cluster(self, server):
        again = ensure_server(
            server.pgdata, database=server.database, required_extensions=REQUIRED, locale=cluster_locale()
        )
        assert again.dsn() == server.dsn()
        assert again.pgdata == server.pgdata

    def test_uri_targets_the_app_database_without_an_empty_password(self, server):
        url = server.uri(driver="asyncpg")
        assert url.startswith("postgresql+asyncpg://")
        assert ":@" not in url  # empty password would trigger password auth
        assert f"/{server.database}" in url
        assert server.uri(driver="psycopg2").startswith("postgresql+psycopg2://")

    def test_bundled_client_binaries_are_reachable(self, server):
        # Backup and restore depend on these: they run the wheel's own tools so
        # the dump format always matches the server.
        for tool in ("pg_dump", "pg_restore", "psql"):
            assert server.tool(tool).exists()
        with pytest.raises(EmbeddedDbError):
            server.tool("not_a_postgres_tool")

    def test_pgdata_carries_the_pinned_major(self, server):
        assert (server.pgdata / "PG_VERSION").read_text().strip() == str(DEFAULT_POSTGRES_VERSION)


class TestUriDerivation:
    """Pure URL surgery on the upstream base URI — no server involved."""

    def _server(self, base_uri: str) -> EmbeddedServer:
        return EmbeddedServer(
            pgdata=Path("/x"), database="roleband", bin_dir=Path("/bin"), base_uri=base_uri
        )

    def test_socket_uri_drops_the_empty_password_and_keeps_the_host_query(self):
        srv = self._server("postgresql://postgres:@/roleband?host=/tmp/sock")
        assert srv.uri() == "postgresql+asyncpg://postgres@/roleband?host=/tmp/sock"

    def test_tcp_uri_drops_the_empty_password(self):
        srv = self._server("postgresql://postgres:@127.0.0.1:5433/roleband")
        assert srv.uri(driver="psycopg2") == "postgresql+psycopg2://postgres@127.0.0.1:5433/roleband"

    def test_a_real_password_passes_through_untouched(self):
        # Would only appear if upstream stopped using trust-on-socket; it must
        # then reach the driver intact, even when it contains `:@` itself.
        srv = self._server("postgresql://postgres:se:@cret@h:5/roleband")
        assert srv.uri() == "postgresql+asyncpg://postgres:se:@cret@h:5/roleband"

    def test_an_unexpected_scheme_is_refused(self):
        with pytest.raises(EmbeddedDbError, match="unexpected URI scheme"):
            self._server("mysql://root@h/roleband").uri()


class TestUpstreamVersionGate:
    """Private upstream API is verified per version; an unknown wheel fails loudly."""

    def test_unverified_wheel_version_is_refused_with_remediation(self, monkeypatch, tmp_path):
        import tracker.platform.embedded_db as embedded

        monkeypatch.setattr(embedded.metadata, "version", lambda dist: "0.9.9")
        with pytest.raises(EmbeddedDbError) as exc:
            ensure_server(tmp_path / "db", database="probe")
        message = str(exc.value)
        assert "0.9.9" in message
        assert "VERIFIED_UPSTREAM_VERSIONS" in message
        assert "package_pg_contrib" in message
        assert not (tmp_path / "db").exists()  # refused before touching anything

    def test_the_installed_wheel_is_a_verified_version(self):
        # If this fails, the pin in requirements.txt moved without this module
        # being re-verified — which is exactly the situation the gate exists for.
        import importlib.metadata as md

        from tracker.platform.embedded_db import VERIFIED_UPSTREAM_VERSIONS

        assert md.version("pixeltable-pgserver") in VERIFIED_UPSTREAM_VERSIONS


class TestEnsureDatabaseRace:
    """Two processes can hit a fresh cluster together (API + watchdog at boot)."""

    def _fake_run_psql(self, script: list[str]):
        """Yield scripted answers; 'raise' simulates a failed CREATE DATABASE."""

        def fake(dsn, bin_dir, sql, **kwargs):
            answer = script.pop(0)
            if answer == "raise":
                raise EmbeddedDbError('psql failed: ERROR:  database "roleband" already exists')
            return answer

        return fake

    def test_losing_the_create_race_is_success(self, monkeypatch):
        import tracker.platform.embedded_db as embedded

        # absent -> CREATE fails (someone else won) -> present on re-check
        monkeypatch.setattr(embedded, "run_psql", self._fake_run_psql(["", "raise", "1"]))
        embedded._ensure_database("dsn", Path("/bin"), "roleband")  # must not raise

    def test_create_failure_with_the_database_still_absent_is_fatal(self, monkeypatch):
        import tracker.platform.embedded_db as embedded

        monkeypatch.setattr(embedded, "run_psql", self._fake_run_psql(["", "raise", ""]))
        with pytest.raises(EmbeddedDbError, match="already exists"):
            embedded._ensure_database("dsn", Path("/bin"), "roleband")

    def test_existing_database_is_left_alone(self, monkeypatch):
        import tracker.platform.embedded_db as embedded

        calls: list[str] = []
        monkeypatch.setattr(
            embedded, "run_psql", lambda dsn, b, sql, **k: (calls.append(sql), "1")[1]
        )
        embedded._ensure_database("dsn", Path("/bin"), "roleband")
        assert len(calls) == 1  # one existence probe, no CREATE


class TestStaleHolderPruning:
    """A SIGKILLed holder leaks its PID; upstream then never stops the server."""

    def test_dead_pids_are_dropped_and_live_ones_kept(self, tmp_path):
        pgdata = tmp_path / "db"
        pgdata.mkdir()
        handle_file = pgdata / ".handle_pids.json"
        dead_pid = 2**22  # above any real pid_max, so never live
        handle_file.write_text(json.dumps([dead_pid, os.getpid()]))

        removed = _prune_dead_holders(pgdata)

        assert removed == 1
        assert json.loads(handle_file.read_text()) == [os.getpid()]

    def test_absent_or_corrupt_file_is_not_an_error(self, tmp_path):
        pgdata = tmp_path / "db"
        pgdata.mkdir()
        assert _prune_dead_holders(pgdata) == 0
        (pgdata / ".handle_pids.json").write_text("{not json")
        assert _prune_dead_holders(pgdata) == 0


class TestPostgresFeatureContract:
    """Every dialect feature the schema and queries depend on, on a real server."""

    @pytest.fixture(autouse=True, scope="class")
    def schema(self, server):
        sql(
            server,
            """
            CREATE EXTENSION IF NOT EXISTS vector;
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            DROP TABLE IF EXISTS probe_jobs;
            CREATE TABLE probe_jobs (
              id bigserial PRIMARY KEY,
              external_id text UNIQUE NOT NULL,
              title text NOT NULL,
              company text NOT NULL,
              domains text[] NOT NULL DEFAULT '{}',
              evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
              embedding vector(768),
              search_vector tsvector
            );
            CREATE INDEX probe_title_trgm ON probe_jobs USING gin (title gin_trgm_ops);
            CREATE INDEX probe_hnsw ON probe_jobs USING hnsw (embedding vector_cosine_ops);
            INSERT INTO probe_jobs (external_id, title, company, domains, evidence, embedding)
            SELECT 'ext-'||g, 'Staff Product Manager '||g, 'Anthropic',
                   ARRAY['ai','infra'], '{"level":{"band":"staff"}}'::jsonb,
                   (SELECT ('['||string_agg('0.01', ',')||']')::vector
                    FROM generate_series(1,768))
            FROM generate_series(1,25) g;
            """,
        )

    def test_upsert_on_conflict_updates_in_place(self, server):
        title = sql(
            server,
            "INSERT INTO probe_jobs (external_id,title,company) VALUES ('ext-1','Renamed','A')"
            " ON CONFLICT (external_id) DO UPDATE SET title=EXCLUDED.title RETURNING title",
        )
        assert title.splitlines()[0] == "Renamed"
        assert sql(server, "SELECT count(*) FROM probe_jobs") == "25"  # updated, not inserted

    def test_jsonb_containment(self, server):
        hits = sql(
            server,
            "SELECT count(*) FROM probe_jobs WHERE evidence @> '{\"level\":{\"band\":\"staff\"}}'",
        )
        assert int(hits) == 25

    def test_array_overlap_and_cardinality(self, server):
        assert sql(server, "SELECT count(*) FROM probe_jobs WHERE domains && ARRAY['ai']") == "25"
        assert sql(server, "SELECT count(*) FROM probe_jobs WHERE cardinality(domains)=2") == "25"

    def test_tsvector_websearch_matches_a_quoted_phrase(self, server):
        assert (
            sql(
                server,
                "SELECT to_tsvector('english','staff product manager')"
                " @@ websearch_to_tsquery('english','\"product manager\"')",
            )
            == "t"
        )

    def test_trigram_similarity_is_typo_tolerant(self, server):
        assert float(sql(server, "SELECT similarity('Anthropc','Anthropic')")) > 0.4
        # and a genuinely different string must not match
        assert float(sql(server, "SELECT similarity('Anthropic','Nvidia')")) < 0.2

    def test_trigram_index_is_used_for_fuzzy_lookup(self, server):
        plan = sql(
            server,
            "SET enable_seqscan=off;"
            " EXPLAIN (COSTS OFF) SELECT id FROM probe_jobs WHERE title % 'Staff Prodct Manager'",
        )
        assert "probe_title_trgm" in plan

    def test_hnsw_cosine_search_returns_neighbours_at_768_dims(self, server):
        assert sql(server, "SELECT vector_dims(embedding) FROM probe_jobs LIMIT 1") == "768"
        rows = sql(
            server,
            "SET enable_seqscan=off;"
            " SELECT count(*) FROM (SELECT id FROM probe_jobs"
            "  ORDER BY embedding <=> (SELECT embedding FROM probe_jobs LIMIT 1) LIMIT 5) s",
        )
        assert rows.splitlines()[-1] == "5"

    def test_watchdog_probe_passes_where_extension_libraries_load(self, server):
        # The degraded-server probe must be valid SQL and pass on a healthy
        # server (vector + pg_trgm installed here). The negative case is real:
        # a postmaster running from a deleted venv answers SELECT 1 while
        # $libdir/vector is unloadable for new backends.
        from tracker.workflows.watchdog import _DB_PROBE_SQL

        assert sql(server, _DB_PROBE_SQL) == "DO"

    def test_advisory_lock_excludes_a_second_connection(self, server):
        """The run-overlap guard: a second holder must be refused, not queued."""
        import psycopg2

        key = 91237
        holder = psycopg2.connect(server.dsn())
        contender = psycopg2.connect(server.dsn())
        try:
            with holder.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(%s)", (key,))
            with contender.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
                assert cur.fetchone()[0] is False  # refused while held

            with holder.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
            with contender.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
                assert cur.fetchone()[0] is True  # granted once released
        finally:
            holder.close()
            contender.close()


class TestRepoSchemaOnEmbedded:
    """The real schema, not a probe table: migrations must apply end to end."""

    def test_full_migration_chain_applies_and_is_current(self, tmp_path):
        """Runs Alembic through the interpreter running the suite, never a path.

        CI installs into setup-python's interpreter and creates no `.venv`, and
        a worktree has none either, so a test that looks for
        `backend/.venv/bin/alembic` and SKIPs when it is absent would prove the
        migration chain applies nowhere but the main checkout, green and silent
        about it.
        `sys.executable -m alembic` is present wherever the suite can import
        `tracker`, so there is no environment left in which skipping is honest.
        """
        pgdata = tmp_path / "migrated"
        env = {
            **os.environ,
            "ROLEBAND_PGDATA": str(pgdata),
            "ROLEBAND_DATABASE_URL": "",
        }
        backend = Path(__file__).resolve().parents[1]
        alembic = [sys.executable, "-m", "alembic"]

        try:
            up = subprocess.run(
                [*alembic, "upgrade", "head"], cwd=backend, env=env, capture_output=True, text=True
            )
            assert up.returncode == 0, (up.stderr or "")[-2000:]

            check = subprocess.run(
                [*alembic, "check"], cwd=backend, env=env, capture_output=True, text=True
            )
            output = check.stdout + check.stderr
            # Both, because each alone can lie: `check` exits non-zero on drift,
            # and a crash before comparing prints no verdict at all.
            assert check.returncode == 0, output[-2000:]
            assert "No new upgrade operations detected" in output, output[-2000:]
        finally:
            destroy(pgdata)

    def test_the_app_starts_its_cluster_with_a_preset_and_inventory_page_room(self, tmp_path):
        """The app's own start (`Settings.ensure_embedded_server`, reached by
        Alembic here) passes the preset, and the migration leaves free space on
        `posting_inventory`'s pages; its downgrade takes the space back."""
        pgdata = tmp_path / "migrated"
        env = {
            **os.environ,
            "ROLEBAND_PGDATA": str(pgdata),
            "ROLEBAND_DATABASE_URL": "",
            "ROLEBAND_DB_PRESET": "standard",
        }
        backend = Path(__file__).resolve().parents[1]
        alembic = [sys.executable, "-m", "alembic"]
        room = "SELECT coalesce(array_to_string(reloptions, ','), '') FROM pg_class WHERE relname = 'posting_inventory'"

        def migrate(*target: str) -> None:
            run = subprocess.run([*alembic, *target], cwd=backend, env=env, capture_output=True, text=True)
            assert run.returncode == 0, (run.stderr or "")[-2000:]

        try:
            migrate("upgrade", "head")
            server = ensure_server(pgdata, database="roleband", locale=cluster_locale())
            assert sql(server, "SHOW roleband.preset") == "standard"
            assert sql(server, "SHOW shared_buffers") == STANDARD.settings["shared_buffers"]
            assert sql(server, room) == "fillfactor=85"

            migrate("downgrade", "544950844911-1")
            assert sql(server, room) == ""
        finally:
            destroy(pgdata)


class TestServerSettings:
    """A start passes its settings on the server's command line; nothing is
    written into the cluster, and attaching to a running server changes none."""

    def test_a_start_runs_with_its_settings_and_says_so(self, tmp_path, caplog):
        pgdata = tmp_path / "sized"
        caplog.set_level(logging.INFO, logger="tracker.platform.embedded_db")
        try:
            srv = ensure_server(
                pgdata, database="probe", locale=cluster_locale(),
                server_settings=STANDARD.server_settings(24 * 2**30),
            )
            for name, value in STANDARD.settings.items():
                assert sql(srv, f"SHOW {name}") == value, name
            assert sql(srv, "SHOW roleband.preset") == "standard"
            assert sql(srv, "SHOW roleband.memory_bytes") == str(24 * 2**30)
            assert "shared_buffers=512MB" in caplog.text
        finally:
            destroy(pgdata)

    def test_attaching_to_a_running_server_keeps_its_settings(self, tmp_path):
        pgdata = tmp_path / "attached"
        try:
            ensure_server(pgdata, database="probe", locale=cluster_locale(),
                          server_settings=STANDARD.server_settings(None))
            again = ensure_server(pgdata, database="probe", server_settings=LARGE.server_settings(None))
            assert sql(again, "SHOW shared_buffers") == "512MB"
            assert sql(again, "SHOW roleband.preset") == "standard"
        finally:
            destroy(pgdata)

    def test_a_start_without_settings_is_back_on_the_stock_values(self, tmp_path):
        """The settings live on the command line only: the next start without
        them runs Postgres's own defaults and names no preset."""
        pgdata = tmp_path / "restarted"
        try:
            ensure_server(pgdata, database="probe", locale=cluster_locale(),
                          server_settings=LARGE.server_settings(None))
            assert stop_server(pgdata)
            plain = ensure_server(pgdata, database="probe")
            assert sql(plain, "SHOW shared_buffers") == "128MB"
            assert sql(plain, "SELECT current_setting('roleband.preset', true) IS NULL") == "t"
        finally:
            destroy(pgdata)


class TestUnavailableLocale:
    """A pinned locale this host does not have is refused by name, before initdb.

    The cluster's collation is pinned to en_US.UTF-8 so text sorts the same on
    every host. Minimal Linux images ship only C, C.UTF-8 and POSIX, and initdb
    answers the pin with "invalid locale settings; check LANG and LC_*
    environment variables": true, and pointing away from the pin that set them.
    Unhandled, `./setup.sh` dies at `alembic upgrade head` with that line inside
    a traceback.
    """

    def test_a_missing_locale_is_refused_by_name_with_both_ways_out(self, tmp_path):
        pgdata = tmp_path / "db"
        with pytest.raises(EmbeddedDbError) as caught:
            ensure_server(pgdata, database="probe", locale="xx_NOPE.UTF-8")
        message = str(caught.value)
        assert "xx_NOPE.UTF-8" in message
        assert "ROLEBAND_DB_LOCALE" in message, "names the setting that chooses another"
        assert "locale-gen" in message, "names how to install the pinned one"
        assert not (pgdata / "PG_VERSION").exists(), "refused before initdb, not after it"

    def test_the_probe_answers_yes_for_a_locale_every_host_has(self):
        """The control: a probe that answered no everywhere passes the test above."""
        from tracker.platform.embedded_db import locale_available  # noqa: PLC0415

        assert locale_available("C")
        assert not locale_available("xx_NOPE.UTF-8")



def test_test_clusters_take_the_locale_the_settings_resolve(monkeypatch):
    """A host without en_US.UTF-8 sets ROLEBAND_DB_LOCALE=C.UTF-8; the app's
    cluster honours it, so the tests' throwaway clusters must too."""
    from tracker.config import get_settings
    from tracker.platform.embedded_db import DEFAULT_LOCALE

    monkeypatch.delenv("ROLEBAND_DB_LOCALE", raising=False)
    get_settings.cache_clear()
    try:
        assert cluster_locale() == DEFAULT_LOCALE
        monkeypatch.setenv("ROLEBAND_DB_LOCALE", "C.UTF-8")
        get_settings.cache_clear()
        assert cluster_locale() == "C.UTF-8"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
