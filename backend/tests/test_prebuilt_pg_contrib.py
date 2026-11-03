"""Prebuilt extensions install offline and refuse mismatched or damaged inputs."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from scripts import install_pg_contrib as installer


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    original = json.loads((installer.BUNDLES / "manifest.json").read_text())
    key = "darwin-arm64"
    entry = original["platforms"][key]
    resources = tmp_path / "bundles"
    resources.mkdir()
    (resources / entry["bundle"]).write_bytes((installer.BUNDLES / entry["bundle"]).read_bytes())
    monkeypatch.setattr(installer, "BUNDLES", resources)
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(installer.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(installer.metadata, "version", lambda name: original["wheel_version"])
    manifest = resources / "manifest.json"
    manifest.write_text(json.dumps(original))
    tree = tmp_path / "wheel"
    (tree / "bin").mkdir(parents=True)
    def pg_version(command, **kwargs):
        assert command == [str(tree / "bin/pg_config"), "--version"]
        return "PostgreSQL 16.14\n"
    monkeypatch.setattr(installer.subprocess, "check_output", pg_version)
    return tree, manifest, original, entry


def test_install_restores_every_pinned_file_and_is_idempotent(bundle):
    tree, _, _, entry = bundle
    installer.install(tree / "bin")
    for name, expected in entry["files"].items():
        assert hashlib.sha256((tree / name).read_bytes()).hexdigest() == expected
    before = {name: (tree / name).stat().st_mtime_ns for name in entry["files"]}
    installer.install(tree / "bin")
    assert before == {name: (tree / name).stat().st_mtime_ns for name in entry["files"]}
    assert (tree / "share/postgresql/extension/pg_trgm.control").is_file()
    assert (tree / "lib/postgresql/pg_trgm.dylib").is_file()


def test_damaged_bundle_writes_no_runtime_files(bundle):
    tree, manifest, _, entry = bundle
    path = manifest.parent / entry["bundle"]
    path.write_bytes(path.read_bytes() + b"damage")
    with pytest.raises(ValueError, match="bundle checksum mismatch"):
        installer.install(tree / "bin")
    assert list(tree.iterdir()) == [tree / "bin"]


@pytest.mark.parametrize("bad", ["file-checksum", "missing-file", "traversal", "symlink"])
def test_invalid_archive_is_rejected_before_any_file_is_published(bundle, bad):
    tree, manifest, content, entry = bundle
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        member = tarfile.TarInfo("lib/postgresql/pg_trgm.dylib")
        data = b"incorrect library"
        if bad == "traversal":
            member.name = "../outside"
            entry["files"][member.name] = hashlib.sha256(data).hexdigest()
        if bad == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "../outside"
        if bad == "missing-file":
            entry["files"][member.name] = hashlib.sha256(data).hexdigest()
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    payload = stream.getvalue()
    (manifest.parent / entry["bundle"]).write_bytes(payload)
    entry["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="checksum mismatch|incomplete|invalid"):
        installer.install(tree / "bin")
    assert list(tree.iterdir()) == [tree / "bin"]
    assert not (tree.parent / "outside").exists()


def test_different_wheel_version_is_refused_before_installing(bundle, monkeypatch):
    tree, *_ = bundle
    monkeypatch.setattr(installer.metadata, "version", lambda name: "0.7.0")
    with pytest.raises(ValueError, match="no prebuilt pg_trgm.*0.7.0"):
        installer.install(tree / "bin")
    assert list(tree.iterdir()) == [tree / "bin"]


def test_different_postgres_build_is_refused_before_installing(bundle, monkeypatch):
    tree, *_ = bundle
    monkeypatch.setattr(installer.subprocess, "check_output", lambda *a, **kw: "PostgreSQL 16.15\n")
    with pytest.raises(ValueError, match="no prebuilt pg_trgm.*16.15"):
        installer.install(tree / "bin")
    assert list(tree.iterdir()) == [tree / "bin"]


def test_unsupported_platform_is_refused_before_installing(bundle, monkeypatch):
    tree, *_ = bundle
    monkeypatch.setattr(installer.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="no prebuilt pg_trgm for darwin-x86_64"):
        installer.install(tree / "bin")
    assert list(tree.iterdir()) == [tree / "bin"]


def test_every_supported_platform_has_a_complete_verified_bundle():
    manifest = json.loads((installer.BUNDLES / "manifest.json").read_text())
    assert set(manifest["platforms"]) == {"darwin-arm64", "linux-aarch64", "linux-x86_64"}
    for entry in manifest["platforms"].values():
        payload = (installer.BUNDLES / entry["bundle"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
            assert {member.name for member in members} == entry["files"].keys()
            for member in members:
                assert member.isfile()
                extracted = archive.extractfile(member)
                assert extracted is not None
                assert hashlib.sha256(extracted.read()).hexdigest() == entry["files"][member.name]
        assert "share/postgresql/extension/pg_trgm.COPYRIGHT" in entry["files"]
