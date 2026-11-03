"""The project is RoleBand: no tracked file names the pre-release name.

Usage (from anywhere inside the checkout):
    python backend/scripts/check_project_name.py

Exits 1 naming every `path:line` that carries the old name and every tracked
path whose name carries it. Standard library only, so CI runs it without
installing anything (`.github/workflows/hygiene.yml`);
`tests/test_project_name.py` runs the same check inside pytest.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

#: Built from two halves so this file never matches itself.
OLD_NAME = "new" + "life"


def repo_root(start: Path | None = None) -> Path:
    here = start or Path(__file__).resolve().parent
    out = subprocess.run(
        ["git", "-C", str(here), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return Path(out.stdout.strip())


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True,
    )
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def find_old_name(path: str, text: str) -> list[str]:
    """Every `path:line` in `text` that carries the old name, any casing."""
    return [
        f"{path}:{number}"
        for number, line in enumerate(text.splitlines(), start=1)
        if OLD_NAME in line.lower()
    ]


def scan(paths: Iterable[str], read: Callable[[str], str | None]) -> list[str]:
    """Every hit, in path order.

    `read` returns a file's text, or None for a file that is not text. A path
    whose NAME carries the old name is a hit however it reads.
    """
    hits: list[str] = []
    for path in paths:
        if OLD_NAME in path.lower():
            hits.append(f"{path}: the path itself")
        text = read(path)
        if text is not None:
            hits.extend(find_old_name(path, text))
    return hits


def _reader(root: Path) -> Callable[[str], str | None]:
    def read(path: str) -> str | None:
        try:
            return (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            return None
    return read


def check(root: Path | None = None) -> list[str]:
    root = root or repo_root()
    return scan(tracked_files(root), _reader(root))


def main() -> int:
    hits = check()
    for hit in hits:
        print(f"old name: {hit}")
    if hits:
        return 1
    print("project name: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
