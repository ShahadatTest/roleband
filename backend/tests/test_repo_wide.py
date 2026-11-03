"""A test that reads past backend/ is marked to run on every pull request."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import repo_wide


@pytest.fixture
def module(tmp_path):
    def write(source: str) -> Path:
        path = tmp_path / f"test_demo_{len(list(tmp_path.iterdir()))}.py"
        path.write_text(source)
        return path

    return write


@pytest.mark.parametrize(
    "source",
    [
        'ROOT = Path(__file__).resolve().parents[2]\n',
        'ROOT = Path(__file__).resolve().parent.parent.parent\n',
        'from tracker.platform.paths import REPO_ROOT\n',
        'FIXTURE = HERE / "../launcher/contracts/status-cases.json"\n',
        'from tests.plugin_web import serve\n',
        'ROOT = HERE / ".." / ".."\n',
        'ROOT = os.path.join(HERE, os.pardir, os.pardir)\n',
        'LOCK = BACKEND.parent / "launcher" / "macos" / "runtime-lock.txt"\n',
        'REPO = TRACKER.parent.parent\n',
        'ROOT = Path(__file__).resolve().parents[1].parent\n',
    ],
)
def test_a_module_naming_a_path_above_backend_is_repo_wide(module, source):
    assert repo_wide.reaches_past_backend(module(source))


@pytest.mark.parametrize(
    "source",
    [
        'FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"\n',
        'URL = "https://jobs.example.test/../acme"\n',
        'from tests.skip_policy import ALLOWED\n',
        'FIXTURE = Path(__file__).parent / "fixtures" / "a.json"\n',
    ],
)
def test_a_module_reading_inside_backend_is_not(module, source):
    """The control: the marker is not on every module, so the split saves something."""
    assert not repo_wide.reaches_past_backend(module(source))


def test_helpers_that_import_each_other_are_read_once(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_wide, "TESTS", tmp_path)
    (tmp_path / "a.py").write_text("from tests.b import x\n")
    (tmp_path / "b.py").write_text("from tests.a import y\n")
    assert not repo_wide.reaches_past_backend(tmp_path / "a.py")
    (tmp_path / "c.py").write_text("from tests.d import x\n")
    (tmp_path / "d.py").write_text('from tests.c import y\nROOT = HERE / ".."\n')
    assert repo_wide.reaches_past_backend(tmp_path / "c.py")


@pytest.mark.parametrize(
    "name",
    [
        "test_gitleaks_config.py",
        "test_release_gate.py",
        "test_docs_closed_set.py",
        "test_ci_workflow_triggers.py",
        "test_check_dependency_audit.py",
        "test_no_compat_shims.py",
    ],
)
def test_the_whole_tree_scans_are_repo_wide(name):
    assert repo_wide.reaches_past_backend(repo_wide.TESTS / name)


def test_collection_marks_the_repo_wide_tests(request):
    # This module names paths above backend/ in its examples, so it is repo-wide itself.
    assert request.node.get_closest_marker("repo_wide") is not None
