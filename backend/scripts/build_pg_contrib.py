"""Build a stock Postgres contrib module against the bundled pgserver install.

Maintainer tooling for compiling extra modules with PGXS against the wheel's
own `pg_config`. Normal setup installs prebuilt pg_trgm through
`scripts.install_pg_contrib`, without a compiler. To regenerate the shipped
bundles, use `scripts.package_pg_contrib` on disposable wheel copies.

    .venv/bin/python -m scripts.build_pg_contrib [module ...]

Defaults to `pg_trgm`. This command writes into the installed wheel's tree.
"""

from __future__ import annotations

import hashlib
import shutil
import ssl
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from tracker.platform.embedded_db import (
    DEFAULT_POSTGRES_VERSION,
    EmbeddedDbError,
    bundled_bin_dir,
)
from tracker.platform.paths import DATA_DIR

BUILD_ROOT = DATA_DIR / "pgcontrib"
MIRROR = "https://ftp.postgresql.org/pub/source"


def _ssl_context() -> ssl.SSLContext:
    """Framework Python on macOS ships no CA bundle; use certifi's when present."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - certifi is an httpx dependency
        return ssl.create_default_context()


def _install_tree(version: int) -> Path:
    # The shared resolver also gates on VERIFIED_UPSTREAM_VERSIONS — a bump is
    # precisely when this script gets re-run, so the re-verification reminder
    # fires here first.
    try:
        return bundled_bin_dir(version)
    except EmbeddedDbError as exc:
        raise SystemExit(str(exc)) from exc


def _server_version(pg_config: Path) -> str:
    out = subprocess.run(
        [str(pg_config), "--version"], capture_output=True, text=True, check=True
    ).stdout
    return out.split()[1].strip()  # "PostgreSQL 16.14" -> "16.14"


def _download_source(version: str) -> Path:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    tarball = BUILD_ROOT / f"postgresql-{version}.tar.gz"
    src_dir = BUILD_ROOT / f"postgresql-{version}"
    if src_dir.exists():
        return src_dir

    url = f"{MIRROR}/v{version}/postgresql-{version}.tar.gz"
    print(f"downloading {url}")
    ctx = _ssl_context()
    with urllib.request.urlopen(url, context=ctx) as resp, tarball.open("wb") as fh:  # noqa: S310
        shutil.copyfileobj(resp, fh)

    with urllib.request.urlopen(f"{url}.sha256", context=ctx) as resp:  # noqa: S310
        expected = resp.read().decode().split()[0].strip()
    actual = hashlib.sha256(tarball.read_bytes()).hexdigest()
    if actual != expected:
        tarball.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {url}: {actual} != {expected}")
    print(f"sha256 verified: {actual}")

    with tarfile.open(tarball) as tf:
        members = [m for m in tf.getmembers() if "/contrib/" in m.name or "/src/makefiles" in m.name]
        tf.extractall(BUILD_ROOT, members=members, filter="data")
    return src_dir


def _sysroot() -> list[str]:
    """macOS: the wheel bakes in its build machine's SDK path, which is absent here."""
    if sys.platform != "darwin":
        return []
    sdk = subprocess.run(
        ["xcrun", "--show-sdk-path"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return [f"PG_SYSROOT={sdk}"]


def build(module: str, version: int = DEFAULT_POSTGRES_VERSION) -> None:
    if sys.platform == "win32":
        raise SystemExit("Windows contrib builds are not supported.")

    bin_dir = _install_tree(version)
    pg_config = bin_dir / "pg_config"
    full_version = _server_version(pg_config)
    src_dir = _download_source(full_version)
    module_dir = src_dir / "contrib" / module
    if not module_dir.is_dir():
        raise SystemExit(f"no contrib module {module!r} in postgresql-{full_version}")

    cmd = [
        "make",
        "-C",
        str(module_dir),
        "USE_PGXS=1",
        f"PG_CONFIG={pg_config}",
        *_sysroot(),
        "install",
    ]
    print(f"building {module} for PG {full_version}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-15:])
        raise SystemExit(f"build failed:\n{tail}")

    control = bin_dir.parent / "share" / "postgresql" / "extension" / f"{module}.control"
    if not control.exists():
        raise SystemExit(f"build reported success but {control} is missing")
    print(f"installed: {control}")


def main(argv: list[str]) -> int:
    modules = argv[1:] or ["pg_trgm"]
    for module in modules:
        build(module)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
