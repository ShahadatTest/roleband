"""A detail page that refuses us is the source refusing us.

A board whose listing fits on one page yields every row before any detail
read. When those reads hit a block, the breaker opens and every later read
raises `CircuitOpenError` without sending a request. Taken as one posting's
detail error, it would leave the listing complete and the source `ok`, and the
source would keep being asked. A bound that fires inside a detail read is ours,
as it is inside the listing. Any other detail failure stays one posting's.
"""

from __future__ import annotations

import pytest

from tests.factories import NoComp, scope_filter
from tracker.connectors.listing.base import SchemaDriftDetector
from tracker.connectors.recipes.outcome import SourceOutcome, classify_source_outcome
from tracker.platform.breaker import CircuitOpenError
from tracker.platform.http import RetryDeadlineExceeded
from tracker.schema import RawJob
from tracker.workflows import outage
from tracker.workflows.collection import collect_sources

#: Admits the board's postings: a staff software engineer in Germany.
SCOPE = scope_filter(
    bands={"staff"},
    roles={"software_engineering"},
    tracks={"technical"},
    locations={"germany"},
    domains=(),
)


class _OnePageBoard:
    """Two postings on one page; every detail read raises `error`."""

    def __init__(self, company: str, error: Exception) -> None:
        self.company, self.error = company, error
        self.drift = SchemaDriftDetector(f"fixture:{company}")
        self.truncated = False
        self.query_observations: list = []
        self.detail_reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for req in ("1", "2"):
            yield RawJob(company=self.company, req_id=req, title="Staff Engineer",
                         url=f"https://example.test/{self.company}/{req}", locations=["Berlin, Germany"])

    async def hydrate(self, raw: RawJob) -> None:
        self.detail_reads += 1
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "outcome", "reads"),
    [
        (CircuitOpenError("greenhouse", 5, blocked=True), SourceOutcome.BLOCKED, 1),
        (RetryDeadlineExceeded("detail read past the source's budget"), SourceOutcome.BOUNDED, 1),
        # The control: a detail page that fails on its own is one posting's.
        (ValueError("detail page had no body"), SourceOutcome.OK, 2),
    ],
    ids=["blocked", "bounded", "one_posting"],
)
async def test_a_detail_read_the_source_stopped_names_the_source(monkeypatch, error, outcome, reads):
    async def network_up(timeout: float = 5.0) -> bool:
        return True

    monkeypatch.setattr(outage, "network_up", network_up)
    built: list[_OnePageBoard] = []

    def factory(company, adapter, board_token=None, **_kw):
        built.append(_OnePageBoard(company, error))
        return built[-1]

    collections = await collect_sources(
        {"acme": {"adapter": "greenhouse", "board_token": "acme"}}, SCOPE, NoComp(),
        max_list=None, hydrate=True, max_concurrent_sources=8, adapter_factory=factory,
    )

    acme = collections["acme"]
    assert classify_source_outcome({**acme.stats, "list_complete": acme.list_complete}) is outcome
    assert acme.list_complete is (outcome is SourceOutcome.OK), "only a read that reached its end can close"
    assert built[0].detail_reads == reads, "a stopped source is asked nothing more"
