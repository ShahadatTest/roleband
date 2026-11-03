"""The route table and the response-model gate.

Three claims, kept apart because each is blind to the others:

1. **The table is frozen**. Every (method, path) the API exposes is recorded
   in the fixture, and no route may appear or vanish as a side effect. Regenerate the fixture ONLY for a deliberate route change:

       .venv/bin/python -m scripts.freeze_route_table

2. **A modelled route stays modelled, and coverage never falls**.
   Freezing the table says nothing about response SHAPES, so the fixture also
   records each route's declared model and a `modelled_count` that may only
   rise.

3. **A route without a response model is a named exception, never a default**.
   Claim 2 cannot see a NEW route: add a `-> dict` handler,
   regenerate the fixture as claim 1 asks, and the count is unchanged, so every
   test above still passes. `NON_JSON_ROUTES` is the exact method/path inventory
   of the routes that answer no JSON of ours, each with its reason and each held
   to that reason; every other route must declare a Pydantic `response_model`,
   and one that does not fails here by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_type_hints

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import Response

from scripts.freeze_route_table import route_rows
from tracker.api.app import app

_FIXTURE = Path(__file__).parent / "fixtures" / "route_table.json"


class _Probe(BaseModel):
    """A response model for the throwaway app below; module-level so a return
    annotation naming it resolves, as it would in a router."""

    ok: bool

#: Every route allowed to declare no response model: none of them answers JSON
#: this codebase shapes. Adding an entry is a decision, not a way to land a
#: route; a route that answers JSON gets a model instead.
NON_JSON_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/"): "the built dashboard's index.html (routers/spa.py)",
    ("GET", "/{full_path:path}"): (
        "the built dashboard: a file under dist, else index.html for a client-side route; an unknown "
        "/api path is refused with a 404 before either (routers/spa.py)"
    ),
    ("GET", "/openapi.json"): "FastAPI's own schema document, generated from the models it describes",
    ("GET", "/docs"): "FastAPI's Swagger UI page",
    ("GET", "/docs/oauth2-redirect"): "FastAPI's Swagger UI OAuth helper page",
    ("GET", "/redoc"): "FastAPI's ReDoc page",
}


def _fixture() -> dict:
    return json.loads(_FIXTURE.read_text())


def _unmodelled(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["method"], r["path"]) for r in rows if not r["response_schema"]}


def _unlisted(rows: list[dict]) -> list[tuple[str, str]]:
    """Routes with no response model that the inventory does not name."""

    return sorted(_unmodelled(rows) - set(NON_JSON_ROUTES))


# --------------------------------------------------------------------------- #
# 1-2. The frozen table and its coverage
# --------------------------------------------------------------------------- #


def test_route_table_is_frozen():
    frozen = _fixture()
    current = route_rows()
    frozen_pairs = {(r["method"], r["path"]) for r in frozen["routes"]}
    current_pairs = {(r["method"], r["path"]) for r in current}
    assert not (frozen_pairs - current_pairs) and not (current_pairs - frozen_pairs), (
        f"route table drifted — missing: {sorted(frozen_pairs - current_pairs)}, "
        f"added: {sorted(current_pairs - frozen_pairs)}. "
        "If deliberate, regenerate tests/fixtures/route_table.json."
    )


def test_a_modelled_route_still_declares_its_model():
    """A route that HAD a response model may not quietly lose it."""

    frozen = {(r["method"], r["path"]): r["response_schema"] for r in _fixture()["routes"]}
    current = {(r["method"], r["path"]): r["response_schema"] for r in route_rows()}
    lost = {
        key: was
        for key, was in frozen.items()
        if was and current.get(key) != was
    }
    assert not lost, (
        f"these routes lost or changed their declared response model: {lost}. "
        "A response_model is the only thing in this repo that catches a renamed "
        "response field, so dropping one is a deliberate act, not a refactor."
    )


def test_response_model_coverage_is_reported_and_may_only_rise():
    """The honest number, kept honest.

    `dict` is not a model. FastAPI infers `response_model` from the return
    annotation, so every `-> dict` handler would look modelled unless it were
    excluded — a counter that lies in the flattering direction.
    `_declared_model` excludes it; this asserts the resulting number matches the
    fixture and never falls.
    """

    frozen = _fixture()
    current = sum(1 for r in route_rows() if r["response_schema"])
    assert current >= frozen["modelled_count"], (
        f"response-model coverage FELL: {current} of {len(route_rows())}, "
        f"down from {frozen['modelled_count']}. The count may only rise."
    )
    assert current == frozen["modelled_count"], (
        f"response-model coverage rose to {current} of {len(route_rows())} — good. "
        "Regenerate tests/fixtures/route_table.json so the new floor is recorded."
    )


# --------------------------------------------------------------------------- #
# 3. No route answers JSON without a model
# --------------------------------------------------------------------------- #


def test_every_route_without_a_model_is_a_named_non_json_exception():
    unlisted = _unlisted(route_rows())
    assert not unlisted, (
        f"these routes declare no response model: {unlisted}. A route that answers JSON "
        "gets a Pydantic response_model (docs/architecture.md, 'API contract'); only a route "
        "that answers no JSON of ours belongs in NON_JSON_ROUTES, with its reason."
    )


def test_no_exception_outlives_its_route():
    stale = sorted(set(NON_JSON_ROUTES) - _unmodelled(route_rows()))
    assert not stale, (
        f"NON_JSON_ROUTES names routes that now declare a model or no longer exist: {stale}. "
        "Delete their entries: an exception nothing needs is room for the next route to hide in."
    )


def _route(method: str, path: str):
    return next(
        r for r in app.routes if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or ())
    )


def test_each_exception_answers_no_json_of_ours():
    """Held to its reason, not just listed.

    FastAPI's own pages and schema are plain Starlette routes it adds itself; any
    other exception is one of our handlers, and its declared return type must be
    a response class that is not JSON — a redirect, a file.
    """

    for method, path in sorted(NON_JSON_ROUTES):
        route = _route(method, path)
        if not isinstance(route, APIRoute):
            assert route.endpoint.__module__ == "fastapi.applications", (
                f"{method} {path} is not one of FastAPI's own routes"
            )
            continue
        returns = get_type_hints(route.endpoint).get("return")
        assert isinstance(returns, type) and issubclass(returns, Response), (
            f"{method} {path} declares no response class; a handler returning a dict answers JSON"
        )
        assert not issubclass(returns, JSONResponse), f"{method} {path} answers JSON: give it a response model"


def test_a_new_json_route_without_a_model_is_named_while_one_with_a_model_is_not():
    """What the gate says about routes the real API does not have.

    The throwaway app carries FastAPI's own four routes, so they must stay
    silent here exactly as they do on the real one.
    """

    probe = FastAPI()

    @probe.get("/api/probe")
    async def unmodelled() -> dict:
        return {"ok": True}

    @probe.post("/api/probe")
    async def modelled() -> _Probe:
        return _Probe(ok=True)

    @probe.get("/api/probe/typed", response_model=_Probe)
    async def declared() -> dict:
        return {"ok": True}

    assert _unlisted(route_rows(probe)) == [("GET", "/api/probe")]
