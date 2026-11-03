"""`FakeHost`: run a plugin's job in a test, under the host's rules, offline.

The fake host enforces what the real one does: declared slots per job,
declared hosts, allowed headers, the identified client only, `needs`, known
companies, taxonomy families, robots (when a test records them), row
validation on its own side, the caps on state keys and reports, one stored row
per key (`RunResult.rows`), and the job's budget on a simulated clock: each
request costs the pacing the real host applies (the manifest's delay, never
less than the core's, `policy.pacing_delay`) plus the recorded latency, and
`ctx.time_left()` reads that clock. It never touches the network: a URL with
no recorded response is a `no_fixture` error, so a test cannot pass by
fetching live.

What it does not reproduce: retries and `Retry-After` waits, the stall
timeout, and the store itself; `RunResult.retires` says what the host would
retire instead (at each whole publish, whatever the run's end).

Every message crosses the wire format: in process, each call and reply is
encoded and decoded as JSON; with `subprocess=True` the job runs in a real
`roleband_plugin_sdk.runner` process over stdio, started by the host's own
command (`launch.runner_command`): isolated, in `/`, with only the SDK and the
plugin's code on its path and a data directory of its own. So a relative path
or an import the plugin does not ship fails here as it fails live.

    host = FakeHost("path/to/plugin", companies=["acme"],
                    responses={"https://data.example.com/acme.json": FakeResponse(body={...})})
    result = host.run("refresh")
    assert result.outcome == "clean"
    assert result.rows("pay.levels", "acme")
"""

from __future__ import annotations

import base64
import json
import queue
import subprocess as sp
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from roleband_robots import path_allowed, target_for

from . import policy, protocol
from .context import JobContext, raise_for
from .launch import RUN_CWD, code_root, runner_command, runner_env
from .manifest import Job, ManifestError, PluginManifest, load_manifest, spec_admits
from .plugin import Plugin, execute, resolve_entry
from .slots import RETIRING_SLOTS, ROW_KEYS, TAXONOMY_FAMILIES
from .version import PROTOCOL_VERSION, SDK_VERSION

#: The agent the real host fetches as (`config.scraper_user_agent`). Robots
#: groups are selected by it, so a fake host reading `*` would answer a
#: different question than the one the live fetch asks.
DEFAULT_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


@dataclass(frozen=True)
class FakeResponse:
    """A recorded response. `body` may be bytes, text, or JSON-able data."""

    status: int = 200
    body: bytes | str | dict[str, Any] | list[Any] = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    #: Simulated seconds the request takes, on top of the manifest's delay.
    latency: float = 0.0
    #: Set to make the request fail on the host side (DNS, TLS, timeout).
    fetch_error: str | None = None

    def content(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        if isinstance(self.body, str):
            return self.body.encode()
        return json.dumps(self.body).encode()


@dataclass(frozen=True)
class Batch:
    slot: str
    company: str
    rows: tuple[BaseModel, ...]
    complete: bool


@dataclass
class RunResult:
    #: clean | partial | bounded | stopped | error, as the host would record it.
    outcome: str
    published: list[Batch]
    requests: list[str]
    refusals: list[str]
    progress: list[tuple[int, int | None]]
    logs: list[tuple[str, str]]
    state: dict[str, Any]
    message: str | None = None
    stderr: str = ""
    #: The job stopped with its pass unfinished (`ctx.resume`): the host would
    #: continue it in a run soon.
    more: bool = False
    #: The numbers the host keeps after this run (`ctx.report`): the ones a
    #: test passed in as kept before it, then the latest `(value, label)` per
    #: key this run reported, a withdrawn key gone.
    reports: dict[str, tuple[int, str]] = field(default_factory=dict)
    #: The run's latest summary (`ctx.summary`), as the host would keep it.
    summary: str | None = None

    @property
    def retires(self) -> set[tuple[str, str]]:
        """(slot, company) pairs the host reads from this run and whose rows not
        published it retires: published complete at least once, which closes
        the run's snapshot over that call and every earlier `complete=False`
        one, in a slot that retires, whatever the run's end (the host does it
        at the publish)."""
        return {(b.slot, b.company) for b in self.published if b.complete and b.slot in RETIRING_SLOTS}

    def rows(self, slot: str, company: str | None = None) -> list[Any]:
        """The rows the host would store from this run: one per key
        (`slots.ROW_KEYS`), the latest under a retiring slot's key and the
        first under history's, as the core's upsert and insert-or-skip do.
        `published` keeps every row as it was sent."""
        fields = ROW_KEYS.get(slot)
        sent = [(b.company, row) for b in self.published if b.slot == slot for row in b.rows]
        if fields:
            kept: dict[tuple[Any, ...], tuple[str, Any]] = {}
            for owner, row in sent:
                key = tuple(owner if f == "company" else getattr(row, f) for f in fields)
                if key not in kept or slot in RETIRING_SLOTS:
                    kept[key] = (owner, row)
            sent = list(kept.values())
        return [row for owner, row in sent if company is None or owner == company]


class _Session:
    """The host side of one run: answers calls, keeps the clock, records everything."""

    def __init__(self, host: FakeHost, job: Job) -> None:
        self.host = host
        self.job = job
        self.clock = 0.0
        self.budget = host.budget_seconds if host.budget_seconds is not None else job.budget_seconds
        self.calls = 0
        self.ended: str | None = None
        self.result = RunResult("error", [], [], [], [], [], dict(host.state), reports=dict(host.reports))

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        try:
            call_id, method, params = protocol.parse_call(message)
        except protocol.CallError as exc:
            return self._refuse(int(message["id"]), exc.code, exc.message)
        if self.ended:
            return protocol.reply_error(call_id, self.ended, f"the run is {self.ended}")
        self.calls += 1
        stop_after = self.host.stop_after_calls
        if stop_after is not None and self.calls > stop_after:
            self.ended = protocol.STOPPED
            return protocol.reply_error(call_id, protocol.STOPPED, "the host stopped the run")
        try:
            return protocol.reply_ok(call_id, getattr(self, "_" + method.replace(".", "_"))(params))
        except protocol.CallError as exc:
            return self._refuse(call_id, exc.code, exc.message)

    def _refuse(self, call_id: int, code: str, message: str) -> dict[str, Any]:
        if code in protocol.TERMINAL_CODES:
            self.ended = code
        else:
            self.result.refusals.append(f"{code}: {message}")
        return protocol.reply_error(call_id, code, message)

    def _check_robots(self, host: str, url: str) -> None:
        """Refuse what the real host refuses, by the same rules.

        Matched on path AND query, because a directive may name a query; the
        agent is the one the host fetches as; and a host that refused its
        robots file disallows everything rather than nothing.

        Consent is deliberately absent. The real host may read a disallowed
        path when the USER allowed this plugin past a robots file they were
        shown, recorded against that file's sha. That is an install-time fact
        about a person, not something a plugin's own tests can grant
        themselves, so a test that needs it would be asserting permission it
        will not have.
        """
        if host not in self.host.robots:
            return
        text = self.host.robots[host]
        if text is None:
            raise protocol.CallError(
                protocol.REFUSED,
                f"https://{host}/robots.txt refused us; the host is treated as disallowing everything",
            )
        target = target_for(url)
        allowed, rule = path_allowed(text, target, agent=self.host.agent)
        if not allowed:
            assert rule is not None
            raise protocol.CallError(
                protocol.REFUSED, f"robots.txt on {host} disallows {target} ({rule[0]}: {rule[1]})"
            )

    def _http_get(self, p: protocol.HttpGet) -> dict[str, Any]:
        manifest = self.host.manifest
        host = policy.check_get(manifest, p)
        policy.check_identity(manifest)
        self._check_robots(host, p.url)
        response = self.host.responses.get(p.url)
        self.clock += policy.pacing_delay(manifest, self.host.core_delay) + (response.latency if response else 0.0)
        if self.clock > self.budget:
            raise protocol.CallError(protocol.BOUNDED, f"the {self.budget}s budget is spent")
        self.result.requests.append(p.url)
        if response is None:
            raise protocol.CallError(protocol.NO_FIXTURE, f"no recorded response for {p.url}")
        if response.fetch_error:
            raise protocol.CallError(protocol.FETCH_FAILED, response.fetch_error)
        return {
            "status": response.status,
            "url": p.url,
            "headers": {k.lower(): v for k, v in response.headers.items()},
            "body_b64": base64.b64encode(response.content()).decode(),
        }

    def _publish(self, p: protocol.Publish) -> dict[str, Any]:
        rows = policy.check_publish(
            self.host.manifest,
            self.job,
            p,
            company_known=lambda slug: slug in self.host.companies,
            families=self.host.families,
        )
        self.result.published.append(Batch(p.slot, p.company, tuple(rows), p.complete))
        return {"accepted": len(rows)}

    def _companies(self, _p: protocol.Companies) -> list[dict[str, str]]:
        policy.check_companies(self.job)
        return [{"slug": s, "name": self.host.companies[s]} for s in self.host.followed]

    def _state_get(self, p: protocol.StateGet) -> dict[str, Any]:
        if p.key in self.result.state:
            return {"found": True, "value": self.result.state[p.key]}
        return {"found": False, "value": None}

    def _state_set(self, p: protocol.StateSet) -> None:
        if p.key not in self.result.state:
            policy.check_new_state_key(len(self.result.state))
        self.result.state[p.key] = p.value

    def _progress(self, p: protocol.Progress) -> None:
        self.result.progress.append((p.done, p.total))

    def _log(self, p: protocol.Log) -> None:
        self.result.logs.append((p.level, p.message))

    def _report(self, p: protocol.Report) -> None:
        reports = self.result.reports
        policy.check_report(p, reports)
        if p.value is None:
            reports.pop(p.key, None)
            return
        reports[p.key] = (p.value, p.label)

    def _summary(self, p: protocol.Summary) -> None:
        self.result.summary = p.text

    def finish(self, end: dict[str, Any] | None, stderr: str = "") -> RunResult:
        r = self.result
        r.stderr = stderr
        status = (end or {}).get("status")
        r.message = (end or {}).get("message") or (None if end else "the plugin exited without an end message")
        r.more = bool((end or {}).get("more"))
        if self.ended:
            r.outcome = self.ended
        elif status == "ok":
            r.outcome = "partial" if r.refusals else "clean"
        else:
            r.outcome = "error"
        return r


class _Loopback:
    """In-process transport: every message is encoded and decoded as on the wire."""

    def __init__(self, session: _Session) -> None:
        self.session = session
        self.next_id = 0

    def call(self, method: str, params: dict[str, Any]) -> Any:
        self.next_id += 1
        line = protocol.encode({"type": "call", "id": self.next_id, "method": method, "params": params})
        reply = self.session.handle(protocol.decode(line))
        return raise_for(protocol.decode(protocol.encode(reply)))


def _pump(stream: Any, lines: queue.Queue[str]) -> None:
    """Every line of `stream`, then "" at its end."""
    for line in iter(lambda: stream.readline(protocol.MAX_LINE_BYTES), ""):
        lines.put(line)
    lines.put("")


class FakeHost:
    def __init__(
        self,
        manifest: PluginManifest | str | Path,
        *,
        responses: Mapping[str, FakeResponse] | None = None,
        companies: Iterable[str] | Mapping[str, str] = (),
        followed: Iterable[str] | None = None,
        families: Iterable[str] | None = None,
        state: Mapping[str, Any] | None = None,
        reports: Mapping[str, tuple[int, str]] | None = None,
        stop_after_calls: int | None = None,
        core_delay: float = policy.CORE_MIN_DELAY_SECONDS,
        budget_seconds: float | None = None,
        robots: Mapping[str, str | None] | None = None,
        agent: str = DEFAULT_AGENT,
        code: str | Path | None = None,
    ) -> None:
        self.manifest = manifest if isinstance(manifest, PluginManifest) else load_manifest(manifest)
        #: Where a subprocess run imports the plugin from: `code`, else the
        #: manifest's own directory, `src/` in it when it has one.
        tree = Path(code) if code is not None else (
            None if isinstance(manifest, PluginManifest)
            else Path(manifest) if Path(manifest).is_dir() else Path(manifest).parent
        )
        self.code_root = code_root(tree) if tree is not None else None
        if not spec_admits(self.manifest.plugin.sdk, SDK_VERSION):
            raise ManifestError([f"plugin.sdk: {self.manifest.plugin.sdk!r} does not admit SDK {SDK_VERSION}"])
        self.responses = dict(responses or {})
        self.companies = dict(companies) if isinstance(companies, Mapping) else {c: c for c in companies}
        self.followed = list(followed) if followed is not None else list(self.companies)
        unknown = sorted(set(self.followed) - set(self.companies))
        if unknown:
            raise ValueError(f"followed companies {unknown} are not in companies")
        #: Taxonomy families `pay.levels` rows may name: the core's, unless a test names its own.
        self.families = frozenset(families if families is not None else TAXONOMY_FAMILIES)
        self.state = dict(state or {})
        #: Numbers earlier runs reported, as `RunResult.reports` gives them:
        #: the host keeps them across runs, and they count toward the cap.
        self.reports = dict(reports or {})
        self.stop_after_calls = stop_after_calls
        #: The core's request delay; the real host paces no plugin faster.
        self.core_delay = core_delay
        #: A budget for this run instead of the job's (a pass split across runs).
        self.budget_seconds = budget_seconds
        #: robots.txt per host, as recorded. A host with none recorded allows
        #: all; a host recorded as None is one that REFUSED its robots file
        #: (401, 403, 5xx), which the real host treats as disallowing
        #: everything rather than as stating no rule.
        self.robots: dict[str, str | None] = {
            host.lower(): text for host, text in (robots or {}).items()
        }
        #: The agent whose rules apply. The real host matches the User-Agent it
        #: sends, so a group naming it wins over `*`; a test that pins another
        #: agent is testing another crawler's rules.
        self.agent = agent

    def _check_jobs(self, plugin: Plugin) -> None:
        declared = {j.name for j in self.manifest.jobs}
        if set(plugin.jobs) != declared:
            raise ManifestError(
                [f"the plugin registers jobs {sorted(plugin.jobs)} but the manifest declares {sorted(declared)}"]
            )

    def run(
        self,
        job: str,
        plugin: Plugin | None = None,
        *,
        args: Mapping[str, Any] | None = None,
        data_dir: str | Path | None = None,
        subprocess: bool = False,
        timeout: float = 60.0,
    ) -> RunResult:
        spec = self.manifest.job(job)
        session = _Session(self, spec)
        if subprocess:
            if plugin is not None:
                raise ValueError("a subprocess run loads the plugin from the manifest's entry")
            if self.code_root is None:
                raise ValueError("a subprocess run imports the plugin from its directory: give FakeHost the "
                                 "manifest's path, or `code=`")
            self._check_jobs(resolve_entry(self.manifest.plugin.entry))
            return self._run_process(session, job, args, data_dir, timeout, self.code_root)
        plugin = plugin or resolve_entry(self.manifest.plugin.entry)
        self._check_jobs(plugin)
        ctx = JobContext(_Loopback(session), job=job, run_id="fake-run", args=args, data_dir=data_dir,
                         budget_seconds=session.budget, clock=lambda: session.clock)
        end = protocol.decode(protocol.encode(execute(plugin.jobs[job], ctx)))
        return session.finish(end)

    def _run_process(
        self,
        session: _Session,
        job: str,
        args: Mapping[str, Any] | None,
        data_dir: str | Path | None,
        timeout: float,
        code: Path,
    ) -> RunResult:
        sdk = Path(__file__).resolve().parent.parent
        cmd = runner_command(sys.executable, [sdk, code], self.manifest.plugin.entry, job)
        deadline = time.monotonic() + timeout
        end = None
        with tempfile.TemporaryFile("w+") as err, tempfile.TemporaryDirectory() as scratch:
            # The real host always sends a data directory.
            start = {
                "type": "start",
                "protocol": PROTOCOL_VERSION,
                "run_id": "fake-run",
                "job": job,
                "args": dict(args or {}),
                "data_dir": str(data_dir) if data_dir else scratch,
                "budget_seconds": session.budget,
            }
            proc = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=err, text=True, cwd=RUN_CWD, env=runner_env())
            assert proc.stdin is not None and proc.stdout is not None
            # A thread reads the runner's lines, so the wait for the next one
            # has a timeout on every platform (`select` takes no pipe on Windows).
            lines: queue.Queue[str] = queue.Queue()
            reader = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
            reader.start()
            try:
                proc.stdin.write(protocol.encode(start))
                proc.stdin.flush()
                while True:
                    try:
                        line = lines.get(timeout=max(deadline - time.monotonic(), 0))
                    except queue.Empty:
                        proc.kill()
                        raise TimeoutError(f"the plugin process did not finish within {timeout}s") from None
                    if not line:
                        break
                    message = protocol.decode(line)
                    if message["type"] == "end":
                        end = message
                        break
                    proc.stdin.write(protocol.encode(session.handle(message)))
                    proc.stdin.flush()
            finally:
                proc.stdin.close()
                proc.wait(timeout=10)
            err.seek(0)
            return session.finish(end, stderr=err.read())
