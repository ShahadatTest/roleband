"""Structured output for chat-shaped backends.

Apple FM gets schema conformance for free (guided generation against an
`@fm.generable`). An OpenAI-compatible or Anthropic endpoint does not: it
returns a text turn, so the schema has to be carried in the prompt and enforced
on the way back.

Kept separate from any one backend because oMLX and the cloud endpoints need
IDENTICAL treatment — if they differed, a routing decision would silently change
what the model was asked for, and the router's whole premise is that the tiers
are interchangeable for a given task.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _field_line(name: str, spec: dict, required: bool) -> str:
    kind = spec.get("type")
    if not kind and "anyOf" in spec:
        kinds = [item.get("type") for item in spec["anyOf"] if isinstance(item, dict)]
        kind = "|".join(k for k in kinds if k)
    enum = spec.get("enum")
    detail = f"one of {json.dumps(enum)}" if enum else (kind or "any")
    suffix = "" if required else " (may be null)"
    description = spec.get("description")
    note = f" — {description}" if description else ""
    return f'- "{name}": {detail}{suffix}{note}'


def json_instruction(schema: type) -> str:
    """A compact field contract for `schema`, appended to the system prompt.

    Uses the Pydantic model's own JSON schema so the instruction can never drift
    from the validator the caller will run.
    """
    try:
        spec = schema.model_json_schema()
    except AttributeError:  # not a Pydantic model — ask for the name only
        return f"Return one JSON object matching the {getattr(schema, '__name__', 'requested')} schema."

    properties = spec.get("properties", {})
    required = set(spec.get("required", []))
    defs = spec.get("$defs", {})

    lines = []
    for name, raw in properties.items():
        resolved = raw
        ref = raw.get("$ref") or next(
            (item.get("$ref") for item in raw.get("anyOf", []) if isinstance(item, dict) and item.get("$ref")),
            None,
        )
        if ref:
            key = ref.rsplit("/", 1)[-1]
            resolved = {**raw, **defs.get(key, {})}
        lines.append(_field_line(name, resolved, name in required))

    return (
        "Return ONE JSON object and nothing else. No prose, no code fence, no "
        "explanation. The object has exactly these keys:\n" + "\n".join(lines)
    )


def parse_json_object(content: str) -> dict[str, Any] | None:
    """Best-effort single JSON object out of a chat turn; None if there isn't one.

    Tolerates a code fence and a leading sentence (reasoning models emit both
    despite JSON mode) but never invents structure — an unparseable turn is a
    validation failure the caller must classify, not something to paper over.
    """
    value = (content or "").strip()
    if not value:
        return None
    fenced = _FENCE.fullmatch(value)
    if fenced:
        value = fenced.group(1)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        if start < 0:
            return None
        try:
            parsed, _ = json.JSONDecoder().raw_decode(value[start:])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
