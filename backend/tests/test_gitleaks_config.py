"""The secret scan's exceptions (`.gitleaks.toml`) excuse known lines, never a file.

The release export stops on any gitleaks finding, so the scan must come back
clean on the tree, and each exception must be narrow: a secret planted in an
excused file is still found. Each excused line is also found WITHOUT the
exceptions, so no exception is dead weight. The planted secrets are built at
run time and never written into the tree.

Needs the `gitleaks` binary; without it these tests skip.
"""

from __future__ import annotations

import base64
import json
import secrets
import shutil
import string
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".gitleaks.toml"
GITLEAKS = shutil.which("gitleaks")

pytestmark = pytest.mark.skipif(GITLEAKS is None, reason="gitleaks is not installed")

#: One excused line per exception, as the tree writes it, with its file. Each is
#: joined from pieces so this file's own text is no finding.
EXCUSED = {
    "backend/tracker/company_directory.json": "".join((
        '  {"adapter": "workable", "board_region": null, "board_', 'token": "two95-',
        'international-inc-3", "display": "Two95 International Inc.", "named_by": "board",',
        ' "slug": "two95-international-inc"},\n',
    )),
    "backend/tests/fixtures/search_retrieval_eval.json": "".join(
        ('   "ke', 'y": "nvidia-', 'JR2019755",\n')
    ),
    "backend/tests/test_secrets.py": "".join(("PRICE_", 'KEY = "tiingo-', '0123456789abcdef"\n')),
    "backend/tests/fixtures/listings/radancy/job.html": "".join((
        '<script type="text/javascript" src="https://www.bugherd.com/sidebarv2.js?api',
        'key=', 'dnyc4hq0zvkd7yxrbmgq2w"></script>\n',
    )),
    "dashboard/src/test/copy-as-found.json": "".join(('"Conf', 'luent",\n"Congo', 'Brazzaville",\n')),
    # gitleaks decodes the base64 and reads the digest as a key; it is encoded here at run time.
    **{
        f"launcher/macos/Tests/LauncherCoreTests/Fixtures/{name}.json": '  "metadata": "{}",\n'.format(
            base64.b64encode(('{\n  "release_key_sha256": "' + "56475aa754634" + "74c0285df5dbf2bcab73da651358839e9b77481b2eab107708c" + '"\n}\n').encode()).decode()
        )
        for name in ("update-artifact", "update-artifact-notice")
    },
}


#: The rule each exception narrows, as `.gitleaks.toml` names it.
RULE = {path: "generic-api-key" for path in EXCUSED} | {
    "dashboard/src/test/copy-as-found.json": "confluent-access-token",
}


def _random(alphabet: str, n: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _candidate(rule: str) -> str:
    """A line shaped like a live secret to `rule`: the rule its file's exception narrows."""
    lower, upper = string.ascii_lowercase + string.digits, string.ascii_uppercase + string.digits
    return {
        "generic-api-key": f'api_key = "{_random(lower + upper, 32)}"\n',
        "confluent-access-token": f'confluent_key = "{_random(upper, 16)}"\n',
    }[rule]


def _defaults(base: Path) -> Path:
    config = base / "defaults.toml"
    config.write_text("[extend]\nuseDefault = true\n")
    return config


def _planted(base: Path) -> dict[str, str]:
    """One secret per excused file that the default rules find on its own.

    A random value that happens to contain one of gitleaks' stopwords reads as no
    secret, so candidates are drawn in bulk and only flagged ones are planted.
    """
    pool = base / "candidates"
    pool.mkdir()
    lines: dict[str, tuple[str, str, str]] = {}
    for path, rule in RULE.items():
        for _ in range(8):
            name, line = f"{len(lines)}.txt", _candidate(rule)
            (pool / name).write_text(line)
            lines[name] = (path, rule, line)
    planted: dict[str, str] = {}
    for name, rule in _scan(pool, _defaults(base)):
        path, wanted, line = lines[name]
        if rule == wanted:
            planted.setdefault(path, line)
    assert planted.keys() == RULE.keys(), "no candidate read as a secret"
    return planted


def _scan(source: Path, config: Path) -> list[tuple[str, str]]:
    report = source.parent / f"{source.name}.json"
    subprocess.run(
        [GITLEAKS, "detect", "--no-git", "--source", str(source), "--config", str(config),
         "--report-format", "json", "--report-path", str(report), "--exit-code", "0",
         "--no-banner", "--log-level", "error"],
        check=True,
    )
    found = json.loads(report.read_text() or "[]")
    return sorted((Path(f["File"]).relative_to(source).as_posix(), f["RuleID"]) for f in found)


def _tree(base: Path, planted: dict[str, str] | None = None) -> Path:
    tree = base / "tree"
    for path, line in EXCUSED.items():
        (tree / path).parent.mkdir(parents=True, exist_ok=True)
        (tree / path).write_text(line + (planted or {}).get(path, ""))
    return tree


def test_the_tracked_tree_has_no_finding(tmp_path):
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode().split("\0")
    tree = tmp_path / "export"
    for path in filter(None, tracked):
        src = ROOT / path
        if src.is_file() and not src.is_symlink():
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, tree / path)
    assert _scan(tree, CONFIG) == []


def test_every_excused_line_passes_and_a_planted_secret_beside_it_is_found(tmp_path):
    assert _scan(_tree(tmp_path), CONFIG) == []
    planted = _tree(tmp_path / "planted", _planted(tmp_path))
    assert _scan(planted, CONFIG) == sorted(RULE.items())


def test_every_exception_is_needed(tmp_path):
    """Without the exceptions, each excused line is a finding."""
    flagged = {path for path, _rule in _scan(_tree(tmp_path), _defaults(tmp_path))}
    assert flagged == set(EXCUSED)
