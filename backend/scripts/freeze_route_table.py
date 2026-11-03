"""Regenerate tests/fixtures/route_table.json from the live app object.

Run only for a deliberate route addition/removal, or after modelling a response;
the snapshot test explains what each field is for.

    .venv/bin/python -m scripts.freeze_route_table
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from tracker.api.app import app


def _declared_model(model: object) -> str | None:
    """The response model's name, or None when the route declares no shape.

    `dict` does NOT count, and this is the whole reason the helper exists.
    FastAPI infers `response_model` from the return annotation, so every
    handler annotated `-> dict` arrives here carrying `dict` as its "model".
    Counting those would report nearly every route modelled when few are -- a
    coverage counter that lies in the most flattering direction possible, which
    is the exact pathology this gate is meant to end.

    A shape is declared when it is a Pydantic model: something a renamed field
    can actually be checked against.
    """

    if model is None or not isinstance(model, type):
        return None
    if not issubclass(model, BaseModel):
        return None
    return model.__name__


def route_rows(application: FastAPI = app) -> list[dict]:
    """Every (method, path) an app exposes, with the response model if any.

    `response_schema` is the name of the declared `response_model`, or None. It
    is recorded per route rather than counted in aggregate so the fixture says
    WHICH routes are modelled — a bare count would let one route lose its model
    while another gained one and report no change.

    `application` is the real API unless a test hands it a throwaway app to
    prove what the gate would say about a route the real one does not have.
    """

    rows = []
    for route in application.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        schema = _declared_model(getattr(route, "response_model", None))
        for method in methods:
            if method == "HEAD":
                continue
            rows.append({"method": method, "path": route.path, "response_schema": schema})
    return sorted(rows, key=lambda r: (r["method"], r["path"]))


def main() -> None:
    rows = route_rows()
    modelled = sum(1 for r in rows if r["response_schema"])
    payload = {
        "_why": (
            "The route table is frozen so the router split cannot add or drop an endpoint "
            "silently. `modelled_count` is the SECOND claim: how many of these routes declare "
            "a response_model. It is deliberately reported as 'N of M' rather than as a pass, "
            "because this gate does not verify response shapes it was never given. "
            "The number may only rise."
        ),
        "modelled_count": modelled,
        "route_count": len(rows),
        "routes": rows,
    }
    out = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "route_table.json"
    out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{len(rows)} routes ({modelled} modelled) -> {out}")


if __name__ == "__main__":
    main()
