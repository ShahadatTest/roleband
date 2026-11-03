"""Run outcome vocabulary: per-source classification and the run projection.

`classify_source_outcome` / `run_status_for`: the daily pipeline's per-source
`SourceOutcome` and the run status projected from it. Closure reads each
posting's absence evidence through `RESETS_ABSENCE`.

**One vocabulary, defined once.** `scrape_runs.status` is a *projection* of the
per-source outcomes, never an independent taxonomy; a parallel enum elsewhere
that "maps to" these would be a second vocabulary to keep in step. The
derivation is a pure function over a plain stats dict: no session, no ORM,
nothing tied to how `per_source` is stored.

The conservative bias is deliberate. When in doubt a run is a pathology
(`degraded`/`failed`, which resets every posting's absence count) rather than
OK: a false OK is what lets a broken source close real jobs; a false pathology
only costs a closure delayed by one more complete scan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum

__all__ = [
    "CLEAN",
    "SourceOutcome",
    "classify_source_outcome",
    "run_status_for",
]

#: Fraction of a listing's items that may be individually unreadable before the
#: loss stops being noise and starts being the source's shape changing.
#:
#: Deliberately strict: a genuine payload change costs far more than 1% of the
#: board, and a selector that half-broke would blow through this immediately.
#: The rate is measured against everything we *saw* (scanned + dropped), not
#: against what was kept — a source can legitimately scan a full board and keep
#: nothing.
_RECORD_DROP_ANOMALY_RATIO = 0.01


# --------------------------------------------------------------------------- #
# Per-source outcome + run projection
# --------------------------------------------------------------------------- #


class SourceOutcome(str, Enum):
    """What one source contributed to a run.

    The distinction that matters: a source may be bounded *by us* (`capped`)
    or broken *by itself* (`degraded`/`failed`). Only the latter is evidence
    against the source. `unattempted` is a source the run never asked (a local
    refusal, or a budget that ran out first), so it says nothing about it.
    """

    OK = "ok"  # no errors, listing complete
    CAPPED = "capped"  # an operator bound (--max-list) was in force; not a pathology
    BOUNDED = "bounded"  # our own time ceiling cut a still-producing source
    TRUNCATED = "truncated"  # our page ceiling cut a still-serving listing
    SUSPENDED = "suspended"  # our host cut the scan: it slept, or had no network
    LOSSY = "lossy"  # a few individual records were unreadable; the rest served
    EMPTY = "empty"  # the board answered in full and proved it lists nothing
    DEGRADED = "degraded"  # usable data, but errors / incomplete / stalled
    FAILED = "failed"  # attempted, produced no usable data
    BLOCKED = "blocked"  # the source is refusing us outright (WAF-style uniform 4xx/5xx)
    UNATTEMPTED = "unattempted"  # never attempted: refused locally, or never reached


#: Outcomes that produced usable observations of the source.
USABLE = frozenset(
    {
        SourceOutcome.OK,
        SourceOutcome.CAPPED,
        SourceOutcome.BOUNDED,
        SourceOutcome.TRUNCATED,
        SourceOutcome.LOSSY,
        SourceOutcome.EMPTY,
        SourceOutcome.DEGRADED,
        SourceOutcome.SUSPENDED,
    }
)
#: Outcomes a run can consist entirely of and still be a clean success.
#:
#: `bounded` is deliberately absent. A source we cut at our own ceiling is not a
#: pathology (so it never resets absence), but the run is not clean either — the
#: listing is incomplete and the ceiling may simply be mistuned. Keeping it out
#: of this set is what makes that mistuning visible as `partial` instead of
#: silently reading as a healthy run.
#:
#: `empty` is present: the source answered everything it was asked and proved
#: it lists nothing, so the run read it in full. What the board's emptiness
#: still costs (postings it held stay open) is a per-company fact, told by
#: the attention report, never by the run's status.
CLEAN = frozenset({SourceOutcome.OK, SourceOutcome.CAPPED, SourceOutcome.EMPTY})

#: Outcomes that start every posting's absence count again: the
#: source itself misbehaved, so a miss counted before it and a miss after it
#: are not two readings of one healthy board. Two complete misses are needed
#: after the last of these. Our own bounds (`capped`, `bounded`, `truncated`, `suspended`), `lossy`,
#: `empty` and `unattempted` are absent: they neither count nor reset.
RESETS_ABSENCE = frozenset(
    {SourceOutcome.DEGRADED, SourceOutcome.FAILED, SourceOutcome.BLOCKED}
)


#: Outcomes worth re-attempting in a targeted retry run. Derived from the
#: vocabulary rather than restated: everything except a finished source and an
#: operator's deliberate cap. `bounded` is the ideal candidate — it was still
#: producing when we stopped it.
#: `truncated` is deliberately absent: the page ceiling is deterministic, so a
#: same-run retry would re-scan the same pages into the same ceiling — unlike
#: `bounded`, where the time pressure that cut the source may have eased.
#: `blocked` is absent for the harder version of the same reason: the source
#: has decided against us, and a retry is just more banned requests aimed at a
#: WAF — the operator signal is "needs attention", never "try again tonight".
#: `lossy` is absent on cost: the drop is transient and a retry might well
#: recover it, but recovering a handful of records means re-scanning the entire
#: board. One night of suppressed closure is the
#: cheaper side of that trade, and the next clean run restores authority anyway.
#: `suspended` is present for the same reason as `bounded` and against the same
#: contrast with `truncated`: the host being asleep says nothing about the board
#: and does not repeat deterministically, so the next pass is worth taking.
#: `empty` is absent: a board proven empty answers the same an hour later.
RETRYABLE = frozenset(
    {
        SourceOutcome.BOUNDED,
        SourceOutcome.SUSPENDED,
        SourceOutcome.DEGRADED,
        SourceOutcome.FAILED,
        SourceOutcome.UNATTEMPTED,
    }
)


def _record_loss_is_negligible(stats: Mapping) -> bool:
    """True when the listing is incomplete *only* because a rounding error's
    worth of individual records could not be read.

    Two conditions, and the first is the load-bearing one. A listing-level
    invalidation (non-200 page, non-JSON body, a missing postings array)
    costs an **unknown and unbounded** slice of the board — there is no
    denominator to be proportional about, so proportionality does not apply and
    the run stays a pathology. Only when every failure was a single countable
    item does the ratio mean anything.
    """
    dropped = int(stats.get("records_dropped") or 0)
    if dropped <= 0 or stats.get("listing_invalidated"):
        return False
    # Everything we actually saw. `scanned` excludes dropped items (they never
    # reach the yield), so the denominator has to add them back.
    observed = int(stats.get("scanned") or 0) + dropped
    return dropped / observed <= _RECORD_DROP_ANOMALY_RATIO


def classify_source_outcome(stats: Mapping) -> SourceOutcome:
    """Derive one source's outcome from its collected stats.

    Pure and total over a plain mapping — deliberately *not* a method on
    `SourceCollection` and deliberately free of any session.

    Rules, evaluated top-down (first match wins):

    1. explicitly `unattempted` — no evidence of any kind;
    2. the breaker identified a WAF-style uniform refusal — `blocked`;
    3. no errors and an operator cap was in force — `capped`, whether or not
       it fired;
    4. no errors and the listing completed — `ok`;
    5. no errors, nothing scanned, nothing invalidated, and the adapter
       proved the board empty from its own response (`empty_proven`) — `empty`;
    6. no errors and our time ceiling cut it while it was still producing —
       `bounded`;
    7. no errors and our page ceiling cut a listing still serving items —
       `truncated`;
    8. no errors, and the only thing lost was a negligible fraction of
       individual records — `lossy`;
    9. our host was suspended mid-scan, or had no network when the source
       failed (`offline`: no job site accepted a connection) —
       `suspended`;
    10. otherwise it is a pathology: `degraded` if it still scanned something,
        `failed` if it produced nothing at all.

    Rule 9 is the third bound that is ours, and the only one that can fire on a
    run that *also* errored — which is why it sits below the no-error block and
    above the pathology split rather than beside `capped`. A host suspension
    does not raise where it happens; it lands as a transport error on the far
    side of it, because every socket open across the gap is dead on resume. So
    "there are errors" cannot be the thing that rules it out, or the rule would
    never fire at all.

    That precedence means a source genuinely breaking *during* a suspension is
    recorded as suspended, and its one run of real evidence is lost. That is the
    deliberate direction to be wrong in, and it is the same trade rules 6-8
    already make: a missed pathology costs one run of judgement, which the next
    un-suspended run supplies, while a false pathology resets every posting's
    absence count. `list_complete` is untouched either way, so closure stays
    suppressed regardless.

    Rule 8 is proportionality, and it is the one rule here that judges a
    *source-caused* incompleteness as inert. The justification is not "it was
    our bound" — it plainly was not — but that the run is overwhelming evidence
    about the source and a rounding error of counter-evidence: losing a handful
    of records out of thousands says the same about the source as losing none.
    Above the ratio the reading flips, because a source shedding 1%
    of its records really has changed shape.

    Note what rule 8 does *not* relax: `list_complete` is already False, so
    closure stays suppressed for the run either way. The rule decides only
    whether the source is judged, never whether absence may close a job.

    Rule 3 outranks a complete listing. A board that finishes under
    its `--max-list` did enumerate completely, and `list_complete` stays true to
    say so, but the run is still a test the operator bounded, not evidence
    about the source. Closure by the capped run itself is gated separately:
    that gate reads `max_list` directly (`run_persistence.should_close_missing`).

    Errors beat a cap deliberately (rules 3-8 require none): a capped run that
    also errored is not a clean operator choice.

    An operator cap outranks our ceiling when both fired: `--max-list` is an
    explicit instruction, and letting `bounded` win would make the source
    retry-eligible and thereby override that instruction.

    A *stall* is not here — silence is the source's own pathology and lands in
    `errors`, so it skips rules 3-8 and lands in rule 10. That asymmetry is the whole point of
    the split: `bounded` is our bound, `degraded` is its behavior.
    """
    if stats.get("unattempted"):
        return SourceOutcome.UNATTEMPTED

    # A detected block outranks the generic pathology split: "the source is
    # refusing us" needs a different operator response than "it errored", and
    # folding it into `degraded`/`failed` would hide exactly that distinction.
    # It is still a pathology (it resets absence), so precedence over the bounds below
    # never matters — a blocked source always carries the CircuitOpenError.
    if stats.get("blocked"):
        return SourceOutcome.BLOCKED

    errors = stats.get("errors") or []
    if not errors:
        # Cap first: over a board that finished under it the listing is complete
        # too, and that must not read as evidence.
        if stats.get("capped"):
            return SourceOutcome.CAPPED
        if stats.get("list_complete"):
            return SourceOutcome.OK
        # Positive proof only, and only alone. A zero the adapter
        # could not explain carries a listing invalidation and falls through to
        # `failed`: that is the empty-versus-broken line, drawn per family.
        if (
            stats.get("empty_proven")
            and not stats.get("listing_invalidated")
            and not int(stats.get("scanned") or 0)
        ):
            return SourceOutcome.EMPTY
        if stats.get("bounded"):
            return SourceOutcome.BOUNDED
        if stats.get("truncated"):
            return SourceOutcome.TRUNCATED
        if _record_loss_is_negligible(stats):
            return SourceOutcome.LOSSY

    # Checked after the no-error block so a source that finished its listing
    # before the host went down still reads `ok`, and before the pathology split
    # so the transport errors the suspension itself caused are attributed to us.
    # A dropped connection lands the same way, without the clock gap that gives
    # a sleep away; `offline` is the probe's word that no job site answered.
    if stats.get("suspended") or stats.get("offline"):
        return SourceOutcome.SUSPENDED

    # Incomplete for a non-cap reason, or errored: did we still see anything?
    # `scanned`, not `kept` — a source can legitimately scan a full board and
    # keep nothing (all out of scope) and still be a good observation.
    if int(stats.get("scanned") or 0) > 0:
        return SourceOutcome.DEGRADED
    return SourceOutcome.FAILED


def board_missing(stats: Mapping) -> bool:
    """A `failed` read whose board root answered that no such board exists.

    A cause within `failed`, not an outcome of its own: closure and the run's
    status read it exactly as any other failed read. What differs is who
    it is about. A board that 404s is the COMPANY's fact (it moved or stopped
    using this board), so it is no
    pressure on the provider, a retry an hour later learns nothing, and the
    person is told once per company by Coverage, never by every scan.
    """
    return bool(stats.get("board_missing")) and classify_source_outcome(stats) is SourceOutcome.FAILED


def run_status_for(outcomes: Iterable[SourceOutcome]) -> str:
    """Project per-source outcomes onto `scrape_runs.status`.

    A **total** function, top-down (first match wins):

    * `ok` — every source is `ok` or `capped`;
    * `error` — no source produced usable data;
    * `partial` — everything else.

    Totality is the point: "8 healthy sources + 1 throttled" must not read as
    "nothing worked". `partial` counts as a successful refresh
    (`health.REFRESHED_STATUSES`), so one throttled source cannot keep the tree
    stale; a degraded source surfaces through its own outcome instead.
    """
    outcomes = list(outcomes)
    if all(outcome in CLEAN for outcome in outcomes):
        return "ok"
    if not any(outcome in USABLE for outcome in outcomes):
        return "error"
    return "partial"


#: `scrape_runs.notes` of a run the person stopped (`POST /api/sync/cancel`).
#: The notification pass reads it to tell their own stop from a failure.
STOPPED_BY_USER_NOTE = "cancelled by user"


def cancelled_run_status(outcomes: Iterable[SourceOutcome]) -> str:
    """The status of a run stopped before it finished, from what it recorded.

    Since sources persist as they finish, a cancelled run can hold
    committed sources: `error` would say none produced usable data, against
    rows the run wrote. So the projection, capped at `partial`: a run that
    stopped early is never a clean `ok`, whatever it reached.
    """
    return "partial" if any(outcome in USABLE for outcome in outcomes) else "error"
