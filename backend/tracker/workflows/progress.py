"""Live per-run scrape progress: in-memory counters published to the UI.

The pipeline runs in two phases that are invisible from the outside:

    collect_sources(...)   concurrent; writes NOTHING to the DB itself
    _RunWriter             the run's one writer, fed by collection as it reads:
                           rows as they arrive, each company as it ends

Until the persist loop starts, ``ScrapeRun.jobs_seen``/``per_source`` are zero,
so a run that is minutes deep into hydration looks identical to a stalled one.
``RunProgress`` closes that gap: collectors report starts and completions into
this object in memory, and the caller publishes snapshots (heartbeat during
collect, inline during persist) into the run's ``sync_started`` notification.

**Every aggregate is derived from the per-company map**, never incremented.
That is load-bearing, not stylistic: a company is reported by the collector hook
*and* again by the post-collect reconcile pass, so counters that were bumped by
each caller would double-count. Deriving makes the second report a no-op by
construction and makes ``companies_scraping`` honest for free, where
``total - collected`` would count every queued company as in flight even
though the collector semaphore admits at most a handful at a time.

Two orthogonal axes describe a company, and they must not be collapsed:

* ``state`` — lifecycle position (queued -> scraping -> collected -> persisting
  -> recorded). Says *where* a company is.
* ``outcome`` — a verbatim ``SourceOutcome``. Says *how it went*, and stays
  ``None`` until collection ends. This module deliberately owns no outcome
  vocabulary of its own (see ``connectors/recipes/outcome.py``).

Ownership: counters only. This module never touches the DB and never decides
run health — liveness stays with ``heartbeat_at`` and the reconciler.

Concurrency: mutated from collector tasks on one asyncio event loop, so plain
attribute assignment is atomic here. Do not share across threads/processes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tracker.connectors.recipes.outcome import SourceOutcome

#: Phase names published to the UI. ``collecting`` covers fetch+hydrate (no DB
#: writes); ``persisting`` covers the serial upsert loop; ``finishing`` covers
#: post-passes after the last company is committed.
PHASES = ("collecting", "persisting", "finishing")

#: Per-company lifecycle, in order. Rank comparison against this tuple is what
#: makes every transition monotonic, and monotonicity is what makes the
#: reconcile pass idempotent and unable to downgrade a further-along company.
COMPANY_STATES = ("queued", "scraping", "collected", "persisting", "recorded")

_STATE_RANK = {name: index for index, name in enumerate(COMPANY_STATES)}

#: States in which this company's collection has finished, whatever the outcome.
_COLLECTED_STATES = frozenset({"collected", "persisting", "recorded"})

#: Beyond this many companies, drop the still-queued entries from the published
#: payload. The aggregates already carry them, and ``meta`` is rewritten whole on
#: every publish — a roster of hundreds of identical "not yet" rows is the one
#: part of this snapshot that grows without telling the reader anything.
_MAX_PUBLISHED_COMPANIES = 200


def _now_ms() -> int:
    """Epoch milliseconds. Wall clock, deliberately: the UI subtracts this from
    its own ``Date.now()``, so a monotonic source would be meaningless there."""
    return int(datetime.now(UTC).timestamp() * 1000)


@dataclass
class CompanyProgress:
    """One company's live position in a run.

    ``detected`` is in-scope keeps (``len(collection.enriched)``); ``scanned`` is
    everything the listing returned. Both are needed because a source that
    scanned a full board and kept nothing is a *successful* observation, and
    without ``scanned`` it is indistinguishable from one that saw nothing at all.
    """

    slug: str
    state: str = "queued"
    outcome: str | None = None
    #: Epoch ms at which this company entered ``state``. ``None`` while queued —
    #: nothing has happened yet, and a fake timestamp would start a clock.
    since_ms: int | None = None
    detected: int = 0
    scanned: int = 0
    recorded: int = 0

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "state": self.state,
            "outcome": self.outcome,
            "since_ms": self.since_ms,
            "detected": self.detected,
            "scanned": self.scanned,
            "recorded": self.recorded,
        }


@dataclass
class RunProgress:
    """Mutable per-company progress for one live run.

    ``detected`` counts opportunities held in memory after a source's collection
    finishes; ``recorded`` counts them after their company's persist commit.
    Detected therefore leads recorded, and both lead the run's final totals.
    """

    companies_total: int
    phase: str = "collecting"
    #: ``scraper_max_concurrent_sources``, published so the UI knows the ceiling
    #: on in-flight sources without hard-coding a backend setting.
    concurrency_limit: int = 0
    companies: dict[str, CompanyProgress] = field(default_factory=dict)
    #: Injectable so tests can pin timestamps. Excluded from equality/repr so two
    #: progress objects compare on their counters, not on their clocks.
    clock: Callable[[], int] = field(default=_now_ms, repr=False, compare=False)

    # ----------------------------------------------------------------- setup --

    def set_targets(self, slugs: Iterable[str], *, concurrency_limit: int) -> None:
        """Seed the roster once targets are resolved.

        Order is preserved: the published list keeps the pipeline's target order
        so the UI can render a stable roster rather than a set.
        """
        self.companies = {slug: CompanyProgress(slug=slug) for slug in slugs}
        self.companies_total = len(self.companies)
        self.concurrency_limit = max(0, concurrency_limit)

    def join(self, company: str) -> None:
        """A company asked for while the run reads: queued in the roster it shows."""
        self._entry(company)

    # ------------------------------------------------------------ transitions --

    def _advance(self, entry: CompanyProgress, state: str) -> bool:
        """Move an entry forward, never backward. False means "already past it"."""
        if _STATE_RANK[state] <= _STATE_RANK[entry.state]:
            return False
        entry.state = state
        entry.since_ms = self.clock()
        return True

    def _entry(self, company: str) -> CompanyProgress:
        """Fetch or create. Creating covers callers that never ran ``set_targets``
        (tests wiring the hooks directly), so a hook can never KeyError."""
        entry = self.companies.get(company)
        if entry is None:
            entry = CompanyProgress(slug=company)
            self.companies[company] = entry
            self.companies_total = max(self.companies_total, len(self.companies))
        return entry

    def source_started(self, company: str) -> None:
        """One source acquired a collector slot. Called from collector tasks.

        Fires only for companies actually attempted — a company the run ran out
        of time to reach must go straight from ``queued`` to its outcome, or the
        UI would show a clock ticking on work that never began.
        """
        self._advance(self._entry(company), "scraping")

    def source_collected(
        self,
        company: str,
        detected: int,
        outcome: str,
        scanned: int = 0,
    ) -> None:
        """One source finished fetch+hydrate.

        Positional-friendly: this is passed directly as the ``on_source_done``
        callback, so the parameter order is part of that contract.

        ``outcome`` is a ``SourceOutcome`` *value*; constructing the enum here is
        the guard against a second outcome vocabulary drifting into the UI.
        """
        SourceOutcome(outcome)
        entry = self._entry(company)
        if not self._advance(entry, "collected"):
            return
        entry.outcome = outcome
        entry.detected = max(0, detected)
        entry.scanned = max(0, scanned)

    def source_persist_started(self, company: str) -> None:
        """This company's rows are being written. Persist is serial, so at most
        one company is in this state at a time."""
        self._advance(self._entry(company), "persisting")

    def source_recorded(self, company: str, kept: int) -> None:
        """One company's rows are committed.

        Never raises on an unknown slug: this runs inside the pipeline's own DB
        transaction, where a display-only counter must not be able to abort a
        commit that already succeeded.
        """
        entry = self.companies.get(company)
        if entry is None or not self._advance(entry, "recorded"):
            return
        entry.recorded = max(0, kept)

    def reconcile_collected(self, results: Mapping[str, tuple[int, str, int]]) -> None:
        """Force any company the collector never reported into its real outcome.

        ``collect_sources`` fills in a failed collection for every company a
        cancelled or crashed backend never produced, but those paths do not fire
        the completion hook. Without this pass those companies would stay
        ``scraping`` for the rest of the run and the UI would show phantom
        in-flight sources with forever-growing clocks.

        Idempotent by construction: companies that already reported are past
        ``collected`` and ``_advance`` refuses to move them.
        """
        for company, (detected, outcome, scanned) in results.items():
            entry = self.companies.get(company)
            if entry is not None and entry.state in _COLLECTED_STATES:
                continue
            self.source_collected(company, detected, outcome, scanned)

    def set_phase(self, phase: str) -> None:
        if phase not in PHASES:  # pragma: no cover - guarded by callers
            raise ValueError(f"unknown phase: {phase}")
        self.phase = phase

    # -------------------------------------------------------------- aggregates --

    def _count(self, predicate: Callable[[CompanyProgress], bool]) -> int:
        return sum(1 for entry in self.companies.values() if predicate(entry))

    @property
    def companies_collected(self) -> int:
        """Sources whose collection has finished, successfully or not."""
        return self._count(lambda c: c.state in _COLLECTED_STATES)

    @property
    def companies_recorded(self) -> int:
        return self._count(lambda c: c.state == "recorded")

    @property
    def companies_scraping(self) -> int:
        """Sources genuinely in flight — never queued ones.

        Bounded by ``min(concurrency_limit, distinct backends with work left)``,
        because the collector semaphore is held per *backend* and a backend
        drains its companies serially.
        """
        return self._count(lambda c: c.state == "scraping")

    @property
    def companies_queued(self) -> int:
        return self._count(lambda c: c.state == "queued")

    @property
    def companies_failed(self) -> int:
        """Sources that produced no usable data at all.

        Strictly ``SourceOutcome.FAILED``: a degraded source returned usable
        observations and is reported separately, because calling it a failure is
        what makes a healthy partial run look broken.
        """
        return self._count(lambda c: c.outcome == SourceOutcome.FAILED.value)

    @property
    def companies_degraded(self) -> int:
        return self._count(lambda c: c.outcome == SourceOutcome.DEGRADED.value)

    @property
    def opportunities_detected(self) -> int:
        return sum(entry.detected for entry in self.companies.values())

    @property
    def opportunities_recorded(self) -> int:
        return sum(entry.recorded for entry in self.companies.values())

    @property
    def opportunities_pending(self) -> int:
        """Detected but not yet written to the DB.

        Clamped: closure reconciliation can commit more rows than this run
        detected, and a negative backlog is meaningless to a reader.
        """
        return max(0, self.opportunities_detected - self.opportunities_recorded)

    # ---------------------------------------------------------------- publish --

    def _published_companies(self) -> list[dict]:
        entries = list(self.companies.values())
        if len(entries) > _MAX_PUBLISHED_COMPANIES:
            entries = [entry for entry in entries if entry.state != "queued"]
        return [entry.as_dict() for entry in entries]

    def snapshot(self) -> dict:
        """Serializable view merged into ``notification.meta.progress``.

        Percent is company-weighted across both phases: collection is the first
        half of the work, persistence the second. It is a progress hint, not a
        time estimate — sources differ by orders of magnitude in job count.

        ``snapshot_at_ms`` is the reader's anchor. Timestamps go over the wire as
        absolute server epochs rather than durations precisely because progress
        is republished only every heartbeat: a duration cannot be re-anchored, so
        the UI would have to guess how stale it is, whereas an epoch plus a skew
        estimate lets it tick a correct clock between publishes.
        """
        total = self.companies_total
        if total > 0:
            done = self.companies_collected + self.companies_recorded
            percent = round(100 * done / (2 * total))
        else:
            # total == 0 means "targets not resolved yet" during run open, or a
            # run with nothing to do. Either way there is no work to report.
            percent = 0
        return {
            "phase": self.phase,
            "percent": min(100, max(0, percent)),
            "companies_total": total,
            "companies_collected": self.companies_collected,
            "companies_recorded": self.companies_recorded,
            "companies_scraping": self.companies_scraping,
            "companies_queued": self.companies_queued,
            "companies_failed": self.companies_failed,
            "companies_degraded": self.companies_degraded,
            "opportunities_detected": self.opportunities_detected,
            "opportunities_recorded": self.opportunities_recorded,
            "opportunities_pending": self.opportunities_pending,
            "concurrency_limit": self.concurrency_limit,
            "snapshot_at_ms": self.clock(),
            "companies": self._published_companies(),
        }
