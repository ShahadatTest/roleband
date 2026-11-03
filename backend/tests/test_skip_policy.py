"""The CI skip policy: required skips fail, named optional skips stay skips.

Most of this runs a real, separate pytest over a throwaway test file, because a
hook that is not registered, or that edits the wrong report, passes every
in-process assertion about its helpers.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import skip_policy

BACKEND = Path(__file__).resolve().parents[1]

_SAMPLE = '''
import pytest

def test_passes():
    assert True

def test_database_missing():
    pytest.skip("database unavailable (ConnectionRefusedError: nothing listening)")

def test_model_missing():
    pytest.skip("embedding model not available offline")
'''

_COLLECTION_SKIP = '''
import pytest

pytest.importorskip("a_module_that_is_not_installed_anywhere", reason="embedded Postgres wheel not installed")

def test_never_collected():
    assert True
'''


def _run(tmp_path: Path, files: dict[str, str], *, enforced: bool) -> subprocess.CompletedProcess:
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    # An empty ini of its own: the repo's workers and conftest stay out of it.
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    env.pop(skip_policy.ENV_FLAG, None)
    if enforced:
        env[skip_policy.ENV_FLAG] = "1"
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "tests.skip_policy", "-c", str(tmp_path / "pytest.ini"),
            "--rootdir", str(tmp_path), *files,
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )


class TestEndToEnd:
    def test_a_database_skip_fails_when_integration_is_required(self, tmp_path):
        proc = _run(tmp_path, {"test_sample.py": _SAMPLE}, enforced=True)
        out = proc.stdout + proc.stderr
        assert proc.returncode == 1, out
        assert "1 failed, 1 passed, 1 skipped" in out, out
        assert "database unavailable" in out, "the failure names the refused reason"

    def test_the_same_file_is_green_when_integration_is_not_required(self, tmp_path):
        """The control: without it, the test above could pass on a runner that
        failed every file for some unrelated reason."""
        proc = _run(tmp_path, {"test_sample.py": _SAMPLE}, enforced=False)
        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, out
        assert "1 passed, 2 skipped" in out, out

    def test_a_skip_at_collection_is_refused_too(self, tmp_path):
        """`importorskip` at module level makes no runtest report at all."""
        proc = _run(tmp_path, {"test_collection.py": _COLLECTION_SKIP}, enforced=True)
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0, out
        assert "embedded Postgres wheel not installed" in out, out


class TestClassification:
    @pytest.mark.parametrize(
        "reason",
        [
            "no database configured",
            "database unavailable (OSError: [Errno 61] Connect call failed)",
            "embedded Postgres wheel not installed",
            "repo venv not present",
            "a reason nobody has reviewed yet",
            # CI provisions the golden test's model, so a missing one is a failure there.
            "MiniLM ONNX artifacts not provisioned locally",
        ],
    )
    def test_required_reasons_are_not_optional(self, reason):
        assert not skip_policy.is_optional(reason)

    @pytest.mark.parametrize(
        "reason",
        [
            "embedding model not available offline",
            "apple serves no robots file",
            "workday genuinely covers canada",
            "caffeinate is macOS's",
        ],
    )
    def test_named_optional_reasons_stay_skips(self, reason):
        assert skip_policy.is_optional(reason)

    def test_an_optional_pattern_does_not_excuse_a_longer_reason(self):
        """Full match, not search: a prefix must not smuggle a new reason in."""
        assert not skip_policy.is_optional(
            "embedding model not available offline and the database is down"
        )


def test_this_suite_runs_with_the_policy_registered(request):
    """Removing the conftest import would silently let required skips pass."""
    impls = request.config.pluginmanager.hook.pytest_runtest_makereport.get_hookimpls()
    assert any(impl.function is skip_policy.pytest_runtest_makereport for impl in impls)
