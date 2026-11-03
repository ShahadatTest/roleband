"""Scrape-priority run-lock acquisition.

A scrape wait-retries for the shared advisory lock instead of skipping instantly,
so it takes priority over the role-discovery scan (which releases the lock between
companies). These pin the retry-until-free and timeout-then-give-up behavior
without a real database.
"""

from __future__ import annotations

import pytest

from tracker.platform.locks import try_advisory_lock


class _FakeSession:
    """`scalar()` returns each queued pg_try_advisory_lock result in turn."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def scalar(self, *args, **kwargs):
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return result


@pytest.mark.asyncio
async def test_waits_and_acquires_when_lock_frees():
    # Held for two polls (discovery still between companies), then free.
    session = _FakeSession([False, False, True])
    got = await try_advisory_lock(session, 91237, wait_seconds=1.0, retry_seconds=0.001)
    assert got is True
    assert session.calls == 3  # it retried rather than skipping on the first miss


@pytest.mark.asyncio
async def test_times_out_when_lock_never_frees():
    # Another scrape holds it for its whole run -> we give up (no concurrent runs).
    session = _FakeSession([False])
    got = await try_advisory_lock(session, 91237, wait_seconds=0.01, retry_seconds=0.002)
    assert got is False
    assert session.calls >= 2  # polled more than once before timing out


@pytest.mark.asyncio
async def test_acquires_immediately_when_free():
    session = _FakeSession([True])
    got = await try_advisory_lock(session, 91237, wait_seconds=1.0, retry_seconds=0.001)
    assert got is True
    assert session.calls == 1
