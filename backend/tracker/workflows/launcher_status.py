"""Presentation facts shared by desktop launchers and the web shell."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, get_args

Activity = Literal["idle", "scanning", "updating"]
HoldKind = Literal["attention", "waiting"]
ModelState = Literal["ready", "preparing", "missing", "unused"]


class Hold(TypedDict):
    kind: HoldKind
    reason: str


class Presentation(TypedDict):
    observed_at: datetime
    activity: Activity
    activity_since: datetime | None
    hold: Hold | None
    attention: list[Literal["coverage", "stuck_scan"]]
    queued: Literal["scan", "update"] | None
    coverage_at: datetime | None
    last_scan_at: datetime | None
    last_scan_outcome: str | None
    model: ModelState


_DERIVATIONS = frozenset({"reembed", "reestimate"})
_ATTENTION = frozenset({"schema_pending", "dependencies_pending", "build_failed", "preflight_failed"})
_WAITING = frozenset({"waiting_for_mains", "waiting_for_wake", "preflight_running", "busy_external"})


def _at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def project_status(
    facts: Mapping[str, Any], *, now: datetime, model: ModelState, reembed_executing: bool,
) -> Presentation:
    supervisor = facts["supervisor"]
    jobs = [job for job in facts["jobs"] if job["job"] in {"scan", *_DERIVATIONS}]
    # An old supervisor row cannot prove that one of its children still runs.
    active = [job for job in jobs if job["job"] in _DERIVATIONS
              and job["state"] in {"starting", "running"} and supervisor["state"] == "running"]
    activity: Activity = "scanning" if facts["running"] else "updating" if active or reembed_executing else "idle"
    since = _at(facts.get("last_run_started_at")) if activity == "scanning" else (
        min((stamp for job in active if (stamp := _at(job.get("since"))) is not None), default=None)
        if activity == "updating" else None
    )
    # Only a job the scheduler holds back now carries a live blocker. An idle job repeats
    # its last run's reason, and an on-request derivation can sit idle for days.
    waiting = [job for job in jobs if job["state"] == "waiting"]
    hold: Hold | None = None
    if supervisor["state"] in {"absent", "stale"}:
        hold = {"kind": "attention", "reason": f"supervisor_{supervisor['state']}"}
    elif supervisor.get("reason") in _ATTENTION:
        hold = {"kind": "attention", "reason": supervisor["reason"]}
    else:
        reason = next((job["reason"] for job in waiting if job.get("reason") in _ATTENTION), None)
        if reason:
            hold = {"kind": "attention", "reason": reason}
    if hold is None and model == "missing":
        hold = {"kind": "attention", "reason": "model_missing"}
    if hold is None:
        if supervisor["state"] == "maintenance":
            hold = {"kind": "waiting", "reason": "maintenance"}
        elif model == "preparing":
            hold = {"kind": "waiting", "reason": "model_preparing"}
        else:
            reason = next((job["reason"] for job in waiting if job.get("reason") in _WAITING), None)
            if reason:
                hold = {"kind": "waiting", "reason": reason}
    # Rows count as pending only against a target fingerprint; without one there is nothing to apply.
    reference = facts.get("reference", {})
    pending_estimates = reference.get("target_fp") is not None and reference.get("pending_jobs", 0) > 0
    queued: Literal["scan", "update"] | None = None
    if facts.get("manual_queued"):
        queued = "scan"
        # A running scan reads every other company while one provider cools down: the
        # cooldown is not what the scan is doing, so it does not become the headline.
        if hold is None and activity == "idle" and facts.get("manual_blocked"):
            hold = {"kind": "waiting", "reason": "provider_" + facts["manual_blocked"][0]["reason"]}
    elif pending_estimates or any(
        job.get("queued", 0) > 0 or job["state"] == "queued" for job in jobs if job["job"] in _DERIVATIONS
    ):
        queued = "update"
        if hold is None and activity == "idle":
            hold = {"kind": "waiting", "reason": "update_queued"}
    attention: list[Literal["coverage", "stuck_scan"]] = []
    if facts.get("coverage_attention"):
        attention.append("coverage")
    if facts["stuck_running"] > 0:
        attention.append("stuck_scan")
    return {
        "observed_at": now, "activity": activity, "activity_since": since,
        "hold": hold, "attention": attention, "queued": queued,
        "coverage_at": _at(facts.get("last_success_at")),
        "last_scan_at": _at(facts.get("last_scan_at")),
        "last_scan_outcome": facts.get("last_scan_outcome"), "model": model,
    }


#: The menu-bar panel draws this many companies in flight; the scan reads a few at a time.
IN_FLIGHT_SHOWN = 5


class ScanCompany(TypedDict):
    name: str
    since: datetime


#: How scans start on their own: ``plan`` reads everyone on the schedule plan's clock,
#: ``timers`` keeps each company's own deadline, ``off`` starts none.
Scheduling = Literal["plan", "timers", "off"]

#: Where a live scan is: reading companies, adding the roles it read, or the passes after it.
ScanStage = Literal["collecting", "persisting", "finishing"]
_STAGES = frozenset(get_args(ScanStage))


class ScanSchedule(TypedDict):
    scheduling: Scheduling
    paused_until: datetime | None
    next_scan_at: datetime | None


class Scan(TypedDict):
    phase: ScanStage | None
    percent: int | None
    companies_total: int | None
    in_flight: list[ScanCompany]
    roles_pending: int | None
    roles_recorded: int | None
    last_companies: int | None
    last_new_roles: int | None
    last_postings: int | None
    last_stopped: bool
    next_scan_at: datetime | None
    scheduling: Scheduling
    paused_until: datetime | None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def in_flight_slugs(progress: Any) -> list[str]:
    """The companies a live scan is reading, longest first. ``progress`` is the run's
    ``sync_started`` notification ``meta.progress``: untyped JSONB, read defensively."""
    companies = progress.get("companies") if isinstance(progress, Mapping) else None
    rows = [row for row in companies if isinstance(row, Mapping)] if isinstance(companies, list) else []
    reading = [row for row in rows if row.get("state") == "scraping" and isinstance(row.get("slug"), str)
               and _count(row.get("since_ms")) is not None]
    reading.sort(key=lambda row: row["since_ms"])
    return [row["slug"] for row in reading[:IN_FLIGHT_SHOWN]]


def project_scan(
    *, progress: Any, names: Mapping[str, str], last_finished: Mapping[str, Any] | None,
    stopped_note: str, schedule: ScanSchedule, now: datetime,
) -> Scan:
    """The scan picture: a live scan's progress while one runs, the last finished scan, and
    when the next one starts.

    ``progress`` is present only while the run is executing; its company clocks are server
    epochs in milliseconds. ``last_finished`` carries that run's ``companies`` (how many it
    read), ``new_roles`` (its roles the New board lists), ``jobs_seen`` and ``notes``. A next
    scan already due reads ``now``: the schedule may have been read a little earlier than
    this projection.
    """
    live = progress if isinstance(progress, Mapping) else None
    rows = (live or {}).get("companies")
    since = {row["slug"]: row["since_ms"] for row in (rows if isinstance(rows, list) else [])
             if isinstance(row, Mapping) and isinstance(row.get("slug"), str)}
    in_flight: list[ScanCompany] = [
        {"name": names.get(slug) or slug, "since": datetime.fromtimestamp(since[slug] / 1000, UTC)}
        for slug in in_flight_slugs(live)
    ]
    percent = _count(live.get("percent")) if live else None
    phase = live.get("phase") if live else None
    return {
        "phase": phase if phase in _STAGES else None,
        "percent": min(percent, 100) if percent is not None else None,
        "companies_total": _count(live.get("companies_total")) if live else None,
        "in_flight": in_flight,
        "roles_pending": _count(live.get("opportunities_pending")) if live else None,
        "roles_recorded": _count(live.get("opportunities_recorded")) if live else None,
        "last_companies": _count(last_finished.get("companies")) if last_finished else None,
        "last_new_roles": _count(last_finished.get("new_roles")) if last_finished else None,
        "last_postings": _count(last_finished.get("jobs_seen")) if last_finished else None,
        "last_stopped": last_finished is not None and last_finished.get("notes") == stopped_note,
        "next_scan_at": max(next_at, now) if (next_at := schedule["next_scan_at"]) is not None else None,
        "scheduling": schedule["scheduling"],
        "paused_until": schedule["paused_until"],
    }
