"""`Plugin`: the object a manifest's `entry` names, holding the plugin's jobs."""

from __future__ import annotations

import importlib
import traceback
from collections.abc import Callable, Mapping
from typing import Any

from .context import JobContext, RunEnded

JobFunction = Callable[[JobContext], None]


class Plugin:
    """Register jobs with `@plugin.job("refresh")`. Each name must match a
    `[[jobs]]` entry in the manifest, and every manifest job must be here."""

    def __init__(self, plugin_id: str | None = None) -> None:
        self.id = plugin_id
        self._jobs: dict[str, JobFunction] = {}

    def job(self, name: str) -> Callable[[JobFunction], JobFunction]:
        def register(fn: JobFunction) -> JobFunction:
            if name in self._jobs:
                raise ValueError(f"job {name!r} is registered twice")
            self._jobs[name] = fn
            return fn

        return register

    @property
    def jobs(self) -> Mapping[str, JobFunction]:
        return dict(self._jobs)


def resolve_entry(entry: str) -> Plugin:
    """The `Plugin` that `module:attribute` names."""
    module_name, _, attr = entry.partition(":")
    obj = getattr(importlib.import_module(module_name), attr)
    if not isinstance(obj, Plugin):
        raise TypeError(f"{entry} is a {type(obj).__name__}, not a roleband_plugin_sdk.Plugin")
    return obj


def execute(fn: JobFunction, ctx: JobContext) -> dict[str, Any]:
    """Run one job and return the `end` message describing how it returned.

    The runner and the fake host both end a run through here."""
    try:
        fn(ctx)
    except RunEnded as ended:
        return {"type": "end", "status": ended.code, "message": ended.message}
    except Exception as exc:  # the job's own failure; the host records it
        tail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return {"type": "end", "status": "error", "message": tail[:2000]}
    return {"type": "end", "status": "ok", "message": None, "more": bool(ctx.more)}

