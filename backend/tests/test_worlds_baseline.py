"""A fresh baseline starts with no world preferences.

Preferences already on record surviving an upgrade is the rehearsal's job
(`tests/test_upgrade_rehearsal.py`).
"""

from tracker.platform.embedded_db import run_psql


def test_a_fresh_baseline_does_not_seed_world_preferences(baseline_database):
    _, dsn, bin_dir = baseline_database
    assert run_psql(dsn, bin_dir, "select count(*) from app_settings") == "0"
