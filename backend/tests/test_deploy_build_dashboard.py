"""`deploy/build_dashboard.sh` changes the served dashboard only with a whole
build: a failed build, or one that wrote no page, leaves it as it was.

Each test copies the script into a throwaway git repository whose
`npm run build:serve` is a stub writing into the directory the script names, so
no real build runs. Its `npm run build`, the contributors' build with the
bundle-size gate, fails: the serving build never runs it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "build_dashboard.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
    ).stdout.strip()


def _repo(tmp_path: Path, build: str) -> Path:
    root = tmp_path / "checkout"
    (root / "deploy").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "deploy" / "build_dashboard.sh")
    dashboard = root / "dashboard"
    dashboard.mkdir()
    (dashboard / "package.json").write_text(
        '{"scripts": {"build": "echo the bundle gate ran >&2; exit 1", "build:serve": "sh build.sh"}}\n'
    )
    (dashboard / "build.sh").write_text(build)
    (root / ".gitignore").write_text("dashboard/dist/\ndashboard/dist.next/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    served = dashboard / "dist"
    served.mkdir()
    (served / "index.html").write_text("old")
    return root


def _build(root: Path) -> subprocess.CompletedProcess:
    if shutil.which("npm") is None:
        pytest.skip("npm is not installed")
    return subprocess.run(
        ["bash", str(root / "deploy" / "build_dashboard.sh")], capture_output=True, text=True, timeout=120,
    )


WRITES = 'mkdir -p "$ROLEBAND_DIST_OUT/assets" && echo new > "$ROLEBAND_DIST_OUT/index.html"\n'


def test_a_whole_build_is_swapped_in_and_names_its_tree(tmp_path):
    root = _repo(tmp_path, WRITES)
    done = _build(root)
    assert done.returncode == 0, done.stdout + done.stderr
    dashboard = root / "dashboard"
    assert (dashboard / "dist" / "index.html").read_text().strip() == "new"
    assert (dashboard / "dist" / ".roleband-tree").read_text().strip() == _git(root, "rev-parse", "HEAD:dashboard")
    assert not (dashboard / "dist.next").exists()
    assert not (dashboard / "dist.previous").exists()
    assert not (dashboard / "dist" / ".roleband-dirty").exists()


def test_a_build_from_uncommitted_dashboard_source_says_so_and_still_names_heads_tree(tmp_path):
    root = _repo(tmp_path, WRITES)
    (root / "dashboard" / "package.json").write_text(
        '{"scripts": {"build": "exit 1", "build:serve": "sh build.sh"}, "version": "edited"}\n'
    )
    done = _build(root)
    assert done.returncode == 0, done.stdout + done.stderr
    served = root / "dashboard" / "dist"
    assert (served / ".roleband-dirty").exists()
    # The supervisor compares this tree with HEAD's; a dirty build must not look stale to it.
    assert (served / ".roleband-tree").read_text().strip() == _git(root, "rev-parse", "HEAD:dashboard")


@pytest.mark.parametrize(
    "build",
    [
        'mkdir -p "$ROLEBAND_DIST_OUT" && echo half > "$ROLEBAND_DIST_OUT/index.html" && exit 2\n',
        'mkdir -p "$ROLEBAND_DIST_OUT/assets"\n',
    ],
    ids=["build fails", "build writes no page"],
)
def test_a_build_that_is_not_whole_leaves_the_served_dashboard_alone(tmp_path, build):
    root = _repo(tmp_path, build)
    done = _build(root)
    assert done.returncode == 1
    dashboard = root / "dashboard"
    assert (dashboard / "dist" / "index.html").read_text() == "old"
    assert not (dashboard / "dist.next").exists()
    assert "served dashboard is unchanged" in done.stderr


def test_the_build_never_writes_into_the_served_directory(tmp_path):
    """The stub fails if it is pointed at the served dist."""
    root = _repo(tmp_path, '[ "$ROLEBAND_DIST_OUT" = "dist.next" ] || exit 9\n' + WRITES)
    assert _build(root).returncode == 0


def test_the_serving_build_type_checks_and_builds_without_the_bundle_gate():
    scripts = json.loads((SCRIPT.parents[1] / "dashboard" / "package.json").read_text())["scripts"]
    assert scripts["build:serve"] == "tsc -b && vite build"
    assert scripts["prebuild:serve"] == scripts["prebuild"], "the copy is generated for both builds alike"
    assert "check-bundle-size" in scripts["build"]
