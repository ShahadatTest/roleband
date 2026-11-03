"""One judgement of a listing read that has ended.

The collector (`collect_source`) and the directory read (`check_company`)
must use the same rule. The adapter here is a namespace around the real drift
recorder: the recorder is what the judgement reads, so it is never faked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tracker.platform.drift import SchemaDriftDetector
from tracker.workflows.collection_types import empty_stats, judge_listing


def _adapter(*, truncated: bool = False) -> SimpleNamespace:
    return SimpleNamespace(drift=SchemaDriftDetector("board"), truncated=truncated)


def _stats(scanned: int = 3, **over):
    stats = empty_stats()
    stats["scanned"] = scanned
    stats.update(over)
    return stats


def test_a_read_that_ran_to_its_end_is_complete_and_its_facts_are_recorded():
    stats = _stats()
    assert judge_listing(stats, _adapter(), cut=False) is True
    assert (stats["truncated"], stats["records_dropped"]) == (False, 0)
    assert (stats["listing_invalidated"], stats["empty_proven"]) == (False, False)


def test_zero_rows_at_the_natural_end_are_never_complete():
    adapter = _adapter()
    stats = _stats(scanned=0)
    assert judge_listing(stats, adapter, cut=False) is False
    assert stats["listing_invalidated"] is True
    assert [a["message"] for a in adapter.drift.alerts] == ["listing yielded no postings"]


def test_a_board_proven_empty_is_recorded_and_still_not_complete():
    adapter = _adapter()
    adapter.drift.board_empty("the board's own zero")
    stats = _stats(scanned=0)
    assert judge_listing(stats, adapter, cut=False) is False
    assert (stats["empty_proven"], stats["listing_invalidated"]) == (True, False)


@pytest.mark.parametrize("over,cut", [
    ({"errors": ["ReadError (no detail)"]}, False),
    ({"unattempted": True}, False),
    ({}, True),
], ids=["errored", "unattempted", "cut"])
def test_a_read_that_did_not_end_on_its_own_is_neither_settled_nor_complete(over, cut):
    adapter = _adapter()
    stats = _stats(scanned=0, **over)
    assert judge_listing(stats, adapter, cut=cut) is False
    # A short read is explained by what stopped it, never judged by its rows.
    assert stats["listing_invalidated"] is False and adapter.drift.alerts == []


def test_a_page_ceiling_or_a_lost_row_is_not_complete():
    stats = _stats()
    assert judge_listing(stats, _adapter(truncated=True), cut=False) is False
    assert stats["truncated"] is True

    adapter = _adapter()
    adapter.drift.drop_record("posting missing title")
    stats = _stats()
    assert judge_listing(stats, adapter, cut=False) is False
    assert stats["records_dropped"] == 1 and stats["listing_invalidated"] is False


def test_no_adapter_is_never_complete():
    stats = _stats()
    assert judge_listing(stats, None, cut=False) is False
    assert (stats["records_dropped"], stats["truncated"]) == (0, False)


def test_an_adapter_with_no_recorder_is_judged_by_the_rest():
    # Duck-typed adapters (test fakes, recipe bridges) carry no drift recorder.
    assert judge_listing(_stats(), SimpleNamespace(), cut=False) is True
    assert judge_listing(_stats(), SimpleNamespace(truncated=True), cut=False) is False
