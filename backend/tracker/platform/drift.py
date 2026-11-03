"""Schema-drift accumulation for scraped/parsed external sources."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DriftError(Exception):
    """Raised when a source's payload does not match what the adapter expects."""


class SchemaDriftDetector:
    """Accumulates drift observations for a single source run.

    `note()` records best-effort detail drift. `require()`, `drop_record()` and
    `invalidate_listing()` additionally mark the listing as incomplete so the
    consumer cannot interpret absent IDs as closed items. The pipeline records
    every alert on the ScrapeRun either way.

    **Incompleteness and pathology are two different claims**. Both
    channels below suppress closure, because a record we could not read is a
    record whose absence proves nothing. Only the listing-level channel also
    says the source is *broken*:

    * `invalidate_listing()` / `require()` — a page or a listing-wide invariant
      failed (non-200, non-JSON, no `jobPostings` array). We lost an unbounded,
      unknowable amount of the board.
    * `drop_record()` — one item in an otherwise-served page was unusable. The
      loss is bounded and counted, so downstream can weigh it against `scanned`
      instead of treating a few bad rows in a large board as a broken source.

    `observe_present()` is not a loss channel at all and deliberately sits
    outside that split: a row that names its requisition and nothing
    else is unusable *as a posting* but is still evidence that requisition is
    on the board, which is the only thing closure needs from it. Recording the
    key instead of discarding it is what keeps the run complete.

    Merged, a handful of stub rows would make `listing_complete` False with no
    error recorded, and `classify_source_outcome` would read a near-perfect
    scan as `degraded`, counting it against the source.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.alerts: list[dict] = []
        #: Set only by the listing-level channel: a page or listing invariant
        #: failed, so the extent of what we missed is unknown.
        self.listing_invalidated = False
        #: Count of individually-unusable items. Bounded, knowable loss.
        self.records_dropped = 0
        #: Keys of rows that identified a requisition but could not be built
        #: into a posting. Presence evidence, not loss — see `observe_present`.
        self.present_only: set[str] = set()
        #: The board answered in full and its own shape says it lists nothing
        #: (`board_empty`). Not a loss and not a pathology, but never closure
        #: evidence either: see `listing_complete`.
        self.empty_proven = False
        #: The board root answered 404/410: no such board (`board_missing`).
        self.board_gone = False

    @property
    def listing_complete(self) -> bool:
        """True only when nothing was lost — the closure-authority gate.

        Derived rather than assigned so a new loss channel cannot forget to
        close it: every way of losing data must show up here. A board proven
        empty is not a loss, but closing every posting on it needs a separate
        two-confirmation contract, which does not exist yet, so it is never complete.
        """
        return not self.listing_invalidated and self.records_dropped == 0 and not self.empty_proven

    def note(self, message: str, **context) -> None:
        alert = {"source": self.source, "message": message, **context}
        self.alerts.append(alert)
        logger.warning("drift[%s]: %s %s", self.source, message, context or "")

    def drop_record(self, message: str, **context) -> None:
        """Record one unusable item within an otherwise-served listing.

        Suppresses closure like any other loss, but keeps the loss *countable*
        so proportionality is expressible downstream. Use this only when the
        rest of the page parsed; a failure that costs a whole page is
        `invalidate_listing()`.
        """
        self.records_dropped += 1
        self.note(message, **context)

    def records_unaccounted(self, count: int, message: str, **context) -> None:
        """Record rows the board COUNTED that the walk never served.

        A counted listing that reads fewer unique rows than it declares lost a
        known number of rows, not an unknown slice of the board: a board that
        loses a posting mid-walk shifts every later row up past the reader, so
        exactly that many live rows went unread. Bounded, countable loss is
        what `drop_record` exists for, so it lands in the same count — closure
        is suppressed, and the outcome weighs it against what was observed.
        A large shortfall (a relevance sort re-serving rows) still crosses the
        drop ratio.
        One alert, however many rows.
        """
        if count <= 0:
            return
        self.records_dropped += count
        self.note(message, missing=count, **context)

    def observe_present(self, key: str, message: str, **context) -> None:
        """Record a row we could not build, but whose identity we read anyway.

        A source can serve a row like `{"bulletFields": ["JR2021715"]}` for a
        live requisition: no title, no `externalPath`, stable across refetches
        and returned by a direct id search. Routed through `drop_record` it
        would cost the whole board: `listing_complete` False every run, closure
        suppressed for every healthy posting to protect one, and the drop ratio
        eventually crossing `_RECORD_DROP_ANOMALY_RATIO` against a source that
        did nothing wrong.

        Nothing was actually lost that closure cares about. The key is what
        `close_missing` compares, so handing it back keeps that one req open on
        its existing row while every other job stays reconcilable. The listing
        is complete: we enumerated the board, and one row of it is stale.

        Keyed and idempotent — a source scanned through several overlapping
        location queries meets the same stub once per query, and a set makes
        the observation count postings rather than sightings.
        """
        if key in self.present_only:
            return
        self.present_only.add(key)
        alert = {"source": self.source, "message": message, "key": key, **context}
        self.alerts.append(alert)
        # Info, not warning: this is a row the source served badly, not a
        # symptom of our scrape going wrong, and it repeats every run for as
        # long as the source leaves the row that way.
        logger.info("present-only[%s]: %s %s", self.source, message, context or "")

    def invalidate_listing(self, message: str, **context) -> None:
        """Record listing drift that makes absence unsafe closure evidence."""
        self.listing_invalidated = True
        self.note(message, **context)

    def board_missing(self, message: str, *, status: int, **context) -> None:
        """The board's own address answered that no such board exists.

        Only an adapter's FIRST request to its board root says this: on a
        multi-tenant family an unknown tenant answers 404 (or 410), the same
        answer a made-up token gets, while a tenant that exists and lists
        nothing answers 200 (`board_empty`). A 404 on page five is a lost page,
        never a missing board, so the adapter decides where this is asked.

        Recorded as a listing invalidation, so closure and the outcome are
        unchanged (`failed`), and flagged on the alert as `board_missing`: the
        company moved or stopped using this board, which is the company's fact,
        not the provider pushing back (`outcome.board_missing`). Any
        other status is a plain listing invalidation.
        """
        if status in (404, 410):
            self.board_gone = True
            self.invalidate_listing(message, status=status, board_missing=True, **context)
        else:
            self.invalidate_listing(message, status=status, **context)

    def require(self, condition: bool, message: str, **context) -> None:
        """Require a listing-level schema invariant."""
        if not condition:
            self.invalidate_listing(message, **context)

    def board_empty(self, evidence: str, **context) -> None:
        """The board answered in full, and its own shape says it lists nothing.

        Positive evidence only: the response envelope is present and
        either its declared total is 0 or its posting array is present and
        empty, on a family whose unknown tenant does NOT answer that way (it
        404s, or names another board). A zero the adapter cannot explain is
        not this; `settle_listing` records it as the pathology it may be.

        Recorded as a log line, not an alert: nothing went wrong with the read,
        and an alert on a zero-row run is what marks a role catalog failed. The
        run classifies `empty`: nothing counted against the source, no provider
        pressure, no closure. What it cannot prove is that the company still
        lists roles somewhere else (a board the company abandoned answers
        exactly this),
        which is why the attention report keeps every empty board in view.
        """
        self.empty_proven = True
        logger.info("empty[%s]: %s %s", self.source, evidence, context or "")

    def settle_listing(self, *, scanned: int) -> None:
        """The zero-row rule, applied once a listing ran to its natural end.

        A listing that served no rows is never complete, whichever adapter read
        it. Closure by absence on an empty board needs a separate
        two-confirmation contract, which does not exist yet;
        until it does, "complete and empty" would close every open posting of
        the company. Applied here once rather than by each adapter: a counted
        board answering a total of 0 ends through `close_listing`, which
        records nothing for 0 of 0.

        Rows the walk saw but could not use (`records_dropped`, `present_only`)
        mean the board was not empty, so they are not this rule's business. A
        listing an adapter already invalidated keeps its own message alone: the
        attention report reads the run's drift as its cause.
        """
        if scanned or self.present_only or self.records_dropped:
            if self.empty_proven:
                # The proof contradicts the rows: neither claim can be trusted.
                self.empty_proven = False
                self.invalidate_listing("board stated it was empty but listed postings")
            return
        if self.listing_invalidated or self.empty_proven:
            return
        self.invalidate_listing("listing yielded no postings")
