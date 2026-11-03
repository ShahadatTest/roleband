"""This machine's time zone: the one answer every local calendar reads.

"Today" for the statistics and the Board, the digest's days, a notification's
day label, the schedule plan's days of the week and ready-by time, and the
supervisor's daily slots are all wall-clock facts in the user's zone, so they
all read it here. It is a zone with its daylight-saving rules, never the fixed
offset of the moment: an offset taken today is wrong for a date across a change.
The dashboard sends its zone with every schedule plan change and the plan
stores it; this answers for a plan nobody has edited yet. Imports no other
tracker module.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MARKER = "zoneinfo/"
#: Where the machine keeps its zone: a link to a named zone, or a copy of its rules.
_LOCALTIME = Path("/etc/localtime")


def zone_name_from_link(target: str | None) -> str | None:
    """The IANA name in a `/etc/localtime` link target, e.g.
    `/var/db/timezone/zoneinfo/Europe/Stockholm` -> `Europe/Stockholm`."""
    if not target or _MARKER not in target:
        return None
    name = target.split(_MARKER, 1)[1].strip("/")
    return name or None


def local_zone() -> ZoneInfo:
    """`TZ` when it names a zone, else the zone `/etc/localtime` links to, else
    the rules in `/etc/localtime` itself (a container copies the file rather
    than linking it), else UTC. A machine this cannot read is UTC: a wrong zone
    shifts a day boundary or a ready-by time, it never stops a scan.

    Read on every call, never cached: a process that lives for weeks must see
    the zone the machine is set to now."""
    localtime = _LOCALTIME
    candidates = [os.environ.get("TZ", "").lstrip(":")]
    try:
        candidates.append(zone_name_from_link(os.readlink(localtime)) or "")
    except OSError:
        pass
    for name in candidates:
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    try:
        with localtime.open("rb") as rules:
            return ZoneInfo.from_file(rules)
    except (OSError, ValueError):
        return ZoneInfo("UTC")
