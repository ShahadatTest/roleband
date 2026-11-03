"""`/api/status` derivation-freshness projection.

`derivation_status` joins the enabled POST_PASSES table against the
`derivation_state` rows and marks each pass fresh/stale. The property that
must hold: an enabled pass with no state row, one that is
registered but has never run — reports `stale=True` instead of being invisible.
Runs without a DB: a fake session supplies the rows, POST_PASSES is swapped for
a small controlled table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tracker.workflows import schedule_status
from tracker.workflows.post_passes import PostPass

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def scalars(self, *_a, **_k):
        return _Scalars(self._rows)


def _row(name, *, age_hours):
    ts = NOW - timedelta(hours=age_hours)
    return SimpleNamespace(name=name, last_ok_at=ts, last_run_at=ts, last_status="ok")


async def _noop(ctx):  # pass body is irrelevant to the projection
    return None


@pytest.mark.asyncio
async def test_enabled_pass_freshness_and_never_run_is_stale(monkeypatch):
    table = (
        PostPass("fresh", _noop),
        PostPass("old", _noop),
        PostPass("never", _noop),  # enabled but no state row
        PostPass("off", _noop, enabled=lambda s: False),
    )
    monkeypatch.setattr(schedule_status, "POST_PASSES", table)

    rows = [_row("fresh", age_hours=1), _row("old", age_hours=100)]
    settings = SimpleNamespace(freshness_max_hours=24)

    result = await schedule_status.derivation_status(_Session(rows), settings, NOW)
    by_name = {d["name"]: d for d in result}

    assert by_name["fresh"]["stale"] is False
    assert by_name["fresh"]["age_hours"] == 1.0
    assert by_name["old"]["stale"] is True
    # Registered, enabled, never produced anything: stale.
    assert by_name["never"]["stale"] is True
    assert by_name["never"]["last_ok_at"] is None
    # Disabled passes are never stale and carry no freshness fields.
    assert by_name["off"] == {"name": "off", "enabled": False, "stale": False}

    stale = [d["name"] for d in result if d["stale"]]
    assert stale == ["old", "never"]
