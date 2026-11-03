"""The shell-facing connection resolver.

Only the pure surface: argument validation and URL rewriting. Nothing here may
start a server — the embedded branch is exercised by the lifecycle tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import db_uri


class TestWithDatabase:
    def test_socket_dsn_keeps_the_host_query(self):
        rewritten = db_uri._with_database(
            "postgresql://postgres:@/roleband?host=/tmp/sock", "roleband_drill"
        )
        assert rewritten == "postgresql://postgres:@/roleband_drill?host=/tmp/sock"

    def test_tcp_dsn_replaces_only_the_path(self):
        rewritten = db_uri._with_database("postgresql://u:p@h:5433/roleband", "scratch")
        assert rewritten == "postgresql://u:p@h:5433/scratch"


class TestArgumentContract:
    def test_database_flag_is_refused_outside_dsn(self, capsys):
        # Never silently ignored: a drill typing `bin-dir --database x` must
        # hear about it.
        with pytest.raises(SystemExit) as exc:
            db_uri.main(["db_uri", "bin-dir", "--database", "x"])
        assert exc.value.code == 2
        assert "--database applies only to dsn" in capsys.readouterr().err

    def test_unknown_subcommand_is_refused(self):
        with pytest.raises(SystemExit) as exc:
            db_uri.main(["db_uri", "everything"])
        assert exc.value.code == 2

    def test_missing_subcommand_is_refused(self):
        with pytest.raises(SystemExit) as exc:
            db_uri.main(["db_uri"])
        assert exc.value.code == 2


class TestExternalResolution:
    """With an override set, resolution is pure string work — no server."""

    def _settings(self):
        return SimpleNamespace(
            database_url_override="postgresql+asyncpg://u:p@ext:5432/other",
            db_embedded=True,
            sync_database_url="postgresql+psycopg2://u:p@ext:5432/other",
        )

    def test_dsn_strips_the_driver_suffix(self, monkeypatch, capsys):
        monkeypatch.setattr(db_uri, "get_settings", self._settings)
        assert db_uri.main(["db_uri", "dsn"]) == 0
        assert capsys.readouterr().out.strip() == "postgresql://u:p@ext:5432/other"

    def test_dsn_database_flag_rewrites_the_path(self, monkeypatch, capsys):
        monkeypatch.setattr(db_uri, "get_settings", self._settings)
        assert db_uri.main(["db_uri", "dsn", "--database", "drill"]) == 0
        assert capsys.readouterr().out.strip() == "postgresql://u:p@ext:5432/drill"

    def test_database_names_the_database_in_the_apps_dsn(self, monkeypatch, capsys):
        # `restore_db.sh` asks this whether a target is live; the
        # name comes from the URL the app connects with, not `postgres_db`.
        settings = SimpleNamespace(**vars(self._settings()), postgres_db="roleband")
        monkeypatch.setattr(db_uri, "get_settings", lambda: settings)
        assert db_uri.main(["db_uri", "database"]) == 0
        assert capsys.readouterr().out.strip() == "other"

    def test_database_takes_no_database_flag(self, monkeypatch):
        monkeypatch.setattr(db_uri, "get_settings", self._settings)
        with pytest.raises(SystemExit) as exc:
            db_uri.main(["db_uri", "database", "--database", "x"])
        assert exc.value.code == 2
