"""The embedded database's memory presets: which one a computer gets, what the
server is told, and the one setting that names a preset instead.

Pure, no server: `test_embedded_db.py` starts real clusters with a preset.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import tracker.config as config
from tracker.config import Settings
from tracker.platform import memory
from tracker.platform.database_presets import LARGE, PRESETS, SMALL, STANDARD, preset_for
from tracker.semantic import provision
from tracker.semantic.manifest import TIER_INT8

GiB = 2**30


@pytest.fixture(autouse=True)
def _no_ambient_preset(monkeypatch):
    """`db_preset` reads `ROLEBAND_DB_PRESET`, which beats a constructor argument."""
    monkeypatch.delenv("ROLEBAND_DB_PRESET", raising=False)


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    ("gib", "expected"),
    [(8, SMALL), (16, STANDARD), (18, STANDARD), (24, STANDARD), (32, LARGE), (36, LARGE), (48, LARGE), (64, LARGE)],
)
def test_a_computer_of_each_memory_size_takes_its_preset(gib, expected):
    assert preset_for(gib * GiB) is expected


@pytest.mark.parametrize(
    ("memory_bytes", "expected"),
    [(16 * GiB - 1, SMALL), (16 * GiB, STANDARD), (32 * GiB - 1, STANDARD), (32 * GiB, LARGE)],
)
def test_each_line_falls_on_the_byte(memory_bytes, expected):
    assert preset_for(memory_bytes) is expected


def test_unknown_memory_is_a_small_computer():
    assert preset_for(None) is SMALL


def test_the_presets_hold_their_sizes():
    sized = ("shared_buffers", "work_mem", "maintenance_work_mem", "effective_cache_size")
    assert {name: {key: preset.settings[key] for key in sized} for name, preset in PRESETS.items()} == {
        "small": {"shared_buffers": "256MB", "work_mem": "8MB", "maintenance_work_mem": "128MB",
                  "effective_cache_size": "4GB"},
        "standard": {"shared_buffers": "512MB", "work_mem": "16MB", "maintenance_work_mem": "256MB",
                     "effective_cache_size": "8GB"},
        "large": {"shared_buffers": "1GB", "work_mem": "32MB", "maintenance_work_mem": "512MB",
                  "effective_cache_size": "16GB"},
    }


def test_every_preset_prices_a_disk_read_for_an_ssd():
    assert {preset.settings["random_page_cost"] for preset in PRESETS.values()} == {"1.1"}


def test_the_server_is_told_its_preset_and_the_memory_that_picked_it():
    told = STANDARD.server_settings(24 * GiB)
    assert told["roleband.preset"] == "standard"
    assert told["roleband.memory_bytes"] == str(24 * GiB)
    assert {key: told[key] for key in STANDARD.settings} == dict(STANDARD.settings)
    assert SMALL.server_settings(None)["roleband.memory_bytes"] == "unknown"


def test_a_preset_cannot_be_changed_in_place():
    with pytest.raises(TypeError):
        LARGE.settings["shared_buffers"] = "8GB"  # type: ignore[index]


@pytest.mark.parametrize("memory_bytes", [8 * GiB, 16 * GiB - 1, 16 * GiB, 48 * GiB, None])
def test_the_embedding_model_and_the_database_agree_on_a_small_computer(memory_bytes):
    """One line decides both: a computer never gets the small model with a
    bigger database preset, or the reverse."""
    small_model = provision.tier_for_ram(memory_bytes) == TIER_INT8
    assert small_model == (preset_for(memory_bytes) is SMALL)


def test_the_model_reads_memory_through_the_one_reader():
    assert provision.detect_total_ram_bytes is memory.total_memory_bytes
    measured = memory.total_memory_bytes()
    assert measured is not None and measured > 0


def test_without_a_named_preset_the_memory_picks():
    assert _settings().database_preset(8 * GiB) is SMALL
    assert _settings().database_preset(48 * GiB) is LARGE
    assert _settings().database_preset(None) is SMALL


def test_a_named_preset_wins_whatever_the_memory(monkeypatch):
    monkeypatch.setenv("ROLEBAND_DB_PRESET", "small")
    assert _settings().database_preset(48 * GiB) is SMALL
    monkeypatch.setenv("ROLEBAND_DB_PRESET", "large")
    assert _settings().database_preset(None) is LARGE


def test_an_unknown_preset_name_is_refused_by_name(monkeypatch):
    monkeypatch.setenv("ROLEBAND_DB_PRESET", "huge")
    with pytest.raises(ValidationError) as caught:
        _settings()
    message = str(caught.value)
    assert "ROLEBAND_DB_PRESET" in message
    assert "'small', 'standard' or 'large'" in message


@pytest.mark.parametrize(("gib", "expected"), [(8, SMALL), (24, STANDARD), (48, LARGE)])
def test_the_embedded_start_carries_the_preset_its_memory_picks(monkeypatch, gib, expected):
    import tracker.platform.embedded_db as embedded

    started: dict = {}
    monkeypatch.setattr(config, "total_memory_bytes", lambda: gib * GiB)
    monkeypatch.setattr(embedded, "ensure_server", lambda pgdata, **kwargs: started.update(kwargs) or "server")
    assert _settings(db_pgdata="/nonexistent/db").ensure_embedded_server() == "server"
    assert started["server_settings"] == expected.server_settings(gib * GiB)
