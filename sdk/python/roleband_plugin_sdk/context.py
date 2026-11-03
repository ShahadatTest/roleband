"""What a job sees: `JobContext`, its responses, and the errors the host sends.

Every method is a call to the host. The host fetches, paces, enforces the
manifest and stores; the context only shapes requests and validates rows
before sending them, so a plugin bug fails at the line that caused it.

`RunEnded` derives from `BaseException`, like `KeyboardInterrupt`: a plugin
that catches `Exception` to skip one company must not swallow the end of its
own run.
"""

from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from . import protocol
from .slots import COMPANY_SLUG, MAX_ROWS_PER_PUBLISH, row_model


class HostError(Exception):
    """The host answered a call with an error. `code` is a protocol code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class Refused(HostError):
    """A policy said no: the manifest does not declare what was asked for."""


class RunEnded(BaseException):  # noqa: N818 (a control-flow signal, like KeyboardInterrupt)
    """The host ended the run: its budget is spent (`bounded`) or it was stopped."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def raise_for(reply: Mapping[str, Any]) -> Any:
    """The result of a reply, or the error it carries, raised."""
    if reply.get("ok"):
        return reply.get("result")
    error = reply.get("error") or {}
    code = str(error.get("code", protocol.INTERNAL))
    message = str(error.get("message", ""))
    if code in protocol.TERMINAL_CODES:
        raise RunEnded(code, message)
    if code == protocol.REFUSED:
        raise Refused(code, message)
    raise HostError(code, message)


T = TypeVar("T")

_PASS_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


@dataclass
class Pass:
    """What one run did of a pass (`JobContext.resume`)."""

    #: Units this run went through, read or failed.
    done: int = 0
    #: Keys of the units that failed; each was logged, and the pass moved on.
    failed: list[str] = field(default_factory=list)
    #: The pass reached its last unit; the next run starts a new one.
    finished: bool = False


class Transport(Protocol):
    def call(self, method: str, params: dict[str, Any]) -> Any:
        """Send one call and return its result, raising what `raise_for` raises."""
        ...


@dataclass(frozen=True)
class Company:
    slug: str
    name: str


@dataclass(frozen=True)
class Response:
    status: int
    url: str
    headers: Mapping[str, str]
    content: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        msg = Message()
        msg["content-type"] = self.headers.get("content-type", "")
        charset = msg.get_content_charset() or "utf-8"
        return self.content.decode(charset, errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


@dataclass
class State:
    """The plugin's own small key/value store, kept by the host between runs."""

    _transport: Transport = field(repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        result = self._transport.call("state.get", {"key": key})
        return result["value"] if result.get("found") else default

    def set(self, key: str, value: Any) -> None:
        self._transport.call("state.set", {"key": key, "value": value})


class JobContext:
    """The handle a job function receives."""

    def __init__(
        self,
        transport: Transport,
        *,
        job: str,
        run_id: str,
        args: Mapping[str, Any] | None = None,
        data_dir: str | Path | None = None,
        budget_seconds: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._transport = transport
        self.job = job
        self.run_id = run_id
        self.args: Mapping[str, Any] = dict(args or {})
        #: The plugin's own data directory (a local import reads from here).
        self.data_dir = Path(data_dir) if data_dir else None
        self.state = State(transport)
        self._budget = budget_seconds
        self._clock = clock or time.monotonic
        self._started = self._clock()
        #: The job stopped with its pass unfinished: the end message says `more`,
        #: and the host continues the pass in a run soon. `resume` sets it.
        self.more = False

    def time_left(self) -> float | None:
        """Seconds of this run's budget left; None when the host did not say.
        The host ends the run `bounded` at zero."""
        if self._budget is None:
            return None
        return max(self._budget - (self._clock() - self._started), 0.0)

    def resume(
        self,
        name: str,
        units: Iterable[T],
        run: Callable[[T], None],
        *,
        key: Callable[[T], str],
        margin: float = 120.0,
    ) -> Pass:
        """Go through `units` across as many runs as it takes, one pass at a time.

        Units are taken in `key` order, after the cursor this pass left in
        `ctx.state` (`resume.<name>`), which is saved after each unit. A unit whose
        `run` raises anything but the end of the run is logged, counted in
        `Pass.failed`, and passed over, so one bad unit never stops a plugin. When
        less than `margin` seconds of the budget are left, the job stops at a unit
        boundary and says `more`: the run ends clean and the host continues the
        pass soon (what it published whole was read at each publish). At the last unit the
        cursor is cleared, so the next run starts a new pass. A run the host ends
        (`RunEnded`) keeps the cursor before the unit it interrupted."""
        if not _PASS_NAME.match(name):
            raise ValueError(f"{name!r} is not a pass name: letters, digits and _.:- only")
        cursor_key = f"resume.{name}"
        ordered = sorted(units, key=key)
        after = self.state.get(cursor_key)
        todo = [u for u in ordered if after is None or key(u) > after]
        result = Pass()
        position = len(ordered) - len(todo)
        for unit in todo:
            left = self.time_left()
            if left is not None and left < margin:
                self.more = True
                return result
            unit_key = key(unit)
            try:
                run(unit)
            except Exception as exc:  # one unit failing is not the pass failing; RunEnded is not an Exception
                result.failed.append(unit_key)
                detail = exc.message if isinstance(exc, HostError) else f"{type(exc).__name__}: {exc}"
                self.log(f"{name}: {unit_key} skipped: {detail}"[:2000], level="warning")
            self.state.set(cursor_key, unit_key)
            result.done += 1
            position += 1
            self.progress(position, len(ordered))
        self.state.set(cursor_key, None)
        self.more = False
        result.finished = True
        return result

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> Response:
        """GET `url` through the host. Any status comes back as a `Response`;
        the host refuses a host or header the manifest does not allow."""
        result = self._transport.call("http.get", {"url": url, "headers": dict(headers or {})})
        return Response(
            status=int(result["status"]),
            url=str(result["url"]),
            headers={str(k).lower(): str(v) for k, v in (result.get("headers") or {}).items()},
            content=base64.b64decode(result.get("body_b64") or ""),
        )

    def publish(
        self,
        slot: str,
        *,
        company: str,
        rows: Iterable[BaseModel | Mapping[str, Any]],
        complete: bool = True,
    ) -> int:
        """Publish one company's rows into one slot.

        `complete=True` closes this run's snapshot of the company in this slot:
        the rows of this call and of every earlier `complete=False` call for it
        this run are ALL its rows. The host reads them from this publish, and
        retires the provider's rows for the company that this run did not
        publish, whatever the run's end; a run stopped later keeps it.

        `complete=False` leaves the snapshot open. A run whose calls for the
        company in the slot are all `complete=False` is a partial read: nothing
        is read whole and nothing retires.

        A snapshot larger than `MAX_ROWS_PER_PUBLISH` rows goes in chunks:
        every chunk but the last with `complete=False`, the last with
        `complete=True`.
        """
        model = row_model(slot)
        if not COMPANY_SLUG.match(company):
            raise ValueError(f"{company!r} is not a company slug")
        wire = []
        for row in rows:
            if isinstance(row, BaseModel) and not isinstance(row, model):
                raise TypeError(f"{slot} takes {model.__name__} rows, not {type(row).__name__}")
            valid = row if isinstance(row, model) else model.model_validate(row)
            wire.append(valid.model_dump(mode="json"))
        if len(wire) > MAX_ROWS_PER_PUBLISH:
            raise ValueError(f"{len(wire)} rows in one publish; the limit is {MAX_ROWS_PER_PUBLISH}")
        result = self._transport.call(
            "publish", {"slot": slot, "company": company, "rows": wire, "complete": complete}
        )
        return int(result["accepted"])

    def companies(self) -> list[Company]:
        """The companies the user follows. Only for a job that `needs` them."""
        result = self._transport.call("companies", {})
        return [Company(slug=c["slug"], name=c["name"]) for c in result]

    def progress(self, done: int, total: int | None = None) -> None:
        self._transport.call("progress", {"done": done, "total": total})

    def log(self, message: str, *, level: str = "info") -> None:
        self._transport.call("log", {"level": level, "message": message})

    def report(self, key: str, value: int | None, label: str) -> None:
        """Show the user a number beside the plugin, such as how many
        followed companies the source does not have. `label` is the plugin's
        own words for what the number counts, shown as written after it; the
        host keeps the latest value per `key` with the time it was reported,
        across runs and updates. `value=None` withdraws it. At most
        `protocol.MAX_REPORTS` keys."""
        self._transport.call("report", {"key": key, "value": value, "label": label})

    def summary(self, text: str) -> None:
        """Say what this run has done so far, in the plugin's own words, such
        as "Read pay for 56 of 1,180 companies". Settings shows the
        latest one beside the plugin, as written, after the host's own words for
        how the run ended and when; call it as the run goes, so a run the host
        stops still has one. At most `protocol.MAX_SUMMARY_CHARS`."""
        self._transport.call("summary", {"text": text})
