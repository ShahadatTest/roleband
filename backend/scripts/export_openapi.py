"""Export the FastAPI OpenAPI schema without starting a server.

Feeds openapi-typescript (dashboard `npm run gen:api`) -> committed
dashboard/src/api.gen.ts. Deterministic output (sorted keys) so the CI
contract-drift job can diff regeneration byte-for-byte.

    .venv/bin/python -m scripts.export_openapi [out_path]

Default out_path: ../dashboard/openapi.json (git-ignored intermediate).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tracker.api.app import app

#: Where the committed artifact lives. `tests/test_openapi_current.py` reads both
#: this and `render()`, so the gate cannot drift from what the script writes.
COMMITTED = Path(__file__).resolve().parents[2] / "dashboard" / "openapi.json"


def render() -> str:
    """The exact bytes the committed artifact must contain."""
    return json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else COMMITTED
    out.write_text(render())
    print(f"{len(app.openapi().get('paths', {}))} paths -> {out}")


if __name__ == "__main__":
    main()
