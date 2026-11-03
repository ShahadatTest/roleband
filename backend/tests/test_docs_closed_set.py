"""The documentation is a closed set, and the tree cites only what exists.

`docs/` holds the documents listed here and nothing else. Plans, audits, reviews
and handovers belong in issues, never in the tree: a document missing from this
list fails here, so adding one is a reviewed edit to the list. Two families are
open by file-name shape: decision records under `docs/decisions/`, and images
under `docs/images/` (the README's screenshots). An image must be referenced by a
tracked Markdown file and stay under `IMAGE_MAX_BYTES`: history keeps every
replaced copy for good.

Three more checks keep the tree from pointing at things that are gone: no file
cites a decision-log entry, every `docs/...` path a file names exists, and every
file path a document names is one the repository tracks.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

ROOT_DOCS = frozenset({
    "AGENTS.md", "CHANGELOG.md", "CLAUDE.md", "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md", "README.md", "SECURITY.md", "SUPPORT.md",
})

DOCS = frozenset({
    "docs/architecture.md",
    "docs/copy.md",
    "docs/decisions/0000-template.md",
    "docs/development.md",
    "docs/field-authority.md",
    "docs/mcp.md",
    "docs/pay.md",
    "docs/plugins.md",
    "docs/sources.md",
    "docs/testing.md",
    "docs/third-party.md",
    "docs/ui.md",
    "docs/usage-data.md",
})

_DECISION = re.compile(r"docs/decisions/\d{4}-[a-z0-9-]+\.md")
_IMAGE = re.compile(r"docs/images/[a-z0-9-]+\.(?:webp|png|svg)")
#: An image named in Markdown: `docs/images/board.webp`, `images/board.webp`, `../docs/images/x.png`.
_IMAGE_CITE = re.compile(r"(?<![\w-])((?:\.{1,2}/)*(?:docs/)?images/[a-z0-9-]+\.(?:webp|png|svg))")
IMAGE_MAX_BYTES = 300 * 1024

#: Assembled so this file never matches its own pattern.
_LOG_REF = re.compile(r"\b" + "IMPL" + r"-\d+")
#: Any Markdown file named in text: `docs/ui.md`, `../SECURITY.md`, a bare `vocabulary.md`.
_MD_CITE = re.compile(r"(?<![\w./:-])((?:\.{1,2}/)*[A-Za-z0-9_][\w./-]*\.md)\b")

#: Files that name Markdown files which do not exist, on purpose: tests that build
#: fake paths as fixtures for their own checks, and the decision-record template's
#: naming pattern.
_FAKE_PATH_FIXTURES = frozenset({
    "backend/tests/test_docs_closed_set.py",
    "backend/tests/test_project_name.py",
    "backend/tests/test_release_gate.py",
    "docs/decisions/0000-template.md",
})
#: The data repository's own files, kept here until it exists: their citations
#: resolve in that repository (`test_the_data_repository_s_files_cite_what_it_holds`).
_OTHER_REPOSITORY = "backend/scripts/data_repo/"

#: Path-shaped tokens anywhere in a document. Scanning the raw text needs no
#: backtick pairing, and a path-shaped token in a technical doc IS a claim about
#: a path wherever it appears, including inside a command. A file extension is
#: required, which separates a path from an HTTP route (`GET /api/jobs`) and a
#: diagram label (`workflows/pipeline`). `tsx` is tried before `ts` and the
#: extension ends at a word boundary, so `Content.tsx` is not read as
#: `Content.ts`, and `cities.tsv` is no claim at all.
_DOC_PATH = re.compile(
    r"(?:\.github/|backend/|dashboard/|docs/|tests/|tracker/|deploy/|scripts/"
    r"|db/|workflows/|semantic/|skills/|analytics/|connectors/|api/|comp_providers/|taxonomy/)"
    r"[A-Za-z0-9_./-]+\.(?:py|tsx|ts|md|toml|json|sh|css|yml|yaml|ini|js|mjs|sql)\b"
)

#: A path is written from wherever a contributor would type it, so it resolves
#: against the repository root, `backend/`, `backend/tracker/` or `dashboard/`.
_PATH_ROOTS = ("", "backend", "backend/tracker", "dashboard")

#: Named on purpose although no clone tracks it: a test run creates it.
_UNTRACKED_BY_DESIGN = frozenset({"dashboard/test-results/results.json"})

#: The decision-record template names a pattern, not a file.
_PATH_CHECK_EXEMPT = frozenset({"docs/decisions/0000-template.md"})

_PATH_CHECKED = sorted(
    ((DOCS | ROOT_DOCS) - _PATH_CHECK_EXEMPT)
    | {p.relative_to(ROOT).as_posix() for p in (ROOT / "docs" / "decisions").glob("*.md")}
    - _PATH_CHECK_EXEMPT
)

_TOOLING_DIRS = (".claude", ".codex", ".agents")

_TEXT = (".md", ".py", ".ts", ".tsx", ".js", ".mjs", ".css", ".json", ".yml",
         ".yaml", ".toml", ".sh", ".ftl", ".csv", ".tsv", ".txt", ".html", ".ini",
         ".cfg", ".sql")


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [p for p in out.split("\0") if p]


def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return ""


def undeclared_docs(paths: list[str]) -> list[str]:
    """Tracked files under `docs/` that are neither listed nor decision records."""
    return sorted(
        p for p in paths
        if p.startswith("docs/") and p not in DOCS
        and not _DECISION.fullmatch(p) and not _IMAGE.fullmatch(p)
    )


def image_problems(tracked: set[str], markdown: dict[str, str], sizes: dict[str, int]) -> list[str]:
    """Images nothing references, references to images that do not exist, and oversized images."""
    images = {p for p in tracked if _IMAGE.fullmatch(p)}
    cited: set[str] = set()
    problems = []
    for path, text in sorted(markdown.items()):
        for ref in _IMAGE_CITE.findall(text):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), ref))
            if not target.startswith("docs/"):
                target = posixpath.normpath("docs/" + ref.lstrip("./"))
            cited.add(target)
            if target not in images:
                problems.append(f"{path} -> {ref}: no such image")
    problems += [f"{p}: referenced by no Markdown file" for p in sorted(images - cited)]
    problems += [f"{p}: {sizes[p]} bytes, over {IMAGE_MAX_BYTES}" for p in sorted(images)
                 if sizes.get(p, 0) > IMAGE_MAX_BYTES]
    return problems


def stray_instructions(paths: list[str]) -> list[str]:
    """Agent tooling folders, at any depth, and per-directory instruction files."""
    return sorted(
        p for p in paths
        if any(part in _TOOLING_DIRS for part in p.split("/")[:-1])
        or p.endswith(("/AGENTS.md", "/CLAUDE.md"))
    )


def log_references(files: dict[str, str]) -> list[str]:
    return [f"{path}:{n}" for path, text in sorted(files.items())
            for n, line in enumerate(text.splitlines(), 1) if _LOG_REF.search(line)]


def dangling_citations(files: dict[str, str], tracked: set[str]) -> list[str]:
    """Every Markdown file a text names that the tree does not have.

    A path resolves against the citing file's directory or the repository root;
    a bare name resolves when any tracked file carries it.
    """
    names = {posixpath.basename(p) for p in tracked}
    hits = []
    for path, text in sorted(files.items()):
        here = posixpath.dirname(path)
        for n, line in enumerate(text.splitlines(), 1):
            for cited in _MD_CITE.findall(line):
                if "/" in cited:
                    candidates = {
                        posixpath.normpath(posixpath.join(here, cited)),
                        posixpath.normpath(cited.lstrip("./")),
                    }
                    if candidates & tracked:
                        continue
                elif cited in names:
                    continue
                hits.append(f"{path}:{n} -> {cited}")
    return hits


def unresolved_paths(text: str, tracked: set[str]) -> list[str]:
    """File paths a document names that the repository does not track.

    Only `git ls-files` answers, never the disk: a file a developer built or
    left untracked in their checkout would pass here and fail in a clean clone.
    """
    missing = set()
    for raw in _DOC_PATH.findall(text):
        path = raw.rstrip(".,;:")
        if path.endswith("/") or "*" in path or path in _UNTRACKED_BY_DESIGN:
            continue
        if not any(posixpath.normpath(posixpath.join(root, path)) in tracked for root in _PATH_ROOTS):
            missing.add(path)
    return sorted(missing)


def _text_files() -> dict[str, str]:
    return {p: _read(p) for p in _tracked() if p.endswith(_TEXT)}


def test_docs_holds_only_the_listed_documents():
    assert undeclared_docs(_tracked()) == [], (
        "docs/ is a closed set. Put plans, audits and reviews in an issue; a new "
        "permanent document is an edit to DOCS in this file."
    )


def test_every_listed_document_exists():
    tracked = set(_tracked())
    assert sorted((DOCS | ROOT_DOCS) - tracked) == []


def test_every_image_is_referenced_small_and_present():
    tracked = set(_tracked())
    markdown = {p: _read(p) for p in tracked if p.endswith(".md")}
    sizes = {p: (ROOT / p).stat().st_size for p in tracked if _IMAGE.fullmatch(p)}
    assert image_problems(tracked, markdown, sizes) == []


def test_root_markdown_is_the_listed_set():
    root_md = {p for p in _tracked() if "/" not in p and p.endswith(".md")}
    assert root_md == ROOT_DOCS


def test_no_agent_tooling_or_nested_instruction_files_ship():
    assert stray_instructions(_tracked()) == []


def test_nothing_cites_a_decision_log_entry():
    hits = log_references(_text_files())
    assert hits == [], "the decision log is gone; say the reason in place:\n" + "\n".join(hits[:50])


def test_every_cited_doc_exists():
    tracked = set(_tracked())
    files = {p: t for p, t in _text_files().items()
             if p not in _FAKE_PATH_FIXTURES and not p.startswith(_OTHER_REPOSITORY)}
    hits = dangling_citations(files, tracked)
    assert hits == [], "these cite documents that do not exist:\n" + "\n".join(hits[:50])


def test_the_data_repository_s_files_cite_what_it_holds():
    """The templates `scripts.data export` writes cite files by their paths in
    the data repository: each must be a file the export puts there."""
    from scripts.data import REPO_FILES, TEMPLATES, read_lock

    holds = {f"{name}/{file}" for name, entry in read_lock()["datasets"].items() for file in entry["files"]}
    holds |= set(REPO_FILES.values())
    files = {REPO_FILES[t.name]: t.read_text(encoding="utf-8") for t in TEMPLATES.iterdir() if t.suffix == ".md"}
    assert files and dangling_citations(files, holds) == []
    assert dangling_citations({"README.md": "see [x](atlas/READ_ME.md)"}, holds) == ["README.md:1 -> atlas/READ_ME.md"]


@pytest.mark.parametrize("doc", _PATH_CHECKED)
def test_every_path_a_document_names_is_tracked(doc):
    missing = unresolved_paths(_read(doc), set(_tracked()))
    assert missing == [], (
        f"{doc} names paths the repository does not track: {missing}. Correct the "
        "doc; a renamed or moved file is exactly what this catches."
    )


# Negative controls: each check notices what it exists to notice.

def test_a_missing_path_is_named_and_paths_resolve_from_where_they_are_typed():
    tracked = {"backend/tracker/blueprint.py", "dashboard/tests/ux/a11y.spec.ts",
               "docs/ui.md"}
    text = ("Edit `tracker/blueprint.py`, run `tests/ux/a11y.spec.ts` from `dashboard/`, "
            "read docs/ui.md, then `backend/tracker/gone.py`.")
    assert unresolved_paths(text, tracked) == ["backend/tracker/gone.py"]


def test_a_tsx_path_is_read_whole():
    tracked = {"dashboard/src/ui/Content.tsx"}
    assert unresolved_paths("see `dashboard/src/ui/Content.tsx`", tracked) == []
    assert unresolved_paths("see `dashboard/src/ui/Content.ts`", tracked) == [
        "dashboard/src/ui/Content.ts"
    ]
    assert unresolved_paths("`backend/tracker/taxonomy/cities.tsv`", set()) == []


def test_a_github_path_is_read_whole_and_script_and_data_extensions_are_claims():
    tracked = {".github/workflows/hygiene.yml", "dashboard/scripts/gen-copy.mjs"}
    text = ("`.github/workflows/hygiene.yml` and `dashboard/scripts/gen-copy.mjs` exist; "
            "`.github/workflows/gone.yml`, `dashboard/gone.config.js`, "
            "`backend/alembic/gone.sql` and `docs/gone.yaml` do not.")
    assert unresolved_paths(text, tracked) == [
        ".github/workflows/gone.yml", "backend/alembic/gone.sql",
        "dashboard/gone.config.js", "docs/gone.yaml",
    ]


def test_an_unlisted_doc_is_named():
    assert undeclared_docs(["docs/ui.md", "docs/some-plan.md", "docs/decisions/0001-x.md"]) == [
        "docs/some-plan.md"
    ]


def test_only_images_are_open_under_docs_images():
    assert undeclared_docs(
        ["docs/images/board.webp", "docs/images/notes.md", "docs/images/Board Shot.png"]
    ) == ["docs/images/Board Shot.png", "docs/images/notes.md"]


def test_an_orphan_a_missing_and_an_oversized_image_are_named():
    tracked = {"README.md", "docs/ui.md", "docs/images/board.webp", "docs/images/old.png",
               "docs/images/huge.webp"}
    markdown = {
        "README.md": '<img src="docs/images/board.webp"> ![x](docs/images/gone.webp) docs/images/huge.webp',
        "docs/ui.md": "![b](images/board.webp)",
    }
    sizes = {"docs/images/board.webp": 1000, "docs/images/old.png": 10,
             "docs/images/huge.webp": IMAGE_MAX_BYTES + 1}
    assert image_problems(tracked, markdown, sizes) == [
        "README.md -> docs/images/gone.webp: no such image",
        "docs/images/old.png: referenced by no Markdown file",
        f"docs/images/huge.webp: {IMAGE_MAX_BYTES + 1} bytes, over {IMAGE_MAX_BYTES}",
    ]


def test_nested_instruction_files_and_tool_folders_are_named():
    assert stray_instructions(
        ["AGENTS.md", "backend/AGENTS.md", ".claude/x.md", "dashboard/.claude/launch.json",
         "a.py", "docs/claude.md"]
    ) == [".claude/x.md", "backend/AGENTS.md", "dashboard/.claude/launch.json"]


def test_a_log_reference_is_found_by_line():
    ref = "IMPL" + "-42"
    assert log_references({"a.py": "x = 1\n# see " + ref + "\n"}) == ["a.py:2"]


def test_a_missing_doc_is_named_and_a_present_one_is_not():
    gone, here = "docs/" + "gone.md", "docs/" + "ui.md"
    files = {"a.py": f"# {here}\n# {gone}\n"}
    assert dangling_citations(files, {here}) == [f"a.py:2 -> {gone}"]


def test_a_bare_or_relative_citation_resolves_or_is_named():
    tracked = {"docs/ui.md", "SECURITY.md", "dashboard/src/copy/en/glossary.yaml"}
    files = {
        "docs/a.md": "see ../SECURITY.md and ui.md\n",
        "x.ftl": "# note (" + "vocabulary" + ".md §4)\n",
    }
    assert dangling_citations(files, tracked) == ["x.ftl:1 -> " + "vocabulary" + ".md"]
