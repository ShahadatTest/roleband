"""`dashboard/openapi.json` is committed, so it must match the app.

Two artifacts are generated and committed — `openapi.json` and, from it,
`dashboard/src/api.gen.ts` — and `.github/workflows/contract-drift.yml` diffs
both after regenerating them. That gate is real, but it only runs in CI, and CI
runs after the commit is made. A stale artifact therefore reaches the branch
first and fails there.

Editing only a docstring on a Pydantic model is enough: a model's docstring is
its OpenAPI `description`, so the committed schema stops matching the app,
and the rest of the backend suite passes anyway — nothing else local reads the
file.

This is the local half. It compares against `export_openapi.render()` rather than
restating the serialization, because a gate that spells out `indent=1,
sort_keys=True` for itself would keep passing after the script changed either.
"""

from __future__ import annotations

from scripts.export_openapi import COMMITTED, render


def test_the_committed_schema_is_what_the_app_serves():
    assert COMMITTED.is_file(), f"{COMMITTED} is missing"
    current = render()
    committed = COMMITTED.read_text()
    if current == committed:
        return

    import difflib

    diff = "".join(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile="committed openapi.json",
            tofile="what the app serves",
            n=1,
        )
    )
    raise AssertionError(
        "dashboard/openapi.json is stale. Regenerate BOTH committed artifacts:\n"
        "    cd backend && .venv/bin/python -m scripts.export_openapi\n"
        "    cd dashboard && npm run gen:api\n"
        f"{diff[:4000]}"
    )
