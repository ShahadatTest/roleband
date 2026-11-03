"""One date a posting's pay grade is read for, whoever reads the level.

Google's ranges are measured per year (`PAY_GRADES`, keyed 2026) and Google
states no posting date. If the scan read the year off `posted_at or now` while
relevel read `first_posted_at or posted_at or first_seen`, from 1 January every
re-observation would write one reading and every relevel the other back.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.factories import SENIOR_PM_SCOPE, Allowed, NoComp, PayingSource
from tracker.db.models import Job
from tracker.enrich import level_mapper
from tracker.enrich.classify import classify_family
from tracker.enrich.level_mapper import level_date, read_level
from tracker.platform.ratelimit import RateLimiterPool
from tracker.schema import LevelBasis, RawJob, SourceDisclosedComp
from tracker.workflows import collection as collection_module
from tracker.workflows.collection import collect_source
from tracker.workflows.collection_types import SourceLookups
from tracker.workflows.relevel import stored_raw

_SEEN = datetime(2026, 9, 10, tzinfo=UTC)
_NEXT_YEAR = datetime(2027, 1, 15, tzinfo=UTC)
# Product Manager II's 2026 range at Google: L5, senior.
_L5 = (163_000, 236_000)


@pytest.fixture
def next_year(monkeypatch):
    monkeypatch.setattr(level_mapper, "_now", lambda: _NEXT_YEAR)


class _Undated(PayingSource):
    """Google's listing: no posting date on any row."""

    async def fetch(self):
        async for raw in super().fetch():
            raw.posted_at = None
            yield raw


def _stored(**over) -> Job:
    row = dict(
        company="google", req_id="pm", dedupe_key="google:pm", title="Product Manager, Google Analytics",
        url="https://example.test/pm", raw_level=None, posted_at=None, first_posted_at=None,
        first_seen=_SEEN, disclosed_base_min=_L5[0], disclosed_base_max=_L5[1],
        disclosed_currency="USD", disclosed_pay_basis="base", disclosed_pay_period="year",
    )
    row.update(over)
    return Job(**row)


def _scanned(**over) -> RawJob:
    """The row as the scan reads it, with what collection holds for it."""
    pay = SourceDisclosedComp(base_min=_L5[0], base_max=_L5[1], currency="USD",
                              pay_basis="base", pay_period="year")
    row = dict(company="google", req_id="pm", title="Product Manager, Google Analytics", url="",
               source_disclosed_comp=pay, posted_at=None, held_first_seen=_SEEN)
    row.update(over)
    return RawJob(**row)


def _read(raw: RawJob):
    return read_level(raw, classify_family(raw))


def test_the_scan_and_relevel_read_one_year_for_a_row_with_no_posted_date(next_year):
    scanned, stored = _scanned(), stored_raw(_stored())
    assert level_date(scanned) == level_date(stored) == _SEEN
    assert _read(scanned) == _read(stored)
    assert _read(scanned).basis is LevelBasis.PAY_GRADE


def test_the_earliest_employer_date_decides_before_our_first_sight(next_year):
    """A re-dated posting (a 2027 date on a 2026 posting) keeps its first
    year, in the scan as in relevel: `first_posted_at` is never raised."""
    first = datetime(2026, 11, 2, tzinfo=UTC)
    scanned = _scanned(posted_at=_NEXT_YEAR, held_first_posted_at=first)
    stored = stored_raw(_stored(posted_at=_NEXT_YEAR, first_posted_at=first))
    assert level_date(scanned) == level_date(stored) == first
    assert _read(scanned) == _read(stored)


def test_a_posting_first_seen_this_year_reads_this_years_ranges(next_year):
    """Negative control: nothing held, nothing dated, so the year is now's,
    and 2027's ranges are unmeasured."""
    raw = _scanned(held_first_seen=None)
    assert level_date(raw) == _NEXT_YEAR
    assert _read(raw).basis is not LevelBasis.PAY_GRADE


@pytest.mark.asyncio
async def test_the_scan_reads_a_held_rows_first_sight(monkeypatch, next_year):
    monkeypatch.setattr(collection_module, "collection_access", lambda *a, **kw: Allowed())
    source = _Undated({"held": _L5, "new": _L5})
    collection = await collect_source(
        "google", {"adapter": "google"}, SENIOR_PM_SCOPE, NoComp(),
        max_list=None, hydrate=True, limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, **kw: source,
        lookups=SourceLookups(held_dates={"google:held": (None, _SEEN)}),
    )
    kept = {job.raw.req_id: job for job in collection.enriched}
    assert kept["held"].level_basis is LevelBasis.PAY_GRADE
    # First seen in this read, in a year whose ranges are unmeasured.
    assert kept["new"].level_basis is not LevelBasis.PAY_GRADE
