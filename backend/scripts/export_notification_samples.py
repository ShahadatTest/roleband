"""Write one notification per wording branch, for the dashboard's contract test.

Each sample is a classifier's real output for a representative input: its
stored English `title` and `body`, and its `meta.say`
(`tracker/notifications/say.py`). The dashboard renders every `say` from its
catalog and must produce exactly the stored English
(`dashboard/src/api/notificationText.test.ts`), so a
sentence reworded on one side and not the other fails there.
`tests/test_notification_say.py` fails when the committed file is stale and
when a key the classifiers can send has no sample.

The reader's zone is pinned to UTC and every count stays under 1,000, so the
English the server wrote and the client's formatting agree byte for byte.

    .venv/bin/python -m scripts.export_notification_samples [--check]
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tracker.connectors.recipes.outcome import (
    STOPPED_BY_USER_NOTE,
    SourceOutcome,
    classify_source_outcome,
    run_status_for,
)
from tracker.notifications import coverage
from tracker.notifications.coverage import classify_coverage, classify_coverage_outage
from tracker.notifications.digest import DigestMatch, classify_daily_digest
from tracker.notifications.events import ClassifiedNotif, classify_event
from tracker.notifications.pursuit_due import classify_pursuit_due, classify_pursuit_quiet
from tracker.notifications.run_result import classify_sync_result, classify_sync_started
from tracker.workflows.collection_types import empty_stats

COMMITTED = (
    Path(__file__).resolve().parents[2] / "dashboard" / "src" / "api" / "notification-samples.json"
)

START = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
#: The register's names, as `tracked_company.display` holds them.
NAMES = {"openai": "OpenAI", "google-deepmind": "Google DeepMind", "stripe": "Stripe", "meta": "Meta"}


@dataclass
class _Job:
    company: str = "openai"
    title: str = "Research Manager, Interpretability"
    total_days_open: int = 3


@dataclass
class _Run:
    """The fields of a `ScrapeRun` the classifiers read. A plain object, not the
    model: the samples are built in memory and never stored."""

    started_at: datetime | None = START
    finished_at: datetime | None = None
    status: str = "ok"
    jobs_seen: int = 120
    jobs_new: int = 4
    jobs_closed: int = 0
    per_source: dict = field(default_factory=dict)
    drift_alerts: list = field(default_factory=list)
    notes: str | None = None
    id: int = 1968


def _recorded(stats: dict, *, list_complete: bool = False) -> dict:
    """A per-source record as `run_persistence` stores it, outcome derived."""
    record = {**stats, "list_complete": list_complete}
    record["outcome"] = classify_source_outcome(record).value
    return record


OK = _recorded({**empty_stats(), "scanned": 300, "kept": 40, "new": 4}, list_complete=True)
SKIPPING = _recorded({**empty_stats(), "scanned": 300, "kept": 40, "new": 4, "unchanged": 31}, list_complete=True)
UNREACHED = _recorded({
    **empty_stats(), "unattempted": True, "errors": ["TimeoutError: collection timed out"],
    "deferred_reason": "run deadline reached before this company started",
})
BOUNDED = _recorded({**empty_stats(), "scanned": 300, "kept": 40, "bounded": True})
OFFLINE = _recorded(
    {**empty_stats(), "scanned": 12, "offline": True, "errors": ["ConnectError: [Errno 8] nodename nor servname provided"]}
)
BROKEN = _recorded({**empty_stats(), "errors": ["HTTPError: 500"]})
DEGRADED = _recorded({**empty_stats(), "scanned": 400, "kept": 2, "listing_invalidated": True})
#: A board that answered nothing usable and recorded no error text.
DOWN = _recorded({**empty_stats(), "listing_invalidated": True})


def _run(per_source: dict, *, minutes: float = 40, status: str | None = None, **over) -> Any:
    """A finished run whose status is the projection of its sources."""
    fields = {
        "status": status or run_status_for(SourceOutcome(s["outcome"]) for s in per_source.values()),
        "finished_at": START + timedelta(minutes=minutes),
        "per_source": per_source,
    }
    return _Run(**{**fields, **over})


def _coverage(**over) -> dict:
    item = {
        "company": "stripe", "display": "Stripe", "automatic": True, "stale": True,
        "cause": "unreachable", "days_since_full_scan": 4.4,
        "last_full_scan_at": datetime(2026, 9, 28, 12, 0, tzinfo=UTC), "held_open": 3,
        "empty_since": None, "days_empty": None, "cause_message": "ReadError: ",
    }
    return {**item, **over}


def _band(low: int | None, high: int | None) -> dict:
    return {"min": low, "max": high}


def _started() -> Any:
    return _Run(started_at=START)


def cases() -> Iterator[tuple[str, ClassifiedNotif | None]]:
    """Every wording branch the classifiers have, by name."""
    job = _Job()
    elsewhere = [(901, "London"), (902, "New York"), (903, "Zurich"), (904, "Paris"), (905, "Tokyo")]
    yield "role-still-listed-in-another-place", classify_event(
        "closed", {}, job, True, listed_elsewhere=elsewhere[:1], names=NAMES
    )
    yield "role-still-listed-in-five-places", classify_event(
        "closed", {}, job, True, listed_elsewhere=elsewhere, names=NAMES
    )
    yield "role-closed", classify_event("closed", {}, job, True, names=NAMES)
    yield "role-reposted", classify_event("reopened", {}, job, True, names=NAMES)
    yield "role-listed-again", classify_event("opened", {}, job, True, lineage_role="duplicate", names=NAMES)
    yield "role-listed", classify_event("opened", {}, job, True, names=NAMES)
    yield "pay-raised", classify_event(
        "changed",
        {"disclosed_base": {"from": _band(200_000, 240_000), "to": _band(300_000, 1_250_000)}},
        job, True, names=NAMES,
    )
    yield "pay-lowered-floor-only", classify_event(
        "changed", {"disclosed_base": {"from": _band(250_000, None), "to": _band(200_000, None)}}, job, True, names=NAMES
    )
    yield "updated-long-open", classify_event(
        "changed", {"title": {}}, _Job(total_days_open=90), True, long_open_days=60, names=NAMES
    )
    yield "changed", classify_event("changed", {"title": {}}, job, True, long_open_days=60, names=NAMES)

    yield "digest-one-unranked", classify_daily_digest("2026-09-28", [DigestMatch(1, "stripe", "Head of Product")], names=NAMES)
    for fit, band in ((0.71, "strong"), (0.55, "good"), (0.45, "fair"), (0.30, "weak")):
        yield f"digest-{band}-lead", classify_daily_digest(
            "2026-09-28",
            [DigestMatch(1, "google-deepmind", "Group Product Manager", fit), DigestMatch(2, "meta", "Director", 0.2),
             DigestMatch(3, "stripe", "Lead", None)],
            names=NAMES,
        )

    yield "follow-up-due-today", classify_pursuit_due("stripe", "Head of Product", "applied", None, 0, names=NAMES)
    yield "follow-up-overdue", classify_pursuit_due(
        "openai", "Research Manager", "interviewing", "Send the take-home", 4, names=NAMES
    )
    yield "pursuit-gone-quiet", classify_pursuit_quiet("stripe", "Head of Product", "applied", 23, names=NAMES)

    yield "coverage-unreachable", classify_coverage(_coverage())
    yield "coverage-unreadable-one-day", classify_coverage(_coverage(cause="unreadable", days_since_full_scan=1.2))
    yield "coverage-partial-under-a-day", classify_coverage(_coverage(cause="partial", days_since_full_scan=0.4))
    yield "coverage-never-scanned", classify_coverage(_coverage(cause="unknown", last_full_scan_at=None))
    yield "coverage-waiting-outage", classify_coverage_outage([
        _coverage(company=f"company-{i}", cause="unknown", last_full_scan_at=None)
        for i in range(5)
    ])
    yield "coverage-empty-holding-one", classify_coverage(_coverage(cause="empty_listing", held_open=1, days_empty=2.2))
    yield "coverage-empty-holding-several", classify_coverage(
        _coverage(cause="empty_listing", held_open=4, days_empty=1.0)
    )
    yield "coverage-empty-holding-none", classify_coverage(_coverage(cause="empty_listing", held_open=0, days_empty=0.3))
    yield "coverage-board-gone", classify_coverage(_coverage(cause="board_missing", days_since_full_scan=5.0))
    yield "coverage-board-gone-holding-one", classify_coverage(
        _coverage(cause="board_missing", held_open=1, days_since_full_scan=1.0)
    )
    yield "coverage-board-gone-holding-none", classify_coverage(
        _coverage(cause="board_missing", held_open=0, days_since_full_scan=0.5)
    )
    stale = [_coverage(company=c, display=c.title(), days_since_full_scan=d,
                       last_full_scan_at=datetime(2026, 9, 28, 12, tzinfo=UTC) - timedelta(days=d))
             for c, d in (("stripe", 3.0), ("meta", 2.5), ("openai", 2.1))]
    yield "coverage-outage", classify_coverage_outage(stale)
    yield "coverage-outage-never-scanned", classify_coverage_outage(
        [{**item, "last_full_scan_at": None, "days_since_full_scan": None} for item in stale]
    )

    started_names = {"apple": "Apple", "google": "Google", "meta": "Meta", "stripe": "Stripe",
                     "openai": "OpenAI", "anthropic": "Anthropic"}
    yield "scan-started-one", classify_sync_started(_started(), ["stripe"], names=started_names)
    yield "scan-started-named", classify_sync_started(_started(), ["google", "meta", "stripe"], names=started_names)
    yield "scan-started-many", classify_sync_started(
        _started(), ["apple", "google", "meta", "stripe", "openai", "anthropic"], names=started_names
    )
    yield "scan-started-all", classify_sync_started(_started(), [])

    stopped = {"notes": STOPPED_BY_USER_NOTE}
    yield "stopped-before-any", classify_sync_result(_run({}, status="error", **stopped), names=NAMES)
    yield "stopped-with-a-problem", classify_sync_result(
        _run({"stripe": OK, "google-deepmind": BROKEN, "meta": UNREACHED}, status="partial", **stopped), names=NAMES
    )
    yield "stopped-clean", classify_sync_result(_run({"stripe": OK}, status="partial", **stopped), names=NAMES)
    yield "stopped-at-a-failed-pass", classify_sync_result(
        _run({"stripe": SKIPPING}, status="partial", **stopped), failure="RuntimeError: embed", names=NAMES
    )

    groups = {"u": {"meta": UNREACHED}, "o": {"openai": OFFLINE}, "c": {"google-deepmind": BOUNDED}}
    for combo in ("u", "o", "c", "uo", "uc", "oc", "uoc"):
        per_source = {"stripe": OK}
        for tag in combo:
            per_source.update(groups[tag])
        yield f"unfinished-{combo}", classify_sync_result(_run(per_source, minutes=0.75), names=NAMES)
    yield "unfinished-several-each", classify_sync_result(
        _run({"stripe": OK, "meta": UNREACHED, "openai": UNREACHED, "anthropic": OFFLINE, "apple": OFFLINE}, minutes=95),
        names=NAMES,
    )
    yield "unfinished-past-four", classify_sync_result(
        _run({"stripe": OK, **{c: UNREACHED for c in ("a1", "b2", "c3", "d4", "e5", "f6")}}), names=NAMES
    )

    yield "failed-with-errors", classify_sync_result(_run({"google-deepmind": BROKEN}, minutes=0.2), names=NAMES)
    yield "failed-named", classify_sync_result(
        _run({"google-deepmind": DOWN, "stripe": DOWN}, jobs_seen=0, jobs_new=0), names=NAMES
    )
    yield "failed-with-notes", classify_sync_result(
        _run({}, status="error", notes="database is locked", started_at=None), names=NAMES
    )
    yield "failed-unexplained", classify_sync_result(_run({}, status="error"), names=NAMES)

    yield "derivation-failed", classify_sync_result(_run({"stripe": SKIPPING}), failure="RuntimeError: embed", names=NAMES)
    yield "derivation-failed-and-unfinished", classify_sync_result(
        _run({"stripe": OK, "meta": UNREACHED}), failure="RuntimeError: embed", names=NAMES
    )

    asleep = _recorded({**empty_stats(), "scanned": 920, "kept": 42, "errors": ["ReadError (no detail)"],
                        "suspended": True, "suspended_seconds": 987.0})
    yield "problems-while-asleep", classify_sync_result(
        _run({"microsoft": asleep, "stripe": OK}, minutes=125), names=NAMES
    )
    yield "problems-and-unfinished", classify_sync_result(
        _run({"google-deepmind": DEGRADED, "stripe": OK, "meta": UNREACHED}), names=NAMES
    )
    yield "problems-from-drift", classify_sync_result(
        _run({"stripe": DEGRADED, "openai": OK},
             drift_alerts=[{"source": "greenhouse:stripe", "message": "selector changed"}]),
        names=NAMES,
    )


@contextmanager
def _reader_in_utc() -> Iterator[None]:
    """The day a coverage notice prints is the reader's; the samples pin UTC."""
    zone = coverage._local_zone
    coverage._local_zone = lambda: UTC
    try:
        yield
    finally:
        coverage._local_zone = zone


def samples() -> list[dict]:
    out = []
    with _reader_in_utc():
        for case, notif in cases():
            if notif is None:
                raise ValueError(f"sample {case} classified to nothing")
            out.append({"case": case, "title": notif.title, "body": notif.body, "say": notif.meta["say"]})
    return out


def render() -> str:
    """The exact bytes the committed file must contain."""
    return json.dumps(samples(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    text = render()
    if "--check" in sys.argv:
        if not COMMITTED.exists() or COMMITTED.read_text() != text:
            print(f"stale: {COMMITTED}; run .venv/bin/python -m scripts.export_notification_samples")
            raise SystemExit(1)
        print(f"up to date: {COMMITTED}")
        return
    COMMITTED.write_text(text)
    print(f"{len(json.loads(text))} samples -> {COMMITTED}")


if __name__ == "__main__":
    main()
