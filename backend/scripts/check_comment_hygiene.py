"""Comments say what the code cannot, and stay true: no process, people or dates.

Usage (from anywhere inside the checkout):
    python backend/scripts/check_comment_hygiene.py

Reads only commentary: Python comments and docstrings, JS/TS/CSS comments, `#`
comments in FTL, shell, YAML and TOML files, and the `note` column of CSV data.
Code and string literals are never read. Each line is checked against the rules
in `RULES` (the reasons are in AGENTS.md, "Comments"), and every file must be
clean. A line that genuinely needs a flagged form carries `hygiene: allow` and
its reason.

Standard library only, so CI runs it without installing anything
(`.github/workflows/hygiene.yml`); `tests/test_comment_hygiene.py` runs the same
check inside pytest.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ALLOW = "hygiene: allow"

#: Generated or copied text this project does not write.
SKIP_PREFIXES = (
    "backend/tests/fixtures/",
    "dashboard/src/copy/gen/",
    "dashboard/src/test/cycle-fixture/",
)
SKIP_FILES = frozenset({"dashboard/src/api.gen.ts"})

#: Vendored snapshots keep upstream's own comments.
VENDORED_REGISTRY = "backend/tracker/vendored.py"

_JS = (".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx")
_HASH = (".sh", ".yml", ".yaml", ".toml", ".ftl", ".cfg", ".ini")

# Commentary text is checked case-insensitively except where a rule says otherwise.
_I = re.IGNORECASE

#: rule -> patterns. A line breaks a rule when any of its patterns matches.
RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    # A person deciding, instead of the reason they decided.
    "owner": (
        re.compile(
            r"\bowner'?s?\s+(?:decision|decided|call|verdict|asked|said|chose|ruled|"
            r"wants?|wanted|approved|approval|order|screenshot|case|picks?|picked|brief|"
            r"correction|request|choice|reversal|rejected|confirmed|agreed)\b", _I),
        re.compile(r"\(\s*owner\b", _I),
        re.compile(r"\bowner,?\s+20\d\d", _I),
        re.compile(r"\bthe owner\s+(?:has\s+)?(?:decided|asked|said|chose|ruled|wants?|"
                   r"wanted|approved|placed|picked|rejected|confirmed|agreed|accepted)\b", _I),
    ),
    # Pointers into a process: plans, reviews, phases, cohorts, decision IDs.
    "process-id": (
        re.compile(r"\breview\s*#\s*\d+", _I),
        re.compile(r"\b(?:plan|review|audit|handover|handoff|proposal|roadmap)\s+"
                   r"(?:item\s+)?[A-Z]{1,2}\d+(?:\.\d+)*[a-z]?\b"),
        re.compile(r"\breview\s+\d+\.\d+", _I),
        re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)*-(?:plan|review|audit|proposal|handover)\b", _I),
        re.compile(r"\b[\w-]+\s+plan\s+(?:§|[A-Z]\d)"),
        re.compile(r"\b(?:plan|review|audit|proposal|roadmap)\s+§"),
        re.compile(r"\b(?:cohort|slice|wave|batch)\s+[A-Z0-9][\w.]*\b"),
        re.compile(r"\b(?:phase|stage)\s+\d+[A-Za-z]?\b", _I),
        # A bare decision ID in parentheses: (D7), (R6, F3), (W1a). Level codes  hygiene: allow (examples)
        # (E, I, L, M, P: E6, IC4, L5, M3, P5) are not decision IDs.
        re.compile(r"\(\s*[ABCDFGHJKNOQRSTUVWXYZ]\d{1,2}[a-z]?"
                   r"(?:\s*[,/;]\s*(?:[A-Z]\d{1,2}[a-z]?|\d+))*\s*\)"),
    ),
    # A section of a document the reader cannot open.
    "section-mark": (re.compile(r"§"),),
    # A date as evidence or status; it ages, and the sentence stays.
    "dated": (re.compile(r"(?<![\w`/.-])20\d\d-[01]\d(?:-[0-3]\d)?(?![\w`])"),),
    # Facts about one copy of live data.
    "aging-evidence": (
        re.compile(r"\bfound live\b", _I),
        re.compile(r"\bas of 20\d\d", _I),
        re.compile(r"\bmeasured\s+(?:on|at|in)\s+(?:20\d\d|the live|production|main)\b", _I),
        re.compile(r"\b(?:on|in) the live (?:db|database|data|corpus)\b", _I),
        re.compile(r"\bat the time of writing\b", _I),
    ),
    # What the code was before. Left out because the product says them about
    # data: "no longer" (a board stopped listing a posting), and a posting that
    # was removed, deleted or replaced. A bare "used to" mostly states a purpose
    # ("the key used to sign"), so the form caught is "used to be". hygiene: allow (names it)
    "history": (
        re.compile(r"\b(?:used to be|previously|formerly|until recently)\b", _I),
        re.compile(r"\b(?:was|were)\s+(?:renamed|moved|retired)\b", _I),
    ),
    # One machine's home directory. Case-sensitive: macOS capitalises it, and the
    # lowercase segment is a route or a URL path.
    "personal": (re.compile(r"/Users/"),),
}

#: `§` is fine after an RFC, a document the tree has, or on a line that carries
#: the URL of what it cites.
_SECTION_OK = re.compile(r"RFC\s*\d+|docs/[\w./-]+\.md|`[^`]*§[^`]*`|https?://", _I)
#: Alembic's generated header names its own creation date.
_ALEMBIC_HEADER = re.compile(r"^\s*(?:Create Date|Revision ID|Revises)\s*:")


# --- extraction: (line number, text) for every line of commentary -----------------

def python_commentary(source: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.string))
        tree = ast.parse(source)
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return out
    nodes = [tree, *(n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))]
    for node in nodes:
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            first = body[0].lineno
            for offset, line in enumerate(body[0].value.value.splitlines()):
                out.append((first + offset, line))
    return sorted(out)


_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")


def _skip_quoted(source: str, i: int) -> int:
    """Index just past the '...' or "..." string starting at `i` (or at its line end)."""
    quote, j, n = source[i], i + 1, len(source)
    while j < n and source[j] not in (quote, "\n"):
        j += 2 if source[j] == "\\" else 1
    return j + 1 if j < n and source[j] == quote else j


def _skip_template(source: str, i: int) -> int:
    """Index just past the template literal starting at `i`, `${...}` parts included."""
    j, n = i + 1, len(source)
    while j < n:
        ch = source[j]
        if ch == "\\":
            j += 2
        elif ch == "`":
            return j + 1
        elif ch == "$" and source[j + 1:j + 2] == "{":
            j, depth = j + 2, 1
            while j < n and depth:
                ch = source[j]
                if ch in "'\"":
                    j = _skip_quoted(source, j)
                    continue
                if ch == "`":
                    j = _skip_template(source, j)
                    continue
                depth += {"{": 1, "}": -1}.get(ch, 0)
                j += 1
        else:
            j += 1
    return n


def _skip_regex(source: str, i: int) -> int:
    j, n, in_class = i + 1, len(source), False
    while j < n and source[j] != "\n":
        ch = source[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return j + 1
        j += 1
    return j


def js_commentary(source: str, css: bool = False) -> list[tuple[int, str]]:
    """Comments in JS/TS/CSS, skipping strings, template literals and regex literals."""
    out: list[tuple[int, str]] = []
    i, n = 0, len(source)
    last_code = ""  # last non-space code character, to tell a regex from a division
    while i < n:
        c, nxt = source[i], source[i + 1:i + 2]
        if not css and c == "/" and nxt == "/":
            end = source.find("\n", i)
            end = n if end == -1 else end
            out.append((source.count("\n", 0, i) + 1, source[i + 2:end]))
            i = end
        elif c == "/" and nxt == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end
            first = source.count("\n", 0, i) + 1
            out.extend((first + k, part) for k, part in enumerate(source[i + 2:end].split("\n")))
            i = end + 2
        elif c in "'\"":
            i, last_code = _skip_quoted(source, i), c
        elif c == "`" and not css:
            i, last_code = _skip_template(source, i), c
        elif c == "/" and not css and (last_code == "" or last_code in _REGEX_BEFORE):
            i, last_code = _skip_regex(source, i), "/"
        else:
            if not c.isspace():
                last_code = c
            i += 1
    return out


def hash_commentary(source: str, ftl: bool = False) -> list[tuple[int, str]]:
    out = []
    for number, text in enumerate(source.splitlines(), 1):
        stripped = text.lstrip()
        if stripped.startswith("#"):
            out.append((number, stripped.lstrip("#")))
        elif not ftl and " #" in text and text.count('"') % 2 == 0 and text.count("'") % 2 == 0:
            out.append((number, text[text.index(" #") + 2:]))
    return out


def csv_commentary(source: str) -> list[tuple[int, str]]:
    rows = list(csv.reader(io.StringIO(source)))
    if not rows or not any(h in ("note", "notes") for h in rows[0]):
        return []
    cols = [k for k, h in enumerate(rows[0]) if h in ("note", "notes")]
    return [(number, row[k]) for number, row in enumerate(rows[1:], 2)
            for k in cols if k < len(row) and row[k]]


def commentary(path: str, source: str) -> list[tuple[int, str]]:
    if path.endswith(".py"):
        return python_commentary(source)
    if path.endswith(_JS):
        return js_commentary(source)
    if path.endswith(".css"):
        return js_commentary(source, css=True)
    if path.endswith(".ftl"):
        return hash_commentary(source, ftl=True)
    if path.endswith(_HASH) or path.endswith(".gitignore"):
        return hash_commentary(source)
    if path.endswith(".csv"):
        return csv_commentary(source)
    return []


# --- rules -------------------------------------------------------------------------

def broken_rules(text: str) -> list[str]:
    if ALLOW in text or _ALEMBIC_HEADER.match(text):
        return []
    hits = []
    for rule, patterns in RULES.items():
        if rule == "section-mark":
            if "§" in text and not _SECTION_OK.search(text):
                hits.append(rule)
        elif any(p.search(text) for p in patterns):
            hits.append(rule)
    return hits


def scan_file(path: str, source: str) -> dict[str, list[int]]:
    """rule -> line numbers that break it."""
    found: dict[str, list[int]] = {}
    for number, text in commentary(path, source):
        for rule in broken_rules(text):
            found.setdefault(rule, []).append(number)
    return found


# --- tree --------------------------------------------------------------------------

def repo_root(start: Path | None = None) -> Path:
    here = start or Path(__file__).resolve().parent
    out = subprocess.run(["git", "-C", str(here), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def tracked_files(root: Path) -> list[str]:
    """Tracked files plus new ones not yet added, so a file is checked before its commit."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, check=True)
    return sorted({p for p in out.stdout.decode("utf-8").split("\0") if p and (root / p).is_file()})


def vendored_files(root: Path) -> set[str]:
    registry = root / VENDORED_REGISTRY
    if not registry.exists():
        return set()
    return set(re.findall(r'local_path="([^"]+)"', registry.read_text(encoding="utf-8")))


def scan_tree(root: Path) -> dict[str, dict[str, list[int]]]:
    result: dict[str, dict[str, list[int]]] = {}
    skip = SKIP_FILES | vendored_files(root)
    for path in tracked_files(root):
        if path in skip or path.startswith(SKIP_PREFIXES):
            continue
        try:
            source = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        found = scan_file(path, source)
        if found:
            result[path] = found
    return result


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    scan = scan_tree(repo_root())
    if not scan:
        return 0
    print("Commentary breaks the rules in AGENTS.md, 'Comments':")
    for path, rules in scan.items():
        for rule, lines in sorted(rules.items()):
            print(f"  {path}: {rule}: lines {', '.join(str(n) for n in lines)}")
    print("Rewrite the comment to say only what stays true, or mark a genuine "
          f"exception with '{ALLOW}' and its reason.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
