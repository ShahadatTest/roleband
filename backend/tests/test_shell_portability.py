"""Shell scripts run on two `mktemp`s: BSD on a developer's Mac, GNU in CI.

BSD `mktemp -t name` reads `-t` as a prefix and appends the random part; GNU
reads the argument as a template, finds no X's and refuses ("too few X's in
template"). Such a call passes on every Mac and fails in CI.

The form both accept: no template at all, or a full path template whose last
component carries at least three X's, and never `-t`.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Every shell script a person or CI runs.
SCRIPTS = sorted(
    [
        *REPO.glob("deploy/*.sh"),
        *REPO.glob("backend/scripts/*.sh"),
        REPO / "setup.sh",
    ]
)

_CALL = re.compile(r"(?<![\w-])mktemp\b([^)\n;|&]*)")


def mktemp_problems(text: str) -> list[str]:
    """Each `mktemp` call in `text` that one of BSD or GNU mktemp would refuse."""
    problems = []
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for match in _CALL.finditer(code):
        args = shlex.split(match.group(1), comments=True)
        if "-t" in args:
            problems.append(
                f"{match.group(0).strip()}: -t means a prefix to BSD, a template to GNU"
            )
            continue
        templates = [a for a in args if not a.startswith("-")]
        for template in templates:
            if "XXX" not in template.rsplit("/", 1)[-1]:
                problems.append(f"{match.group(0).strip()}: GNU needs X's in the last component")
    return problems


def test_the_scripts_are_found():
    assert REPO / "deploy" / "restore_db.sh" in SCRIPTS
    assert all(path.is_file() for path in SCRIPTS)


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: str(p.relative_to(REPO)))
def test_every_mktemp_works_on_bsd_and_gnu(path):
    assert mktemp_problems(path.read_text()) == []


@pytest.mark.parametrize(
    "line",
    [
        'RESTORE_ERR="$(mktemp -t roleband_restore_err)"',
        'ERR="$(mktemp -t roleband_restore_err.XXXXXX)"',
        'ERR="$(mktemp /tmp/roleband_restore_err)"',
        'D="$(mktemp -d "${TMPDIR:-/tmp}/XXXXXX/scratch")"',
        '  if true; then E="$(mktemp -t x)"; fi',
    ],
)
def test_a_template_one_mktemp_refuses_is_named(line):
    assert mktemp_problems(line), line


@pytest.mark.parametrize(
    "line",
    [
        'RESTORE_ERR="$(mktemp "${TMPDIR:-/tmp}/roleband_restore_err.XXXXXX")"',
        'BROWSER_LOG="$(mktemp)"',
        'D="$(mktemp -d)"',
        'D="$(mktemp -d "${TMPDIR:-/tmp}/roleband.XXXXXX")"',
        "# not `mktemp -t prefix`: BSD reads -t as a prefix",
    ],
)
def test_a_portable_call_passes(line):
    assert mktemp_problems(line) == []
