"""Per-binding learned bounds — the update rule.

A tuner is a feedback loop wired to the thing that produces its own input, so
the tests that matter are the ones that run it for many rounds and assert it
does not walk somewhere stupid. Single-step assertions cannot catch a bound
that oscillates, collapses over a quiet week, or ratchets itself to the floor.

The four properties, each with its failure mode:

* ratcheted — without it a quiet night re-cuts the bound and the next normal
  night truncates, forever;
* escalation is evidence-driven — a bound that fired censored its own
  observation, so fitting to the sample re-derives the bound that just failed;
* only a natural stop lowers — the symmetric half;
* bounded — auto-tuning that can raise its own ceiling is not a bound.
"""

from __future__ import annotations

import pytest

from tracker.platform.paging import (
    MAX_PAGES_FLOOR,
    MAX_PAGES_HARD,
    QueryObservation,
    StopReason,
)
from tracker.workflows.tuning import (
    MIN_BUDGET_SECONDS,
    TuningPolicy,
    TuningState,
    escalate_budget,
    next_tuning,
    percentile,
)

POLICY = TuningPolicy(headroom=1.5, escalate=2.0, decay=0.1, samples=20,
                      budget_ceiling_seconds=1800.0)


def obs(
    pages: int,
    *,
    reason: StopReason = StopReason.EXHAUSTED,
    ceiling: int = 100,
    declared: int | None = None,
    size: int | None = None,
    key: str = "united_states",
) -> QueryObservation:
    return QueryObservation(
        query_key=key,
        pages_used=pages,
        items=pages * 20,
        stop_reason=reason,
        ceiling=ceiling,
        declared_total=declared,
        page_size=size,
    )


def run(observations, *, state: TuningState | None = None, policy=POLICY, durations=None):
    """Fold a sequence of observations, returning the final state."""
    state = state or TuningState(query_key="united_states")
    for index, observation in enumerate(observations):
        duration = durations[index] if durations else None
        state = next_tuning(state, observation, duration_seconds=duration, policy=policy)
    return state


# -- percentile -------------------------------------------------------------- #


def test_percentile_returns_an_observed_value_never_an_interpolated_one():
    """Nearest-rank, deliberately. An interpolated p95 over few samples returns
    a page count no run ever produced, and the bound must be a number the source
    actually reached."""
    samples = [10, 20, 30, 40]
    assert percentile(samples, 0.95) in samples
    assert percentile(samples, 0.95) == 40
    assert percentile([], 0.95) == 0.0
    assert percentile([7], 0.95) == 7


# -- the ratchet ------------------------------------------------------------- #


def test_a_quiet_night_cannot_re_cut_a_bound_below_what_the_board_needed():
    """The core ratchet. A board that paged 60 for weeks, then one night
    returns 3 pages (a source half-refusing, a transient empty index), must not
    leave a bound the normal night would truncate against."""
    state = run([obs(60)] * 10)
    settled = state.tuned_max_pages
    assert settled >= 60

    quiet = run([obs(3)], state=state)

    assert quiet.tuned_max_pages >= 60, "the bound must still fit the real board"
    assert quiet.observed_pages_p95 >= 60


def test_a_sustained_shrink_lowers_the_bound_but_only_gradually():
    """The ratchet is not a freeze: a board that genuinely halves should be
    followed down, over runs. Rate-limited so no single night can do it."""
    state = run([obs(80)] * 20)
    high = state.tuned_max_pages

    # Twenty runs of a genuinely smaller board — enough to age out every old
    # sample, since `samples=20`.
    shrunk = run([obs(20)] * 20, state=state)

    assert shrunk.tuned_max_pages < high, "a real shrink is eventually followed"
    assert shrunk.tuned_max_pages >= shrunk.observed_pages_p95
    # And it never fell below what the smaller board itself needs.
    assert shrunk.tuned_max_pages >= 20


def test_one_step_can_never_drop_the_bound_by_more_than_the_decay_rate():
    """The rate limit stated directly, so a refactor that snaps straight to
    target fails here rather than in production six weeks later."""
    state = run([obs(100)] * 20)
    before = state.tuned_max_pages

    after = next_tuning(state, obs(1), policy=POLICY).tuned_max_pages

    assert after >= before * (1 - POLICY.decay) - 1


# -- escalation -------------------------------------------------------------- #


def test_a_ceiling_hit_escalates_from_the_bound_that_fired():
    """The censoring argument. A run cut at 100 pages reports `pages_used=100`
    — a number produced BY the bound. Fitting to it would compute
    100*1.5=150 as if 100 were the board's size; the board might be 10,000.
    Escalation multiplies the bound instead."""
    state = run([obs(100, reason=StopReason.CEILING, ceiling=100)])

    assert state.tuned_max_pages == 200, "doubled the bound that fired"
    assert state.saturated is True


def test_repeated_truncation_keeps_escalating_until_the_board_fits():
    """A source far larger than its seed must converge in a few runs, not creep
    up by a headroom multiple each time."""
    state = TuningState(query_key="united_states")
    bounds = []
    for _ in range(5):
        ceiling = state.tuned_max_pages or 100
        # The source is bigger than whatever we allow: it always truncates.
        state = next_tuning(
            state, obs(ceiling, reason=StopReason.CEILING, ceiling=ceiling), policy=POLICY
        )
        bounds.append(state.tuned_max_pages)

    assert bounds == [200, 400, 800, MAX_PAGES_HARD, MAX_PAGES_HARD]


def test_a_bound_that_fired_is_never_lowered_by_the_same_observation():
    """The two rules meeting: a ceiling stop is both the largest sample seen
    AND the reason to escalate. It must never take the decay branch."""
    state = run([obs(30)] * 10)
    before = state.tuned_max_pages

    after = next_tuning(
        state, obs(before, reason=StopReason.CEILING, ceiling=before), policy=POLICY
    )

    assert after.tuned_max_pages > before


# -- declared totals --------------------------------------------------------- #


def test_a_declared_total_raises_the_target_before_a_truncation_teaches_it():
    """The point of reading source metadata at all: anticipate growth the
    source already announced, instead of waiting to be truncated by it."""
    # Paged 10 pages, but the source says 4,000 postings at 20/page = 200 pages
    # (the rest were out of scope / deduped away).
    state = run([obs(10, declared=4000, size=20)])

    assert state.tuned_max_pages >= 200
    assert state.declared_total_last == 4000


def test_a_source_under_reporting_its_own_count_cannot_lower_the_bound():
    """Metadata is a hint, never the answer — the standing rule is to measure
    behavior. When the declared total and what we watched disagree, the larger
    wins."""
    state = run([obs(90)] * 10)
    before = state.tuned_max_pages

    after = next_tuning(state, obs(90, declared=20, size=20), policy=POLICY)

    assert after.tuned_max_pages >= before
    assert after.tuned_max_pages >= 90


# -- operator limits --------------------------------------------------------- #


def test_a_learned_page_bound_never_escapes_the_published_maximum():
    state = run([obs(999, declared=10_000_000, size=1)])
    assert state.tuned_max_pages == MAX_PAGES_HARD


def test_a_tiny_board_still_leaves_room_to_recover():
    """A source that legitimately serves one page must not leave a bound of 1:
    the next run would truncate on any growth at all.

    40 runs, because the descent is deliberately slow — from a seed of 100 at
    10%/run it takes ~24 runs to reach the floor, and that slowness IS the
    ratchet. Ten runs still leaves the bound in the thirties.
    """
    assert run([obs(1)] * 10).tuned_max_pages > MAX_PAGES_FLOOR, "descent is gradual"
    assert run([obs(1)] * 40).tuned_max_pages == MAX_PAGES_FLOOR, "and it settles"


@pytest.mark.parametrize(
    "durations,expected",
    [
        ([1.6] * 5, MIN_BUDGET_SECONDS),  # floor: jitter must not read as overrun
        ([1000.0] * 5, 1500.0),  # 1000 * 1.5 headroom
        ([1700.0] * 5, 1800.0),  # clamped at the operator's global ceiling
    ],
)
def test_a_learned_time_budget_stays_inside_operator_limits(durations, expected):
    state = run([obs(10)] * len(durations), durations=durations)
    assert state.tuned_budget_seconds == expected


def test_a_learned_budget_can_never_exceed_the_global_ceiling_however_slow():
    """meta's case, and the honest limit of tuning: a source measuring 1812s against
    an 1800s operator ceiling learns 1800, not 1812. Auto-tuning fits a source
    INSIDE the operator's limit; raising that limit stays a human decision."""
    state = run([obs(10)] * 5, durations=[1812.0] * 5)
    assert state.tuned_budget_seconds == 1800.0


def test_no_duration_evidence_means_no_learned_budget():
    """A per-query row records pages, not durations. It must return None rather
    than a budget derived from nothing."""
    assert run([obs(10)] * 3).tuned_budget_seconds is None


def test_one_fast_night_cannot_set_a_budget_that_cuts_the_next_ordinary_one():
    """A budget is a claim about a distribution; p95 over one sample is just
    that sample. Until there is a spread to measure, the operator's global
    ceiling stands — `None` means "no learned budget", not "no budget".

    Asymmetric with page bounds on purpose: those are ratcheted to observed p95
    and can fall only 10% per run, so an early bad sample is self-correcting. A
    budget takes effect in full on the very next run.
    """
    assert run([obs(10)] * 2, durations=[3.0, 4.0]).tuned_budget_seconds is None
    assert run([obs(10)] * 3, durations=[3.0, 4.0, 900.0]).tuned_budget_seconds is not None


def test_a_learned_budget_follows_the_slow_tail_not_the_median():
    """p95, so the budget covers the source's bad nights. A source usually
    taking 100s but regularly 800s must get a budget fitting 800, or it is
    bounded every time it does the thing it regularly does.

    Two slow nights in twenty, not one: nearest-rank p95 of 20 samples is the
    19th, so a single outlier sits exactly AT the percentile and is excluded by
    design. That is the tail-trimming p95 exists for — one freak night must not
    permanently widen the budget.
    """
    assert run([obs(10)] * 20, durations=[100.0] * 18 + [800.0] * 2).tuned_budget_seconds == 1200.0
    assert run([obs(10)] * 20, durations=[100.0] * 19 + [800.0]).tuned_budget_seconds == 150.0


# -- a budget that fired (bounded) ------------------------------------------- #

#: A real source-level row (qualcomm's): 14 natural reads of 400-490s, a
#: learned budget of 736s.
QUALCOMM = TuningState(
    query_key="*",
    duration_samples=(490.7, 404.7, 400.4, 404.1, 408.4, 410.8, 406.1, 406.7, 414.7, 413.5, 412.5, 411.2,
                      420.6, 428.8),
    tuned_budget_seconds=736.0,
)


def test_a_budget_that_cut_the_read_is_multiplied_and_nothing_of_the_run_is_folded():
    """The cut run's duration is the budget itself, censored by it: folding it
    would re-derive the budget that just failed. So only the budget moves."""
    raised = escalate_budget(QUALCOMM, POLICY)
    assert raised.tuned_budget_seconds == 1472.0
    assert raised.duration_samples == QUALCOMM.duration_samples
    assert escalate_budget(raised, POLICY).tuned_budget_seconds == 1800.0  # clamped to the operator ceiling
    assert escalate_budget(TuningState(query_key="*", tuned_budget_seconds=1800.0), POLICY).tuned_budget_seconds \
        == 1800.0


def test_no_learned_budget_means_the_global_ceiling_fired_and_nothing_is_raised():
    fresh = TuningState(query_key="*", duration_samples=(400.0,))
    assert escalate_budget(fresh, POLICY) == fresh


def test_a_source_that_grew_slower_than_its_budget_gets_read_whole_again():
    """The loop to escape: every read past 736s is cut, a cut read never
    teaches, so the budget never moves. Run the tuner against a source that
    now needs 1000s: within two nights its reads end on their own, and stay so."""
    state, natural = QUALCOMM, []
    for _night in range(6):
        if 1000.0 > (state.tuned_budget_seconds or POLICY.budget_ceiling_seconds):
            state, cut = escalate_budget(state, POLICY), True
        else:
            state, cut = next_tuning(state, obs(10), duration_seconds=1000.0, policy=POLICY), False
        natural.append(not cut)
    assert natural[:2] == [False, True] and all(natural[1:])
    assert state.tuned_budget_seconds >= 1000.0


def test_one_fast_night_lowers_a_budget_by_at_most_the_decay_rate():
    """An escalated budget must not snap back on one quick read, or the next
    slow read is cut again: lowering walks down at most `decay` per run, never
    below the observed p95 x headroom."""
    raised = escalate_budget(QUALCOMM, POLICY)  # 1472
    after = next_tuning(raised, obs(10), duration_seconds=420.0, policy=POLICY)
    assert after.tuned_budget_seconds == round(1472.0 * 0.9, 1)
    walked = run([obs(10)] * 40, state=raised, durations=[420.0] * 40)
    assert walked.tuned_budget_seconds == 630.0  # 420 x 1.5: the floor the walk settles on


# -- bookkeeping ------------------------------------------------------------- #


def test_samples_are_bounded_so_a_row_cannot_grow_without_limit():
    policy = TuningPolicy(samples=5)
    state = run([obs(n) for n in range(1, 30)], policy=policy)
    assert len(state.page_samples) == 5
    assert state.page_samples == (25, 26, 27, 28, 29)


def test_stop_reasons_are_tallied_so_how_a_query_ends_is_answerable():
    state = run(
        [obs(10), obs(10, reason=StopReason.STOPPED), obs(10, reason=StopReason.CEILING)]
    )
    assert state.stop_reason_hist == {"exhausted": 1, "stopped": 1, "ceiling": 1}


def test_saturated_tracks_the_latest_run_not_the_history():
    """A source that truncated last month and pages cleanly now is not
    saturated — otherwise the flag could never clear."""
    state = run([obs(50, reason=StopReason.CEILING, ceiling=50)])
    assert state.saturated is True
    assert run([obs(10)], state=state).saturated is False


def test_the_fold_is_deterministic_so_the_pass_is_safely_re_runnable():
    sequence = [obs(10), obs(40, reason=StopReason.CEILING, ceiling=40), obs(12)]
    assert run(sequence) == run(sequence)
