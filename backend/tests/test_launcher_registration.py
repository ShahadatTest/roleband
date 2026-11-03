"""Discovery follows the installed checkout, never another clone or a port guess."""

from __future__ import annotations

import json
import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tracker.platform.launcher import (
    installation_identity,
    installed_checkout,
    register_installation,
    registration_path,
    unregister_installation,
)


def checkout(path: Path) -> Path:
    (path / "deploy").mkdir(parents=True)
    (path / "deploy" / "roleband").write_text("#!/bin/sh\n")
    (path / "backend").mkdir()
    return path


def install(home: Path, root: Path, **overrides: object) -> Path:
    path = home / "Library" / "LaunchAgents" / "com.roleband.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    item = {
        "Label": "com.roleband",
        "ProgramArguments": [str(root / "deploy" / "roleband")],
        "WorkingDirectory": str(root / "backend"),
        **overrides,
    }
    path.write_bytes(plistlib.dumps(item))
    return path


def identity(root: Path, *, port: int = 58199, version: str = "0.1.0"):
    return installation_identity(root, api_host="127.0.0.1", api_port=port, version=version)


@pytest.mark.parametrize(("host", "expected"), [
    ("127.0.0.1", "127.0.0.1"), ("localhost", "localhost"), ("::1", "[::1]"),
    ("0.0.0.0", "127.0.0.1"), ("::", "[::1]"),
])
def test_identity_uses_the_configured_port_and_only_a_local_origin(tmp_path, host, expected):
    value = installation_identity(tmp_path, api_host=host, api_port=58201, version="1.2.3")
    assert value["api_origin"] == f"http://{expected}:58201"
    assert value["product"] == "roleband"
    assert value["format"] == 1
    assert value["version"] == "1.2.3"
    assert str(tmp_path) not in json.dumps(value)


@pytest.mark.parametrize(("host", "port"), [
    ("example.com", 8010), ("192.168.1.2", 8010), ("http://localhost", 8010),
    ("localhost@evil.example", 8010), ("127.0.0.1", 0), ("127.0.0.1", 65536),
])
def test_identity_refuses_remote_hosts_and_invalid_ports(tmp_path, host, port):
    with pytest.raises(ValueError):
        installation_identity(tmp_path, api_host=host, api_port=port, version="0.1.0")


def test_instance_is_stable_across_symlinks_versions_and_ports_but_distinguishes_clones(tmp_path):
    root = checkout(tmp_path / "installed")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert identity(alias, port=58202, version="2.0.0")["instance"] == identity(root)["instance"]
    assert identity(tmp_path / "worktree")["instance"] != identity(root)["instance"]
    install(tmp_path / "home", alias)
    assert installed_checkout(root, home=tmp_path / "home")


def test_a_worktree_cannot_register_or_remove_the_installed_engines_discovery(tmp_path):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    other = checkout(tmp_path / "worktree")
    install(home, root)
    assert register_installation(root, identity(root), home=home)
    saved = registration_path(home).read_bytes()
    assert not register_installation(other, identity(other), home=home)
    assert not unregister_installation(other, home=home)
    assert registration_path(home).read_bytes() == saved


def test_no_installed_item_means_no_discovery_directory_is_created(tmp_path):
    home = tmp_path / "home"
    assert not register_installation(tmp_path, identity(tmp_path), home=home)
    assert not (home / ".roleband").exists()


@pytest.mark.parametrize("overrides", [
    {"Label": "other.service"}, {"ProgramArguments": []},
    {"ProgramArguments": ["relative/deploy/roleband"]},
    {"ProgramArguments": ["/bin/sh", "deploy/roleband"]},
    {"ProgramArguments": [123]}, {"WorkingDirectory": "/tmp"},
    {"WorkingDirectory": "backend"}, {"Program": "/bin/sh"},
])
def test_unknown_or_mismatched_plist_shapes_cannot_publish(tmp_path, overrides):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root, **overrides)
    assert not register_installation(root, identity(root), home=home)
    assert not registration_path(home).exists()


@pytest.mark.parametrize("data", [b"broken plist", b"x" * 32769, plistlib.dumps(["not a dictionary"])])
def test_malformed_and_oversized_plists_fail_closed(tmp_path, data):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    path = install(home, root)
    path.write_bytes(data)
    assert not register_installation(root, identity(root), home=home)


def test_a_symlink_loop_in_the_installed_program_fails_closed(tmp_path):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    install(home, root, ProgramArguments=[str(loop)])
    assert not register_installation(root, identity(root), home=home)
    assert not unregister_installation(root, home=home)


def test_refresh_is_atomic_private_and_replaces_the_old_port_without_changing_instance(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root)
    assert register_installation(root, identity(root), home=home)
    path = registration_path(home)
    before = path.read_bytes()
    replace = os.replace
    observed = []

    def observe_replace(source, destination):
        observed.append((path.read_bytes(), json.loads(Path(source).read_bytes())))
        replace(source, destination)

    monkeypatch.setattr(os, "replace", observe_replace)
    changed = identity(root, port=58203, version="1.0.0")
    assert register_installation(root, changed, home=home)
    assert observed == [(before, changed)]
    assert json.loads(path.read_bytes()) == changed
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert list(path.parent.iterdir()) == [path]


def test_failed_atomic_replace_preserves_the_previous_complete_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root)
    register_installation(root, identity(root), home=home)
    path = registration_path(home)
    before = path.read_bytes()

    def fail_replace(*args):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        register_installation(root, identity(root, port=58204), home=home)
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("link", ["directory", "file"])
def test_discovery_symlinks_are_refused_without_changing_their_target(tmp_path, link):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root)
    path = registration_path(home)
    path.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "installation.json"
    victim.write_text("untouched")
    if link == "directory":
        path.parent.rmdir()
        path.parent.symlink_to(outside, target_is_directory=True)
    else:
        path.symlink_to(victim)
    with pytest.raises(ValueError):
        register_installation(root, identity(root), home=home)
    assert not unregister_installation(root, home=home)
    assert victim.read_text() == "untouched"


@pytest.mark.parametrize("value", [
    {"product": "other", "instance": "wrong", "format": 1},
    {"product": "roleband", "instance": "another-checkout", "format": 1},
    ["not an identity"], None,
])
def test_uninstall_preserves_unrelated_registration(tmp_path, value):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root)
    path = registration_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value))
    assert not unregister_installation(root, home=home)
    assert json.loads(path.read_text()) == value


def test_uninstall_removes_its_own_registration_even_after_port_and_version_changes(tmp_path):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root)
    register_installation(root, identity(root, port=58205, version="old"), home=home)
    assert unregister_installation(root, home=home)
    assert not registration_path(home).exists()
    assert not unregister_installation(root, home=home)


def test_an_item_not_owned_by_the_current_user_cannot_publish_or_remove(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = checkout(tmp_path / "installed")
    install(home, root)
    register_installation(root, identity(root), home=home)
    before = registration_path(home).read_bytes()
    monkeypatch.setattr(os, "getuid", lambda: registration_path(home).stat().st_uid + 1)
    assert not register_installation(root, identity(root, port=58207), home=home)
    assert not unregister_installation(root, home=home)
    assert registration_path(home).read_bytes() == before


@pytest.mark.parametrize("blocked", [False, True])
def test_existing_install_refreshes_without_new_environment_or_a_database_and_tolerates_failure(tmp_path, blocked):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    install(home, root)
    if blocked:
        directory = registration_path(home).parent
        directory.parent.mkdir()
        directory.write_text("not a directory")
    environment = {
        **os.environ, "HOME": str(home), "PYTHONPATH": str(root / "backend"),
        "ROLEBAND_API_HOST": "127.0.0.1", "ROLEBAND_API_PORT": "58206",
        "ROLEBAND_PGDATA": str(tmp_path / "must-not-start-db"), "ROLEBAND_DATABASE_URL": "",
    }
    done = subprocess.run(
        [sys.executable, "-c", "from tracker.supervisor.launcher import refresh_registration; refresh_registration()"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    if blocked:
        assert "Could not publish launcher discovery" in done.stderr
        assert not registration_path(home).exists()
    else:
        value = json.loads(registration_path(home).read_bytes())
        assert value["api_origin"] == "http://127.0.0.1:58206"
        assert value["instance"] == identity(root)["instance"]
    assert not (tmp_path / "must-not-start-db").exists()
