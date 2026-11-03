"""Health checks for the supervisor's `health` job.

The supervisor owns API recovery and backup scheduling, including wake catch-up.
This pass records unhealthy conditions, recovers embedded Postgres, reconciles
orphaned runs, stops a scan that reads no further, and queues a scan when data
is stale.

Backup failures are alert-only here: an immediate retry can repeat the backup
script's empty-database refusal. A state file suppresses repeated desktop alerts
while a condition persists.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, text

from tracker.config import get_settings
from tracker.db import job_store
from tracker.db.models import JobRun, Notification, ScrapeRun, ScrapeSourceRun
from tracker.db.repo import reconcile_stale_runs
from tracker.db.session import session_scope
from tracker.health import freshness, should_catch_up, stale_derivations
from tracker.osnotify import TITLE, banner, notify
from tracker.platform.embedded_db import EmbeddedDbError, stop_server
from tracker.platform.http import make_client
from tracker.platform.paths import DATA_DIR
from tracker.platform.util import describe_exception
from tracker.supervisor.results import FAILED

logger = logging.getLogger(__name__)

STATE_FILE = DATA_DIR / "watchdog_state.json"
ALERTS_LOG = DATA_DIR / "alerts.log"
BACKUPS_DIR = DATA_DIR / "backups"

# Human-readable text for each alert key (used for banner + alerts.log).
ALERT_KEYS = {
    "db_down": "banner-db-down",
    "api_down": "banner-api-down",
    "stuck_runs": "banner-stuck-runs",
    "stale_data": "banner-stale-data",
    "derivations_stale": "banner-derivations-stale",
    "backup_stale": "banner-backup-stale",
}


def newest_backup_at(backups_dir) -> datetime | None:
    """Modification time of the newest dump, or ``None`` when there are none.

    Deliberately reads the directory rather than a status file the backup script
    writes: it must report "no backups" for every failure mode, including the
    ones where the script never ran at all (agent unloaded, database down,
    the whole file tree gone).
    """
    try:
        dumps = list(backups_dir.glob("roleband_*.dump"))
    except Exception:  # noqa: BLE001 - unreadable dir counts as no backups
        return None
    if not dumps:
        return None
    newest = max(dump.stat().st_mtime for dump in dumps)
    return datetime.fromtimestamp(newest, UTC)


def backup_failed(run: JobRun | None, newest_dump: datetime | None) -> bool:
    """Whether the last backup run left no dump: it failed, timed out or never
    started, and no dump has landed since it began (a hand-run backup after a
    failed night clears it)."""
    if run is None:
        return False
    failed = run.state in (job_store.TIMED_OUT, job_store.SPAWN_FAILED) or (
        run.state == job_store.EXITED and (run.result or {}).get("kind") == FAILED
    )
    return failed and (newest_dump is None or newest_dump < run.started_at)


async def _last_backup() -> JobRun | None:
    try:
        async with session_scope() as session:
            return await job_store.last_ended(session, "backup")
    except Exception as exc:  # noqa: BLE001 - the dump's age still alerts without the record
        logger.warning("could not read the last backup run: %s", exc)
        return None


def recover_db() -> str | None:
    """Bring the database back. Returns a failure summary, or None on success.

    In-process: the embedded server is ours to start. The ensure-seam is
    idempotent, so this
    attaches when the server is merely unreachable-from-here and starts it when
    it is genuinely down.
    """
    settings = get_settings()
    if settings.database_url_override or not settings.db_embedded:
        # An external server is the operator's to run; restarting is not ours.
        return "external database is unreachable (ROLEBAND_DATABASE_URL)"
    try:
        settings.ensure_embedded_server()
    except EmbeddedDbError as attach_error:
        # Attaching is not always enough: the *running server* can be the
        # fault. A postmaster started from an install tree that was later
        # deleted survives on open inodes, SELECT 1 keeps passing, and every
        # new backend fails to load $libdir/vector. A restart from this
        # checkout's intact install tree is the remedy, so escalate once
        # before reporting failure.
        try:
            stop_server(settings.embedded_pgdata())
            settings.ensure_embedded_server()
        except EmbeddedDbError as restart_error:
            # The message already carries the tail of <pgdata>/log, which is
            # the only place initdb/startup errors surface.
            return f"{restart_error} (initial attach error: {attach_error})"
    return None


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001 - missing/corrupt state resets cleanly
        return {}


def _save_state(state: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist watchdog state: %s", exc)


def _append_alert(message: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with ALERTS_LOG.open("a") as fh:
            fh.write(f"{stamp} {message}\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not append alert: %s", exc)


def dispatch_alerts(prev: dict, firing: dict) -> list[str]:
    """Notify + log only conditions that are *newly* firing. Returns them.

    Pure w.r.t. inputs except for the notify/log side effects, and returns the
    dispatched keys so the behavior is unit-testable.
    """
    dispatched: list[str] = []
    for key, is_firing in firing.items():
        if is_firing and not prev.get(key):
            message = banner(ALERT_KEYS[key]) if key in ALERT_KEYS else key
            notify(TITLE, message)
            _append_alert(message)
            dispatched.append(key)
    return dispatched


def _api_base(settings) -> str:
    return f"http://{settings.api_host}:{settings.api_port}"


async def _http_get(client: httpx.AsyncClient, base: str, path: str, timeout: float):
    try:
        resp = await client.get(base + path, timeout=timeout)
        return resp
    except Exception:  # noqa: BLE001 - unreachable/hung endpoint
        return None


# A reachable server can still be broken: SELECT 1 succeeds while every backend
# that needs an extension .so fails to load it (a postmaster started from a
# since-deleted install tree answers SELECT 1 while `$libdir/vector` is gone
# for every new connection). Probe each *installed*
# extension's library; a merely-uninstalled extension is the migration gate's
# business, not the supervisor's.
_DB_PROBE_SQL = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        PERFORM '[1]'::vector;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        PERFORM similarity('probe', 'probe');
    END IF;
END
$$
"""


async def _db_reachable() -> bool:
    try:
        async with asyncio.timeout(5):
            async with session_scope() as session:
                await session.execute(text("SELECT 1"))
                await session.execute(text(_DB_PROBE_SQL))
        return True
    except Exception:  # noqa: BLE001
        return False


async def ring_scan() -> None:
    """Stale data asks for a scan: a request, which joins one already queued and
    waits for a live scan, never a restart of one."""
    async with session_scope() as session:
        await job_store.ring(session, "scan", requested_by="catch_up")


#: How long past a company's own budget a scan may go without finishing a
#: company before it is stuck: every company stops by its budget, its backstop
#: and its close grace, so a scan still reading finishes one well within this.
STUCK_MARGIN = timedelta(minutes=15)


async def stop_stuck_scan(session, *, now: datetime, settings) -> bool:
    """Ask the supervisor to stop the live scan when it has finished no company
    for a company's budget plus `STUCK_MARGIN` while it still reads. A scan is
    judged by its progress, never by how long it has run: a slow network makes
    a scan long, not stuck. Once stopped, the next tick closes it as
    interrupted and continues with the companies it had not read. The passes
    after collection are not judged here. True when a stop was asked for."""
    run = await session.scalar(
        select(ScrapeRun).where(ScrapeRun.status == "running").order_by(ScrapeRun.id.desc()).limit(1)
    )
    if run is None:
        return False
    phase = await session.scalar(
        select(Notification.meta["progress"]["phase"].astext).where(
            Notification.source_type == "run",
            Notification.source_id == run.id,
            Notification.category == "sync_started",
        )
    )
    if phase not in (None, "collecting"):
        return False
    last = await session.scalar(
        select(func.max(ScrapeSourceRun.finished_at)).where(ScrapeSourceRun.run_id == run.id)
    )
    if now - (last or run.started_at) < timedelta(seconds=settings.scraper_source_budget_seconds) + STUCK_MARGIN:
        return False
    scan = next((job for job in await job_store.live_runs(session) if job.key == "scan"), None)
    if scan is None:
        return False
    return await job_store.request_cancel(session, scan.id, reason="stuck")


async def run_once(
    *,
    catch_up: Callable[[], Awaitable[None]] = ring_scan,
    reconcile_runs: bool = True,
) -> dict:
    """Execute one supervision pass. Returns the firing-condition map.

    `catch_up` is what stale data asks for: a scan request. `reconcile_runs` is
    False while the supervisor holds a live scan process: a run whose process
    provably lives is not stuck, whatever its heartbeat said across a sleep. An
    API that does not answer is reported; the supervisor that runs it restarts
    it (`tracker.supervisor.api`)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prev = _load_state()
    firing: dict[str, bool] = {}
    settings = get_settings()

    # 1. Database reachability (fix before anything that needs it).
    db_ok = await _db_reachable()
    if not db_ok:
        firing["db_down"] = True
        logger.warning("db unreachable; starting the embedded server")
        failure = recover_db()
        if failure:
            logger.error("db recovery failed: %s", failure)
        db_ok = await _db_reachable()

    # The supervisor owns recovery for an unhealthy API.
    api_base = _api_base(settings)
    async with make_client(timeout=5.0) as client:
        health = await _http_get(client, api_base, "/api/health", 3.0)
    if health is None or health.status_code != 200:
        firing["api_down"] = True
        logger.warning("api health failed")

    # 3. Reconcile orphaned "running" runs (covers a scraper that died between fires).
    if db_ok and reconcile_runs:
        try:
            async with session_scope() as session:
                reconciled = await reconcile_stale_runs(
                    session,
                    settings.stale_run_minutes,
                    settings.stale_run_heartbeat_seconds,
                )
            if reconciled:
                firing["stuck_runs"] = True
                logger.info("reconciled %d stuck run(s)", reconciled)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stale-run reconcile failed: %s", describe_exception(exc), exc_info=True)
    elif db_ok:
        try:
            async with session_scope() as session:
                stopped = await stop_stuck_scan(session, now=datetime.now(UTC), settings=settings)
            if stopped:
                firing["stuck_runs"] = True
                logger.warning("the live scan finished no company for too long; asked it to stop")
        except Exception as exc:  # noqa: BLE001
            logger.warning("stuck-scan check failed: %s", describe_exception(exc), exc_info=True)

    # 4. Freshness catch-up — advance provider-safe due work if data is stale.
    if db_ok and not firing.get("api_down"):
        async with make_client(timeout=5.0) as client:
            status_resp = await _http_get(client, api_base, "/api/status", 5.0)
        if status_resp is not None and status_resp.status_code == 200:
            payload = status_resp.json()
            if should_catch_up(payload):
                firing["stale_data"] = True
                logger.info("data stale; asking for a scan")
                await catch_up()
            # A derived table can go stale while the scrape itself is healthy:
            # a pass that never ran or is failing. Notify; authoritative
            # reconciliation owns the rebuild.
            stale = stale_derivations(payload)
            if stale:
                firing["derivations_stale"] = True
                logger.warning("stale derivations: %s", ", ".join(stale))

    # 5. Backup freshness. Checked unconditionally — a backup that stopped
    #    landing matters most exactly when the rest of the system looks fine.
    newest_dump = newest_backup_at(BACKUPS_DIR)
    _, backup_stale = freshness(newest_dump, datetime.now(UTC), settings.backup_max_age_hours)
    if backup_stale:
        firing["backup_stale"] = True
        logger.warning("no database backup within %dh", settings.backup_max_age_hours)
    elif db_ok and backup_failed(await _last_backup(), newest_dump):
        firing["backup_stale"] = True
        logger.warning("the last backup run failed; see data/logs/backup.log")

    dispatch_alerts(prev, firing)
    _save_state(firing)
    return firing


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
