"""The page-read rule keeps `read_level`'s order.

`full_read_can_state` restates `read_level`'s precedence by hand to say whether
reading a posting in full could state its level, and collection holds a
guessed posting for that read (`level_awaits_read`). The copies can drift: one
that reads director titles a printed rung never pulls down is wrong. The two
copies are kept rather than rewriting `read_level` as one ordered list of
rules, so this gate holds them together over the committed title snapshot (CI
has no corpus); `bench_level_bands read-agreement` does the same over the live
postings.
"""

from __future__ import annotations

import json

from scripts.bench_level_bands import (
    TITLE_SNAPSHOT,
    read_agreement,
    read_control_failures,
    snapshot_postings,
)
from tracker.levels.ladder import prints_rungs_in_text

SNAPSHOT = json.loads(TITLE_SNAPSHOT.read_text())


def test_the_planted_postings_read_as_planted_and_an_inverted_rule_is_caught():
    assert read_control_failures() == []


def test_the_page_read_rule_agrees_with_read_level_on_every_guessed_title():
    report = read_agreement(snapshot_postings(SNAPSHOT))
    # A regenerated snapshot that held almost no guessed titles would pass by
    # judging nothing.
    assert report.considered >= 1000, f"only {report.considered} guessed titles judged"
    assert report.agrees, (
        f"never read though a read places them {dict(report.skipped)}; "
        f"read though nothing places them {dict(report.wasted)}: {report.samples[:5]}"
    )


def test_a_rule_that_forgot_the_stated_range_is_caught():
    """Planted drift: the rule asks only about printed rungs, without the range
    step."""
    report = read_agreement(
        snapshot_postings(SNAPSHOT),
        lambda job, _family: job.raw_level is None and prints_rungs_in_text(job.company),
    )
    assert report.skipped["google"] > 0 and report.skipped["amazon"] > 0
    assert not report.wasted


def test_a_rule_that_reads_every_guess_is_caught():
    """Planted drift the other way: a read made, and the posting held for it,
    where nothing a read adds can place the level (a firm with no measured
    range, no printed rung)."""
    report = read_agreement(snapshot_postings(SNAPSHOT), lambda _job, _family: True)
    assert report.wasted["ey"] > 0 and not report.skipped
