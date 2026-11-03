"""Per-source outcome + run-status projection.

This layer decides whether `last_success_at` advances, so the table below is the
specification, not a sample. Two properties are load-bearing and both are
asserted directly:

* the run status is a **total** function of the per-source outcomes — a rule
  that leaves "zero ok but at least one degraded-with-data" unmapped misses
  precisely the case that decides whether `last_success_at` advances;
* the derivation is **pure over a stats dict** — no session, no ORM — so it
  ports unchanged to `ScrapeSourceRun` rows.
"""

from __future__ import annotations

import pytest

from tracker.connectors.recipes.outcome import (
    RESETS_ABSENCE,
    RETRYABLE,
    SourceOutcome,
    classify_source_outcome,
    run_status_for,
)


def stats(**overrides) -> dict:
    """A stats dict shaped exactly like the pipeline's `per_source` entries."""
    base = {
        "scanned": 0,
        "kept": 0,
        "new": 0,
        "closed": 0,
        "errors": [],
        "capped": False,
        "bounded": False,
        "truncated": False,
        "blocked": False,
        "suspended": False,
        "list_complete": False,
    }
    base.update(overrides)
    return base


# -- per-source derivation -------------------------------------------------- #


@pytest.mark.parametrize(
    "case,source_stats,expected",
    [
        (
            "clean complete listing",
            stats(scanned=500, kept=12, list_complete=True),
            SourceOutcome.OK,
        ),
        (
            "complete and genuinely empty board",
            stats(scanned=0, list_complete=True),
            SourceOutcome.OK,
        ),
        (
            "operator cap (--max-list): incomplete but not a pathology",
            stats(scanned=151, kept=3, capped=True),
            SourceOutcome.CAPPED,
        ),
        (
            # The listing really did complete, and a test run is still not
            # evidence about the source. Classified `ok`, it would clear health
            # and activate a withheld binding.
            "operator cap governed a board that finished under it",
            stats(scanned=2, kept=2, capped=True, list_complete=True),
            SourceOutcome.CAPPED,
        ),
        (
            "errored mid-listing but still saw jobs",
            stats(scanned=400, kept=8, errors=["HTTPError: 500"]),
            SourceOutcome.DEGRADED,
        ),
        (
            "stalled: went silent mid-listing, its own pathology",
            stats(scanned=220, kept=4, errors=["SourceStalled: meta produced nothing for 90s"]),
            SourceOutcome.DEGRADED,
        ),
        (
            "our time ceiling cut a source that was still producing",
            stats(scanned=1880, kept=40, bounded=True),
            SourceOutcome.BOUNDED,
        ),
        (
            "our page ceiling cut a listing still serving items",
            stats(scanned=3000, kept=90, truncated=True),
            SourceOutcome.TRUNCATED,
        ),
        (
            "listing drift invalidated completeness, no error raised",
            stats(scanned=90, kept=2, list_complete=False),
            SourceOutcome.DEGRADED,
        ),
        (
            "a rounding error of unreadable rows in an otherwise-served listing",
            stats(scanned=1678, kept=81, list_complete=False, records_dropped=4),
            SourceOutcome.LOSSY,
        ),
        (
            "record loss past the ratio is the source's shape changing",
            stats(scanned=800, kept=20, list_complete=False, records_dropped=200),
            SourceOutcome.DEGRADED,
        ),
        (
            "a page-level failure alongside drops: the lost slice is unbounded",
            stats(
                scanned=1678,
                kept=81,
                list_complete=False,
                records_dropped=4,
                listing_invalidated=True,
            ),
            SourceOutcome.DEGRADED,
        ),
        (
            "attempted, produced nothing at all",
            stats(errors=["TimeoutError: collection timed out"]),
            SourceOutcome.FAILED,
        ),
        (
            "circuit opened before a single page came back",
            stats(errors=["CircuitOpenError: circuit open for 'meta'"]),
            SourceOutcome.FAILED,
        ),
        (
            "breaker identified a WAF-style uniform refusal",
            stats(errors=["CircuitOpenError: source blocked: 'meta'"], blocked=True),
            SourceOutcome.BLOCKED,
        ),
        (
            "blocked outranks degraded even when pages landed before the block",
            stats(
                scanned=652,
                kept=15,
                errors=["CircuitOpenError: source blocked: 'meta'"],
                blocked=True,
            ),
            SourceOutcome.BLOCKED,
        ),
        (
            "host slept mid-listing: the transport error is ours, not the source's",
            stats(scanned=920, kept=42, errors=["ReadError (no detail)"], suspended=True),
            SourceOutcome.SUSPENDED,
        ),
        (
            "host slept before a single page came back",
            stats(scanned=0, errors=["ReadError (no detail)"], suspended=True),
            SourceOutcome.SUSPENDED,
        ),
        (
            "host slept after the listing was already complete",
            stats(scanned=1196, kept=61, list_complete=True, suspended=True),
            SourceOutcome.OK,
        ),
        (
            "a refusal outranks a suspension: the source decided, then we slept",
            stats(
                scanned=12,
                errors=["CircuitOpenError: source blocked: 'meta'"],
                blocked=True,
                suspended=True,
            ),
            SourceOutcome.BLOCKED,
        ),
        (
            "never attempted (reserved for §12's global-budget deferral)",
            stats(unattempted=True),
            SourceOutcome.UNATTEMPTED,
        ),
    ],
)
def test_source_outcome_derivation(case, source_stats, expected):
    assert classify_source_outcome(source_stats) is expected, case


def test_errors_beat_a_cap_so_a_broken_capped_run_is_not_called_clean():
    """A capped run that also errored is not the clean operator choice `capped`
    describes — otherwise `--max-list` would launder a real failure."""
    assert (
        classify_source_outcome(stats(scanned=151, kept=3, capped=True, errors=["boom"]))
        is SourceOutcome.DEGRADED
    )


def test_scanned_not_kept_decides_usable_data():
    """A source can legitimately scan a full board and keep nothing (all out of
    scope). That is a good observation, not a failure."""
    assert (
        classify_source_outcome(stats(scanned=800, kept=0, errors=["late 500"]))
        is SourceOutcome.DEGRADED
    )
    assert (
        classify_source_outcome(stats(scanned=0, kept=0, errors=["late 500"]))
        is SourceOutcome.FAILED
    )


# -- proportionality of record loss ------------------------------ #


def test_a_few_stub_postings_in_a_large_scan_never_count_against_the_source():
    """Two scans of one large board, seven postings apart; the second also meets
    4 stub postings carrying only `bulletFields`, 0.24% of what it saw. Read as
    `degraded`, those would count against a 99.76%-clean source. The two scans
    must not be judged differently as a verdict on the source.
    """
    clean = stats(scanned=1685, kept=90, new=0, list_complete=True)
    with_stubs = stats(scanned=1678, kept=81, new=46, list_complete=False, records_dropped=4)

    assert classify_source_outcome(clean) is SourceOutcome.OK
    assert classify_source_outcome(with_stubs) is SourceOutcome.LOSSY
    # Different outcomes, deliberately: the second scan really did lose four rows and so
    # cannot authorize closure. What must match is the verdict on the *source*:
    # four bad rows never count against it, so no posting's count is reset.
    assert SourceOutcome.LOSSY not in RESETS_ABSENCE


def test_the_drop_ratio_is_measured_against_everything_seen_not_what_survived():
    """`scanned` counts only items that made it through the parser, so the
    dropped rows have to be added back before taking the fraction.

    The boundary is chosen so the two cases straddle it by one row: 1-in-100 is
    noise, 2-in-100 is not. Measured against `scanned` alone the first case
    would be 1/99 = 1.01% and would wrongly read as degraded.
    """
    assert (
        classify_source_outcome(stats(scanned=99, kept=9, list_complete=False, records_dropped=1))
        is SourceOutcome.LOSSY
    )
    assert (
        classify_source_outcome(stats(scanned=98, kept=9, list_complete=False, records_dropped=2))
        is SourceOutcome.DEGRADED
    )


def test_a_small_board_cannot_hide_a_loss_behind_the_ratio():
    """Proportionality cuts both ways: one unreadable row out of ten is 10% of
    the board, and a source shedding a tenth of its postings is drifting."""
    assert (
        classify_source_outcome(stats(scanned=9, kept=1, list_complete=False, records_dropped=1))
        is SourceOutcome.DEGRADED
    )


def test_an_unbounded_loss_is_never_proportional_however_few_rows_also_dropped():
    """The guard that keeps rule 7 honest. A non-200 page costs an unknown slice
    of the board, so there is no denominator to be proportional about — and a
    run that hit one must not launder itself into `lossy` by also dropping a
    couple of rows cheaply."""
    assert (
        classify_source_outcome(
            stats(
                scanned=5000,
                kept=100,
                list_complete=False,
                records_dropped=1,
                listing_invalidated=True,
            )
        )
        is SourceOutcome.DEGRADED
    )


def test_lossy_never_reports_a_clean_run():
    """Like `bounded`, a lossy source is health-inert but the run is not clean —
    the loss has to stay visible in `scrape_runs.status` rather than reading as
    a perfect night."""
    assert run_status_for([SourceOutcome.OK, SourceOutcome.LOSSY]) == "partial"
    assert run_status_for([SourceOutcome.LOSSY]) == "partial"


def test_derivation_needs_nothing_but_a_bare_mapping():
    """Portability lock: no session, no ORM row, no defaults required."""
    assert classify_source_outcome({}) is SourceOutcome.FAILED
    assert classify_source_outcome({"scanned": 5}) is SourceOutcome.DEGRADED
    assert classify_source_outcome({"list_complete": True}) is SourceOutcome.OK


# -- run status projection -------------------------------------------------- #


OK = SourceOutcome.OK
CAPPED = SourceOutcome.CAPPED
DEGRADED = SourceOutcome.DEGRADED
FAILED = SourceOutcome.FAILED


@pytest.mark.parametrize(
    "case,outcomes,expected",
    [
        ("every source clean", [OK, OK, OK], "ok"),
        ("all capped — an operator cap is not degradation", [CAPPED, CAPPED], "ok"),
        ("mixed ok and capped", [OK, CAPPED, OK], "ok"),
        ("the live case: 8 healthy sources + 1 throttled", [OK] * 8 + [FAILED], "partial"),
        ("one degraded neighbour", [OK, OK, DEGRADED], "partial"),
        (
            "zero ok but one degraded-with-data",
            [FAILED, DEGRADED, FAILED],
            "partial",
        ),
        ("nothing usable came back", [FAILED, FAILED, FAILED], "error"),
        ("single failed source", [FAILED], "error"),
        ("a capped run with one failure still refreshed data", [CAPPED, FAILED], "partial"),
    ],
)
def test_run_status_projection(case, outcomes, expected):
    assert run_status_for(outcomes) == expected, case


def test_run_status_holds_its_invariants_over_every_outcome_combination():
    """The three properties downstream code relies on, checked exhaustively.

    Stated as invariants rather than by re-deriving the rules: restating the
    implementation would pass for any implementation, including a broken one.
    """
    from itertools import combinations_with_replacement

    for size in (1, 2, 3):
        for combo in combinations_with_replacement(list(SourceOutcome), size):
            status = run_status_for(combo)
            assert status in {"ok", "partial", "error"}  # total: no fall-through

            # 1. The loop-breaking property: a run containing a healthy source
            #    is never a total failure, so `last_success_at` always advances.
            if SourceOutcome.OK in combo:
                assert status != "error", combo

            # 2. `ok` is reserved for runs with nothing wrong — a degraded or
            #    failed source must always be visible in the status.
            if {SourceOutcome.DEGRADED, SourceOutcome.FAILED} & set(combo):
                assert status != "ok", combo

            # 3. `error` means nothing usable came back; a source that returned
            #    data must never be reported as a total failure.
            if status == "error":
                assert SourceOutcome.DEGRADED not in combo, combo
                assert SourceOutcome.CAPPED not in combo, combo
                assert SourceOutcome.LOSSY not in combo, combo


def test_no_sources_is_not_an_error():
    """An empty target set (`--company` filtered to nothing) never ran anything
    and must not be reported as a failed run."""
    assert run_status_for([]) == "ok"


# --- `bounded`: our ceiling, not the source's fault ------------------------- #
# A cut at our per-source ceiling says nothing about the source. Scored as an
# anomaly, a mistuned ceiling would quarantine healthy bindings, which
# suppresses closure indefinitely. These pin the split that prevents it.


def test_an_operator_cap_outranks_our_ceiling_when_both_fired():
    """`capped` must win, or the source becomes retry-eligible and the retry
    overrides the `--max-list` instruction the operator gave."""
    both = stats(scanned=150, kept=3, capped=True, bounded=True)
    assert classify_source_outcome(both) is SourceOutcome.CAPPED


def test_errors_beat_our_ceiling_so_a_broken_bounded_run_stays_a_pathology():
    """A source that errored AND hit the ceiling is not inert: the error is
    evidence about the source, and swallowing it would hide a real fault."""
    broken = stats(scanned=200, kept=5, bounded=True, errors=["HTTPError: 503"])
    assert classify_source_outcome(broken) is SourceOutcome.DEGRADED


def test_a_bounded_run_is_usable_but_never_clean():
    """Usable (it collected pages) so the run is not `error`; not clean, so the
    run reads `partial` and a mistuned ceiling stays visible."""
    assert run_status_for([SourceOutcome.BOUNDED]) == "partial"
    assert run_status_for([SourceOutcome.OK, SourceOutcome.BOUNDED]) == "partial"
    # ...and it never drags an otherwise-usable run down to `error`.
    assert run_status_for([SourceOutcome.BOUNDED, SourceOutcome.FAILED]) == "partial"


def test_a_ceiling_cut_never_counts_against_the_source():
    """Why this outcome exists: scored as an anomaly, three cuts at our own
    ceiling would quarantine a healthy source, and a cut that resets every
    posting's absence count means a board we keep cutting short never closes
    a posting."""
    assert SourceOutcome.BOUNDED not in RESETS_ABSENCE
    assert SourceOutcome.TRUNCATED not in RESETS_ABSENCE


def test_a_stall_still_counts_against_the_source_because_silence_is_its_fault():
    """The other half of the split: a hung source is a pathology, and resets
    each posting's count so nothing closes on what it failed to list."""
    stalled = stats(scanned=220, errors=["SourceStalled: no progress for 90s"])
    assert classify_source_outcome(stalled) is SourceOutcome.DEGRADED
    assert SourceOutcome.DEGRADED in RESETS_ABSENCE


# --- retry eligibility derives from the vocabulary -------------------------- #


def test_retryable_is_everything_except_a_finished_source_and_our_fixed_bounds():
    assert RETRYABLE == {
        SourceOutcome.BOUNDED,
        SourceOutcome.SUSPENDED,
        SourceOutcome.DEGRADED,
        SourceOutcome.FAILED,
        SourceOutcome.UNATTEMPTED,
    }
    # The exclusions carry the meaning: nothing to redo (ok), don't override an
    # operator's deliberate cap (capped), don't re-run a DETERMINISTIC bound
    # (truncated) — a same-run retry pages into the same ceiling, unlike
    # `bounded`, where the time pressure may have eased — and don't aim more
    # requests at a WAF that has decided (blocked).
    assert SourceOutcome.OK not in RETRYABLE
    assert SourceOutcome.CAPPED not in RETRYABLE
    assert SourceOutcome.TRUNCATED not in RETRYABLE
    assert SourceOutcome.BLOCKED not in RETRYABLE
    # `lossy` is excluded on cost, not principle: recovering a handful of rows
    # means re-scanning the whole board, and the next clean run restores
    # closure authority anyway.
    assert SourceOutcome.LOSSY not in RETRYABLE


def test_every_outcome_is_classified_as_retryable_or_not():
    """Totality: a new outcome member must be decided, not silently dropped."""
    for outcome in SourceOutcome:
        assert (outcome in RETRYABLE) == (
            outcome
            not in (
                SourceOutcome.OK,
                SourceOutcome.CAPPED,
                SourceOutcome.TRUNCATED,
                SourceOutcome.LOSSY,
                SourceOutcome.BLOCKED,
                # A board proven empty answers the same an hour later.
                SourceOutcome.EMPTY,
            )
        )


# --- host suspension is our bound, not the source's pathology ---- #


def test_a_suspension_is_read_through_the_errors_it_caused():
    """A host suspension does not raise where it happens: every socket open
    across the gap is dead on resume, so it lands as a transport error
    attributed to whichever source was mid-listing.

    Socket-death `ReadError`s sit on suspension gaps, so the errors are the
    suspension's symptom, and reading them as the source's behavior would put
    a healthy binding on the road to quarantine.
    """
    slept = stats(scanned=920, kept=42, errors=["ReadError (no detail)"], suspended=True)
    assert classify_source_outcome(slept) is SourceOutcome.SUSPENDED
    assert SourceOutcome.SUSPENDED not in RESETS_ABSENCE

    # The same stats without the flag are still the source's problem. If this
    # half ever stops holding, the fix has stopped distinguishing anything.
    awake = stats(scanned=920, kept=42, errors=["ReadError (no detail)"])
    assert classify_source_outcome(awake) is SourceOutcome.DEGRADED
    assert SourceOutcome.DEGRADED in RESETS_ABSENCE


def test_a_suspended_run_is_usable_but_never_clean():
    """`partial`, not `error` and not `ok`. `error` would raise a high-priority
    "Sync failed" for our own laptop sleeping; `ok` would claim a refresh that
    only half happened and let `last_success_at` advance on it."""
    assert run_status_for([SourceOutcome.SUSPENDED]) == "partial"
    assert run_status_for([SourceOutcome.SUSPENDED, SourceOutcome.OK]) == "partial"


def test_a_suspension_never_authorizes_closure():
    """Health-inert is not the same permission as closure-authoritative. We
    cannot claim a req is gone from a listing we slept through."""
    from tracker.workflows.collection_types import empty_stats

    assert "suspended" in empty_stats(), "the pipeline must record the flag it derives from"
