"""Listing recipe v1 JSON Schema.

The schema is the *published contract* a community author writes against, and
the first line of the compiler's defense. Two invariants matter most and are
enforced here, not left to prose:

- `additionalProperties: false` at every level. An unknown key is a rejection,
  not a silently-ignored field: a typo'd `requird: true` must fail loudly, and
  a smuggled `xpath:` or `eval:` has nowhere to hide. Field names are a closed
  set too (`FIELD_NAMES`, the names the runner reads), so a misspelled
  `locaitons` is refused rather than dropped.
- CSS-only location. There is no `xpath` property anywhere in the schema, so a
  recipe carrying raw XPath fails validation structurally.

The schema has two views of one format. `RECIPE_V1_SCHEMA` is the contract: what
a recipe may declare when it is saved, previewed, validated or shadowed, and
nothing a runtime cannot execute. `STORED_RECIPE_V1_SCHEMA` is what a revision
already in the database must meet to load: it also accepts the transport modes
the format reserves (`RESERVED_TRANSPORT_MODES`), a POST `body`, and any field
name. A stored revision that uses one of those still compiles, the runtime then
refuses it by name or ignores the unread field, and validating it again reports
the problem.

Closure authority is deliberately absent: `list_complete` and
`closure_capability` are runtime/binding decisions, never recipe
fields. A recipe may describe a structural `empty_state_selector`; it cannot
declare its own empty result authoritative.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "FIELD_NAMES",
    "RECIPE_V1_SCHEMA",
    "RESERVED_TRANSPORT_MODES",
    "STORED_RECIPE_V1_SCHEMA",
    "TRANSFORM_NAMES",
    "TRANSPORT_MODES",
]

#: Transforms a recipe field may declare. No arbitrary code / eval / JS.
TRANSFORM_NAMES = (
    "trim",
    "collapse_whitespace",
    "lower",
    "upper",
    "join",
    "resolve_url",
    "parse_date",
    "regex_capture",
)

#: Transport modes a recipe may request: the ones a runtime executes.
TRANSPORT_MODES = ("static_http",)
#: Mode names the v1 format reserves but no runtime executes. Only a stored
#: revision may carry one; the runtime refuses it by name.
RESERVED_TRANSPORT_MODES = ("static_impersonate", "render")

#: The fields the runner reads into a posting. `req_id`, `title` and `url` are
#: required; `posted_at` is parsed as a date.
FIELD_NAMES = ("req_id", "title", "url", "locations", "department", "team", "posted_at")

_FIELD_SPEC: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Locators: CSS only. No `xpath`.
        "css": {"type": "string"},
        "css_all": {"type": "string"},
        "json_path": {"type": "string"},  # dotted key/index path for JSON responses
        "literal": {"type": "string"},
        # Extraction modifiers.
        "attr": {"type": "string"},
        "text": {"type": "boolean"},
        "absolute": {"type": "boolean"},
        "required": {"type": "boolean"},
        # Bounded transform pipeline.
        "transforms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "op": {"type": "string", "enum": list(TRANSFORM_NAMES)},
                    "sep": {"type": "string"},
                    "pattern": {"type": "string"},
                    "format": {"type": "string"},
                },
                "required": ["op"],
            },
        },
    },
}

STORED_RECIPE_V1_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RoleBand listing recipe v1",
    "type": "object",
    "additionalProperties": False,
    "required": ["format_version", "kind", "id", "match", "transport", "listing"],
    "properties": {
        "format_version": {"const": 1},
        "kind": {"const": "job_listing"},
        "id": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{1,63}$"},
        "match": {
            "type": "object",
            "additionalProperties": False,
            "required": ["domains"],
            "properties": {
                # Exact approved hosts. Recipe data can never introduce a new
                # host implicitly. A domain admits its subdomains, so it needs
                # at least one dot: a bare `com` would admit every .com host.
                "domains": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "pattern": r"^[a-z0-9-]+(\.[a-z0-9-]+)+$"},
                }
            },
        },
        "transport": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode"],
            "properties": {
                "mode": {"type": "string", "enum": [*TRANSPORT_MODES, *RESERVED_TRANSPORT_MODES]},
                "delay_ms": {"type": "integer", "minimum": 0, "maximum": 60000},
            },
        },
        "listing": {
            "type": "object",
            "additionalProperties": False,
            "required": ["start_url", "response", "item", "fields"],
            "properties": {
                "start_url": {"type": "string", "format": "uri"},
                "response": {"type": "string", "enum": ["html", "json"]},
                # For JSON, `item` is a dotted path to the array of postings.
                "item": {"type": "string"},
                # POST stays loadable so the compiler names it; no runtime sends it.
                "method": {"type": "string", "enum": ["GET", "POST"]},
                "body": {"type": "object"},
                "fields": {
                    "type": "object",
                    "additionalProperties": _FIELD_SPEC,
                    # Enough to build a RawJob; runtime enforces req_id/title/url.
                    "required": ["req_id", "title", "url"],
                },
            },
        },
        "pagination": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode", "max_pages"],
            "properties": {
                "mode": {"type": "string", "enum": ["next_link", "page_number", "offset", "cursor"]},
                "selector": {"type": "string"},
                "param": {"type": "string"},
                "size": {"type": "integer", "minimum": 1, "maximum": 500},
                "cursor_path": {"type": "string"},
                # Hard upper bound; hitting it yields list_complete=false.
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
        },
        "validation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "required_field_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                "min_items": {"type": "integer", "minimum": 0},
                # Structural empty-state marker. Describes emptiness; does NOT
                # authorize closure: that is a binding/runtime decision.
                "empty_state_selector": {"type": "string"},
            },
        },
    },
}


def _contract(stored: dict[str, Any]) -> dict[str, Any]:
    """The stored view narrowed to what a runtime executes and the runner reads."""
    schema = copy.deepcopy(stored)
    props = schema["properties"]
    props["transport"]["properties"]["mode"]["enum"] = list(TRANSPORT_MODES)
    listing = props["listing"]["properties"]
    listing["method"]["enum"] = ["GET"]
    del listing["body"]
    listing["fields"]["propertyNames"] = {"enum": list(FIELD_NAMES)}
    return schema


RECIPE_V1_SCHEMA: dict[str, Any] = _contract(STORED_RECIPE_V1_SCHEMA)
