"""Build a pinned pg_trgm bundle in a disposable copy of the database wheel.

Run on the target platform with a compiler; users run install_pg_contrib instead.
Inputs and output hashes live in tracker/platform/pgcontrib/manifest.json.

    python -m scripts.package_pg_contrib --wheel WHEEL --source TARBALL
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from scripts.build_pg_contrib import _ssl_context

BUNDLES = Path(__file__).resolve().parents[1] / "tracker/platform/pgcontrib"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(wheel: Path, source: Path) -> Path:
    manifest = json.loads((BUNDLES / "manifest.json").read_text())
    key = f"{platform.system().lower()}-{platform.machine().lower()}"
    entry = manifest["platforms"][key]
    if wheel.name != entry["wheel"] or digest(wheel) != entry["wheel_sha256"]:
        raise ValueError("database wheel does not match the pinned build input")
    if digest(source) != manifest["source_sha256"]:
        raise ValueError("PostgreSQL source does not match the pinned build input")
    with tempfile.TemporaryDirectory(prefix="roleband-pgcontrib-") as temporary:
        work = Path(temporary)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(work / "wheel")
            for info in archive.infolist():
                if info.external_attr >> 16:
                    (work / "wheel" / info.filename).chmod(info.external_attr >> 16)
        with tarfile.open(source) as archive:
            archive.extractall(work, filter="data")
        tree = work / "wheel/pixeltable_pgserver/pginstall"
        pg_config = tree / "bin/pg_config"
        src = work / f"postgresql-{manifest['postgres']}"
        cmd = ["make", "-C", str(src / "contrib/pg_trgm"), "USE_PGXS=1", f"PG_CONFIG={pg_config}", "enable_rpath=no"]
        if platform.system() == "Darwin":
            sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
            cmd += [f"PG_SYSROOT={sdk}", "MACOSX_DEPLOYMENT_TARGET=14.0"]
        subprocess.run([*cmd, "install"], check=True, env={**os.environ, "SOURCE_DATE_EPOCH": "0"})
        library = tree / "lib/postgresql" / ("pg_trgm.dylib" if platform.system() == "Darwin" else "pg_trgm.so")
        files = [library, *sorted((tree / "share/postgresql/extension").glob("pg_trgm*"))]
        notice = tree / "share/postgresql/extension/pg_trgm.COPYRIGHT"
        notice.write_bytes((src / "COPYRIGHT").read_bytes())
        files.append(notice)
        hashes = {}
        output = BUNDLES / entry["bundle"]
        with output.open("wb") as raw, gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as archive:
            for path in sorted(set(files)):
                relative = path.relative_to(tree).as_posix()
                data = path.read_bytes()
                hashes[relative] = hashlib.sha256(data).hexdigest()
                member = tarfile.TarInfo(relative)
                member.size = len(data)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(data))
        entry.update(sha256=digest(output), files=hashes)
        (BUNDLES / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--download", action="store_true", help="download the pinned build inputs")
    args = parser.parse_args()
    if args.download:
        if args.wheel or args.source:
            parser.error("--download cannot be combined with --wheel or --source")
        manifest = json.loads((BUNDLES / "manifest.json").read_text())
        key = f"{platform.system().lower()}-{platform.machine().lower()}"
        entry = manifest["platforms"][key]
        with tempfile.TemporaryDirectory(prefix="roleband-pgcontrib-inputs-") as temporary:
            wheel = Path(temporary) / entry["wheel"]
            source = Path(temporary) / "postgresql.tar.gz"
            for url, path in [(entry["wheel_url"], wheel), (manifest["source_url"], source)]:
                with urllib.request.urlopen(url, context=_ssl_context(), timeout=60) as response:  # noqa: S310
                    path.write_bytes(response.read())
            print(package(wheel, source))
    else:
        if not args.wheel or not args.source:
            parser.error("supply --wheel and --source, or --download")
        print(package(args.wheel, args.source))


if __name__ == "__main__":
    main()
