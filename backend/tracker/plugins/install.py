"""Install a plugin from a directory: check it, pin it, copy it, record it.

Plugins install from the CLI only. An install:

1. validates the manifest (the SDK's rules, then the core's, `plugin_manifest`);
2. runs the static check (`roleband_plugin_sdk.checks`): plugin code that
   imports a network or process module does not load;
3. hashes what will run: the manifest bytes, the source tree (`code_sha`) and
   the lock file if there is one. Their fingerprint is what approval approves;
4. copies the tree to `<plugins_dir>/<id>/src`, and (unless told not to)
   builds `<plugins_dir>/<id>/venv` with the SDK from this checkout and the
   plugin, under the core's constraints file;
5. records `plugin_install`. An update keeps `enabled` but lapses approval.

`code_sha` is recomputed by the host before every run (`installed_code_sha`),
so an edit to the installed copy stops the plugin rather than running
unapproved code.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import PluginInstall
from tracker.platform.paths import PACKAGED, REPO_ROOT, backend_dir
from tracker.plugin_manifest import COMPANY_FACTS, fact_rank_of
from tracker.plugins import store, writer

#: Not part of what runs, so not part of what is approved.
IGNORED = ("__pycache__", ".git", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist")
LOCK_FILES = ("pylock.toml", "uv.lock", "requirements.lock")
#: The one lock format pip installs, every pin with its hash. A plugin with
#: another lock exports this one (`uv export --format requirements-txt`).
PIP_LOCK = "requirements.lock"
#: What pip, and the plugin's build backend it runs, see of our environment:
#: what the plugin's own runs see (`roleband_plugin_sdk.launch.PASSED_ENV`), no
#: address or key of ours.
BUILD_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
SDK_DIR = REPO_ROOT / "sdk" / "python"
#: The SDK depends on it and neither is on an index, so a plugin's venv
#: installs both from this checkout.
ROBOTS_DIR = REPO_ROOT / "robots" / "python"


class InstallRefused(Exception):
    """The plugin cannot be installed; `problems` says why."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def _files(root: Path, *, bytecode: bool = False) -> list[Path]:
    skipped = set(IGNORED) - ({"__pycache__"} if bytecode else set())
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in skipped or part.endswith(".egg-info") for part in rel.parts):
            continue
        if path.is_file():
            out.append(path)
    return out


def code_sha(root: Path, *, bytecode: bool = False) -> str:
    """sha256 over every file's relative path and bytes, in path order."""
    digest = hashlib.sha256()
    for path in _files(root, bytecode=bytecode):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def installed_code_sha(src: Path) -> str:
    """`code_sha` of an installed copy, its bytecode caches counted. The copy is
    made without them and the runner writes none (`-B`), but Python imports a
    cached module whose header matches its source in place of the source, so a
    cache that appears is code nobody approved."""
    return code_sha(src, bytecode=True)


def _commit(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return (done.stdout.strip() or None) if done.returncode == 0 else None


@dataclass(frozen=True)
class Inspected:
    manifest: Any  # roleband_plugin_sdk.manifest.PluginManifest
    manifest_sha: str
    code_sha: str
    lock_sha: str | None
    commit_sha: str | None

    @property
    def fingerprint(self) -> str:
        return store.fingerprint(manifest_sha=self.manifest_sha, code_sha=self.code_sha, lock_sha=self.lock_sha)


def inspect(source: Path) -> Inspected:
    """Everything an install would record about `source`, or `InstallRefused`."""
    from roleband_plugin_sdk.checks import scan
    from roleband_plugin_sdk.launch import code_root
    from roleband_plugin_sdk.manifest import MANIFEST_FILENAME, ManifestError

    from tracker.plugin_manifest import load

    try:
        manifest = load(source)
    except ManifestError as exc:
        raise InstallRefused(exc.problems) from None
    except FileNotFoundError:
        raise InstallRefused([f"{source} has no roleband-plugin.toml"]) from None
    findings = [str(f) for f in scan(code_root(source))]
    if findings:
        raise InstallRefused([f"reaches the network or a process itself: {f}" for f in findings])
    lock = next((source / name for name in LOCK_FILES if (source / name).is_file()), None)
    if lock is not None and lock.name != PIP_LOCK:
        # Approval covers the lock; installing anything but its pins would make
        # that a promise the venv does not keep.
        raise InstallRefused([f"{lock.name}: pip installs only a {PIP_LOCK} with hashes; export one "
                              f"(uv export --format requirements-txt > {PIP_LOCK})"])
    return Inspected(
        manifest=manifest,
        manifest_sha=hashlib.sha256((source / MANIFEST_FILENAME).read_bytes()).hexdigest(),
        code_sha=code_sha(source),
        lock_sha=hashlib.sha256(lock.read_bytes()).hexdigest() if lock else None,
        commit_sha=_commit(source),
    )


def constraints_file() -> Path:
    machine = platform.machine().lower()
    name = "macos-arm64.txt" if sys.platform == "darwin" else (
        "linux-aarch64.txt" if machine in ("aarch64", "arm64") else "linux-x86_64.txt")
    return backend_dir(REPO_ROOT) / "constraints" / name


def _packaged_wheel(name: str) -> str:
    wheels = list((REPO_ROOT / "plugin-wheels").glob(f"{name}-*.whl"))
    if len(wheels) != 1:
        raise InstallRefused([f"the app must contain exactly one {name} wheel; reinstall RoleBand"])
    return str(wheels[0])


def pip_steps(python: Path, src: Path) -> list[list[str]]:
    """The pip commands that fill a plugin's venv. With a `requirements.lock`
    the approved pins are what is installed (`--require-hashes`, then the
    robots matcher, the SDK and the plugin with no further resolution);
    without one, the three resolve under the core's constraints file.

    The matcher is named explicitly rather than left to the SDK's dependency
    on it: it is published to no index, so a resolver would look for it there
    and fail. Passed in the same command, it satisfies that dependency from
    this checkout."""
    pip = [str(python), "-m", "pip", "install", "--quiet"]
    # A source distribution builds metadata beside its code. Bundled wheels
    # install without writing into the signed app's SDK and matcher resources.
    robots = _packaged_wheel("roleband_robots") if PACKAGED else str(ROBOTS_DIR)
    sdk = _packaged_wheel("roleband_plugin_sdk") if PACKAGED else str(SDK_DIR)
    lock = src / PIP_LOCK
    if lock.is_file():
        return [pip + ["--require-hashes", "-r", str(lock)],
                pip + ["--no-deps", robots, sdk, str(src)]]
    return [pip + ["-c", str(constraints_file()), robots, sdk, str(src)]]


def build_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in BUILD_ENV if k in os.environ}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def build_venv(home: Path, *, src: Path | None = None, into: Path | None = None) -> Path:
    """A venv at `into` (default `<home>/venv`) with the SDK from this checkout and
    the plugin from `src` (default `<home>/src`). Both installed as copies, so an
    update builds beside the installed venv and is renamed into place."""
    venv = into or home / "venv"
    if venv.exists():
        shutil.rmtree(venv)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, env=build_env())
    python = venv / "bin" / "python"
    for step in pip_steps(python, src or home / "src"):
        subprocess.run(step, check=True, env=build_env())
    return python


def _swap(dest: Path, staged: Path) -> None:
    """Put `staged` in `dest`'s place, the old one out of the way first."""
    old = dest.with_name(dest.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if dest.exists():
        dest.rename(old)
    staged.rename(dest)
    shutil.rmtree(old, ignore_errors=True)


async def install(
    session: AsyncSession, source: Path, *, plugins_dir: Path, venv: bool = True
) -> tuple[PluginInstall, bool]:
    """Install or update from `source`. Returns the row and whether an approval
    it had has lapsed."""
    inspected = inspect(source)
    manifest = inspected.manifest
    if await session.get(PluginInstall, manifest.id) is None and await writer.provider_has_rows(session, manifest.id):
        # Rows written under that value before any plugin had it would read as
        # this plugin's own; its own rows never block its update.
        raise InstallRefused([f"the id {manifest.id!r} already names data RoleBand stored; "
                              "give the plugin another id"])
    home = plugins_dir / manifest.id
    dest = home / "src"
    # Built beside the installed copy and venv, swapped in only once both are
    # ready: a failed copy or pip leaves the installed version, which
    # still matches its approval, untouched.
    staged_src, staged_venv = home / "src.new", home / "venv.new"
    for staged in (staged_src, staged_venv):
        if staged.exists():
            shutil.rmtree(staged)
    shutil.copytree(source, staged_src, ignore=shutil.ignore_patterns(*IGNORED, "*.egg-info"))
    (home / "data").mkdir(parents=True, exist_ok=True)
    try:
        if code_sha(staged_src) != inspected.code_sha:
            raise InstallRefused(["the copied tree does not hash as the source did; the installed version is unchanged"])
        if venv:
            try:
                build_venv(home, src=staged_src, into=staged_venv)
            except subprocess.CalledProcessError as exc:
                raise InstallRefused([f"its environment could not be built ({' '.join(map(str, exc.cmd[:4]))} "
                                      f"exited {exc.returncode}); the installed version is unchanged"]) from None
    except BaseException:
        shutil.rmtree(staged_src, ignore_errors=True)
        shutil.rmtree(staged_venv, ignore_errors=True)
        raise
    _swap(dest, staged_src)
    if venv:
        _swap(home / "venv", staged_venv)
    from roleband_plugin_sdk import SDK_VERSION

    before = await session.get(PluginInstall, manifest.id)
    was_approved = before is not None and before.approved_fingerprint == before.fingerprint
    row = await store.record_install(
        session, plugin_id=manifest.id, name=manifest.plugin.name, version=manifest.plugin.version,
        source_dir=str(dest), manifest=manifest.model_dump(mode="json"), manifest_sha=inspected.manifest_sha,
        code_sha=inspected.code_sha, commit_sha=inspected.commit_sha, lock_sha=inspected.lock_sha,
        sdk_version=SDK_VERSION,
    )
    return row, was_approved and row.approved_fingerprint != row.fingerprint


def forget_code(source_dir: str) -> bool:
    """Delete an installed plugin's copied code and venv, never its `data/`
    and never anything outside its own home. True when there was code to delete."""
    dest = Path(source_dir)
    home = dest.parent
    if dest.name != "src" or not dest.exists():
        return False
    shutil.rmtree(dest)
    shutil.rmtree(home / "venv", ignore_errors=True)
    return True


def approval_text(manifest: dict[str, Any]) -> dict[str, Any]:
    """What approving shows, and stores: everything the plugin may do."""
    plugin = manifest["plugin"]
    network = manifest.get("network") or {}
    return {
        "plugin": plugin["id"],
        "name": plugin["name"],
        "version": plugin["version"],
        "repository": plugin["repository"],
        "licence": plugin["licence"],
        "attribution": plugin["attribution"],
        "slots": [p["slot"] for p in manifest["provides"]],
        "fact_fields": next((list(p.get("fields") or []) for p in manifest["provides"]
                             if p["slot"] == COMPANY_FACTS), []),
        # The trust its company facts get, capped by the core; None without facts.
        "fact_rank": fact_rank_of(manifest["provides"]),
        "hosts": list(network.get("hosts", [])),
        "identity": network.get("identity"),
        "jobs": [{"name": j["name"], "schedule": j["schedule"], "budget_seconds": j["budget_seconds"],
                  "needs": list(j.get("needs", []))} for j in manifest["jobs"]],
    }
