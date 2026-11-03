"""The README's install steps and SECURITY.md's update rows describe the Mac app as
it ships: a downloaded disk image, not a source checkout. Each fact is read from
the app's own code, so the docs cannot drift from what a release carries."""

import json
import plistlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "launcher" / "macos"


def _section(text: str, heading: str) -> str:
    return text.split(heading + "\n", 1)[1].split("\n#", 1)[0]


def _mac_install() -> str:
    return _section((REPO / "README.md").read_text(), "### Install on macOS")


def _image_name() -> str:
    """The disk image an installed app looks for, with `<version>` for the version."""
    swift = (LAUNCHER / "Sources" / "LauncherCore" / "Updates.swift").read_text()
    prefix = re.search(r'func prefix\(_ version: String\) -> String \{ "([^"]+)" \}', swift)
    assert prefix, "Updates.swift no longer names the release prefix in one line"
    return prefix.group(1).replace(r"\(version)", "<version>") + ".dmg"


def test_mac_install_is_the_release_download():
    """A stranger on a Mac downloads the app from the latest release and needs no
    developer tools; the clone-and-setup steps belong to Linux and contributors."""
    section = _mac_install()
    assert "https://github.com/roleband/roleband/releases/latest" in section
    assert f"`{_image_name()}`" in section
    for source_step in ("git clone", "./setup.sh", "Python", "Node", "deploy/install.sh"):
        assert source_step not in section, f"the Mac install still asks for {source_step!r}"


def test_mac_install_states_the_app_s_minimum_macos():
    """The README's minimum is the one the app's Info.plist enforces."""
    plist = plistlib.loads((LAUNCHER / "Resources" / "LauncherInfo.plist").read_bytes())
    major = plist["LSMinimumSystemVersion"].split(".")[0]
    section = _mac_install()
    assert f"macOS {major} or later" in section
    assert "Apple silicon" in section


def test_mac_install_explains_the_first_open_approval():
    """The app is self-signed, so macOS blocks its first open until the person
    approves it in Privacy & Security; the README must say how."""
    section = _mac_install()
    assert "Open Anyway" in section
    assert "Privacy & Security" in section


def test_readme_never_says_the_app_installs_no_code():
    """The app installs signed updates itself (SECURITY.md, docs/architecture.md#mac-app-updates)."""
    for name in ("README.md", "SECURITY.md"):
        text = (REPO / name).read_text()
        assert "installs no code" not in text, name
        assert "never installs code" not in text, name


def test_security_names_every_host_the_updater_contacts():
    """SECURITY.md's table is the full list of what leaves the computer: the
    release check's endpoint and the asset hosts the download accepts."""
    security = (REPO / "SECURITY.md").read_text()
    updates = (LAUNCHER / "Sources" / "LauncherCore" / "Updates.swift").read_text()
    download = (LAUNCHER / "Sources" / "LauncherCore" / "UpdateDownload.swift").read_text()
    endpoint = re.search(r'"https://(api\.github\.com/repos/)\\\(repository\.rawValue\)(/releases/latest)"', updates)
    assert endpoint, "Updates.swift no longer builds the check endpoint in one string"
    production = re.search(r'case production = "([^"]+)"', download)
    assert production
    assert f"{endpoint.group(1)}{production.group(1)}{endpoint.group(2)}" in security
    hosts = [host for host in re.findall(r'url\.host == "([^"]+)"', download) if host != "127.0.0.1"]
    assert hosts, "UpdateDownload.swift no longer names the hosts it accepts"
    for host in hosts:
        assert host in security, f"SECURITY.md does not name {host}"


def test_security_publishes_the_recorded_release_identity():
    """SECURITY.md's certificate digest and keys are the ones every release is sealed
    with, and its commands read the Info.plist keys the sealing step writes."""
    identity = json.loads((LAUNCHER / "release-identity.json").read_text())
    section = _section((REPO / "SECURITY.md").read_text(), "## Checking a Mac release")
    for field in ("certificate_sha256", "release_public_key", "spare_release_public_key"):
        assert identity.get(field), f"release-identity.json records no {field}"
        assert f"`{identity[field]}`" in section, f"SECURITY.md does not publish {field}"
    signing = (LAUNCHER / "Tools" / "signing.py").read_text()
    written = set(re.findall(r"info\['(RoleBandUpdate\w*Key)'\]", signing))
    assert written == {"RoleBandUpdatePublicKey", "RoleBandUpdateSpareKey"}
    assert set(re.findall(r"plutil -extract (\w+) raw", section)) == written
