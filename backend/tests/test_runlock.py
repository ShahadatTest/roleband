"""Run-lock contract: only one holder at a time; re-acquirable after release."""

from __future__ import annotations

import pytest

from tracker.platform.locks import AlreadyRunning, run_lock


def test_second_holder_is_refused(tmp_path):
    lock = tmp_path / "daily.lock"
    with run_lock(lock):
        with pytest.raises(AlreadyRunning):
            with run_lock(lock):
                pass  # pragma: no cover - should not be reached


def test_lock_is_reacquirable_after_release(tmp_path):
    lock = tmp_path / "daily.lock"
    with run_lock(lock):
        pass
    # Released on context exit; a fresh acquire must succeed.
    with run_lock(lock):
        pass


def test_lock_dir_is_created(tmp_path):
    lock = tmp_path / "nested" / "dir" / "daily.lock"
    with run_lock(lock):
        assert lock.exists()
