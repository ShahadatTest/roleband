"""The Content-Security-Policy the dashboard is served under.

The directives are `dashboard/csp-policy.json`, one file for the API and for
the build the UX suite runs (`dashboard/vite.config.ts`): scripts from this
origin only, and connections to this origin and the usage-statistics host
alone, so a promise about where the page talks is one the browser keeps.
`{usage_host}` is the configured host's origin.
"""

from __future__ import annotations

import json
from functools import cache
from urllib.parse import urlsplit

from tracker.platform.paths import REPO_ROOT

POLICY_FILE = REPO_ROOT / "dashboard" / "csp-policy.json"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@cache
def dashboard_csp(usage_host: str) -> str:
    directives: dict[str, list[str]] = json.loads(POLICY_FILE.read_text())["directives"]
    origin = _origin(usage_host)
    return "; ".join(
        " ".join([name, *(origin if value == "{usage_host}" else value for value in values)])
        for name, values in directives.items()
    )
