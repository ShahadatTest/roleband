"""Per-binding learned bounds: the update rule.

Sources' real durations span orders of magnitude, so one global
`scraper_source_budget_seconds` cannot fit them, and a hand-written
`_MAX_PAGES` constant nobody re-measures is a time bomb with a long fuse. Each
binding learns its own bounds instead.

Everything here is **pure over plain data**: no session, no ORM, no clock. The
persistence half lives in `workflows/tuning_pass.py`; this module is the policy,
so it can be tested exhaustively against adversarial observation sequences.

Four properties carry the design, and each exists because its absence has a
known failure mode:

* **Ratcheted.** A bound never falls below observed p95. Without it a quiet
  night (a board briefly small, a source half-refusing) re-cuts the bound, and
  the next normal night truncates: the bound would oscillate around the
  traffic instead of bounding it. Same discipline as the import-linter
  allowlist and the frontend ratchet: it moves down only deliberately, and
  slowly.
* **Escalation is evidence-driven.** A bound that *fired* is proof it was too
  low. It is not evidence of how much too low: the truncated observation is
  censored *by the bound itself*, so fitting to it would re-derive the same
  bound. Hence a multiplier on the current bound, not a fit to the sample.
* **Only a natural stop justifies lowering.** The symmetric half: an
  observation produced under a bound that fired says nothing about where the
  board actually ends.
* **Bounded.** Learned values clamp inside operator limits, never past them.
  Auto-tuning that can raise its own ceiling is not a bound.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from tracker.platform.paging import (
    MAX_PAGES_FLOOR,
    MAX_PAGES_HARD,
    QueryObservation,
    StopReason,
)

__all__ = [
    "MAX_PAGES_FLOOR",
    "MAX_PAGES_HARD",
    "MIN_BUDGET_SECONDS",
    "QueryObservation",
    "StopReason",
    "TuningPolicy",
    "TuningState",
    "escalate_budget",
    "next_tuning",
    "percentile",
]

#: Floor for a learned time budget. Below this, ordinary jitter (a retry, one
#: slow response) reads as a source overrunning its budget.
MIN_BUDGET_SECONDS = 60.0
#: Runs required before a learned budget replaces the operator's global one.
#:
#: A time budget is a claim about a *distribution*, and one run is not a
#: distribution — p95 over a single sample is just that sample. Unlike a page
#: bound (ratcheted to observed p95, and able to fall only 10% per run), a
#: budget learned from one unusually fast night would take effect immediately
#: and cut the next ordinary one. Until there is a spread to measure, the global
#: ceiling stands.
MIN_BUDGET_SAMPLES = 3


@dataclass(frozen=True)
class TuningPolicy:
    """Operator limits and rates. Mirrors the `scraper_tuning_*` settings."""

    headroom: float = 1.5
    escalate: float = 2.0
    decay: float = 0.1
    samples: int = 20
    #: Hard ceiling for a learned time budget: the operator's global budget.
    budget_ceiling_seconds: float = 1800.0


@dataclass(frozen=True)
class TuningState:
    """One row of `source_binding_tuning`, as plain data.

    `page_samples`/`duration_samples` are the retained evidence p95 is computed
    from — stored rather than a running p95, so a bound is re-derivable and
    explainable instead of being folklore.
    """

    query_key: str
    page_samples: tuple[int, ...] = ()
    duration_samples: tuple[float, ...] = ()
    declared_total_last: int | None = None
    saturated: bool = False
    stop_reason_hist: dict[str, int] = field(default_factory=dict)
    tuned_max_pages: int | None = None
    tuned_budget_seconds: float | None = None

    @property
    def observed_pages_p95(self) -> int:
        return int(percentile(self.page_samples, 0.95)) if self.page_samples else 0

    @property
    def observed_duration_p95(self) -> float:
        return percentile(self.duration_samples, 0.95) if self.duration_samples else 0.0


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile.

    Nearest-rank, not interpolated, and deliberately: an interpolated p95 over
    few samples returns a value *between* two observations — a page count no run
    ever produced. The bound must be a number the source actually reached.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def next_tuning(
    prev: TuningState,
    observation: QueryObservation,
    *,
    duration_seconds: float | None = None,
    policy: TuningPolicy | None = None,
) -> TuningState:
    """Fold one run's observation into a query's tuning row.

    Total and deterministic: same `(prev, observation, policy)` always yields the
    same state, so the pass is safely re-runnable and a bound can be replayed
    from `page_samples`.
    """
    policy = policy or TuningPolicy()

    # --- retained evidence ---------------------------------------------------
    # A censored page count is still evidence of a *lower bound* on the board,
    # so it belongs in the samples. What it must never do is justify LOWERING
    # the ceiling — that is handled below, by refusing to decay on a ceiling
    # stop, not by discarding the observation.
    page_samples = (*prev.page_samples, observation.pages_used)[-policy.samples :]
    duration_samples = prev.duration_samples
    if duration_seconds is not None:
        duration_samples = (*duration_samples, duration_seconds)[-policy.samples :]

    hist = dict(prev.stop_reason_hist)
    hist[observation.stop_reason.value] = hist.get(observation.stop_reason.value, 0) + 1

    state = TuningState(
        query_key=prev.query_key or observation.query_key,
        page_samples=page_samples,
        duration_samples=duration_samples,
        declared_total_last=(
            observation.declared_total
            if observation.declared_total is not None
            else prev.declared_total_last
        ),
        saturated=observation.stop_reason is StopReason.CEILING,
        stop_reason_hist=hist,
        tuned_max_pages=prev.tuned_max_pages,
        tuned_budget_seconds=prev.tuned_budget_seconds,
    )

    return TuningState(
        query_key=state.query_key,
        page_samples=state.page_samples,
        duration_samples=state.duration_samples,
        declared_total_last=state.declared_total_last,
        saturated=state.saturated,
        stop_reason_hist=state.stop_reason_hist,
        tuned_max_pages=_next_max_pages(prev, state, observation, policy),
        tuned_budget_seconds=_next_budget(prev, state, policy),
    )


def escalate_budget(prev: TuningState, policy: TuningPolicy | None = None) -> TuningState:
    """A run our learned time budget cut short (`bounded`): multiply the budget.

    The same rule as a page ceiling that fired, and for the same reason: the cut
    run is proof the budget was too low and no evidence of how much, because the
    budget censored the very duration that would size it. So nothing of the run
    is folded in (its pages and its duration stay out of the samples); only the
    budget moves, clamped to the operator's ceiling. Without this a source that
    grows slower than its old p95 x headroom is cut on every run, and since a
    cut run never teaches, the budget never moves.
    A budget not yet learned is the operator's global ceiling: nothing to raise.
    """
    policy = policy or TuningPolicy()
    if prev.tuned_budget_seconds is None:
        return prev
    raised = _clamp(prev.tuned_budget_seconds * policy.escalate, MIN_BUDGET_SECONDS, policy.budget_ceiling_seconds)
    return TuningState(
        query_key=prev.query_key,
        page_samples=prev.page_samples,
        duration_samples=prev.duration_samples,
        declared_total_last=prev.declared_total_last,
        saturated=prev.saturated,
        stop_reason_hist=prev.stop_reason_hist,
        tuned_max_pages=prev.tuned_max_pages,
        tuned_budget_seconds=round(max(raised, prev.tuned_budget_seconds), 1),
    )


def _target_pages(state: TuningState, observation: QueryObservation, policy: TuningPolicy) -> int:
    """Where the bound would sit if nothing else constrained it.

    The declared total is used as a *floor* on the target, never as the answer:
    it is source metadata, and the standing rule is to measure behavior rather
    than trust what a source claims. When the two disagree the larger wins, so a
    source under-reporting its own count cannot talk us into a bound below what
    we watched it serve.
    """
    needed = float(state.observed_pages_p95)
    if observation.declared_total is not None and observation.page_size:
        needed = max(needed, math.ceil(observation.declared_total / observation.page_size))
    return int(math.ceil(needed * policy.headroom))


def _next_max_pages(
    prev: TuningState,
    state: TuningState,
    observation: QueryObservation,
    policy: TuningPolicy,
) -> int:
    current = prev.tuned_max_pages or observation.ceiling
    target = _target_pages(state, observation, policy)

    if observation.stop_reason is StopReason.CEILING:
        # It fired, so it was too low — by an unknown amount, because the bound
        # censored the very observation that would size it. Multiply the bound
        # that fired; never fit to the truncated sample.
        proposed = max(current * policy.escalate, float(target))
    elif target >= current:
        proposed = float(target)
    else:
        # Lowering, and only from a natural stop. Rate-limited so the bound
        # walks down over runs instead of snapping to one quiet night.
        #
        # `max(1.0, ...)` because the step is re-ceilinged to an int each run:
        # at a bound of 9 a 10% step is 0.9 pages, `ceil` rounds it back to 9,
        # and the bound sticks there forever — a fixed point a few pages above
        # the floor that no amount of evidence could clear.
        step = max(1.0, current * policy.decay)
        proposed = max(float(target), current - step)

    # The ratchet, applied last so no branch above can slip beneath it: never
    # below what we have actually watched this query need.
    proposed = max(proposed, float(state.observed_pages_p95))
    return int(_clamp(math.ceil(proposed), MAX_PAGES_FLOOR, MAX_PAGES_HARD))


def _next_budget(prev: TuningState, state: TuningState, policy: TuningPolicy) -> float | None:
    """A learned time budget, or None while there is not enough to learn from.

    Raising follows the observed p95 at once. Lowering is rate-limited like a
    page ceiling (at most `decay` per run): the folded run ended naturally, but
    one fast night must not undo a budget a slow board needed, or an escalated
    budget (`escalate_budget`) snaps back and the next slow run is cut again.
    """
    if len(state.duration_samples) < MIN_BUDGET_SAMPLES:
        return None
    proposed = state.observed_duration_p95 * policy.headroom
    current = prev.tuned_budget_seconds
    if current is not None and proposed < current:
        proposed = max(proposed, current * (1 - policy.decay))
    return round(
        _clamp(proposed, MIN_BUDGET_SECONDS, policy.budget_ceiling_seconds), 1
    )
