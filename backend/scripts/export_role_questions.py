"""Export the walk's "which roles" table for the dashboard.

`tracker/taxonomy/role_rows.py` is the one source; the dashboard imports the
committed `dashboard/src/features/scope/walk/roleQuestions.gen.json`.
`tests/test_role_rows.py` fails when the committed file differs from `render()`.

    .venv/bin/python -m scripts.export_role_questions
"""

from __future__ import annotations

import json
from pathlib import Path

from tracker.taxonomy.role_rows import export

COMMITTED = (
    Path(__file__).resolve().parents[2]
    / "dashboard" / "src" / "features" / "scope" / "walk" / "roleQuestions.gen.json"
)


def render() -> str:
    """The exact bytes the committed artifact must contain."""
    return json.dumps(export(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    COMMITTED.write_text(render())
    print(f"{sum(len(q['rows']) for q in export().values())} rows -> {COMMITTED}")


if __name__ == "__main__":
    main()
