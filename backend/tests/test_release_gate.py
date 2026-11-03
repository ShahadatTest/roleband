"""Release gate: the core names neither outside pay source.

The two pay sources are plugins in their own repositories. Three scans over
every file the repository carries must find nothing of them:

- **content**: a vendor's name or domain, in any casing or regex escape;
- **paths**: a file named after one;
- **identifiers**: the name as a word or identifier part. One of the names is
  also an English word, so `vendor_names.vendor_word` reads each hit (the
  lowercase word in prose is English; a quoted value or a capitalised name is
  the vendor).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests import vendor_names

ROOT = Path(__file__).resolve().parents[2]


def _files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode()
    return sorted(p for p in out.split("\0") if p and (ROOT / p).is_file())


def _text(path: str) -> str | None:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # a binary file names nothing a reader sees


def _hits(path: str, text: str) -> list[tuple[int, str]]:
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        if vendor_names.CONTENT.search(line) or any(
            vendor_names.vendor_word(line, m) for m in vendor_names.IDENTIFIER.finditer(line)
        ):
            found.append((n, line.strip()[:120]))
    return found


def test_no_file_names_an_outside_pay_source():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout: the gate reads the tracked file list")
    found = {}
    for path in _files():
        text = _text(path)
        if text is not None and (hits := _hits(path, text)):
            found[path] = hits
    assert found == {}, "name the source neutrally (a plugin, an outside pay source)"


def test_no_tracked_path_names_an_outside_pay_source():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    named = [p for p in _files() if vendor_names.PATH.search(p)]
    assert named == []


@pytest.mark.parametrize("kind", ["content", "identifier", "quoted"])
def test_the_scans_see_a_planted_name(kind):
    assert _hits("x.py", vendor_names.planted(kind)), kind


def test_the_identifier_scan_leaves_the_english_word_alone():
    assert _hits("x.py", vendor_names.planted("english")) == []
    word = vendor_names.planted("english").split()[3]
    assert _hits("x.md", f"The scan is location-{word}, and a {word} spot.") == []


def test_the_path_scan_sees_a_planted_path():
    assert vendor_names.PATH.search(vendor_names.planted("path"))
