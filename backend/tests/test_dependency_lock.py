"""The per-platform locks agree with the requirements they were generated from.

`backend/constraints/<platform>.txt` pins the whole install graph, and every
install passes one with `-c`. A requirements pin bumped without regenerating
would make that `-c` either contradict the request (pip refuses) or, for a
package whose marker changed, pin something the platform should not get. This
fails by package name first, so the fix is obvious: run
`.venv/bin/python -m scripts.lock_dependencies`.
"""

from __future__ import annotations

import re

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.lock_dependencies import BACKEND, CONSTRAINTS_DIR, PLATFORMS, REQUIREMENTS

#: Marker environment for each locked platform.
ENVIRONMENTS: dict[str, dict[str, str]] = {
    "macos-arm64": {"sys_platform": "darwin", "platform_system": "Darwin", "platform_machine": "arm64"},
    "linux-x86_64": {"sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64"},
    "linux-aarch64": {"sys_platform": "linux", "platform_system": "Linux", "platform_machine": "aarch64"},
}

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==(\S+?)\s*(?:;.*)?$")


def read_requirements(text: str) -> list[Requirement]:
    reqs = []
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if line and not line.startswith(("#", "-")):
            reqs.append(Requirement(line))
    return reqs


def read_lock(text: str) -> tuple[dict[str, str], list[str]]:
    """(name -> pinned version, lines that are not an exact pin)."""
    pins: dict[str, str] = {}
    unpinned: list[str] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = _PIN.match(raw.strip())
        if match is None:
            unpinned.append(raw)
            continue
        pins[canonicalize_name(match.group(1))] = match.group(2)
    return pins, unpinned


def drift(requirements: list[Requirement], lock: dict[str, str], env: dict[str, str]) -> list[str]:
    environment = {"python_version": "3.12", "python_full_version": "3.12.0", **env}
    problems = []
    for req in requirements:
        name = canonicalize_name(req.name)
        (spec,) = req.specifier  # every direct requirement is an exact pin
        applies = req.marker is None or req.marker.evaluate(environment)
        if applies and lock.get(name) != spec.version:
            problems.append(f"{req.name}: requirements pin {spec.version}, lock has {lock.get(name)}")
        if not applies and name in lock:
            problems.append(f"{req.name}: its marker excludes this platform, yet the lock pins it")
    return problems


def _requirements() -> list[Requirement]:
    return [req for name in REQUIREMENTS for req in read_requirements((BACKEND / name).read_text())]


def test_every_locked_platform_has_a_marker_environment():
    assert set(ENVIRONMENTS) == set(PLATFORMS)


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_the_lock_exists_and_names_how_it_was_made(platform):
    text = (CONSTRAINTS_DIR / f"{platform}.txt").read_text()
    assert "scripts.lock_dependencies" in text.splitlines()[1]


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_the_lock_agrees_with_every_direct_requirement(platform):
    pins, _ = read_lock((CONSTRAINTS_DIR / f"{platform}.txt").read_text())
    assert drift(_requirements(), pins, ENVIRONMENTS[platform]) == []


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_every_line_of_the_lock_is_an_exact_pin(platform):
    _, unpinned = read_lock((CONSTRAINTS_DIR / f"{platform}.txt").read_text())
    assert unpinned == []


def test_a_bumped_pin_without_relocking_is_reported_by_name():
    """The control: `drift` must be able to say no."""
    pins, _ = read_lock((CONSTRAINTS_DIR / "linux-x86_64.txt").read_text())
    bumped = read_requirements("httpx[http2]==99.0.0\n")
    assert drift(bumped, pins, ENVIRONMENTS["linux-x86_64"]) == [
        f"httpx: requirements pin 99.0.0, lock has {pins['httpx']}"
    ]


def test_a_package_its_marker_excludes_is_reported_when_locked():
    reqs = read_requirements('apple-fm-sdk==0.2.1; sys_platform == "darwin"\n')
    assert drift(reqs, {"apple-fm-sdk": "0.2.1"}, ENVIRONMENTS["linux-aarch64"]) != []
    assert drift(reqs, {"apple-fm-sdk": "0.2.1"}, ENVIRONMENTS["macos-arm64"]) == []


def test_the_runtime_requirements_carry_no_test_tooling():
    """`deploy/install.sh` installs requirements.txt alone into the always-on runtime."""
    runtime = {canonicalize_name(r.name) for r in read_requirements((BACKEND / "requirements.txt").read_text())}
    assert not {name for name in runtime if name.startswith(("pytest", "ruff", "import-linter"))}
