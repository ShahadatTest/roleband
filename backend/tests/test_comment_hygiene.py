"""Commentary follows AGENTS.md, "Comments".

`scripts/check_comment_hygiene.py` is the check; CI also runs it without a path
filter (`.github/workflows/hygiene.yml`). The tests below pin each rule to the
forms it must catch and to the look-alikes it must leave alone.
"""

from __future__ import annotations

import pytest

from scripts.check_comment_hygiene import (
    RULES,
    broken_rules,
    commentary,
    repo_root,
    scan_file,
    scan_tree,
)


def test_the_tree_breaks_no_rule():
    found = scan_tree(repo_root())
    assert found == {}, "commentary breaks AGENTS.md 'Comments':\n" + "\n".join(
        f"{p}: {r}: lines {lines}" for p, rules in found.items() for r, lines in rules.items())


# --- each rule catches its forms ---------------------------------------------------

@pytest.mark.parametrize(("text", "rule"), [
    ("Robots gate on consent (owner decision 2026-09-21).", "owner"),
    ("A firm's rank (owner Q2): read anywhere", "owner"),
    ("the owner decided the other way", "owner"),
    ("Owner approved the ladder.", "owner"),
    ("see review #38", "process-id"),
    ("Moved out of pipeline.py (R7).", "process-id"),
    ("Settles plan A3 and P10 together", "process-id"),
    ("as the scraping-platform-plan says", "process-id"),
    ("schemas move in cohort D1", "process-id"),
    ("Phase 4 dissolved the tier", "process-id"),
    ("the decision tree of §5.5", "section-mark"),
    ("Measured 2026-09-10: the EU host answers", "dated"),
    ("Found live: three companies had none", "aging-evidence"),
    ("Measured on the live corpus: 34 bindings", "aging-evidence"),
    ("as of 2026, every board", "aging-evidence"),
    ("the dial used to be the other way", "history"),
    ("this column was renamed", "history"),
    ("the URL is /Users/someone/db", "personal"),
])
def test_a_rule_catches_its_form(text, rule):
    assert rule in broken_rules(text)


# --- and leaves the look-alikes alone ----------------------------------------------

@pytest.mark.parametrize("text", [
    "Amazon's L5 and Meta's E6 are the same band; IC4 and M3 too; Atlassian's P5.",
    "a rung code such as (L6) or (E5) is a level, not a decision",
    "RFC 9309 §2.2.1: the longest match wins",
    "the read owner of this table is the API",
    "the data owner column lists writers and readers",
    "a stage in the pursuit (applied, interviewing)",
    "dates look like `2026-01-31` in the API",
    "an ISO date such as `YYYY-MM-DD`",
    "the measured bonus ratio wins over the policy",
    "a quoted example 2026-01-31 hygiene: allow (date format in the API)",
    "Every company needs a source binding; without one, closure skips the gate.",
    "a posting the board no longer lists is closed once a complete read confirms it",
])
def test_a_look_alike_is_left_alone(text):
    assert broken_rules(text) == []


# --- the narrow rules: the form still caught beside the look-alike now freed --------

@pytest.mark.parametrize(("caught", "freed", "rule"), [
    ("the dial used to be the other way", "the key used to sign a request", "history"),
    ("the helper was moved to utils", "a posting that was removed from the board stays closed",
     "history"),
    ("these columns were renamed", "rows that were deleted by the user are never shown",
     "history"),
    ("the parser was retired", "a figure that was replaced by the company's own wins", "history"),
    ("the header grammar is in §4.2", "the header grammar is in §4.2 of https://example.org/spec",
     "section-mark"),
    ("the data lives in /Users/someone/db", "GET /users/me answers with the profile", "personal"),
])
def test_a_narrow_rule_keeps_its_form_and_frees_its_look_alike(caught, freed, rule):
    assert rule in broken_rules(caught)
    assert broken_rules(freed) == []


def test_the_personal_rule_names_nobody():
    """The check ships with the tree, so a login in its pattern would publish it."""
    assert [p.pattern for p in RULES["personal"]] == ["/Users/"]


def test_alembic_header_dates_are_left_alone():
    assert broken_rules("Create Date: 2026-10-12 09:00:00") == []


# --- only commentary is read -------------------------------------------------------

def test_python_reads_comments_and_docstrings_never_strings():
    source = (
        '"""Module doc (owner decision)."""\n'
        'X = "owner decision 2026-01-01"  # set in review #4\n'
        'def f():\n'
        '    """Function doc, used to be different."""\n'
        '    return "§1"\n'
    )
    found = scan_file("m.py", source)
    assert found == {"owner": [1], "process-id": [2], "history": [4]}


def test_ts_reads_comments_never_strings_templates_or_regexes():
    source = (
        'const glob = "**/api/**";  // fine\n'
        "const t = `/* not a comment ${x // y} */`;\n"
        "const r = /\\/* still code/;\n"
        "/* (R7) a real block\n"
        "   comment */\n"
        "// owner decision\n"
    )
    found = scan_file("a.ts", source)
    assert found == {"process-id": [4], "owner": [6]}


def test_css_and_ftl_and_csv_notes_are_read():
    css = 'a { content: "/* no */"; } /* used to be blue */\n'
    ftl = "# note=\"plan §6.7\"\nkey = owner decision is the words here\n"
    data = "company,note\nacme,ordered 2026-10-09 (atlas batch 2)\n"
    assert scan_file("s.css", css) == {"history": [1]}
    assert scan_file("m.ftl", ftl) == {"process-id": [1], "section-mark": [1]}
    assert scan_file("d.csv", data) == {"process-id": [2], "dated": [2]}


def test_markdown_and_json_are_not_commentary():
    assert commentary("README.md", "owner decision 2026-01-01") == []
    assert commentary("x.json", '{"why": "owner decision"}') == []
