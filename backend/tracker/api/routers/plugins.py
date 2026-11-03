"""Settings > Plugins: list, approve, enable, disable, refresh, pause, schedule,
remove data, uninstall.

Install and update of the CODE stay CLI-only: the dashboard
approves, enables, schedules, refreshes and uninstalls what the CLI installed. Nothing here imports
the plugin SDK or a plugin: a run is a detached `tracker.plugins.cli run` process
(`plugins.runtime`), and the route table and OpenAPI do not change with what
is installed.

What each decision does lives in `plugins.lifecycle`, shared with the CLI;
this router is its transport. Every change that moves the reference set
(approve, enable, disable, uninstall, remove data) spawns a detached
re-estimate; the stored estimates follow, and `/api/status.reference` shows
the move.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from tracker.api.deps import SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.plugins import (
    PayCoverage,
    PluginActionResponse,
    PluginApprove,
    PluginDetail,
    PluginRefresh,
    PluginRefreshResponse,
    PluginRemoveData,
    PluginRemoveDataResponse,
    PluginRobots,
    PluginRobotsSet,
    PluginScheduleSet,
    PluginsResponse,
)
from tracker.config import get_settings
from tracker.platform.power import read_power
from tracker.plugins import lifecycle, runtime, status

router = APIRouter()

#: A lifecycle refusal as the API answers it.
_REFUSALS: dict[str, tuple[int, ErrorCode]] = {
    lifecycle.NOT_FOUND: (404, ErrorCode.PLUGIN_NOT_FOUND),
    lifecycle.NOT_RUNNABLE: (409, ErrorCode.PLUGIN_NOT_RUNNABLE),
    lifecycle.APPROVAL_STALE: (409, ErrorCode.PLUGIN_APPROVAL_STALE),
    lifecycle.STILL_ENABLED: (409, ErrorCode.PLUGIN_STILL_ENABLED),
    lifecycle.CONFIRM_MISMATCH: (400, ErrorCode.PLUGIN_CONFIRM_MISMATCH),
    lifecycle.RUNNING: (409, ErrorCode.PLUGIN_RUNNING),
    lifecycle.NO_JOB: (400, ErrorCode.INVALID_INPUT),
    lifecycle.ESTIMATES_MOVING: (409, ErrorCode.PLUGIN_ESTIMATES_MOVING),
    lifecycle.ROBOTS_INVALID: (400, ErrorCode.INVALID_INPUT),
}


def _error(exc: lifecycle.Refused) -> HTTPException:
    status_code, code = _REFUSALS[exc.reason]
    return api_error(status_code, code, exc.message, **exc.detail)


async def _view(session, plugin_id: str) -> dict:
    return next(v for v in await status.plugin_list(session) if v["id"] == plugin_id)


async def _follow(session, change: lifecycle.Change) -> bool:
    """Ask for a re-estimate when the change moved the reference set."""
    if change.reference_moved:
        await runtime.spawn_reestimate(session)
        await session.commit()
    return change.reference_moved


async def _answer(session, change: lifecycle.Change) -> dict:
    return {"plugin": await _view(session, change.plugin_id),
            "reestimate_started": await _follow(session, change), "stopped": change.stopped}


@router.get("/api/plugins", response_model=PluginsResponse)
async def plugins(session: SessionDep) -> dict:
    available = get_settings().plugins_enabled
    return {
        "available": available,
        "plugins": await status.plugin_list(session) if available else [],
        "reference": await status.reference_status(session),
        "capabilities": await status.capabilities(session),
    }


@router.get("/api/pay-coverage", response_model=PayCoverage)
async def pay_coverage(session: SessionDep) -> dict:
    """Who answers pay and which companies it has read."""
    return await status.pay_coverage(session)


@router.get("/api/plugins/{plugin_id}", response_model=PluginDetail)
async def plugin(session: SessionDep, plugin_id: str) -> dict:
    detail = await status.plugin_detail(session, plugin_id) if get_settings().plugins_enabled else None
    if detail is None:
        raise api_error(404, ErrorCode.PLUGIN_NOT_FOUND, f"no plugin {plugin_id!r} is installed", plugin=plugin_id)
    return detail


@router.post("/api/plugins/{plugin_id}/approve", response_model=PluginActionResponse)
async def approve(session: SessionDep, plugin_id: str, payload: PluginApprove) -> dict:
    """Approve the install AS SHOWN: the fingerprint the dialog displayed must
    still be the install's, or the code changed under the user's eyes."""
    try:
        change = await lifecycle.approve(session, plugin_id, fingerprint=payload.fingerprint,
                                         robots=payload.robots)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.get("/api/plugins/{plugin_id}/robots", response_model=PluginRobots)
async def plugin_robots(session: SessionDep, plugin_id: str) -> dict:
    """Each declared site's robots rules for RoleBand, read now, and the user's
    current choice: what the approval and Review show before the user
    allows the plugin past them."""
    view = await status.plugin_robots(session, plugin_id)
    if view is None:
        raise api_error(404, ErrorCode.PLUGIN_NOT_FOUND, f"no plugin {plugin_id!r} is installed", plugin=plugin_id)
    return view


@router.put("/api/plugins/{plugin_id}/robots", response_model=PluginActionResponse)
async def set_robots(session: SessionDep, plugin_id: str, payload: PluginRobotsSet) -> dict:
    """Allow the plugin past its sites' robots rules as shown, or stop (null)."""
    try:
        change = await lifecycle.set_robots(session, plugin_id, payload.robots)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.post("/api/plugins/{plugin_id}/enable", response_model=PluginActionResponse)
async def enable(session: SessionDep, plugin_id: str) -> dict:
    """Enabling changes no answer until the first clean run; a plugin
    that has one answers again at once, with no fetch."""
    try:
        change = await lifecycle.enable(session, plugin_id)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.post("/api/plugins/{plugin_id}/disable", response_model=PluginActionResponse)
async def disable(session: SessionDep, plugin_id: str) -> dict:
    """Stops a running job (it ends `stopped`; companies it had already
    published whole stay read) and returns
    every answer to the next provider, locally, with no fetch."""
    try:
        change = await lifecycle.disable(session, plugin_id)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.post("/api/plugins/{plugin_id}/refresh", response_model=PluginRefreshResponse)
async def refresh(session: SessionDep, plugin_id: str, payload: PluginRefresh | None = None) -> dict:
    """Refresh now: one job, due or not. Work the user starts skips the mains
    gate, never the maintenance-wake gate."""
    try:
        started = await lifecycle.start(session, plugin_id, job=payload.job if payload else None,
                                        wait_reason=lambda: read_power().wait_reason(mains=False))
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return {"started": started.started, "job": started.job, "waiting": started.waiting}


@router.post("/api/plugins/{plugin_id}/pause", response_model=PluginActionResponse)
async def pause(session: SessionDep, plugin_id: str) -> dict:
    """Pause: stop a running job (it ends `stopped`; companies it had already
    published whole stay read) and hold
    every automatic run. The plugin stays on and its data keeps answering, so
    no estimate moves."""
    try:
        change = await lifecycle.pause(session, plugin_id)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.post("/api/plugins/{plugin_id}/resume", response_model=PluginActionResponse)
async def resume(session: SessionDep, plugin_id: str) -> dict:
    """Release a pause: automatic runs follow the schedule again. Starts nothing
    now (Start does: `refresh` releases a pause too)."""
    try:
        change = await lifecycle.resume(session, plugin_id)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.put("/api/plugins/{plugin_id}/schedule", response_model=PluginActionResponse)
async def set_schedule(session: SessionDep, plugin_id: str, payload: PluginScheduleSet) -> dict:
    """How often every job of the plugin runs; null returns to the plugin's own.
    Changes when it fetches, never what is read."""
    try:
        change = await lifecycle.set_schedule(session, plugin_id, payload.schedule)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.delete("/api/plugins/{plugin_id}", response_model=PluginActionResponse)
async def uninstall(session: SessionDep, plugin_id: str) -> dict:
    """Uninstall: everything disable does, then forget the code (its venv and
    copied source, never its data directory). Every row it published stays,
    unread, until the user's Remove data; installing it again needs approval."""
    try:
        change = await lifecycle.uninstall(session, plugin_id)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return await _answer(session, change)


@router.post("/api/plugins/{plugin_id}/remove-data", response_model=PluginRemoveDataResponse)
async def remove_data(session: SessionDep, plugin_id: str, payload: PluginRemoveData) -> dict:
    """Delete the plugin's pay-level and benefit rows: typed
    confirmation, a disabled plugin only, never automatic. Append-only
    observations and fact claims are history and stay, unread."""
    try:
        deleted, change = await lifecycle.remove_data(session, plugin_id, confirm=payload.confirm)
    except lifecycle.Refused as exc:
        raise _error(exc) from None
    return {"deleted": deleted, "reestimate_started": await _follow(session, change)}
