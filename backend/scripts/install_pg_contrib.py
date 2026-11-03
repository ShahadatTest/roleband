"""Install the bundled pg_trgm without a compiler or a network connection.

    .venv/bin/python -m scripts.install_pg_contrib
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import platform
import subprocess
import tarfile
import tempfile
from importlib import metadata
from pathlib import Path

from tracker.platform.embedded_db import bundled_bin_dir

BUNDLES = Path(__file__).resolve().parents[1] / "tracker/platform/pgcontrib"


def install(bin_dir: Path) -> None:
    manifest = json.loads((BUNDLES / "manifest.json").read_text())
    wheel_version = metadata.version("pixeltable-pgserver")
    if wheel_version != manifest["wheel_version"]:
        raise ValueError(f"no prebuilt pg_trgm for pixeltable-pgserver {wheel_version}; rebuild the bundles")
    server_version = subprocess.check_output([str(bin_dir / "pg_config"), "--version"], text=True).strip()
    if server_version != f"PostgreSQL {manifest['postgres']}":
        raise ValueError(f"no prebuilt pg_trgm for {server_version}; rebuild the bundles")
    key = f"{platform.system().lower()}-{platform.machine().lower()}"
    entry = manifest["platforms"].get(key)
    if entry is None:
        raise ValueError(f"no prebuilt pg_trgm for {key}")
    content = (BUNDLES / entry["bundle"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ValueError("pg_trgm bundle checksum mismatch; restore the checkout")
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts or member.name not in entry["files"] or member.name in files:
                raise ValueError(f"invalid pg_trgm bundle member: {member.name}")
            stream = archive.extractfile(member)
            assert stream is not None
            data = stream.read()
            if hashlib.sha256(data).hexdigest() != entry["files"][member.name]:
                raise ValueError(f"pg_trgm file checksum mismatch: {member.name}")
            files[member.name] = data
    if files.keys() != entry["files"].keys():
        raise ValueError("pg_trgm bundle is incomplete")
    tree = bin_dir.parent
    with (tree / ".roleband-pgcontrib.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Publish the control file last so Postgres sees only a complete extension.
        for name in sorted(files, key=lambda name: name.endswith(".control")):
            target = tree / name
            if target.is_file() and target.read_bytes() == files[name]:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                staged = Path(temporary.name)
                try:
                    temporary.write(files[name])
                    temporary.flush()
                    staged.chmod(0o644)
                    os.replace(staged, target)
                finally:
                    staged.unlink(missing_ok=True)


def main() -> None:
    install(bundled_bin_dir())
    print("pg_trgm installed from the verified prebuilt bundle")


if __name__ == "__main__":
    main()
