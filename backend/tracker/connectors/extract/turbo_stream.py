"""Reading the data a React Router page streams into itself.

A React Router (Remix) page carries its loader data as a "turbo-stream": JSON
chunks pushed through `window.__reactRouterContext.streamController.enqueue(
"...")`. The first line of the joined chunks is one flat array. A value is an
index into that array; an object's keys are written `"_N"` (the key is the
string at index N); negative indices are sentinels (undefined, null, NaN,
infinities); a list starting with a type tag ("D" a date, "P" a promise, a
class name) is a tagged value, returned as it stands. Shared values are one
index, so a value referenced twice is decoded once and reused.

Only what a page states is read: no promise is awaited and no later line (a
deferred value) is fetched, so a page whose data arrives late decodes to what
it held when served.
"""

from __future__ import annotations

import json
import re

__all__ = ["decode_turbo_stream", "loader_data"]

_ENQUEUE = re.compile(r"streamController\.enqueue\((\"(?:[^\"\\]|\\.)*\")\);", re.S)
#: -1 undefined, -2 hole, -3 NaN, -4 +Infinity, -5 undefined, -6 -Infinity, -7 null.
_SENTINELS: dict[int, object] = {
    -1: None, -2: None, -3: float("nan"), -4: float("inf"), -5: None, -6: float("-inf"), -7: None,
}


def _stream(page: str) -> str | None:
    chunks = _ENQUEUE.findall(page)
    if not chunks:
        return None
    try:
        return "".join(json.loads(chunk) for chunk in chunks)
    except ValueError:
        return None


def decode_turbo_stream(page: str) -> object | None:
    """The page's streamed root value, or None if it carries no readable stream."""
    text = _stream(page)
    first = next((line for line in (text or "").split("\n") if line.strip()), None)
    if first is None:
        return None
    try:
        table = json.loads(first)
    except ValueError:
        return None
    if not isinstance(table, list) or not table:
        return None
    memo: dict[int, object] = {}

    def value(index: object) -> object:
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if index < 0:
            return _SENTINELS.get(index)
        if index >= len(table):
            return None
        if index in memo:
            return memo[index]
        raw = table[index]
        if isinstance(raw, list):
            if raw and isinstance(raw[0], str):
                memo[index] = raw  # a tagged value ("D", "P", a class name)
                return raw
            items: list[object] = []
            memo[index] = items
            items.extend(value(item) for item in raw)
            return items
        if isinstance(raw, dict):
            obj: dict[str, object] = {}
            memo[index] = obj
            for key, item in raw.items():
                name = table[int(key[1:])] if key[1:].isdigit() and int(key[1:]) < len(table) else None
                if isinstance(name, str):
                    obj[name] = value(item)
            return obj
        memo[index] = raw
        return raw

    try:
        return value(0)
    except RecursionError:
        return None  # nested past any page a board serves: not read


def loader_data(page: str, route: str) -> dict | None:
    """One route's loader data (`loaderData[route]`), or None."""
    root = decode_turbo_stream(page)
    data = root.get("loaderData") if isinstance(root, dict) else None
    found = data.get(route) if isinstance(data, dict) else None
    return found if isinstance(found, dict) else None
