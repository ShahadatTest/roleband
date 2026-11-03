"""Pure server-side diff between two adjacent lineage members.

Powers the stack-deck "what changed each time it was posted" panel. Compares the
newer member against the previous one and returns only the fields that moved, so
the dashboard stays a dumb renderer and the logic is unit-testable. Reads the live
`disclosed_*` band (what the posting stated), never the estimate.
"""

from __future__ import annotations

from typing import Any


def _band(member: Any) -> list[int] | None:
    lo = getattr(member, "disclosed_base_min", None)
    hi = getattr(member, "disclosed_base_max", None)
    if lo is None and hi is None:
        return None
    return [lo, hi]


def build_member_diff(prev: Any, cur: Any) -> dict:
    """Return {field: change} for every field that differs from prev -> cur.

    ``prev``/``cur`` are objects with the Job attributes (title, locations,
    level_band, family, comp_median, comp_currency, disclosed_base_min/max,
    disclosed_currency, disclosed_pay_basis). An empty dict means nothing
    material changed.
    """
    diff: dict = {}

    if getattr(prev, "title", None) != getattr(cur, "title", None):
        diff["title"] = {"from": prev.title, "to": cur.title}

    if getattr(prev, "level_band", None) != getattr(cur, "level_band", None):
        diff["level_band"] = {"from": prev.level_band, "to": cur.level_band}

    prev_band, cur_band = _band(prev), _band(cur)
    if prev_band != cur_band:
        diff["disclosed_band"] = {
            "from": prev_band,
            "to": cur_band,
            "currency": getattr(cur, "disclosed_currency", None)
            or getattr(prev, "disclosed_currency", None),
        }

    if getattr(prev, "disclosed_pay_basis", None) != getattr(cur, "disclosed_pay_basis", None):
        diff["pay_basis"] = {
            "from": getattr(prev, "disclosed_pay_basis", None),
            "to": getattr(cur, "disclosed_pay_basis", None),
        }

    prev_locs = list(getattr(prev, "locations", None) or [])
    cur_locs = list(getattr(cur, "locations", None) or [])
    added = [loc for loc in cur_locs if loc not in prev_locs]
    removed = [loc for loc in prev_locs if loc not in cur_locs]
    if added or removed:
        diff["locations"] = {"added": added, "removed": removed}

    if getattr(prev, "comp_median", None) != getattr(cur, "comp_median", None):
        diff["comp_median"] = {
            "from": getattr(prev, "comp_median", None),
            "to": getattr(cur, "comp_median", None),
            "currency": getattr(cur, "comp_currency", None)
            or getattr(prev, "comp_currency", None),
        }

    return diff
