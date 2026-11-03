"""What a finished or starting scan says: the run-health classifiers.

`classify_sync_started` writes the "Scanning ..." row and `classify_sync_result`
the run's terminal row, or nothing for a clean run; `run_diagnostics` is the
per-source payload a run's row expands into. Pure: they read a `ScrapeRun`
and return a `ClassifiedNotif`, and `store` persists it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tracker.connectors.recipes.outcome import (
    CLEAN,
    STOPPED_BY_USER_NOTE,
    SourceOutcome,
    board_missing,
    classify_source_outcome,
)
from tracker.db.models import ScrapeRun
from tracker.notifications import say as S
from tracker.notifications.events import ClassifiedNotif, _said
from tracker.notifications.render import (
    _fmt_time,
    _source_summary,
    affected_slugs,
    company_namer,
)


def _duration_seconds(run: ScrapeRun) -> float | None:
    if run.started_at is None or run.finished_at is None:
        return None
    return max(0.0, (run.finished_at - run.started_at).total_seconds())


def _source_totals(run: ScrapeRun) -> tuple[int, int]:
    skipped = 0
    updated = 0
    for stats in (run.per_source or {}).values():
        if not isinstance(stats, dict):
            continue
        kept = int(stats.get("kept") or 0)
        new = int(stats.get("new") or 0)
        closed = int(stats.get("closed") or 0)
        for key in ("skipped", "unchanged"):
            value = stats.get(key)
            if isinstance(value, int):
                skipped += value
        updated += max(0, kept - new) + max(0, closed)
    return skipped, updated


@dataclass(frozen=True)
class _Unfinished:
    """The sources a run did not finish for a reason that was OURS.

    `unreached`: a stored run's deadline came before the company started. Only
    `deferred_reason` says that (the marker `run_persistence` reads too):
    `unattempted` alone also covers a policy refusal and an adapter this build
    lacks, and neither is a timeout.
    A deferred company also carries the run-deadline marker in `errors`, so
    reading `errors` alone would name it both as a problem and as not reached
    in one notification.

    `cut_short`: our own time ceiling stopped a listing still producing
    (`bounded`). A retry pass takes it again and its learned budget grows, so
    it is this run's news.

    `quiet`: ours, and never a run's news, because it is the same every run.
    A policy refusal is a standing decision (the operator's deny list, a wall
    awaiting consent), reported where it is decided: the schedule's
    `policy_denied`, the Companies row's "Needs consent". A fetch tier this
    build lacks refuses the same way and is named only in the run's own
    per-source record (`policy_reason`, served by the run log). A page ceiling
    (`truncated`) is deterministic (outcome.py leaves it out of `RETRYABLE`),
    so a board past it would read "only in part" on every run, promising a
    complete read that never comes; the Companies row says "partly counted".

    An adapter this build lacks is none of these: it records an error and
    stays a problem.

    `offline`: no job site accepted a connection when the company's read
    failed, or when its lane reached it. Our network, not the
    company, so it is named with what happens next, never as a problem.
    """

    unreached: list[str]
    cut_short: list[str]
    quiet: list[str]
    offline: list[str] = field(default_factory=list)

    @property
    def named(self) -> bool:
        return bool(self.unreached or self.cut_short or self.offline)


@dataclass(frozen=True)
class _RunSources:
    """One pass over a run's per-source stats, read by every branch of the result.

    `outcome`: each source's `classify_source_outcome`, the one outcome
    vocabulary, in the run's order. `errors`: the sources that recorded
    errors, as text. `suspended`: sources whose collection window held a host
    suspension, with its length in seconds, so the row can say how long the
    machine was down; such a source may still have collected cleanly, since
    the suspension can land after its listing finished. `unfinished`: what the
    run left undone for a reason that was ours (`_Unfinished`).

    `told`: sources a run says nothing about, however their reads ended.
    `lossy`: the board was read in full but for under 1% of its rows, which is
    a successful refresh everywhere else in RoleBand (health-inert, a full scan
    for Coverage, rechecked at the cadence) and the same loss the next run,
    so naming it would ring on every run. A board gone from its address: the
    company moved its careers page, which Coverage tells once per company
    (`outcome.board_missing`); every scan repeating it would flood the feed.
    """

    outcome: dict[str, SourceOutcome]
    errors: dict[str, list[str]]
    told: frozenset[str]
    unfinished: _Unfinished
    suspended: dict[str, float]

    @property
    def settled(self) -> frozenset[str]:
        """Sources whose read ended clean (`ok`, `capped`, `empty`)."""
        return frozenset(source for source, outcome in self.outcome.items() if outcome in CLEAN)

    @property
    def ours(self) -> frozenset[str]:
        unfinished = self.unfinished
        return frozenset({*unfinished.unreached, *unfinished.cut_short, *unfinished.quiet, *unfinished.offline})

    @property
    def deferred(self) -> frozenset[str]:
        """A deferred company carries the run-deadline marker in `errors`,
        and one our outage cut carries its transport
        errors, but nothing went wrong AT either: each is named as not reached
        or as cut by our connection, never as a problem."""
        return frozenset({*self.unfinished.unreached, *self.unfinished.offline})

    @property
    def named_errors(self) -> dict[str, list[str]]:
        """The errors a run names: of neither a source told elsewhere nor one
        deferred. One filter for the list of sources and for their texts."""
        return {
            source: errors
            for source, errors in self.errors.items()
            if source not in self.deferred and source not in self.told
        }

    def imperfect(self) -> list[str]:
        """Sources less than clean that the run itself must account for."""
        return [
            source
            for source, outcome in self.outcome.items()
            if source not in self.told and outcome not in CLEAN
        ]

    def only_ours(self) -> bool:
        """Every source that was less than clean is one `_Unfinished` accounts for."""
        imperfect = self.imperfect()
        return bool(imperfect) and all(source in self.ours for source in imperfect)


def _read_sources(run: ScrapeRun) -> _RunSources:
    outcomes: dict[str, SourceOutcome] = {}
    errors: dict[str, list[str]] = {}
    told: set[str] = set()
    suspended: dict[str, float] = {}
    unreached: list[str] = []
    cut_short: list[str] = []
    quiet: list[str] = []
    offline: list[str] = []
    for source, stats in (run.per_source or {}).items():
        if not isinstance(stats, dict):
            continue
        outcome = outcomes[source] = classify_source_outcome(stats)
        if stats.get("errors"):
            errors[source] = [str(error) for error in stats.get("errors") or []]
        if outcome is SourceOutcome.LOSSY or board_missing(stats):
            told.add(source)
        if stats.get("suspended"):
            suspended[source] = float(stats.get("suspended_seconds") or 0.0)
        if stats.get("offline"):
            offline.append(source)
        elif outcome is SourceOutcome.UNATTEMPTED and stats.get("deferred_reason"):
            unreached.append(source)
        elif outcome is SourceOutcome.UNATTEMPTED and stats.get("policy_reason"):
            quiet.append(source)
        elif outcome is SourceOutcome.BOUNDED:
            cut_short.append(source)
        elif outcome is SourceOutcome.TRUNCATED:
            quiet.append(source)
    unfinished = _Unfinished(sorted(unreached), sorted(cut_short), sorted(quiet), sorted(offline))
    return _RunSources(outcomes, errors, frozenset(told), unfinished, suspended)


def _drift_company(source: str) -> str:
    """The company a drift alert is about: alerts are `{adapter}:{company}`."""
    return source.split(":", 1)[1] if ":" in source else source


def _unfinished_title_say(unfinished: _Unfinished) -> S.Say:
    """`_unfinished_title` as a key per combination of what went unfinished."""
    unreached, offline, cut = len(unfinished.unreached), len(unfinished.offline), len(unfinished.cut_short)
    key = "notif-unfinished-" + "".join(tag for tag, n in (("u", unreached), ("o", offline), ("c", cut)) if n)
    params: dict = {}
    if unreached:
        params["unreached"] = S.companies(unreached)
    if offline:
        params["offline"] = S.companies(offline)
    if cut:
        # Alone it counts companies ("read 2 companies only in part"); after
        # another part it is a bare number ("and read 2 only in part").
        params["cut"] = S.companies(cut) if not (unreached or offline) else cut
    return S.say(key, **params)


def _unfinished_say(unfinished: _Unfinished, label: Callable[[str], str]) -> list[S.Say]:
    """`_unfinished_sentences`, one message per sentence."""
    out: list[S.Say] = []
    if unfinished.unreached:
        out.append(S.say(
            "notif-unreached",
            sources=S.sources([label(s) for s in unfinished.unreached]),
            count=len(unfinished.unreached),
        ))
    if unfinished.offline:
        out.append(S.say(
            "notif-offline",
            sources=S.sources([label(s) for s in unfinished.offline]),
            count=len(unfinished.offline),
        ))
    if unfinished.cut_short:
        out.append(S.say("notif-cut-short", sources=S.sources([label(s) for s in unfinished.cut_short])))
    return out


#: Keys in a per-source stats dict that are counters, not diagnostic payload.
_SOURCE_COUNTERS = ("scanned", "kept", "new", "closed")


def _drift_rows(run: ScrapeRun) -> list[dict]:
    """Normalize adapter drift alerts into {source, message, context} rows.

    Adapters emit a flat dict: `{"source": ..., "message": ..., **context}` (see
    `SchemaDriftDetector.note`). The context keys are the actual debugging payload
    (status codes, req ids, selectors), so split them out rather than dropping them.
    """
    rows: list[dict] = []
    for alert in run.drift_alerts or []:
        if not isinstance(alert, dict):
            rows.append({"source": "unknown", "message": str(alert), "context": {}})
            continue
        context = {
            key: value
            for key, value in alert.items()
            if key not in ("source", "message") and value is not None
        }
        rows.append(
            {
                "source": str(alert.get("source") or "unknown"),
                "message": str(alert.get("message") or "drift recorded"),
                "context": context,
            }
        )
    return rows


def _source_rows(run: ScrapeRun) -> list[dict]:
    """Per-source scan table, worst-first: errors, then drift, then healthy."""
    rows: list[dict] = []
    for source, stats in (run.per_source or {}).items():
        if not isinstance(stats, dict):
            continue
        errors = [str(e) for e in (stats.get("errors") or [])]
        drift = [d for d in (stats.get("drift") or []) if isinstance(d, dict)]
        row = {
            "source": source,
            # The pipeline already derived why this source was less than clean
            # (ok/capped/degraded/failed); surfacing it here is what makes a
            # `partial` run explainable in the notification center instead of
            # leaving the reader to infer it from the error strings.
            "outcome": stats.get("outcome"),
            "errors": errors,
            "drift_count": len(drift),
            "duration_seconds": stats.get("duration_seconds"),
        }
        for key in _SOURCE_COUNTERS:
            row[key] = int(stats.get(key) or 0)
        rows.append(row)
    rows.sort(key=lambda r: (0 if r["errors"] else 1 if r["drift_count"] else 2, r["source"]))
    return rows


def run_diagnostics(run: ScrapeRun) -> dict:
    """Structured, copy-pasteable debugging payload for a scrape run.

    This is what the notification center expands into. It is deliberately a
    superset of the summary line: the summary says *that* something went wrong,
    this says *where*, *how often*, and *with what status code*.
    """
    sources = _source_rows(run)
    return {
        "run_id": run.id,
        "run_status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": _duration_seconds(run),
        "totals": {
            "jobs_seen": run.jobs_seen,
            "jobs_new": run.jobs_new,
            "jobs_closed": run.jobs_closed,
            "sources_ok": sum(1 for r in sources if not r["errors"] and not r["drift_count"]),
            "sources_total": len(sources),
        },
        "sources": sources,
        "drift": _drift_rows(run),
        "errors": [
            {"source": source, "error": error}
            for source, errors in _read_sources(run).errors.items()
            for error in errors
        ],
        "notes": run.notes or None,
    }


def classify_sync_started(
    run: ScrapeRun, sources: list[str], *, names: Mapping[str, str] | None = None
) -> ClassifiedNotif:
    """The "Scanning ..." row. Companies by the names the person follows them
    under (`names`, slug -> display; `_company_label` otherwise). No clock time
    in the words: the feed shows when the row was written, in the reader's own
    time, and a time written here would be the server's."""
    started = run.started_at or datetime.now(UTC)
    source_count = len(sources)
    label = company_namer(names)
    return ClassifiedNotif(
        priority="normal",
        category="sync_started",
        meta={
            "sync_state": "running",
            "started_at": started.isoformat(),
            "source_count": source_count,
            "sources": sources,
            "say": _said(
                S.say("notif-scan-started"),
                S.say("notif-scan-started-body", count=source_count, sources=S.sources([label(s) for s in sources]))
                if source_count
                else S.say("notif-scan-started-all-body", sources=S.sources([])),
            ),
        },
    )


#: The category of a run whose only imperfection was our own time:
#: its own, not `sync_warning`, because the category is what the feed files and
#: filters by, and "the scan ran out of time" is not "the scan had problems".
SYNC_UNFINISHED = "sync_unfinished"


def classify_sync_result(
    run: ScrapeRun, *, failure: str | None = None, names: Mapping[str, str] | None = None
) -> ClassifiedNotif | None:
    """Terminal notification for a run, or None when the run was clean.

    A clean run returns None: "the thing that is supposed to happen happened"
    is an ambient fact, not an interrupt: nothing to act on, and a bell badge
    every time. Run history stays fully readable on the ops/status surface, which is
    where an always-true signal belongs. So is a run whose only imperfection is
    one that recurs on every run (`_Unfinished.quiet`).

    `names` maps a company slug to the name the user knows it by (the store
    reads `tracked_company.display`, the name Coverage copy uses); a company
    it does not name falls back to `_company_label`.
    """
    run_sources = _read_sources(run)
    told = run_sources.told
    # Drift on a source the run reads as fine (`ok`, `lossy`, an empty board)
    # or a board Coverage tells is a note in the run log, never news: a
    # connector's failover or a retried transient answer on an `ok` run is
    # nothing the person can act on.
    quiet = told | run_sources.settled
    problem_drift = [row for row in _drift_rows(run) if _drift_company(row["source"]) not in quiet]
    drift_count = len(problem_drift)
    unfinished = run_sources.unfinished
    source_errors = run_sources.named_errors
    error_sources = list(source_errors)
    # `failure` is the pipeline exception, or None. It is its own signal because
    # the status is a projection of the SOURCES: a derivation that
    # fails over healthy sources leaves the run `ok`, and without this the feed
    # would say nothing at all about a pass that did not run.
    ours = run_sources.ours
    # `ok` is the projection of every source's outcome, so an `ok`
    # run has no problem source by definition, whatever older stats omit.
    problems = [source for source in run_sources.imperfect() if source not in ours] if run.status != "ok" else []
    has_errors = bool(problems) or bool(error_sources) or bool(failure)
    has_success = any(
        isinstance(stats, dict) and not stats.get("errors") and int(stats.get("scanned") or 0) > 0
        for stats in (run.per_source or {}).values()
    )
    suspended = run_sources.suspended
    label = company_namer(names)
    skipped, updated = _source_totals(run)
    finished_at = _fmt_time(run.finished_at or datetime.now(UTC))
    unfinished_say = _unfinished_say(unfinished, label)
    summary_say = (
        S.say("notif-scan-summary-skipped", found=run.jobs_seen, created=run.jobs_new, updated=updated, skipped=skipped)
        if skipped
        else S.say("notif-scan-summary", found=run.jobs_seen, created=run.jobs_new, updated=updated)
    )
    finished_say = S.say("notif-finished-at", at=finished_at, duration=S.duration(_duration_seconds(run)))
    meta = {
        "sync_state": "success",
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": _duration_seconds(run),
        "jobs_found": run.jobs_seen,
        "jobs_created": run.jobs_new,
        "jobs_updated": updated,
        "jobs_skipped_or_unchanged": skipped,
        "jobs_closed": run.jobs_closed,
        "error_sources": error_sources,
        "source_errors": source_errors,
        "suspended_sources": suspended,
        "unreached_sources": unfinished.unreached,
        "offline_sources": unfinished.offline,
        "cut_short_sources": unfinished.cut_short,
        "drift_alerts": run.drift_alerts or [],
    }
    if has_errors or drift_count:
        meta["diagnostics"] = run_diagnostics(run)

    # The person pressed Stop scan (`POST /api/sync/cancel`). Their own act is
    # never a failure: the record keeps `error` when nothing was saved
    # (`cancelled_run_status`, an audit fact), so the failure branch must not
    # read it. Filed with the scans that did not finish for a reason
    # of ours, at low priority; a real problem at a company it did read is
    # still named, as a warning, never as a failed scan.
    if run.notes == STOPPED_BY_USER_NOTE:
        read = [
            source for source, outcome in run_sources.outcome.items() if outcome is not SourceOutcome.UNATTEMPTED
        ]
        meta["stopped_by_user"] = True
        if not read:
            body_say: list = [S.say("notif-stopped-before-any")]
        else:
            pass
            body_say = [S.say("notif-stopped-after", companies=S.companies(len(read)))]
        troubled = has_errors or bool(drift_count)
        if troubled:
            at_fault = [*error_sources, *(source for source in problems if source not in error_sources)]
            body_say.append(S.say("notif-problems-at", affected=S.affected(affected_slugs(at_fault, problem_drift), label)))
        if read and run.status != "error":
            # `partial` is `cancelled_run_status` finding a usable read saved.
            body_say.append(S.say("notif-read-saved"))
        if unfinished.named:
            body_say.extend(unfinished_say)
        if read:
            body_say.append(summary_say)
        meta["sync_state"] = "warning" if troubled else "partial"
        meta["say"] = _said(S.say("notif-scan-stopped"), *body_say)
        return ClassifiedNotif(
            priority="normal" if troubled else "low",
            category="sync_warning" if troubled else SYNC_UNFINISHED,
            meta=meta,
        )

    # Nothing went wrong at any company: every one less than clean stopped for
    # a reason that was OURS. Checked first, because a run whose
    # deadline came before every company is `error` without a single failure.
    # What recurs on every run says nothing; what this run left undone is
    # named at low priority with what happens next, never as "problems".
    if not error_sources and not drift_count and not failure and not suspended and run_sources.only_ours():
        if not unfinished.named:
            return None
        meta["sync_state"] = "partial"
        meta["say"] = _said(_unfinished_title_say(unfinished), finished_say, *unfinished_say, summary_say)
        return ClassifiedNotif(
            priority="low",
            category=SYNC_UNFINISHED,
            meta=meta,
        )

    # `error` is a total judgement ("no source produced usable data"), so it
    # alone decides the failure banner. `partial` is a warning, never a
    # failure: a run where most sources delivered did refresh the data, and
    # raising "Sync failed" for it trains the user to ignore the banner.
    # `has_success` stays in the condition as a guard for older rows whose
    # status is not a projection of the sources.
    # Every source a board Coverage tells (or a read that was ours): nothing
    # for the run to say. A run with no source at all (cancelled, or dead
    # before collecting) still fails out loud.
    sources = set(run.per_source or {})
    told_only = bool(sources) and sources <= told | ours
    if run.status == "error" and not has_success and not told_only:
        meta["sync_state"] = "failed"
        # Named by company; the run's notes only when no company is at fault.
        named = error_sources or problems
        detail_say: S.Say | str
        if source_errors:
            detail = "; ".join(
                f"{label(source)}: {errors[0]}" for source, errors in source_errors.items() if errors
            )
            detail_say = detail  # each company's own error text, as the run recorded it
        elif named:
            detail = _source_summary([label(source) for source in named])
            detail_say = S.sources([label(source) for source in named])
        else:
            detail = run.notes or "run failed"
            detail_say = run.notes or S.say("notif-run-failed")
        meta["say"] = _said(
            S.say("notif-scan-failed"),
            S.say("notif-failed-at", at=finished_at, duration=S.duration(_duration_seconds(run))),
            S.say("notif-problems-at", affected=detail_say),
            *(unfinished_say if unfinished.named else []),
            summary_say,
        )
        return ClassifiedNotif(
            priority="high",
            category="sync_failed",
            meta=meta,
        )

    # A derivation blew up while the collection itself was fine. Its own branch,
    # because the sources are NOT the answer here: `error_sources` is empty,
    # and an empty list must never read as "every source" while the per-source
    # table says each one was `ok`. The scraped data is good and already
    # written; what is missing is a derived artifact, which `stale_derivations`
    # also reports on the status surface.
    if failure and not error_sources and not drift_count:
        meta["sync_state"] = "warning"
        meta["failure"] = failure
        delivered_say = (
            [S.say("notif-post-pass-unfinished", failure=failure), *unfinished_say]
            if unfinished.named
            else [S.say("notif-every-source-delivered", failure=failure)]
        )
        meta["say"] = _said(
            S.say("notif-scan-derivation-failed"), finished_say, *delivered_say, S.say("notif-data-saved"), summary_say
        )
        return ClassifiedNotif(
            priority="normal",
            category="sync_warning",
            meta=meta,
        )

    if has_errors or drift_count:
        meta["sync_state"] = "warning"
        at_fault = [*error_sources, *(source for source in problems if source not in error_sources)]
        if failure:
            meta["failure"] = failure
        # Name the cause when it was ours. A host suspension ends a source's
        # listing by killing its sockets, so without this the body blames the
        # source for a transport error it never caused, which reads as a bug in
        # the adapter. The sources are still named: the listing
        # really is incomplete and closure really was suppressed for them.
        meta["say"] = _said(
            S.say("notif-scan-problems"),
            finished_say,
            *([S.say("notif-asleep", duration=S.duration(max(suspended.values())))] if suspended else []),
            S.say("notif-problems-at", affected=S.affected(affected_slugs(at_fault, problem_drift), label)),
            *(unfinished_say if unfinished.named else []),
            summary_say,
        )
        return ClassifiedNotif(
            priority="normal",
            category="sync_warning",
            meta=meta,
        )

    return None
