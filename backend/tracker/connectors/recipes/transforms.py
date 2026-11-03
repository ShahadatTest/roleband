"""Bounded transform allowlist for recipe fields.

No arbitrary code, eval or JavaScript: every op here is a named function over
strings. `regex_capture` runs the recipe's pattern under three bounds
(`pattern_problem` and `_MAX_INPUT_LEN`); it never executes recipe-supplied code.

Python's `re` has no timeout, and the pattern runs on the event loop over text a
third party serves, so a pattern that backtracks catastrophically would stall
the process. The shape that does is a repeat inside a repeat (`(\\w+\\s?)+`),
and it is refused when the recipe is checked; the text a pattern reads is capped
too, which bounds what any other slow pattern can cost.
"""

from __future__ import annotations

import re
import re._parser as sre_parse
from collections.abc import Sequence
from urllib.parse import urljoin

from tracker.platform.util import parse_datetime

__all__ = ["TransformError", "apply_transforms", "pattern_problem"]

_WS_RE = re.compile(r"\s+")
_MAX_PATTERN_LEN = 200
#: The text a pattern reads. Fields are ids, titles, places and short labels.
_MAX_INPUT_LEN = 2000
_REPEATS = {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT, sre_parse.POSSESSIVE_REPEAT}


def _repeats_within(node: object) -> bool:
    """Whether a parsed pattern holds a repeat of more than one."""
    if isinstance(node, (list, tuple, sre_parse.SubPattern)):
        items = list(node)
        if len(items) == 2 and items[0] in _REPEATS:
            low, high, sub = items[1]
            return high > 1 or _repeats_within(sub)
        return any(_repeats_within(item) for item in items)
    return False


def _nested_repeat(node: object) -> bool:
    """Whether a repeat of more than one holds another: the shape that
    backtracks without end on text it almost matches."""
    if isinstance(node, (list, tuple, sre_parse.SubPattern)):
        items = list(node)
        if len(items) == 2 and items[0] in _REPEATS:
            low, high, sub = items[1]
            if high > 1 and _repeats_within(sub):
                return True
            return _nested_repeat(sub)
        return any(_nested_repeat(item) for item in items)
    return False


def pattern_problem(pattern: object) -> str | None:
    """Why `regex_capture` refuses `pattern`, or None when it may run."""
    if not isinstance(pattern, str) or not pattern:
        return "regex_capture: missing pattern"
    if len(pattern) > _MAX_PATTERN_LEN:
        return "regex_capture: pattern too long"
    try:
        parsed = sre_parse.parse(pattern)
    except re.error as exc:
        return f"regex_capture: bad pattern: {exc}"
    if _nested_repeat(parsed):
        return "regex_capture: a repeated group that holds a repeat of its own can backtrack without end; repeat only one of them"
    return None


class TransformError(ValueError):
    """A transform could not be applied. Surfaced as a field/validation error,
    never a crash."""


def _trim(value: str, spec: dict, ctx: dict) -> str:
    return value.strip()


def _collapse_whitespace(value: str, spec: dict, ctx: dict) -> str:
    return _WS_RE.sub(" ", value).strip()


def _lower(value: str, spec: dict, ctx: dict) -> str:
    return value.lower()


def _upper(value: str, spec: dict, ctx: dict) -> str:
    return value.upper()


def _join(value, spec: dict, ctx: dict) -> str:
    sep = spec.get("sep", " ")
    if isinstance(value, str):
        return value
    return sep.join(str(v) for v in value)


def _resolve_url(value: str, spec: dict, ctx: dict) -> str:
    base = ctx.get("base_url")
    return urljoin(base, value) if base else value


def _parse_date(value: str, spec: dict, ctx: dict) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        raise TransformError(f"parse_date: unrecognized date {value!r}")
    return parsed.isoformat()


def _regex_capture(value: str, spec: dict, ctx: dict) -> str:
    pattern = spec.get("pattern")
    problem = pattern_problem(pattern)
    if problem is not None:
        raise TransformError(problem)
    match = re.compile(str(pattern)).search(value[:_MAX_INPUT_LEN])
    if not match:
        return ""
    # Prefer an explicit capture group; fall back to the whole match.
    return match.group(1) if match.groups() else match.group(0)


_OPS = {
    "trim": _trim,
    "collapse_whitespace": _collapse_whitespace,
    "lower": _lower,
    "upper": _upper,
    "join": _join,
    "resolve_url": _resolve_url,
    "parse_date": _parse_date,
    "regex_capture": _regex_capture,
}


def apply_transforms(value, transforms: Sequence[dict], ctx: dict):
    """Run a value through its declared transform pipeline, in order.

    `join` may consume a list; every other op operates on a string, so a list
    reaching a string-only op is joined with a space first. `ctx` carries
    runtime context a transform needs (`base_url` for `resolve_url`).
    """
    result = value
    for spec in transforms:
        op = spec["op"]
        func = _OPS.get(op)
        if func is None:  # compiler already rejects unknown ops; defense in depth
            raise TransformError(f"unknown transform op {op!r}")
        if op != "join" and isinstance(result, list):
            result = " ".join(str(v) for v in result)
        result = func(result, spec, ctx)
    return result
