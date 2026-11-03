"""Every category an opt-in setting has shipped, and what became of it.

Roles, seniority bands, career tracks and locations are stored as the slugs a
user switched ON. That is right for what they are, short lists of things the
user picked, and it is why a category added later arrives OFF: a new country or
role family switched on for everyone would widen boards with things nobody
asked for.

It is wrong for a category that is RENAMED or SPLIT. The stored slug stops
matching anything, the setting reads without it, and whatever the user had on
silently turns off. This registry makes the repair a declaration instead of a
hand-written migration: a retired slug names its heirs, and a stored setting is
read through them (`carry_forward`), so a split `director_plus` turns on both of
its replacements for everyone who had it on. `tests/test_slug_history.py` fails
a slug that leaves the taxonomy without an entry here.

It also says what is NEW to a user. A save records the full list the user saw
(`settings_store`); a setting saved before that existed saw the frozen
`baseline`. A current slug outside what the user saw is new, and the scope
catalog marks it until the next save.

Pure data, no tracker imports: the live slug lists are compared against it by
the test, never read here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path

__all__ = ["AXES", "baseline", "carry_forward", "known", "renamed"]

AXES = ("roles", "bands", "tracks", "locations")
_PATH = Path(__file__).with_name("slug_history.json")


@cache
def _axes() -> dict[str, dict]:
    return json.loads(_PATH.read_text())["axes"]


def baseline(axis: str) -> frozenset[str]:
    """What a user who saved before `seen` was recorded had in front of them."""
    return frozenset(_axes()[axis]["baseline"])


def known(axis: str) -> frozenset[str]:
    """Every slug this axis has ever shipped."""
    entry = _axes()[axis]
    return frozenset(entry["baseline"]) | frozenset(entry["added"])


def renamed(axis: str) -> dict[str, tuple[str, ...]]:
    """Retired slug -> the slugs that replaced it (empty: retired, no heir)."""
    return {old: tuple(new) for old, new in _axes()[axis]["renamed"].items()}


def carry_forward(axis: str, slugs: Iterable[str]) -> set[str]:
    """`slugs` with every retired slug replaced by its heirs, transitively.

    A slug renamed twice (a -> b -> c) reaches `c`. Cycle-safe: a slug is
    expanded at most once, so a bad entry cannot hang a settings read.
    """
    heirs = renamed(axis)
    out: set[str] = set()
    pending = [slug for slug in slugs if isinstance(slug, str)]
    expanded: set[str] = set()
    while pending:
        slug = pending.pop()
        if slug in heirs:
            if slug not in expanded:
                expanded.add(slug)
                pending.extend(heirs[slug])
            continue
        out.add(slug)
    return out
