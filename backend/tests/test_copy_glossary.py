"""The product language, held on the text the backend writes for a person
(docs/copy.md; docs/copy.md "a backend twin").

The rules are the dashboard's (`dashboard/src/copy/en/glossary.yaml`), read
from the copy `npm run gen:copy` writes to `tests/fixtures/copy_glossary.gen.json`;
the dashboard suite fails when that copy is stale, so one rule set serves both.
Generated catalog text is checked at its FTL source, with as-is wording advisory.

Scanned: every prose string literal (plain or f-string) in the notification
classifier and renderer and in the macOS banner producers. Docstrings and
logging and command-line help are not app display text. Violations are named in
`tests/fixtures/copy_glossary_baseline.json` and only shrink: a new one fails,
and a fixed one leaves the list in the same change.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = json.loads((ROOT / "tests/fixtures/copy_glossary.gen.json").read_text())
BASELINE_PATH = ROOT / "tests/fixtures/copy_glossary_baseline.json"

#: The person-facing writers: notifications, and the banners (`osnotify` callers).
SCANNED = sorted(
    [p for p in (ROOT / "tracker/notifications").glob("*.py") if p.name != "catalog_gen.py"]
    + [ROOT / p for p in ("tracker/osnotify.py", "tracker/workflows/daily.py",
                          "tracker/workflows/watchdog.py", "tracker/semantic/backfill.py")]
)
#: Calls whose strings no person reads in the app: logging and command-line help.
_NOT_READ = {"debug", "info", "warning", "error", "exception", "critical", "log",
             "add_argument", "ArgumentParser", "add_parser", "add_subparsers"}


def _pattern(words: list[str]) -> re.Pattern[str]:
    """A word with its inflections, hyphen or space as a joiner (the dashboard's rule)."""
    forms = []
    for w in words:
        *head, last = [re.escape(p) for p in w.split()]
        stem = last.removesuffix("e")
        tails = f"(?:{last}(?:s|es|d|ed|r|rs|er|ers)?|{stem}ing|{stem}ings)"
        forms.append(r"[\s-]+".join([*head, tails]))
    return re.compile(rf"(?<![^\W\d_])({'|'.join(forms)})(?![^\W\d_])", re.IGNORECASE)


VOCAB = _pattern([*GLOSSARY["banned"], *GLOSSARY["retired"]])


def problems(text: str) -> list[str]:
    vocabulary_text = text
    for phrase in GLOSSARY["allowed_phrases"]:
        vocabulary_text = vocabulary_text.replace(phrase, " ")
    found = []
    if hit := VOCAB.search(vocabulary_text):
        found.append(f"vocabulary:{hit.group(1).lower()}")
    for bad in GLOSSARY["forbid"]:
        if bad in text:
            found.append("mechanics:" + ("em-dash" if bad == "—" else bad))
    for long, short in GLOSSARY["contractions"].items():
        if re.search(rf"\b{re.escape(long)}\b", text):
            found.append(f"mechanics:{long} -> {short}")
    return found


def _strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    skip: set[int] = set()
    for node in ast.walk(tree):
        name = node.func.attr if isinstance(getattr(node, "func", None), ast.Attribute) else getattr(getattr(node, "func", None), "id", None)
        if isinstance(node, ast.Call) and name in _NOT_READ:
            skip.update(id(n) for n in ast.walk(node))
    out = []
    for node in ast.walk(tree):
        if id(node) in docstrings or id(node) in skip:
            continue
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
            skip.update(id(v) for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        words = re.sub(r"\{[^}]*\}", " ", text)
        if re.match(r"\s*(SELECT|UPDATE|INSERT|DELETE|WITH|DO \$\$)\b", text):
            continue  # SQL, not text
        if re.search(r"[A-Za-z]{2,}", words) and " " in words.strip():
            out.append(" ".join(text.split()))
    return out


def scan() -> list[str]:
    found = set()
    for path in SCANNED:
        rel = path.relative_to(ROOT).as_posix()
        for text in _strings(path):
            for problem in problems(text):
                found.add(f"{problem}|{rel}|{text}")
    return sorted(found)


def test_the_glossary_copy_is_the_dashboards_rule_set():
    assert {"scrape", "sync", "scope"} <= set(GLOSSARY["banned"])
    assert "—" in GLOSSARY["forbid"] and "Could not" in GLOSSARY["contractions"]


def test_backend_text_adds_no_banned_word_or_mechanics_problem():
    baseline = json.loads(BASELINE_PATH.read_text())
    now = scan()
    fresh = [p for p in now if p not in baseline]
    fixed = [p for p in baseline if p not in now]
    assert not fresh, "new problems in text the backend writes for a person:\n" + "\n".join(fresh)
    assert not fixed, "fixed, so remove from copy_glossary_baseline.json:\n" + "\n".join(fixed)


def test_the_rules_catch_what_they_claim():
    for bad in ("Daily scrape finished with errors", "Still scraping", "re-sync now",
                "Couldn't scan — nothing was updated", "Could not reach it"):
        assert problems(bad), bad
    for good in ("Apple closed a role you saved", "Scanning 12 companies", "Apple Intelligence is ready"):
        assert problems(good) == [], good
    assert "tracker/notifications/events.py" in {p.relative_to(ROOT).as_posix() for p in SCANNED}
