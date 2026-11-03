"""What a finished run did, in one vocabulary: the structured result.

`kind`: ran | nothing_due | waiting | busy | refused | failed. This says what the
PROCESS did with its turn, never how a collection went: that stays the domain
record's (`scrape_runs.status`, `plugin_run.outcome`), which `links` points to.

Pure: each job's adapter reads the job's own return value (the raw result an
entry writes) or, for a command, its exit code. A ten-minute tick that found
nothing due is `nothing_due`, not a success that crowds the run history.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tracker.platform.power import WAITING_FOR_FULL_WAKE, WAITING_FOR_MAINS

RAN = "ran"
NOTHING_DUE = "nothing_due"
WAITING = "waiting"
BUSY = "busy"
REFUSED = "refused"
FAILED = "failed"

_POWER_WAITS = {WAITING_FOR_FULL_WAKE: "waiting_for_wake", WAITING_FOR_MAINS: "waiting_for_mains"}


def _result(kind: str, reason: str | None = None, **links: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind}
    if reason is not None:
        out["reason"] = reason
    linked = {name: value for name, value in links.items() if value is not None}
    if linked:
        out["links"] = linked
    return out


def _scan(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """The scheduler tick's own result: `ran`, a `reason` when it did not, and
    the pipeline's `summary` (with its `run_id`) when it did."""
    if exit_code != 0 or not isinstance(raw, Mapping):
        return _result(FAILED)
    if raw.get("ran"):
        summary = raw.get("summary") or {}
        return _result(RAN, scrape_run=summary.get("run_id"))
    reason = str(raw.get("reason") or "")
    if reason == "run in progress":
        return _result(BUSY, "busy_external")
    if reason in _POWER_WAITS:
        return _result(WAITING, _POWER_WAITS[reason])
    summary = raw.get("summary") or {}
    if summary.get("status") == "skipped":
        # The pipeline found its own advisory lock held by another process.
        return _result(BUSY, "busy_external")
    return _result(NOTHING_DUE)


def _directory(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """The sweep's passes, in order; the last says why the run stopped."""
    if exit_code != 0 or not isinstance(raw, list) or not raw:
        return _result(FAILED)
    passes = [step for step in raw if isinstance(step, Mapping)]
    checked = sum(int(step.get("checked") or 0) for step in passes if step.get("ran"))
    if any(step.get("ran") for step in passes):
        return _result(RAN, checked=checked)
    reason = str(passes[-1].get("reason") or "")
    if reason == "a pass is already running":
        return _result(BUSY, "busy_external")
    if reason in _POWER_WAITS:
        return _result(WAITING, _POWER_WAITS[reason])
    if reason == "a scan goes first":
        return _result(WAITING, "yielding_to_sync")
    return _result(NOTHING_DUE)


def _plugins_due(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """`plugins_when_due`: the jobs it asked for, or why it asked for none."""
    if exit_code != 0 or not isinstance(raw, Mapping):
        return _result(FAILED)
    if raw.get("started"):
        return _result(RAN)
    waiting = str(raw.get("waiting") or "")
    if waiting in _POWER_WAITS:
        return _result(WAITING, _POWER_WAITS[waiting])
    return _result(NOTHING_DUE)


def _usage_send(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """`flush_if_due`: how many events went, or why none did."""
    if exit_code != 0 or not isinstance(raw, Mapping):
        return _result(FAILED)
    if raw.get("sent"):
        return _result(RAN)
    reason = str(raw.get("reason") or "")
    if reason in _POWER_WAITS:
        return _result(WAITING, _POWER_WAITS[reason])
    if raw.get("outcome") not in (None, "sent"):
        # Built and posted, and the endpoint did not take it.
        return _result(FAILED, "not_delivered")
    return _result(NOTHING_DUE)


def _role_discovery(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """`discover`: "ok" read every company, "yielded" stopped early for a scan,
    "deferred" found the pipeline lock held and read nothing."""
    if exit_code != 0 or not isinstance(raw, Mapping):
        return _result(FAILED)
    status = raw.get("status")
    companies = raw.get("companies")
    count = len(companies) if isinstance(companies, Mapping) else 0
    if status == "deferred":
        return _result(BUSY, "busy")
    if status in ("ok", "yielded"):
        return _result(RAN, companies=count)
    return _result(FAILED)


def _reembed(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """`backfill.run`'s counts, or the turn another embedder held."""
    if exit_code != 0 or not isinstance(raw, Mapping):
        return _result(FAILED)
    if raw.get("ran") is False:
        return _result(BUSY, "busy_external")
    return _result(RAN, embedded=raw.get("embedded"))


def _prices(exit_code: int | None, raw: Any) -> dict[str, Any]:
    """`run_refresh`'s summary. `next_at` travels with the result: it is the
    job's own deadline (`AtDeadline`), read back from its last run."""
    if exit_code != 0 or not isinstance(raw, Mapping):
        return _result(FAILED)
    skipped = raw.get("skipped")
    if skipped == "no_key":
        return _result(NOTHING_DUE, "no_key")
    if skipped == "busy":
        return _result(BUSY, "busy_external")
    refused = raw.get("refused")
    if refused == "unauthorized":
        out = _result(REFUSED, "key_refused")
    elif refused == "rate_limited":
        out = _result(WAITING, "rate_limited")
    elif raw.get("priced") or raw.get("failed"):
        out = _result(RAN)
    else:
        out = _result(NOTHING_DUE)
    for field in ("next_at", "deferred"):
        if raw.get(field):
            out[field] = raw[field]
    return out


#: `tracker.plugins.reestimate_cli` exits 3 (its `LOCKED`) when another process
#: holds the reference lock.
REESTIMATE_LOCKED = 3
#: `deploy/preflight.sh`.
PREFLIGHT_REFUSED = 75
PREFLIGHT_TREE_MOVED = 76
PREFLIGHT_BUSY = 77


def _reestimate(exit_code: int | None, _raw: Any) -> dict[str, Any]:
    if exit_code == 0:
        return _result(RAN)
    if exit_code == REESTIMATE_LOCKED:
        return _result(BUSY, "busy_external")
    return _result(FAILED)


def _preflight(exit_code: int | None, _raw: Any) -> dict[str, Any]:
    if exit_code == 0:
        return _result(RAN)
    if exit_code == PREFLIGHT_REFUSED:
        return _result(REFUSED, "preflight_failed")
    if exit_code == PREFLIGHT_TREE_MOVED:
        return _result(REFUSED, "tree_moved")
    if exit_code == PREFLIGHT_BUSY:
        return _result(BUSY, "busy_external")
    return _result(FAILED)


def _by_exit_code(exit_code: int | None, _raw: Any) -> dict[str, Any]:
    return _result(RAN if exit_code == 0 else FAILED)


ADAPTERS: dict[str, Callable[[int | None, Any], dict[str, Any]]] = {
    "scan": _scan,
    "directory": _directory,
    "plugins_due": _plugins_due,
    "usage_send": _usage_send,
    "role_discovery": _role_discovery,
    "reembed": _reembed,
    "prices": _prices,
    "reestimate": _reestimate,
    "preflight": _preflight,
}


def summarize(job: str, exit_code: int | None, raw: Any) -> dict[str, Any]:
    if exit_code == 0 and isinstance(raw, Mapping) and raw.get("dry_run"):
        return _result(NOTHING_DUE, "dry_run")
    return ADAPTERS.get(job, _by_exit_code)(exit_code, raw)
