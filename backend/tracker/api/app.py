"""FastAPI composition root: the dashboard's HTTP API.

The API serves the dashboard's reads (job list and detail, facets, demand,
statistics, run status) and it is NOT read-only: the user's own actions change
state through it (settings, profile, favorites, dismissals, pursuits, duplicate
review), and it asks the supervisor for background work and to stop it.

Composition only (docs/architecture.md): routes live in
`tracker/api/routers/*`, shared dependencies in `tracker/api/deps.py`, requests
to the supervisor in `tracker/api/scan_requests.py` and
`tracker/api/job_requests.py`. This module re-exports nothing. Import a name
from the module that defines it, and patch it where it is looked up —
`tests/test_api_composition.py` fails if a fan-out or re-export returns.
`tracker.api.app:app` is the uvicorn target.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pydantic.json_schema import models_json_schema

from tracker import __version__
from tracker.api.boundary import LoopbackBoundary
from tracker.api.errors import ErrorDetail
from tracker.api.routers import (
    companies,
    intelligence,
    jobs,
    lineage,
    notifications,
    ops,
    plugins,
    profile,
    recipes,
    settings,
    skills,
    spa,
    statistics,
    usage,
)
from tracker.api.usage_counter import UsageCounter
from tracker.company_store import ensure_builtins, ensure_catalog_connectors
from tracker.config import get_settings
from tracker.db.session import get_session_factory
from tracker.platform import preparation
from tracker.platform.paths import DASHBOARD_DIST, DATA_DIR, PACING_DIR, PACKAGED
from tracker.platform.ratelimit import enable_shared_pacing
from tracker.profiles.seed import ensure_company_profiles
from tracker.semantic.embed import warm_model
from tracker.usage_stats import tally as usage_tally


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Seed built-in company rows + profiles and warm the embedding model at startup."""
    # The API reads posting pages when someone opens a posting and
    # previews recipes: provider-facing requests on the hosts the scheduler
    # and the directory pass pace. Sharing their slots keeps the per-host delay
    # the combined bound. Here, not at import: tests build the app
    # without its lifespan and stay process-local.
    enable_shared_pacing(PACING_DIR)
    # Resolved here, not at import: the embedded server starts on first use.
    async with get_session_factory()() as session:
        await ensure_builtins(session)
        # A company added before its connector shipped keeps `adapter=None` and
        # is dropped from every run with no error; the catalog is read back into
        # it here so the roster is correct the moment the API is up.
        await ensure_catalog_connectors(session)
        await session.commit()
        # Profile row per tracked company (blueprint identity as seed claims), so
        # /company lists a new company immediately — a plugin's facts then
        # enrich rather than create.
        await ensure_company_profiles(session)
        await session.commit()
    settings = get_settings()
    warm = None
    if settings.search_semantic_enabled and settings.search_warm_model_on_startup:
        warm = asyncio.create_task(warm_model())
    elif PACKAGED:
        preparation.update(DATA_DIR, model="unused", downloaded_bytes=0, total_bytes=0, reason=None)
    if PACKAGED:
        preparation.update(DATA_DIR, database="ready", service="ready")
    # Usage sharing: the request path only tallies; this writes the tally out
    # every minute, and only while the user shares (docs/architecture.md).
    drain = asyncio.create_task(usage_tally.run(get_session_factory()))
    try:
        yield
    finally:
        drain.cancel()
        if warm is not None:
            warm.cancel()
            with suppress(asyncio.CancelledError):
                await warm


app = FastAPI(title="RoleBand Job Tracker API", version=__version__, lifespan=_lifespan)

# Innermost of the three: counts only what the boundary admitted and the router
# answered, by the route the router matched (tracker/api/usage_counter.py).
app.add_middleware(UsageCounter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().dev_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last, so it is outermost: nothing — CORS included — answers a request
# that crossed the loopback boundary. The API has no authentication, and this
# is what that design rests on (tracker/api/boundary.py).
app.add_middleware(
    LoopbackBoundary,
    trusted_hosts=[get_settings().api_host, *get_settings().api_trusted_hosts],
)

app.include_router(ops.router)
app.include_router(jobs.router)
app.include_router(lineage.router)
app.include_router(skills.router)
app.include_router(statistics.router)
app.include_router(notifications.router)
app.include_router(settings.router)
app.include_router(profile.router)
app.include_router(intelligence.router)
app.include_router(companies.router)
app.include_router(recipes.router)
app.include_router(usage.router)
app.include_router(plugins.router)

# --------------------------------------------------------------------------- #
# Built dashboard (single-origin). Mounted last so every /api route wins first.
# Only active once `dashboard/dist` exists (created by `npm run build` /
# deploy/install.sh); the API still serves headlessly without it.
# --------------------------------------------------------------------------- #

if (DASHBOARD_DIST / "index.html").is_file():
    _assets_dir = DASHBOARD_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

app.include_router(spa.router)


def _openapi() -> dict:
    """The schema, plus `ErrorDetail`: the shape of every error the API answers
    on purpose and the full `ErrorCode` set, so the dashboard's generated types
    know every code without each route restating it (tracker/api/errors.py)."""
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        _, defs = models_json_schema(
            [(ErrorDetail, "serialization")], ref_template="#/components/schemas/{model}"
        )
        schema.setdefault("components", {}).setdefault("schemas", {}).update(defs.get("$defs", {}))
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _openapi  # type: ignore[method-assign]
