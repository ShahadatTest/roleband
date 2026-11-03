"""What the dashboard reads about plugins and the reference set.

One projection for two surfaces: `GET /api/plugins` (the Plugins tab) and
`/api/status` (`capabilities`, `reference`, `plugins_running`), so the tab and
the header can never disagree about what is active or still moving.

- **state** of an install: `removed`, `needs_approval` (never approved, or its
  code, manifest or lock changed since), `enabled` or `disabled`.
- **active slots**: the slots the registry reads the plugin's rows for now
  (enabled, approved as it is, and a clean run published them).
- **reference**: the applied fingerprint, the target a re-estimate is moving
  to, the jobs it still has to reach, and the last `reference_change` with its
  moved report, whose id the dashboard watches to refetch.
- **reports**: the numbers a plugin asked the user to see (`ctx.report`), in
  key order, each with its own words and when it was reported.
- **capabilities**: per slot, who answers it app-wide: the plugin
  selected there, or the core's own data (`builtin`), never both.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import (
    Job,
    PluginCoverage,
    PluginInstall,
    PluginReport,
    PluginRun,
    ReferenceChange,
    ReferenceState,
    TrackedCompany,
)
from tracker.plugins import robots, schedule
from tracker.plugins.install import approval_text
from tracker.plugins.reestimate import pending_jobs
from tracker.plugins.registry import (
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    InstallRecord,
    load_providers,
    reader_providers,
)
from tracker.plugins.slots import BUILTIN_SLOTS, SLOTS, spec

#: How many recent runs a plugin's detail lists.
RECENT_RUNS = 10


def install_state(row: PluginInstall) -> str:
    return InstallRecord.of(row).state


def run_view(run: PluginRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "job": run.job,
        "trigger": run.trigger,
        "outcome": run.outcome,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "progress_done": run.progress_done,
        "progress_total": run.progress_total,
        "published": {str(k): int(v) for k, v in (run.published or {}).items()},
        "message": run.message,
        "summary": run.summary,
        "continues": bool(run.continues),
    }


def _change_view(change: ReferenceChange | None) -> dict[str, Any] | None:
    if change is None:
        return None
    report = change.moved_report or {}
    return {
        "id": change.id,
        "at": change.at,
        "jobs": int(report.get("jobs", 0)),
        "moved": int(report.get("moved", 0)),
        "gained": int(report.get("gained", 0)),
        "lost": int(report.get("lost", 0)),
        "companies": len(report.get("companies") or {}),
    }


async def reference_status(session: AsyncSession) -> dict[str, Any]:
    state = await session.get(ReferenceState, 1)
    change = await session.get(ReferenceChange, state.last_change_id) if state and state.last_change_id else None
    return {
        "applied_fp": state.applied_fp if state else None,
        "target_fp": state.target_fp if state else None,
        "pending_jobs": await pending_jobs(session),
        "last_change_id": state.last_change_id if state else None,
        "last_change": _change_view(change),
    }


async def reference_changes(session: AsyncSession, since: datetime | None) -> list[dict[str, Any]]:
    """Every reference switch since `since`, oldest first: the chart markers
    comp-trends draws, so a step in a pay series reads as a switch of sources,
    never as the market moving."""
    stmt = select(ReferenceChange).order_by(ReferenceChange.at)
    if since is not None:
        stmt = stmt.where(ReferenceChange.at >= since)
    views = (_change_view(c) for c in (await session.execute(stmt)).scalars())
    # A switch that moved no estimate (code that answers the same) is no step in
    # any series, so it draws no marker.
    return [v for v in views if v is not None and v["moved"] + v["gained"] + v["lost"] > 0]


async def status_block(session: AsyncSession) -> dict[str, Any]:
    """`/api/status`'s `capabilities`, `reference` and `plugins_running` in ONE
    statement while no plugin is installed (the provider set is then known
    without reading it), plus the registry's reads once one is."""
    state = select(ReferenceState).where(ReferenceState.id == 1).subquery()
    target = select(state.c.target_fp).scalar_subquery()
    applied = select(state.c.applied_fp).scalar_subquery()
    # `reestimate.pending_jobs` in SQL: past the cursor while a switch moves (no
    # job's shown copy moves before its last batch), else not under
    # the applied set.
    pending = case(
        (target.is_not(None), Job.id > func.coalesce(select(state.c.cursor_job_id).scalar_subquery(), 0)),
        else_=or_(applied.is_(None), Job.comp_ref_fp.is_distinct_from(applied)),
    )
    last_id = select(state.c.last_change_id).scalar_subquery()
    row = (
        await session.execute(
            select(
                applied.label("applied_fp"),
                target.label("target_fp"),
                last_id.label("last_change_id"),
                select(ReferenceChange.at).where(ReferenceChange.id == last_id).scalar_subquery().label("at"),
                select(ReferenceChange.moved_report).where(ReferenceChange.id == last_id)
                .scalar_subquery().label("report"),
                select(func.count()).select_from(Job).where(pending).scalar_subquery().label("pending"),
                select(func.count()).select_from(PluginRun).where(PluginRun.outcome == "running")
                .scalar_subquery().label("running"),
                select(func.count()).select_from(PluginInstall).scalar_subquery().label("installs"),
            )
        )
    ).one()
    change = None
    if row.last_change_id is not None and row.at is not None:
        report = row.report or {}
        change = {"id": row.last_change_id, "at": row.at, "jobs": int(report.get("jobs", 0)),
                  "moved": int(report.get("moved", 0)), "gained": int(report.get("gained", 0)),
                  "lost": int(report.get("lost", 0)), "companies": len(report.get("companies") or {})}
    caps = (
        await capabilities(session) if row.installs
        else [{"slot": slot, "providers": [], "builtin": slot in BUILTIN_SLOTS} for slot in SLOTS]
    )
    return {
        "capabilities": caps,
        "reference": {"applied_fp": row.applied_fp, "target_fp": row.target_fp, "pending_jobs": int(row.pending),
                      "last_change_id": row.last_change_id, "last_change": change},
        "plugins_running": int(row.running),
    }


async def capabilities(session: AsyncSession) -> list[dict[str, Any]]:
    providers = await load_providers(session)
    return [
        {"slot": slot, "providers": list(providers.active.get(slot, ())),
         "builtin": slot in BUILTIN_SLOTS and providers.source_for(slot) is None}
        for slot in SLOTS
    ]


async def plugins_running(session: AsyncSession) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(PluginRun).where(PluginRun.outcome == "running"))
        or 0
    )


async def _last_runs(session: AsyncSession) -> tuple[dict[str, PluginRun], dict[str, datetime]]:
    latest_ids = select(func.max(PluginRun.id)).group_by(PluginRun.plugin_id)
    latest = {r.plugin_id: r for r in (await session.execute(select(PluginRun).where(PluginRun.id.in_(latest_ids))))
              .scalars()}
    clean: dict[str, datetime] = {
        pid: started
        for pid, started in (await session.execute(
            select(PluginRun.plugin_id, func.max(PluginRun.started_at))
            .where(PluginRun.outcome == "clean").group_by(PluginRun.plugin_id)
        )).all()
    }
    return latest, clean


async def _run_records(session: AsyncSession) -> list[schedule.RunRecord]:
    rows = (await session.execute(select(PluginRun.plugin_id, PluginRun.job, PluginRun.outcome,
                                         PluginRun.started_at, PluginRun.ended_at, PluginRun.continues,
                                         PluginRun.progress_done, PluginRun.progress_total))).all()
    return [schedule.RunRecord(*row) for row in rows]


async def _coverage(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Per provider and slot, the companies whose rows are read: published
    whole at least once."""
    rows = (
        await session.execute(
            select(PluginCoverage.provider, PluginCoverage.slot, func.count())
            .where(PluginCoverage.rows > 0, PluginCoverage.complete_at.is_not(None))
            .group_by(PluginCoverage.provider, PluginCoverage.slot)
        )
    ).all()
    out: dict[str, dict[str, int]] = {}
    for provider, slot, companies in rows:
        out.setdefault(provider, {})[slot] = int(companies)
    return out


async def _reports(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    rows = (await session.scalars(select(PluginReport).order_by(PluginReport.plugin_id, PluginReport.key))).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.plugin_id, []).append(
            {"key": r.key, "value": r.value, "label": r.label, "reported_at": r.reported_at})
    return out


async def _followed(session: AsyncSession) -> int:
    """How many companies a plugin is given to read: the followed set its
    `companies()` call answers (`host._companies`)."""
    return int(await session.scalar(select(func.count()).select_from(TrackedCompany)
                                    .where(TrackedCompany.enabled.is_(True))) or 0)


def _reading_left(jobs: Sequence[dict[str, Any]], runs: Sequence[schedule.RunRecord]) -> dict[str, Any] | None:
    """The longest pass under way among the plugin's jobs."""
    left = [r for r in (schedule.reading_left(j, runs) for j in jobs) if r is not None]
    if not left:
        return None
    most = max(left, key=lambda r: r.seconds)
    return {"units": most.units, "seconds_per_unit": most.seconds_per_unit, "seconds": most.seconds}


def estimates_read(state: ReferenceState | None, plugin_id: str) -> bool:
    """Whether the applied reference set, or the one a re-estimate is moving to,
    reads `plugin_id`'s rows: then its data may not be removed yet."""
    if state is None:
        return False
    for record in (state.applied_providers or {}, state.target_providers or {}):
        if plugin_id in {pid for pids in (record.get("active") or {}).values() for pid in pids}:
            return True
    return False


def _view(row: PluginInstall, active: dict[str, tuple[str, ...]], last: PluginRun | None,
          last_clean: datetime | None, coverage: dict[str, int],
          runs: Sequence[schedule.RunRecord] = (),
          reports: Sequence[dict[str, Any]] = (), followed: int = 0,
          state: ReferenceState | None = None) -> dict[str, Any]:
    manifest = row.manifest or {}
    record = InstallRecord.of(row)
    plugin = manifest.get("plugin") or {}
    network = manifest.get("network") or {}
    jobs = [j for j in manifest.get("jobs", ()) if isinstance(j, dict)]
    schedules = [schedule.job_schedule(record, j) for j in jobs]
    starts = [schedule.next_start(record, j, runs) for j in jobs]
    due = [n.at for n in starts if n is not None and n.at is not None]
    return {
        "id": row.plugin_id,
        "name": row.name,
        "version": row.version,
        "state": record.state,
        "enabled": row.enabled,
        "slots": sorted(record.slots),
        "active_slots": sorted(slot for slot, pids in active.items() if row.plugin_id in pids),
        "jobs": [
            {"name": str(j.get("name")), "schedule": sched, "manifest_schedule": str(j.get("schedule")),
             "budget_seconds": int(j.get("budget_seconds") or 0)}
            for j, sched in zip(jobs, schedules, strict=True)
        ],
        "schedule": row.schedule,
        "schedules": list(schedule.SCHEDULES),
        "paused": row.paused_at is not None,
        "paused_at": row.paused_at,
        "next_update_at": min(due) if due else None,
        "hosts": [str(h) for h in network.get("hosts", ())],
        "attribution": plugin.get("attribution"),
        "description": plugin.get("description"),
        "licence": plugin.get("licence"),
        "repository": plugin.get("repository"),
        "installed_at": row.installed_at,
        "approved_at": row.approved_at,
        "enabled_at": row.enabled_at,
        "running": last is not None and last.outcome == "running",
        "last_run": run_view(last),
        "last_clean_at": last_clean,
        "coverage": coverage,
        "companies": followed,
        # What Remove data deletes for it, and whether it may now.
        "removable_slots": sorted(slot for slot in record.slots if slot in SLOTS and spec(slot).removable),
        "estimates_read": estimates_read(state, row.plugin_id),
        "robots_consent_at": row.robots_consent_at,
        "robots_lapsed": sorted(h for h, sha in (row.robots_consent or {}).items()
                                if (row.robots_seen or {}).get(h, sha) != sha),
        "reading_left": _reading_left(jobs, runs),
        "reports": list(reports),
    }


async def plugin_list(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(PluginInstall).order_by(PluginInstall.plugin_id))).scalars().all()
    if not rows:
        return []
    providers = await load_providers(session)
    latest, clean = await _last_runs(session)
    coverage = await _coverage(session)
    runs = await _run_records(session)
    reports = await _reports(session)
    followed = await _followed(session)
    state = await session.get(ReferenceState, 1)
    return [
        _view(row, dict(providers.active), latest.get(row.plugin_id), clean.get(row.plugin_id),
              coverage.get(row.plugin_id, {}),
              [r for r in runs if r.plugin_id == row.plugin_id], reports.get(row.plugin_id, ()), followed,
              state)
        for row in rows
    ]


async def plugin_detail(session: AsyncSession, plugin_id: str) -> dict[str, Any] | None:
    row = await session.get(PluginInstall, plugin_id)
    if row is None:
        return None
    view = next(v for v in await plugin_list(session) if v["id"] == plugin_id)
    runs = (
        await session.execute(
            select(PluginRun).where(PluginRun.plugin_id == plugin_id).order_by(PluginRun.id.desc()).limit(RECENT_RUNS)
        )
    ).scalars().all()
    view["runs"] = [run_view(r) for r in runs]
    view["approval"] = approval_text(row.manifest or {})
    view["fingerprint"] = row.fingerprint
    return view


async def plugin_robots(session: AsyncSession, plugin_id: str) -> dict[str, Any] | None:
    """Each declared site's robots rules for RoleBand, read now (network), and the
    user's current choice; None when no such plugin is installed."""
    row = await session.get(PluginInstall, plugin_id)
    if row is None:
        return None
    hosts = [str(h) for h in (row.manifest or {}).get("network", {}).get("hosts", ())]
    return {"sites": await robots.site_rules(hosts), "consent": row.robots_consent,
            "consent_at": row.robots_consent_at}


async def pay_coverage(session: AsyncSession) -> dict[str, Any]:
    """Who answers pay app-wide and the companies it has read, from
    the applied set the stored estimates follow, so a list says "not covered"
    for exactly the jobs a switch left with no estimate."""
    providers = await reader_providers(session)
    plugin = providers.source_for(PAY_LEVELS)
    return {
        "plugin": plugin,
        "plugin_name": providers.fact_labels.get(plugin) if plugin else None,
        "companies": providers.covered_companies(PAY_LEVELS),
    }


__all__ = [
    "BUILTIN_SLOTS",
    "PAY_OBSERVATIONS",
    "capabilities",
    "install_state",
    "pay_coverage",
    "plugin_robots",
    "plugin_detail",
    "plugin_list",
    "plugins_running",
    "reference_changes",
    "reference_status",
    "status_block",
]
