"""The repeated-failover report: a reader that misses one company's template."""

from __future__ import annotations

from scripts.check_detail_failovers import FAILOVER_MESSAGE, flagged, summarize


def _note(req: str, company: str = "micron", reason: str = "pay paragraph changed") -> dict:
    return {"message": FAILOVER_MESSAGE, "company": company, "connector": "eightfold",
            "reason": reason, "req": req}


def test_one_reason_across_many_postings_of_one_company_is_flagged():
    runs = [
        (1, [_note(str(n)) for n in range(6)]),
        # The same postings read again in a later run are the same postings.
        (2, [_note(str(n)) for n in range(6)]),
        (2, [_note("x", company="netflix")]),
    ]

    patterns = summarize(runs)

    [micron] = flagged(patterns, min_postings=5, max_repeats=99)
    assert (micron.company, len(micron.postings), micron.notes, len(micron.runs)) == ("micron", 6, 12, 2)
    assert micron.repeats == 2
    assert [p.company for p in patterns] == ["micron", "netflix"]


def test_scattered_failovers_and_other_drift_are_not_flagged():
    runs = [
        (1, [_note("1"), _note("2", reason="headings missing"), _note("3", company="qualcomm")]),
        (2, [{"message": "non-200 job detail", "company": "micron", "req": "4"}, "not a note"]),
    ]

    patterns = summarize(runs)

    assert not flagged(patterns, min_postings=2, max_repeats=2)
    assert sum(p.notes for p in patterns) == 3


def test_one_posting_failing_over_in_run_after_run_is_flagged_as_never_stored():
    runs = [(run_id, [_note("43", company="radai")]) for run_id in range(4)]
    # Two notes for one posting in a single run are one sighting, not two runs.
    runs.append((9, [_note("7", company="acme"), _note("7", company="acme")]))

    bad = flagged(summarize(runs), min_postings=99, max_repeats=4)

    assert [(p.company, p.repeats) for p in bad] == [("radai", 4)]
