"""The core's plugin host: run one job of one plugin out of process and answer it.

The plugin runs the SDK runner in its own venv's interpreter, isolated (`-I`:
no current directory, user site-packages or PYTHON* variables on its path),
started in a directory it cannot write, with an environment that carries no
database address and no key of ours; nothing it can write is on its import path.
It talks to this host over stdio; the host:

- answers every call through `roleband_plugin_sdk.policy`, the same checks the
  SDK's fake host makes, so what passes a plugin's own tests passes here;
- performs every request itself: https only, declared hosts only, the
  identified client with our User-Agent (any other identity needs a consent the
  core cannot record), the host's `robots.txt` honoured unless the user allowed
  the plugin past that file, paced on one shared
  limiter per plugin at no less than the core's delay, retried by the core's
  policy, and bounded by the job's budget on a `SourceClock`;
- writes each publish in its own transaction (`writer.write_batch`); a
  facts publish leaves the profile alone, whose columns are ours only;
- decides the outcome itself (`clean`, `partial`, `bounded`, `stopped`,
  `error`). A company published whole is read, and retires the rows this run
  did not repeat for it, at that publish, whatever the run's end;
- records, once a run that published anything has closed, where the stored
  estimates go (`reestimate.begin`), so the status says they are updating.

This module imports the plugin SDK, so it runs only in the detached host
process (`tracker.plugins.cli run`, which the supervisor starts and
`scripts.plugin run` runs by hand), never in the API or the pipeline.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import signal
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from roleband_plugin_sdk import PROTOCOL_VERSION, policy, protocol
from roleband_plugin_sdk.launch import RUN_CWD, code_root, runner_command, runner_env
from roleband_plugin_sdk.manifest import Job, ManifestError, PluginManifest, validate_manifest
from roleband_robots import path_allowed, target_for
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import PluginInstall, TrackedCompany
from tracker.platform.clock import SourceClock
from tracker.platform.http import RetryDeadlineExceeded, RetryPolicy, request_with_retry
from tracker.platform.locks import AlreadyRunning, run_lock
from tracker.platform.ratelimit import RateLimiter, RateLimiterPool
from tracker.platform.safe_fetch import BlockedDestination, public_client
from tracker.plugin_manifest import accept
from tracker.plugins import store, writer
from tracker.plugins.install import SDK_DIR, installed_code_sha
from tracker.plugins.reestimate import begin
from tracker.plugins.registry import InstallRecord
from tracker.plugins.robots import ROBOTS_FAILED, read_robots, robots_sha
from tracker.taxonomy.roles import all_slugs

logger = logging.getLogger(__name__)

#: The most a response body may be; a plugin parses pages, not archives.
MAX_BODY_BYTES = 20 * 1024 * 1024
#: Per-run stderr logs a plugin's data directory keeps; older ones are deleted.
KEPT_RUN_LOGS = 20
#: The per-plugin run lock, in its data directory: one host per plugin at a time.
RUN_LOCK = ".host.lock"


def pacing_delay(manifest: PluginManifest, core_delay: float) -> float:
    """A plugin is paced at its own declared delay, and never faster than the
    core (`policy.pacing_delay`, the rule the SDK's fake host paces by too)."""
    return policy.pacing_delay(manifest, core_delay)


class NotRunnable(Exception):
    """The plugin may not run: not installed, disabled, removed, or changed since approval."""


#: Why a plugin whose `InstallRecord.state` is this may not run.
_NOT_RUNNABLE = {
    "removed": "removed",
    "needs_approval": "never approved, or changed since it was approved",
    "disabled": "disabled",
}


@dataclass
class HostConfig:
    #: The plugin venv's interpreter.
    python: str
    #: Extra import paths for the runner (a dev install, the tests).
    pythonpath: Sequence[str] = ()
    #: The plugin's own data directory (`ctx.data_dir`): its to write, so never
    #: the runner's working directory nor on its import path.
    data_dir: Path | None = None
    #: The HTTP client; None builds the identified, public-destination client.
    client: httpx.AsyncClient | None = None
    clock: Callable[[], float] = time.monotonic
    #: Seconds the host waits for the plugin's next message before it stops it.
    stall_seconds: float | None = None
    #: Called with the run id once the run row exists (the CLI prints it).
    on_open: Callable[[int], None] | None = None
    #: Starts the runner process; None is `asyncio.create_subprocess_exec`. The
    #: host builds the argv itself (the SDK runner, nothing else); tests under
    #: `no_escape` pass the real spawner here, explicitly.
    spawn: Callable[..., Awaitable[asyncio.subprocess.Process]] | None = None
    #: Seconds a runner gets to exit after its end before it is killed.
    exit_grace_seconds: float = 10.0
    #: Signals the runner (a stop ends it, a runner past its grace is killed);
    #: None is `os.kill`. Tests under `no_escape` pass the real one for the
    #: runner they started, explicitly, as with `spawn`.
    send_signal: Callable[[int, int], None] | None = None
    #: The pacer; None is the shared per-plugin limiter at `pacing_delay`.
    limiter: RateLimiter | None = None
    #: Recompute the installed code's hash before running (off only in tests
    #: that run a plugin from a source checkout).
    verify_code: bool = True


def installed_config(install: PluginInstall, *, python: str | None = None,
                     on_open: Callable[[int], None] | None = None) -> HostConfig:
    """How the host runs an installed plugin: its venv's interpreter (or
    `python`, in development), isolated and outside its data directory,
    importing the SDK this
    core ships and the plugin's APPROVED copy (`<home>/src`, the tree `code_sha`
    hashes and the host re-checks before every run) ahead of anything in the
    venv's site-packages, so the code that runs is the code that was approved,
    and the SDK is the one `plugin_manifest.accept` checked the range against."""
    home = Path(install.source_dir).parent
    return HostConfig(
        python=python or str(home / "venv" / "bin" / "python"),
        pythonpath=[str(SDK_DIR), str(code_root(Path(install.source_dir)))],
        data_dir=home / "data",
        on_open=on_open,
    )


@dataclass
class HostResult:
    run_id: int
    outcome: str
    published: dict[str, int]
    refusals: list[str]
    retired: int
    message: str | None
    stderr: str = ""
    #: The plugin stopped with its pass unfinished (`end.more`); recorded on a clean run.
    continues: bool = False


@dataclass
class _Batches:
    """What a run published: the row keys per (slot, company), and rows per slot."""

    keys: dict[tuple[str, str], set[tuple[str, ...]]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


class _Session:
    """The host side of one run."""

    def __init__(
        self, db: AsyncSession, install: PluginInstall, manifest: PluginManifest, job: Job, run_id: int,
        config: HostConfig, client: httpx.AsyncClient,
    ) -> None:
        settings = get_settings()
        self.db = db
        self.install = install
        self.provider = install.plugin_id
        self.manifest = manifest
        self.job = job
        self.run_id = run_id
        self.client = client
        self.stall_seconds = float(config.stall_seconds or settings.scraper_source_stall_seconds)
        self.clock = SourceClock(
            stall_seconds=self.stall_seconds,
            hard_deadline=config.clock() + job.budget_seconds,
            clock=config.clock,
        )
        self.limiter = config.limiter or RateLimiterPool().get(
            f"plugin:{self.provider}", pacing_delay(manifest, settings.scraper_min_delay_seconds)
        )
        self.retry = RetryPolicy(max_retries=settings.scraper_max_retries)
        self.families = frozenset(all_slugs())
        self.robots: dict[str, str | None] = {}
        #: The robots files this run read, {host: sha256} (`store.note_robots_seen`).
        self.robots_seen: dict[str, str] = {}
        #: The files the user allowed this plugin past, {host: sha256}.
        self.robots_consent: dict[str, str] = dict(install.robots_consent or {})
        self.known: dict[str, bool] = {}
        self.ended: str | None = None
        #: The host failed on its own side (a store error, a bug): the run ends `error`.
        self.failed = False
        self.stop_requested = False
        self.refusals: list[str] = []
        self.batches = _Batches()
        #: Rows retired as companies were read whole.
        self.retired = 0

    async def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        try:
            call_id, method, params = protocol.parse_call(message)
        except protocol.CallError as exc:
            return self._refuse(int(message["id"]), exc.code, exc.message)
        if self.stop_requested and not self.ended:
            self.ended = protocol.STOPPED
        if self.ended:
            return protocol.reply_error(call_id, self.ended, f"the run is {self.ended}")
        try:
            handler = getattr(self, "_" + method.replace(".", "_"))
            result = await handler(params)
        except protocol.CallError as exc:
            return self._refuse(call_id, exc.code, exc.message)
        self.clock.progress()
        return protocol.reply_ok(call_id, result)

    def _refuse(self, call_id: int, code: str, message: str) -> dict[str, Any]:
        if code in protocol.TERMINAL_CODES:
            self.ended = code
        else:
            self.refusals.append(f"{code}: {message}")
        return protocol.reply_error(call_id, code, message)

    # -- http ---------------------------------------------------------------

    async def _http_get(self, p: protocol.HttpGet) -> dict[str, Any]:
        host = policy.check_get(self.manifest, p)
        policy.check_identity(self.manifest)
        if self.clock.exhausted():
            raise protocol.CallError(protocol.BOUNDED, f"the {self.job.budget_seconds}s budget is spent")
        # Path AND query, built by the package both hosts share so neither can
        # ask a different question than the other.
        verdict = await self._robots_verdict(host, target_for(p.url))
        if verdict is not None:
            raise protocol.CallError(protocol.REFUSED, verdict)
        response = await self._fetch(p.url, dict(p.headers))
        return {
            "status": response.status_code,
            "url": str(response.url),
            "headers": {k.lower(): v for k, v in response.headers.items()},
            "body_b64": base64.b64encode(response.content).decode(),
        }

    async def _fetch(self, url: str, headers: dict[str, str]) -> httpx.Response:
        try:
            response = await request_with_retry(
                self.client, "GET", url, retry=self.retry, limiter=self.limiter, deadline=self.clock,
                log_name=f"plugin:{self.provider}", headers=headers,
            )
        except RetryDeadlineExceeded:
            raise protocol.CallError(protocol.BOUNDED, f"the {self.job.budget_seconds}s budget is spent") from None
        except BlockedDestination as exc:
            raise protocol.CallError(protocol.REFUSED, f"{url} is not public: {exc}") from None
        except httpx.HTTPError as exc:
            raise protocol.CallError(protocol.FETCH_FAILED, f"{type(exc).__name__}: {exc}") from None
        if len(response.content) > MAX_BODY_BYTES:
            raise protocol.CallError(protocol.FETCH_FAILED, f"body over {MAX_BODY_BYTES} bytes")
        return response

    async def _robots_verdict(self, host: str, path: str) -> str | None:
        """None when robots allows `path` (path and query) on `host`, else why not.
        One read per host per run, paced like any request, through `read_robots`,
        the read the approval dialog shows, so the run and the dialog see the
        same file. A host that refuses its robots file (401, 403, 5xx) is
        treated as disallowing everything, as `recipe_preview` does; a read that
        fails is tried again at the next request to the host.

        The rules are those for the agent we send (the client's User-Agent), else
        `*`. A disallowed path is read only when the user allowed this
        plugin past this very file (`robots_consent`); a site that changed
        its file since is skipped until they look again. A refused file is never
        consented past: that is a site refusing us, not a rule."""
        if host not in self.robots:
            await self.limiter.wait()
            state, read = await read_robots(self.client, host)
            self.clock.progress()
            logger.info("plugin:%s robots %s -> %s (sha %s)", self.provider, host, state,
                        robots_sha(read)[:12] if read is not None else "none")
            if state == ROBOTS_FAILED:
                raise protocol.CallError(protocol.FETCH_FAILED, f"https://{host}/robots.txt could not be read")
            self.robots[host] = read
            if read is not None:
                self.robots_seen[host] = robots_sha(read)
        text = self.robots[host]
        if text is None:
            return f"https://{host}/robots.txt refused us; the host is treated as disallowing everything"
        agent = self.client.headers.get("user-agent", "*")
        allowed, rule = path_allowed(text, path, agent=agent)
        if allowed:
            return None
        assert rule is not None
        consented = self.robots_consent.get(host)
        if consented is not None and consented == self.robots_seen.get(host):
            logger.info("plugin:%s reads %s on %s past %s: %s (the user allowed it)",
                        self.provider, path, host, rule[0], rule[1])
            return None
        if consented is not None:
            return (f"robots.txt on {host} disallows {path} ({rule[0]}: {rule[1]}), and the site changed its "
                    f"robots rules since you allowed this plugin past them; review them in Settings > Plugins")
        return (f"robots.txt on {host} disallows {path} ({rule[0]}: {rule[1]}); the user can allow this plugin "
                f"past its sites' rules in Settings > Plugins")

    # -- writes -------------------------------------------------------------

    async def _company_known(self, slug: str) -> bool:
        if slug not in self.known:
            self.known[slug] = await writer.company_exists(self.db, slug)
        return self.known[slug]

    async def _publish(self, p: protocol.Publish) -> dict[str, Any]:
        known = await self._company_known(p.company)
        rows = policy.check_publish(
            self.manifest, self.job, p, company_known=lambda _slug: known, families=self.families
        )
        dumped = [r.model_dump() for r in rows]
        key = (p.slot, p.company)
        try:
            keys = await writer.write_batch(self.db, self.provider, p.slot, p.company, dumped)
            seen = self.batches.keys.get(key, set()) | keys
            # A complete publish closes the run's snapshot of the company in
            # this slot: the rows of this call and of every earlier
            # `complete=False` call this run are the whole. Its rows are read
            # from now (`complete_at`), and what the run did not publish for it
            # retires now, not at the end of a pass. Incomplete calls alone
            # read nothing and retire nothing.
            await store.note_coverage(self.db, provider=self.provider, slot=p.slot, company=p.company,
                                      rows=len(dumped), run_id=self.run_id, complete=p.complete)
            retired = (await writer.retire_unpublished(self.db, self.provider, p.slot, p.company, seen)
                       if p.complete else 0)
            await self.db.commit()
        except ValueError as exc:
            await self.db.rollback()
            raise protocol.CallError(protocol.INVALID, str(exc)) from None
        self.batches.keys[key] = seen
        self.batches.counts[p.slot] = self.batches.counts.get(p.slot, 0) + len(dumped)
        self.retired += retired
        return {"accepted": len(dumped)}

    async def _companies(self, _p: protocol.Companies) -> list[dict[str, str]]:
        policy.check_companies(self.job)
        rows = (
            await self.db.execute(
                select(TrackedCompany.slug, TrackedCompany.display)
                .where(TrackedCompany.enabled.is_(True))
                .order_by(TrackedCompany.slug)
            )
        ).all()
        return [{"slug": slug, "name": name} for slug, name in rows]

    async def _state_get(self, p: protocol.StateGet) -> dict[str, Any]:
        found, value = await store.state_get(self.db, self.provider, p.key)
        return {"found": found, "value": value}

    async def _state_set(self, p: protocol.StateSet) -> None:
        found, _ = await store.state_get(self.db, self.provider, p.key)
        if not found:
            policy.check_new_state_key(await store.state_keys(self.db, self.provider))
        await store.state_set(self.db, self.provider, p.key, p.value)
        await self.db.commit()

    async def _progress(self, p: protocol.Progress) -> None:
        await store.note_progress(self.db, self.run_id, p.done, p.total)
        await self.db.commit()

    async def _summary(self, p: protocol.Summary) -> None:
        await store.note_summary(self.db, self.run_id, p.text)
        await self.db.commit()

    async def _report(self, p: protocol.Report) -> None:
        if p.value is not None:
            policy.check_report(p, await store.report_keys(self.db, self.provider))
        await store.report_set(self.db, self.provider, p.key, p.value, p.label)
        await self.db.commit()

    async def _log(self, p: protocol.Log) -> None:
        logger.log(logging.getLevelName(p.level.upper()), "plugin:%s %s", self.provider, p.message)

    # -- end ----------------------------------------------------------------

    def outcome(self, end: Mapping[str, Any] | None) -> str:
        if self.failed:
            return "error"
        if self.ended:
            return self.ended
        if end is None or end.get("status") != "ok":
            return "error"
        return "partial" if self.refusals else "clean"


def _tail(path: Path, chars: int) -> str:
    """The end of a log the plugin wrote, read without loading the whole of it."""
    with path.open("rb") as handle:
        handle.seek(max(path.stat().st_size - chars * 4, 0))
        return handle.read().decode(errors="replace")[-chars:]


def _prune_logs(data_dir: Path, *, keep: int) -> None:
    """Keep the newest `keep` per-run stderr logs."""
    logs = sorted(data_dir.glob("run-*.stderr.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        with contextlib.suppress(OSError):
            old.unlink()


class _Stopped(Exception):
    """The user's stop arrived while the host waited for the plugin."""


async def _readline(stream: asyncio.StreamReader, timeout: float, stop: asyncio.Event | None = None) -> bytes:
    """The plugin's next line. `TimeoutError` after `timeout`; `_Stopped` as soon
    as `stop` is set, not at the plugin's next message: a plugin busy between
    calls (parsing, sleeping) would otherwise hold a Stop until the stall timeout."""
    read = asyncio.ensure_future(stream.readline())
    waits: list[asyncio.Future[Any]] = [read]
    if stop is not None:
        waits.append(asyncio.ensure_future(stop.wait()))
    try:
        done, _ = await asyncio.wait(waits, timeout=max(timeout, 0.01), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiting in waits:
            if not waiting.done():
                waiting.cancel()
    if read in done:
        return read.result()
    if len(waits) > 1 and waits[1] in done:
        raise _Stopped
    raise TimeoutError


async def _refused_run(db: AsyncSession, install: PluginInstall, job_name: str, *, trigger: str,
                       message: str) -> HostResult:
    """Record a run that never started, `error`, with the reason."""
    run = await store.open_run(db, install, job_name, trigger=trigger, pid=os.getpid())
    run_id = run.id
    await store.close_run(db, run_id, outcome="error", published={}, refusals=[], message=message)
    await db.commit()
    logger.warning("plugin:%s %s", install.plugin_id, message)
    return HostResult(run_id, "error", {}, [], 0, message)


async def _mark_reference(db: AsyncSession, plugin_id: str) -> None:
    """Record where the stored estimates go now that this run's publishes landed
    (`reestimate.begin`): its rows and how far it has read move the current set,
    so `/api/status` says estimates are updating from the run's end, not
    "settled" until the next idle re-estimate notices. Once per run, never per
    publish: each mark reads every pay row, and a new target restarts a
    re-estimate under way. A set the run did not move marks nothing. The run is
    already recorded, so a failure here is logged, and the idle re-estimate
    still finds the set moved."""
    try:
        await begin(db)
    except Exception:
        await db.rollback()
        logger.exception("plugin:%s could not mark the re-estimate target after its run", plugin_id)


async def run_job(
    db: AsyncSession,
    plugin_id: str,
    job_name: str,
    *,
    trigger: str,
    config: HostConfig,
    stop: asyncio.Event | None = None,
) -> HostResult:
    """Run `job_name` of `plugin_id` to its end and record it. Raises
    `NotRunnable` before anything starts when the plugin may not run."""
    install = await db.get(PluginInstall, plugin_id)
    if install is None:
        raise NotRunnable(f"no plugin {plugin_id!r} is installed")
    record = InstallRecord.of(install)
    if not record.runnable:
        raise NotRunnable(f"plugin {plugin_id!r} may not run: {_NOT_RUNNABLE[record.state]}")
    if config.verify_code and installed_code_sha(Path(install.source_dir)) != install.code_sha:
        # Recorded, never only raised: the user sees why, and the
        # schedule waits `RETRY_AFTER` instead of spawning it again every tick.
        return await _refused_run(db, install, job_name, trigger=trigger, message=(
            "its installed code changed on disk since it was installed and approved; it does not run "
            "until you reinstall it (scripts.plugin install) and approve it again"))
    try:
        manifest = accept(validate_manifest(install.manifest))
    except ManifestError as exc:
        # Accepted at install, refused now (an SDK bump, a tightened core rule):
        # the attempt is recorded, so the retry waits and the user sees why.
        return await _refused_run(db, install, job_name, trigger=trigger,
                                  message=f"the core no longer accepts this plugin's manifest: {exc}")
    try:
        job = manifest.job(job_name)
    except KeyError:
        raise NotRunnable(f"plugin {plugin_id!r} declares no job {job_name!r}") from None
    data_dir = config.data_dir or Path.cwd()
    # One run of a plugin at a time, whoever starts it (the scheduler, Sync,
    # Start, the CLI): the `running` row appears only once a host has started,
    # so two starts inside that window both pass the API's and the scheduler's
    # check. The second host stops here, before it records anything.
    with contextlib.ExitStack() as held:
        try:
            held.enter_context(run_lock(data_dir / RUN_LOCK))
        except AlreadyRunning:
            raise NotRunnable(f"plugin {plugin_id!r} is already running") from None
        return await _run_held(db, install, manifest, job, job_name, trigger=trigger, config=config,
                               data_dir=data_dir, stop=stop)


async def _run_held(
    db: AsyncSession,
    install: PluginInstall,
    manifest: PluginManifest,
    job: Job,
    job_name: str,
    *,
    trigger: str,
    config: HostConfig,
    data_dir: Path,
    stop: asyncio.Event | None,
) -> HostResult:
    """`run_job` once the plugin's run lock is held."""
    plugin_id = install.plugin_id
    run = await store.open_run(db, install, job_name, trigger=trigger, pid=os.getpid())
    await db.commit()
    run_id = run.id  # read once: a rollback below expires the row
    if config.on_open:
        config.on_open(run_id)

    own_client = config.client is None
    client = config.client or public_client(user_agent=get_settings().scraper_user_agent)
    session = _Session(db, install, manifest, job, run_id, config, client)
    data_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = data_dir / f"run-{run_id}.stderr.log"
    end: dict[str, Any] | None = None
    message: str | None = None
    with stderr_path.open("w") as stderr:
        spawn = config.spawn or asyncio.create_subprocess_exec
        proc = await spawn(
            *runner_command(config.python, config.pythonpath, manifest.plugin.entry, job_name),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
            cwd=RUN_CWD, env=runner_env(), limit=protocol.MAX_LINE_BYTES,
        )
        assert proc.stdin is not None and proc.stdout is not None
        try:
            start = {"type": "start", "protocol": PROTOCOL_VERSION, "run_id": str(run_id), "job": job_name,
                     "args": {}, "data_dir": str(data_dir),
                     # The job's own ceiling, not the stall window `remaining()` also counts.
                     "budget_seconds": max(session.clock.hard_deadline - config.clock(), 0.0)}
            proc.stdin.write(protocol.encode(start).encode())
            await proc.stdin.drain()
            while True:
                if stop is not None and stop.is_set():
                    session.stop_requested = True
                wait = min(session.clock.remaining(), session.stall_seconds)
                try:
                    line = await _readline(proc.stdout, wait, stop)
                except _Stopped:
                    session.ended = protocol.STOPPED
                    break
                except TimeoutError:
                    if session.clock.exhausted():
                        session.ended = protocol.BOUNDED
                        message = f"the {job.budget_seconds}s budget is spent"
                    elif stop is not None and stop.is_set():
                        session.ended = protocol.STOPPED
                    else:
                        message = f"the plugin sent nothing for {wait:.0f}s"
                    break
                if not line:
                    message = "the plugin exited without an end message"
                    break
                incoming = protocol.decode(line)
                if incoming["type"] == "end":
                    end = incoming
                    break
                reply = await session.handle(incoming)
                proc.stdin.write(protocol.encode(reply).encode())
                await proc.stdin.drain()
        except (protocol.ProtocolError, ConnectionError) as exc:
            message = f"protocol: {exc}"
        except Exception as exc:  # the host's own failure: the run still closes, saying why
            logger.exception("plugin:%s the host failed during run %s", plugin_id, run_id)
            await db.rollback()
            session.failed = True
            message = f"the host failed: {type(exc).__name__}: {exc}"
        finally:
            proc.stdin.close()
            send = config.send_signal or os.kill
            if session.ended == protocol.STOPPED:
                # The run is over for the user: end the runner now, whatever it
                # is doing; it holds no write of its own.
                with contextlib.suppress(ProcessLookupError):
                    send(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=config.exit_grace_seconds)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    send(proc.pid, signal.SIGKILL)
                await proc.wait()
            if own_client:
                await client.aclose()

    outcome = session.outcome(end)
    if message is None and end is not None:
        message = end.get("message")
    retired = session.retired
    await store.note_robots_seen(db, plugin_id, session.robots_seen)
    await store.close_run(db, run_id, outcome=outcome, published=session.batches.counts,
                          refusals=session.refusals, message=message, continues=bool((end or {}).get("more")))
    await db.commit()
    if session.batches.counts:
        await _mark_reference(db, plugin_id)
    stderr_text = _tail(stderr_path, 4000)
    _prune_logs(data_dir, keep=KEPT_RUN_LOGS)
    return HostResult(run_id, outcome, dict(session.batches.counts), list(session.refusals), retired, message,
                      stderr_text, continues=outcome in store.PASS_OUTCOMES and bool((end or {}).get("more")))
