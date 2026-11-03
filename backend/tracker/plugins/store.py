"""The one writer of `plugin_install`, `plugin_run`, `plugin_state`, `plugin_report` and `plugin_coverage`.

Install, approve, enable and disable change `plugin_install`; the host opens and
closes `plugin_run`, keeps `plugin_state` and `plugin_report`, and records
`plugin_coverage`. Nothing
here imports the plugin SDK: the manifest arrives as the dict the SDK produced.

Approval follows the consent model (`company_store.record_consent`): what the
user was shown is stored with the fingerprint it approved, and any change to
the plugin's code, manifest or lock produces a new fingerprint, which lapses it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import PluginCoverage, PluginInstall, PluginReport, PluginRun, PluginState

OUTCOMES = ("clean", "partial", "bounded", "stopped", "error")
#: Outcomes that went through the job: a `partial` run did what it set out to and
#: was refused some of it (one failed request among thousands, a robots rule), so
#: it ends or continues a pass as a clean run does; its refusals stay on the run.
#: The rest are attempts the schedule retries.
PASS_OUTCOMES = frozenset({"clean", "partial"})
TRIGGERS = ("schedule", "sync", "manual", "cli")


def fingerprint(*, manifest_sha: str, code_sha: str, lock_sha: str | None) -> str:
    """What an approval approves: the manifest, the code, the lock."""
    joined = "\n".join((manifest_sha, code_sha, lock_sha or "-"))
    return hashlib.sha256(joined.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def record_install(
    session: AsyncSession,
    *,
    plugin_id: str,
    name: str,
    version: str,
    source_dir: str,
    manifest: Mapping[str, Any],
    manifest_sha: str,
    code_sha: str,
    commit_sha: str | None,
    lock_sha: str | None,
    sdk_version: str | None = None,
) -> PluginInstall:
    """Install or update. An update keeps `enabled` but its new fingerprint no
    longer equals the approved one, so it cannot run until approved again."""
    fp = fingerprint(manifest_sha=manifest_sha, code_sha=code_sha, lock_sha=lock_sha)
    values = dict(
        name=name, version=version, source_dir=source_dir, manifest=dict(manifest),
        manifest_sha=manifest_sha, code_sha=code_sha, commit_sha=commit_sha, lock_sha=lock_sha, fingerprint=fp,
        sdk_version=sdk_version, removed_at=None, updated_at=_now(),
    )
    await session.execute(
        pg_insert(PluginInstall)
        .values(plugin_id=plugin_id, **values)
        .on_conflict_do_update(index_elements=[PluginInstall.plugin_id], set_=values)
    )
    row = await session.get(PluginInstall, plugin_id, populate_existing=True)
    assert row is not None
    return row


async def approve(session: AsyncSession, plugin_id: str, *, shown: Mapping[str, Any]) -> PluginInstall:
    """Approve the plugin as it is now, recording what the user was shown."""
    row = await _get(session, plugin_id)
    row.approved_fingerprint = row.fingerprint
    row.approved_at = _now()
    row.approved_text = dict(shown)
    return row


async def set_robots_consent(session: AsyncSession, plugin_id: str, consent: Mapping[str, str] | None) -> PluginInstall:
    """The user's choice about the sites' robots rules: {host: sha256}
    of the files they allowed the plugin past, or None (it follows them)."""
    row = await _get(session, plugin_id)
    row.robots_consent = dict(consent) if consent else None
    row.robots_consent_at = _now() if consent else None
    return row


async def note_robots_seen(session: AsyncSession, plugin_id: str, seen: Mapping[str, str]) -> None:
    """The robots files a run read, per host (kept with the ones read before)."""
    if not seen:
        return
    row = await _get(session, plugin_id)
    row.robots_seen = {**(row.robots_seen or {}), **seen}


async def set_enabled(session: AsyncSession, plugin_id: str, enabled: bool) -> PluginInstall:
    row = await _get(session, plugin_id)
    row.enabled = enabled
    row.enabled_at = _now() if enabled else row.enabled_at
    return row


async def set_paused(session: AsyncSession, plugin_id: str, paused: bool) -> PluginInstall:
    """Hold, or release, every automatic run. The plugin stays on and answers."""
    row = await _get(session, plugin_id)
    row.paused_at = (row.paused_at or _now()) if paused else None
    return row


async def set_schedule(session: AsyncSession, plugin_id: str, schedule: str | None) -> PluginInstall:
    """The user's schedule for every job of the plugin; None = the manifest's."""
    row = await _get(session, plugin_id)
    row.schedule = schedule
    return row


async def mark_removed(session: AsyncSession, plugin_id: str) -> PluginInstall:
    """Remove does what disable does and forgets the code; every row it
    published stays, unread (the registry still knows the provider is a plugin's)."""
    row = await _get(session, plugin_id)
    row.enabled = False
    row.removed_at = _now()
    return row


async def _get(session: AsyncSession, plugin_id: str) -> PluginInstall:
    row = await session.get(PluginInstall, plugin_id)
    if row is None:
        raise LookupError(f"no plugin {plugin_id!r} is installed")
    return row


async def open_run(
    session: AsyncSession, install: PluginInstall, job: str, *, trigger: str, pid: int | None = None
) -> PluginRun:
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    run = PluginRun(plugin_id=install.plugin_id, job=job, trigger=trigger, fingerprint=install.fingerprint,
                    outcome="running", pid=pid, heartbeat_at=_now())
    session.add(run)
    await session.flush()
    return run


async def note_progress(session: AsyncSession, run_id: int, done: int, total: int | None) -> None:
    await session.execute(
        update(PluginRun)
        .where(PluginRun.id == run_id)
        .values(progress_done=done, progress_total=total, heartbeat_at=_now())
    )


async def note_summary(session: AsyncSession, run_id: int, text: str) -> None:
    await session.execute(
        update(PluginRun).where(PluginRun.id == run_id).values(summary=text, heartbeat_at=_now())
    )


async def close_run(
    session: AsyncSession,
    run_id: int,
    *,
    outcome: str,
    published: Mapping[str, int],
    refusals: list[str],
    message: str | None,
    continues: bool = False,
) -> None:
    """Record the host's verdict. `continues`: the plugin said its pass is not
    through (`end.more`); only a run that went through the job
    (`PASS_OUTCOMES`) carries it."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    await session.execute(
        update(PluginRun)
        .where(PluginRun.id == run_id)
        .values(outcome=outcome, ended_at=_now(), published=dict(published), refusals=refusals[:200],
                message=(message or None) and message[:4000], continues=continues and outcome in PASS_OUTCOMES)
    )


async def state_get(session: AsyncSession, plugin_id: str, key: str) -> tuple[bool, Any]:
    row = await session.get(PluginState, (plugin_id, key))
    return (False, None) if row is None else (True, row.value)


async def state_keys(session: AsyncSession, plugin_id: str) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(PluginState).where(PluginState.plugin_id == plugin_id)) or 0)


async def state_set(session: AsyncSession, plugin_id: str, key: str, value: Any) -> None:
    await session.execute(
        pg_insert(PluginState)
        .values(plugin_id=plugin_id, key=key, value=value, updated_at=_now())
        .on_conflict_do_update(
            index_elements=[PluginState.plugin_id, PluginState.key], set_={"value": value, "updated_at": _now()}
        )
    )


async def report_keys(session: AsyncSession, plugin_id: str) -> set[str]:
    return set((await session.scalars(select(PluginReport.key).where(PluginReport.plugin_id == plugin_id))).all())


async def report_set(session: AsyncSession, plugin_id: str, key: str, value: int | None, label: str) -> None:
    """The latest value a plugin reported under `key`; None withdraws it."""
    if value is None:
        await session.execute(
            delete(PluginReport).where(PluginReport.plugin_id == plugin_id, PluginReport.key == key))
        return
    at = _now()
    await session.execute(
        pg_insert(PluginReport)
        .values(plugin_id=plugin_id, key=key, value=value, label=label, reported_at=at)
        .on_conflict_do_update(
            index_elements=[PluginReport.plugin_id, PluginReport.key],
            set_={"value": value, "label": label, "reported_at": at},
        )
    )


async def note_coverage(
    session: AsyncSession, *, provider: str, slot: str, company: str, rows: int, run_id: int,
    complete: bool = False,
) -> None:
    """Record a publish. A complete one marks the company read whole
    (`complete_at`, kept from the first time): its rows there are read from now."""
    now = _now()
    stmt = pg_insert(PluginCoverage).values(
        provider=provider, slot=slot, company_slug=company, last_attempt_at=now, last_published_at=now,
        rows=rows, last_run_id=run_id, complete_at=now if complete else None,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[PluginCoverage.provider, PluginCoverage.slot, PluginCoverage.company_slug],
            set_={"last_attempt_at": now, "last_published_at": now, "rows": rows, "last_run_id": run_id,
                  "complete_at": func.coalesce(PluginCoverage.complete_at, stmt.excluded.complete_at)},
        )
    )


async def complete_coverage(session: AsyncSession, providers: list[str]) -> dict[str, dict[str, dict[str, datetime]]]:
    """provider -> slot -> {company: when first read whole}, for these providers."""
    if not providers:
        return {}
    rows = (await session.execute(
        select(PluginCoverage.provider, PluginCoverage.slot, PluginCoverage.company_slug, PluginCoverage.complete_at)
        .where(PluginCoverage.provider.in_(providers), PluginCoverage.complete_at.is_not(None))
    )).all()
    out: dict[str, dict[str, dict[str, datetime]]] = {}
    for provider, slot, company, at in rows:
        out.setdefault(provider, {}).setdefault(slot, {})[company] = at
    return out


async def close_dead_runs(session: AsyncSession, run_ids: list[int]) -> None:
    """Close `running` rows whose runner process is gone (`runtime.reconcile_dead_runs`)."""
    if not run_ids:
        return
    await session.execute(
        update(PluginRun)
        .where(PluginRun.id.in_(run_ids), PluginRun.outcome == "running")
        .values(outcome="error", ended_at=_now(), message="the runner process ended without closing the run")
    )


async def running_runs(session: AsyncSession, plugin_id: str | None = None) -> list[PluginRun]:
    stmt = select(PluginRun).where(PluginRun.outcome == "running")
    if plugin_id is not None:
        stmt = stmt.where(PluginRun.plugin_id == plugin_id)
    return list((await session.execute(stmt)).scalars().all())


async def clear_state(session: AsyncSession, plugin_id: str) -> int:
    """Forget what the plugin kept about its own reading (its resume cursor and
    the like) with its removed data: its next update starts afresh."""
    result = await session.execute(delete(PluginState).where(PluginState.plugin_id == plugin_id))
    return int(getattr(result, "rowcount", 0) or 0)


async def clear_reports(session: AsyncSession, plugin_id: str) -> int:
    """Forget the numbers it reported about its data, with that data."""
    result = await session.execute(delete(PluginReport).where(PluginReport.plugin_id == plugin_id))
    return int(getattr(result, "rowcount", 0) or 0)


async def clear_coverage(session: AsyncSession, provider: str) -> int:
    """Forget `provider`'s coverage with its removed data."""
    result = await session.execute(delete(PluginCoverage).where(PluginCoverage.provider == provider))
    return int(getattr(result, "rowcount", 0) or 0)
