"""The app's copy of the published datasets, and the lock that names it.

The level atlas and the benefits dataset are edited in their own repository,
`roleband-data`. The app carries a read-only copy of one data commit at its
usual paths, so a clone sets up offline. `tracker/datasets.lock.json` names
that commit and every file's sha256 and size; `tests/test_dataset_lock.py`
fails on a copy that differs from the lock, on a file it does not name, on a
missing one, and on a trial.

    .venv/bin/python -m scripts.data pin ../../roleband-data         # copy a pushed data commit
    .venv/bin/python -m scripts.data pin --try ../../roleband-data   # copy working files, as a trial
    .venv/bin/python -m scripts.data lock                            # re-record the copy, until pinned
    .venv/bin/python -m scripts.data export /tmp/roleband-data       # the data repository's files, until pinned

The loop: edit in the data checkout, `pin --try` and run the app's tests,
commit and push the data, then `pin` and commit the pin with any code change.

Until the copy is pinned to a data commit (the lock's `commit` is empty), the
data is edited in the app tree and `lock` records it, and `export` writes the
data repository's first commit from it. Once pinned, both refuse and the build
scripts write into a data checkout (`output_dir`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tracker.platform.paths import REPO_ROOT

BACKEND = REPO_ROOT / "backend"
LOCK = BACKEND / "tracker" / "datasets.lock.json"
REPOSITORY = "https://github.com/roleband/roleband-data"
#: The data repository's folder for each dataset -> the app's copy, from `backend/`.
DATASETS = {"atlas": "tracker/levels/atlas", "benefits": "tracker/profiles/benefits_dataset"}
#: Where a build writes once the copy is pinned and no `--out` is given.
DEFAULT_CHECKOUT = REPO_ROOT.parent / "roleband-data"
#: The data repository's own files, kept here until it exists: template -> its path there.
TEMPLATES = BACKEND / "scripts" / "data_repo"
REPO_FILES = {
    "LICENSE": "LICENSE",
    "README.md": "README.md",
    "CONTRIBUTING.md": "CONTRIBUTING.md",
    "gitattributes": ".gitattributes",
    "check.yml": ".github/workflows/check.yml",
}


class DataError(RuntimeError):
    """A refusal, said in one line."""


# --------------------------------------------------------------------------- #
# The lock
# --------------------------------------------------------------------------- #


def _files(folder: Path) -> dict[str, dict[str, Any]]:
    """Each file's sha256 and size. A dotfile (a desktop's `.DS_Store`) is
    no dataset file: git does not carry it and nothing reads it."""
    out = {}
    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            raise DataError(f"{path}: a dataset folder holds files only")
        data = path.read_bytes()
        out[path.name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return out


def lock_text(commit: str | None, trial: bool, backend: Path = BACKEND) -> str:
    """The lock for the app's copy as it is on disk now."""
    lock = {
        "repository": REPOSITORY,
        "commit": commit,
        "trial": trial,
        "datasets": {name: {"path": path, "files": _files(backend / path)} for name, path in DATASETS.items()},
    }
    return json.dumps(lock, indent=2) + "\n"


def read_lock(path: Path = LOCK) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def lock_problems(lock: dict[str, Any], backend: Path = BACKEND) -> list[str]:
    """Every way the app's copy differs from `lock`, one line each."""
    out = []
    if lock.get("trial"):
        out.append(f"{LOCK.name}: a trial pin (pin --try); pin a pushed data commit before committing")
    for entry in lock["datasets"].values():
        folder = backend / entry["path"]
        try:
            actual = _files(folder)
        except DataError as error:
            out.append(str(error))
            continue
        locked = entry["files"]
        out += [f"{entry['path']}/{f}: not in the lock" for f in sorted(set(actual) - set(locked))]
        out += [f"{entry['path']}/{f}: missing" for f in sorted(set(locked) - set(actual))]
        out += [f"{entry['path']}/{f}: differs from the lock" for f in sorted(set(actual) & set(locked))
                if actual[f] != locked[f]]
    return out


def pinned(lock: dict[str, Any] | None = None) -> bool:
    """The copy came from a data checkout (a commit, or a trial): it is no
    longer edited in the app tree."""
    lock = lock if lock is not None else read_lock()
    return bool(lock.get("commit") or lock.get("trial"))


# --------------------------------------------------------------------------- #
# Pinning
# --------------------------------------------------------------------------- #


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise DataError(f"{checkout}: git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def pin(checkout: Path, trial: bool = False, backend: Path = BACKEND, lock_path: Path = LOCK) -> list[str]:
    """Copy the checkout's datasets into the app and write the lock. Returns
    the dataset check's problems (a trial copies despite them; a pin refuses)."""
    from scripts.check_datasets import check

    checkout = checkout.resolve()
    commit = _git(checkout, "rev-parse", "HEAD")
    if not trial:
        if _git(checkout, "status", "--porcelain"):
            raise DataError(f"{checkout}: uncommitted changes; commit and push them, or use pin --try")
        if not _git(checkout, "branch", "--remotes", "--contains", commit):
            raise DataError(f"{checkout}: {commit[:12]} is on no remote branch; push it first, so others can fetch it")
    found = check(checkout)
    if found and not trial:
        raise DataError(f"{checkout}: {len(found)} problem(s); run scripts.check_datasets --root {checkout}")
    for name, path in DATASETS.items():
        source, target = checkout / name, backend / path
        files = _files(source)
        for old in target.iterdir():
            if old.is_file() and not old.name.startswith(".") and old.name not in files:
                old.unlink()
        for file in files:
            shutil.copy2(source / file, target / file)
    lock_path.write_text(lock_text(commit, trial, backend), encoding="utf-8")
    return found


def output_dir(dataset: str, out: Path | None, lock: dict[str, Any] | None = None) -> Path:
    """Where a build script writes `dataset`'s files. Until the copy is
    pinned, the app's copy (the default); once pinned, a data checkout
    (`out`, else `DEFAULT_CHECKOUT`), never the app's copy, whose next pin
    would undo the write."""
    app_copy = (BACKEND / DATASETS[dataset]).resolve()
    if out is None and not pinned(lock):
        return app_copy
    root = out if out is not None else DEFAULT_CHECKOUT
    target = (root / dataset).resolve()
    if target == app_copy:
        raise DataError(f"{target}: the app's copy is pinned; write into a data checkout and pin it")
    if not target.is_dir():
        raise DataError(f"{target}: no {dataset}/ folder; pass --out <a roleband-data checkout>")
    return target


def export(target: Path, backend: Path = BACKEND, lock_path: Path = LOCK) -> list[str]:
    """Write the data repository into the empty folder `target`: each
    dataset's locked files under its folder, and the repository's own files.
    Returns the paths written, relative to `target`.

    Only while the copy is unpinned: once the data repository exists it is the
    source, and exporting the app's copy over it would reverse the flow."""
    from scripts.check_datasets import check

    lock = read_lock(lock_path)
    if pinned(lock):
        raise DataError(f"{lock_path.name}: the copy is pinned; the data repository is the source now")
    if target.exists() and any(target.iterdir()):
        raise DataError(f"{target}: not empty; export writes a new repository's first commit")
    if problems := lock_problems(lock, backend):
        raise DataError(f"the app's copy differs from {lock_path.name}: {problems[0]}")
    if backend == BACKEND and (found := check()):
        raise DataError(f"the app's copy has {len(found)} problem(s); run scripts.check_datasets")
    written = []
    for name, entry in lock["datasets"].items():
        for file in entry["files"]:
            (target / name).mkdir(parents=True, exist_ok=True)
            shutil.copy2(backend / entry["path"] / file, target / name / file)
            written.append(f"{name}/{file}")
    for template, path in REPO_FILES.items():
        (target / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES / template, target / path)
        written.append(path)
    return written


#: The help for a build script's `--out`.
OUT_HELP = "a roleband-data checkout to write into; needed once the app's copy is pinned"


def build_target(dataset: str, file: str, out: Path | None, check: bool = False) -> Path:
    """The file a build script writes, or compares against with `--check`.
    A check without `--out` reads the app's copy, which the tests hold; a
    refusal ends the script with its one line."""
    if check and out is None:
        return (BACKEND / DATASETS[dataset] / file).resolve()
    try:
        return output_dir(dataset, out) / file
    except DataError as error:
        raise SystemExit(str(error)) from None


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pin", help="copy a data checkout's datasets into the app and lock them")
    p.add_argument("checkout", type=Path)
    p.add_argument("--try", dest="trial", action="store_true",
                   help="copy the working files as a trial; the lock test fails until a real pin")
    sub.add_parser("lock", help="re-record the app's copy in the lock (only until it is pinned)")
    p = sub.add_parser("export", help="write the data repository's files into an empty folder (only until pinned)")
    p.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            written = export(args.target)
            print(f"{args.target}: {len(written)} files; next: git init, review, one root commit")
            return 0
        if args.command == "lock":
            if LOCK.exists() and pinned():
                raise DataError(f"{LOCK.name}: the copy is pinned to a data commit; edit the data there and pin it")
            LOCK.write_text(lock_text(None, False), encoding="utf-8")
            print(f"{LOCK.name}: recorded the app's copy")
            return 0
        found = pin(args.checkout, trial=args.trial)
    except DataError as error:
        print(error, file=sys.stderr)
        return 1
    for line in found:
        print(line)
    kind = "trial of" if args.trial else "pinned"
    print(f"{LOCK.name}: {kind} {args.checkout} ({len(found)} dataset problem(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
