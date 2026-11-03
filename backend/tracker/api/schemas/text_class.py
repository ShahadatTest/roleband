"""What kind of text a response field carries (docs/copy.md).

The dashboard says the product's words itself, from its catalog, so a string the
API sends is one of:

- ``code``: a code or slug the client turns into words (a category, a status).
- ``content``: third-party text, shown as written and never translated (a
  role's title, a company's name, an employer's heading).
- ``record``: text stored as agreed or as it happened, never re-rendered (a
  consent, a notification's stored fallback).
- ``diagnostic``: engineering text shown only behind the diagnostics toggle.
- ``identifier``: an id, a URL, a path.

Declared on the field, it reaches ``openapi.json`` as ``x-text``::

    title: str = Field(json_schema_extra=text("content"))

``tests/test_api_text_classes.py`` counts the display-named fields that declare
none, and the count only falls.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic.config import JsonDict

TextClass = Literal["code", "content", "record", "diagnostic", "identifier"]
TEXT_CLASSES: frozenset[str] = frozenset(get_args(TextClass))


def text(kind: TextClass) -> JsonDict:
    """The ``json_schema_extra`` that declares a field's text class. An unknown
    class is refused when the model is defined: a module mypy does not check
    could otherwise publish a class no client knows."""
    if kind not in TEXT_CLASSES:
        raise ValueError(f"{kind!r} is not a text class; one of {sorted(TEXT_CLASSES)}")
    return {"x-text": kind}
