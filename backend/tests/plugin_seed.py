"""How a test says a plugin has read companies whole.

A plugin's rows for a company are read once it published that company whole:
`plugin_coverage.complete_at`. Pure tests pass `covers(...)` to
`providers_from`; database tests add the rows with `cover(...)`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from tracker.db.models import PluginCoverage

AT = datetime(2026, 10, 1, tzinfo=UTC)
#: Every company the pure tests name.
COMPANIES = ("acme", "apple", "globex", "google", "meta")


def covers(pid: str, *slots: str, companies: Iterable[str] = COMPANIES, at: datetime = AT) -> dict:
    """`providers_from`'s coverage: `pid` read each of `companies` whole in each slot."""
    return {pid: {slot: dict.fromkeys(companies, at) for slot in slots}}


def cover(db, provider: str, slots: Iterable[str], companies: Iterable[str], at: datetime = AT) -> None:
    """Add the coverage rows saying `provider` read `companies` whole in `slots`."""
    for slot in slots:
        for company in companies:
            db.add(PluginCoverage(provider=provider, slot=slot, company_slug=company, rows=1,
                                  last_published_at=at, last_attempt_at=at, complete_at=at))
