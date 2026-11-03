"""Built dashboard (single-origin) SPA shell + client-route fallback.

Included last so every /api route wins first. Routes register unconditionally
so the route table is identical with or without a built dashboard (the frozen
route-table gate runs on CI, where `dashboard/dist` does not exist); the
handlers check for the build per request and 404 when serving headlessly.
The /assets static mount itself lives in app.py.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from tracker.api.csp import dashboard_csp
from tracker.api.errors import ErrorCode, api_error
from tracker.config import get_settings
from tracker.platform.paths import DASHBOARD_DIST

router = APIRouter()


# The shell must be REVALIDATED on every load, while the hashed bundles it
# points at stay cacheable forever.
#
# Without this the browser applies heuristic freshness to `index.html` and can
# keep serving a shell that references a bundle a rebuild already deleted — the
# page then looks unchanged after a deploy, or 404s its own script.
# `no-cache` is not "do not store": the ETag still makes the common case a 304.
_SHELL_HEADERS = {"Cache-Control": "no-cache"}


def _index() -> FileResponse:
    index = DASHBOARD_DIST / "index.html"
    if not index.is_file():
        raise api_error(404, ErrorCode.PAGE_NOT_FOUND, "dashboard build not present")
    csp = dashboard_csp(get_settings().usage_stats_host)
    return FileResponse(index, headers={**_SHELL_HEADERS, "Content-Security-Policy": csp})


@router.get("/", include_in_schema=False)
async def _spa_root() -> FileResponse:
    return _index()


@router.get("/{full_path:path}", include_in_schema=False)
async def _spa_fallback(full_path: str) -> FileResponse:
    # /api/* never reaches here for known routes; guard unknown ones so a
    # bad API path 404s as JSON-ish rather than silently returning the SPA.
    if full_path.startswith("api/"):
        raise api_error(404, ErrorCode.PAGE_NOT_FOUND, "not found")
    candidate = DASHBOARD_DIST / full_path
    if candidate.is_file() and candidate.resolve().is_relative_to(DASHBOARD_DIST.resolve()):
        return FileResponse(candidate)
    # Client-side route (e.g. /favorites) -> hand back the SPA shell.
    return _index()
