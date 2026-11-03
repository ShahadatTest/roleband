"""Installed notes never substitute another version or an unreleased draft."""

from __future__ import annotations

import json

import pytest

from tracker import __version__
from tracker.api.app import app
from tracker.platform.paths import REPO_ROOT
from tracker.platform.releases import (
    UNKNOWN_VERSION,
    release_notes,
    release_version,
    running_version,
)

pytestmark = pytest.mark.usefixtures("no_escape")


def test_version_comes_from_package_metadata_and_reaches_the_api(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(json.dumps({"version": "1.12.0-beta.2+source"}))
    assert release_version(path) == "1.12.0-beta.2+source"
    assert app.version == __version__ == release_version()
    assert release_notes(__version__) is not None
    lock = json.loads((REPO_ROOT / "dashboard/package-lock.json").read_text())
    assert lock["version"] == lock["packages"][""]["version"] == __version__


@pytest.mark.parametrize("version", ["01.0.0", "1.0", "v1.0.0", "1.0.0-beta.01", "1.0.0\n", None])
def test_bad_release_metadata_is_refused(tmp_path, version):
    path = tmp_path / "package.json"
    path.write_text(json.dumps({"version": version}))
    with pytest.raises(ValueError):
        release_version(path)


@pytest.mark.parametrize("text", [
    '{\n<<<<<<< HEAD\n  "version": "1.1.0",\n=======\n  "version": "1.2.0",\n>>>>>>> main\n}',
    '{"name": "roleband"}', '["1.1.0"]', '{"version": "1.1"}', "", None,
])
def test_a_broken_package_file_never_stops_a_running_process(tmp_path, text):
    path = tmp_path / "package.json"
    if text is not None:
        path.write_text(text)
    assert running_version(path) == UNKNOWN_VERSION
    with pytest.raises((OSError, ValueError, KeyError, TypeError)):
        release_version(path)


def test_running_version_reports_a_good_package_file_unchanged(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(json.dumps({"version": "1.12.0-beta.2+source"}))
    assert running_version(path) == "1.12.0-beta.2+source"
    assert running_version() == release_version() == __version__


def test_notes_select_only_the_exact_installed_section(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## [Unreleased]\n\nDRAFT DO NOT DISPLAY\n\n## [1.1.0] - 2026-10-28\n\nNew release.\n\n### Added\n\n- A useful feature.\n\n## [1.0.0]\n\nOld release.\n")
    assert release_notes("1.1.0", path) == "New release.\n\n### Added\n\n- A useful feature."
    assert release_notes("1.0.0", path) == "Old release."
    assert release_notes("1.2.0", path) is None
    assert release_notes("Unreleased", path) is None


def test_empty_missing_or_oversized_notes_do_not_fall_back_to_a_different_release(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    assert release_notes("1.0.0", path) is None
    path.write_text("## [1.0.0]\n\n## [0.9.0]\nOlder notes.")
    assert release_notes("1.0.0", path) is None
    path.write_text("## [1.0.0]\n" + "x" * 65537)
    assert release_notes("1.0.0", path) is None
    path.write_bytes(b"\xff")
    assert release_notes("1.0.0", path) is None


@pytest.mark.asyncio
async def test_the_readonly_http_reply_binds_notes_to_the_actual_engine(api_client, monkeypatch, tmp_path):
    import tracker.api.routers.ops as ops

    settings = ops.get_settings().model_copy(update={"api_host": "127.0.0.1", "api_port": 58221})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\nDRAFT DO NOT DISPLAY\n\n"
        f"## [{__version__}]\n\nThis engine's release.\n\n## [0.0.1]\n\nAn older release.\n"
    )
    monkeypatch.setattr(ops, "release_notes", lambda version: release_notes(version, changelog))
    response = await api_client.get("/api/release-notes")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == body["launcher"]["version"] == __version__
    assert body["launcher"]["api_origin"] == "http://127.0.0.1:58221"
    assert body["notes"] == "This engine's release."


@pytest.mark.asyncio
async def test_remote_binding_does_not_publish_a_false_local_identity(api_client, monkeypatch):
    import tracker.api.routers.ops as ops

    settings = ops.get_settings().model_copy(update={"api_host": "192.168.1.2"})
    monkeypatch.setattr(ops, "get_settings", lambda: settings)
    body = (await api_client.get("/api/release-notes")).json()
    assert body["launcher"] is None
    assert body["version"] == __version__
