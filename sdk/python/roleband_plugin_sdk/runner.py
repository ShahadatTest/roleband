"""The plugin process: `python -m roleband_plugin_sdk.runner --entry M:A --job NAME`.

The host starts this inside the plugin's venv, isolated (`python -I`, its path
given by the host; the plugin's data directory is never on it), writes one
`start` line, then answers calls until the runner writes `end`. Before the
plugin is imported, file descriptor 1 is pointed at stderr and the protocol
keeps a private copy of the original stdout, so neither a `print()` nor a
child process can write a line the host would read as a message.

Exit status: 0 when the job returned, 1 when it failed or the run ended
early, 2 when the protocol itself broke.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import IO, Any

from . import protocol
from .context import JobContext, raise_for
from .plugin import execute, resolve_entry
from .version import PROTOCOL_VERSION


class StdioTransport:
    """Calls over the runner's two protocol streams, answered in order."""

    def __init__(self, reader: IO[str], writer: IO[str]) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 0

    def send(self, message: dict[str, Any]) -> None:
        self._writer.write(protocol.encode(message))
        self._writer.flush()

    def call(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        call_id = self._next_id
        self.send({"type": "call", "id": call_id, "method": method, "params": params})
        reply = protocol.decode(self._reader.readline(protocol.MAX_LINE_BYTES))
        if reply.get("type") != "reply" or reply.get("id") != call_id:
            raise protocol.ProtocolError(f"expected the reply to call {call_id}, got {reply!r:.200}")
        return raise_for(reply)


def _protocol_streams() -> tuple[IO[str], IO[str]]:
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return sys.stdin, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roleband_plugin_sdk.runner")
    parser.add_argument("--entry", required=True, help="module:attribute naming the Plugin")
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)

    reader, writer = _protocol_streams()
    transport = StdioTransport(reader, writer)
    try:
        start = protocol.decode(reader.readline(protocol.MAX_LINE_BYTES))
    except protocol.ProtocolError as exc:
        transport.send({"type": "end", "status": "error", "message": f"no start message: {exc}"})
        return 2
    if start.get("type") != "start" or start.get("protocol") != PROTOCOL_VERSION:
        transport.send(
            {
                "type": "end",
                "status": "error",
                "message": f"this runner speaks protocol {PROTOCOL_VERSION}, "
                f"the host sent {start.get('type')!r} protocol {start.get('protocol')!r}",
            }
        )
        return 2
    if start.get("job") != args.job:
        transport.send({"type": "end", "status": "error", "message": "start names a different job"})
        return 2

    try:
        fn = resolve_entry(args.entry).jobs[args.job]
    except Exception as exc:  # an entry that does not load is the plugin's failure
        transport.send({"type": "end", "status": "error", "message": f"cannot load {args.entry}: {exc}"})
        return 1

    ctx = JobContext(
        transport,
        job=args.job,
        run_id=str(start.get("run_id", "")),
        args=start.get("args") or {},
        data_dir=start.get("data_dir"),
        budget_seconds=start.get("budget_seconds"),
    )
    end = execute(fn, ctx)
    transport.send(end)
    return 0 if end["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
