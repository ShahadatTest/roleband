"""The project is RoleBand everywhere.

`scripts/check_project_name.py` is the check; CI also runs it without a path
filter (`.github/workflows/hygiene.yml`), because a dashboard-only change must
not skip a whole-tree rule.
"""

from __future__ import annotations

from scripts.check_project_name import OLD_NAME, check, scan

# The pre-release name as people wrote it, built so this file never matches itself.
DISPLAY = "New" + "Life"


def _reader(files: dict[str, str | None]):
    return files.get


def test_the_tree_never_carries_the_old_name():
    hits = check()
    assert hits == [], "the old name is back:\n" + "\n".join(hits)


def test_any_casing_is_found_and_named_by_line():
    files = {
        "a.py": "x = 1\ny = 'Welcome to " + DISPLAY + "'\n",
        "b.sh": "export " + OLD_NAME.upper() + "_PGDATA=/tmp\n",
        "c.ts": "const k = '" + OLD_NAME + ".locale';\n",
        "d.md": "RoleBand only\n",
    }
    assert scan(files, _reader(files)) == ["a.py:2", "b.sh:1", "c.ts:1"]


def test_a_path_named_with_the_old_name_is_a_hit_even_when_unreadable():
    path = "deploy/com." + OLD_NAME + ".api.plist.template"
    files = {path: None}
    assert scan(files, _reader(files)) == [f"{path}: the path itself"]
