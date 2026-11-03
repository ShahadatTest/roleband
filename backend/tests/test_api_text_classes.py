"""The API declares a text class for every display-named string field
(docs/copy.md; `tracker/api/schemas/text_class.py`).

An undeclared field can reach the dashboard as untranslated English.
The undeclared-field count can only fall; a new one fails here."""

from __future__ import annotations

import re

import pytest
from pydantic import BaseModel, Field

from tracker.api.app import app
from tracker.api.schemas.text_class import TEXT_CLASSES, text

#: Undeclared display-named string fields: 0. A new one fails: declare its
#: class, or send a code the client says.
UNDECLARED_BASELINE = 0

DISPLAY = re.compile(
    r"(label|title|message|reason|note|notes|detail|description|text|summary|headline"
    r"|caption|hint|sentence|why|explanation|display|heading|name)$",
    re.IGNORECASE,
)


def _is_string(prop: dict) -> bool:
    if prop.get("type") == "string":
        return True
    if prop.get("type") == "array" and (prop.get("items") or {}).get("type") == "string":
        return True
    return any(_is_string(p) for p in prop.get("anyOf", []))


def undeclared(schema: dict) -> list[str]:
    out = []
    for name, model in schema.get("components", {}).get("schemas", {}).items():
        for field, prop in (model.get("properties") or {}).items():
            if DISPLAY.search(field) and _is_string(prop) and "x-text" not in prop:
                out.append(f"{name}.{field}")
    return sorted(out)


def test_undeclared_display_fields_only_fall():
    fields = undeclared(app.openapi())
    assert len(fields) <= UNDECLARED_BASELINE, (
        f"{len(fields) - UNDECLARED_BASELINE} new display-named string field(s) with no text class; "
        "declare it with `Field(json_schema_extra=text(...))`"
    )
    assert len(fields) == UNDECLARED_BASELINE, (
        f"down to {len(fields)}: lower UNDECLARED_BASELINE in the same change"
    )


def test_a_declared_field_is_not_counted_and_an_undeclared_one_is():
    class Probe(BaseModel):
        title: str = Field(json_schema_extra=text("content"))
        reason: str | None = None

    schema = {"components": {"schemas": {"Probe": Probe.model_json_schema()}}}
    assert schema["components"]["schemas"]["Probe"]["properties"]["title"]["x-text"] == "content"
    assert undeclared(schema) == ["Probe.reason"]


def _declared(node, out: list[str]) -> list[str]:
    if isinstance(node, dict):
        if "x-text" in node:
            out.append(node["x-text"])
        for value in node.values():
            _declared(value, out)
    elif isinstance(node, list):
        for value in node:
            _declared(value, out)
    return out


def test_every_declared_class_is_one_the_client_knows():
    declared = _declared(app.openapi(), [])
    assert declared, "the schema declares classes; this check must see them"
    assert sorted(set(declared) - TEXT_CLASSES) == []


def test_an_unknown_class_is_refused_where_it_is_declared():
    with pytest.raises(ValueError, match="'slug' is not a text class"):
        text("slug")  # type: ignore[arg-type]
