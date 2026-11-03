"""The stdio protocol between a plugin process and the host.

One JSON object per line. The plugin's stdout carries only these lines; the
runner points everything a plugin prints at stderr.

    host -> plugin   {"type": "start", "protocol": 1, "run_id": ..., "job": ...,
                      "args": {...}, "data_dir": str | null,
                      "budget_seconds": float | null}
    plugin -> host   {"type": "call", "id": N, "method": ..., "params": {...}}
    host -> plugin   {"type": "reply", "id": N, "ok": true, "result": ...}
                     {"type": "reply", "id": N, "ok": false,
                      "error": {"code": ..., "message": ...}}
    plugin -> host   {"type": "end", "status": "ok" | "error" | "bounded" | "stopped",
                      "message": str | null, "more": bool}

Calls are answered in order, one at a time. The host decides the run's
outcome; `end` is only the plugin's account of how its job returned. `more`
says the job stopped at a unit boundary with its pass unfinished
(`JobContext.resume`): the host continues the pass in a run soon.

A method added in a later minor SDK version is one an older host does not
know: a plugin calling it declares an `sdk` range from that version, which an
older core refuses at install.

Fields added in a minor SDK version are optional on both sides: a side that
does not know one ignores it, so the protocol stays 1.

`parse_call` is the host side's validation of a call, used by the SDK's fake
host and by the core's host alike, so the two cannot drift.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

METHODS = ("http.get", "publish", "companies", "state.get", "state.set", "progress", "log", "report", "summary")
END_STATUSES = ("ok", "error", "bounded", "stopped")

#: A policy said no: an undeclared slot, host, header or need.
REFUSED = "refused"
#: The call or its rows failed validation on the host.
INVALID = "invalid"
#: The host could not complete the request (DNS, TLS, timeout).
FETCH_FAILED = "fetch_failed"
#: The run's budget is spent. Every later call gets the same answer.
BOUNDED = "bounded"
#: The host stopped the run (a disable, a quit). Every later call gets the same answer.
STOPPED = "stopped"
#: The fake host has no recorded response for a URL. Never sent by the real host.
NO_FIXTURE = "no_fixture"
#: The host failed on its own side.
INTERNAL = "internal"

#: Ends the run: the SDK raises these past `except Exception`.
TERMINAL_CODES = frozenset({BOUNDED, STOPPED})

#: Request headers a plugin may set. The host sets its own identity; a plugin
#: never names a User-Agent.
ALLOWED_REQUEST_HEADERS = frozenset({"accept", "accept-language", "if-none-match", "if-modified-since"})

MAX_LINE_BYTES = 64 * 1024 * 1024
MAX_STATE_BYTES = 64 * 1024
#: Keys one plugin may keep in its state; a cursor is one key, not one per unit.
MAX_STATE_KEYS = 10_000
#: Numbers one plugin may report at once (`report`).
MAX_REPORTS = 8
#: How long a run's summary may be (`summary`): one line beside the plugin's name.
MAX_SUMMARY_CHARS = 160


class ProtocolError(Exception):
    """A line that is not a protocol message."""


class CallError(Exception):
    """A call the host must refuse; `code` is one of the codes above."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def encode(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def decode(line: str | bytes) -> dict[str, Any]:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    if not line.strip():
        raise ProtocolError("empty line (the other side closed the stream)")
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"not JSON: {exc}") from None
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("a message is a JSON object with a string 'type'")
    return message


def reply_ok(call_id: int, result: Any) -> dict[str, Any]:
    return {"type": "reply", "id": call_id, "ok": True, "result": result}


def reply_error(call_id: int, code: str, message: str) -> dict[str, Any]:
    return {"type": "reply", "id": call_id, "ok": False, "error": {"code": code, "message": message}}


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpGet(_Params):
    url: Annotated[StrictStr, Field(min_length=1, max_length=4000)]
    headers: dict[StrictStr, StrictStr] = Field(default_factory=dict)


class Publish(_Params):
    slot: StrictStr
    company: StrictStr
    rows: list[dict[str, Any]] = Field(max_length=5000)
    complete: StrictBool


class Companies(_Params):
    pass


class StateGet(_Params):
    key: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]


class StateSet(_Params):
    key: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
    value: Any


class Progress(_Params):
    done: Annotated[StrictInt, Field(ge=0)]
    total: Annotated[StrictInt, Field(ge=0)] | None = None


class Log(_Params):
    level: Literal["debug", "info", "warning", "error"]
    message: Annotated[StrictStr, Field(max_length=2000)]


class Report(_Params):
    """A number the plugin wants the user to see beside it: `value` with
    the plugin's own words for it; `value=None` withdraws the report."""

    key: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
    value: Annotated[StrictInt, Field(ge=0)] | None
    label: Annotated[StrictStr, Field(min_length=1, max_length=160)]


class Summary(_Params):
    """What this run has done so far, in the plugin's own words: the
    latest one stands for the run, so a run the host stops keeps its last."""

    text: Annotated[StrictStr, Field(min_length=1, max_length=MAX_SUMMARY_CHARS)]


PARAMS: dict[str, type[_Params]] = {
    "http.get": HttpGet,
    "publish": Publish,
    "companies": Companies,
    "state.get": StateGet,
    "state.set": StateSet,
    "progress": Progress,
    "log": Log,
    "report": Report,
    "summary": Summary,
}


def parse_call(message: dict[str, Any]) -> tuple[int, str, _Params]:
    """A `call` message as (id, method, params). Raises `ProtocolError` when
    the message has no usable id (nothing can be replied to), else `CallError`."""
    call_id = message.get("id")
    if message.get("type") != "call" or type(call_id) is not int:
        raise ProtocolError("expected a call with an integer id")
    method = message.get("method")
    if method not in PARAMS:
        raise CallError(INVALID, f"unknown method {method!r}")
    try:
        params = PARAMS[method].model_validate(message.get("params") or {})
    except ValidationError as exc:
        raise CallError(INVALID, f"{method}: {exc.errors()[0]['msg']}") from None
    if isinstance(params, StateSet):
        try:
            size = len(json.dumps(params.value, allow_nan=False).encode())
        except (TypeError, ValueError):
            raise CallError(INVALID, "state values are plain JSON") from None
        if size > MAX_STATE_BYTES:
            raise CallError(INVALID, f"state value is {size} bytes; the limit is {MAX_STATE_BYTES}")
    if isinstance(params, Progress) and params.total is not None and params.done > params.total:
        raise CallError(INVALID, "progress done exceeds total")
    return call_id, method, params
