"""Settings read only environment names that start with `ROLEBAND_`.

A shell that already exports `POSTGRES_DB` for a Docker project, `API_HOST` for
another server, or `ANTHROPIC_API_KEY` for a command-line tool must not
reconfigure RoleBand: an ambient `POSTGRES_DB` once made setup migrate one
database while the background service opened another, empty one. The file the
settings read is `backend/.env`, wherever the process starts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tracker.config import Settings
from tracker.usage_stats import kill

BACKEND = Path(__file__).resolve().parents[1]
AMBIENT = {
    "POSTGRES_DB": "someone_elses_db",
    "API_HOST": "0.0.0.0",
    "ANTHROPIC_API_KEY": "sk-ambient-not-ours",
    "SEARCH_LLM_ENABLED": "true",
    "SCRAPER_MIN_DELAY_SECONDS": "0",
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in [*AMBIENT, *(f"ROLEBAND_{name}" for name in AMBIENT), "ROLEBAND_PGDATA", "DB_PGDATA"]:
        monkeypatch.delenv(name, raising=False)


def test_a_name_another_tool_uses_never_configures_the_app(monkeypatch):
    for name, value in AMBIENT.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.postgres_db == "roleband"
    assert settings.api_host == "127.0.0.1"
    assert settings.anthropic_api_key is None
    assert settings.search_llm_enabled is False
    assert settings.scraper_min_delay_seconds == 2.0


def test_the_prefixed_name_configures_it(monkeypatch):
    for name, value in AMBIENT.items():
        monkeypatch.setenv(f"ROLEBAND_{name}", value)
    settings = Settings(_env_file=None)
    assert settings.postgres_db == "someone_elses_db"
    assert settings.api_host == "0.0.0.0"
    assert settings.anthropic_api_key == "sk-ambient-not-ours"
    assert settings.search_llm_enabled is True
    assert settings.scraper_min_delay_seconds == 0.0


def test_a_field_with_its_own_name_reads_that_name_and_never_the_bare_one(monkeypatch):
    monkeypatch.setenv("DB_PGDATA", "/not/this/one")
    assert Settings(_env_file=None).db_pgdata is None
    monkeypatch.setenv("ROLEBAND_PGDATA", "/this/one")
    assert Settings(_env_file=None).db_pgdata == "/this/one"


def test_the_env_file_is_the_backend_s_wherever_the_process_starts(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ROLEBAND_POSTGRES_DB=from_the_current_directory\n")
    monkeypatch.chdir(tmp_path)
    assert Settings().postgres_db != "from_the_current_directory"
    assert Path(Settings.model_config["env_file"]) == BACKEND / ".env" == kill.ENV_FILE
