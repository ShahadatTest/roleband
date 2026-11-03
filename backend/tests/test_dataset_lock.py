"""The app's copy of the datasets is exactly what its lock names.

`tracker/datasets.lock.json` names a data commit and every file's sha256 and
size. Until the copy is pinned the data is edited in the app tree and
`scripts.data lock` re-records it; once pinned, data changes arrive only by
`scripts.data pin`. Either way the copy on disk and the lock agree, and a
trial pin never reaches a commit.

The pin itself is proven end to end on a scratch data repository with a pushed
commit, and each refusal on the case that should trip it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import data
from scripts.data import (
    DATASETS,
    REPO_FILES,
    DataError,
    export,
    lock_problems,
    lock_text,
    output_dir,
    pin,
    read_lock,
)


def test_the_app_s_copy_is_what_its_lock_names():
    problems = lock_problems(read_lock())
    assert problems == [], (
        "the datasets differ from tracker/datasets.lock.json: run `scripts.data lock` "
        "while the copy is edited in the app tree, or pin a data commit\n" + "\n".join(problems))


@pytest.fixture
def backend(tmp_path) -> Path:
    """A scratch `backend/` holding a copy of today's datasets and its lock."""
    root = tmp_path / "backend"
    for path in DATASETS.values():
        shutil.copytree(data.BACKEND / path, root / path)
    (root / "lock.json").write_text(lock_text(None, False, root), encoding="utf-8")
    return root


def _lock(backend: Path) -> dict:
    return read_lock(backend / "lock.json")


def test_an_edited_an_added_and_a_removed_file_are_each_named(backend):
    atlas = backend / DATASETS["atlas"]
    (atlas / "printed.csv").write_text((atlas / "printed.csv").read_text(encoding="utf-8") + "x,y,senior\n",
                                       encoding="utf-8")
    (atlas / "scratch.csv").write_text("a\n", encoding="utf-8")
    (backend / DATASETS["benefits"] / "taxonomy.json").unlink()
    assert lock_problems(_lock(backend), backend) == [
        "tracker/levels/atlas/scratch.csv: not in the lock",
        "tracker/levels/atlas/printed.csv: differs from the lock",
        "tracker/profiles/benefits_dataset/taxonomy.json: missing",
    ]


def test_a_desktop_s_dotfile_is_not_a_dataset_file(backend):
    (backend / DATASETS["atlas"] / ".DS_Store").write_bytes(b"\0")
    assert lock_problems(_lock(backend), backend) == []


def test_a_trial_lock_never_passes(backend):
    lock = _lock(backend)
    lock["trial"] = True
    (problem,) = lock_problems(lock, backend)
    assert "trial" in problem


# --------------------------------------------------------------------------- #
# Pinning from a data checkout
# --------------------------------------------------------------------------- #


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path) -> Path:
    """A data repository's clone holding today's data, its commit pushed."""
    remote, clone = tmp_path / "remote.git", tmp_path / "roleband-data"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", "-q", str(remote), str(clone))
    for name, path in DATASETS.items():
        shutil.copytree(data.BACKEND / path, clone / name)
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "data")
    _git(clone, "push", "-q", "origin", "main")
    return clone


def _change_a_rung_note(checkout: Path) -> None:
    rungs = checkout / "atlas" / "rungs.csv"
    text = rungs.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("google,company,L5,") and line.endswith(","))
    rungs.write_text(text.replace(line, line + "edited in the data repository", 1), encoding="utf-8")


def test_a_pin_copies_a_pushed_commit_and_locks_it(backend, checkout):
    (backend / DATASETS["atlas"] / "stale.csv").write_text("left from an older copy\n", encoding="utf-8")
    _change_a_rung_note(checkout)
    _git(checkout, "commit", "-q", "-am", "note")
    _git(checkout, "push", "-q", "origin", "main")

    assert pin(checkout, backend=backend, lock_path=backend / "lock.json") == []

    lock = _lock(backend)
    assert lock["commit"] == _git(checkout, "rev-parse", "HEAD") and lock["trial"] is False
    assert lock_problems(lock, backend) == []
    assert not (backend / DATASETS["atlas"] / "stale.csv").exists()
    assert "edited in the data repository" in (backend / DATASETS["atlas"] / "rungs.csv").read_text(encoding="utf-8")


def test_a_pin_refuses_uncommitted_and_unpushed_data(backend, checkout):
    before = (backend / "lock.json").read_text(encoding="utf-8")
    _change_a_rung_note(checkout)
    with pytest.raises(DataError, match="uncommitted"):
        pin(checkout, backend=backend, lock_path=backend / "lock.json")
    _git(checkout, "commit", "-q", "-am", "note")
    with pytest.raises(DataError, match="on no remote branch"):
        pin(checkout, backend=backend, lock_path=backend / "lock.json")
    assert (backend / "lock.json").read_text(encoding="utf-8") == before


def test_a_pin_refuses_data_the_check_finds_broken_and_a_trial_copies_it(backend, checkout):
    observations = checkout / "benefits" / "observations.jsonl"
    lines = observations.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps({**json.loads(lines[0]), "benefit_type": "moon_base"})
    observations.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(checkout, "commit", "-q", "-am", "broken")
    _git(checkout, "push", "-q", "origin", "main")
    with pytest.raises(DataError, match="1 problem"):
        pin(checkout, backend=backend, lock_path=backend / "lock.json")

    found = pin(checkout, trial=True, backend=backend, lock_path=backend / "lock.json")
    assert found == ["benefits/observations.jsonl:1: benefit_type 'moon_base' is not in taxonomy.json"]
    lock = _lock(backend)
    assert lock["trial"] is True
    assert [p for p in lock_problems(lock, backend) if "trial" in p]


# --------------------------------------------------------------------------- #
# Where a build writes
# --------------------------------------------------------------------------- #


def test_a_build_writes_the_app_s_copy_until_it_is_pinned_then_a_data_checkout(tmp_path):
    unpinned = {"commit": None, "trial": False}
    pinned = {"commit": "0" * 40, "trial": False}
    app_atlas = (data.BACKEND / DATASETS["atlas"]).resolve()
    assert output_dir("atlas", None, unpinned) == app_atlas

    (tmp_path / "atlas").mkdir()
    assert output_dir("atlas", tmp_path, pinned) == (tmp_path / "atlas").resolve()
    with pytest.raises(DataError, match="no benefits/ folder"):
        output_dir("benefits", tmp_path, pinned)
    with pytest.raises(DataError, match="pinned"):
        output_dir("atlas", app_atlas.parent, pinned)


# --------------------------------------------------------------------------- #
# Exporting the data repository's first commit
# --------------------------------------------------------------------------- #


def test_an_export_pinned_back_is_the_same_data(tmp_path, backend):
    """The cut exports the data repository from the app's copy, then pins the
    app to that commit: the round trip must give back every byte."""
    repo, remote = tmp_path / "export", tmp_path / "export.git"
    written = export(repo, backend=backend, lock_path=backend / "lock.json")
    assert set(REPO_FILES.values()) <= set(written)
    assert {w.split("/")[0] for w in written} >= set(DATASETS)

    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Initial public release")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin")

    assert pin(repo, backend=backend, lock_path=backend / "lock.json") == []
    lock, app = _lock(backend), read_lock()
    assert lock["commit"] == _git(repo, "rev-parse", "HEAD")
    assert {name: entry["files"] for name, entry in lock["datasets"].items()} == \
        {name: entry["files"] for name, entry in app["datasets"].items()}


def test_an_export_refuses_a_used_folder_and_a_pinned_copy(tmp_path, backend):
    used = tmp_path / "used"
    used.mkdir()
    (used / "notes.txt").write_text("mine\n", encoding="utf-8")
    with pytest.raises(DataError, match="not empty"):
        export(used, backend=backend, lock_path=backend / "lock.json")
    assert (used / "notes.txt").read_text(encoding="utf-8") == "mine\n"

    lock = _lock(backend)
    lock["commit"] = "0" * 40
    (backend / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(DataError, match="pinned"):
        export(tmp_path / "fresh", backend=backend, lock_path=backend / "lock.json")
    assert not (tmp_path / "fresh").exists()

