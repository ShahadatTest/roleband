"""What each kind of listing read may change: one table.

A listing read's outcome feeds six owners, each deciding its own effect: run
status (`CLEAN`), absence counting (`RESETS_ABSENCE`), targeted retry (`RETRYABLE`), learned bounds
(`tuning_pass.is_teachable`), binding activation (`decide_binding_activation`)
and closure (`judge_listing` -> `should_close_missing`). The rules
("bounds we impose are never evidence against a source", "capped and bounded
map to NON_AUTHORITATIVE: no closure, no absence reset, no binding
activation", "truncated runs teach; bounded, capped, errored and blocked runs
do not") would hold across those owners only by each one's own reading.

Each row is EVIDENCE, the stats and drift a real read leaves, taken through
`judge_listing` and `classify_source_outcome` as the collector does; the
columns are what every owner then decides. A change to any owner that breaks
a rule fails here by name. No second classifier: every column calls the
owner itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from tracker.connectors.recipes.outcome import (
    CLEAN,
    RESETS_ABSENCE,
    RETRYABLE,
    SourceOutcome,
    classify_source_outcome,
)
from tracker.db.binding import decide_binding_activation
from tracker.platform.drift import SchemaDriftDetector
from tracker.workflows.collection_types import SourceCollection, empty_stats, judge_listing
from tracker.workflows.run_persistence import should_close_missing
from tracker.workflows.tuning_pass import is_teachable


@dataclass(frozen=True)
class Read:
    """What a read left behind."""

    scanned: int = 40
    errors: tuple[str, ...] = ()
    capped: bool = False
    bounded: bool = False
    truncated: bool = False
    suspended: bool = False
    blocked: bool = False
    unattempted: bool = False
    lost_page: bool = False
    lost_rows: int = 0
    proven_empty: bool = False
    cut: bool = False  # something other than the board's end stopped it


def _judge(read: Read) -> tuple[SourceOutcome, dict, bool]:
    stats = empty_stats()
    stats.update(
        scanned=read.scanned, errors=list(read.errors), capped=read.capped,
        bounded=read.bounded, suspended=read.suspended, blocked=read.blocked,
        unattempted=read.unattempted,
    )
    drift = SchemaDriftDetector("matrix")
    if read.lost_page:
        drift.invalidate_listing("a page failed")
    for _ in range(read.lost_rows):
        drift.drop_record("an unreadable row")
    if read.proven_empty:
        drift.board_empty("the board says it lists nothing")
    adapter = SimpleNamespace(drift=drift, truncated=read.truncated)
    complete = judge_listing(
        stats, None if read.unattempted else adapter,
        cut=read.cut or read.bounded or read.suspended,
    )
    # Recorded as the collector and the directory read record it, so the
    # outcome derivation stays a function of the stats.
    stats["list_complete"] = complete
    return classify_source_outcome(stats), stats, complete


def _binding():
    return SimpleNamespace(closure_capability="none", connector_kind="adapter", status="stable")


ROWS = [
    # name, read, outcome, clean, resets absence, retry, teaches, activates, closes
    ("complete", Read(), SourceOutcome.OK, True, False, False, True, True, True),
    ("operator cap", Read(capped=True), SourceOutcome.CAPPED, True, False, False, False, False, False),
    ("our time bound", Read(bounded=True), SourceOutcome.BOUNDED, False, False, True, False, False, False),
    ("our page ceiling", Read(truncated=True), SourceOutcome.TRUNCATED, False, False, False, True, False, False),
    ("host asleep", Read(suspended=True), SourceOutcome.SUSPENDED, False, False, True, False, False, False),
    ("a few rows lost", Read(scanned=400, lost_rows=1), SourceOutcome.LOSSY, False, False, False, True, False, False),
    ("proven empty", Read(scanned=0, proven_empty=True), SourceOutcome.EMPTY, True, False, False, True, False, False),
    ("a page lost", Read(lost_page=True), SourceOutcome.DEGRADED, False, True, True, True, False, False),
    ("failed", Read(scanned=0, errors=("ReadError",)), SourceOutcome.FAILED, False, True, True, False, False, False),
    ("refused", Read(scanned=0, errors=("403",), blocked=True), SourceOutcome.BLOCKED, False, True, False, False, False, False),
    ("never reached", Read(scanned=0, unattempted=True), SourceOutcome.UNATTEMPTED, False, False, True, True, False, False),
]


@pytest.mark.parametrize(
    ("read", "outcome", "clean", "resets", "retry", "teaches", "activates", "closes"),
    [row[1:] for row in ROWS],
    ids=[row[0] for row in ROWS],
)
def test_each_read_has_exactly_these_effects(
    read, outcome, clean, resets, retry, teaches, activates, closes
):
    got, stats, complete = _judge(read)
    assert got is outcome
    collection = SourceCollection(
        company="matrix", enriched=[], seen_keys=set(), stats=stats, drift=[],
        list_complete=complete,
    )
    effects = {
        "clean": got in CLEAN,
        "resets": got in RESETS_ABSENCE,
        "retry": got in RETRYABLE,
        "teaches": is_teachable(stats),
        "activates": decide_binding_activation(
            binding=_binding(), outcome=got, scan_mode="reconcile", scanned=stats["scanned"]
        ).activate,
        "closes": should_close_missing(collection, max_list=40 if read.capped else None),
    }
    assert effects == {
        "clean": clean, "resets": resets, "retry": retry,
        "teaches": teaches, "activates": activates, "closes": closes,
    }


def test_no_bound_of_ours_is_ever_evidence_against_the_source():
    """The rule stated once over the table: a read cut by our cap, time bound,
    page ceiling or sleeping host never resets absence,
    never activates and never closes."""
    ours = {"operator cap", "our time bound", "our page ceiling", "host asleep"}
    for name, read, *_ in ROWS:
        if name not in ours:
            continue
        got, stats, complete = _judge(read)
        assert got not in RESETS_ABSENCE, name
        collection = SourceCollection(
            company="matrix", enriched=[], seen_keys=set(), stats=stats, drift=[],
            list_complete=complete,
        )
        assert not should_close_missing(collection, max_list=40 if read.capped else None), name
