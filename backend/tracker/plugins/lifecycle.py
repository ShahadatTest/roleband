"""What a user's decision about a plugin does, once, for every surface.

Settings > Plugins (`api/routers/plugins.py`) and the CLI (`scripts.plugin`)
both approve, enable, disable, pause, schedule, uninstall and remove data
through here, so the two cannot drift: each step commits its change, then does
what the change implies, in this order:

- a run that must end is signalled (`runtime.stop_runs`: disable, pause,
  uninstall; the run ends `stopped`, and a company it had already published
  whole stays read);
- every profile the plugin's claims touch resolves again (approve, enable,
  disable, uninstall);
- whether the reference set moved is reported (`Change.reference_moved`), and
  the caller follows it: the API spawns a detached re-estimate, the CLI runs it
  in place.

A refusal is a `Refused` with a `reason` the API maps to its error code. This
module imports neither the plugin SDK nor a plugin.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import PluginInstall, PluginRun, ReferenceState
from tracker.plugins import install as installer
from tracker.plugins import runtime, status, store, writer
from tracker.plugins.install import approval_text, forget_code
from tracker.plugins.reestimate import begin
from tracker.plugins.registry import REFERENCE_SOURCES_KEY, SLOTS, InstallRecord, install_records
from tracker.plugins.schedule import job_schedule
from tracker.profiles.store import rematerialize_sources
from tracker.settings_store import get_setting_dict, set_setting_dict

#: Why a decision was refused; `api/routers/plugins.py` maps each to its code.
NOT_FOUND = "not_found"
NOT_RUNNABLE = "not_runnable"
APPROVAL_STALE = "approval_stale"
STILL_ENABLED = "still_enabled"
CONFIRM_MISMATCH = "confirm_mismatch"
RUNNING = "running"
NO_JOB = "no_job"
ESTIMATES_MOVING = "estimates_moving"
NOT_A_PROVIDER = "not_a_provider"
ROBOTS_INVALID = "robots_invalid"
_SHA = re.compile(r"[0-9a-f]{64}")


class Refused(Exception):
    """The decision cannot be applied; `reason` is one of the codes above."""

    def __init__(self, reason: str, message: str, **detail: Any) -> None:
        self.reason = reason
        self.message = message
        self.detail = detail
        super().__init__(message)


@dataclass(frozen=True)
class Change:
    plugin_id: str
    #: Runner PIDs signalled to stop.
    stopped: list[int] = field(default_factory=list)
    #: The current reference fingerprint is not the applied one: estimates must follow.
    reference_moved: bool = False


@dataclass(frozen=True)
class Started:
    """What Start (Refresh now) did."""

    job: str
    started: bool
    #: Why it did not start now (a maintenance wake), else None.
    waiting: str | None = None


async def _install(session: AsyncSession, plugin_id: str) -> PluginInstall:
    row = await session.get(PluginInstall, plugin_id)
    if row is None:
        raise Refused(NOT_FOUND, f"no plugin {plugin_id!r} is installed", plugin=plugin_id)
    return row


def _present(row: PluginInstall, what: str) -> None:
    if row.removed_at is not None:
        raise Refused(NOT_RUNNABLE, f"a removed plugin cannot be {what}", plugin=row.plugin_id)


async def _rematerialize(session: AsyncSession, row: PluginInstall) -> None:
    """Its claims became read or unread: every profile they touch resolves
    again now."""
    await rematerialize_sources(session, [row.plugin_id])
    await session.commit()


async def _estimates_read(session: AsyncSession, plugin_id: str) -> bool:
    """Whether the applied reference set, or the one a re-estimate is moving to,
    reads `plugin_id`'s rows (`status.estimates_read`, which the view shows)."""
    return status.estimates_read(await session.get(ReferenceState, 1), plugin_id)


async def reference_moved(session: AsyncSession) -> bool:
    """Whether the stored estimates must follow this decision. When they must,
    the target is recorded now (`reestimate.begin`), so `/api/status` says they
    are updating before the re-estimate the caller spawns has started;
    otherwise it would say nothing is pending while every reader still reads the
    old set."""
    return await begin(session)


async def install(
    session: AsyncSession, source: Path, *, plugins_dir: Path, venv: bool = True,
) -> tuple[PluginInstall, bool, Change]:
    """Install or update from `source` (`plugins.install`; `InstallRefused` says
    why not). An update that lapses an approval makes the plugin's claims unread at
    once: their profiles resolve again
    and the estimates follow."""
    row, lapsed = await installer.install(session, source, plugins_dir=plugins_dir, venv=venv)
    await session.commit()
    if not lapsed:
        return row, False, Change(row.plugin_id)
    await _rematerialize(session, row)
    return row, True, Change(row.plugin_id, reference_moved=await reference_moved(session))


def _check_robots(row: PluginInstall, robots: Mapping[str, str] | None) -> None:
    """A consent names only hosts the plugin declares, each by a file's sha256."""
    if not robots:
        return
    declared = set((row.manifest or {}).get("network", {}).get("hosts", ()))
    bad = sorted(h for h, sha in robots.items() if h not in declared or not _SHA.fullmatch(str(sha)))
    if bad:
        raise Refused(ROBOTS_INVALID, f"not a declared host with a robots file sha256: {', '.join(bad)}",
                      plugin=row.plugin_id)


async def approve(session: AsyncSession, plugin_id: str, *, fingerprint: str,
                  robots: Mapping[str, str] | None = None) -> Change:
    """Approve the install AS SHOWN: `fingerprint` is the one the user was shown,
    and it must still be the install's, or the code changed under their eyes.
    `robots`: what the user chose in the same dialog about its sites' robots
    rules, {host: sha256} of the files they allowed it past, or None:
    it follows them. An approval always records that choice."""
    row = await _install(session, plugin_id)
    _present(row, "approved")
    if fingerprint != row.fingerprint:
        raise Refused(APPROVAL_STALE, "the plugin changed since it was shown", plugin=plugin_id)
    _check_robots(row, robots)
    await store.approve(session, plugin_id, shown=approval_text(row.manifest or {}))
    await store.set_robots_consent(session, plugin_id, robots)
    await session.commit()
    await _rematerialize(session, row)  # an enabled plugin approved again is read again
    return Change(plugin_id, reference_moved=await reference_moved(session))


async def set_robots(session: AsyncSession, plugin_id: str, robots: Mapping[str, str] | None) -> Change:
    """Allow the plugin past its sites' robots rules as shown ({host: sha256}), or
    stop (None): Settings > Plugins, after a site changed its file or on second
    thoughts. Moves no estimate: it changes what the next run may read."""
    row = await _install(session, plugin_id)
    _check_robots(row, robots)
    await store.set_robots_consent(session, plugin_id, robots)
    await session.commit()
    return Change(plugin_id)


async def enable(session: AsyncSession, plugin_id: str) -> Change:
    """Selects the plugin for every slot it declares, before it has read
    anything: a company it has not read is "not covered", never ours.
    Readers move to it at one moment, when the re-estimate the caller follows
    applies the set; no fetch."""
    row = await _install(session, plugin_id)
    _present(row, "enabled")
    await store.set_enabled(session, plugin_id, True)
    await session.commit()
    await _rematerialize(session, row)
    return Change(plugin_id, reference_moved=await reference_moved(session))


async def disable(session: AsyncSession, plugin_id: str) -> Change:
    """Stops a running job; every slot it answered returns to ours (or the next
    plugin in order) when the re-estimate the caller follows applies the set,
    with no fetch."""
    row = await _install(session, plugin_id)
    await store.set_enabled(session, plugin_id, False)
    await session.commit()
    stopped = await runtime.stop_runs(session, plugin_id)
    await _rematerialize(session, row)
    return Change(plugin_id, stopped=stopped, reference_moved=await reference_moved(session))


async def pause(session: AsyncSession, plugin_id: str) -> Change:
    """Stop a running job and hold every automatic run. The plugin stays on and
    its data keeps answering, so no estimate moves."""
    row = await _install(session, plugin_id)
    _present(row, "paused")
    await store.set_paused(session, plugin_id, True)
    await session.commit()
    return Change(plugin_id, stopped=await runtime.stop_runs(session, plugin_id))


async def resume(session: AsyncSession, plugin_id: str) -> Change:
    """Release a pause: automatic runs follow the schedule again. Starts nothing."""
    await _install(session, plugin_id)
    await store.set_paused(session, plugin_id, False)
    await session.commit()
    return Change(plugin_id)


async def set_schedule(session: AsyncSession, plugin_id: str, schedule: str | None) -> Change:
    """How often every job runs; None returns to the plugin's own. Changes when
    it fetches, never what is read."""
    row = await _install(session, plugin_id)
    _present(row, "scheduled")
    await store.set_schedule(session, plugin_id, schedule)
    await session.commit()
    return Change(plugin_id)


async def uninstall(session: AsyncSession, plugin_id: str) -> Change:
    """Everything disable does, then forget the code (its venv and copied source,
    never its data directory). Every row it published stays, unread, until the
    user's Remove data; installing it again needs approval."""
    row = await _install(session, plugin_id)
    await store.mark_removed(session, plugin_id)
    await session.commit()
    stopped = await runtime.stop_runs(session, plugin_id)
    forget_code(row.source_dir)
    await _rematerialize(session, row)
    return Change(plugin_id, stopped=stopped, reference_moved=await reference_moved(session))


async def remove_data(session: AsyncSession, plugin_id: str, *, confirm: str) -> tuple[dict[str, int], Change]:
    """Delete the plugin's pay-level and benefit rows and its coverage: typed
    confirmation, a plugin that is off, never automatic. Append-only
    observations and fact claims are history and stay, unread."""
    row = await _install(session, plugin_id)
    if confirm != plugin_id:
        raise Refused(CONFIRM_MISMATCH, "type the plugin's id to confirm", plugin=plugin_id)
    if row.enabled and row.removed_at is None:
        raise Refused(STILL_ENABLED, "disable the plugin before removing its data", plugin=plugin_id)
    if await _estimates_read(session, plugin_id):
        # The disable's re-estimate has not landed: stored estimates still come
        # from these rows, and deleting them now would leave a list and a detail
        # answering from different data until it does.
        raise Refused(ESTIMATES_MOVING, "the estimates still read this plugin's data; try again when they are updated",
                      plugin=plugin_id)
    if await session.scalar(select(PluginRun.id).where(PluginRun.plugin_id == plugin_id,
                                                       PluginRun.outcome == "running").limit(1)) is not None:
        # A run would publish into the tables being emptied.
        raise Refused(RUNNING, "an update is running; stop it before removing its data", plugin=plugin_id)
    deleted = await writer.remove_provider_rows(session, plugin_id)
    deleted["plugin_state"] = await store.clear_state(session, plugin_id)
    deleted["plugin_report"] = await store.clear_reports(session, plugin_id)
    deleted["plugin_coverage"] = await store.clear_coverage(session, plugin_id)
    await session.commit()
    return deleted, Change(plugin_id, reference_moved=await reference_moved(session))


async def set_order(session: AsyncSession, slot: str, plugin_ids: list[str]) -> Change:
    """Which plugin answers first in `slot` when several do (`reference_sources`,
    read by the registry); an empty list returns to the id order. Each id must
    be an installed plugin that provides the slot."""
    if slot not in SLOTS:
        raise Refused(NOT_A_PROVIDER, f"unknown slot {slot!r}", slot=slot)
    records = {r.plugin_id: r for r in await install_records(session)}
    for pid in plugin_ids:
        if pid not in records or slot not in records[pid].slots:
            raise Refused(NOT_A_PROVIDER, f"{pid!r} is not an installed plugin providing {slot}", plugin=pid)
    order = dict(await get_setting_dict(session, REFERENCE_SOURCES_KEY) or {})
    if plugin_ids:
        order[slot] = list(dict.fromkeys(plugin_ids))
    else:
        order.pop(slot, None)
    await set_setting_dict(session, REFERENCE_SOURCES_KEY, order)
    await session.commit()
    return Change(plugin_ids[0] if plugin_ids else "", reference_moved=await reference_moved(session))


async def start(
    session: AsyncSession, plugin_id: str, *, job: str | None, wait_reason: Callable[[], str | None],
) -> Started:
    """Start one job now, due or not: the named one, else the first scheduled,
    else the first. Work the user starts skips the mains gate, never the
    maintenance-wake gate (`wait_reason`), and releases a pause."""
    row = await _install(session, plugin_id)
    record = InstallRecord.of(row)
    if record.state != "enabled":
        raise Refused(NOT_RUNNABLE, f"plugin {plugin_id!r} is {record.state}", plugin=plugin_id,
                      state=record.state)
    jobs = [j for j in record.manifest.get("jobs", ()) if isinstance(j, dict)]
    names = [str(j.get("name")) for j in jobs]
    scheduled = [str(j.get("name")) for j in jobs if job_schedule(record, j) != "manual"]
    chosen = job or next(iter(scheduled or names), None)
    if chosen is None or chosen not in names:
        raise Refused(NO_JOB, f"plugin {plugin_id!r} has no job {chosen!r}", plugin=plugin_id)
    await runtime.reconcile_dead_runs(session)
    await session.commit()
    if await store.running_runs(session, plugin_id):
        raise Refused(RUNNING, f"plugin {plugin_id!r} is already running", plugin=plugin_id)
    waiting = wait_reason()
    if waiting is not None:
        return Started(chosen, started=False, waiting=waiting)
    if row.paused_at is not None:  # Start releases a pause: the user asked for work
        await store.set_paused(session, plugin_id, False)
        await session.commit()
    await runtime.spawn_run(session, plugin_id, chosen, trigger="manual")
    await session.commit()
    return Started(chosen, started=True)
